"""Langfuse environment label.

This one is a silent-data-loss trap rather than a crash. The SDK does not reject an
invalid environment — it logs "Dropping value" at warning level and carries on, so every
trace lands in `default` while the request looks perfectly healthy.

Measured before this check existed:

    LANGFUSE_ENVIRONMENT=POC  ->  turn completed, no exception
                              ->  "Propagated attribute 'environment' must be a
                                   lowercase alphanumeric string ... Dropping value."

So the rule is enforced here at boot instead, using Langfuse's own pattern:
`^(?!langfuse)[a-z0-9-_]+$` with a 40-character limit.
"""

from __future__ import annotations

import pytest

from orchestrator.config import ConfigurationError, Settings


def _settings(**overrides) -> Settings:
    base = {
        "litellm_api_key": "sk-test",
        "planner_model": "test/planner",
        "langfuse_tracing_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.parametrize(
    "label", ["dev", "staging", "prod", "production", "qa", "my-env_1", "team_a-2"]
)
def test_valid_labels_are_accepted(label: str) -> None:
    assert _settings(langfuse_environment=label).validate() == []


@pytest.mark.parametrize(
    "label",
    [
        "POC",              # uppercase
        "Dev",              # mixed case
        "langfuse-prod",    # reserved prefix
        "a" * 41,           # too long
        "prod env",         # space
        "prod.env",         # dot
    ],
)
def test_invalid_labels_are_rejected_at_boot(label: str) -> None:
    with pytest.raises(ConfigurationError, match="LANGFUSE_ENVIRONMENT"):
        _settings(langfuse_environment=label).validate()


def test_error_explains_the_silent_drop() -> None:
    """The message must say why it matters, not just that it is wrong."""
    with pytest.raises(ConfigurationError) as exc:
        _settings(langfuse_environment="POC").validate()

    message = str(exc.value)
    assert "silently dropped" in message
    assert "default" in message


def test_empty_label_is_allowed() -> None:
    """Empty means "let the SDK decide" rather than an error."""
    assert _settings(langfuse_environment="").validate() == []


def test_default_is_dev() -> None:
    """`poc` was a one-off label; dev/staging/prod is the convention."""
    assert Settings().langfuse_environment == "dev"
