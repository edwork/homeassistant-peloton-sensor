"""Peloton login, token refresh and token revocation.

Peloton's identity provider is Auth0 at auth.onepeloton.com. A password grant
returns a JWT access token (valid for 48 hours) and a refresh token. The
refresh grant returns a new access token but no new refresh token; the
original refresh token keeps working. Failures come back as HTTP 403 with
``error: invalid_grant``.
"""

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import json
import logging
import math
import time
from typing import Any, Self

import aiohttp

from ._http import describe_error, raise_for_transient, read_body
from .const import (
    CLIENT_ID,
    REFRESH_MARGIN,
    REQUEST_TIMEOUT,
    REVOKE_URL,
    SCOPE,
    TOKEN_URL,
    USER_ID_CLAIM,
)
from .exceptions import (
    PelotonAuthError,
    PelotonConnectionError,
    PelotonError,
    PelotonMfaRequiredError,
)

_LOGGER = logging.getLogger(__name__)

# OAuth error codes that mean the credentials or refresh token are not valid.
_AUTH_ERRORS = frozenset({"invalid_grant", "access_denied"})


@dataclass(frozen=True, slots=True)
class PelotonTokens:
    """Tokens for one Peloton account."""

    access_token: str
    refresh_token: str | None
    expires_at: float
    user_id: str | None

    @classmethod
    def from_token_response(
        cls, data: Mapping[str, Any], previous_refresh_token: str | None = None
    ) -> Self:
        """Build tokens from a token endpoint response.

        The refresh grant does not return a refresh token, so the previous one
        is kept. A new one is used if Peloton ever starts rotating them.
        """
        access_token = data["access_token"]
        claims = _jwt_claims(access_token)
        expires_at = _number(claims.get("exp"))
        if expires_at is None:
            expires_at = time.time() + (_number(data.get("expires_in")) or 0)
        user_id = claims.get(USER_ID_CLAIM)
        refresh_token = data.get("refresh_token")
        return cls(
            access_token=access_token,
            refresh_token=refresh_token
            if isinstance(refresh_token, str) and refresh_token
            else previous_refresh_token,
            expires_at=float(expires_at),
            user_id=user_id if isinstance(user_id, str) and user_id else None,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Restore tokens saved with as_dict."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=float(data.get("expires_at") or 0),
            user_id=data.get("user_id"),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the tokens in a form that can be stored in a config entry."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "user_id": self.user_id,
        }

    def needs_refresh(self, now: float | None = None) -> bool:
        """Return True when the access token expires within REFRESH_MARGIN."""
        if now is None:
            now = time.time()
        return now >= self.expires_at - REFRESH_MARGIN

    def __repr__(self) -> str:
        """Keep token values out of logs and tracebacks."""
        return (
            f"PelotonTokens(expires_at={self.expires_at}, user_id={self.user_id}, "
            f"has_refresh_token={self.refresh_token is not None})"
        )


async def async_login(
    session: aiohttp.ClientSession, username: str, password: str
) -> PelotonTokens:
    """Log in with a username (or email) and password.

    Only call this from user-driven steps (config, reauth and reconfigure
    flows, and the one-time migration of old entries). Never from polling.
    """
    _LOGGER.debug("Password login")
    data = await _async_token_request(
        session,
        {
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "username": username,
            "password": password,
        },
    )
    return PelotonTokens.from_token_response(data)


async def async_refresh(
    session: aiohttp.ClientSession, refresh_token: str
) -> PelotonTokens:
    """Exchange a refresh token for a new access token."""
    data = await _async_token_request(
        session,
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )
    _LOGGER.debug("Token refreshed")
    return PelotonTokens.from_token_response(data, refresh_token)


async def async_revoke(session: aiohttp.ClientSession, refresh_token: str) -> None:
    """Revoke a refresh token.

    Access tokens already issued stay valid until they expire.
    """
    try:
        async with session.post(
            REVOKE_URL,
            json={"client_id": CLIENT_ID, "token": refresh_token},
            timeout=REQUEST_TIMEOUT,
            # Never re-send a token to wherever a redirect points.
            allow_redirects=False,
        ) as resp:
            status = resp.status
            data, text = await read_body(resp)
            headers = resp.headers
    except (aiohttp.ClientError, TimeoutError) as err:
        raise PelotonConnectionError(
            f"Revoke: cannot reach Peloton: {describe_error(err)}"
        ) from err
    if status == 200:
        _LOGGER.debug("Refresh token revoked")
        return
    raise_for_transient(status, text, headers, "Revoke")
    error = _error_code(data)
    raise PelotonError(f"Revoke failed: HTTP {status} {error or ''}".rstrip())


async def _async_token_request(
    session: aiohttp.ClientSession, payload: dict[str, str]
) -> dict[str, Any]:
    """Send a request to the token endpoint and classify the response."""
    try:
        async with session.post(
            TOKEN_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
            # Never re-send credentials to wherever a redirect points.
            allow_redirects=False,
        ) as resp:
            status = resp.status
            data, text = await read_body(resp)
            headers = resp.headers
    except (aiohttp.ClientError, TimeoutError) as err:
        raise PelotonConnectionError(
            f"Login: cannot reach Peloton: {describe_error(err)}"
        ) from err

    if (
        status == 200
        and isinstance(data, dict)
        and isinstance(data.get("access_token"), str)
        and data["access_token"]
    ):
        return data

    error = _error_code(data)
    if error == "mfa_required":
        raise PelotonMfaRequiredError("Login requires multi-factor authentication")
    if error in _AUTH_ERRORS:
        _LOGGER.debug("Token request rejected: %s", error)
        raise PelotonAuthError(f"Peloton rejected the login ({error})")
    raise_for_transient(status, text, headers, "Login")
    # Includes unauthorized_client / invalid_client, which mean Peloton no
    # longer accepts this client or grant: not something the user can fix.
    raise PelotonError(
        f"Unexpected response from the token endpoint: HTTP {status} {error or ''}".rstrip()
    )


def _error_code(data: Any) -> str | None:
    """Return the OAuth "error" code of a response body, if it is a string."""
    error = data.get("error") if isinstance(data, dict) else None
    return error if isinstance(error, str) else None


def _jwt_claims(token: str) -> dict[str, Any]:
    """Return the claims of a JWT without verifying it.

    The token comes straight from Peloton over TLS and is only read for its
    expiry and user id.
    """
    try:
        payload = token.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
    except IndexError, ValueError:
        return {}
    return claims if isinstance(claims, dict) else {}


def _number(value: Any) -> float | None:
    """Return value if it is an int or float (not bool), else None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None
