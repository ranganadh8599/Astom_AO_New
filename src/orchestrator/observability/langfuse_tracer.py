"""Langfuse tracing, isolated from the rest of the orchestrator.

Two rules matter here:

1. **One trace per conversation.** Every observation is created with an explicit
   ``trace_context={"trace_id": ...}``, using the id derived from the conversation.
   If an OpenTelemetry context is ever lost (fan-out, background task, restart), the
   SDK still attaches the span to the same trace instead of opening a new one.
2. **Tracing can never break a request.** The SDK is imported lazily and every call is
   guarded, so a missing package, bad keys or an unreachable Langfuse just means "no
   spans".

Targets the Langfuse v4 server API. Works with the Python SDK v4 and v5: the span
factory and the attribute propagation helper are both resolved at runtime.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Iterator, Mapping, Protocol

from orchestrator.config import Settings
from orchestrator.observability.trace_context import TraceContext

log = logging.getLogger(__name__)

try:  # Langfuse SDK v4+
    from langfuse import propagate_attributes as _propagate_attributes
except Exception:  # pragma: no cover - only when the extra is not installed
    _propagate_attributes = None


class Tracer(Protocol):
    """The small surface the orchestrator depends on."""

    enabled: bool

    def turn(
        self,
        trace: TraceContext,
        *,
        name: str,
        session_id: str = "",
        user_id: str = "",
        input: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any: ...

    def span(
        self,
        name: str,
        *,
        trace: TraceContext | None = None,
        input: Any = None,
        output: Any = None,
        metadata: Mapping[str, Any] | None = None,
        as_type: str = "span",
        model: str = "",
    ) -> Any: ...

    def flush(self) -> None: ...


@contextlib.contextmanager
def _nothing() -> Iterator[None]:
    yield None


class NullTracer:
    """Used by tests and whenever Langfuse is not configured."""

    enabled = False

    def turn(self, trace: TraceContext, **_: Any) -> Any:
        return _nothing()

    def span(self, name: str, **_: Any) -> Any:
        return _nothing()

    def flush(self) -> None:
        return None


def update(span: Any, **fields: Any) -> None:
    """Best-effort span update; never raises."""
    if span is None:
        return
    try:
        span.update(**fields)
    except Exception:  # pragma: no cover - tracing must not fail a request
        log.debug("langfuse span update failed", exc_info=True)


class LangfuseTracer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None
        self._unavailable = False
        self.enabled = settings.langfuse_enabled

    # -- client -----------------------------------------------------------
    def _get_client(self) -> Any:
        if self._client is not None or self._unavailable:
            return self._client
        try:
            from langfuse import Langfuse

            kwargs: dict[str, Any] = {
                "public_key": self._settings.langfuse_public_key,
                "secret_key": self._settings.langfuse_secret_key,
                "tracing_enabled": True,
            }
            if self._settings.langfuse_base_url:
                kwargs["base_url"] = self._settings.langfuse_base_url
            try:
                self._client = Langfuse(**kwargs)
            except TypeError:
                # SDK v4 called the parameter ``host``.
                kwargs.pop("base_url", None)
                if self._settings.langfuse_base_url:
                    kwargs["host"] = self._settings.langfuse_base_url
                self._client = Langfuse(**kwargs)
        except Exception as exc:
            self._unavailable = True
            self.enabled = False
            log.warning("langfuse tracing disabled: %s", exc)
        return self._client

    def _start(self, client: Any, **kwargs: Any) -> Any:
        trace_context = kwargs.pop("trace_context", None)
        observation = getattr(client, "start_as_current_observation", None)
        if observation is not None:
            return observation(trace_context=trace_context, **kwargs)
        # Python SDK v4.0 shipped the span-named factory.
        return client.start_as_current_span(trace_context=trace_context, **kwargs)

    # -- API --------------------------------------------------------------
    @contextlib.contextmanager
    def turn(
        self,
        trace: TraceContext,
        *,
        name: str,
        session_id: str = "",
        user_id: str = "",
        input: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Iterator[Any]:
        client = self._get_client() if self.enabled else None
        if client is None:
            yield None
            return

        attributes: dict[str, Any] = {
            "session_id": session_id or None,
            "user_id": user_id or None,
            "trace_name": self._settings.langfuse_trace_name,
            "environment": self._settings.langfuse_environment,
            "tags": ["orchestrator"],
            "metadata": dict(metadata or {}) or None,
        }
        attributes = {key: value for key, value in attributes.items() if value is not None}

        with _attributes(**attributes):
            with self._start(
                client,
                name=name,
                as_type="span",
                input=input,
                metadata=dict(metadata or {}) or None,
                trace_context={"trace_id": trace.trace_id},
            ) as span:
                try:
                    yield span
                except Exception as exc:
                    update(span, level="ERROR", status_message=str(exc))
                    raise

    @contextlib.contextmanager
    def span(
        self,
        name: str,
        *,
        trace: TraceContext | None = None,
        input: Any = None,
        output: Any = None,
        metadata: Mapping[str, Any] | None = None,
        as_type: str = "span",
        model: str = "",
    ) -> Iterator[Any]:
        client = self._get_client() if self.enabled else None
        if client is None:
            yield None
            return

        kwargs: dict[str, Any] = {
            "name": name,
            "as_type": as_type,
            "input": input,
            "metadata": dict(metadata or {}) or None,
            "trace_context": {"trace_id": trace.trace_id} if trace else None,
        }
        if model:
            kwargs["model"] = model
        with self._start(client, **kwargs) as span:
            update(span, output=output)
            yield span

    def flush(self) -> None:
        if not self.enabled:
            return
        client = self._get_client()
        if client is None:
            return
        try:
            client.flush()
        except Exception:  # pragma: no cover
            log.debug("langfuse flush failed", exc_info=True)


def _attributes(**kwargs: Any) -> Any:
    if _propagate_attributes is None:
        return _nothing()
    try:
        return _propagate_attributes(**kwargs)
    except Exception:  # pragma: no cover - older SDK signature
        log.debug("langfuse attribute propagation unavailable", exc_info=True)
        return _nothing()


def build_tracer(settings: Settings) -> Tracer:
    if settings.langfuse_enabled:
        return LangfuseTracer(settings)
    return NullTracer()
