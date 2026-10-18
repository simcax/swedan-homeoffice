"""Shared-secret authentication for the API.

The Flet frontend attaches a shared secret to every request in the
``X-API-Key`` header; this module exposes a FastAPI dependency that verifies
that header against the configured ``APP_SHARED_SECRET`` on every guarded
request.

A dependency (rather than raw middleware) is used so verification integrates
with FastAPI's dependency injection and OpenAPI, and so it only guards the
routes it is attached to — leaving CORS pre-flight ``OPTIONS`` and any mounted
Flet frontend unaffected. The expected value is read from :class:`Settings`
(via :func:`get_settings`) rather than the environment directly, keeping
configuration in one place.

Requirements: 7.2, 7.3
"""

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from backend.config import Settings, get_settings

#: Name of the request header carrying the shared secret.
API_KEY_HEADER = "X-API-Key"

# Dependency aliases, following the ``Annotated[..., Depends(...)]`` convention
# used by the routers (avoids a ``Depends`` call in an argument default, B008).
_ApiKeyHeader = Annotated[str | None, Header(alias=API_KEY_HEADER)]
_Settings = Annotated[Settings, Depends(get_settings)]


class AuthError(HTTPException):
    """HTTP 401 raised when the ``X-API-Key`` header is missing or wrong.

    Rejecting with ``401 Unauthorized`` (rather than ``403``) lets the Flet
    client recognise a rejected secret and return the user to the login screen
    (Requirement 7.3).
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def verify_api_key(
    settings: _Settings,
    x_api_key: _ApiKeyHeader = None,
) -> None:
    """Allow the request iff ``X-API-Key`` equals ``APP_SHARED_SECRET``.

    The expected secret is read from :attr:`Settings.required_shared_secret`,
    which raises :class:`~backend.config.SharedSecretConfigurationError` when
    the variable is unset — startup validation guards against that case so a
    misconfigured deployment never serves traffic.

    The supplied header is compared to the expected value with
    :func:`secrets.compare_digest`, a constant-time comparison that avoids
    leaking the secret through timing side-channels.

    Args:
        x_api_key: The ``X-API-Key`` header value, or ``None`` when absent.
        settings: The application settings providing the expected secret.

    Raises:
        AuthError: When the header is missing or does not match
            ``APP_SHARED_SECRET`` (Requirement 7.3).
    """
    expected = settings.required_shared_secret
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise AuthError()
