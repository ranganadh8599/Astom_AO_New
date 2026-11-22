"""Identity as the orchestrator sees it.

The claim names match Entra ID access tokens exactly (``oid``, ``tid``, ``roles``,
``preferred_username``), so switching from the dev issuer to a real tenant changes only
which validator is constructed — not any downstream code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class AuthError(Exception):
    """Raised for any token that must not be trusted."""


@dataclass(frozen=True)
class UserContext:
    """The validated caller. This object is the only source of identity in the graph."""

    oid: str
    name: str
    # Promoted to a first-class field (it used to live only in ``claims``) so settings
    # that name an attribute — ``LANGFUSE_USER_ID_FIELD=email`` — actually resolve.
    # ``getattr`` on a dataclass only sees real fields, never dict keys.
    email: str = ""
    roles: tuple[str, ...] = ()
    tenant_id: str = ""
    scopes: tuple[str, ...] = ()
    claims: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def has_role(self, role: str) -> bool:
        return role in self.roles

    @property
    def is_authenticated(self) -> bool:
        return bool(self.oid)

    def to_state(self) -> dict[str, Any]:
        """Serializable form, safe to persist in a LangGraph checkpoint."""
        return {
            "oid": self.oid,
            "name": self.name,
            "email": self.email,
            "roles": list(self.roles),
            "tenant_id": self.tenant_id,
        }


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def extract_user_context(claims: Mapping[str, Any]) -> UserContext:
    """Map validated claims onto a UserContext.

    ``oid`` is required: without a stable user key there is nothing to authorize or
    audit, so a token lacking it is invalid rather than an anonymous user.
    """
    oid = str(claims.get("oid") or "").strip()
    if not oid:
        raise AuthError("token has no 'oid' claim")

    name = str(
        claims.get("name")
        or claims.get("preferred_username")
        or claims.get("upn")
        or oid
    )
    # Entra puts the address in `email`, `preferred_username` or `upn` depending on the
    # token shape; take the first that looks like one.
    email = str(
        claims.get("email")
        or claims.get("preferred_username")
        or claims.get("upn")
        or ""
    ).strip()
    scp = claims.get("scp")
    scopes = tuple(str(scp).split()) if scp else ()

    return UserContext(
        oid=oid,
        name=name,
        email=email,
        roles=_as_tuple(claims.get("roles")),
        tenant_id=str(claims.get("tid") or ""),
        scopes=scopes,
        claims=dict(claims),
    )
