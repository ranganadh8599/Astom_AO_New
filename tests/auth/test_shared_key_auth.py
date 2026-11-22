"""Shared-key authentication (LibreChat integration).

The design trades verification for simplicity:

* the **key** proves the caller is LibreChat (or anything else holding it);
* the **user id header** proves nothing — it is unsigned.

So a key holder can impersonate any user. That is accepted, and these tests pin the
properties that make it survivable rather than reckless:

1. It fails **closed** — no key, wrong key, or missing user header is rejected. There is
   no anonymous path.
2. The key comparison is **constant time**, so it cannot be recovered by timing.
3. The weakness is **recorded in the claim set**, so anything downstream (logs, traces,
   future authorization) can see identity was asserted, not proven.
4. Startup **refuses** a shared key shorter than 32 characters and **warns** unconditionally.
"""

from __future__ import annotations

import pytest

from orchestrator.config import ConfigurationError, Settings
from orchestrator.auth import AuthError, SharedKeyValidator, build_authenticator

KEY = "k" * 40
HEADERS = {"x-librechat-user-id": "user-123", "x-librechat-user-email": "a@example.com"}


def _validator(**overrides) -> SharedKeyValidator:
    base = {"key": KEY}
    base.update(overrides)
    return SharedKeyValidator(**base)


# -- happy path ------------------------------------------------------------


def test_identity_comes_from_the_header() -> None:
    user = _validator().validate(KEY, HEADERS)

    assert user.oid == "user-123"
    assert user.name == "a@example.com"
    assert user.is_authenticated


def test_name_falls_back_to_user_id() -> None:
    user = _validator().validate(KEY, {"x-librechat-user-id": "user-9"})

    assert user.oid == "user-9"
    assert user.name == "user-9"


def test_roles_come_from_configuration() -> None:
    user = _validator(roles=("AgentUser", "Admin")).validate(KEY, HEADERS)
    assert user.has_role("Admin")


def test_email_header_lands_on_the_field() -> None:
    """`LANGFUSE_USER_ID_FIELD=email` resolves here too, not just for token modes."""
    user = _validator().validate(
        KEY, {"x-librechat-user-id": "user-123", "x-librechat-user-email": "a@example.com"}
    )

    assert user.email == "a@example.com"


def test_missing_email_header_is_empty() -> None:
    user = _validator().validate(KEY, {"x-librechat-user-id": "user-9"})

    assert user.email == ""


def test_custom_email_header_name_is_honoured() -> None:
    """The header names are a contract with the front end, so they are configurable."""
    validator = _validator(user_email_header="X-Tenant-Email")
    user = validator.validate(
        KEY, {"x-librechat-user-id": "u1", "X-Tenant-Email": "u1@corp.example"}
    )

    assert user.email == "u1@corp.example"
    assert user.claims["email"] == "u1@corp.example"


def test_identity_is_recorded_as_unverified() -> None:
    """Downstream must be able to distinguish asserted identity from a signed token."""
    user = _validator().validate(KEY, HEADERS)

    assert user.claims["identity_source"] == "header"
    assert user.claims["identity_verified"] is False


def test_header_lookup_is_case_insensitive() -> None:
    user = _validator().validate(KEY, {"X-LibreChat-User-Id": "user-abc"})

    assert user.oid == "user-abc"


# -- fails closed ----------------------------------------------------------


def test_wrong_key_is_rejected() -> None:
    with pytest.raises(AuthError, match="invalid shared key"):
        _validator().validate("wrong-key", HEADERS)


def test_missing_key_is_rejected() -> None:
    with pytest.raises(AuthError, match="missing bearer token"):
        _validator().validate("", HEADERS)


def test_missing_user_header_is_rejected_not_anonymous() -> None:
    """The critical property: a valid key with no identity must not become anonymous."""
    with pytest.raises(AuthError, match="missing 'x-librechat-user-id'"):
        _validator().validate(KEY, {})


def test_empty_user_header_is_rejected() -> None:
    with pytest.raises(AuthError):
        _validator().validate(KEY, {"x-librechat-user-id": "   "})


def test_overlong_user_id_is_rejected() -> None:
    with pytest.raises(AuthError, match="too long"):
        _validator().validate(KEY, {"x-librechat-user-id": "u" * 201})


def test_validator_refuses_to_construct_without_a_key() -> None:
    with pytest.raises(ValueError, match="ORCH_SHARED_KEY"):
        SharedKeyValidator(key="")


# -- constant-time comparison ---------------------------------------------


def test_comparison_is_constant_time() -> None:
    """Guards against a refactor to `==`, which leaks the key by timing."""
    import inspect

    source = inspect.getsource(SharedKeyValidator.validate)

    assert "hmac.compare_digest" in source
    assert "== self._key" not in source


# -- configuration ---------------------------------------------------------


def _settings(**overrides) -> Settings:
    base = {
        "litellm_api_key": "sk-test",
        "planner_model": "test/planner",
        "langfuse_tracing_enabled": False,
        "auth_mode": "shared_key",
        "orch_shared_key": KEY,
    }
    base.update(overrides)
    return Settings(**base)


def test_short_key_is_rejected_at_boot() -> None:
    with pytest.raises(ConfigurationError, match="at least 32 characters"):
        _settings(orch_shared_key="short").validate()


def test_missing_key_is_rejected_at_boot() -> None:
    with pytest.raises(ConfigurationError, match="ORCH_SHARED_KEY"):
        _settings(orch_shared_key="").validate()


def test_startup_always_warns_about_the_trade() -> None:
    warnings = _settings().validate()

    assert any("UNSIGNED header" in w for w in warnings)
    assert any("impersonate" in w for w in warnings)


def test_builder_wires_shared_key_mode() -> None:
    validator = build_authenticator(_settings())

    assert isinstance(validator, SharedKeyValidator)
    assert validator.validate(KEY, HEADERS).oid == "user-123"
