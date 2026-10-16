"""Tests for the options flow, diagnostics, translations and icons."""

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.peloton.const import (
    CONF_ACTIVE_INTERVAL,
    CONF_IDLE_INTERVAL,
    CONF_MAX_WORKOUT_MINUTES,
)
from custom_components.peloton.sensor import SENSORS

from .common import setup_integration
from .conftest import USER_ID, USERNAME

COMPONENT = Path(__file__).parent.parent / "custom_components" / "peloton"


@pytest.mark.usefixtures("mock_api")
async def test_options_flow(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The options flow shows the defaults and stores whole numbers."""
    await setup_integration(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
    }
    assert suggested == {
        CONF_IDLE_INTERVAL: 15,
        CONF_ACTIVE_INTERVAL: 10,
        CONF_MAX_WORKOUT_MINUTES: 240,
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_IDLE_INTERVAL: 20.0,
            CONF_ACTIVE_INTERVAL: 5,
            CONF_MAX_WORKOUT_MINUTES: 90,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_IDLE_INTERVAL: 20,
        CONF_ACTIVE_INTERVAL: 5,
        CONF_MAX_WORKOUT_MINUTES: 90,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_IDLE_INTERVAL, 9),
        (CONF_IDLE_INTERVAL, 61),
        (CONF_ACTIVE_INTERVAL, 4),
        (CONF_ACTIVE_INTERVAL, 61),
        (CONF_MAX_WORKOUT_MINUTES, 29),
        (CONF_MAX_WORKOUT_MINUTES, 601),
    ],
)
@pytest.mark.usefixtures("mock_api")
async def test_options_flow_rejects_out_of_range(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, field: str, value: int
) -> None:
    """Values outside the allowed ranges are refused."""
    await setup_integration(hass, mock_config_entry)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    user_input = {
        CONF_IDLE_INTERVAL: 15,
        CONF_ACTIVE_INTERVAL: 10,
        CONF_MAX_WORKOUT_MINUTES: 240,
    } | {field: value}

    with pytest.raises(InvalidData, match=field):
        await hass.config_entries.options.async_configure(result["flow_id"], user_input)


@pytest.mark.usefixtures("mock_api")
async def test_diagnostics_hide_tokens_and_personal_data(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Diagnostics contain workout data but no tokens, ids or names."""
    await setup_integration(hass, mock_config_entry)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )
    text = json.dumps(diagnostics)

    for secret in (
        mock_config_entry.data["token"]["access_token"],
        mock_config_entry.data["token"]["refresh_token"],
        USER_ID,
        USERNAME,
        "Test",
        "https://example.invalid/ride.png",
    ):
        assert secret not in text
    assert diagnostics["coordinator"]["last_update_success"] is True
    assert diagnostics["data"]["workout"]["status"] == "COMPLETE"
    assert (
        diagnostics["data"]["performance_graph"]["metrics"]["cadence"]["average"] == 85
    )


def test_every_entity_has_a_name_and_icon() -> None:
    """Every translation key used by an entity has a name and an icon."""
    strings = json.loads((COMPONENT / "strings.json").read_text())["entity"]
    icons = json.loads((COMPONENT / "icons.json").read_text())["entity"]

    sensor_keys = {description.translation_key for description in SENSORS}
    assert sensor_keys == set(strings["sensor"])
    assert sensor_keys == set(icons["sensor"])
    assert set(strings["binary_sensor"]) == {"workout"}
    assert set(icons["binary_sensor"]) == {"workout"}
