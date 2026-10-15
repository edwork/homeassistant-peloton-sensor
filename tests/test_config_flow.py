"""Tests for the Peloton config flow.

These describe the flow as it behaves with pylotoncycle today. Roadmap phase 2
replaces the flow (token storage, user id as unique_id, reauth without account
switching) and updates these tests with it.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pylotoncycle.pylotoncycle import PelotonLoginException
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout

from custom_components.peloton.const import DOMAIN

from .conftest import PASSWORD, USERNAME

USER_INPUT = {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}


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


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow(hass: HomeAssistant, mock_peloton: MagicMock) -> None:
    """A valid login creates an entry.

    The title uses the username Peloton returns; the unique_id is the login
    exactly as typed (here an email address).
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    login = {CONF_USERNAME: "rider@example.invalid", CONF_PASSWORD: PASSWORD}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], login)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Peloton: {USERNAME}"
    assert result["data"] == login
    assert result["result"].unique_id == "rider@example.invalid"
    mock_peloton.assert_called_once_with("rider@example.invalid", PASSWORD)


@pytest.mark.usefixtures("mock_setup_entry")
@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        # Code path only: pylotoncycle 0.9.1 never raises PelotonLoginException.
        (PelotonLoginException, "invalid_auth"),
        (Timeout, "cannot_connect"),
        # Current behaviour: the flow catches the builtin ConnectionError, but
        # requests raises its own ConnectionError (an OSError subclass), so a
        # DNS or network failure shows "unknown".
        (RequestsConnectionError, "unknown"),
        # Current behaviour: pylotoncycle 0.9.1 raises a plain Exception for a
        # wrong password, so users see "unknown" rather than "invalid_auth".
        (Exception, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_peloton: MagicMock,
    side_effect: type[Exception],
    error: str,
) -> None:
    """Login errors are shown on the form and the user can retry."""
    client = mock_peloton.return_value
    mock_peloton.side_effect = side_effect
    mock_peloton.return_value = None

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_peloton.side_effect = None
    mock_peloton.return_value = client
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_peloton", "mock_setup_entry")
async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The same username cannot be added twice."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_peloton")
async def test_reauth_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    """Reauth stores the new credentials and reloads the entry."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    new_input = {CONF_USERNAME: USERNAME, CONF_PASSWORD: "a-new-password"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], new_input
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == new_input
    assert mock_config_entry.unique_id == USERNAME
    mock_setup_entry.assert_called_once()


@pytest.mark.usefixtures("mock_peloton", "mock_setup_entry")
async def test_reauth_flow_switches_account(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Current behaviour: reauth accepts a different account.

    The entry keeps its old unique_id but now holds another account's login.
    Roadmap phase 2 aborts with "wrong_account" instead.
    """
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    other = {CONF_USERNAME: "someoneelse", CONF_PASSWORD: "a-new-password"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], other)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == other
    assert mock_config_entry.unique_id == USERNAME
