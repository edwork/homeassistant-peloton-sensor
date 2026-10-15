"""Baseline tests for setup, entities and polling.

These pin down how the integration behaves before the refactor. The unique_id
and device identifier assertions must keep passing through every roadmap
phase. Tests and comments marked "current behaviour" document defects that
later phases fix; those assertions are expected to change with the fix.
"""

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pylotoncycle.pylotoncycle import PelotonLoginException
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout

from custom_components.peloton.const import DOMAIN

from .conftest import USER_ID, load_fixture

# unique_id suffix -> target entity_id for a fresh install, for a user whose
# first name is "Test". Existing installs already have these entity_ids.
EXPECTED_ENTITIES = {
    "workout": "binary_sensor.test_on_peloton_workout",
    "start_time": "sensor.test_on_peloton_start_time",
    "end_time": "sensor.test_on_peloton_end_time",
    "duration": "sensor.test_on_peloton_duration",
    "leaderboard:_rank": "sensor.test_on_peloton_leaderboard_rank",
    "leaderboard:_total_users": "sensor.test_on_peloton_leaderboard_total_users",
    "power_output": "sensor.test_on_peloton_power_output",
    "distance": "sensor.test_on_peloton_distance",
    "total_calories": "sensor.test_on_peloton_total_calories",
    "active_calories": "sensor.test_on_peloton_active_calories",
    "total_output": "sensor.test_on_peloton_total_output",
    "heart_rate:_average": "sensor.test_on_peloton_heart_rate_average",
    "heart_rate:_max": "sensor.test_on_peloton_heart_rate_max",
    "heart_rate:_current": "sensor.test_on_peloton_heart_rate_current",
    "resistance:_average": "sensor.test_on_peloton_resistance_average",
    "resistance:_max": "sensor.test_on_peloton_resistance_max",
    "resistance:_current": "sensor.test_on_peloton_resistance_current",
    "speed:_average": "sensor.test_on_peloton_speed_average",
    "speed:_max": "sensor.test_on_peloton_speed_max",
    "speed:_current": "sensor.test_on_peloton_speed_current",
    "cadence:_average": "sensor.test_on_peloton_cadence_average",
    "cadence:_max": "sensor.test_on_peloton_cadence_max",
    "cadence:_current": "sensor.test_on_peloton_cadence_current",
    "bike_bootcamp_count": "sensor.test_on_peloton_bike_bootcamp_count",
    "rowing_count": "sensor.test_on_peloton_rowing_count",
    "row_bootcamp_count": "sensor.test_on_peloton_row_bootcamp_count",
    "cardio_count": "sensor.test_on_peloton_cardio_count",
    "tread_bootcamp_count": "sensor.test_on_peloton_tread_bootcamp_count",
    "cycling_count": "sensor.test_on_peloton_cycling_count",
    "meditation_count": "sensor.test_on_peloton_meditation_count",
    "running_count": "sensor.test_on_peloton_running_count",
    "strength_count": "sensor.test_on_peloton_strength_count",
    "stretching_count": "sensor.test_on_peloton_stretching_count",
    "walking_count": "sensor.test_on_peloton_walking_count",
    "yoga_count": "sensor.test_on_peloton_yoga_count",
}

# Workout count sensors are registered but disabled by default.
DISABLED_BY_DEFAULT = {key for key in EXPECTED_ENTITIES if key.endswith("_count")}

# Binary sensor attribute keys. User templates depend on these names.
BINARY_SENSOR_ATTRIBUTES = (
    "Workout Type",
    "Device Type",
    "Ride Title",
    "Ride Description",
    "Workout Image",
    "FTP",
    "Instructor",
    "Paused",
)


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def advance_one_poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Move time forward one 10 s update interval and let the coordinator run."""
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Run one coordinator refresh so every entity has received data.

    Current behaviour: entities only read data in _handle_coordinator_update,
    and the refresh at setup runs before they subscribe, so states stay
    unknown until a later poll (timing varies by Home Assistant version).
    Roadmap phase 3 sets state when entities are added; the coordinator also
    moves from hass.data to entry.runtime_data then.
    """
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()


def state_of(hass: HomeAssistant, suffix: str) -> State:
    """Return the state of the entity with unique_id f"{USER_ID}_{suffix}".

    Looks the entity up by unique_id so the tests do not depend on the
    entity_id a fresh install happens to get (see test_fresh_install_entity_ids).
    """
    domain = "binary_sensor" if suffix == "workout" else "sensor"
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{USER_ID}_{suffix}"
    )
    assert entity_id is not None, suffix
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


@pytest.mark.usefixtures("mock_peloton")
async def test_setup_and_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The entry loads and unloads cleanly."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("mock_peloton")
async def test_unique_ids_and_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Unique ids and the device identifier match existing installs.

    Never change these: existing installs keep their entity_ids, history and
    dashboards only while unique ids and the device identifier stay the same.
    """
    await setup_integration(hass, mock_config_entry)

    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    assert {entry.unique_id for entry in entries} == {
        f"{USER_ID}_{suffix}" for suffix in EXPECTED_ENTITIES
    }

    disabled = {
        entry.unique_id.removeprefix(f"{USER_ID}_")
        for entry in entries
        if entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    }
    assert disabled == DISABLED_BY_DEFAULT

    # The device name depends on which platform registers the device first
    # (see test_fresh_install_entity_ids), so only the identifier is pinned.
    devices = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    assert len(devices) == 1
    assert devices[0].identifiers == {(DOMAIN, USER_ID)}
    assert {entry.device_id for entry in entries} == {devices[0].id}


@pytest.mark.usefixtures("mock_peloton")
async def test_fresh_install_entity_ids(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Entity ids a fresh install gets.

    Current behaviour: only the binary sensor gives the device a name; sensors
    pass identifiers only. Platforms set up concurrently, so if the sensor
    platform registers the device first, the device takes the entry title.
    On Home Assistant 2026.4 and newer the registry then puts that name in
    front of the sensor entity_ids ("peloton_testrider_..."); on 2026.3 it
    does not. Which platform wins is a race. Roadmap phase 3 (full DeviceInfo
    on every entity, has_entity_name) should make every entity match
    EXPECTED_ENTITIES exactly.
    """
    await setup_integration(hass, mock_config_entry)

    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    actual = {
        entry.unique_id.removeprefix(f"{USER_ID}_"): entry.entity_id
        for entry in entries
    }
    for suffix, target in EXPECTED_ENTITIES.items():
        prefixed = target.replace("sensor.", "sensor.peloton_testrider_", 1)
        assert actual[suffix] in (target, prefixed), suffix


@pytest.mark.usefixtures("mock_peloton")
async def test_completed_workout(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A completed workout: binary sensor off, summary values, current values 0."""
    await setup_integration(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)

    workout = state_of(hass, "workout")
    assert workout.state == STATE_OFF
    assert workout.attributes["icon"] == "mdi:bike"
    assert {key: workout.attributes[key] for key in BINARY_SENSOR_ATTRIBUTES} == {
        "Workout Type": "cycling",
        "Device Type": "home_bike_plus",
        "Ride Title": "30 min Synthetic Ride",
        "Ride Description": "Synthetic class used in tests.",
        "Workout Image": "https://example.invalid/ride.png",
        "FTP": 200,
        "Instructor": "Synthetic Instructor",
        "Paused": False,
    }

    expected_states = {
        "start_time": "2025-10-09T08:53:20+00:00",
        "end_time": "2025-10-09T09:23:20+00:00",
        "duration": "30.0",
        "leaderboard:_rank": "120",
        "power_output": "100.0",
        "distance": "10.5",
        "total_calories": "450",
        "total_output": "360",
        "heart_rate:_average": "140",
        "heart_rate:_max": "165",
        "heart_rate:_current": "0",
        "cadence:_average": "85",
        "cadence:_current": "0",
        "speed:_max": "24.5",
        "speed:_current": "0.0",
    }
    actual_states = {suffix: state_of(hass, suffix).state for suffix in expected_states}
    assert actual_states == expected_states

    # Units today come partly from the API's display_unit strings (issue #101).
    expected_units = {
        "power_output": "Wh",
        "distance": "mi",
        "total_calories": "kcal",
        "total_output": "kj",
        "heart_rate:_average": "bpm",
        "heart_rate:_current": "bpm",
        "speed:_max": "mph",
    }
    actual_units = {
        suffix: state_of(hass, suffix).attributes.get("unit_of_measurement")
        for suffix in expected_units
    }
    assert actual_units == expected_units


@pytest.mark.parametrize(
    "workout", [load_fixture("workout_in_progress.json")], ids=["in_progress"]
)
@pytest.mark.usefixtures("mock_peloton")
async def test_workout_in_progress(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, workout: dict[str, Any]
) -> None:
    """An in-progress workout turns the binary sensor on and fills current values."""
    await setup_integration(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)

    binary = state_of(hass, "workout")
    assert binary.state == STATE_ON
    assert binary.attributes["icon"] == "mdi:bike-fast"
    assert set(BINARY_SENSOR_ATTRIBUTES) <= set(binary.attributes)
    assert state_of(hass, "start_time").state == "2025-10-09T08:53:20+00:00"
    assert state_of(hass, "heart_rate:_current").state == "148"
    assert state_of(hass, "cadence:_current").state == "88"
    assert state_of(hass, "resistance:_current").state == "44"
    assert state_of(hass, "speed:_current").state == "20.4"


@pytest.mark.parametrize(
    "workout",
    [{**load_fixture("workout_complete.json"), "end_time": 1760000000}],
    ids=["end_equals_start"],
)
@pytest.mark.usefixtures("mock_peloton")
async def test_end_time_from_duration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, workout: dict[str, Any]
) -> None:
    """An end time equal to the start time is replaced by start + duration (#86)."""
    await setup_integration(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)

    assert state_of(hass, "start_time").state == "2025-10-09T08:53:20+00:00"
    assert state_of(hass, "end_time").state == "2025-10-09T09:23:20+00:00"


@pytest.mark.usefixtures("mock_peloton", "entity_registry_enabled_by_default")
async def test_workout_counts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Workout count sensors map API slugs to their display names."""
    await setup_integration(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)

    expected = {
        "cycling_count": "30",
        "strength_count": "5",
        "bike_bootcamp_count": "4",
        "rowing_count": "2",  # slug "caesar"
        "row_bootcamp_count": "6",  # slug "caesar_bootcamp"
        "cardio_count": "1",
        "tread_bootcamp_count": "7",  # slug "circuit"
        "meditation_count": "8",
        "running_count": "9",
        "stretching_count": "3",
        "walking_count": "10",
        "yoga_count": "11",
    }
    assert {suffix: state_of(hass, suffix).state for suffix in expected} == expected


async def test_polling_reuses_login(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_peloton: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The client is created once; later polls fetch data without logging in.

    Logging in happens when the pylotoncycle client is constructed, so the
    class must be called exactly once however many polls run.
    """
    await setup_integration(hass, mock_config_entry)
    client = mock_peloton.return_value
    fetches_after_setup = client.GetRecentWorkouts.call_count
    assert fetches_after_setup >= 1

    for _ in range(3):
        await advance_one_poll(hass, freezer)

    assert client.GetRecentWorkouts.call_count == fetches_after_setup + 3
    assert mock_peloton.call_count == 1


async def test_poll_failure_makes_entities_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_peloton: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Current behaviour: one failed poll makes every entity unavailable.

    For the fan use case this turns the workout sensor unavailable mid-ride.
    Roadmap phase 3 keeps the binary sensor's last state through a few failed
    polls; this assertion is expected to change then.
    """
    await setup_integration(hass, mock_config_entry)
    await refresh(hass, mock_config_entry)
    assert state_of(hass, "workout").state == STATE_OFF

    mock_peloton.return_value.GetRecentWorkouts.side_effect = Timeout
    await advance_one_poll(hass, freezer)

    assert state_of(hass, "workout").state == STATE_UNAVAILABLE
    assert state_of(hass, "heart_rate:_average").state == STATE_UNAVAILABLE


async def test_no_workouts_retries_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_peloton: MagicMock
) -> None:
    """Current behaviour: an account with no workouts cannot finish setup."""
    mock_peloton.return_value.GetRecentWorkouts.return_value = []
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_login_exception_starts_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_peloton: MagicMock
) -> None:
    """Code path only: PelotonLoginException at setup starts a reauth flow.

    Unreachable in practice: pylotoncycle 0.9.1 defines PelotonLoginException
    but never raises it. A wrong password raises a plain Exception instead
    (see test_setup_errors_do_not_retry).
    """
    mock_peloton.side_effect = PelotonLoginException
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


@pytest.mark.parametrize("side_effect", [Exception, Timeout, RequestsConnectionError])
async def test_setup_errors_do_not_retry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_peloton: MagicMock,
    side_effect: type[Exception],
) -> None:
    """Current behaviour: login failures end setup with no retry or reauth.

    pylotoncycle raises a plain Exception for a wrong password. A timeout is
    turned into UpdateFailed, which setup does not treat as "not ready".
    requests' ConnectionError is not the builtin ConnectionError the code
    catches, so network errors are not handled either.
    """
    mock_peloton.side_effect = side_effect
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert not hass.config_entries.flow.async_progress()
