"""Temporary adapter from the API models to the existing sensor list.

Phase 3 of the refactor replaces this module with entity descriptions. Until
then it builds the same PelotonStat list (names, units, device and state
classes) that the pylotoncycle-based code produced, so unique ids and states
stay the same.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTime,
)
from homeassistant.util import dt as dt_util

from .api import Metric, PelotonUser, PerformanceGraph, Summary, UserSettings, Workout


@dataclass
class PelotonStat:
    """One sensor value."""

    name: str
    native_value: Any
    native_unit_of_measurement: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    icon: str | None = None
    entity_category: EntityCategory | None = None
    entity_registry_enabled_default: bool = True


# Workout count sensors: display name and Peloton fitness discipline slug.
WORKOUT_COUNTS = (
    ("Bike Bootcamp count", "bike_bootcamp", "mdi:bike"),
    ("Rowing count", "caesar", "mdi:rowing"),
    ("Row Bootcamp count", "caesar_bootcamp", "mdi:rowing"),
    ("Cardio count", "cardio", "mdi:heart"),
    ("Tread Bootcamp count", "circuit", "mdi:run-fast"),
    ("Cycling count", "cycling", "mdi:bike"),
    ("Meditation count", "meditation", "mdi:meditation"),
    ("Running count", "running", "mdi:run-fast"),
    ("Strength count", "strength", "mdi:weight-lifter"),
    ("Stretching count", "stretching", "mdi:gymnastics"),
    ("Walking count", "walking", "mdi:walk"),
    ("Yoga count", "yoga", "mdi:yoga"),
)


async def async_resolve_timezone(name: str | None) -> tzinfo:
    """Return the workout's time zone, or UTC if it is missing or unknown."""
    if name:
        try:
            zone = await dt_util.async_get_time_zone(name)
        except ValueError:
            # zoneinfo rejects keys that are not normalized relative paths.
            zone = None
        if zone is not None:
            return zone
    return dt_util.UTC


async def async_build_stats(
    user: PelotonUser,
    settings: UserSettings,
    workout: Workout | None,
    graph: PerformanceGraph | None,
) -> list[PelotonStat]:
    """Return the sensor values for the latest workout and the profile."""
    in_progress = workout is not None and workout.is_in_progress
    zone = await async_resolve_timezone(workout.timezone if workout else None)

    start_time = _timestamp(workout.start_time if workout else None, zone)
    end_time = _timestamp(workout.end_time if workout else None, zone)
    duration = workout.ride.duration if workout and workout.ride else None
    # Peloton sets end_time to start_time while a workout is running (#86).
    if start_time and end_time and start_time == end_time and duration is not None:
        end_time = start_time + timedelta(seconds=duration)

    summaries = graph.summaries if graph else {}
    metrics = graph.metrics if graph else {}
    calories = summaries.get("total_calories") or summaries.get("calories")
    distance_unit = settings.distance_unit
    length_unit = _by_unit_system(
        distance_unit, UnitOfLength.MILES, UnitOfLength.KILOMETERS
    )
    speed_unit = _by_unit_system(
        distance_unit, UnitOfSpeed.MILES_PER_HOUR, UnitOfSpeed.KILOMETERS_PER_HOUR
    )
    total_work = workout.total_work if workout else None

    def current(metric: Metric | None, idle: float) -> Any:
        """Return the latest sample during a workout, else the idle value."""
        if not in_progress:
            return idle
        return metric.last if metric else None

    heart_rate = metrics.get("heart_rate")
    resistance = metrics.get("resistance")
    speed = metrics.get("speed")
    cadence = metrics.get("cadence")

    stats = [
        PelotonStat(
            "Start Time",
            start_time,
            None,
            SensorDeviceClass.TIMESTAMP,
            None,
            "mdi:timer-sand",
        ),
        PelotonStat(
            "End Time",
            end_time,
            None,
            SensorDeviceClass.TIMESTAMP,
            None,
            "mdi:timer-sand-complete",
        ),
        PelotonStat(
            "Duration",
            round(duration / 60, 2) if duration else duration,
            UnitOfTime.MINUTES,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:timer-outline",
        ),
        PelotonStat(
            "Leaderboard: Rank",
            _or_zero(workout.leaderboard_rank if workout else None),
            None,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:trophy-award",
        ),
        PelotonStat(
            "Leaderboard: Total Users",
            _or_zero(workout.total_leaderboard_users if workout else None),
            None,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:account-group",
        ),
        PelotonStat(
            "Power Output",
            round(total_work / 3600, 4) if total_work is not None else None,
            UnitOfEnergy.WATT_HOUR,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL,
            None,
        ),
        PelotonStat(
            "Distance",
            _value(summaries.get("distance")),
            length_unit,
            SensorDeviceClass.DISTANCE if "distance" in summaries else None,
            SensorStateClass.MEASUREMENT,
            "mdi:map-marker-distance",
        ),
        PelotonStat(
            "Total Calories",
            _value(calories),
            _unit(calories),
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:fire",
        ),
        PelotonStat(
            "Active Calories",
            _value(summaries.get("active_calories")),
            _unit(summaries.get("active_calories")),
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:fire",
        ),
        PelotonStat(
            "Total Output",
            _value(summaries.get("total_output")),
            _unit(summaries.get("total_output")),
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:lightning-bolt",
        ),
        PelotonStat(
            "Heart Rate: Average",
            heart_rate.average if heart_rate else None,
            _unit(heart_rate),
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:heart-pulse",
        ),
        PelotonStat(
            "Heart Rate: Max",
            heart_rate.maximum if heart_rate else None,
            _unit(heart_rate),
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:heart-pulse",
        ),
        PelotonStat(
            "Heart Rate: Current",
            current(heart_rate, 0),
            "bpm",
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:heart-pulse",
        ),
        PelotonStat(
            "Resistance: Average",
            resistance.average if resistance else None,
            PERCENTAGE,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:network-strength-2",
        ),
        PelotonStat(
            "Resistance: Max",
            resistance.maximum if resistance else None,
            PERCENTAGE,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:network-strength-4",
        ),
        PelotonStat(
            "Resistance: Current",
            current(resistance, 0),
            PERCENTAGE,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:network-strength-1",
        ),
        PelotonStat(
            "Speed: Average",
            speed.average if speed else None,
            speed_unit,
            SensorDeviceClass.SPEED if speed else None,
            SensorStateClass.MEASUREMENT,
            "mdi:speedometer-medium",
        ),
        PelotonStat(
            "Speed: Max",
            speed.maximum if speed else None,
            speed_unit,
            SensorDeviceClass.SPEED if speed else None,
            SensorStateClass.MEASUREMENT,
            "mdi:speedometer",
        ),
        PelotonStat(
            "Speed: Current",
            current(speed, 0.0),
            speed_unit,
            SensorDeviceClass.SPEED if speed else None,
            SensorStateClass.MEASUREMENT,
            "mdi:speedometer-slow",
        ),
        PelotonStat(
            "Cadence: Average",
            cadence.average if cadence else None,
            REVOLUTIONS_PER_MINUTE,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:fan",
        ),
        PelotonStat(
            "Cadence: Max",
            cadence.maximum if cadence else None,
            REVOLUTIONS_PER_MINUTE,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:fan-chevron-up",
        ),
        PelotonStat(
            "Cadence: Current",
            current(cadence, 0),
            REVOLUTIONS_PER_MINUTE,
            None,
            SensorStateClass.MEASUREMENT,
            "mdi:fan-clock",
        ),
    ]
    stats.extend(
        PelotonStat(
            name=name,
            native_value=user.workout_counts.get(slug),
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon=icon,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        )
        for name, slug, icon in WORKOUT_COUNTS
    )
    return stats


def _timestamp(value: int | None, zone: tzinfo) -> datetime | None:
    return datetime.fromtimestamp(value, zone) if value is not None else None


def _by_unit_system(
    distance_unit: str | None, imperial: str, metric: str
) -> str | None:
    if distance_unit == "imperial":
        return imperial
    if distance_unit == "metric":
        return metric
    return None


def _or_zero(value: int | None) -> int:
    return value if value is not None else 0


def _value(item: Summary | None) -> Any:
    return item.value if item else None


def _unit(item: Summary | Metric | None) -> str | None:
    return item.display_unit if item else None
