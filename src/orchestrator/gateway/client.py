"""The only way the orchestrator talks to the outside world.

Every method goes through LiteLLM. The client holds one virtual key, scoped to the agents
and MCP servers this orchestrator may use, and attaches trace/lineage headers to every
request.

Both protocols terminate at the gateway:

* **A2A** — ``GET /v1/agents`` to discover, ``POST /a2a/{agent_id}`` to invoke.
* **MCP** — ``GET /v1/mcp/server`` + ``GET /mcp-rest/tools/list`` to discover,
  ``POST /mcp-rest/tools/call`` to invoke.

The orchestrator never talks to an agent or an MCP server directly.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Mapping, Sequence

import httpx

from orchestrator.config import Settings
from orchestrator.observability.langfuse_tracer import NullTracer, Tracer, update as update_span
from orchestrator.observability.trace_context import Lineage, TraceContext, call_headers
from orchestrator.gateway.models import AgentCard, InvocationResult, Target


class GatewayError(RuntimeError):
    """A call to LiteLLM failed. Message is safe to log; never contains the key."""

    def __init__(self, message: str, *, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _snippet(text: str, limit: int = 500) -> str:
    text = " ".join(text.split())
    return text[:limit]


def _collect_text(node: Any) -> list[str]:
    """Pull every text fragment out of a response of unknown vintage.

    Handles A2A 0.3 (``result.parts[]``), A2A 1.x (``result.message.parts[]``), MCP tool
    results (``content[].text``) and task/status envelopes, without a per-version parser.
    """
    found: list[str] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == "text" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_collect_text(value))
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
        for item in node:
            found.extend(_collect_text(item))
    return found


def _as_list(data: Any, keys: Sequence[str]) -> list[Mapping[str, Any]]:
    if isinstance(data, Mapping):
        for key in keys:
            value = data.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return [item for item in value if isinstance(item, Mapping)]
        return []
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        return [item for item in data if isinstance(item, Mapping)]
    return []


def _server_identity(server: Mapping[str, Any]) -> tuple[str, str]:
    """Return ``(server_id, server_name)`` from a ``/v1/mcp/server`` row."""
    name = str(
        server.get("server_name")
        or server.get("name")
        or server.get("alias")
        or server.get("server_id")
        or ""
    )
    server_id = str(server.get("server_id") or server.get("id") or name)
    return server_id, name


def _is_search_unavailable(exc: "GatewayError") -> bool:
    """True when a search failure means "not configured", not "broken".

    Two known shapes:

    * ``400 agent_search_not_configured`` — no ``agent_search_embedding_model``.
    * ``403 forbidden / mcp_tool_search requires mcp_tool_search_enabled`` — the key
      has not opted into tool search.
    """
    haystack = f"{exc} {exc.body}".lower()
    return (
        "agent_search_not_configured" in haystack
        or "mcp_tool_search_enabled" in haystack
        or ("forbidden" in haystack and "search" in haystack)
        or "unknown tool" in haystack
        or "tool not found" in haystack
    )


def _mcp_search_hits(data: Any) -> list[Mapping[str, Any]] | None:
    """Extract the JSON tool list an ``mcp_tool_search`` call returns as text content.

    Returns ``None`` when the tool reported an error (e.g. the embedding call failed),
    so the caller falls back to listing instead of pretending there are no tools.
    """
    if not isinstance(data, Mapping):
        return None
    if data.get("isError") or data.get("error"):
        return None

    texts = _collect_text(data)
    for text in texts:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, Mapping)]
        if isinstance(parsed, Mapping) and isinstance(parsed.get("tools"), list):
            return [item for item in parsed["tools"] if isinstance(item, Mapping)]
    return None


def _resolve_server(
    raw_name: str, server_map: Mapping[str, tuple[str, str]]
) -> tuple[str, str]:
    """Resolve which MCP server a prefixed tool name belongs to.

    Prefers an exact match on a known server prefix (longest first, so ``field_ops``
    wins over ``field``). Falls back to the text before the first ``-``.
    """
    lowered = raw_name.lower()
    for key in sorted(server_map, key=len, reverse=True):
        if lowered.startswith(f"{key}-"):
            return server_map[key]
    hint = raw_name.split("-", 1)[0] if "-" in raw_name else "mcp"
    return hint, hint


class LiteLLMGateway:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None
        self._tracer: Tracer = tracer or NullTracer()

    async def __aenter__(self) -> "LiteLLMGateway":
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.litellm_base_url,
                timeout=self._settings.request_timeout_s,
            )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("LiteLLMGateway used outside its async context")
        return self._client

    # -- discovery: A2A ---------------------------------------------------
    async def list_agents(self, trace: TraceContext, *, query: str = "") -> list[Target]:
        if not self._settings.a2a_enabled:
            return []
        params = {"query": query} if query else None
        with self._tracer.span(
            "litellm.a2a.list_agents",
            trace=trace,
            input={"query": query},
            metadata={"protocol": "a2a"},
        ) as span:
            data = await self._request_json("GET", "/v1/agents", trace=trace, params=params)
            records = [Target.from_api(item) for item in _as_list(data, ("data", "agents"))]
            update_span(span, output={"agents": len(records)})
            return records

    async def get_agent_card(self, agent_id: str, trace: TraceContext) -> AgentCard:
        path = f"/a2a/{agent_id}{self._settings.agent_card_suffix}"
        data = await self._request_json("GET", path, trace=trace)
        if not isinstance(data, Mapping):
            raise GatewayError(f"agent card for {agent_id} is not an object")
        return AgentCard.from_dict(data)

    # -- discovery: MCP ---------------------------------------------------
    async def list_mcp_servers(self, trace: TraceContext) -> list[Mapping[str, Any]]:
        data = await self._request_json("GET", "/v1/mcp/server", trace=trace)
        return _as_list(data, ("data", "servers", "mcp_servers"))

    async def list_mcp_tools(self, trace: TraceContext) -> list[Target]:
        """Every MCP tool this key can see, as routable records.

        Discovery degrades quietly: a proxy without MCP, or a key without MCP
        permission, yields an empty list and A2A still works.
        """
        if not self._settings.mcp_enabled:
            return []

        with self._tracer.span(
            "litellm.mcp.list_tools",
            trace=trace,
            metadata={"protocol": "mcp"},
        ) as span:
            records: list[Target] = []
            errors: list[str] = []

            try:
                servers = await self.list_mcp_servers(trace)
            except GatewayError as exc:
                servers = []
                errors.append(str(exc))

            wanted = {item.lower() for item in self._settings.mcp_servers}
            selected: list[tuple[str, str]] = []
            for server in servers:
                server_id, server_name = _server_identity(server)
                if not server_id:
                    continue
                if wanted and server_id.lower() not in wanted and server_name.lower() not in wanted:
                    continue
                selected.append((server_id, server_name))

            if selected:
                results = await asyncio.gather(
                    *(
                        self._tools_for_server(server_id, server_name, trace)
                        for server_id, server_name in selected
                    ),
                    return_exceptions=True,
                )
                for item in results:
                    if isinstance(item, list):
                        records.extend(item)
                    elif isinstance(item, GatewayError):
                        errors.append(str(item))

            if not records:
                # Older proxies only expose the flat list; tools carry mcp_info.
                try:
                    tools = await self._mcp_tool_list(trace)
                except GatewayError as exc:
                    tools = []
                    errors.append(str(exc))
                for tool in tools:
                    info = tool.get("mcp_info") if isinstance(tool.get("mcp_info"), Mapping) else {}
                    server_name = str(info.get("server_name") or info.get("server_id") or "mcp")
                    server_id = str(info.get("server_id") or server_name)
                    if wanted and server_id.lower() not in wanted and server_name.lower() not in wanted:
                        continue
                    records.append(Target.from_mcp_tool(server_id, server_name, tool))

            if not records and errors:
                # Nothing usable *and* something failed: report it rather than looking
                # like a gateway that simply has no MCP servers. The catalog treats this
                # as "surface unavailable" and A2A keeps working.
                update_span(span, level="ERROR", status_message=errors[0])
                raise GatewayError(errors[0])

            update_span(span, output={"tools": len(records), "servers": len(selected)})
            return records

    async def _tools_for_server(
        self, server_id: str, server_name: str, trace: TraceContext
    ) -> list[Target]:
        tools = await self._mcp_tool_list(trace, server_id=server_id)
        return [Target.from_mcp_tool(server_id, server_name, tool) for tool in tools]

    async def _mcp_tool_list(
        self, trace: TraceContext, *, server_id: str = ""
    ) -> list[Mapping[str, Any]]:
        params = {"server_id": server_id} if server_id else None
        data = await self._request_json(
            "GET", "/mcp-rest/tools/list", trace=trace, params=params
        )
        return _as_list(data, ("tools", "data"))

    # -- retrieval (semantic search over the gateway) ----------------------
    async def search_agents(
        self, query: str, trace: TraceContext, *, top_k: int = 8
    ) -> list[Target] | None:
        """Rank A2A agents against the user's query via ``GET /v1/agents?query=``.

        Returns ``None`` when the gateway has no ``litellm_settings.agent_search_
        embedding_model`` configured — that is a deployment choice, not an error, and
        the caller falls back to listing.
        """
        if not self._settings.a2a_enabled or not query.strip():
            return None
        params = {"query": query, "top_k": top_k}
        with self._tracer.span(
            "litellm.a2a.search_agents",
            trace=trace,
            input={"query": query, "top_k": top_k},
            metadata={"protocol": "a2a", "mode": "search"},
        ) as span:
            try:
                data = await self._request_json(
                    "GET", "/v1/agents", trace=trace, params=params
                )
            except GatewayError as exc:
                if _is_search_unavailable(exc):
                    update_span(span, output={"mode": "unavailable"})
                    return None
                update_span(span, level="ERROR", status_message=str(exc))
                raise
            records = [Target.from_api(item) for item in _as_list(data, ("data", "agents"))]
            update_span(span, output={"agents": len(records)})
            return records

    async def search_mcp_tools(
        self, query: str, trace: TraceContext, *, top_k: int = 8
    ) -> list[Target] | None:
        """Rank MCP tools against the query via the gateway's ``mcp_tool_search`` tool.

        Returns ``None`` when the key does not have ``mcp_tool_search_enabled``, or when
        semantic ranking is unavailable — the caller falls back to listing.
        """
        if not self._settings.mcp_enabled or not query.strip():
            return None
        body = {
            "name": "mcp_tool_search",
            "arguments": {"query": query, "top_k": top_k},
        }
        with self._tracer.span(
            "litellm.mcp.search_tools",
            trace=trace,
            input={"query": query, "top_k": top_k},
            metadata={"protocol": "mcp", "mode": "search"},
        ) as span:
            try:
                data = await self._request_json(
                    "POST", "/mcp-rest/tools/call", trace=trace, json_body=body
                )
            except GatewayError as exc:
                if _is_search_unavailable(exc):
                    update_span(span, output={"mode": "unavailable"})
                    return None
                update_span(span, level="ERROR", status_message=str(exc))
                raise

            hits = _mcp_search_hits(data)
            if hits is None:
                update_span(span, output={"mode": "error"})
                return None

            server_map = await self._mcp_server_index(trace)
            records: list[Target] = []
            for hit in hits:
                raw_name = str(hit.get("name") or "")
                server_id, server_name = _resolve_server(raw_name, server_map)
                records.append(
                    Target.from_mcp_search_hit(
                        hit, server_id=server_id, server_name=server_name
                    )
                )
            update_span(span, output={"tools": len(records)})
            return records

    async def _mcp_server_index(self, trace: TraceContext) -> dict[str, tuple[str, str]]:
        """Map server name/id -> (server_id, server_name) for prefixed tool names."""
        index: dict[str, tuple[str, str]] = {}
        try:
            servers = await self.list_mcp_servers(trace)
        except GatewayError:
            return index
        for server in servers:
            server_id, server_name = _server_identity(server)
            if not server_id:
                continue
            index[server_id.lower()] = (server_id, server_name)
            if server_name:
                index[server_name.lower()] = (server_id, server_name)
        return index

    # -- model preflight --------------------------------------------------
    async def list_models(self, trace: TraceContext) -> list[str]:
        """Model ids the gateway advertises. A hint, not an authority.

        A virtual key may carry a wildcard pattern (``openai/*``) that permits models
        absent from this list, so absence here is never proof a model is unusable.
        """
        data = await self._request_json("GET", "/v1/models", trace=trace)
        entries = _as_list(data, ("data", "models"))
        return [str(item.get("id")) for item in entries if item.get("id")]

    async def probe_model(
        self, model: str, trace: TraceContext
    ) -> tuple[str, str]:
        """Ask the gateway to actually serve one token with ``model``.

        Returns ``(verdict, detail)`` where verdict is:

        * ``"ok"`` — the gateway answered.
        * ``"rejected"`` — 404/403: the model does not exist or this key may not use it.
          This is a configuration error, not an outage.
        * ``"unavailable"`` — anything else (timeout, 5xx, connection). Transient; must
          not block startup, or a briefly restarting gateway becomes a failed deploy.
        """
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1,
            "temperature": 0,
        }
        try:
            await self._request_json(
                "POST", "/v1/chat/completions", trace=trace, json_body=body
            )
            return "ok", ""
        except GatewayError as exc:
            detail = _snippet(exc.body) if exc.body else str(exc)
            if exc.status in (403, 404):
                return "rejected", detail
            return "unavailable", detail or str(exc)

    # -- invocation -------------------------------------------------------
    async def invoke(
        self,
        agent: Target,
        instruction: str,
        *,
        trace: TraceContext,
        lineage: Lineage,
        arguments: Mapping[str, Any] | None = None,
    ) -> InvocationResult:
        if agent.is_mcp:
            return await self._invoke_mcp(
                agent, instruction, trace=trace, lineage=lineage, arguments=arguments
            )
        if agent.is_model:
            return await self._invoke_model(agent, instruction, trace=trace, lineage=lineage)
        return await self._invoke_a2a(agent, instruction, trace=trace, lineage=lineage)

    async def _invoke_model(
        self,
        agent: Target,
        instruction: str,
        *,
        trace: TraceContext,
        lineage: Lineage,
    ) -> InvocationResult:
        """Invoke a LiteLLM model as a target, via the same chat endpoint the planner uses."""
        started = time.perf_counter()
        with self._tracer.span(
            f"litellm.model.invoke {agent.agent_name}",
            trace=trace,
            input={"instruction": instruction},
            as_type="generation",
            model=agent.agent_name,
            metadata={"protocol": "model"},
        ) as span:
            try:
                text = await self.complete(
                    agent.agent_name,
                    [{"role": "user", "content": instruction}],
                    trace=trace,
                    lineage=lineage,
                )
            except GatewayError as exc:
                update_span(span, level="ERROR", status_message=str(exc))
                return InvocationResult(
                    agent_id=agent.agent_id,
                    agent_name=agent.agent_name,
                    instruction=instruction,
                    ok=False,
                    error=str(exc),
                    http_status=exc.status,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    protocol="model",
                    tool_name=agent.agent_name,
                )

            elapsed = int((time.perf_counter() - started) * 1000)
            text = text.strip()
            if not text:
                update_span(span, level="WARNING", status_message="model returned no text")
                return InvocationResult(
                    agent_id=agent.agent_id,
                    agent_name=agent.agent_name,
                    instruction=instruction,
                    ok=False,
                    error="model returned no text",
                    latency_ms=elapsed,
                    protocol="model",
                    tool_name=agent.agent_name,
                )
            if agent.declined(text, self._settings.refusal_markers):
                # A refusal is not an answer. Surface it as a failure so merge reports it
                # instead of presenting "Beyond scope" as a considered response.
                update_span(span, level="WARNING", status_message="model declined")
                return InvocationResult(
                    agent_id=agent.agent_id,
                    agent_name=agent.agent_name,
                    instruction=instruction,
                    ok=False,
                    error=f"declined: {text[:160]}",
                    latency_ms=elapsed,
                    protocol="model",
                    tool_name=agent.agent_name,
                )
            update_span(span, output={"text": text})
            return InvocationResult(
                agent_id=agent.agent_id,
                agent_name=agent.agent_name,
                instruction=instruction,
                ok=True,
                text=text,
                latency_ms=elapsed,
                protocol="model",
                tool_name=agent.agent_name,
            )

    async def _invoke_a2a(
        self,
        agent: Target,
        instruction: str,
        *,
        trace: TraceContext,
        lineage: Lineage,
    ) -> InvocationResult:
        started = time.perf_counter()
        headers = call_headers(trace, lineage)
        with self._tracer.span(
            f"litellm.a2a.invoke {agent.agent_name}",
            trace=trace,
            input={"instruction": instruction},
            metadata={"protocol": "a2a", "agent_id": agent.agent_id},
        ) as span:
            try:
                payload = self._invocation_payload(agent, instruction)
                data = await self._request_json(
                    "POST",
                    payload["path"],
                    trace=trace,
                    json_body=payload["body"],
                    extra_headers=headers,
                )
                text = "\n".join(_collect_text(data)).strip()
                elapsed = int((time.perf_counter() - started) * 1000)
                if not text:
                    update_span(span, level="WARNING", status_message="agent returned no text")
                    return InvocationResult(
                        agent_id=agent.agent_id,
                        agent_name=agent.agent_name,
                        instruction=instruction,
                        ok=False,
                        error="agent returned no text",
                        latency_ms=elapsed,
                        protocol="a2a",
                    )
                update_span(span, output={"text": text})
                return InvocationResult(
                    agent_id=agent.agent_id,
                    agent_name=agent.agent_name,
                    instruction=instruction,
                    ok=True,
                    text=text,
                    latency_ms=elapsed,
                    protocol="a2a",
                )
            except GatewayError as exc:
                update_span(span, level="ERROR", status_message=str(exc))
                return InvocationResult(
                    agent_id=agent.agent_id,
                    agent_name=agent.agent_name,
                    instruction=instruction,
                    ok=False,
                    error=str(exc),
                    http_status=exc.status,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    protocol="a2a",
                )

    async def _invoke_mcp(
        self,
        agent: Target,
        instruction: str,
        *,
        trace: TraceContext,
        lineage: Lineage,
        arguments: Mapping[str, Any] | None = None,
    ) -> InvocationResult:
        started = time.perf_counter()
        headers = call_headers(trace, lineage)
        tool_args = self._mcp_arguments(arguments)
        body = {
            "server_id": agent.server_id or agent.server_name,
            "name": agent.tool_name or agent.agent_name,
            "arguments": tool_args,
        }
        with self._tracer.span(
            f"litellm.mcp.call {agent.agent_name}",
            trace=trace,
            input={"tool": body["name"], "arguments": tool_args},
            metadata={"protocol": "mcp", "server_id": body["server_id"]},
        ) as span:
            try:
                data = await self._request_json(
                    "POST",
                    "/mcp-rest/tools/call",
                    trace=trace,
                    json_body=body,
                    extra_headers=headers,
                )
                text = "\n".join(_collect_text(data)).strip()
                elapsed = int((time.perf_counter() - started) * 1000)
                failed = isinstance(data, Mapping) and bool(
                    data.get("isError") or data.get("error")
                )
                if failed or not text:
                    error = text or "mcp tool returned no text"
                    update_span(span, level="ERROR", status_message=error)
                    return InvocationResult(
                        agent_id=agent.agent_id,
                        agent_name=agent.agent_name,
                        instruction=instruction,
                        ok=False,
                        error=error,
                        latency_ms=elapsed,
                        protocol="mcp",
                        tool_name=body["name"],
                    )
                update_span(span, output={"text": text})
                return InvocationResult(
                    agent_id=agent.agent_id,
                    agent_name=agent.agent_name,
                    instruction=instruction,
                    ok=True,
                    text=text,
                    latency_ms=elapsed,
                    protocol="mcp",
                    tool_name=body["name"],
                )
            except GatewayError as exc:
                update_span(span, level="ERROR", status_message=str(exc))
                return InvocationResult(
                    agent_id=agent.agent_id,
                    agent_name=agent.agent_name,
                    instruction=instruction,
                    ok=False,
                    error=str(exc),
                    http_status=exc.status,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    protocol="mcp",
                    tool_name=body["name"],
                )

    @staticmethod
    def _mcp_arguments(arguments: Mapping[str, Any] | None) -> dict[str, Any]:
        """The planner owns argument values; the gateway sends what it decided.

        No inference happens here. If the planner missed a required argument the execute
        node has already refused the call, so this cannot silently send a guess.
        """
        return dict(arguments) if isinstance(arguments, Mapping) else {}

    def _invocation_payload(self, agent: Target, instruction: str) -> dict[str, Any]:
        strategy = self._settings.invocation_strategy
        if strategy == "chat":
            return {
                "path": "/v1/chat/completions",
                "body": {
                    "model": f"a2a/{agent.agent_name}",
                    "messages": [{"role": "user", "content": instruction}],
                },
            }
        if strategy == "jsonrpc":
            return {
                "path": f"/a2a/{agent.agent_id}",
                "body": {
                    "jsonrpc": "2.0",
                    "id": uuid.uuid4().hex,
                    "method": "message/send",
                    "params": {
                        "message": {
                            "messageId": uuid.uuid4().hex,
                            "role": "user",
                            "parts": [{"kind": "text", "text": instruction}],
                        }
                    },
                },
            }
        # "simple" — the LiteLLM proxy form documented for direct agent invocation.
        return {
            "path": f"/a2a/{agent.agent_id}",
            "body": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": instruction}],
                }
            },
        }

    # -- model calls (planner / merge) ------------------------------------
    async def complete(
        self,
        model: str,
        messages: Sequence[Mapping[str, str]],
        *,
        trace: TraceContext,
        lineage: Lineage,
        temperature: float = 0.0,
        response_format_json: bool = False,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if response_format_json:
            body["response_format"] = {"type": "json_object"}

        with self._tracer.span(
            f"litellm.chat {model}",
            trace=trace,
            input=list(messages),
            as_type="generation",
            model=model,
            metadata={"protocol": "llm"},
        ) as span:
            data = await self._request_json(
                "POST",
                "/v1/chat/completions",
                trace=trace,
                json_body=body,
                extra_headers=call_headers(trace, lineage),
            )
            choices = (data or {}).get("choices") or []
            if not choices:
                raise GatewayError("chat completion returned no choices")
            message = choices[0].get("message") or {}
            content = str(message.get("content") or "")
            usage = (data or {}).get("usage") or {}
            update_span(
                span,
                output=content,
                usage_details={
                    "input": usage.get("prompt_tokens", 0) or 0,
                    "output": usage.get("completion_tokens", 0) or 0,
                },
            )
            return content

    # -- transport --------------------------------------------------------
    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        trace: TraceContext,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Any:
        headers: dict[str, str] = {"accept": "application/json"}
        if self._settings.litellm_api_key:
            headers["authorization"] = f"Bearer {self._settings.litellm_api_key}"
        headers.update(trace.to_headers())
        if extra_headers:
            headers.update(extra_headers)

        try:
            response = await self.client.request(
                method,
                path,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise GatewayError(f"{method} {path} failed: {exc}") from exc

        if response.status_code >= 400:
            raise GatewayError(
                f"{method} {path} -> {response.status_code}",
                status=response.status_code,
                body=_snippet(response.text),
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise GatewayError(
                f"{method} {path} returned non-JSON", status=response.status_code
            ) from exc
