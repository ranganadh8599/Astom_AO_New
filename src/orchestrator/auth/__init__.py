"""Authentication surface for the orchestrator."""

from orchestrator.auth.claims import AuthError, UserContext, extract_user_context
from orchestrator.auth.validators import (
    Authenticator,
    DevValidator,
    EntraValidator,
    NullAuthenticator,
    SharedKeyValidator,
    build_authenticator,
)

__all__ = [
    "AuthError",
    "Authenticator",
    "DevValidator",
    "EntraValidator",
    "NullAuthenticator",
    "SharedKeyValidator",
    "UserContext",
    "build_authenticator",
    "extract_user_context",
]
