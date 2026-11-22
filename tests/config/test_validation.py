"""Startup validation.

Three config changes shipped with a silent-typo risk (CANDIDATE_MAX_TARGETS rename,
MAX_DEPTH removal, the thresholds removal). This is the check that would have caught
each of them at boot instead of degrading quietly.

Split of responsibility:

* ``validate_environment`` — names in the environment that look like ours but are not
  settings. One message for both a typo and a leftover: same action either way.
* ``Settings.validate`` — values that cannot work. Errors, because serving traffic with
  them is not possible.
"""

from __future__ import annotations

import pytest

from orchestrator.config import (
    ConfigurationError,
    Settings,
    validate_environment,
)


# -- unrecognised names ----------------------------------------------------


@pytest.mark.parametrize(
    "leftover",
    [
        # renamed
        "PLANNER_MAX_TARGETS",
        "AGENT_SHORTLIST_SIZE",
        # removed
        "AGENT_SEARCH_THRESHOLD",
        "MCP_SEARCH_THRESHOLD",
        "MERGE_MODEL",
        "INVOCATION_STRATEGY",
    ],
)
def test_every_retired_name_is_still_flagged(leftover: str) -> None:
    """Prefix matching replaces the old explicit table, so nothing falls through."""
    warnings = validate_environment({leftover: "x"})

    assert len(warnings) == 1
    assert leftover in warnings[0]
    assert "not a known setting" in warnings[0]


def test_max_depth_is_the_known_gap_in_prefix_matching() -> None:
    """Documented limitation, not an oversight.

    ``MAX_DEPTH`` was ours, but the only prefix that would catch it is a bare ``MAX_``,
    which also flags ``MAX_OPEN_FILES``, ``MAX_RETRIES``, ``MAX_CONNECTIONS`` and
    ``MAX_WORKERS`` — variables the platform and other tools inject. An alarm that fires
    on every boot gets ignored, so the over-match is the worse trade.

    Harm is low: ``MAX_DEPTH`` is read by nothing, so a stale line changes no behaviour.
    """
    assert validate_environment({"MAX_DEPTH": "2"}) == []


def test_bare_max_prefix_is_not_owned() -> None:
    """Guards the decision above: adding 'MAX_' would break this test deliberately."""
    from orchestrator.config import _OWNED_PREFIXES

    assert "MAX_" not in _OWNED_PREFIXES


def test_unknown_name_with_our_prefix_is_flagged() -> None:
    warnings = validate_environment({"PLANNER_MODLE": "typo"})

    assert warnings and "PLANNER_MODLE" in warnings[0]
    assert "not a known setting" in warnings[0]


def test_unrelated_variables_are_ignored() -> None:
    """The process shares its environment; only names we own are our business."""
    warnings = validate_environment(
        {"PATH": "/usr/bin", "HOME": "/root", "OPENAI_API_KEY": "sk-x", "LANG": "C"}
    )
    assert warnings == []


def test_known_names_produce_no_warnings() -> None:
    warnings = validate_environment(
        {"PLANNER_MODEL": "m", "LITELLM_API_KEY": "k", "GATE_MODEL": "g"}
    )
    assert warnings == []


# -- values that cannot work ----------------------------------------------


def _settings(**overrides) -> Settings:
    base = {
        "litellm_api_key": "sk-test",
        "planner_model": "test/planner",
        # Tracing closed by default so unrelated assertions see a clean warning list.
        "langfuse_tracing_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_valid_settings_pass() -> None:
    assert _settings().validate() == []


def test_missing_gateway_key_is_fatal() -> None:
    with pytest.raises(ConfigurationError, match="LITELLM_API_KEY"):
        _settings(litellm_api_key="").validate()


def test_missing_planner_model_is_fatal() -> None:
    with pytest.raises(ConfigurationError, match="PLANNER_MODEL"):
        _settings(planner_model="").validate()


def test_gate_enabled_without_any_model_is_fatal() -> None:
    """Gate falls back to the planner, so both being empty is the only broken case."""
    with pytest.raises(ConfigurationError):
        _settings(planner_model="", coverage_gate_enabled=True).validate()


def test_postgres_backend_without_dsn_is_fatal() -> None:
    with pytest.raises(ConfigurationError, match="POSTGRES_DSN"):
        _settings(checkpoint_backend="postgres").validate()


def test_query_cap_below_the_fan_out_limit_warns() -> None:
    """Each query makes one sub-question findable; a lower cap drops questions.

    Measured: with 3 queries and 4 allowed tasks, "…and what is a chasen?" was never
    searched and its answer was missing from a four-question turn.
    """
    warnings = _settings(query_rewrite_max_queries=3, max_agents_per_request=4).validate()

    assert any("QUERY_REWRITE_MAX_QUERIES" in w for w in warnings), warnings
    assert _settings(query_rewrite_max_queries=4, max_agents_per_request=4).validate() == []
    # Nothing is dropped when rewriting is off.
    assert _settings(
        query_rewrite_enabled=False, query_rewrite_max_queries=1, max_agents_per_request=4
    ).validate() == []


def test_unknown_auth_mode_is_fatal() -> None:
    with pytest.raises(ConfigurationError, match="AUTH_MODE"):
        _settings(auth_mode="oauth3").validate()


def test_entra_without_tenant_is_fatal() -> None:
    with pytest.raises(ConfigurationError, match="ENTRA_TENANT_ID"):
        _settings(auth_mode="entra").validate()


def test_entra_with_tenant_passes() -> None:
    assert _settings(auth_mode="entra", entra_tenant_id="tenant-1").validate() == []


def test_unsupported_protocol_is_fatal() -> None:
    with pytest.raises(ConfigurationError, match="PROTOCOLS"):
        _settings(protocols=("a2a", "grpc")).validate()


def test_tracing_without_keys_is_a_warning_not_an_error() -> None:
    warnings = _settings(langfuse_tracing_enabled=True).validate()

    assert any("untraced" in w for w in warnings)
    # Still bootable: tracing is optional by design.
    assert _settings(langfuse_tracing_enabled=False).validate() == []


# -- parsing ---------------------------------------------------------------


def test_non_numeric_setting_fails_at_load_not_at_request(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_TOP_K", "eight")
    with pytest.raises(ConfigurationError, match="RETRIEVAL_TOP_K"):
        Settings.from_env()


def test_zero_or_negative_count_fails_at_load(monkeypatch) -> None:
    monkeypatch.setenv("MAX_AGENTS_PER_REQUEST", "0")
    with pytest.raises(ConfigurationError, match="MAX_AGENTS_PER_REQUEST"):
        Settings.from_env()


def test_non_numeric_float_fails_at_load(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_TIMEOUT_S", "sixty")
    with pytest.raises(ConfigurationError, match="REQUEST_TIMEOUT_S"):
        Settings.from_env()
