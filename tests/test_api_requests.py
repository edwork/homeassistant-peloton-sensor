"""Tests for request options the HTTP mock does not record."""

from typing import Any

from aiohttp import ClientSession
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.api import PelotonClient, async_login, async_revoke
from custom_components.peloton.api.const import REQUEST_TIMEOUT, REVOKE_URL, TOKEN_URL

from .conftest import PASSWORD, USERNAME
from .peloton_api import JSON, TEXT, api_url, token_response

NOW = 1_760_000_000.0


async def test_request_options(
    session: ClientSession,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Every request has a timeout; token and revoke POSTs never follow redirects."""
    freezer.move_to("2025-10-09 08:53:20+00:00")
    seen: list[tuple[str, dict[str, Any]]] = []
    original = session._request  # noqa: SLF001

    def spy(method: str, url: str, **kwargs: Any) -> Any:
        seen.append((method, kwargs))
        return original(method, url, **kwargs)

    object.__setattr__(session, "_request", spy)
    aioclient_mock.post(TOKEN_URL, json=token_response(now=NOW), headers=JSON)
    aioclient_mock.get(api_url("/api/me"), json={}, headers=JSON)
    aioclient_mock.post(REVOKE_URL, text="", headers=TEXT)

    tokens = await async_login(session, USERNAME, PASSWORD)
    await PelotonClient(session, tokens).async_get_me()
    await async_revoke(session, "refresh-1")

    assert [method for method, _ in seen] == ["POST", "GET", "POST"]
    assert all(kwargs["timeout"] is REQUEST_TIMEOUT for _, kwargs in seen)
    posts = [kwargs for method, kwargs in seen if method == "POST"]
    assert all(kwargs["allow_redirects"] is False for kwargs in posts)
