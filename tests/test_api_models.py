"""Tests for parsing Peloton API responses."""

from typing import Any

import pytest

from custom_components.peloton.api import (
    PelotonUser,
    PerformanceGraph,
    Ride,
    UserSettings,
    Workout,
)

from .conftest import USER_ID, load_fixture


def test_user() -> None:
    """/api/me parses into a user with workout counts by slug."""
    user = PelotonUser.from_api(load_fixture("me.json"))

    assert user.id == USER_ID
    assert user.username == "testrider"
    assert user.first_name == "Test"
    assert user.total_workouts == 96
    assert user.workout_counts["caesar"] == 2
    assert len(user.workout_counts) == 12


def test_user_skips_malformed_counts() -> None:
    """Workout count entries without a slug or numeric count are skipped."""
    user = PelotonUser.from_api(
        {
            "workout_counts": [
                {"slug": "cycling", "count": 3},
                {"slug": "yoga", "count": "many"},
                {"count": 4},
                "junk",
            ]
        }
    )

    assert user.workout_counts == {"cycling": 3}
    assert user.id is None


def test_settings() -> None:
    """The distance unit is read from the settings."""
    assert UserSettings.from_api(load_fixture("settings.json")).distance_unit == (
        "imperial"
    )
    assert UserSettings.from_api({}).distance_unit is None


def test_workout_detail() -> None:
    """A workout from /api/workout/{id} has every field."""
    workout = Workout.from_api(load_fixture("api/workout.json"))

    assert workout == Workout(
        id="fedcba9876543210fedcba9876543210",
        user_id=USER_ID,
        status="COMPLETE",
        fitness_discipline="cycling",
        device_type="home_bike_plus",
        timezone="America/New_York",
        created_at=1760000000,
        start_time=1760000000,
        end_time=1760001800,
        is_paused=False,
        total_work=360000.0,
        leaderboard_rank=120,
        total_leaderboard_users=4000,
        ftp=200,
        ride=Ride(
            id="00112233445566778899aabbccddeeff",
            title="30 min Synthetic Ride",
            description="Synthetic class used in tests.",
            image_url="https://example.invalid/ride.png",
            duration=1800,
            instructor_name="Synthetic Instructor",
        ),
    )
    assert not workout.is_in_progress
    assert workout.ride is not None
    assert workout.ride.is_class


def test_workout_list_row() -> None:
    """A workout list row has no leaderboard, output, FTP or pause fields."""
    workout = Workout.from_api(load_fixture("api/workouts.json")["data"][0])

    assert workout.status == "COMPLETE"
    assert workout.total_work is None
    assert workout.leaderboard_rank is None
    assert workout.ftp is None
    assert workout.is_paused is None


def test_just_ride() -> None:
    """A workout without a class has no instructor and is not a class."""
    workout = Workout.from_api(load_fixture("api/workout_just_ride.json"))

    assert workout.ride is not None
    assert not workout.ride.is_class
    # The joined ride carries a placeholder instructor named "JUST RIDE".
    assert workout.ride.instructor_name is None
    assert workout.ride.title == "Just Ride"
    assert workout.ride.duration == 1800


def test_in_progress() -> None:
    """IN_PROGRESS marks a running workout."""
    assert Workout.from_api({"status": "IN_PROGRESS"}).is_in_progress


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        "text",
        {
            "id": 5,
            "start_time": "1760000000",
            "end_time": None,
            "total_work": True,
            "is_paused": "no",
            "leaderboard_rank": 1.0,
            "ftp_info": None,
            "ride": "not a ride",
        },
    ],
    ids=["none", "list", "string", "wrong_types"],
)
def test_workout_tolerates_bad_data(data: Any) -> None:
    """Missing or wrongly typed fields become None instead of raising."""
    workout = Workout.from_api(data)

    assert workout.id is None
    assert workout.start_time is None
    assert workout.end_time is None
    assert workout.total_work is None
    assert workout.is_paused is None
    assert workout.ftp is None
    assert workout.ride is None
    if isinstance(data, dict):
        assert workout.leaderboard_rank == 1


def test_performance_graph() -> None:
    """Summaries and metrics are keyed by slug."""
    graph = PerformanceGraph.from_api(load_fixture("performance_graph.json"))

    assert graph.duration == 1800
    assert graph.summaries["calories"].value == 450
    assert graph.summaries["distance"].display_unit == "mi"
    heart_rate = graph.metrics["heart_rate"]
    assert (heart_rate.average, heart_rate.maximum, heart_rate.last) == (140, 165, 148)
    assert graph.metrics["speed"].last == 20.4
    # Peloton's displayed averages can differ from the metric averages.
    assert graph.average_summaries["avg_speed"].value == 17.5
    assert graph.metrics["speed"].average == 20.1
    assert set(graph.average_summaries) == {
        "avg_output",
        "avg_cadence",
        "avg_resistance",
        "avg_speed",
    }


def test_performance_graph_tolerates_bad_data() -> None:
    """Empty sample lists, booleans and missing slugs do not break parsing."""
    graph = PerformanceGraph.from_api(
        {
            "summaries": [{"slug": "calories", "value": True}, {"value": 3}],
            "metrics": [
                {"slug": "cadence", "values": [], "average_value": None},
                {"slug": "output", "values": [100, "x"], "max_value": False},
                "junk",
            ],
        }
    )

    assert graph.summaries["calories"].value is None
    assert len(graph.summaries) == 1
    assert graph.average_summaries == {}
    assert graph.metrics["cadence"].last is None
    assert graph.metrics["output"].values == (100, None)
    assert graph.metrics["output"].last is None
    assert graph.metrics["output"].maximum is None
    assert PerformanceGraph.from_api(None) == PerformanceGraph(duration=None)
