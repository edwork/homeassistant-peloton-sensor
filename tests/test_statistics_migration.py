"""Long-term statistics recorded by earlier versions keep working."""

from datetime import datetime, timedelta
from functools import partial
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    get_last_short_term_statistics,
    get_metadata,
    update_statistics_issues,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
    do_adhoc_statistics,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.api.const import API_BASE
from custom_components.peloton.const import DOMAIN

from .common import setup_integration
from .conftest import JSON_HEADERS, USER_ID, WORKOUT_ID, load_fixture

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


CALORIES = "sensor.test_on_peloton_total_calories"
CREATED = "2025-10-09T08:53:20+00:00"
# Where Peloton moves start_time when the workout completes.
MOVED_START = "2025-10-09T08:54:20+00:00"


def register_api(
    aioclient_mock: AiohttpClientMocker,
    workouts: dict[str, Any],
    workout: dict[str, Any],
) -> None:
    """Answer the Peloton endpoints polled with stored tokens."""
    for path, body in (
        ("/api/me", load_fixture("me.json")),
        (f"/api/user/{USER_ID}/settings", load_fixture("settings.json")),
        (f"/api/user/{USER_ID}/workouts", workouts),
        (
            f"/api/workout/{WORKOUT_ID}/performance_graph",
            load_fixture("performance_graph.json"),
        ),
        (f"/api/workout/{WORKOUT_ID}", workout),
    ):
        aioclient_mock.get(f"{API_BASE}{path}", json=body, headers=JSON_HEADERS)


def _completed_with_moved_start() -> tuple[dict[str, Any], dict[str, Any]]:
    workouts = load_fixture("api/workouts.json")
    workouts["data"][0]["start_time"] = 1760000060
    return workouts, load_fixture("api/workout.json") | {"start_time": 1760000060}


async def _short_term(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    found = await get_instance(hass).async_add_executor_job(
        get_last_short_term_statistics, hass, 1, entity_id, False, {"last_reset", "sum"}
    )
    return found[entity_id][0]


def _register_calories(
    entity_registry: er.EntityRegistry, entry: MockConfigEntry
) -> None:
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{USER_ID}_total_calories",
        config_entry=entry,
        suggested_object_id="test_on_peloton_total_calories",
    )


async def _record_earlier_version(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    start: datetime,
    last_reset: str,
) -> None:
    """Record statistics as an earlier version would have, then remove the state."""
    freezer.move_to(start + timedelta(minutes=1))
    hass.states.async_set(
        CALORIES,
        "450",
        {
            "state_class": "total",
            "device_class": "energy",
            "unit_of_measurement": "kcal",
            "last_reset": last_reset,
        },
    )
    await async_wait_recording_done(hass)
    do_adhoc_statistics(hass, start=start)
    await async_wait_recording_done(hass)
    hass.states.async_remove(CALORIES)


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [_completed_with_moved_start()],
    ids=["completed"],
)
@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_upgrade_keeps_recorded_last_reset(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A last_reset of the latest workout in the statistics is kept on upgrade.

    1.0.0 used the start time, which Peloton moved when the workout
    completed. Switching to the creation time would count the workout again.
    """
    await async_setup_component(hass, "sensor", {})
    await async_wait_recording_done(hass)
    mock_config_entry.add_to_hass(hass)
    _register_calories(entity_registry, mock_config_entry)
    start = dt_util.parse_datetime("2025-10-09 10:00:00+00:00")
    await _record_earlier_version(hass, freezer, start, MOVED_START)
    # The first value of a new statistic is its starting point.
    assert (await _short_term(hass, CALORIES))["sum"] == 0

    freezer.move_to(start + timedelta(minutes=6))
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(CALORIES).attributes["last_reset"] == MOVED_START
    # Totals without recorded statistics use the creation time.
    assert (
        hass.states.get("sensor.test_on_peloton_total_output").attributes["last_reset"]
        == CREATED
    )
    await async_wait_recording_done(hass)
    do_adhoc_statistics(hass, start=start + timedelta(minutes=5))
    await async_wait_recording_done(hass)

    # A new cycle would have added the workout's 450 kcal again.
    stats = await _short_term(hass, CALORIES)
    assert stats["sum"] == 0
    assert stats["last_reset"] == dt_util.parse_datetime(MOVED_START).timestamp()


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [_completed_with_moved_start()],
    ids=["completed"],
)
@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_upgrade_soon_after_completion(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """States recorded after the last compiled period win over it.

    1.0.0 recorded the completion (moved start), and Home Assistant
    restarted before the next compile. The next compile compares the new
    version's first state with that last recorded state, not with the row.
    """
    await async_setup_component(hass, "sensor", {})
    await async_wait_recording_done(hass)
    mock_config_entry.add_to_hass(hass)
    _register_calories(entity_registry, mock_config_entry)
    start = dt_util.parse_datetime("2025-10-09 10:00:00+00:00")
    await _record_earlier_version(hass, freezer, start, CREATED)
    freezer.move_to(start + timedelta(minutes=6))
    hass.states.async_set(
        CALORIES,
        "450",
        {
            "state_class": "total",
            "device_class": "energy",
            "unit_of_measurement": "kcal",
            "last_reset": MOVED_START,
        },
    )
    # Unavailable at shutdown: skipped, as by the compile.
    hass.states.async_set(CALORIES, "unavailable", {"state_class": "total"})
    await async_wait_recording_done(hass)
    hass.states.async_remove(CALORIES)

    freezer.move_to(start + timedelta(minutes=7))
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(CALORIES).attributes["last_reset"] == MOVED_START
    await async_wait_recording_done(hass)
    do_adhoc_statistics(hass, start=start + timedelta(minutes=5))
    await async_wait_recording_done(hass)

    # 1.0.0 already started a second cycle at the completion; no third one.
    assert (await _short_term(hass, CALORIES))["sum"] == 450


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [_completed_with_moved_start()],
    ids=["completed"],
)
@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_upgrade_keeps_last_reset_between_creation_and_start(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A start time 1.0.0 recorded during the workout is kept too.

    It need not equal the creation time; it lies between the creation time
    and the final start time.
    """
    await async_setup_component(hass, "sensor", {})
    await async_wait_recording_done(hass)
    mock_config_entry.add_to_hass(hass)
    _register_calories(entity_registry, mock_config_entry)
    start = dt_util.parse_datetime("2025-10-09 10:00:00+00:00")
    await _record_earlier_version(hass, freezer, start, "2025-10-09T08:53:50+00:00")

    freezer.move_to(start + timedelta(minutes=6))
    await setup_integration(hass, mock_config_entry)

    assert (
        hass.states.get(CALORIES).attributes["last_reset"]
        == "2025-10-09T08:53:50+00:00"
    )


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [_completed_with_moved_start()],
    ids=["completed"],
)
@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_recorded_state_without_last_reset_uses_row(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A later numeric state without last_reset leaves the row's value."""
    await async_setup_component(hass, "sensor", {})
    await async_wait_recording_done(hass)
    mock_config_entry.add_to_hass(hass)
    _register_calories(entity_registry, mock_config_entry)
    start = dt_util.parse_datetime("2025-10-09 10:00:00+00:00")
    await _record_earlier_version(hass, freezer, start, MOVED_START)
    freezer.move_to(start + timedelta(minutes=6))
    hass.states.async_set(CALORIES, "450", {"state_class": "total"})
    await async_wait_recording_done(hass)
    hass.states.async_remove(CALORIES)

    freezer.move_to(start + timedelta(minutes=7))
    await setup_integration(hass, mock_config_entry)

    assert hass.states.get(CALORIES).attributes["last_reset"] == MOVED_START


@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_recorded_last_reset_of_earlier_workout_is_not_kept(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A last_reset of an earlier workout starts a new cycle for the latest one."""
    await async_setup_component(hass, "sensor", {})
    await async_wait_recording_done(hass)
    mock_config_entry.add_to_hass(hass)
    _register_calories(entity_registry, mock_config_entry)
    start = dt_util.parse_datetime("2025-10-09 10:00:00+00:00")
    await _record_earlier_version(hass, freezer, start, "2025-10-08T08:00:00+00:00")

    freezer.move_to(start + timedelta(minutes=6))
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(CALORIES).attributes["last_reset"] == CREATED
    await async_wait_recording_done(hass)
    do_adhoc_statistics(hass, start=start + timedelta(minutes=5))
    await async_wait_recording_done(hass)

    assert (await _short_term(hass, CALORIES))["sum"] == 450


@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations")
async def test_completed_workout_is_counted_once(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A workout's totals are counted once, although its start time moves."""
    start = dt_util.parse_datetime("2025-10-09 09:00:00+00:00")
    freezer.move_to(start + timedelta(minutes=1))
    workouts = load_fixture("api/workouts.json")
    workouts["data"][0] |= {"status": "IN_PROGRESS", "end_time": None}
    workout = load_fixture("api/workout.json") | {
        "status": "IN_PROGRESS",
        "end_time": None,
    }
    register_api(aioclient_mock, workouts, workout)
    await setup_integration(hass, mock_config_entry)
    await async_wait_recording_done(hass)
    do_adhoc_statistics(hass, start=start)
    await async_wait_recording_done(hass)
    assert (await _short_term(hass, CALORIES))["sum"] == 0

    aioclient_mock.clear_requests()
    register_api(aioclient_mock, *_completed_with_moved_start())
    freezer.move_to(start + timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.test_on_peloton_start_time").state == MOVED_START
    await async_wait_recording_done(hass)
    do_adhoc_statistics(hass, start=start + timedelta(minutes=5))
    await async_wait_recording_done(hass)

    # 1.0.0 started a new cycle here and added the 450 kcal again.
    assert (await _short_term(hass, CALORIES))["sum"] == 0


@pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations", "mock_api")
async def test_last_reset_read_error_does_not_block_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """If the statistics cannot be read, the totals use the creation time."""
    mock_config_entry.add_to_hass(hass)
    _register_calories(entity_registry, mock_config_entry)

    with patch(
        "homeassistant.components.recorder.statistics.get_last_short_term_statistics",
        side_effect=RuntimeError("database locked"),
    ):
        await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(CALORIES).attributes["last_reset"] == CREATED
