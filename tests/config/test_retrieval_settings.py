"""Settings added with query building and resilient search, plus the gate rename."""

from __future__ import annotations

import pytest

from orchestrator.config import ConfigurationError, Settings, validate_environment


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> Settings:
    # Unit tests must not read the developer's `.env`: `from_env()` loads it and, because
    # these tests delete the variables first, a real .env value would reappear and win.
    monkeypatch.setattr("orchestrator.config.load_dotenv", lambda *a, **k: None)
    for name in (
        "COVERAGE_GATE_ENABLED", "RELEVANCE_GATE_ENABLED", "QUERY_REWRITE_ENABLED",
        "QUERY_REWRITE_MODEL", "QUERY_REWRITE_MAX_QUERIES", "SEARCH_RETRIES",
        "SEARCH_RETRY_BACKOFF_S", "GATE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return Settings.from_env()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _env(monkeypatch)

    assert s.query_rewrite_enabled is True
    assert s.query_rewrite_max_queries == 3
    assert s.search_retries == 1
    assert s.coverage_gate_enabled is True


def test_new_names_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _env(
        monkeypatch,
        QUERY_REWRITE_ENABLED="false",
        QUERY_REWRITE_MAX_QUERIES="2",
        SEARCH_RETRIES="0",
        SEARCH_RETRY_BACKOFF_S="0.5",
    )

    assert (s.query_rewrite_enabled, s.query_rewrite_max_queries) == (False, 2)
    assert (s.search_retries, s.search_retry_backoff_s) == (0, 0.5)


def test_legacy_gate_name_still_works_and_the_new_one_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _env(monkeypatch, RELEVANCE_GATE_ENABLED="false").coverage_gate_enabled is False
    both = _env(monkeypatch, RELEVANCE_GATE_ENABLED="false", COVERAGE_GATE_ENABLED="true")
    assert both.coverage_gate_enabled is True


def test_rewrite_model_defaults_to_the_gate_model(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _env(monkeypatch, GATE_MODEL="small/model")
    assert s.effective_rewrite_model == "small/model"
    assert _env(monkeypatch, GATE_MODEL="small/model", QUERY_REWRITE_MODEL="other").effective_rewrite_model == "other"


@pytest.mark.parametrize(
    "overrides",
    [{"query_rewrite_max_queries": 0}, {"search_retries": -1}, {"search_retry_backoff_s": -0.1}],
)
def test_invalid_values_fail_at_startup(overrides: dict) -> None:
    settings = Settings(litellm_api_key="sk-x", planner_model="m", **overrides)
    with pytest.raises(ConfigurationError):
        settings.validate()


def test_the_new_names_are_known_so_they_are_not_flagged_as_typos() -> None:
    env = {
        "QUERY_REWRITE_ENABLED": "true", "QUERY_REWRITE_MODEL": "m",
        "QUERY_REWRITE_MAX_QUERIES": "3", "SEARCH_RETRIES": "1",
        "SEARCH_RETRY_BACKOFF_S": "0.25", "COVERAGE_GATE_ENABLED": "true",
    }
    assert validate_environment(env) == []
    assert validate_environment({"QUERY_REWRITE_ENABELD": "true"})  # a typo is still caught
