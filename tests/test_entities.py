"""Entity tests: unique ids, entity ids, states, units and attributes.

The unique_id and device identifier assertions must keep passing in every
later change: existing installs keep their entity_ids, history and dashboards
only while those stay the same.
"""

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    CONF_TOKEN,
    CONF_USERNAME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.api.const import API_BASE
from custom_components.peloton.const import DOMAIN, TOLERATED_FAILED_POLLS

from .common import advance, setup_integration, state_of
from .conftest import JSON_HEADERS, USER_ID, USERNAME, load_fixture, stored_tokens

# unique_id suffix (kept from earlier versions) -> entity_id on a fresh install,
# for a user whose first name is "Test".
EXPECTED_ENTITIES = {
    "workout": "binary_sensor.test_on_peloton_workout",
    "start_time": "sensor.test_on_peloton_start_time",
    "end_time": "sensor.test_on_peloton_end_time",
    "duration": "sensor.test_on_peloton_duration",
    "leaderboard:_rank": "sensor.test_on_peloton_leaderboard_rank",
    "leaderboard:_total_users": "sensor.test_on_peloton_leaderboard_total_users",
    # Called "Power Output" before; existing installs keep their entity_id.
    "power_output": "sensor.test_on_peloton_total_work",
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
    "output:_average": "sensor.test_on_peloton_output_average",
    "output:_max": "sensor.test_on_peloton_output_max",
    "output:_current": "sensor.test_on_peloton_output_current",
    "total_workouts": "sensor.test_on_peloton_total_workouts",
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
    "stroke_rate:_average": "sensor.test_on_peloton_stroke_rate_average",
    "stroke_rate:_max": "sensor.test_on_peloton_stroke_rate_max",
    "stroke_rate:_current": "sensor.test_on_peloton_stroke_rate_current",
    "split_pace:_average": "sensor.test_on_peloton_split_pace_average",
    "split_pace:_max": "sensor.test_on_peloton_split_pace_best",
    "split_pace:_current": "sensor.test_on_peloton_split_pace_current",
    "stroke_count": "sensor.test_on_peloton_stroke_count",
    "pace:_average": "sensor.test_on_peloton_pace_average",
    "pace:_max": "sensor.test_on_peloton_pace_best",
    "pace:_current": "sensor.test_on_peloton_pace_current",
    "incline:_average": "sensor.test_on_peloton_incline_average",
    "incline:_max": "sensor.test_on_peloton_incline_max",
    "incline:_current": "sensor.test_on_peloton_incline_current",
    "elevation": "sensor.test_on_peloton_elevation",
}

# Rower and tread sensors (#105), added in version 3 of the config entry.
MODALITY_SUFFIXES = {
    key
    for key in EXPECTED_ENTITIES
    if key.split(":")[0]
    in {"stroke_rate", "split_pace", "stroke_count", "pace", "incline", "elevation"}
}

# unique_id suffixes of entities that existed before version 3 of the config
# entry. These must never change.
LEGACY_SUFFIXES = (
    set(EXPECTED_ENTITIES)
    - {"output:_average", "output:_max", "output:_current", "total_workouts"}
    - MODALITY_SUFFIXES
)

# Workout count, rower and tread sensors are registered but disabled by default.
DISABLED_BY_DEFAULT = {
    key for key in EXPECTED_ENTITIES if key.endswith("_count")
} | MODALITY_SUFFIXES

BINARY_SENSOR_ATTRIBUTES = (
    "workout_type",
    "device_type",
    "ride_title",
    "ride_description",
    "workout_image",
    "ftp",
    "instructor",
    "paused",
)


@pytest.fixture
async def imperial(hass: HomeAssistant) -> None:
    """Use US customary units in Home Assistant (no display conversion of miles)."""
    hass.config.units = US_CUSTOMARY_SYSTEM


def in_progress_list(**changes: Any) -> dict[str, Any]:
    """Return a workout list whose latest workout is running."""
    data = load_fixture("api/workouts.json")
    data["data"][0] |= {"status": "IN_PROGRESS", "end_time": None} | changes
    return data


def in_progress_detail(**changes: Any) -> dict[str, Any]:
    """Return the detail of a running workout."""
    return (
        load_fixture("api/workout.json")
        | {"status": "IN_PROGRESS", "end_time": None}
        | changes
    )


@pytest.mark.usefixtures("mock_api")
async def test_unique_ids_and_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Unique ids and the device identifier match existing installs."""
    await setup_integration(hass, mock_config_entry)

    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    suffixes = {entry.unique_id.removeprefix(f"{USER_ID}_") for entry in entries}
    assert suffixes == set(EXPECTED_ENTITIES)
    assert suffixes >= LEGACY_SUFFIXES

    disabled = {
        entry.unique_id.removeprefix(f"{USER_ID}_")
        for entry in entries
        if entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    }
    assert disabled == DISABLED_BY_DEFAULT

    devices = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, USER_ID)}
    assert device.name == "Test on Peloton"
    assert device.manufacturer == "Peloton"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.configuration_url == "https://members.onepeloton.com"
    assert {entry.device_id for entry in entries} == {device.id}


@pytest.mark.usefixtures("mock_api")
async def test_fresh_install_entity_ids(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """A fresh install gets predictable entity ids from the device and entity names."""
    await setup_integration(hass, mock_config_entry)

    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    actual = {
        entry.unique_id.removeprefix(f"{USER_ID}_"): entry.entity_id
        for entry in entries
    }
    assert actual == EXPECTED_ENTITIES


@pytest.mark.usefixtures("mock_api")
async def test_existing_entity_ids_are_kept(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Entities registered by earlier versions keep their entity_ids."""
    mock_config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{USER_ID}_power_output",
        config_entry=mock_config_entry,
        suggested_object_id="ed_on_peloton_power_output",
    )

    await setup_integration(hass, mock_config_entry)

    assert (
        entity_registry.async_get_entity_id("sensor", DOMAIN, f"{USER_ID}_power_output")
        == "sensor.ed_on_peloton_power_output"
    )
    assert hass.states.get("sensor.ed_on_peloton_power_output").state == "100.0"


@pytest.mark.parametrize("me_json", [{"first_name": None}], ids=["no_first_name"])
async def test_device_name_falls_back_to_username(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Accounts without a first name are named after the username."""
    await setup_integration(hass, mock_config_entry)

    (device,) = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    assert device.name == "testrider on Peloton"


@pytest.mark.usefixtures("mock_api")
async def test_states_are_set_when_added(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Entities have their values right after setup, without waiting for a poll."""
    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "workout").state == STATE_OFF
    assert state_of(hass, "heart_rate:_average").state == "140"


@pytest.mark.usefixtures("mock_api", "imperial")
async def test_completed_workout(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A completed workout: binary sensor off, totals, averages and idle currents."""
    await setup_integration(hass, mock_config_entry)

    workout = state_of(hass, "workout")
    assert workout.state == STATE_OFF
    assert workout.attributes["friendly_name"] == "Test on Peloton Workout"
    assert {key: workout.attributes[key] for key in BINARY_SENSOR_ATTRIBUTES} == {
        "workout_type": "cycling",
        "device_type": "home_bike_plus",
        "ride_title": "30 min Synthetic Ride",
        "ride_description": "Synthetic class used in tests.",
        "workout_image": "https://example.invalid/ride.png",
        "ftp": 200,
        "instructor": "Synthetic Instructor",
        "paused": False,
    }

    expected = {
        "start_time": ("2025-10-09T08:53:20+00:00", None),
        "end_time": ("2025-10-09T09:23:20+00:00", None),
        "duration": ("30.0", "min"),
        "leaderboard:_rank": ("120", None),
        "leaderboard:_total_users": ("4000", None),
        "power_output": ("100.0", "Wh"),
        "distance": ("10.5", "mi"),
        "total_calories": ("450", "kcal"),
        "active_calories": ("380", "kcal"),
        "total_output": ("360", "kJ"),
        "heart_rate:_average": ("140", "bpm"),
        "heart_rate:_max": ("165", "bpm"),
        "heart_rate:_current": (STATE_UNKNOWN, "bpm"),
        "resistance:_average": ("42", "%"),
        "resistance:_current": ("0", "%"),
        # Peloton's displayed average (avg_speed), not the metric average.
        "speed:_average": ("17.5", "mph"),
        "speed:_max": ("24.5", "mph"),
        "speed:_current": ("0", "mph"),
        "cadence:_average": ("85", "rpm"),
        "cadence:_current": ("0", "rpm"),
        "output:_average": ("200", "W"),
        "output:_max": ("320", "W"),
        "output:_current": ("0", "W"),
        "total_workouts": ("96", None),
    }
    actual = {
        suffix: (
            state_of(hass, suffix).state,
            state_of(hass, suffix).attributes.get("unit_of_measurement"),
        )
        for suffix in expected
    }
    assert actual == expected


@pytest.mark.usefixtures("mock_api")
async def test_sensor_classes(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Device and state classes that long-term statistics depend on."""
    await setup_integration(hass, mock_config_entry)

    expected = {
        "power_output": ("energy", "total"),
        "total_calories": ("energy", "total"),
        "active_calories": ("energy", "total"),
        "total_output": ("energy", "total"),
        "duration": ("duration", "measurement"),
        "distance": ("distance", "measurement"),
        "speed:_max": ("speed", "measurement"),
        "output:_current": ("power", "measurement"),
        "heart_rate:_current": (None, "measurement"),
        "total_workouts": (None, "total_increasing"),
    }
    actual = {
        suffix: (
            state_of(hass, suffix).attributes.get("device_class"),
            state_of(hass, suffix).attributes.get("state_class"),
        )
        for suffix in expected
    }
    assert actual == expected


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [(in_progress_list(), in_progress_detail())],
    ids=["in_progress"],
)
@pytest.mark.usefixtures("mock_api", "imperial")
async def test_workout_in_progress(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A running workout turns the binary sensor on and fills current values."""
    freezer.move_to("2025-10-09 09:00:00+00:00")  # 7 minutes into the class
    await setup_integration(hass, mock_config_entry)

    binary = state_of(hass, "workout")
    assert binary.state == STATE_ON
    assert set(BINARY_SENSOR_ATTRIBUTES) <= set(binary.attributes)
    assert state_of(hass, "end_time").state == STATE_UNKNOWN
    assert state_of(hass, "heart_rate:_current").state == "148"
    assert state_of(hass, "cadence:_current").state == "88"
    assert state_of(hass, "resistance:_current").state == "44"
    assert state_of(hass, "speed:_current").state == "20.4"
    assert state_of(hass, "output:_current").state == "190"


@pytest.mark.parametrize(
    ("workouts_json", "workout_json", "now", "state"),
    [
        # 30 minute class started at 08:53:20; 15 minutes of grace.
        (in_progress_list(), in_progress_detail(), "2025-10-09 09:38:00", STATE_ON),
        (in_progress_list(), in_progress_detail(), "2025-10-09 09:39:00", STATE_OFF),
        # No class length: the 240 minute default limit applies.
        (
            in_progress_list(ride=load_fixture("api/workout_just_ride.json")["ride"]),
            in_progress_detail(ride=load_fixture("api/workout_just_ride.json")["ride"]),
            "2025-10-09 12:50:00",
            STATE_ON,
        ),
        (
            in_progress_list(ride=load_fixture("api/workout_just_ride.json")["ride"]),
            in_progress_detail(ride=load_fixture("api/workout_just_ride.json")["ride"]),
            "2025-10-09 12:54:00",
            STATE_OFF,
        ),
    ],
    ids=["class_in_grace", "class_abandoned", "just_ride_open", "just_ride_abandoned"],
)
@pytest.mark.usefixtures("mock_api")
async def test_abandoned_workout_guard(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    now: str,
    state: str,
) -> None:
    """A workout left in progress long after it should have ended counts as ended."""
    freezer.move_to(f"{now}+00:00")
    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "workout").state == state
    expected_current = "0" if state == STATE_OFF else "88"
    assert state_of(hass, "cadence:_current").state == expected_current


@pytest.mark.parametrize(
    "workout_json",
    [load_fixture("api/workout.json") | {"end_time": 1760000000}],
    ids=["end_equals_start"],
)
@pytest.mark.usefixtures("mock_api")
async def test_end_time_from_duration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An end time equal to the start time is replaced by start + duration (#86)."""
    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "end_time").state == "2025-10-09T09:23:20+00:00"


@pytest.mark.parametrize(
    ("workout_json", "zone"),
    [
        (load_fixture("api/workout.json"), "America/New_York"),
        (load_fixture("api/workout.json") | {"timezone": "Not/AZone"}, "UTC"),
        (load_fixture("api/workout.json") | {"timezone": ""}, "UTC"),
        (load_fixture("api/workout.json") | {"timezone": None}, "UTC"),
        (load_fixture("api/workout.json") | {"timezone": "Etc/GMT+5"}, "Etc/GMT+5"),
        (load_fixture("api/workout.json") | {"timezone": "America/New_York/"}, "UTC"),
        (load_fixture("api/workout.json") | {"timezone": "../x"}, "UTC"),
        (load_fixture("api/workout.json") | {"timezone": "A" * 300}, "UTC"),
    ],
    ids=[
        "valid",
        "unknown",
        "empty",
        "missing",
        "etc_gmt",
        "trailing_slash",
        "relative",
        "overlong",
    ],
)
@pytest.mark.usefixtures("mock_api")
async def test_workout_timezones(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, zone: str
) -> None:
    """Workout time zones resolve; unknown or malformed ones fall back to UTC."""
    await setup_integration(hass, mock_config_entry)

    assert str(mock_config_entry.runtime_data.data.timezone) == zone
    assert state_of(hass, "start_time").state == "2025-10-09T08:53:20+00:00"


@pytest.mark.usefixtures("mock_api", "entity_registry_enabled_by_default")
async def test_workout_counts(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Workout count sensors map API slugs to their names."""
    await setup_integration(hass, mock_config_entry)

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
    entry = entity_registry.async_get(EXPECTED_ENTITIES["cycling_count"])
    assert entry.entity_category is EntityCategory.DIAGNOSTIC


@pytest.mark.parametrize("workouts_json", [load_fixture("api/workouts_empty.json")])
@pytest.mark.usefixtures("mock_api")
async def test_no_workouts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An account without workouts: binary sensor off, workout values unknown."""
    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "workout").state == STATE_OFF
    assert state_of(hass, "workout").attributes["workout_type"] is None
    for suffix in ("start_time", "end_time", "duration", "leaderboard:_rank"):
        assert state_of(hass, suffix).state == STATE_UNKNOWN, suffix
    assert state_of(hass, "heart_rate:_average").state == STATE_UNKNOWN
    assert state_of(hass, "heart_rate:_current").state == STATE_UNKNOWN
    assert state_of(hass, "cadence:_current").state == "0"
    assert state_of(hass, "total_workouts").state == "96"


@pytest.mark.parametrize(
    "workout_json",
    [
        load_fixture("api/workout.json")
        | {"leaderboard_rank": None, "total_leaderboard_users": None}
    ],
)
@pytest.mark.usefixtures("mock_api")
async def test_missing_leaderboard_is_unknown(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A workout without a leaderboard shows unknown rather than 0."""
    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "leaderboard:_rank").state == STATE_UNKNOWN
    assert state_of(hass, "leaderboard:_total_users").state == STATE_UNKNOWN


@pytest.mark.parametrize(
    ("settings_json", "distance", "speed"),
    [
        ({"distance_unit": "metric"}, ("16.898", "km"), ("39.43", "km/h")),
        ({}, ("16.898", "km"), ("39.43", "km/h")),
    ],
    ids=["metric", "unset"],
)
@pytest.mark.usefixtures("mock_api")
async def test_units_follow_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    distance: tuple[str, str],
    speed: tuple[str, str],
) -> None:
    """Distance and speed are converted to the unit of the Peloton settings."""
    await setup_integration(hass, mock_config_entry)

    state = state_of(hass, "distance")
    assert (state.state, state.attributes["unit_of_measurement"]) == distance
    state = state_of(hass, "speed:_max")
    assert (state.state, state.attributes["unit_of_measurement"]) == speed


def rower_graph() -> dict[str, Any]:
    """Return a synthetic rower performance graph (distance in meters)."""
    return {
        "duration": 1200,
        "summaries": [
            {"slug": "total_output", "display_unit": "kj", "value": 150},
            {"slug": "distance", "display_unit": "m", "value": 4023.36},
            {"slug": "stroke_count", "display_unit": None, "value": 480},
            {"slug": "calories", "display_unit": "kcal", "value": 200},
        ],
        "average_summaries": [
            {"slug": "avg_output", "display_unit": "watts", "value": 125},
            {"slug": "avg_stroke_rate", "display_unit": "spm", "value": 24},
            {"slug": "avg_split_pace", "display_unit": "min/500m", "value": 3.65},
        ],
        "metrics": [
            {
                "slug": "output",
                "display_unit": "watts",
                "average_value": 120,
                "max_value": 210,
                "values": [100, 130],
            },
            {
                "slug": "stroke_rate",
                "display_unit": "spm",
                "average_value": 24,
                "max_value": 30,
                "values": [22, 25],
            },
            {
                "slug": "split_pace",
                "display_unit": "min/500m",
                "average_value": 3.66,
                "max_value": 2.72,
                "values": [3.9, 0],
            },
        ],
    }


def tread_graph(
    distance_unit: str = "mi",
    pace: tuple[float | None, ...] = (12.0, 10.0),
    speed: tuple[float, ...] = (5.0, 6.0),
) -> dict[str, Any]:
    """Return a synthetic tread performance graph.

    Like Peloton's, speed is only an alternative of the pace metric, and the
    pace "max" is the fastest pace.
    """
    pace_unit = f"min/{distance_unit}"
    return {
        "duration": 1800,
        "summaries": [
            {"slug": "total_output", "display_unit": "kj", "value": 96},
            {"slug": "distance", "display_unit": distance_unit, "value": 2.0},
            {"slug": "elevation", "display_unit": "ft", "value": 269},
            {"slug": "calories", "display_unit": "kcal", "value": 156},
        ],
        "average_summaries": [
            {"slug": "avg_output", "display_unit": "watts", "value": 63},
            {"slug": "avg_pace", "display_unit": pace_unit, "value": 11.43},
            {"slug": "avg_incline", "display_unit": "%", "value": 3.0},
            {"slug": "avg_speed", "display_unit": "mph", "value": 5.2},
        ],
        "metrics": [
            {
                "slug": "output",
                "display_unit": "watts",
                "average_value": 63,
                "max_value": 220,
                "values": [62, 103],
            },
            {
                "slug": "pace",
                "display_unit": pace_unit,
                "average_value": 11.43,
                "max_value": 8.5,
                "values": list(pace),
                "alternatives": [
                    {
                        "slug": "speed",
                        "display_unit": "mph",
                        "average_value": 5.2,
                        "max_value": 7.06,
                        "values": list(speed),
                    }
                ],
            },
            {
                "slug": "incline",
                "display_unit": "%",
                "average_value": 3.0,
                "max_value": 12.0,
                "values": [1.0, 4.5],
            },
        ],
    }


@pytest.mark.parametrize(
    "workout_json",
    [load_fixture("api/workout.json") | {"fitness_discipline": "caesar"}],
    ids=["rower"],
)
@pytest.mark.usefixtures("imperial")
async def test_rower_workout(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    workout_json: dict[str, Any],
) -> None:
    """Rower distance in meters becomes miles; bike-only metrics are unknown."""
    aioclient_mock.clear_requests()
    _register_graph(aioclient_mock, rower_graph(), workout_json)

    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "distance").state == "2.5"
    assert state_of(hass, "distance").attributes["unit_of_measurement"] == "mi"
    assert state_of(hass, "output:_average").state == "125"
    assert state_of(hass, "cadence:_average").state == STATE_UNKNOWN
    assert state_of(hass, "speed:_max").state == STATE_UNKNOWN
    assert state_of(hass, "total_calories").state == "200"


@pytest.mark.parametrize(
    "workout_json",
    [load_fixture("api/workout.json") | {"fitness_discipline": "caesar"}],
    ids=["rower"],
)
@pytest.mark.usefixtures("imperial", "entity_registry_enabled_by_default")
async def test_rower_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    workout_json: dict[str, Any],
) -> None:
    """Stroke rate, split pace and strokes come from the rower's metrics."""
    aioclient_mock.clear_requests()
    _register_graph(aioclient_mock, rower_graph(), workout_json)

    await setup_integration(hass, mock_config_entry)

    expected = {
        "stroke_rate:_average": ("24", "spm"),
        "stroke_rate:_max": ("30", "spm"),
        "stroke_rate:_current": ("0", "spm"),
        "split_pace:_average": ("3.65", "min/500m"),
        "split_pace:_max": ("2.72", "min/500m"),
        "split_pace:_current": (STATE_UNKNOWN, "min/500m"),
        "stroke_count": ("480", None),
        "pace:_average": (STATE_UNKNOWN, "min/mi"),
        "incline:_average": (STATE_UNKNOWN, "%"),
        "elevation": (STATE_UNKNOWN, "ft"),
    }
    for suffix, (value, unit) in expected.items():
        state = state_of(hass, suffix)
        assert (state.state, state.attributes.get("unit_of_measurement")) == (
            value,
            unit,
        ), suffix
    assert state_of(hass, "stroke_count").attributes["state_class"] == "total"


@pytest.mark.parametrize(
    ("settings", "graph", "pace", "elevation"),
    [
        ({"distance_unit": "imperial"}, tread_graph(), ("11.43", "min/mi"), 269),
        ({"distance_unit": "metric"}, tread_graph(), ("7.1", "min/km"), 269),
        ({"distance_unit": "imperial"}, tread_graph("km"), ("18.39", "min/mi"), 269),
    ],
    ids=["imperial", "metric", "km_display"],
)
@pytest.mark.usefixtures("imperial", "entity_registry_enabled_by_default")
async def test_tread_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    settings: dict[str, Any],
    graph: dict[str, Any],
    pace: tuple[str, str],
    elevation: int,
) -> None:
    """Pace, incline and elevation follow the settings; speed comes from pace."""
    aioclient_mock.clear_requests()
    _register_graph(
        aioclient_mock,
        graph,
        load_fixture("api/workout.json") | {"fitness_discipline": "running"},
        settings=settings,
    )

    await setup_integration(hass, mock_config_entry)

    state = state_of(hass, "pace:_average")
    assert (state.state, state.attributes["unit_of_measurement"]) == pace
    assert state_of(hass, "pace:_current").state == STATE_UNKNOWN
    assert state_of(hass, "incline:_average").state == "3.0"
    assert state_of(hass, "incline:_max").state == "12.0"
    assert state_of(hass, "incline:_current").state == "0"
    # Home Assistant shows distances of new entities in its unit system (feet
    # here); the conversion from the settings unit is in test_values.py.
    assert round(float(state_of(hass, "elevation").state)) == elevation
    # Speed is only an alternative of pace on the tread.
    assert state_of(hass, "speed:_max").state != STATE_UNKNOWN


@pytest.mark.usefixtures("imperial", "entity_registry_enabled_by_default")
async def test_tread_sensors_during_workout(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """During a tread workout the current pace, incline and speed are live."""
    freezer.move_to("2025-10-09 09:00:00+00:00")
    aioclient_mock.clear_requests()
    _register_graph(
        aioclient_mock,
        tread_graph(),
        in_progress_detail(fitness_discipline="running"),
        in_progress_list(fitness_discipline="running"),
    )

    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "workout").state == STATE_ON
    assert state_of(hass, "pace:_current").state == "10.0"
    assert state_of(hass, "pace:_max").state == "8.5"
    assert state_of(hass, "incline:_current").state == "4.5"
    assert state_of(hass, "speed:_current").state == "6.0"
    assert state_of(hass, "speed:_max").state == "7.06"
    # Pace has no long-term statistics: its unit follows the Peloton settings
    # and Home Assistant cannot convert it.
    for kind in ("average", "max", "current"):
        assert "state_class" not in state_of(hass, f"pace:_{kind}").attributes
    assert state_of(hass, "incline:_current").attributes["state_class"] == (
        "measurement"
    )


async def test_workout_start_without_samples(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """At the start of a ride Peloton sends metrics without samples (#61).

    Seen on a real ride for about the first minute: the workout sensor is on
    and the current values are unknown until the first sample arrives.
    """
    freezer.move_to("2025-10-09 09:00:00+00:00")
    graph = load_fixture("performance_graph.json")
    for metric in graph["metrics"]:
        metric["values"] = []
    aioclient_mock.clear_requests()
    _register_graph(aioclient_mock, graph, in_progress_detail(), in_progress_list())

    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "workout").state == STATE_ON
    for suffix in ("output:_current", "cadence:_current", "speed:_current"):
        assert state_of(hass, suffix).state == STATE_UNKNOWN, suffix


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [(in_progress_list(), in_progress_detail(is_paused=True))],
    ids=["paused"],
)
@pytest.mark.usefixtures("mock_api")
async def test_paused_workout(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A paused workout stays on, and current values read as between workouts."""
    freezer.move_to("2025-10-09 09:00:00+00:00")
    await setup_integration(hass, mock_config_entry)

    workout = state_of(hass, "workout")
    assert (workout.state, workout.attributes["paused"]) == (STATE_ON, True)
    assert state_of(hass, "cadence:_current").state == "0"
    assert state_of(hass, "output:_current").state == "0"
    assert state_of(hass, "heart_rate:_current").state == STATE_UNKNOWN
    # Averages and maximums of the workout so far stay.
    assert state_of(hass, "cadence:_max").state != STATE_UNKNOWN


@pytest.mark.usefixtures("imperial", "entity_registry_enabled_by_default")
async def test_tread_belt_stopped(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With the belt stopped Peloton sends no pace and a speed of 0."""
    freezer.move_to("2025-10-09 09:00:00+00:00")
    aioclient_mock.clear_requests()
    _register_graph(
        aioclient_mock,
        tread_graph(pace=(12.0, None), speed=(5.0, 0.0)),
        in_progress_detail(fitness_discipline="running"),
        in_progress_list(fitness_discipline="running"),
    )

    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "pace:_current").state == STATE_UNKNOWN
    assert state_of(hass, "speed:_current").state == "0.0"
    assert state_of(hass, "pace:_average").state == "11.43"
    assert state_of(hass, "pace:_max").state == "8.5"


@pytest.mark.parametrize(
    "workout_json",
    [load_fixture("api/workout.json") | {"fitness_discipline": "strength"}],
    ids=["strength"],
)
async def test_workout_without_metrics(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_api: AiohttpClientMocker,
    workout_json: dict[str, Any],
) -> None:
    """A workout without metrics (for example strength from the app) is handled."""
    aioclient_mock.clear_requests()
    _register_graph(
        aioclient_mock,
        {"duration": 600, "summaries": [], "metrics": []},
        workout_json,
    )

    await setup_integration(hass, mock_config_entry)

    assert state_of(hass, "workout").attributes["workout_type"] == "strength"
    assert state_of(hass, "heart_rate:_average").state == STATE_UNKNOWN
    assert state_of(hass, "distance").state == STATE_UNKNOWN
    assert state_of(hass, "cadence:_current").state == "0"


def _register_graph(
    aioclient_mock: AiohttpClientMocker,
    graph: dict[str, Any],
    workout: dict[str, Any],
    workouts: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> None:
    """Register the API with a custom performance graph and workout detail."""
    workout_id = "fedcba9876543210fedcba9876543210"
    for path, body in (
        ("/api/me", load_fixture("me.json")),
        (f"/api/user/{USER_ID}/settings", settings or load_fixture("settings.json")),
        (
            f"/api/user/{USER_ID}/workouts",
            workouts or load_fixture("api/workouts.json"),
        ),
        (f"/api/workout/{workout_id}/performance_graph", graph),
        (f"/api/workout/{workout_id}", workout),
    ):
        aioclient_mock.get(f"{API_BASE}{path}", json=body, headers=JSON_HEADERS)


async def test_entities_survive_a_few_failed_polls(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Entities keep their last state for a few failed polls, then go unavailable."""
    await setup_integration(hass, mock_config_entry)
    assert state_of(hass, "workout").state == STATE_OFF

    mock_api.clear_requests()
    mock_api.get(
        f"{API_BASE}/api/user/{USER_ID}/workouts",
        status=503,
        text="unavailable",
        headers=JSON_HEADERS,
    )
    coordinator = mock_config_entry.runtime_data
    for failures in range(1, TOLERATED_FAILED_POLLS + 1):
        await advance(hass, freezer)
        assert coordinator.failed_polls == failures
        # Home Assistant only writes state on the first failure of a streak;
        # make the entities re-read their availability after every failure.
        coordinator.async_update_listeners()
        assert state_of(hass, "workout").state == STATE_OFF
        assert state_of(hass, "heart_rate:_average").state == "140"

    await advance(hass, freezer, timedelta(seconds=60))

    assert state_of(hass, "workout").state == STATE_UNAVAILABLE
    assert state_of(hass, "heart_rate:_average").state == STATE_UNAVAILABLE


async def test_failed_poll_count_resets_after_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Failures separated by a successful poll do not add up."""
    await setup_integration(hass, mock_config_entry)
    for _ in range(TOLERATED_FAILED_POLLS + 1):
        mock_api.clear_requests()
        mock_api.get(
            f"{API_BASE}/api/user/{USER_ID}/workouts",
            status=503,
            text="unavailable",
            headers=JSON_HEADERS,
        )
        await advance(hass, freezer)
        assert state_of(hass, "workout").state == STATE_OFF
        mock_api.clear_requests()
        _register_graph(
            mock_api,
            load_fixture("performance_graph.json"),
            load_fixture("api/workout.json"),
        )
        await advance(hass, freezer)
        assert state_of(hass, "workout").state == STATE_OFF
    assert mock_config_entry.runtime_data.failed_polls == 0


async def test_unexpected_errors_count_as_failed_polls(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Errors that are not Peloton errors also end the tolerance."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data

    with patch.object(
        coordinator.client, "async_get_latest_workout", side_effect=RuntimeError
    ):
        for _ in range(TOLERATED_FAILED_POLLS + 1):
            await advance(hass, freezer)

    assert coordinator.failed_polls == TOLERATED_FAILED_POLLS + 1
    assert state_of(hass, "workout").state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [(in_progress_list(), in_progress_detail())],
    ids=["in_progress"],
)
async def test_long_rate_limit_makes_entities_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A rate limit with a long wait does not keep showing a running workout."""
    freezer.move_to("2025-10-09 09:00:00+00:00")
    await setup_integration(hass, mock_config_entry)
    assert state_of(hass, "workout").state == STATE_ON

    mock_api.clear_requests()
    mock_api.get(
        f"{API_BASE}/api/user/{USER_ID}/workouts",
        status=429,
        text="slow down",
        headers={"content-type": "text/plain", "Retry-After": "900"},
    )
    await advance(hass, freezer, timedelta(seconds=10))

    assert state_of(hass, "workout").state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [
        (
            in_progress_list(ride=load_fixture("api/workout_just_ride.json")["ride"]),
            in_progress_detail(ride=load_fixture("api/workout_just_ride.json")["ride"]),
        )
    ],
    ids=["just_ride"],
)
async def test_max_workout_minutes_option(
    hass: HomeAssistant,
    mock_api: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The max_workout_minutes option sets when a Just Ride counts as ended."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id=USER_ID,
        data={CONF_USERNAME: USERNAME, CONF_TOKEN: stored_tokens()},
        options={"max_workout_minutes": 60},
    )
    freezer.move_to("2025-10-09 09:50:00+00:00")
    await setup_integration(hass, entry)
    assert state_of(hass, "workout").state == STATE_ON

    freezer.move_to("2025-10-09 09:55:00+00:00")
    await advance(hass, freezer)

    assert state_of(hass, "workout").state == STATE_OFF


@pytest.mark.usefixtures("mock_api")
async def test_energy_totals_reset_at_workout_start(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Per-workout totals report the workout start as last_reset."""
    await setup_integration(hass, mock_config_entry)

    for suffix in ("power_output", "total_calories", "active_calories", "total_output"):
        assert (
            state_of(hass, suffix).attributes["last_reset"]
            == "2025-10-09T08:53:20+00:00"
        ), suffix
    assert "last_reset" not in state_of(hass, "total_workouts").attributes


@pytest.mark.parametrize("workouts_json", [load_fixture("api/workouts_empty.json")])
@pytest.mark.usefixtures("mock_api")
async def test_energy_totals_without_workout(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Without a workout the totals and their last_reset are unknown."""
    await setup_integration(hass, mock_config_entry)

    state = state_of(hass, "total_calories")
    assert state.state == STATE_UNKNOWN
    assert state.attributes.get("last_reset") is None
