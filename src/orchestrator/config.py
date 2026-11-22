"""Runtime configuration, read once from the environment.

Everything that differs between your laptop, the POC cluster and production lives here
so no other module touches ``os.environ``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

_DEFAULT_CARD_SUFFIX = "/.well-known/agent-card.json"

# Langfuse's rule for the environment label: lowercase, alphanumerics plus - and _,
# must not start with "langfuse", at most 40 characters. An invalid value is *dropped*
# by the SDK rather than rejected, so traces silently land in `default` — validate here.
_LANGFUSE_ENV_RE = re.compile(r"^(?!langfuse)[a-z0-9-_]+$")

DEFAULT_DENIAL_MESSAGE = (
    "I can't carry out that change. This orchestrator is read-only: it answers "
    "questions and never creates, updates, deletes or approves anything, and it has "
    "no approval workflow to hand the request to. Please use the owning system "
    "(or raise a normal service request) and I'll happily answer questions about "
    "the current state."
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = _env(name)
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_semicolon_list(name: str) -> tuple[str, ...]:
    """Split on ``;`` instead of ``,``.

    For values whose items contain commas — a target description like
    "company name, office locations" is one entry, not two. Using ``,`` produced
    phantom targets from fragments of a description.
    """
    raw = _env(name)
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(";") if item.strip())


class ConfigurationError(RuntimeError):
    """Settings that cannot work. Raised at load time, never mid-request."""


# Attributes of ``UserContext`` that make sense as a trace identifier. Kept here rather
# than imported from ``auth`` because ``auth`` imports this module. ``tests/config/test_config.py``
# asserts every name is a real field, so the duplication cannot drift.
# ``scopes`` (a tuple) and ``claims`` (a dict) are deliberately excluded: stringifying
# either produces noise, not an identifier.
USER_CONTEXT_FIELDS: tuple[str, ...] = ("oid", "name", "email", "roles", "tenant_id")


# Every environment variable the orchestrator reads. A name outside this set that looks
# like one of ours is a typo, and silently ignoring it is how a rename becomes an outage.
KNOWN_ENV = frozenset(
    {
        "LITELLM_BASE_URL", "LITELLM_API_KEY", "LITELLM_ADMIN_KEY",
        "PLANNER_MODEL", "PLANNER_TEMPERATURE", "GATE_MODEL", "MODEL_PREFLIGHT_ENABLED",
        "CANDIDATE_MAX_TARGETS", "RETRIEVAL_ENABLED", "RETRIEVAL_TOP_K",
        "COVERAGE_GATE_ENABLED", "RELEVANCE_GATE_ENABLED",  # legacy name, still accepted
        "QUERY_REWRITE_ENABLED", "QUERY_REWRITE_MODEL", "QUERY_REWRITE_MAX_QUERIES",
        "SEARCH_RETRIES", "SEARCH_RETRY_BACKOFF_S",
        "MAX_AGENTS_PER_REQUEST", "REQUEST_TIMEOUT_S",
        "CARD_CACHE_TTL_S", "SEARCH_UNAVAILABLE_TTL_S", "PROTOCOLS", "MCP_SERVERS",
        "MODEL_TARGETS", "REFUSAL_MARKERS",
        "READ_ONLY_MODE", "READ_ONLY_DENIAL_MESSAGE",
        "SMALLTALK_ENABLED", "SMALLTALK_CAPABILITIES_REPLY",
        "CHECKPOINT_BACKEND", "POSTGRES_DSN", "POSTGRES_AUTO_CREATE", "HISTORY_MAX_TURNS",
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL",
        "LANGFUSE_HOST", "LANGFUSE_TRACING_ENABLED", "LANGFUSE_TRACE_NAME",
        "LANGFUSE_ENVIRONMENT", "LANGFUSE_USER_ID_FIELD", "TRACE_PER_CONVERSATION",
        "AUTH_MODE", "ORCH_SHARED_KEY", "SHARED_KEY_ROLES",
        "USER_ID_HEADER", "USER_EMAIL_HEADER", "USER_NAME_HEADER",
        "ENTRA_TENANT_ID", "ENTRA_AUDIENCE", "ENTRA_ISSUER",
        "ENTRA_JWKS_URI", "ENTRA_REQUIRED_ROLE", "DEV_JWT_SECRET", "DEV_JWT_ISSUER",
        "DEV_JWT_AUDIENCE",
    }
)

# Prefixes we own. Anything matching these but absent from KNOWN_ENV is reported, so a
# typo or a leftover setting cannot linger unnoticed. This replaces a hand-maintained
# list of retired names: that table had to grow with every rename, and got the job done
# only for names we remembered to add.
_OWNED_PREFIXES = (
    "LITELLM_", "PLANNER_", "CANDIDATE_", "RETRIEVAL_", "RELEVANCE_", "COVERAGE_", "GATE_",
    "QUERY_REWRITE_", "SEARCH_RETRY", "SEARCH_RETRIES",
    "MAX_AGENTS_", "LANGFUSE_", "TRACE_", "AUTH_", "ENTRA_", "DEV_JWT_",
    "CHECKPOINT_", "MCP_", "PROTOCOLS", "READ_ONLY_", "CARD_CACHE_",
    "SEARCH_UNAVAILABLE_", "REQUEST_TIMEOUT_", "INVOCATION_", "AGENT_", "MERGE_",
)


def _env_float_checked(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name}={raw!r} is not a number") from exc


def _env_int_checked(name: str, default: int, *, minimum: int = 1) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name}={raw!r} is not an integer") from exc
    if value < minimum:
        raise ConfigurationError(f"{name}={value} must be >= {minimum}")
    return value


def validate_environment(environ: Mapping[str, str] | None = None) -> list[str]:
    """Report settings that look like ours but are not recognised.

    One class only: the name matches one of our prefixes and is absent from
    ``KNOWN_ENV``, which means either a typo or a leftover from a removed setting. Both
    want the same action — delete or correct the line — so one message covers both.

    Deliberately *not* a hand-maintained list of retired names: that table had to grow
    with every rename and only helped for names somebody remembered to add. Prefix
    matching is derived from the settings themselves, so a rename or removal is caught
    automatically the moment ``KNOWN_ENV`` changes.

    Warnings rather than errors: this process shares an environment with the gateway,
    the shell and anything else the platform injects, and refusing to boot over an
    unrelated variable would be worse than the risk it removes.
    """
    env = environ if environ is not None else os.environ
    return [
        f"{name} is not a known setting; it is being ignored"
        for name in sorted(env)
        if name not in KNOWN_ENV and name.startswith(_OWNED_PREFIXES)
    ]


def _parse_env_value(raw: str) -> str:
    """Strip surrounding quotes, then a trailing inline comment.

    Handles the three forms people actually write:

        KEY=value            -> value
        KEY=value  # note    -> value
        KEY="value # kept"   -> value # kept

    A bare ``#`` inside an unquoted value is kept (a value can legitimately contain
    one); only a ``#`` preceded by whitespace starts a comment.
    """
    value = raw.strip()

    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]

    if value and value[0] in "\"'":
        # Quoted value with a trailing comment: "value"  # note
        quote = value[0]
        closing = value.find(quote, 1)
        if closing != -1:
            return value[1:closing]

    for marker in (" #", "\t#"):
        index = value.find(marker)
        if index != -1:
            value = value[:index]
            break
    if value.startswith("#"):
        # KEY=#comment — the whole value is a comment.
        value = ""
    return value.strip()


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader; never overwrites variables already set in the environment."""
    env_path = path or Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = _parse_env_value(value)


@dataclass(frozen=True)
class Settings:
    # --- LiteLLM gateway -------------------------------------------------
    litellm_base_url: str = "http://localhost:4000"
    # Virtual key used by *this* orchestrator. Never the master key.
    litellm_api_key: str = ""
    # Admin key, only needed by the onboarding tooling (not by the orchestrator).
    litellm_admin_key: str = ""

    # The planner model is the only way a request is decomposed and routed: there is
    # no heuristic fallback, so this must name a model the gateway serves.
    planner_model: str = ""
    planner_temperature: float = 0.0

    # --- Model targets ---------------------------------------------------
    # LiteLLM models exposed as routable targets. Empty = only A2A agents and MCP tools
    # are routable. An entry here makes a model discoverable and composable alongside
    # them; nothing is inferred from /v1/models, which would list hundreds of models.
    #
    # Format: semicolon-separated "model|description" pairs in MODEL_TARGETS. Ex:- model|desc;model2|desc2
    # descriptions routinely contain commas.
    model_targets: tuple[str, ...] = ()
    # Text a target uses to decline. Matched case-insensitively; a match marks the
    # invocation as failed so merge reports it honestly instead of passing a refusal off
    # as an answer. Applies to model targets only.
    #
    # **This is heuristic, not reliable.** It catches phrasings seen in practice, and a
    # model can always decline in words that are not on the list — "I do not have
    # specific details" and "I'm unable to provide" both slipped through before being
    # added. The robust fix is to instruct the target to begin a refusal with a fixed
    # sentinel (e.g. `OUT_OF_SCOPE:`) and match that instead; string matching is what
    # works without changing the target's prompt.
    refusal_markers: tuple[str, ...] = (
        "beyond scope",
        "outside my scope",
        "not within my scope",
        "outside the scope",
        # capability negatives
        "i don't cover",
        "i do not cover",
        "i don't have information",
        "i do not have information",
        "i don't have specific",
        "i do not have specific",
        "i don't have details",
        "i do not have details",
        "i'm unable to provide",
        "i am unable to provide",
        "unable to provide",
        "i'm not able to",
        "i am not able to",
        "cannot provide",
        "can't provide",
        "i don't have access to",
        "i do not have access to",
        "no information about",
        "i'm not sure about",
        "i am not sure about",
    )

    # --- Routing limits --------------------------------------------------
    # Retrieval: ask the gateway to rank agents/tools against the query. Off falls back
    # to listing the catalogue (useful for debugging a search surface).
    retrieval_enabled: bool = True
    # How many targets retrieval asks for per protocol.
    retrieval_top_k: int = 8
    # Query building: before searching, turn the message into standalone search queries.
    # A follow-up ("and in 2016?") is rewritten using the recent conversation, and a
    # message with several questions becomes one query per question (results are merged
    # by reciprocal rank fusion), so no topic is averaged away in a single embedding.
    # Only runs when the message needs it; any failure falls back to the raw message.
    # Empty model = reuse the gate model.
    query_rewrite_enabled: bool = True
    query_rewrite_model: str = ""
    # Same ceiling as `max_agents_per_request`: one query per question, or the extra
    # questions are never searched (see the warning in `validate`).
    query_rewrite_max_queries: int = 4
    # A transient search failure (timeout, 429, 5xx) is retried this many times, then the
    # turn falls back to listing *for this turn only*. Only "search is not configured"
    # switches search off for `search_unavailable_ttl_s`.
    search_retries: int = 1
    search_retry_backoff_s: float = 0.25
    # Coverage gate: one LLM call asking "can any target answer this?" before the
    # planner is asked "which one?". Measured to be the difference between rejecting
    # 2/7 and 7/7 irrelevant queries, and it is the *only* coverage decision: there is
    # deliberately no relevance-score threshold in front of it, because measured such a
    # threshold changed no outcome and could hide a valid target.
    # Empty model = reuse `planner_model`.
    coverage_gate_enabled: bool = True
    gate_model: str = ""
    # Ceiling on candidates handed to the coverage gate, per protocol when listing.
    # Named for the gate because the gate consumes them: the planner only sees what the
    # gate passes through, which is always fewer.
    candidate_max_targets: int = 40
    # Ceiling on how many tasks execute in one turn. The planner may propose more; the
    # extras are dropped. Caps parallel fan-out, not the candidate list.
    # Probe the configured models against the gateway at boot. A rejected model is fatal
    # (wrong name or not permitted); a transient failure is a warning.
    model_preflight_enabled: bool = True
    max_agents_per_request: int = 4
    request_timeout_s: float = 60.0
    # How long a fetched agent catalogue may be reused before it is refetched.
    card_cache_ttl_s: float = 300.0
    # How long a search surface that reported "not configured" stays marked unavailable.
    # Separate from the catalogue TTL because they are tuned for opposite goals: list
    # freshness versus not re-probing a broken surface on every turn.
    search_unavailable_ttl_s: float = 60.0

    # --- Protocols -------------------------------------------------------
    # Nothing to configure: on startup the orchestrator asks the gateway what is
    # registered and routes to whatever it finds. Both surfaces are always probed;
    # an empty or forbidden one simply contributes nothing.
    # `protocols` exists only to *narrow* discovery (e.g. tests); leave it alone.
    protocols: tuple[str, ...] = ("a2a", "mcp")
    # Optional MCP server allowlist. Empty = every server the key can see.
    mcp_servers: tuple[str, ...] = ()

    # How to call an A2A agent through the gateway. Not exposed as an env var: exactly
    # one shape works on current proxies, and offering three in .env invited people to
    # pick a broken one. Kept as a field so tests and the onboarding CLI can drive the
    # alternatives, and so a future proxy change is one-line.
    #   "jsonrpc" -> POST /a2a/{agent_id}  JSON-RPC message/send  (the only working shape)
    #   "simple"  -> POST /a2a/{agent_id}  {"message": {...}}     (400 on this gateway)
    #   "chat"    -> POST /v1/chat/completions model="a2a/{name}" (403: resolves against
    #                the model list, not the agent registry)
    invocation_strategy: str = "jsonrpc"

    # --- Small talk ------------------------------------------------------
    # Greetings, thanks and "what can you do?" are answered by the orchestrator with a
    # fixed reply: no target can cover them, and a model call per "hi" is waste. Set
    # false to disable the fast path and let the gate decline them instead.
    smalltalk_enabled: bool = True
    # Optional override for the capabilities answer. Blank uses the built-in text.
    smalltalk_capabilities_reply: str = ""

    # --- Read-only policy (no human in the loop) -------------------------
    # The request intent ("read" or "mutation") is classified by the planner model, not
    # by local pattern matching. read_only_mode tells the planner to refuse a mutation;
    # the hard guarantee is that only read-only capabilities are registered.
    read_only_mode: bool = True
    read_only_denial_message: str = DEFAULT_DENIAL_MESSAGE

    # --- Memory ----------------------------------------------------------
    # memory   -> LangGraph InMemorySaver, one thread per conversation (POC default)
    # postgres -> AsyncPostgresSaver, survives restarts (phase 2; needs the extra)
    checkpoint_backend: str = "memory"
    postgres_dsn: str = ""
    # Create the DSN's database and LangGraph's tables on first boot. Tables are always
    # created by ``saver.setup()``; this flag additionally covers the *database*, which
    # otherwise fails with 'database "<name>" does not exist' before any table exists.
    # Set false where the role has no CREATEDB (managed Postgres, locked-down prod).
    postgres_auto_create: bool = True
    history_max_turns: int = 6

    # --- Tracing (Langfuse) ----------------------------------------------
    # Langfuse v4 server. The Python SDK (v4/v5) talks to it over OTLP.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""
    langfuse_tracing_enabled: bool = True
    langfuse_trace_name: str = "a2a-orchestrator"
    # Langfuse environment label. Filter dimension only: it does not change behaviour,
    # but an invalid value is silently dropped by the SDK and the trace lands in
    # `default` instead — so it is validated at startup (see validate()).
    # Convention: dev | staging | prod (Langfuse's own examples use `production`).
    langfuse_environment: str = "dev"
    langfuse_user_id_field: str = "oid"
    # One Langfuse trace per conversation: the trace id is derived from the
    # conversation id, so every turn adds spans to the same trace.
    trace_per_conversation: bool = True

    # --- Identity --------------------------------------------------------
    # "dev"        -> locally signed HS256 tokens shaped like Entra tokens
    # "entra"      -> validate against the tenant's JWKS
    # "shared_key" -> LibreChat integration: one shared key authenticates the caller,
    #                 and the user is identified by a plain header. See
    #                 docs/sso-integration.md before choosing this.
    # "none"       -> no auth (local experiments only; refuses to start in production)
    auth_mode: str = "dev"

    # --- Shared-key mode (LibreChat) -------------------------------------
    # The key LibreChat sends as `apiKey: '${ORCH_KEY}'`.
    orch_shared_key: str = ""
    # Identity headers, filled from LibreChat templates:
    #   {{LIBRECHAT_USER_ID}}, {{LIBRECHAT_USER_EMAIL}}, {{LIBRECHAT_USER_NAME}}
    # These are NOT signed. They are trusted only because the shared key is secret and
    # because nothing but LibreChat holds it. Anyone with the key can impersonate any
    # user — that is the accepted trade, recorded in docs/sso-integration.md.
    user_id_header: str = "x-librechat-user-id"
    user_email_header: str = "x-librechat-user-email"
    user_name_header: str = "x-librechat-user-name"
    # Role(s) attached to every shared-key caller. Purely a claim-shape filler: it keeps
    # UserContext identical to what an Entra token produces, so switching AUTH_MODE does
    # not touch downstream code.
    #
    # It grants and denies nothing. There is no role gate in shared-key mode (the
    # validator has no `required_role`), and no code outside `auth/` reads `UserContext`
    # roles, so every caller is served the same way whatever this is set to. Role
    # enforcement exists only in `entra` and `dev` mode, via ENTRA_REQUIRED_ROLE.
    #
    # Blank is NOT "no role gate": _env_list treats an empty value as unset and returns
    # the default, so this cannot be turned off from the environment.
    shared_key_roles: tuple[str, ...] = ("AgentUser",)

    entra_tenant_id: str = ""
    entra_audience: str = ""  # the orchestrator's own api:// app ID URI
    entra_issuer: str = ""  # optional override; derived from tenant when empty
    entra_jwks_uri: str = ""
    # The only working role gate: a caller whose token lacks this role gets a 401.
    # Honoured by EntraValidator and DevValidator; ignored in shared_key/none mode.
    entra_required_role: str = ""  # optional coarse gate, e.g. "AgentUser"
    dev_jwt_secret: str = "dev-only-not-a-secret-change-me-32bytes-minimum"
    dev_jwt_issuer: str = "http://localhost/dev-idp"
    dev_jwt_audience: str = "api://orchestrator"

    # --- Transport -------------------------------------------------------
    card_path_suffix: str = _DEFAULT_CARD_SUFFIX
    forwarded_header_allowlist: tuple[str, ...] = field(
        default_factory=lambda: (
            "traceparent",
            "tracestate",
            "x-litellm-trace-id",
            "x-request-id",
        )
    )

    @property
    def agent_card_suffix(self) -> str:
        return self.card_path_suffix or _DEFAULT_CARD_SUFFIX

    @property
    def effective_issuer(self) -> str:
        if self.entra_issuer:
            return self.entra_issuer
        if self.entra_tenant_id:
            return f"https://login.microsoftonline.com/{self.entra_tenant_id}/v2.0"
        return self.dev_jwt_issuer

    @property
    def effective_jwks_uri(self) -> str:
        if self.entra_jwks_uri:
            return self.entra_jwks_uri
        if self.entra_tenant_id:
            return (
                "https://login.microsoftonline.com/"
                f"{self.entra_tenant_id}/discovery/v2.0/keys"
            )
        return ""

    @property
    def can_plan_with_model(self) -> bool:
        return bool(self.planner_model and self.litellm_api_key)

    @property
    def model_target_descriptions(self) -> dict[str, str]:
        """Parse ``MODEL_TARGETS`` into ``{model: description}``.

        Entries are ``model|description``, comma-separated. A pipe separates the fields
        because descriptions routinely contain colons, commas and slashes — ``"="``
        produced silently wrong targets when the description had punctuation.

        An entry without a pipe still becomes a target with a generic description: a
        target the operator asked for must not vanish because of a formatting slip.
        """
        parsed: dict[str, str] = {}
        for entry in self.model_targets:
            model, _, description = entry.partition("|")
            model = model.strip()
            if not model:
                continue
            parsed[model] = description.strip() or f"Model {model}, served by the gateway."
        return parsed

    @property
    def can_gate_with_model(self) -> bool:
        return bool(self.effective_gate_model and self.litellm_api_key)

    @property
    def effective_gate_model(self) -> str:
        return self.gate_model or self.planner_model

    @property
    def effective_rewrite_model(self) -> str:
        return self.query_rewrite_model or self.effective_gate_model

    @property
    def can_rewrite_queries(self) -> bool:
        return bool(
            self.query_rewrite_enabled
            and self.retrieval_enabled
            and self.effective_rewrite_model
            and self.litellm_api_key
        )

    @property
    def mcp_enabled(self) -> bool:
        return "mcp" in self.protocols

    @property
    def a2a_enabled(self) -> bool:
        return "a2a" in self.protocols

    @property
    def langfuse_enabled(self) -> bool:
        return bool(
            self.langfuse_tracing_enabled
            and self.langfuse_public_key
            and self.langfuse_secret_key
        )

    def validate(self) -> list[str]:
        """Report settings that cannot work. Returns warnings; raises on hard errors.

        Called at startup so a misconfiguration fails immediately, not on the first
        request. Everything here is a condition the process cannot serve traffic with —
        anything merely suspicious is a warning.
        """
        warnings: list[str] = []

        if not self.litellm_api_key:
            raise ConfigurationError(
                "LITELLM_API_KEY is not set: every call goes through the gateway"
            )
        if not self.planner_model:
            raise ConfigurationError(
                "PLANNER_MODEL is not set: routing happens only through the planner and "
                "there is no local fallback"
            )
        if self.coverage_gate_enabled and not self.effective_gate_model:
            raise ConfigurationError(
                "COVERAGE_GATE_ENABLED=true but neither GATE_MODEL nor PLANNER_MODEL is "
                "set; disable the gate or name a model"
            )
        if self.query_rewrite_max_queries < 1:
            raise ConfigurationError("QUERY_REWRITE_MAX_QUERIES must be at least 1")
        if self.query_rewrite_enabled and self.query_rewrite_max_queries < self.max_agents_per_request:
            # Each search query is what makes one sub-question findable, so a lower cap
            # than the fan-out limit silently drops questions. Measured: with 3 queries
            # and 4 allowed tasks, "…and what is a chasen?" was never searched and the
            # answer omitted it entirely.
            warnings.append(
                f"QUERY_REWRITE_MAX_QUERIES={self.query_rewrite_max_queries} is below "
                f"MAX_AGENTS_PER_REQUEST={self.max_agents_per_request}: a message with "
                "more questions than the query cap will leave the extra ones unsearched"
            )
        if self.search_retries < 0 or self.search_retry_backoff_s < 0:
            raise ConfigurationError("SEARCH_RETRIES and SEARCH_RETRY_BACKOFF_S cannot be negative")
        if self.checkpoint_backend == "postgres" and not self.postgres_dsn:
            raise ConfigurationError(
                "CHECKPOINT_BACKEND=postgres requires POSTGRES_DSN"
            )
        if self.auth_mode not in ("dev", "entra", "none", "shared_key"):
            raise ConfigurationError(
                f"AUTH_MODE={self.auth_mode!r} is not one of dev, entra, shared_key, none"
            )
        if self.auth_mode == "entra" and not (self.entra_tenant_id or self.entra_jwks_uri):
            raise ConfigurationError(
                "AUTH_MODE=entra requires ENTRA_TENANT_ID or ENTRA_JWKS_URI"
            )
        if self.auth_mode == "shared_key":
            if not self.orch_shared_key:
                raise ConfigurationError(
                    "AUTH_MODE=shared_key requires ORCH_SHARED_KEY — the value LibreChat "
                    "sends as apiKey: '${ORCH_KEY}'"
                )
            if len(self.orch_shared_key) < 32:
                raise ConfigurationError(
                    "ORCH_SHARED_KEY must be at least 32 characters: it is the only "
                    "thing separating callers from every user's identity"
                )
            warnings.append(
                "AUTH_MODE=shared_key: the user is identified by an UNSIGNED header. "
                "Anyone holding ORCH_SHARED_KEY can impersonate any user. Acceptable "
                "only when LibreChat (and its key store) are trusted; see "
                "docs/sso-integration.md for the token-forwarding alternative."
            )

        # Unknown protocols are named rather than silently ignored.
        unknown = [p for p in self.protocols if p not in ("a2a", "mcp")]
        if unknown:
            raise ConfigurationError(
                f"PROTOCOLS contains unsupported value(s) {unknown}; use a2a and/or mcp"
            )

        # The A2A wire shape is not configurable from the environment: only `jsonrpc`
        # works on current gateways. Validation stays so a caller constructing Settings
        # programmatically still gets told when it asks for something broken.
        if self.invocation_strategy not in ("jsonrpc", "simple", "chat"):
            raise ConfigurationError(
                f"invocation_strategy={self.invocation_strategy!r} is not one of "
                "jsonrpc, simple, chat"
            )
        if self.invocation_strategy != "jsonrpc":
            warnings.append(
                f"invocation_strategy={self.invocation_strategy} is a legacy A2A shape; "
                "current gateways expect 'jsonrpc' and will reject it"
            )

        if self.langfuse_tracing_enabled and not self.langfuse_enabled:
            warnings.append(
                "LANGFUSE_TRACING_ENABLED=true but LANGFUSE_PUBLIC_KEY/SECRET_KEY are "
                "missing; running untraced"
            )
        if self.langfuse_enabled and not self.langfuse_base_url:
            warnings.append(
                "LANGFUSE_BASE_URL is empty; the SDK will fall back to its default host"
            )

        # The SDK *drops* an invalid environment label instead of raising, so a typo
        # sends every trace to `default` with no visible failure. Catch it at boot.
        env_label = self.langfuse_environment
        if env_label:
            if not _LANGFUSE_ENV_RE.match(env_label) or len(env_label) > 40:
                raise ConfigurationError(
                    f"LANGFUSE_ENVIRONMENT={env_label!r} is invalid. Langfuse requires "
                    "lowercase letters, digits, '-' or '_' (max 40 chars, must not start "
                    "with 'langfuse'). An invalid value is silently dropped, which would "
                    "put every trace in the 'default' environment."
                )

        # LANGFUSE_USER_ID_FIELD is a getattr() target on UserContext, so a name that is
        # not an attribute resolves to empty and the code quietly falls back to `oid`.
        # Attribution then looks plausible but is wrong, which is worse than failing.
        if self.langfuse_user_id_field not in USER_CONTEXT_FIELDS:
            warnings.append(
                f"LANGFUSE_USER_ID_FIELD={self.langfuse_user_id_field!r} is not an "
                f"attribute of UserContext; traces will fall back to 'oid'. Valid: "
                + ", ".join(USER_CONTEXT_FIELDS)
            )

        return warnings

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            litellm_base_url=_env("LITELLM_BASE_URL", "http://localhost:4000").rstrip("/"),
            litellm_api_key=_env("LITELLM_API_KEY"),
            litellm_admin_key=_env("LITELLM_ADMIN_KEY"),
            planner_model=_env("PLANNER_MODEL"),
            planner_temperature=_env_float_checked("PLANNER_TEMPERATURE", 0.0),
            model_targets=_env_semicolon_list("MODEL_TARGETS"),
            refusal_markers=_env_list("REFUSAL_MARKERS", (
                "beyond scope",
                "outside my scope",
                "not within my scope",
                "outside the scope",
                "i don't cover",
                "i do not cover",
                "i don't have information",
                "i do not have information",
                "i don't have specific",
                "i do not have specific",
                "i don't have details",
                "i do not have details",
                "i'm unable to provide",
                "i am unable to provide",
                "unable to provide",
                "i'm not able to",
                "i am not able to",
                "cannot provide",
                "can't provide",
                "i don't have access to",
                "i do not have access to",
                "no information about",
                "i'm not sure about",
                "i am not sure about",
            )),
            candidate_max_targets=_env_int_checked("CANDIDATE_MAX_TARGETS", 40),
            retrieval_enabled=_env_bool("RETRIEVAL_ENABLED", True),
            retrieval_top_k=_env_int_checked("RETRIEVAL_TOP_K", 8),
            coverage_gate_enabled=_env_bool(
                "COVERAGE_GATE_ENABLED", _env_bool("RELEVANCE_GATE_ENABLED", True)
            ),
            query_rewrite_enabled=_env_bool("QUERY_REWRITE_ENABLED", True),
            query_rewrite_model=_env("QUERY_REWRITE_MODEL"),
            query_rewrite_max_queries=_env_int_checked("QUERY_REWRITE_MAX_QUERIES", 3),
            search_retries=_env_int_checked("SEARCH_RETRIES", 1, minimum=0),
            search_retry_backoff_s=_env_float_checked("SEARCH_RETRY_BACKOFF_S", 0.25),
            gate_model=_env("GATE_MODEL"),
            model_preflight_enabled=_env_bool("MODEL_PREFLIGHT_ENABLED", True),
            max_agents_per_request=_env_int_checked("MAX_AGENTS_PER_REQUEST", 4),
            request_timeout_s=_env_float_checked("REQUEST_TIMEOUT_S", 60.0),
            card_cache_ttl_s=_env_float_checked("CARD_CACHE_TTL_S", 300.0),
            search_unavailable_ttl_s=_env_float_checked("SEARCH_UNAVAILABLE_TTL_S", 60.0),
            protocols=_env_list("PROTOCOLS", ("a2a", "mcp")),
            mcp_servers=_env_list("MCP_SERVERS"),
            invocation_strategy="jsonrpc",
            smalltalk_enabled=_env_bool("SMALLTALK_ENABLED", True),
            smalltalk_capabilities_reply=_env("SMALLTALK_CAPABILITIES_REPLY"),
            read_only_mode=_env_bool("READ_ONLY_MODE", True),
            read_only_denial_message=_env("READ_ONLY_DENIAL_MESSAGE")
            or DEFAULT_DENIAL_MESSAGE,
            checkpoint_backend=_env("CHECKPOINT_BACKEND", "memory").lower(),
            postgres_dsn=_env("POSTGRES_DSN"),
            postgres_auto_create=_env_bool("POSTGRES_AUTO_CREATE", True),
            history_max_turns=_env_int_checked("HISTORY_MAX_TURNS", 6),
            langfuse_public_key=_env("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=_env("LANGFUSE_SECRET_KEY"),
            langfuse_base_url=_env("LANGFUSE_BASE_URL") or _env("LANGFUSE_HOST"),
            langfuse_tracing_enabled=_env_bool("LANGFUSE_TRACING_ENABLED", True),
            langfuse_trace_name=_env("LANGFUSE_TRACE_NAME", "a2a-orchestrator"),
            langfuse_environment=_env("LANGFUSE_ENVIRONMENT", "dev"),
            langfuse_user_id_field=_env("LANGFUSE_USER_ID_FIELD", "oid"),
            trace_per_conversation=_env_bool("TRACE_PER_CONVERSATION", True),
            auth_mode=_env("AUTH_MODE", "dev").lower(),
            orch_shared_key=_env("ORCH_SHARED_KEY"),
            user_id_header=_env("USER_ID_HEADER", "x-librechat-user-id").lower(),
            user_email_header=_env("USER_EMAIL_HEADER", "x-librechat-user-email").lower(),
            user_name_header=_env("USER_NAME_HEADER", "x-librechat-user-name").lower(),
            shared_key_roles=_env_list("SHARED_KEY_ROLES", ("AgentUser",)),
            entra_tenant_id=_env("ENTRA_TENANT_ID"),
            entra_audience=_env("ENTRA_AUDIENCE"),
            entra_issuer=_env("ENTRA_ISSUER"),
            entra_jwks_uri=_env("ENTRA_JWKS_URI"),
            entra_required_role=_env("ENTRA_REQUIRED_ROLE"),
            dev_jwt_secret=_env("DEV_JWT_SECRET", "dev-only-not-a-secret"),
            dev_jwt_issuer=_env("DEV_JWT_ISSUER", "http://localhost/dev-idp"),
            dev_jwt_audience=_env("DEV_JWT_AUDIENCE", "api://orchestrator"),
        )
