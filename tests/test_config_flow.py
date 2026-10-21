"""Tests for the Peloton config flow."""

from collections.abc import AsyncGenerator
import time
from typing import Any
from unittest.mock import AsyncMock, patch

from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.api.const import API_BASE, REVOKE_URL, TOKEN_URL
from custom_components.peloton.const import DOMAIN

from .conftest import JSON_HEADERS, PASSWORD, USER_ID, USERNAME, load_fixture
from .peloton_api import TEXT, token_requests, token_response

USER_INPUT = {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
OTHER_USER_ID = "99999999999999999999999999999999"


@pytest.fixture
async def mock_setup_entry(hass: HomeAssistant) -> AsyncGenerator[AsyncMock]:
    """Skip integration setup and unload around the flow."""
    with (
        patch(
            "custom_components.peloton.async_setup_entry", return_value=True
        ) as mock_setup,
        patch("custom_components.peloton.async_unload_entry", return_value=True),
    ):
        yield mock_setup
        # Unload while patched; Home Assistant's own teardown runs later.
        for entry in hass.config_entries.async_entries(DOMAIN):
            await hass.config_entries.async_unload(entry.entry_id)


def mock_login(aioclient_mock: AiohttpClientMocker, **kwargs: Any) -> None:
    """Answer the token endpoint; kwargs override the successful response."""
    aioclient_mock.clear_requests()
    if not kwargs:
        kwargs = {"json": token_response(now=time.time()), "headers": JSON_HEADERS}
    aioclient_mock.post(TOKEN_URL, **kwargs)
    aioclient_mock.post(REVOKE_URL, text="", headers=TEXT)
    aioclient_mock.get(
        f"{API_BASE}/api/me", json=load_fixture("me.json"), headers=JSON_HEADERS
    )


def password_grants(aioclient_mock: AiohttpClientMocker) -> int:
    """Return how many password logins were sent."""
    return sum(
        1
        for payload in token_requests(aioclient_mock.mock_calls)
        if payload["grant_type"] == "password"
    )


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A valid login creates an entry with tokens and no password."""
    mock_login(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    login = {CONF_USERNAME: " rider@example.invalid ", CONF_PASSWORD: PASSWORD}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], login)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Peloton: {USERNAME}"
    entry = result["result"]
    assert entry.unique_id == USER_ID
    assert entry.version == 3
    assert set(entry.data) == {CONF_USERNAME, CONF_TOKEN}
    assert entry.data[CONF_USERNAME] == "rider@example.invalid"
    assert entry.data[CONF_TOKEN]["refresh_token"] == "refresh-1"
    assert entry.data[CONF_TOKEN]["user_id"] == USER_ID
    assert PASSWORD not in str(entry.data)
    assert password_grants(aioclient_mock) == 1


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_title_falls_back_to_login(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """If the profile cannot be read, the title uses the login name."""
    aioclient_mock.post(
        TOKEN_URL, json=token_response(now=time.time()), headers=JSON_HEADERS
    )
    aioclient_mock.get(f"{API_BASE}/api/me", exc=ClientError())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Peloton: {USERNAME}"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_user_id_from_profile(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A token without the user id claim gets the id from /api/me."""
    mock_login(
        aioclient_mock,
        json=token_response(now=time.time(), user_id=None),
        headers=JSON_HEADERS,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == USER_ID
    assert result["result"].data[CONF_TOKEN]["user_id"] == USER_ID


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        (
            {
                "status": 403,
                "json": {"error": "invalid_grant"},
                "headers": JSON_HEADERS,
            },
            "invalid_auth",
        ),
        (
            {"status": 403, "json": {"error": "mfa_required"}, "headers": JSON_HEADERS},
            "mfa_required",
        ),
        (
            {
                "status": 429,
                "json": {"error": "too_many_attempts"},
                "headers": JSON_HEADERS,
            },
            "rate_limited",
        ),
        ({"status": 503, "text": "unavailable", "headers": TEXT}, "cannot_connect"),
        ({"exc": ClientError()}, "cannot_connect"),
        (
            {
                "status": 401,
                "json": {"error": "invalid_client"},
                "headers": JSON_HEADERS,
            },
            "unknown",
        ),
    ],
    ids=[
        "wrong_password",
        "mfa",
        "rate_limited",
        "server_error",
        "network",
        "client_rejected",
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict[str, Any],
    error: str,
) -> None:
    """Login errors are shown on the form, and the user can retry."""
    mock_login(aioclient_mock, **kwargs)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert password_grants(aioclient_mock) == 1

    mock_login(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_profile_error_without_user_id(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without a user id in the token or profile, the flow cannot continue."""
    aioclient_mock.post(
        TOKEN_URL,
        json=token_response(now=time.time(), user_id=None),
        headers=JSON_HEADERS,
    )
    aioclient_mock.get(f"{API_BASE}/api/me", json={}, headers=JSON_HEADERS)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )

    assert result["errors"] == {"base": "unknown"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same account cannot be added twice, even with a different login name."""
    mock_config_entry.add_to_hass(hass)
    mock_login(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_USERNAME: "rider@example.invalid", CONF_PASSWORD: PASSWORD},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry_v2: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """Reauth asks for the password only, stores tokens and drops the password."""
    mock_config_entry_v2.add_to_hass(hass)
    mock_login(aioclient_mock)

    result = await mock_config_entry_v2.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"][CONF_USERNAME] == USERNAME
    assert list(result["data_schema"].schema) == [CONF_PASSWORD]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "a-new-password"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert set(mock_config_entry_v2.data) == {CONF_USERNAME, CONF_TOKEN}
    assert mock_config_entry_v2.data[CONF_USERNAME] == USERNAME
    assert mock_config_entry_v2.unique_id == USER_ID
    assert token_requests(aioclient_mock.mock_calls)[0]["password"] == "a-new-password"
    mock_setup_entry.assert_called_once()


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_flow_wrong_account(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reauth refuses a login that belongs to another account."""
    mock_config_entry.add_to_hass(hass)
    stored = dict(mock_config_entry.data)
    mock_login(
        aioclient_mock,
        json=token_response(now=time.time(), user_id=OTHER_USER_ID),
        headers=JSON_HEADERS,
    )

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert dict(mock_config_entry.data) == stored


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_flow_error_then_success(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A wrong password in reauth shows an error and can be corrected."""
    mock_config_entry.add_to_hass(hass)
    mock_login(
        aioclient_mock,
        status=403,
        json={"error": "invalid_grant"},
        headers=JSON_HEADERS,
    )

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_login(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["reason"] == "reauth_successful"


async def test_reconfigure_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """Reconfigure logs in again with the same account and a new login name."""
    mock_config_entry.add_to_hass(hass)
    mock_login(aioclient_mock)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "  rider@example.invalid ", CONF_PASSWORD: PASSWORD},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert set(mock_config_entry.data) == {CONF_USERNAME, CONF_TOKEN}
    assert PASSWORD not in str(mock_config_entry.data)
    assert password_grants(aioclient_mock) == 1
    assert mock_config_entry.data[CONF_USERNAME] == "rider@example.invalid"
    assert mock_config_entry.data[CONF_TOKEN]["refresh_token"] == "refresh-1"
    mock_setup_entry.assert_called_once()


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_flow_wrong_account(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfigure cannot switch the entry to another account."""
    mock_config_entry.add_to_hass(hass)
    mock_login(
        aioclient_mock,
        json=token_response(now=time.time(), user_id=OTHER_USER_ID),
        headers=JSON_HEADERS,
    )

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "someoneelse", CONF_PASSWORD: PASSWORD}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert mock_config_entry.data[CONF_USERNAME] == USERNAME


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_flow_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfigure shows login errors on its form."""
    mock_config_entry.add_to_hass(hass)
    mock_login(aioclient_mock, exc=ClientError())

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


def revoked_tokens(aioclient_mock: AiohttpClientMocker) -> list[str]:
    """Return the refresh tokens sent to the revocation endpoint."""
    return [
        call[2]["token"]
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "post" and str(call[1]) == REVOKE_URL
    ]


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize("login", ["testrider", " TestRider "])
async def test_user_flow_existing_login_name_needs_no_login(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry_v2: MockConfigEntry,
    login: str,
) -> None:
    """An entry keyed by the same login name aborts before any password login."""
    mock_config_entry_v2.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_USERNAME: login, CONF_PASSWORD: PASSWORD},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_abort_revokes_new_token(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Tokens from a login the flow does not keep are revoked."""
    mock_config_entry.add_to_hass(hass)
    mock_login(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_USERNAME: "rider@example.invalid", CONF_PASSWORD: PASSWORD},
    )

    assert result["reason"] == "already_configured"
    assert revoked_tokens(aioclient_mock) == ["refresh-1"]


async def test_reauth_flow_revokes_old_token(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """A successful reauth revokes the refresh token it replaces."""
    mock_config_entry.add_to_hass(hass)
    mock_login(aioclient_mock)

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    assert result["reason"] == "reauth_successful"
    assert revoked_tokens(aioclient_mock) == ["stored-refresh"]
    assert mock_config_entry.data[CONF_TOKEN]["refresh_token"] == "refresh-1"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_wrong_account_revokes_new_token(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The tokens of a refused account are revoked."""
    mock_config_entry.add_to_hass(hass)
    mock_login(
        aioclient_mock,
        json=token_response(now=time.time(), user_id=OTHER_USER_ID),
        headers=JSON_HEADERS,
    )

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    assert result["reason"] == "wrong_account"
    assert revoked_tokens(aioclient_mock) == ["refresh-1"]


async def test_reauth_repairs_entry_whose_migration_failed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry_v2: MockConfigEntry,
) -> None:
    """A pre-version-3 entry whose password was rejected can be repaired by reauth."""
    aioclient_mock.post(
        TOKEN_URL, status=403, json={"error": "invalid_grant"}, headers=JSON_HEADERS
    )
    mock_config_entry_v2.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry_v2.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry_v2.unique_id == USERNAME
    flow = next(
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"]["source"] == "reauth"
    )

    mock_login(aioclient_mock)
    with patch("custom_components.peloton.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {CONF_PASSWORD: "the-current-password"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry_v2.unique_id == USER_ID
    assert set(mock_config_entry_v2.data) == {CONF_USERNAME, CONF_TOKEN}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_legacy_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry_v2: MockConfigEntry,
) -> None:
    """A legacy entry can be reconfigured with its own login name only."""
    mock_config_entry_v2.add_to_hass(hass)
    mock_login(aioclient_mock)

    result = await mock_config_entry_v2.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "someoneelse", CONF_PASSWORD: PASSWORD}
    )
    assert result["reason"] == "wrong_account"

    mock_login(aioclient_mock)
    result = await mock_config_entry_v2.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "TESTRIDER", CONF_PASSWORD: PASSWORD}
    )
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry_v2.unique_id == USER_ID


@pytest.mark.usefixtures("mock_setup_entry")
async def test_legacy_reauth_when_account_has_another_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_config_entry_v2: MockConfigEntry,
) -> None:
    """A legacy entry for an account that already has an entry is not merged."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry_v2.add_to_hass(hass)
    mock_login(aioclient_mock)

    result = await mock_config_entry_v2.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    assert result["reason"] == "already_configured"
    assert mock_config_entry_v2.unique_id == USERNAME


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_keeps_typed_username_after_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """After an error the form shows the login name the user typed."""
    mock_config_entry.add_to_hass(hass)
    mock_login(aioclient_mock, exc=ClientError())

    result = await mock_config_entry.start_reconfigure_flow(hass)
    first_form_default = _suggested(result, CONF_USERNAME)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "rider@example.invalid", CONF_PASSWORD: PASSWORD},
    )

    assert first_form_default == USERNAME
    assert _suggested(result, CONF_USERNAME) == "rider@example.invalid"
    assert _suggested(result, CONF_PASSWORD) is None


def _suggested(result: Any, field: str) -> Any:
    """Return the suggested value of a form field."""
    for key in result["data_schema"].schema:
        if key == field:
            return (key.description or {}).get("suggested_value")
    raise AssertionError(field)


@pytest.mark.usefixtures("mock_setup_entry")
async def test_failed_revoke_does_not_break_the_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """If revoking a discarded token fails, the flow still finishes."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(
        TOKEN_URL, json=token_response(now=time.time()), headers=JSON_HEADERS
    )
    aioclient_mock.post(REVOKE_URL, exc=ClientError())
    aioclient_mock.get(
        f"{API_BASE}/api/me", json=load_fixture("me.json"), headers=JSON_HEADERS
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_USERNAME: "rider@example.invalid", CONF_PASSWORD: PASSWORD},
    )

    assert result["reason"] == "already_configured"
