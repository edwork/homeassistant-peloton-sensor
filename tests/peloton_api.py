"""Helpers for mocking the Peloton auth and API endpoints."""

import base64
from collections.abc import Awaitable, Callable, Iterable
import json
from typing import Any

from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.peloton.api.const import API_BASE, TOKEN_URL, USER_ID_CLAIM

USER_ID = "0123456789abcdef0123456789abcdef"

JSON = {"content-type": "application/json; charset=utf-8"}
HTML = {"content-type": "text/html; charset=utf-8"}
TEXT = {"content-type": "text/plain; charset=utf-8"}

ACCESS_TOKEN_LIFETIME = 48 * 3600
REFRESH_TOKEN = "refresh-1"


def make_jwt(claims: dict[str, Any]) -> str:
    """Return an unsigned JWT with the given claims."""

    def encode(part: dict[str, Any]) -> str:
        raw = json.dumps(part).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'RS256', 'typ': 'JWT'})}.{encode(claims)}.signature"


def token_response(
    *,
    now: float,
    refresh_token: str | None = REFRESH_TOKEN,
    user_id: str | None = USER_ID,
    marker: str = "1",
) -> dict[str, Any]:
    """Return a token endpoint response like Peloton's.

    ``marker`` makes access tokens distinguishable in assertions.
    """
    claims: dict[str, Any] = {
        "iat": int(now),
        "exp": int(now) + ACCESS_TOKEN_LIFETIME,
        "marker": marker,
    }
    if user_id is not None:
        claims[USER_ID_CLAIM] = user_id
    data: dict[str, Any] = {
        "access_token": make_jwt(claims),
        "expires_in": ACCESS_TOKEN_LIFETIME,
        "token_type": "Bearer",
        "scope": "openid offline_access",
    }
    if refresh_token is not None:
        data["refresh_token"] = refresh_token
    return data


def api_url(path: str) -> str:
    """Return the full API URL for a path."""
    return f"{API_BASE}{path}"


def sequence(
    responses: Iterable[dict[str, Any]],
) -> Callable[[str, URL, Any], Awaitable[AiohttpClientMockResponse]]:
    """Return an aioclient_mock side_effect that answers with each response in turn.

    Each item holds AiohttpClientMockResponse keyword arguments (status, json,
    text, headers, exc). The last one repeats once the others are used up.
    """
    pending = list(responses)

    async def side_effect(
        method: str, url: URL, data: Any
    ) -> AiohttpClientMockResponse:
        kwargs = pending.pop(0) if len(pending) > 1 else pending[0]
        return AiohttpClientMockResponse(method, url, **kwargs)

    return side_effect


def token_requests(mock_calls: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    """Return the JSON payloads posted to the token endpoint."""
    return [
        data
        for method, url, data, _headers in mock_calls
        if method.lower() == "post" and str(url) == TOKEN_URL
    ]
