"""Identity: the dev issuer must behave like Entra, and failures must be loud."""

from __future__ import annotations

import jwt
import pytest

from orchestrator.auth import AuthError, DevValidator, EntraValidator, NullAuthenticator, extract_user_context

DEV = dict(
    secret="test-secret-at-least-32-bytes-long-ok",
    issuer="http://localhost/dev-idp",
    audience="api://orchestrator",
)


def _validator(**overrides) -> DevValidator:
    return DevValidator(**{**DEV, **overrides})


def test_dev_round_trip_yields_entra_shaped_user() -> None:
    validator = _validator()
    user = validator.validate(validator.issue(oid="oid-42", roles=("AgentUser", "Approver")))
    assert user.oid == "oid-42"
    assert user.roles == ("AgentUser", "Approver")
    assert user.has_role("Approver")
    assert user.is_authenticated


def test_dev_rejects_wrong_audience() -> None:
    issuer = _validator()
    token = issuer.issue()
    with pytest.raises(AuthError):
        _validator(audience="api://somebody-else").validate(token)


def test_dev_rejects_expired_token() -> None:
    validator = _validator()
    with pytest.raises(AuthError):
        validator.validate(validator.issue(ttl_s=-120))


def test_dev_rejects_tampered_token() -> None:
    validator = _validator()
    token = validator.issue()
    head, body, sig = token.split(".")
    with pytest.raises(AuthError):
        validator.validate(f"{head}.{body}.{sig[:-3]}abc")


def test_required_role_is_enforced() -> None:
    validator = _validator(required_role="Approver")
    with pytest.raises(AuthError):
        validator.validate(validator.issue(roles=("AgentUser",)))
    assert validator.validate(validator.issue(roles=("AgentUser", "Approver"))).has_role("Approver")


def test_token_without_oid_is_rejected() -> None:
    validator = _validator()
    token = jwt.encode(
        {"aud": DEV["audience"], "iss": DEV["issuer"], "exp": 9999999999, "roles": []},
        DEV["secret"],
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        validator.validate(token)


def test_extract_user_context_maps_entra_claims() -> None:
    user = extract_user_context(
        {
            "oid": "abc",
            "name": "Ranganadh",
            "roles": ["AgentUser"],
            "tid": "tenant-1",
            "scp": "access_as_user read",
        }
    )
    assert user.name == "Ranganadh"
    assert user.tenant_id == "tenant-1"
    assert user.scopes == ("access_as_user", "read")


# -- email is a first-class field, not just a dict key ---------------------


def test_email_claim_lands_on_the_field() -> None:
    """LANGFUSE_USER_ID_FIELD=email does getattr(user, 'email') — it must resolve."""
    user = extract_user_context({"oid": "abc", "name": "R", "email": "r@example.com"})

    assert user.email == "r@example.com"


def test_email_falls_back_to_preferred_username() -> None:
    user = extract_user_context({"oid": "abc", "preferred_username": "r@corp.example"})

    assert user.email == "r@corp.example"


def test_email_falls_back_to_upn() -> None:
    user = extract_user_context({"oid": "abc", "upn": "r@legacy.example"})

    assert user.email == "r@legacy.example"


def test_missing_email_is_empty_not_the_oid() -> None:
    """Attribution must be able to tell 'no address' from 'address == oid'."""
    user = extract_user_context({"oid": "abc"})

    assert user.email == ""


def test_email_survives_to_state() -> None:
    user = extract_user_context({"oid": "abc", "email": "r@example.com"})

    assert user.to_state()["email"] == "r@example.com"


def test_entra_validator_requires_configuration() -> None:
    with pytest.raises(ValueError):
        EntraValidator(issuer="", audience="", jwks_uri="")


def test_null_authenticator_is_explicitly_anonymous() -> None:
    user = NullAuthenticator().validate("")
    assert user.oid == "anonymous"
