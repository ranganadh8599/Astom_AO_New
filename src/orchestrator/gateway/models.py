"""Wire models for what the gateway returns.

LiteLLM re-serves a curated A2A card, so the orchestrator never talks to an agent
directly — it reads cards from ``/a2a/{agent_id}/.well-known/agent-card.json`` on the
gateway and invokes through the same host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


def _get(data: Mapping[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in data and data[name] not in (None, ""):
            return data[name]
    return default


# First-person capability negative: "I do not have the specific address",
# "we can't provide that", "I am unable to find". Deliberately narrow — it must not fire
# on a real answer that happens to contain "do not", e.g. "do not exceed 40 hours".
_DECLINE_RE = re.compile(
    r"\b(?:i|we)\s+(?:do\s+not|don't|does\s+not|cannot|can't|am\s+unable|are\s+unable|"
    r"am\s+not\s+able|are\s+not\s+able)\s+"
    r"(?:have|cover|provide|know|find|access|share|disclose|answer)\b"
)


def _as_score(value: Any) -> float:
    """Coerce a relevance score, tolerating strings, None and absent fields."""
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class Skill:
    id: str = ""
    name: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Skill":
        tags = data.get("tags") or ()
        if isinstance(tags, str):
            tags = (tags,)
        return cls(
            id=str(_get(data, "id", "skill_id")),
            name=str(_get(data, "name")),
            description=str(_get(data, "description")),
            tags=tuple(str(tag) for tag in tags),
        )

    def search_text(self) -> str:
        return " ".join((self.id, self.name, self.description, " ".join(self.tags)))


@dataclass(frozen=True)
class AgentCard:
    """The A2A card as served by LiteLLM, plus the fields worth reasoning over."""

    name: str = ""
    description: str = ""
    url: str = ""
    version: str = ""
    protocol_version: str = ""
    organization: str = ""
    skills: tuple[Skill, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentCard":
        provider = data.get("provider") or {}
        skills = data.get("skills") or ()
        return cls(
            name=str(_get(data, "name")),
            description=str(_get(data, "description")),
            url=str(_get(data, "url")),
            version=str(_get(data, "version")),
            protocol_version=str(_get(data, "protocolVersion", "protocol_version")),
            organization=str(provider.get("organization", "")) if isinstance(provider, Mapping) else "",
            skills=tuple(Skill.from_dict(skill) for skill in skills if isinstance(skill, Mapping)),
            raw=dict(data),
        )


@dataclass(frozen=True)
class Target:
    """One routable target, always reached through LiteLLM.

    ``protocol="a2a"`` is a registered agent (``/v1/agents``), ``protocol="mcp"`` is a
    single tool exposed by an MCP server registered on the gateway
    (``/mcp-rest/tools/*``). The planner sees both in one list.
    """

    agent_id: str
    agent_name: str
    description: str = ""
    url: str = ""
    protocol_version: str = ""
    skills: tuple[Skill, ...] = ()
    card: AgentCard | None = None
    protocol: str = "a2a"
    server_id: str = ""
    server_name: str = ""
    tool_name: str = ""
    # Relevance from the gateway's search, when this record came from retrieval.
    # 0.0 when listed rather than searched.
    search_score: float = 0.0
    input_schema: Mapping[str, Any] = field(default_factory=dict, repr=False)
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "Target":
        card_params = data.get("agent_card_params") or {}
        card = AgentCard.from_dict(card_params) if isinstance(card_params, Mapping) and card_params else None
        return cls(
            agent_id=str(_get(data, "agent_id", "id")),
            agent_name=str(_get(data, "agent_name", "name")),
            description=str(_get(data, "description")) or (card.description if card else ""),
            url=str(_get(data, "url")) or (card.url if card else ""),
            protocol_version=(card.protocol_version if card else ""),
            skills=card.skills if card else (),
            card=card,
            protocol="a2a",
            # /v1/agents?query= adds this; plain listing has no score.
            search_score=_as_score(data.get("search_score")),
            raw=dict(data),
        )

    @classmethod
    def from_mcp_tool(
        cls,
        server_id: str,
        server_name: str,
        tool: Mapping[str, Any],
    ) -> "Target":
        name = str(_get(tool, "name", "tool_name")).strip()
        # LiteLLM prefixes tools with the server name ("places_api-getPlaces"); only add
        # the prefix when the proxy did not.
        display = name if server_name and name.startswith(f"{server_name}") else (
            f"{server_name}-{name}" if server_name and name else name
        )
        schema = _get(tool, "inputSchema", "input_schema", "parameters", "schema", default={})
        return cls(
            agent_id=f"mcp:{server_id}:{name}",
            agent_name=display,
            description=str(_get(tool, "description")),
            protocol="mcp",
            server_id=server_id,
            server_name=server_name,
            tool_name=name,
            input_schema=schema if isinstance(schema, Mapping) else {},
            raw=dict(tool),
        )

    @classmethod
    def from_mcp_search_hit(
        cls,
        hit: Mapping[str, Any],
        *,
        server_id: str,
        server_name: str,
    ) -> "Target":
        """Build a record from an ``mcp_tool_search`` result.

        Search returns the *prefixed* name (``field_ops-get_asset_status``) while a
        per-server listing returns the bare one (``get_asset_status``). The prefix is
        stripped so both paths produce the same ``agent_id`` — otherwise a retrieved
        tool would not resolve when the executor looks it up.
        """
        raw_name = str(_get(hit, "name", "tool_name")).strip()
        tool_name = raw_name
        if server_name and raw_name.startswith(f"{server_name}-"):
            tool_name = raw_name[len(server_name) + 1 :]

        schema = _get(hit, "inputSchema", "input_schema", "parameters", "schema", default={})
        return cls(
            agent_id=f"mcp:{server_id}:{tool_name}",
            agent_name=raw_name,
            description=str(_get(hit, "description")),
            protocol="mcp",
            server_id=server_id,
            server_name=server_name,
            tool_name=tool_name,
            # mcp_tool_search returns a cosine similarity per hit.
            search_score=_as_score(hit.get("score")),
            input_schema=schema if isinstance(schema, Mapping) else {},
            raw=dict(hit),
        )

    @classmethod
    def from_model(cls, model: str, description: str = "") -> "Target":
        """A LiteLLM model exposed as a routable target.

        Gives a model the same shape as an agent or MCP tool, so the planner chooses
        between them without knowing the protocol differs.
        """
        return cls(
            agent_id=f"model:{model}",
            agent_name=model,
            description=description,
            protocol="model",
            tool_name=model,
        )

    def with_card(self, card: AgentCard) -> "Target":
        return Target(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            description=self.description or card.description,
            url=self.url or card.url,
            protocol_version=card.protocol_version or self.protocol_version,
            skills=card.skills or self.skills,
            card=card,
            protocol=self.protocol,
            server_id=self.server_id,
            server_name=self.server_name,
            tool_name=self.tool_name,
            search_score=self.search_score,
            input_schema=self.input_schema,
            raw=self.raw,
        )

    @property
    def is_mcp(self) -> bool:
        return self.protocol == "mcp"

    @property
    def is_model(self) -> bool:
        return self.protocol == "model"

    def declined(self, text: str, markers: tuple[str, ...]) -> bool:
        """Whether this response is the target declining rather than answering.

        Only meaningful for model targets: an LLM asked outside its remit tends to
        *explain* that it cannot help, which reads as a confident answer. Marking it
        failed lets merge say so, instead of passing a refusal through as content.

        Two layers, because exact substrings proved too brittle — "I do not have the
        specific address" slipped past a list containing "I do not have specific":

        1. Configured ``markers``, matched as substrings (cheap, explicit, overridable).
        2. A first-person capability-negative pattern: ``I/we`` + ``do not/don't/cannot/
           can't/am unable`` + ``have/cover/provide/know/find``. Catches the paraphrases
           a marker list will always miss.

        Still heuristic. A model can decline without any of these words; the reliable
        answer is a sentinel prefix the target is instructed to emit.
        """
        lowered = (text or "").lower()
        if not lowered:
            return False
        if any(marker.lower() in lowered for marker in markers if marker):
            return True
        return bool(_DECLINE_RE.search(lowered))

    @property
    def required_arguments(self) -> tuple[str, ...]:
        required = self.input_schema.get("required") or ()
        return tuple(str(item) for item in required) if isinstance(required, (list, tuple)) else ()

    @property
    def argument_names(self) -> tuple[str, ...]:
        properties = self.input_schema.get("properties") or {}
        return tuple(str(key) for key in properties) if isinstance(properties, Mapping) else ()

    def missing_arguments(self, arguments: Mapping[str, Any] | None) -> tuple[str, ...]:
        """Required arguments the planner did not supply.

        The planner fills arguments; this only validates them against the tool's own
        schema so a call is never made with a knowingly incomplete object.
        """
        supplied = arguments or {}
        return tuple(name for name in self.required_arguments if not str(supplied.get(name, "")).strip())

    def search_text(self) -> str:
        parts = [self.agent_name, self.description, self.server_name, self.tool_name]
        parts.extend(skill.search_text() for skill in self.skills)
        parts.extend(self.argument_names)
        return " ".join(part for part in parts if part)

    def summary(self) -> str:
        """Compact one-liner for the planner prompt."""
        if self.is_mcp:
            args = ", ".join(self.argument_names) or "none"
            return (
                f"- {self.agent_name} [mcp, server={self.server_name or self.server_id}]: "
                f"{self.description} | arguments: {args}"
            )
        if self.is_model:
            return f"- {self.agent_name} [model]: {self.description}"
        skills = ", ".join(skill.name or skill.id for skill in self.skills if skill.name or skill.id)
        detail = f" | skills: {skills}" if skills else ""
        return f"- {self.agent_name} [a2a]: {self.description}{detail}"


@dataclass(frozen=True)
class InvocationResult:
    agent_id: str
    agent_name: str
    instruction: str
    ok: bool
    text: str = ""
    error: str = ""
    http_status: int = 0
    latency_ms: int = 0
    protocol: str = "a2a"
    tool_name: str = ""

    def to_state(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "instruction": self.instruction,
            "ok": self.ok,
            "text": self.text,
            "error": self.error,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "protocol": self.protocol,
            "tool_name": self.tool_name,
        }
