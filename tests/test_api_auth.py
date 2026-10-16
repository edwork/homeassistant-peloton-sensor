"""Tests for Peloton login, refresh and revoke."""

from aiohttp import ClientError, ClientSession
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.api import (
    PelotonAuthError,
    PelotonConnectionError,
    PelotonError,
    PelotonMfaRequiredError,
    PelotonRateLimitError,
    PelotonTokens,
    async_login,
    async_refresh,
    async_revoke,
)
from custom_components.peloton.api.const import (
    CLIENT_ID,
    REFRESH_MARGIN,
    REVOKE_URL,
    SCOPE,
    TOKEN_URL,
)

from .conftest import PASSWORD, USER_ID, USERNAME
from .peloton_api import (
    ACCESS_TOKEN_LIFETIME,
    HTML,
    JSON,
    TEXT,
    make_jwt,
    token_requests,
    token_response,
)

NOW = 1_760_000_000.0


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> None:
    """Pin time.time() so token expiry is predictable."""
    freezer.move_to("2025-10-09 08:53:20+00:00")  # NOW


async def test_login(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A password login sends the password grant and parses the tokens."""
    aioclient_mock.post(TOKEN_URL, json=token_response(now=NOW), headers=JSON)

    tokens = await async_login(session, USERNAME, PASSWORD)

    assert token_requests(aioclient_mock.mock_calls) == [
        {
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "scope": SCOPE,
            "username": USERNAME,
            "password": PASSWORD,
        }
    ]
    assert tokens.refresh_token == "refresh-1"
    assert tokens.expires_at == NOW + ACCESS_TOKEN_LIFETIME
    assert tokens.user_id == USER_ID
    assert not tokens.needs_refresh()


async def test_login_without_jwt_uses_expires_in(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """If the access token is not a readable JWT, expires_in sets the expiry."""
    aioclient_mock.post(
        TOKEN_URL,
        json={"access_token": "opaque", "refresh_token": "r", "expires_in": 3600},
        headers=JSON,
    )

    tokens = await async_login(session, USERNAME, PASSWORD)

    assert tokens.expires_at == NOW + 3600
    assert tokens.user_id is None


@pytest.mark.parametrize(
    ("status", "body", "headers", "error"),
    [
        (
            403,
            {"error": "invalid_grant", "error_description": "Login Failed"},
            JSON,
            PelotonAuthError,
        ),
        (403, {"error": "access_denied"}, JSON, PelotonAuthError),
        (403, {"error": "mfa_required"}, JSON, PelotonMfaRequiredError),
        (429, {"error": "too_many_requests"}, JSON, PelotonRateLimitError),
        (403, "error code: 1015", TEXT, PelotonRateLimitError),
        (503, "<html>Service Unavailable</html>", HTML, PelotonConnectionError),
        (200, "<html>maintenance</html>", HTML, PelotonError),
        (200, {"token_type": "Bearer"}, JSON, PelotonError),
        (403, {"error": "unauthorized_client"}, JSON, PelotonError),
        (401, {"error": "invalid_client"}, JSON, PelotonError),
        (401, {"error": "access_denied"}, JSON, PelotonAuthError),
        (400, {"error": "invalid_request"}, JSON, PelotonError),
        (403, {"error": {"code": "invalid_grant"}}, JSON, PelotonError),
        (200, {"access_token": 123}, JSON, PelotonError),
        (200, '{"access_token": "x"}', TEXT, PelotonError),
    ],
    ids=[
        "wrong_password",
        "access_denied",
        "mfa_required",
        "http_429",
        "cloudflare_1015",
        "server_error",
        "html_body",
        "no_access_token",
        "client_not_allowed",
        "invalid_client_401",
        "access_denied_401",
        "invalid_request",
        "error_not_a_string",
        "access_token_not_a_string",
        "json_body_text_content_type",
    ],
)
async def test_login_errors(
    session: ClientSession,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    body: dict | str,
    headers: dict[str, str],
    error: type[PelotonError],
) -> None:
    """Token endpoint failures map to the right exception."""
    kwargs = {"json": body} if isinstance(body, dict) else {"text": body}
    aioclient_mock.post(TOKEN_URL, status=status, headers=headers, **kwargs)

    with pytest.raises(error) as exc_info:
        await async_login(session, USERNAME, PASSWORD)

    assert type(exc_info.value) is error
    assert PASSWORD not in str(exc_info.value)


async def test_login_rate_limit_retry_after(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The Retry-After header is passed on with the rate limit error."""
    aioclient_mock.post(
        TOKEN_URL, status=429, text="slow down", headers={**TEXT, "Retry-After": "30"}
    )

    with pytest.raises(PelotonRateLimitError) as exc_info:
        await async_login(session, USERNAME, PASSWORD)

    assert exc_info.value.retry_after == 30


@pytest.mark.parametrize("exc", [ClientError("boom"), TimeoutError()])
async def test_login_network_errors(
    session: ClientSession, aioclient_mock: AiohttpClientMocker, exc: Exception
) -> None:
    """Network failures and timeouts are connection errors."""
    aioclient_mock.post(TOKEN_URL, exc=exc)

    with pytest.raises(PelotonConnectionError):
        await async_login(session, USERNAME, PASSWORD)


async def test_refresh_keeps_refresh_token(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The refresh response has no refresh token; the old one is kept."""
    aioclient_mock.post(
        TOKEN_URL, json=token_response(now=NOW, refresh_token=None), headers=JSON
    )

    tokens = await async_refresh(session, "refresh-1")

    assert token_requests(aioclient_mock.mock_calls) == [
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": "refresh-1",
        }
    ]
    assert tokens.refresh_token == "refresh-1"
    assert tokens.expires_at == NOW + ACCESS_TOKEN_LIFETIME


async def test_refresh_accepts_rotated_refresh_token(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """If Peloton starts rotating refresh tokens, the new one is used."""
    aioclient_mock.post(
        TOKEN_URL, json=token_response(now=NOW, refresh_token="refresh-2"), headers=JSON
    )

    tokens = await async_refresh(session, "refresh-1")

    assert tokens.refresh_token == "refresh-2"


async def test_refresh_revoked(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A revoked refresh token is an auth error."""
    aioclient_mock.post(
        TOKEN_URL,
        status=403,
        json={
            "error": "invalid_grant",
            "error_description": "Unknown or invalid refresh token.",
        },
        headers=JSON,
    )

    with pytest.raises(PelotonAuthError) as exc_info:
        await async_refresh(session, "refresh-1")

    assert "refresh-1" not in str(exc_info.value)


async def test_revoke(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Revoke posts the refresh token to the revocation endpoint."""
    aioclient_mock.post(REVOKE_URL, text="", headers=TEXT)

    await async_revoke(session, "refresh-1")

    assert aioclient_mock.mock_calls[0][2] == {
        "client_id": CLIENT_ID,
        "token": "refresh-1",
    }


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (503, "unavailable", PelotonConnectionError),
        (400, '{"error": "invalid_request"}', PelotonError),
    ],
)
async def test_revoke_errors(
    session: ClientSession,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    body: str,
    error: type[PelotonError],
) -> None:
    """Revoke failures raise so callers can decide whether to ignore them."""
    aioclient_mock.post(REVOKE_URL, status=status, text=body, headers=JSON)

    with pytest.raises(error) as exc_info:
        await async_revoke(session, "refresh-1")

    assert "refresh-1" not in str(exc_info.value)


async def test_revoke_network_error(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A network failure during revoke is a connection error."""
    aioclient_mock.post(REVOKE_URL, exc=ClientError())

    with pytest.raises(PelotonConnectionError):
        await async_revoke(session, "refresh-1")


def test_tokens_round_trip_and_repr() -> None:
    """Tokens survive storage, and their repr does not show token values."""
    access_token = make_jwt({"exp": int(NOW) + 100})
    tokens = PelotonTokens(access_token, "refresh-1", NOW + 100, USER_ID)

    assert PelotonTokens.from_dict(tokens.as_dict()) == tokens
    assert access_token not in repr(tokens)
    assert "refresh-1" not in repr(tokens)


def test_needs_refresh_margin() -> None:
    """Tokens are refreshed REFRESH_MARGIN seconds before they expire."""
    tokens = PelotonTokens("a", "r", NOW + REFRESH_MARGIN + 1, USER_ID)

    assert not tokens.needs_refresh(NOW)
    assert tokens.needs_refresh(NOW + 1)


async def test_login_expiry_comes_from_jwt_exp(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The JWT exp claim sets the expiry; expires_in is only a fallback."""
    data = token_response(now=NOW - 600)  # issued 10 minutes before it arrives
    aioclient_mock.post(TOKEN_URL, json=data, headers=JSON)

    tokens = await async_login(session, USERNAME, PASSWORD)

    assert tokens.expires_at == NOW - 600 + ACCESS_TOKEN_LIFETIME


async def test_login_ignores_unusable_exp(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """An exp claim that is not a usable number falls back to expires_in."""
    aioclient_mock.post(
        TOKEN_URL,
        json={
            "access_token": make_jwt({"exp": 10**400}),
            "refresh_token": "r",
            "expires_in": 3600,
        },
        headers=JSON,
    )

    tokens = await async_login(session, USERNAME, PASSWORD)

    assert tokens.expires_at == NOW + 3600


async def test_refresh_ignores_non_string_refresh_token(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A refresh_token that is not a string keeps the previous one."""
    data = token_response(now=NOW, refresh_token=None)
    data["refresh_token"] = {"unexpected": True}
    aioclient_mock.post(TOKEN_URL, json=data, headers=JSON)

    tokens = await async_refresh(session, "refresh-1")

    assert tokens.refresh_token == "refresh-1"


async def test_undecodable_error_page_login(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A gateway error page that is not valid UTF-8 is still a connection error."""
    aioclient_mock.post(
        TOKEN_URL, status=502, content=b"<html>\xff\xfe gateway</html>", headers=HTML
    )

    with pytest.raises(PelotonConnectionError):
        await async_login(session, USERNAME, PASSWORD)


async def test_undecodable_error_page_revoke(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The same holds for the revocation endpoint."""
    aioclient_mock.post(
        REVOKE_URL, status=502, content=b"<html>\xff\xfe gateway</html>", headers=HTML
    )

    with pytest.raises(PelotonConnectionError):
        await async_revoke(session, "refresh-1")


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "Infinity", "soon"])
async def test_unusable_retry_after_is_ignored(
    session: ClientSession, aioclient_mock: AiohttpClientMocker, value: str
) -> None:
    """Retry-After values that are not positive finite numbers are ignored."""
    aioclient_mock.post(
        TOKEN_URL, status=429, text="slow down", headers={**TEXT, "Retry-After": value}
    )

    with pytest.raises(PelotonRateLimitError) as exc_info:
        await async_login(session, USERNAME, PASSWORD)

    assert exc_info.value.retry_after is None
