"""Tests for the authenticated Peloton API client."""

import asyncio

from aiohttp import ClientError, ClientSession
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.peloton.api import (
    PelotonAuthError,
    PelotonClient,
    PelotonConnectionError,
    PelotonError,
    PelotonRateLimitError,
    PelotonTokens,
)
from custom_components.peloton.api.const import (
    REFRESH_RETRY_DELAY,
    REVOKE_URL,
    TOKEN_URL,
)

from .conftest import USER_ID, load_fixture
from .peloton_api import (
    ACCESS_TOKEN_LIFETIME,
    HTML,
    JSON,
    TEXT,
    api_url,
    make_jwt,
    sequence,
    token_requests,
    token_response,
)

NOW = 1_760_000_000.0
WORKOUT_ID = "fedcba9876543210fedcba9876543210"
ME_URL = api_url("/api/me")


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> None:
    """Pin time.time() so token expiry is predictable."""
    freezer.move_to("2025-10-09 08:53:20+00:00")  # NOW


def fresh_tokens(user_id: str | None = USER_ID) -> PelotonTokens:
    """Return tokens that are valid for another 48 hours."""
    return PelotonTokens(
        make_jwt({"exp": int(NOW) + ACCESS_TOKEN_LIFETIME, "marker": "0"}),
        "refresh-1",
        NOW + ACCESS_TOKEN_LIFETIME,
        user_id,
    )


def expiring_tokens() -> PelotonTokens:
    """Return tokens that expire within the refresh margin."""
    return PelotonTokens("old-access", "refresh-1", NOW + 60, USER_ID)


class Recorder:
    """Collect tokens passed to on_tokens_updated."""

    def __init__(self) -> None:
        """Start empty."""
        self.calls: list[PelotonTokens] = []

    def __call__(self, tokens: PelotonTokens) -> None:
        """Record one update."""
        self.calls.append(tokens)


def assert_no_token_values(text: str, tokens: PelotonTokens) -> None:
    """Fail if an access or refresh token value appears in text."""
    assert tokens.access_token not in text
    assert tokens.refresh_token is None or tokens.refresh_token not in text


def bearer(mock_call: tuple) -> str:
    """Return the bearer token sent with a recorded request."""
    return mock_call[3]["Authorization"].removeprefix("Bearer ")


async def test_get_me_with_fresh_token(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A fresh token is used as is: no token request, expected headers."""
    tokens = fresh_tokens()
    aioclient_mock.get(ME_URL, json=load_fixture("me.json"), headers=JSON)
    client = PelotonClient(session, tokens)

    user = await client.async_get_me()

    assert user.username == "testrider"
    assert user.first_name == "Test"
    assert token_requests(aioclient_mock.mock_calls) == []
    headers = aioclient_mock.mock_calls[0][3]
    assert headers == {
        "Authorization": f"Bearer {tokens.access_token}",
        "Accept": "application/json",
        "Peloton-Platform": "web",
    }


async def test_refresh_before_expiry(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A token close to expiry is refreshed first, and the new tokens are reported."""
    aioclient_mock.post(
        TOKEN_URL, json=token_response(now=NOW, refresh_token=None), headers=JSON
    )
    aioclient_mock.get(ME_URL, json=load_fixture("me.json"), headers=JSON)
    recorder = Recorder()
    client = PelotonClient(session, expiring_tokens(), recorder)

    await client.async_get_me()

    assert [p["grant_type"] for p in token_requests(aioclient_mock.mock_calls)] == [
        "refresh_token"
    ]
    assert len(recorder.calls) == 1
    new_tokens = recorder.calls[0]
    assert new_tokens.refresh_token == "refresh-1"
    assert new_tokens.expires_at == NOW + ACCESS_TOKEN_LIFETIME
    assert client.tokens == new_tokens
    assert bearer(aioclient_mock.mock_calls[-1]) == new_tokens.access_token


async def test_concurrent_calls_refresh_once(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Five requests that all find the token expiring cause one refresh."""

    async def slow_token(method, url, data):
        # Yield so the other requests reach the lock while this refresh runs.
        await asyncio.sleep(0)
        return AiohttpClientMockResponse(
            method, url, json=token_response(now=NOW), headers=JSON
        )

    aioclient_mock.post(TOKEN_URL, side_effect=slow_token)
    aioclient_mock.get(ME_URL, json=load_fixture("me.json"), headers=JSON)
    recorder = Recorder()
    client = PelotonClient(session, expiring_tokens(), recorder)

    await asyncio.gather(*(client.async_get_me() for _ in range(5)))

    assert len(token_requests(aioclient_mock.mock_calls)) == 1
    assert len(recorder.calls) == 1
    sent = [bearer(c) for c in aioclient_mock.mock_calls if c[0].lower() == "get"]
    assert sent == [recorder.calls[0].access_token] * 5


async def test_401_refreshes_and_retries(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 on a token that looked valid triggers one refresh and one retry."""
    aioclient_mock.post(
        TOKEN_URL, json=token_response(now=NOW, marker="2"), headers=JSON
    )
    aioclient_mock.get(
        ME_URL,
        side_effect=sequence(
            [
                {
                    "status": 401,
                    "json": {
                        "status": 401,
                        "error_code": 3020,
                        "message": "Not logged in",
                    },
                    "headers": JSON,
                },
                {"json": load_fixture("me.json"), "headers": JSON},
            ]
        ),
    )
    recorder = Recorder()
    tokens = fresh_tokens()
    client = PelotonClient(session, tokens, recorder)

    user = await client.async_get_me()

    assert user.id == USER_ID
    assert len(token_requests(aioclient_mock.mock_calls)) == 1
    api_calls = [call for call in aioclient_mock.mock_calls if call[0].lower() == "get"]
    assert [bearer(call) for call in api_calls] == [
        tokens.access_token,
        recorder.calls[0].access_token,
    ]


async def test_concurrent_401s_refresh_once(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Several requests rejected with the same token cause a single refresh."""
    tokens = fresh_tokens()

    async def slow_token(method, url, data):
        # Yield so the other rejected requests reach the lock while this refresh runs.
        await asyncio.sleep(0)
        return AiohttpClientMockResponse(
            method, url, json=token_response(now=NOW, marker="2"), headers=JSON
        )

    aioclient_mock.post(TOKEN_URL, side_effect=slow_token)

    async def reject_original_token(method, url, data):
        # mock_calls[-1] is this request: it is recorded just before the call.
        sent_with = bearer(aioclient_mock.mock_calls[-1])
        # Yield so all three requests are sent before any of them refreshes.
        await asyncio.sleep(0)
        if sent_with == tokens.access_token:
            return AiohttpClientMockResponse(
                method, url, status=401, json={"error_code": 3020}, headers=JSON
            )
        return AiohttpClientMockResponse(
            method, url, json=load_fixture("me.json"), headers=JSON
        )

    aioclient_mock.get(ME_URL, side_effect=reject_original_token)
    client = PelotonClient(session, tokens)

    await asyncio.gather(*(client.async_get_me() for _ in range(3)))

    assert len(token_requests(aioclient_mock.mock_calls)) == 1
    sent = [bearer(call) for call in aioclient_mock.mock_calls if call[0] == "GET"]
    assert sent[:3] == [tokens.access_token] * 3
    assert len(sent) == 6


async def test_second_401_is_auth_error(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """If the refreshed token is rejected too, the user has to log in again."""
    aioclient_mock.post(TOKEN_URL, json=token_response(now=NOW), headers=JSON)
    aioclient_mock.get(ME_URL, status=401, json={"error_code": 3020}, headers=JSON)
    client = PelotonClient(session, fresh_tokens())

    with pytest.raises(PelotonAuthError) as exc_info:
        await client.async_get_me()

    assert len(token_requests(aioclient_mock.mock_calls)) == 1
    assert_no_token_values(str(exc_info.value), client.tokens)


async def test_revoked_refresh_token_is_auth_error(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected refresh token raises PelotonAuthError and keeps the old tokens."""
    aioclient_mock.post(
        TOKEN_URL,
        status=403,
        json={
            "error": "invalid_grant",
            "error_description": "Unknown or invalid refresh token.",
        },
        headers=JSON,
    )
    recorder = Recorder()
    tokens = expiring_tokens()
    client = PelotonClient(session, tokens, recorder)

    with pytest.raises(PelotonAuthError) as exc_info:
        await client.async_get_me()

    assert recorder.calls == []
    assert client.tokens == tokens
    assert_no_token_values(str(exc_info.value), tokens)


async def test_missing_refresh_token_is_auth_error(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without a refresh token an expiring access token cannot be renewed."""
    client = PelotonClient(session, PelotonTokens("old", None, NOW + 60, USER_ID))

    with pytest.raises(PelotonAuthError):
        await client.async_get_me()

    assert aioclient_mock.call_count == 0


async def test_refresh_network_error_with_expired_token(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A network failure refreshing an expired token is a connection error."""
    aioclient_mock.post(TOKEN_URL, exc=TimeoutError())
    tokens = PelotonTokens("old-access", "refresh-1", NOW - 1, USER_ID)
    client = PelotonClient(session, tokens)

    with pytest.raises(PelotonConnectionError) as exc_info:
        await client.async_get_me()

    assert aioclient_mock.call_count == 1
    assert_no_token_values(str(exc_info.value), tokens)


async def test_failed_proactive_refresh_uses_current_token(
    session: ClientSession,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A transient refresh failure keeps the still-valid token and pauses retries."""
    aioclient_mock.post(TOKEN_URL, status=503, text="unavailable", headers=TEXT)
    aioclient_mock.get(ME_URL, json=load_fixture("me.json"), headers=JSON)
    tokens = PelotonTokens("old-access", "refresh-1", NOW + 240, USER_ID)
    client = PelotonClient(session, tokens)

    await client.async_get_me()
    freezer.tick(REFRESH_RETRY_DELAY - 1)
    await client.async_get_me()

    assert len(token_requests(aioclient_mock.mock_calls)) == 1
    sent = [bearer(c) for c in aioclient_mock.mock_calls if c[0].lower() == "get"]
    assert sent == ["old-access", "old-access"]

    freezer.tick(2)
    await client.async_get_me()

    assert len(token_requests(aioclient_mock.mock_calls)) == 2


async def test_rate_limited_refresh_waits_for_retry_after(
    session: ClientSession,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A rate-limited proactive refresh is not retried before Retry-After."""
    aioclient_mock.post(
        TOKEN_URL, status=429, text="slow down", headers={**TEXT, "Retry-After": "120"}
    )
    aioclient_mock.get(ME_URL, json=load_fixture("me.json"), headers=JSON)
    client = PelotonClient(
        session, PelotonTokens("old-access", "refresh-1", NOW + 240, USER_ID)
    )

    await client.async_get_me()
    freezer.tick(REFRESH_RETRY_DELAY + 1)
    await client.async_get_me()

    assert len(token_requests(aioclient_mock.mock_calls)) == 1


async def test_failed_proactive_refresh_auth_error_raises(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected refresh token raises even while the access token still works."""
    aioclient_mock.post(
        TOKEN_URL, status=403, json={"error": "invalid_grant"}, headers=JSON
    )
    client = PelotonClient(
        session, PelotonTokens("old-access", "refresh-1", NOW + 240, USER_ID)
    )

    with pytest.raises(PelotonAuthError):
        await client.async_get_me()


async def test_failed_refresh_after_401_raises(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """After a 401 there is no token to fall back to, so a refresh failure raises."""
    aioclient_mock.post(TOKEN_URL, status=503, text="unavailable", headers=TEXT)
    aioclient_mock.get(ME_URL, status=401, json={"error_code": 3020}, headers=JSON)
    client = PelotonClient(session, fresh_tokens())

    with pytest.raises(PelotonConnectionError):
        await client.async_get_me()


async def test_failed_refresh_is_shared_with_waiting_requests(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Requests waiting on the lock reuse a failed refresh instead of repeating it."""

    async def slow_failure(method, url, data):
        await asyncio.sleep(0)
        return AiohttpClientMockResponse(
            method, url, status=503, text="unavailable", headers=TEXT
        )

    aioclient_mock.post(TOKEN_URL, side_effect=slow_failure)
    client = PelotonClient(
        session, PelotonTokens("old-access", "refresh-1", NOW - 1, USER_ID)
    )

    results = await asyncio.gather(
        *(client.async_get_me() for _ in range(5)), return_exceptions=True
    )

    assert all(isinstance(r, PelotonConnectionError) for r in results)
    assert len(token_requests(aioclient_mock.mock_calls)) == 1


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        (
            {"status": 404, "text": "<html>Not Found</html>", "headers": HTML},
            PelotonError,
        ),
        ({"status": 403, "json": {"error_code": 9}, "headers": JSON}, PelotonError),
        (
            {"status": 200, "text": "<html>Peloton</html>", "headers": HTML},
            PelotonError,
        ),
        ({"status": 200, "text": "{broken", "headers": JSON}, PelotonError),
        ({"status": 200, "text": "{}", "headers": TEXT}, PelotonError),
        (
            {"status": 502, "content": b"<html>\xff\xfe</html>", "headers": HTML},
            PelotonConnectionError,
        ),
        ({"status": 429, "text": "slow down", "headers": TEXT}, PelotonRateLimitError),
        (
            {"status": 403, "text": "error code: 1015", "headers": TEXT},
            PelotonRateLimitError,
        ),
        (
            {"status": 502, "text": "bad gateway", "headers": TEXT},
            PelotonConnectionError,
        ),
        ({"exc": ClientError()}, PelotonConnectionError),
        ({"exc": TimeoutError()}, PelotonConnectionError),
    ],
    ids=[
        "not_found",
        "forbidden",
        "html_200",
        "invalid_json",
        "json_body_text_content_type",
        "undecodable_bad_gateway",
        "http_429",
        "cloudflare_1015",
        "bad_gateway",
        "client_error",
        "timeout",
    ],
)
async def test_api_errors(
    session: ClientSession,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict,
    error: type[PelotonError],
) -> None:
    """API failures map to the right exception and never to an auth error."""
    aioclient_mock.get(ME_URL, **kwargs)
    client = PelotonClient(session, fresh_tokens())

    with pytest.raises(error) as exc_info:
        await client.async_get_me()

    assert type(exc_info.value) is error
    assert token_requests(aioclient_mock.mock_calls) == []
    assert_no_token_values(str(exc_info.value), client.tokens)


async def test_latest_workout(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The latest workout is one list request with the ride and instructor joined."""
    aioclient_mock.get(
        api_url(f"/api/user/{USER_ID}/workouts"),
        json=load_fixture("api/workouts.json"),
        headers=JSON,
    )
    client = PelotonClient(session, fresh_tokens())

    workout = await client.async_get_latest_workout()

    assert aioclient_mock.call_count == 1
    url = aioclient_mock.mock_calls[0][1]
    assert dict(url.query) == {
        "sort_by": "-created",
        "page": "0",
        "limit": "1",
        "joins": "ride,ride.instructor",
    }
    assert workout is not None
    assert workout.id == WORKOUT_ID
    assert workout.status == "COMPLETE"
    assert workout.ride is not None
    assert workout.ride.instructor_name == "Synthetic Instructor"
    # The list leaves these out.
    assert workout.total_work is None
    assert workout.leaderboard_rank is None


async def test_latest_workout_none(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """An account without workouts gives None instead of an error."""
    aioclient_mock.get(
        api_url(f"/api/user/{USER_ID}/workouts"),
        json=load_fixture("api/workouts_empty.json"),
        headers=JSON,
    )
    client = PelotonClient(session, fresh_tokens())

    assert await client.async_get_latest_workout() is None


async def test_user_id_from_api_me_when_token_has_none(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without the user id claim the client asks /api/me once and remembers it."""
    aioclient_mock.get(ME_URL, json=load_fixture("me.json"), headers=JSON)
    aioclient_mock.get(
        api_url(f"/api/user/{USER_ID}/settings"),
        json=load_fixture("settings.json"),
        headers=JSON,
    )
    client = PelotonClient(session, fresh_tokens(user_id=None))

    settings = await client.async_get_settings()
    await client.async_get_settings()

    assert settings.distance_unit == "imperial"
    assert [str(call[1]) for call in aioclient_mock.mock_calls] == [
        ME_URL,
        api_url(f"/api/user/{USER_ID}/settings"),
        api_url(f"/api/user/{USER_ID}/settings"),
    ]


async def test_workout_and_performance_graph(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Workout detail and performance graph requests use the expected parameters."""
    aioclient_mock.get(
        api_url(f"/api/workout/{WORKOUT_ID}"),
        json=load_fixture("api/workout.json"),
        headers=JSON,
    )
    aioclient_mock.get(
        api_url(f"/api/workout/{WORKOUT_ID}/performance_graph"),
        json=load_fixture("performance_graph.json"),
        headers=JSON,
    )
    client = PelotonClient(session, fresh_tokens())

    workout = await client.async_get_workout(WORKOUT_ID)
    graph = await client.async_get_performance_graph(WORKOUT_ID, every_n=50)

    assert workout.leaderboard_rank == 120
    assert workout.ftp == 200
    assert graph.metrics["heart_rate"].last == 148
    queries = [dict(call[1].query) for call in aioclient_mock.mock_calls]
    assert queries == [{"joins": "ride,ride.instructor"}, {"every_n": "50"}]


async def test_revoke(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The client revokes its refresh token."""
    aioclient_mock.post(REVOKE_URL, text="", headers=TEXT)
    client = PelotonClient(session, fresh_tokens())

    await client.async_revoke()

    assert aioclient_mock.mock_calls[0][2]["token"] == "refresh-1"


async def test_never_sends_password_grant(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Even when every token is rejected, the client never logs in with a password."""
    aioclient_mock.post(
        TOKEN_URL, status=403, json={"error": "invalid_grant"}, headers=JSON
    )
    aioclient_mock.get(ME_URL, status=401, json={"error_code": 3020}, headers=JSON)
    client = PelotonClient(session, fresh_tokens())

    for _ in range(3):
        with pytest.raises(PelotonAuthError):
            await client.async_get_me()

    grants = [p["grant_type"] for p in token_requests(aioclient_mock.mock_calls)]
    assert grants
    assert set(grants) == {"refresh_token"}


async def test_user_id_missing_everywhere(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """If neither the token nor /api/me has a user id, user endpoints fail clearly."""
    aioclient_mock.get(ME_URL, json={"username": "x"}, headers=JSON)
    client = PelotonClient(session, fresh_tokens(user_id=None))

    with pytest.raises(PelotonError, match="user id"):
        await client.async_get_latest_workout()


async def test_get_raw(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """async_get_raw returns the parsed JSON of any path."""
    aioclient_mock.get(api_url("/api/anything"), json={"a": 1}, headers=JSON)
    client = PelotonClient(session, fresh_tokens())

    assert await client.async_get_raw("/api/anything", {"x": 1}) == {"a": 1}


async def test_revoke_without_refresh_token(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without a refresh token there is nothing to revoke and no request is sent."""
    client = PelotonClient(
        session, PelotonTokens("access", None, NOW + ACCESS_TOKEN_LIFETIME, USER_ID)
    )

    await client.async_revoke()

    assert aioclient_mock.call_count == 0


async def test_user_id_from_refreshed_token(
    session: ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A refresh that supplies the user id saves the /api/me lookup."""
    aioclient_mock.post(TOKEN_URL, json=token_response(now=NOW), headers=JSON)
    aioclient_mock.get(
        api_url(f"/api/workout/{WORKOUT_ID}"),
        json=load_fixture("api/workout.json"),
        headers=JSON,
    )
    aioclient_mock.get(
        api_url(f"/api/user/{USER_ID}/settings"),
        json=load_fixture("settings.json"),
        headers=JSON,
    )
    client = PelotonClient(
        session, PelotonTokens("old-access", "refresh-1", NOW + 60, None)
    )

    await client.async_get_workout(WORKOUT_ID)
    await client.async_get_settings()

    assert ME_URL not in [str(call[1]) for call in aioclient_mock.mock_calls]
