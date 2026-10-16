"""Unit tests for value helpers that need no Home Assistant instance."""

from datetime import UTC, datetime

from custom_components.peloton import binary_sensor, sensor
from custom_components.peloton.api import (
    Metric,
    PelotonUser,
    PerformanceGraph,
    Summary,
    UserSettings,
    Workout,
)
from custom_components.peloton.coordinator import PelotonData, workout_active
from custom_components.peloton.sensor import SENSORS

NOW = datetime(2025, 10, 9, 9, 0, tzinfo=UTC)


def _sensor(key: str):
    return next(description for description in SENSORS if description.key == key)


def _data(graph: PerformanceGraph, *, active: bool = True) -> PelotonData:
    return PelotonData(
        user=PelotonUser(id="u", username="x", first_name=None, total_workouts=0),
        settings=UserSettings(distance_unit="imperial"),
        workout=Workout.from_api({"status": "IN_PROGRESS"}),
        performance_graph=graph,
        timezone=UTC,
        active=active,
    )


def test_running_workout_without_any_time_is_active() -> None:
    """Without a start or creation time there is nothing to measure against."""
    workout = Workout.from_api({"status": "IN_PROGRESS"})

    assert workout_active(workout, NOW, 240)


def test_running_workout_falls_back_to_created_at() -> None:
    """Without a start time, the creation time bounds the workout."""
    old = Workout.from_api(
        {"status": "IN_PROGRESS", "created_at": NOW.timestamp() - 11 * 86400}
    )
    recent = Workout.from_api(
        {"status": "IN_PROGRESS", "created_at": NOW.timestamp() - 60}
    )

    assert not workout_active(old, NOW, 240)
    assert workout_active(recent, NOW, 240)


def test_speed_unit_from_metric() -> None:
    """The speed metric's display unit is used (kph here, settings imperial)."""
    graph = PerformanceGraph(
        duration=60,
        metrics={"speed": Metric("speed", "kph", 16.09344, 32.18688, (16.09344,))},
    )
    data = _data(graph)

    assert _sensor("speed_current").value_fn(data) == 10.0
    assert _sensor("speed_max").value_fn(data) == 20.0


def test_parallel_updates() -> None:
    """Entities never update in parallel batches; the coordinator does the polling."""
    assert sensor.PARALLEL_UPDATES == 0
    assert binary_sensor.PARALLEL_UPDATES == 0


def test_unknown_units_give_no_value() -> None:
    """Values in a unit the integration does not know are not guessed."""
    graph = PerformanceGraph(
        duration=60,
        summaries={"distance": Summary("distance", 3.0, "furlongs")},
        metrics={"speed": Metric("speed", "knots", 10.0, 12.0, (11.0,))},
    )
    data = _data(graph)

    assert _sensor("distance").value_fn(data) is None
    assert _sensor("speed_current").value_fn(data) is None
    assert _sensor("speed_max").value_fn(data) is None


def test_speed_unit_from_average_summary() -> None:
    """Without a speed metric, the average summary's unit is used."""
    graph = PerformanceGraph(
        duration=60,
        average_summaries={"avg_speed": Summary("avg_speed", 6.0, "mph")},
    )

    assert _sensor("speed_average").value_fn(_data(graph)) == 6.0
