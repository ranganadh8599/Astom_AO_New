"""The CLI entry point.

`python -m orchestrator.admin.cli` is the only way to exercise the full pipeline without an
HTTP client: under `AUTH_MODE=dev` the API needs a minted JWT, and the CLI mints one
itself. That makes it the fastest reproduction loop for a reported answer.

It is also the only entry point that had no coverage, and it touches everything that
changed recently — auth, config validation, deferred model checks, the service lifecycle
— so these tests exist to notice when one of those moves.

Contract worth pinning:

* stdout is **only** JSON, so the output stays pipeable (`| jq`);
* diagnostics go to stderr;
* exit code 0 = completed, 1 = not completed, 2 = cannot start.
"""

from __future__ import annotations

import json

import pytest

from orchestrator.admin import cli
from orchestrator.config import Settings
from orchestrator.service import ModelCheck


@pytest.fixture
def settings(monkeypatch) -> Settings:
    base = Settings(
        litellm_base_url="http://gateway.test",
        litellm_api_key="sk-test",
        planner_model="test/planner",
        langfuse_tracing_enabled=False,
        auth_mode="dev",
        protocols=("a2a",),
    )
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: base))
    return base


class _FakeService:
    """Stands in for OrchestratorService: records calls, returns a canned result."""

    last: dict = {}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run_preflight(self):
        return ModelCheck(status="ok")

    async def run(self, message, user, session_id=""):
        from orchestrator.service import RunResult

        _FakeService.last = {"message": message, "user": user, "session_id": session_id}
        return RunResult(
            run_id="r1",
            answer="24 days",
            status="completed",
            trace_id="t" * 32,
            conversation_id=session_id,
        )


@pytest.fixture
def fake_service(monkeypatch):
    monkeypatch.setattr(cli, "OrchestratorService", _FakeService)
    return _FakeService


# -- happy path ------------------------------------------------------------


def test_prints_json_only_on_stdout(settings, fake_service, capsys) -> None:
    code = cli.main(["how many leave days?"])

    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)  # stdout must parse as JSON
    assert payload["answer"] == "24 days"


def test_mints_a_dev_token_when_none_is_supplied(settings, fake_service) -> None:
    cli.main(["anything"])

    user = fake_service.last["user"]
    assert user.is_authenticated
    assert user.oid


def test_session_id_is_forwarded(settings, fake_service) -> None:
    cli.main(["anything", "--session-id", "conv-42"])

    assert fake_service.last["session_id"] == "conv-42"


# -- failure modes ---------------------------------------------------------


def test_non_completed_run_exits_one(settings, fake_service, monkeypatch) -> None:
    async def not_completed(self, message, user, session_id=""):
        from orchestrator.service import RunResult

        return RunResult(
            run_id="r", answer="", status="failed", trace_id="t" * 32, error="boom"
        )

    monkeypatch.setattr(_FakeService, "run", not_completed)

    assert cli.main(["anything"]) == 1


def test_invalid_config_exits_two_without_running(
    settings, fake_service, monkeypatch, capsys
) -> None:
    from orchestrator.config import ConfigurationError

    def bad_validate(self):
        raise ConfigurationError("PLANNER_MODEL is not set")

    monkeypatch.setattr(Settings, "validate", bad_validate)

    assert cli.main(["anything"]) == 2
    assert "PLANNER_MODEL" in capsys.readouterr().err


def test_failed_model_check_still_runs_the_query(
    settings, fake_service, monkeypatch, capsys
) -> None:
    """A bad model name is reported but must not block a manual query."""
    async def failed_check(self):
        return ModelCheck(status="failed", error="gateway rejected model 'x'")

    monkeypatch.setattr(_FakeService, "run_preflight", failed_check)

    code = cli.main(["anything"])

    assert code == 0
    assert "rejected model" in capsys.readouterr().err


def test_entra_without_token_exits_two(settings, fake_service, monkeypatch, capsys) -> None:
    """The CLI cannot mint a token it did not issue."""
    from orchestrator import auth

    class NotDevNorNull:
        def validate(self, token):  # pragma: no cover - should not be reached
            raise AssertionError("validate must not be called without a token")

    monkeypatch.setattr(cli, "build_authenticator", lambda s: NotDevNorNull())

    assert cli.main(["anything"]) == 2
    assert "requires --token" in capsys.readouterr().err
