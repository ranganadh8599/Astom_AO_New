"""``python -m orchestrator`` entry point.

The behaviour that matters is the event loop choice: psycopg's async connections cannot
use Windows' ProactorEventLoop, and uvicorn hard-codes exactly that when asked to run
itself. These tests pin the contract without starting a server.
"""

from __future__ import annotations

import asyncio
import sys

import orchestrator.__main__ as entry


def test_selector_loop_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert entry.loop_factory() is asyncio.SelectorEventLoop


def test_default_loop_elsewhere(monkeypatch) -> None:
    """Linux and containers keep the interpreter default — no override imposed."""
    monkeypatch.setattr(sys, "platform", "linux")

    assert entry.loop_factory() is None


class _FakeRunner:
    """Stands in for asyncio.Runner: records the factory and runs nothing."""

    instances: list["_FakeRunner"] = []

    def __init__(self, *, loop_factory=None) -> None:
        self.loop_factory = loop_factory
        self.ran = False
        _FakeRunner.instances.append(self)

    def __enter__(self) -> "_FakeRunner":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def run(self, coro) -> None:
        self.ran = True
        coro.close()


class _FakeServer:
    def __init__(self, config) -> None:
        self.config = config

    async def serve(self) -> None:  # pragma: no cover - never awaited
        raise AssertionError("serve() must not run in tests")


def _patch(monkeypatch) -> None:
    _FakeRunner.instances.clear()
    monkeypatch.setattr(entry.uvicorn, "Server", _FakeServer)
    monkeypatch.setattr(entry.asyncio, "Runner", _FakeRunner)


def test_main_passes_bind_options_and_no_loop_override_on_linux(monkeypatch) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")

    assert entry.main(["--host", "127.0.0.1", "--port", "8123"]) == 0

    runner = _FakeRunner.instances[-1]
    assert runner.loop_factory is None
    assert runner.ran


def test_main_uses_selector_on_windows(monkeypatch) -> None:
    """The reason this module exists: an explicit factory, not a policy."""
    _patch(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")

    assert entry.main([]) == 0

    assert _FakeRunner.instances[-1].loop_factory is asyncio.SelectorEventLoop


def test_main_returns_zero_after_serving(monkeypatch) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")

    assert entry.main(["--log-level", "debug"]) == 0


def test_defaults_match_the_documented_command() -> None:
    args = entry.build_parser().parse_args([])

    assert (args.host, args.port) == ("0.0.0.0", 8000)
    assert args.log_level == "info"


def test_reload_flag_is_absent() -> None:
    """A --reload that silently re-breaks psycopg would be worse than no flag."""
    options = {action.dest for action in entry.build_parser()._actions}

    assert "reload" not in options
