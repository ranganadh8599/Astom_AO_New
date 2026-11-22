"""`.env` parsing.

This exists because a trailing inline comment on one line took down startup:

    CANDIDATE_MAX_TARGETS=40 #Cap on number of agents ...

`int("40 #Cap ...")` raised, and the failure surfaced at import of Settings rather than
at the offending line. These cases pin the three forms people actually write.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.config import Settings, _parse_env_value, load_dotenv


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("40", "40"),
        ("40 #Cap on number of agents", "40"),
        ("true  # enable it", "true"),
        ("openai/gpt-4o-mini", "openai/gpt-4o-mini"),
        ('"sk-value"  # quoted', "sk-value"),
        ("'value # kept'", "value # kept"),
        ("#comment-only", ""),
        ("", ""),
        ("  40  ", "40"),
        # A URL fragment or path may contain '#' but not as a comment marker.
        ("https://example.com/a#b", "https://example.com/a#b"),
    ],
)
def test_parse_env_value(raw: str, expected: str) -> None:
    assert _parse_env_value(raw) == expected


def test_inline_comment_does_not_break_numeric_settings(tmp_path: Path) -> None:
    """The exact regression: a commented line must still produce a valid int."""
    env = tmp_path / ".env"
    env.write_text(
        "candidate_max_targets=40 #Cap on number of agents\n"
        "RETRIEVAL_TOP_K=8  # per protocol\n"
        "COVERAGE_GATE_ENABLED=true # on\n",
        encoding="utf-8",
    )

    load_dotenv(env)
    settings = Settings.from_env()

    assert settings.candidate_max_targets == 40
    assert settings.retrieval_top_k == 8
    assert settings.coverage_gate_enabled is True


# -- LANGFUSE_USER_ID_FIELD names a UserContext attribute ------------------


def test_user_context_fields_are_real_attributes() -> None:
    """The constant in config.py duplicates the dataclass on purpose (circular import).

    This test is what keeps the copy honest: every name must be a real field, and the
    only omissions allowed are the two that cannot be an identifier.
    """
    from dataclasses import fields

    from orchestrator.auth.claims import UserContext
    from orchestrator.config import USER_CONTEXT_FIELDS

    real = {f.name for f in fields(UserContext)}
    allowed = set(USER_CONTEXT_FIELDS)

    assert allowed <= real, f"not a UserContext field: {allowed - real}"
    assert real - allowed == {"scopes", "claims"}


def test_unknown_langfuse_user_id_field_warns() -> None:
    """A getattr() miss falls back to `oid` silently — so the boot log must say so."""
    settings = Settings(
        litellm_api_key="sk-test",
        planner_model="test/planner",
        langfuse_user_id_field="emails",
    )

    warnings = settings.validate()

    assert any("LANGFUSE_USER_ID_FIELD" in w and "emails" in w for w in warnings)


def test_email_is_a_valid_langfuse_user_id_field() -> None:
    """The regression this fixes: `email` used to resolve to nothing."""
    settings = Settings(
        litellm_api_key="sk-test",
        planner_model="test/planner",
        langfuse_user_id_field="email",
    )

    assert not [w for w in settings.validate() if "LANGFUSE_USER_ID_FIELD" in w]
