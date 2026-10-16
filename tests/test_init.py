"""Tests for setup, migration, token handling and polling."""

from datetime import timedelta
import time
from typing import Any

from aiohttp import ClientError
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.api.const import (
    API_BASE,
    REFRESH_MARGIN,
    REVOKE_URL,
    TOKEN_URL,
)
from custom_components.peloton.const import (
    DOMAIN,
    PROFILE_REFRESH_INTERVAL,
    SCAN_INTERVAL,
)

from .common import advance, setup_integration
from .conftest import (
    JSON_HEADERS,
    PASSWORD,
    USER_ID,
    USERNAME,
    WORKOUT_ID,
    load_fixture,
    stored_tokens,
)
from .peloton_api import TEXT, token_requests, token_response

WORKOUTS_URL = f"{API_BASE}/api/user/{USER_ID}/workouts"
WORKOUT_URL = f"{API_BASE}/api/workout/{WORKOUT_ID}"
ME_URL = f"{API_BASE}/api/me"


def grants(aioclient_mock: AiohttpClientMocker) -> list[str]:
    """Return the grant types sent to the token endpoint, in order."""
    return [p["grant_type"] for p in token_requests(aioclient_mock.mock_calls)]


def gets(aioclient_mock: AiohttpClientMocker) -> list[str]:
    """Return the URLs (without query) of the API GET requests, in order."""
    return [
        str(call[1].with_query(None))
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "get"
    ]


def reauth_flows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return the reauth flows in progress."""
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == SOURCE_REAUTH
    ]


async def test_setup_uses_stored_tokens(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Setup with valid stored tokens sends no token request at all."""
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert grants(mock_api) == []
    # Profile and settings once, then the latest workout with its details.
    assert gets(mock_api)[:5] == [
        ME_URL,
        f"{API_BASE}/api/user/{USER_ID}/settings",
        WORKOUTS_URL,
        WORKOUT_URL,
        f"{WORKOUT_URL}/performance_graph",
    ]


async def test_restart_does_not_log_in(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Unloading and setting up again reuses the stored tokens."""
    await setup_integration(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert grants(mock_api) == []


@pytest.mark.parametrize(
    "token_json", [token_response(now=time.time(), refresh_token=None)]
)
async def test_expiring_token_is_refreshed_and_saved(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """A token close to expiry is refreshed at setup and the new one is stored."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id=USER_ID,
        data={
            CONF_USERNAME: USERNAME,
            CONF_TOKEN: stored_tokens(expires_at=time.time() + REFRESH_MARGIN - 1),
        },
    )
    old_access_token = entry.data[CONF_TOKEN]["access_token"]

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert grants(mock_api) == ["refresh_token"]
    saved = entry.data[CONF_TOKEN]
    assert saved["access_token"] != old_access_token
    assert saved["refresh_token"] == "stored-refresh"
    assert saved["expires_at"] > time.time() + REFRESH_MARGIN


async def test_polling_cost(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """While the latest workout is complete, each poll is a single request."""
    await setup_integration(hass, mock_config_entry)
    mock_api.mock_calls.clear()

    for _ in range(3):
        await advance(hass, freezer)

    assert gets(mock_api) == [WORKOUTS_URL] * 3
    assert grants(mock_api) == []


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [
        (
            load_fixture("api/workouts.json")
            | {
                "data": [
                    load_fixture("api/workouts.json")["data"][0]
                    | {"status": "IN_PROGRESS", "end_time": None}
                ]
            },
            load_fixture("api/workout.json")
            | {"status": "IN_PROGRESS", "end_time": None},
        )
    ],
    ids=["in_progress"],
)
async def test_polling_during_workout(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """While a workout is in progress, every poll fetches its details."""
    await setup_integration(hass, mock_config_entry)
    mock_api.mock_calls.clear()

    await advance(hass, freezer)

    assert gets(mock_api) == [
        WORKOUTS_URL,
        WORKOUT_URL,
        f"{WORKOUT_URL}/performance_graph",
    ]


async def test_new_workout_refreshes_details_and_profile(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A status change refetches the workout and the profile (new counts)."""
    await setup_integration(hass, mock_config_entry)
    running = load_fixture("api/workouts.json")
    running["data"][0] |= {"status": "IN_PROGRESS"}
    mock_api.clear_requests()
    mock_api.get(WORKOUTS_URL, json=running, headers=JSON_HEADERS)
    mock_api.get(ME_URL, json=load_fixture("me.json"), headers=JSON_HEADERS)
    mock_api.get(
        f"{API_BASE}/api/user/{USER_ID}/settings",
        json=load_fixture("settings.json"),
        headers=JSON_HEADERS,
    )
    mock_api.get(
        f"{WORKOUT_URL}/performance_graph",
        json=load_fixture("performance_graph.json"),
        headers=JSON_HEADERS,
    )
    mock_api.get(
        WORKOUT_URL,
        json=load_fixture("api/workout.json") | {"status": "IN_PROGRESS"},
        headers=JSON_HEADERS,
    )

    await advance(hass, freezer)

    assert sorted(set(gets(mock_api))) == sorted(
        {
            WORKOUTS_URL,
            WORKOUT_URL,
            f"{WORKOUT_URL}/performance_graph",
            ME_URL,
            f"{API_BASE}/api/user/{USER_ID}/settings",
        }
    )


async def test_profile_refreshed_hourly(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The profile, settings and cached workout are refreshed every hour."""
    await setup_integration(hass, mock_config_entry)
    mock_api.mock_calls.clear()

    await advance(hass, freezer, PROFILE_REFRESH_INTERVAL)

    assert ME_URL in gets(mock_api)
    assert WORKOUT_URL in gets(mock_api)


@pytest.mark.parametrize("workouts_json", [load_fixture("api/workouts_empty.json")])
async def test_no_workouts_sets_up(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """An account without workouts sets up normally."""
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert WORKOUT_URL not in gets(mock_api)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exc": ClientError()},
        {"status": 503, "text": "unavailable", "headers": TEXT},
        {"status": 429, "text": "slow down", "headers": TEXT},
    ],
    ids=["network", "server_error", "rate_limited"],
)
async def test_connection_error_at_setup_retries(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict[str, Any],
) -> None:
    """Network trouble at startup leaves the entry retrying, not failed."""
    aioclient_mock.get(ME_URL, **kwargs)

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert grants(aioclient_mock) == []
    # Home Assistant 2026.3 does not pass the translation key of a failed first
    # refresh on to the entry; later releases do.
    if mock_config_entry.error_reason_translation_key is not None:
        assert mock_config_entry.error_reason_translation_key == "update_failed"
        assert mock_config_entry.reason.startswith("Error fetching data from Peloton: ")


async def test_rejected_refresh_token_starts_one_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A revoked refresh token starts one reauth flow and stops polling."""
    await setup_integration(hass, mock_config_entry)
    mock_api.clear_requests()
    mock_api.get(
        WORKOUTS_URL, status=401, json={"error_code": 3020}, headers=JSON_HEADERS
    )
    mock_api.post(
        TOKEN_URL,
        status=403,
        json={"error": "invalid_grant"},
        headers=JSON_HEADERS,
    )

    await advance(hass, freezer)
    assert len(reauth_flows(hass)) == 1
    requests_after_failure = len(mock_api.mock_calls)

    for _ in range(5):
        await advance(hass, freezer)

    assert len(mock_api.mock_calls) == requests_after_failure
    assert len(reauth_flows(hass)) == 1
    assert "password" not in grants(mock_api)


async def test_second_401_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A token rejected again after a successful refresh starts reauth."""
    await setup_integration(hass, mock_config_entry)
    mock_api.clear_requests()
    mock_api.get(
        WORKOUTS_URL, status=401, json={"error_code": 3020}, headers=JSON_HEADERS
    )
    mock_api.post(TOKEN_URL, json=token_response(now=time.time()), headers=JSON_HEADERS)

    await advance(hass, freezer)

    assert len(reauth_flows(hass)) == 1
    assert grants(mock_api) == ["refresh_token"]


async def test_unusable_stored_tokens_start_reauth(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """Corrupt stored tokens lead to reauth instead of a crash."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id=USER_ID,
        data={CONF_USERNAME: USERNAME, CONF_TOKEN: {"refresh_token": "x"}},
    )

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1
    assert grants(mock_api) == []


async def test_migrate_v2_entry(
    hass: HomeAssistant,
    mock_config_entry_v2: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """An old entry logs in once, then stores tokens instead of the password."""
    await setup_integration(hass, mock_config_entry_v2)

    entry = mock_config_entry_v2
    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 3
    assert entry.unique_id == USER_ID
    assert set(entry.data) == {CONF_USERNAME, CONF_TOKEN}
    assert entry.data[CONF_TOKEN]["refresh_token"] == "refresh-1"
    assert PASSWORD not in str(entry.data)
    assert grants(mock_api) == ["password"]

    # Later setups use the tokens.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert grants(mock_api) == ["password"]


async def test_migrate_v2_keeps_unique_id_if_taken(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_config_entry_v2: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """If another entry already uses the user id, the old unique_id stays."""
    mock_config_entry.add_to_hass(hass)

    await setup_integration(hass, mock_config_entry_v2)

    assert mock_config_entry_v2.unique_id == USERNAME
    assert CONF_PASSWORD not in mock_config_entry_v2.data


@pytest.mark.parametrize(
    ("kwargs", "state", "reason"),
    [
        (
            {"exc": ClientError()},
            ConfigEntryState.SETUP_RETRY,
            ("cannot_connect", "Could not reach Peloton: "),
        ),
        (
            {
                "status": 429,
                "json": {"error": "too_many_attempts"},
                "headers": JSON_HEADERS,
            },
            ConfigEntryState.SETUP_RETRY,
            ("rate_limited", "Peloton is limiting login attempts"),
        ),
        (
            {
                "status": 401,
                "json": {"error": "invalid_client"},
                "headers": JSON_HEADERS,
            },
            ConfigEntryState.SETUP_RETRY,
            ("cannot_connect", "Could not reach Peloton: "),
        ),
        (
            {
                "status": 403,
                "json": {"error": "invalid_grant"},
                "headers": JSON_HEADERS,
            },
            ConfigEntryState.SETUP_ERROR,
            ("auth_failed", "The stored Peloton login is no longer valid"),
        ),
    ],
    ids=["network", "rate_limited", "client_rejected", "wrong_password"],
)
async def test_migrate_v2_login_errors(
    hass: HomeAssistant,
    mock_config_entry_v2: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict[str, Any],
    state: ConfigEntryState,
    reason: tuple[str, str],
) -> None:
    """Migration errors retry later, or start reauth for a rejected password."""
    aioclient_mock.post(TOKEN_URL, **kwargs)

    await setup_integration(hass, mock_config_entry_v2)

    assert mock_config_entry_v2.state is state
    expect_reauth = state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == int(expect_reauth)
    # A rejected password is deleted at once; others are kept for the retry.
    assert (CONF_PASSWORD in mock_config_entry_v2.data) is not expect_reauth
    if not expect_reauth:
        assert mock_config_entry_v2.error_reason_translation_key == reason[0]
        assert mock_config_entry_v2.reason.startswith(reason[1])
        assert "{" not in mock_config_entry_v2.reason


async def test_rejected_migration_password_is_not_sent_again(
    hass: HomeAssistant,
    mock_config_entry_v2: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """After a rejected migration login, reloads send no password grant."""
    aioclient_mock.post(
        TOKEN_URL, status=403, json={"error": "invalid_grant"}, headers=JSON_HEADERS
    )
    await setup_integration(hass, mock_config_entry_v2)
    assert grants(aioclient_mock) == ["password"]

    await hass.config_entries.async_reload(mock_config_entry_v2.entry_id)
    await hass.async_block_till_done()

    assert grants(aioclient_mock) == ["password"]
    assert mock_config_entry_v2.state is ConfigEntryState.SETUP_ERROR


@pytest.mark.parametrize("token_json", [token_response(now=time.time(), user_id=None)])
async def test_migrate_v2_user_id_from_profile(
    hass: HomeAssistant,
    mock_config_entry_v2: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Migration reads the user id from /api/me if the token lacks it."""
    await setup_integration(hass, mock_config_entry_v2)

    assert mock_config_entry_v2.unique_id == USER_ID
    assert mock_config_entry_v2.data[CONF_TOKEN]["user_id"] == USER_ID


async def test_migrate_v2_without_password_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An old entry without a password cannot migrate silently."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, unique_id=USERNAME, data={CONF_USERNAME: USERNAME}
    )

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1
    assert aioclient_mock.call_count == 0


async def test_migrate_v1_entry(
    hass: HomeAssistant, mock_api: AiohttpClientMocker
) -> None:
    """Version 1 entries go through version 2 to 3."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )

    await setup_integration(hass, entry)

    assert entry.version == 3
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == USER_ID


async def test_downgrade_is_refused(hass: HomeAssistant) -> None:
    """Entries from a newer version of the integration are not loaded."""
    entry = MockConfigEntry(domain=DOMAIN, version=4, data={})

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_remove_entry_revokes_refresh_token(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
) -> None:
    """Deleting the entry revokes its refresh token."""
    await setup_integration(hass, mock_config_entry)

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    revokes = [c for c in mock_api.mock_calls if str(c[1]) == REVOKE_URL]
    assert len(revokes) == 1
    assert revokes[0][2]["token"] == "stored-refresh"


async def test_remove_entry_ignores_revoke_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed revoke does not stop the entry from being removed."""
    await setup_integration(hass, mock_config_entry)
    aioclient_mock.clear_requests()
    aioclient_mock.post(REVOKE_URL, exc=ClientError())

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(mock_config_entry.entry_id) is None
    assert aioclient_mock.call_count == 1
    assert "Error calling entry remove callback" not in caplog.text


async def test_remove_entry_without_tokens(
    hass: HomeAssistant,
    mock_config_entry_v2: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Removing an entry that never got tokens sends nothing."""
    mock_config_entry_v2.add_to_hass(hass)

    await hass.config_entries.async_remove(mock_config_entry_v2.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(mock_config_entry_v2.entry_id) is None
    assert aioclient_mock.call_count == 0
    assert "Error calling entry remove callback" not in caplog.text


async def test_scan_interval() -> None:
    """Polling stays at 10 seconds until adaptive polling (phase 3)."""
    assert timedelta(seconds=10) == SCAN_INTERVAL


async def test_rejected_token_at_setup_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Stored tokens that Peloton rejects at startup lead to reauth."""
    aioclient_mock.get(
        ME_URL, status=401, json={"error_code": 3020}, headers=JSON_HEADERS
    )
    aioclient_mock.post(
        TOKEN_URL, status=403, json={"error": "invalid_grant"}, headers=JSON_HEADERS
    )

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1
    assert "password" not in grants(aioclient_mock)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exc": ClientError()},
        {"status": 503, "text": "unavailable", "headers": TEXT},
        {"status": 429, "text": "slow down", "headers": TEXT},
    ],
    ids=["network", "server_error", "rate_limited"],
)
async def test_transient_poll_error_keeps_polling(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    kwargs: dict[str, Any],
) -> None:
    """A temporary failure while polling neither starts reauth nor stops polling."""
    await setup_integration(hass, mock_config_entry)
    mock_api.clear_requests()
    mock_api.get(WORKOUTS_URL, **kwargs)

    await advance(hass, freezer)
    assert mock_config_entry.runtime_data.last_update_success is False
    calls = len(mock_api.mock_calls)

    await advance(hass, freezer)
    assert len(mock_api.mock_calls) > calls
    assert reauth_flows(hass) == []
    assert grants(mock_api) == []


def _register(mock: AiohttpClientMocker, workouts: Any, workout: Any) -> None:
    """Register the API endpoints with the given workout list and detail."""
    mock.get(WORKOUTS_URL, json=workouts, headers=JSON_HEADERS)
    mock.get(ME_URL, json=load_fixture("me.json"), headers=JSON_HEADERS)
    mock.get(
        f"{API_BASE}/api/user/{USER_ID}/settings",
        json=load_fixture("settings.json"),
        headers=JSON_HEADERS,
    )
    mock.get(
        f"{WORKOUT_URL}/performance_graph",
        json=load_fixture("performance_graph.json"),
        headers=JSON_HEADERS,
    )
    mock.get(WORKOUT_URL, json=workout, headers=JSON_HEADERS)


def _running() -> tuple[dict[str, Any], dict[str, Any]]:
    workouts = load_fixture("api/workouts.json")
    workouts["data"][0] |= {"status": "IN_PROGRESS", "end_time": None}
    workout = load_fixture("api/workout.json") | {
        "status": "IN_PROGRESS",
        "end_time": None,
    }
    return workouts, workout


async def test_workout_completion_refetches_once(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """IN_PROGRESS to COMPLETE refetches details and profile once, then idles."""
    _register(aioclient_mock, *_running())
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.data.workout.is_in_progress

    aioclient_mock.clear_requests()
    _register(
        aioclient_mock,
        load_fixture("api/workouts.json"),
        load_fixture("api/workout.json"),
    )
    await advance(hass, freezer)

    assert not mock_config_entry.runtime_data.data.workout.is_in_progress
    assert gets(aioclient_mock) == [
        WORKOUTS_URL,
        WORKOUT_URL,
        f"{WORKOUT_URL}/performance_graph",
        ME_URL,
        f"{API_BASE}/api/user/{USER_ID}/settings",
    ]

    aioclient_mock.mock_calls.clear()
    await advance(hass, freezer)
    assert gets(aioclient_mock) == [WORKOUTS_URL]


async def test_completion_seen_when_list_and_detail_disagree(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A workout that ends between the list and detail reads is still seen as ended."""
    running_list, _ = _running()
    # The list still says running; the detail fetched right after says complete.
    _register(aioclient_mock, running_list, load_fixture("api/workout.json"))
    await setup_integration(hass, mock_config_entry)

    aioclient_mock.clear_requests()
    _register(
        aioclient_mock,
        load_fixture("api/workouts.json"),
        load_fixture("api/workout.json"),
    )
    await advance(hass, freezer)

    assert ME_URL in gets(aioclient_mock)
    assert WORKOUT_URL in gets(aioclient_mock)


async def test_latest_workout_disappears(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """If the only workout is deleted, the profile is refreshed once."""
    _register(
        aioclient_mock,
        load_fixture("api/workouts.json"),
        load_fixture("api/workout.json"),
    )
    await setup_integration(hass, mock_config_entry)

    aioclient_mock.clear_requests()
    _register(
        aioclient_mock,
        load_fixture("api/workouts_empty.json"),
        load_fixture("api/workout.json"),
    )
    await advance(hass, freezer)

    assert mock_config_entry.runtime_data.data.workout is None
    assert gets(aioclient_mock) == [
        WORKOUTS_URL,
        ME_URL,
        f"{API_BASE}/api/user/{USER_ID}/settings",
    ]

    aioclient_mock.mock_calls.clear()
    await advance(hass, freezer)
    assert gets(aioclient_mock) == [WORKOUTS_URL]
