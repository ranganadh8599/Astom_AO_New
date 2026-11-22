"""FastAPI surface — the contract LibreChat (or any front end) calls.

Auth is enforced by one dependency on the router, so a new route cannot be added without
inheriting the check.
"""


import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from orchestrator.auth import AuthError, Authenticator, UserContext, build_authenticator
from orchestrator.config import Settings, validate_environment
from orchestrator.service import OrchestratorService
from orchestrator.observability.trace_context import LIBRECHAT_MESSAGE_ID_HEADER, SESSION_HEADER

log = logging.getLogger(__name__)


async def _background_preflight(service: OrchestratorService) -> None:
    """Run the boot checks off the startup path and report the outcome.

    Never raises: a failed check is data, not a crash. The result is surfaced through
    ``service.model_check`` (and therefore ``/health``) so a platform can alert without
    the process having to die.
    """
    try:
        check = await service.run_boot_checks()
    except Exception:  # pragma: no cover - run_boot_checks already swallows
        log.exception("preflight: unexpected failure")
        return

    if check.status == "failed":
        log.error("preflight: %s", check.error)
    for warning in check.warnings:
        log.warning("preflight: %s", warning)
    if check.status == "ok":
        log.info("preflight: configured models answered")


class OrchestrateRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str = ""
    refresh_catalog: bool = False


class OrchestrateResponse(BaseModel):
    run_id: str
    status: str
    answer: str
    error: str = ""
    trace_id: str
    conversation_id: str = ""
    denied: bool = False
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# --- OpenAI-compatible surface ------------------------------------------------
# LibreChat's custom endpoint calls `{baseURL}/chat/completions` and expects the
# OpenAI response shape. This adapts that protocol onto the orchestrator so LibreChat
# can point at us without a translation proxy in between.
class ChatMessage(BaseModel):
    role: str = "user"
    content: Any = ""


class ChatCompletionRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False
    # LibreChat sends its conversation id here as well as in the header; either works.
    conversation_id: str = ""
    user: str = ""


def _last_user_message(messages: list[ChatMessage]) -> str:
    """The orchestration layer answers one question per turn.

    Earlier turns are already in its checkpointed history, so re-sending them would
    duplicate context. Only the newest user message is new.
    """
    for message in reversed(messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "\n".join(parts).strip()
    return ""


def _orchestrator_metadata(result: Any) -> dict[str, Any]:
    """Run metadata LibreChat ignores but a direct caller may want."""
    return {
        "run_id": result.run_id,
        "status": result.status,
        "trace_id": result.trace_id,
        "denied": result.denied,
        "conversation_id": result.conversation_id,
    }


def _bearer(authorization: str = Header(default="")) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token")
    return token.strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    # Fail at boot, not on the first request. Unknown env names are warnings because
    # this process shares its environment with the platform; settings that cannot work
    # are errors.
    for message in validate_environment():
        log.warning("config: %s", message)
    for message in settings.validate():
        log.warning("config: %s", message)

    authenticator: Authenticator = build_authenticator(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service = OrchestratorService(settings)
        await service.__aenter__()
        app.state.service = service

        # Model check runs *after* boot so a slow or wrong model name cannot delay or
        # block startup. The result lands on /health, and the log carries it too.
        preflight_task: asyncio.Task | None = None
        if settings.model_preflight_enabled:
            preflight_task = asyncio.create_task(
                _background_preflight(service), name="model-preflight"
            )
        try:
            yield
        finally:
            if preflight_task is not None and not preflight_task.done():
                preflight_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await preflight_task
            await service.__aexit__(None, None, None)

    app = FastAPI(title="A2A Orchestrator", version="0.1.0", lifespan=lifespan)

    def current_user(
        request: Request, token: Annotated[str, Depends(_bearer)]
    ) -> UserContext:
        try:
            # Validators that need request headers (shared-key mode reads the user id
            # header) get them; token-based validators ignore the argument.
            return authenticator.validate(token, dict(request.headers))
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Readiness: is this instance fit to serve traffic?

        Separate from `/health` on purpose. Liveness answers "is the process alive" and
        must never fail for something a retry can fix, or the platform restarts the
        container forever. Readiness answers "should traffic reach this instance" — a
        rejected model is exactly that: alive, but every turn would fail.

        `pending` counts as ready: the check has not finished, and refusing traffic
        during normal startup would make a healthy rollout look broken.

        The checkpointer is probed here too, because a boot-time connection proves
        nothing about now: Postgres can restart underneath a running instance. Measured
        before this check existed — every turn returned 500 while `/ready` said 200.
        """
        service: OrchestratorService = request.app.state.service
        check = service.model_check
        memory = await service.memory_health.probe()

        healthy = check.serves_traffic and memory.reachable
        payload = {
            "status": "ready" if healthy else "not_ready",
            "models": check.to_dict(),
            "memory": memory.to_dict(),
        }
        return JSONResponse(status_code=200 if healthy else 503, content=payload)

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        service: OrchestratorService = request.app.state.service
        check = service.model_check
        return {
            # "ok" is liveness: the process serves requests. Model state is separate so
            # a liveness probe is never failed by something that resolves on retry.
            "status": "ok",
            "auth_mode": settings.auth_mode,
            "gateway": settings.litellm_base_url,
            "protocols": list(settings.protocols),
            "read_only": settings.read_only_mode,
            "memory": settings.checkpoint_backend,
            # Cached, never a live probe: /health must stay cheap and always 200. The
            # authoritative connectivity answer is on /ready.
            "memory_state": service.memory_health.cached().to_dict(),
            "tracing": "langfuse" if settings.langfuse_enabled else "off",
            "models": check.to_dict(),
            "planner": settings.planner_model or "NOT CONFIGURED",
            "compose_answer": "deterministic",
        }

    @app.get("/v1/agents")
    async def agents(
        request: Request,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> list[dict[str, Any]]:
        service: OrchestratorService = request.app.state.service
        records = await service.list_agents()
        return [
            {
                "agent_id": record.agent_id,
                "agent_name": record.agent_name,
                "protocol": record.protocol,
                "description": record.description,
                "skills": [skill.name or skill.id for skill in record.skills],
            }
            for record in records
        ]

    @app.get("/v1/capabilities")
    async def capabilities(
        request: Request,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> dict[str, Any]:
        """What the gateway has registered, by protocol. Nothing is configured."""
        service: OrchestratorService = request.app.state.service
        return await service.capabilities()

    @app.post("/v1/chat/completions")
    async def chat_completions(
        body: ChatCompletionRequest,
        request: Request,
        user: Annotated[UserContext, Depends(current_user)],
    ):
        """OpenAI-compatible adapter, so LibreChat can treat the orchestrator as a model.

        LibreChat requests `stream: true` for custom endpoints and parses SSE; returning
        plain JSON produces "The model provider returned an empty response". The stream
        here is honest: the orchestrator produces one complete answer, so it is emitted
        as a single content delta rather than faked token-by-token.
        """
        import time as _time
        import uuid as _uuid

        message = _last_user_message(body.messages)
        if not message:
            raise HTTPException(status_code=400, detail="no user message in request")

        # Session = the conversation. The header carries LibreChat's conversation id;
        # `body.user` carries the *user*, so it must not win here — using it as the
        # session would put every conversation of one user into a single Langfuse
        # session. Order: explicit body field, then the conversation header, then user.
        conversation_id = (
            body.conversation_id
            or request.headers.get(SESSION_HEADER, "")
            or body.user
        )
        inbound = {
            "traceparent": request.headers.get("traceparent", ""),
            "tracestate": request.headers.get("tracestate", ""),
            LIBRECHAT_MESSAGE_ID_HEADER: request.headers.get(LIBRECHAT_MESSAGE_ID_HEADER, ""),
            SESSION_HEADER: conversation_id,
        }

        service: OrchestratorService = request.app.state.service
        result = await service.run(
            message,
            user,
            session_id=conversation_id,
            inbound_headers=inbound,
        )

        text = result.answer or result.error or "No answer was produced."
        created = int(_time.time())
        completion_id = f"chatcmpl-{result.run_id or _uuid.uuid4().hex}"
        model = body.model or "a2a-orchestrator"

        if not body.stream:
            return JSONResponse(
                {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": text},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "x_orchestrator": _orchestrator_metadata(result),
                }
            )

        def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
            return "data: " + json.dumps(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
            ) + "\n\n"

        async def events():
            # Role first, then the whole answer as one delta, then the terminator.
            yield chunk({"role": "assistant", "content": ""})
            yield chunk({"content": text})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/v1/orchestrate", response_model=OrchestrateResponse)
    async def orchestrate(
        body: OrchestrateRequest,
        request: Request,
        user: Annotated[UserContext, Depends(current_user)],
    ) -> OrchestrateResponse:
        service: OrchestratorService = request.app.state.service
        # Forward everything the trace join needs. LibreChat sends its message id, from
        # which we derive the same Langfuse trace id it used, and the conversation id,
        # which becomes the Langfuse session.
        inbound = {
            "traceparent": request.headers.get("traceparent", ""),
            "tracestate": request.headers.get("tracestate", ""),
            LIBRECHAT_MESSAGE_ID_HEADER: request.headers.get(LIBRECHAT_MESSAGE_ID_HEADER, ""),
            SESSION_HEADER: request.headers.get(SESSION_HEADER, ""),
        }
        result = await service.run(
            body.message,
            user,
            session_id=body.conversation_id,
            inbound_headers=inbound,
            refresh_catalog=body.refresh_catalog,
        )
        return OrchestrateResponse(**result.to_dict())

    return app


# `uvicorn orchestrator.api.app:app` resolves this attribute lazily, so merely importing the
# module (tests, tooling, type checkers) never needs a complete environment.
_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
