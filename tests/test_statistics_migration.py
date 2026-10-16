"""Long-term statistics recorded by earlier versions keep working."""

from datetime import timedelta
from functools import partial
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    get_metadata,
    update_statistics_issues,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
    do_adhoc_statistics,
)

from custom_components.peloton.const import DOMAIN

from .common import setup_integration
from .conftest import USER_ID

ENTITY_ID = "sensor.test_on_peloton_total_output"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations() -> None:
    """Override: the recorder must be set up before hass is created."""


async def _metadata(hass: HomeAssistant) -> dict:
    found = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={ENTITY_ID})
    )
    return found[ENTITY_ID][1]


@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_total_output_statistics_are_relabelled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Statistics recorded in "kj" are relabelled "kJ" and keep compiling."""
    await async_setup_component(hass, "sensor", {})
    await async_wait_recording_done(hass)
    mock_config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{USER_ID}_total_output",
        config_entry=mock_config_entry,
        suggested_object_id="test_on_peloton_total_output",
    )

    # What an earlier version recorded: Peloton's "kj", as a measurement.
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=3
    )
    freezer.move_to(start + timedelta(minutes=1))
    hass.states.async_set(
        ENTITY_ID, "300", {"state_class": "measurement", "unit_of_measurement": "kj"}
    )
    await async_wait_recording_done(hass)
    do_adhoc_statistics(hass, start=start)
    await async_wait_recording_done(hass)
    assert (await _metadata(hass))["unit_of_measurement"] == "kj"

    # As after a restart: no state until the integration's entity writes one.
    hass.states.async_remove(ENTITY_ID)
    freezer.move_to(start + timedelta(minutes=6))
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(ENTITY_ID).attributes["unit_of_measurement"] == "kJ"
    await async_wait_recording_done(hass)

    metadata = await _metadata(hass)
    assert metadata["unit_of_measurement"] == "kJ"
    assert metadata["unit_class"] == "energy"

    do_adhoc_statistics(hass, start=start + timedelta(minutes=5))
    await async_wait_recording_done(hass)
    await get_instance(hass).async_add_executor_job(update_statistics_issues, hass)
    await hass.async_block_till_done()
    issues = [
        issue_id
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == "sensor" and ENTITY_ID in issue_id
    ]
    assert issues == []


@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_no_statistics_no_change(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A fresh install with no recorded statistics sets up normally."""
    await setup_integration(hass, mock_config_entry)
    await async_wait_recording_done(hass)

    assert hass.states.get(ENTITY_ID) is not None


@pytest.mark.parametrize("seed_unit", [None, "kJ"], ids=["no_statistics", "already_kj"])
@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_statistics_left_alone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
    seed_unit: str | None,
) -> None:
    """Entities without statistics, or already in kJ, are not touched."""
    await async_setup_component(hass, "sensor", {})
    await async_wait_recording_done(hass)
    mock_config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{USER_ID}_total_output",
        config_entry=mock_config_entry,
        suggested_object_id="test_on_peloton_total_output",
    )
    if seed_unit is not None:
        start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(
            hours=3
        )
        freezer.move_to(start + timedelta(minutes=1))
        hass.states.async_set(
            ENTITY_ID,
            "300",
            {
                "state_class": "total",
                "device_class": "energy",
                "unit_of_measurement": seed_unit,
            },
        )
        await async_wait_recording_done(hass)
        do_adhoc_statistics(hass, start=start)
        await async_wait_recording_done(hass)
        hass.states.async_remove(ENTITY_ID)

    with patch.object(
        get_instance(hass), "async_update_statistics_metadata"
    ) as update_metadata:
        await setup_integration(hass, mock_config_entry)
        await async_wait_recording_done(hass)

    update_metadata.assert_not_called()


@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_statistics_read_error_does_not_block_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """If the statistics cannot be read, setup continues without the fix."""
    mock_config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{USER_ID}_total_output",
        config_entry=mock_config_entry,
        suggested_object_id="test_on_peloton_total_output",
    )

    with patch(
        "homeassistant.components.recorder.statistics.get_metadata",
        side_effect=RuntimeError("database locked"),
    ):
        await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
