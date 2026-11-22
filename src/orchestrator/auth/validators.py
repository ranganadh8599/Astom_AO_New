"""Token validators.

``EntraValidator`` does the real work: signature against the tenant JWKS, issuer pinned,
audience pinned, expiry checked, roles read from the ``roles`` claim. ``DevValidator``
produces and checks the same claim shape locally so the orchestrator is runnable before
the tenant exists — the only thing that changes later is which validator is wired up.
"""

from __future__ import annotations

import hmac
import time
from typing import Any, Mapping, Protocol

import jwt
from jwt import PyJWKClient

from orchestrator.config import Settings
from orchestrator.auth.claims import AuthError, UserContext, extract_user_context

_LEEWAY_S = 60  # bounded clock skew
_JWKS_CACHE_S = 3600


class Authenticator(Protocol):
    def validate(
        self, token: str, headers: Mapping[str, str] | None = None
    ) -> UserContext: ...


class SharedKeyValidator:
    """LibreChat integration: one secret key authenticates the caller; a plain header
    names the user.

    ## What this does and does not prove

    The key proves *"the caller is LibreChat"* (or anything else holding the key). The
    header proves **nothing** — it is unsigned, so anyone with the key can claim any
    user id. That is the accepted trade: it removes the need for per-user token
    exchange, at the cost of impersonation being possible for key holders.

    Two properties make it defensible:

    * **Failing closed.** No key, wrong key, or no user header is rejected. A request
      cannot be anonymous.
    * **Constant-time key comparison**, so the key cannot be recovered by timing.

    If the key leaks, every user is exposed. Rotate it like a password, and prefer
    ``AUTH_MODE=entra`` with token forwarding (or OBO) when the threat model includes
    insider or key-compromise risk. See ``docs/sso-integration.md``.
    """

    def __init__(
        self,
        *,
        key: str,
        user_id_header: str = "x-librechat-user-id",
        user_email_header: str = "x-librechat-user-email",
        user_name_header: str = "x-librechat-user-name",
        roles: tuple[str, ...] = ("AgentUser",),
    ) -> None:
        if not key:
            raise ValueError(
                "AUTH_MODE=shared_key requires ORCH_SHARED_KEY (the value LibreChat "
                "sends as apiKey: '${ORCH_KEY}')"
            )
        self._key = key
        self._user_id_header = user_id_header.lower()
        self._user_email_header = user_email_header.lower()
        self._user_name_header = user_name_header.lower()
        self._roles = roles

    def validate(
        self, token: str, headers: Mapping[str, str] | None = None
    ) -> UserContext:
        if not token:
            raise AuthError("missing bearer token")
        if not hmac.compare_digest(token, self._key):
            raise AuthError("invalid shared key")

        lowered = {name.lower(): (value or "").strip() for name, value in (headers or {}).items()}
        user_id = lowered.get(self._user_id_header, "")
        if not user_id:
            # LibreChat substitutes this template in custom-endpoint headers.
            template = "{{LIBRECHAT_USER_ID}}"
            raise AuthError(
                f"missing {self._user_id_header!r} header; LibreChat must send "
                f"{self._user_id_header}: '{template}'"
            )
        if len(user_id) > 200:
            raise AuthError("user id header is too long")

        email = lowered.get(self._user_email_header, "")
        name = lowered.get(self._user_name_header, "") or email or user_id

        return UserContext(
            oid=user_id,
            name=name,
            email=email,
            roles=self._roles,
            # Recorded so the trusted-but-unverified nature is visible downstream.
            claims={
                "identity_source": "header",
                "identity_verified": False,
                "email": email,
            },
        )


class EntraValidator:
    """Validates Entra ID access tokens (v2.0, or v1.0 when the issuer is pinned)."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_uri: str,
        required_role: str = "",
        jwk_client: PyJWKClient | None = None,
    ) -> None:
        if not (issuer and audience and jwks_uri):
            raise ValueError(
                "ENTRA_TENANT_ID (or ENTRA_ISSUER/ENTRA_JWKS_URI) and ENTRA_AUDIENCE "
                "are required when AUTH_MODE=entra"
            )
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._required_role = required_role
        self._jwk_client = jwk_client or PyJWKClient(jwks_uri, cache_keys=True)

    def validate(
        self, token: str, headers: Mapping[str, str] | None = None
    ) -> UserContext:
        if not token:
            raise AuthError("missing bearer token")
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token).key
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=self._audience,
                # v1/v2 issuers both appear in the wild; accept either form of the tenant
                # issuer but pin the tenant itself.
                options={"require": ["exp", "iss", "aud"], "verify_iss": False},
                leeway=_LEEWAY_S,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthError(f"token audience is not {self._audience!r}") from exc
        except jwt.PyJWTError as exc:
            raise AuthError(f"token rejected: {exc}") from exc

        if not self._issuer_matches(str(claims.get("iss", ""))):
            raise AuthError(f"unexpected token issuer {claims.get('iss')!r}")

        user = extract_user_context(claims)
        if self._required_role and not user.has_role(self._required_role):
            raise AuthError(f"missing required role {self._required_role!r}")
        return user

    def _issuer_matches(self, iss: str) -> bool:
        normalized = iss.rstrip("/")
        if normalized == self._issuer:
            return True
        # v1.0 tokens use sts.windows.net; same tenant, different host.
        tenant = self._issuer.rsplit("/", 2)[0] if self._issuer.endswith("/v2.0") else ""
        return bool(tenant) and normalized.startswith(tenant)


class DevValidator:
    """Local HS256 issuer/validator using the Entra claim shape."""

    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        required_role: str = "",
    ) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._required_role = required_role

    def validate(
        self, token: str, headers: Mapping[str, str] | None = None
    ) -> UserContext:
        if not token:
            raise AuthError("missing bearer token")
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud"]},
                leeway=_LEEWAY_S,
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"token rejected: {exc}") from exc

        user = extract_user_context(claims)
        if self._required_role and not user.has_role(self._required_role):
            raise AuthError(f"missing required role {self._required_role!r}")
        return user

    def issue(
        self,
        *,
        oid: str = "00000000-0000-0000-0000-000000000001",
        name: str = "Dev User",
        roles: tuple[str, ...] = ("AgentUser",),
        tenant_id: str = "dev-tenant",
        ttl_s: int = 3600,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "oid": oid,
            "name": name,
            "preferred_username": f"{oid[:8]}@example.com",
            "roles": list(roles),
            "tid": tenant_id,
            "aud": self._audience,
            "iss": self._issuer,
            "iat": now,
            "nbf": now,
            "exp": now + ttl_s,
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")


class NullAuthenticator:
    """AUTH_MODE=none — local experiments only."""

    def __init__(self, user: UserContext | None = None) -> None:
        self._user = user or UserContext(
            oid="anonymous", name="Anonymous (AUTH_MODE=none)", roles=("AgentUser",)
        )

    def validate(
        self, token: str, headers: Mapping[str, str] | None = None
    ) -> UserContext:
        return self._user


def build_authenticator(settings: Settings) -> Authenticator:
    mode = settings.auth_mode
    if mode == "entra":
        return EntraValidator(
            issuer=settings.effective_issuer,
            audience=settings.entra_audience,
            jwks_uri=settings.effective_jwks_uri,
            required_role=settings.entra_required_role,
        )
    if mode == "shared_key":
        return SharedKeyValidator(
            key=settings.orch_shared_key,
            user_id_header=settings.user_id_header,
            user_email_header=settings.user_email_header,
            user_name_header=settings.user_name_header,
            roles=settings.shared_key_roles,
        )
    if mode == "dev":
        return DevValidator(
            secret=settings.dev_jwt_secret,
            issuer=settings.dev_jwt_issuer,
            audience=settings.dev_jwt_audience,
            required_role=settings.entra_required_role,
        )
    if mode == "none":
        return NullAuthenticator()
    raise ValueError(
        f"unknown AUTH_MODE {mode!r} (expected entra|shared_key|dev|none)"
    )
