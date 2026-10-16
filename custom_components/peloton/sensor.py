"""Sensors for the latest Peloton workout and the account's workout counts."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import DistanceConverter, SpeedConverter

from .api import Metric, Summary
from .coordinator import PelotonConfigEntry, PelotonCoordinator, PelotonData
from .entity import PelotonEntity

PARALLEL_UPDATES = 0

BEATS_PER_MINUTE = "bpm"

# Units Peloton uses in display_unit, mapped to Home Assistant units.
_DISTANCE_UNITS: dict[str, str] = {
    "mi": UnitOfLength.MILES,
    "km": UnitOfLength.KILOMETERS,
    "m": UnitOfLength.METERS,
    "ft": UnitOfLength.FEET,
    "yd": UnitOfLength.YARDS,
}
_SPEED_UNITS: dict[str, str] = {
    "mph": UnitOfSpeed.MILES_PER_HOUR,
    "kph": UnitOfSpeed.KILOMETERS_PER_HOUR,
    "km/h": UnitOfSpeed.KILOMETERS_PER_HOUR,
}


@dataclass(frozen=True, kw_only=True)
class PelotonSensorEntityDescription(SensorEntityDescription):
    """Describes a Peloton sensor."""

    # Suffix of the unique_id; kept from earlier versions so existing entities
    # keep their entity_ids and history.
    unique_suffix: str
    value_fn: Callable[[PelotonData], StateType | datetime]
    # For units that follow the account's Peloton settings (distance, speed).
    unit_fn: Callable[[PelotonData], str] | None = None
    # For per-workout totals: when the total started (the workout start).
    last_reset_fn: Callable[[PelotonData], datetime | None] | None = None


def _imperial(data: PelotonData) -> bool:
    return data.settings.distance_unit == "imperial"


def _length_unit(data: PelotonData) -> str:
    """Distance unit of the account's Peloton settings (metric if unset)."""
    return UnitOfLength.MILES if _imperial(data) else UnitOfLength.KILOMETERS


def _speed_unit(data: PelotonData) -> str:
    """Speed unit of the account's Peloton settings (metric if unset)."""
    if _imperial(data):
        return UnitOfSpeed.MILES_PER_HOUR
    return UnitOfSpeed.KILOMETERS_PER_HOUR


def _summary(data: PelotonData, *slugs: str) -> Summary | None:
    """Return the first workout total found among ``slugs``."""
    graph = data.performance_graph
    if graph is None:
        return None
    for slug in slugs:
        if (summary := graph.summaries.get(slug)) is not None:
            return summary
    return None


def _summary_value(data: PelotonData, *slugs: str) -> StateType:
    summary = _summary(data, *slugs)
    return summary.value if summary else None


def _metric(data: PelotonData, slug: str) -> Metric | None:
    graph = data.performance_graph
    return graph.metrics.get(slug) if graph else None


def _average(data: PelotonData, slug: str) -> int | float | None:
    """Return Peloton's displayed average, else the metric's average.

    For bike speed the two differ: Peloton shows distance over the whole
    workout, while the metric averages the sampled values.
    """
    graph = data.performance_graph
    if graph is None:
        return None
    summary = graph.average_summaries.get(f"avg_{slug}")
    if summary is not None and summary.value is not None:
        return summary.value
    metric = graph.metrics.get(slug)
    return metric.average if metric else None


def _maximum(data: PelotonData, slug: str) -> int | float | None:
    metric = _metric(data, slug)
    return metric.maximum if metric else None


def _current(data: PelotonData, slug: str, idle: int | None) -> int | float | None:
    """Return the latest sample during a workout, else ``idle``."""
    if not data.active:
        return idle
    metric = _metric(data, slug)
    return metric.last if metric else None


def _speed(data: PelotonData, value: float | None) -> float | None:
    """Convert a speed from Peloton's display unit to the settings unit."""
    if not value:
        return value
    graph = data.performance_graph
    metric = graph.metrics.get("speed") if graph else None
    summary = graph.average_summaries.get("avg_speed") if graph else None
    unit = (metric.display_unit if metric else None) or (
        summary.display_unit if summary else None
    )
    if (source := _SPEED_UNITS.get(unit or "")) is None:
        return None
    return round(SpeedConverter.convert(value, source, _speed_unit(data)), 2)


def _distance(data: PelotonData) -> float | None:
    """Return the distance, converted to the settings unit (rower meters too)."""
    summary = _summary(data, "distance")
    if summary is None or summary.value is None:
        return None
    if (source := _DISTANCE_UNITS.get(summary.display_unit or "")) is None:
        return None
    return round(
        DistanceConverter.convert(summary.value, source, _length_unit(data)), 3
    )


def _timestamp(data: PelotonData, value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, data.timezone) if value is not None else None


def _start_time(data: PelotonData) -> datetime | None:
    return _timestamp(data, data.workout.start_time if data.workout else None)


def _end_time(data: PelotonData) -> datetime | None:
    workout = data.workout
    if workout is None:
        return None
    start, end = _start_time(data), _timestamp(data, workout.end_time)
    duration = workout.ride.duration if workout.ride else None
    # Peloton sets end_time to start_time for some workouts (#86).
    if start and end and start == end and duration is not None:
        return start + timedelta(seconds=duration)
    return end


def _duration(data: PelotonData) -> float | None:
    workout = data.workout
    duration = workout.ride.duration if workout and workout.ride else None
    return round(duration / 60, 2) if duration else None


def _total_work(data: PelotonData) -> float | None:
    total_work = data.workout.total_work if data.workout else None
    return round(total_work / 3600, 4) if total_work is not None else None


def _metric_sensors(
    slug: str,
    unit: str,
    *,
    idle: int | None,
    device_class: SensorDeviceClass | None = None,
) -> tuple[PelotonSensorEntityDescription, ...]:
    """Return the average, max and current sensors of one metric.

    ``idle`` is the current value between workouts.
    """
    return tuple(
        PelotonSensorEntityDescription(
            key=f"{slug}_{kind}",
            translation_key=f"{slug}_{kind}",
            unique_suffix=f"{slug}:_{kind}",
            native_unit_of_measurement=unit,
            device_class=device_class,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=value_fn,
        )
        for kind, value_fn in (
            ("average", lambda data: _average(data, slug)),
            ("max", lambda data: _maximum(data, slug)),
            ("current", lambda data: _current(data, slug, idle)),
        )
    )


def _speed_sensors() -> tuple[PelotonSensorEntityDescription, ...]:
    return tuple(
        PelotonSensorEntityDescription(
            key=f"speed_{kind}",
            translation_key=f"speed_{kind}",
            unique_suffix=f"speed:_{kind}",
            device_class=SensorDeviceClass.SPEED,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
            unit_fn=_speed_unit,
            value_fn=value_fn,
        )
        for kind, value_fn in (
            ("average", lambda data: _speed(data, _average(data, "speed"))),
            ("max", lambda data: _speed(data, _maximum(data, "speed"))),
            ("current", lambda data: _speed(data, _current(data, "speed", 0))),
        )
    )


# Workout count sensors: key (also the translation key and unique suffix) and
# the Peloton fitness discipline slug.
WORKOUT_COUNTS = (
    ("bike_bootcamp_count", "bike_bootcamp"),
    ("rowing_count", "caesar"),
    ("row_bootcamp_count", "caesar_bootcamp"),
    ("cardio_count", "cardio"),
    ("tread_bootcamp_count", "circuit"),
    ("cycling_count", "cycling"),
    ("meditation_count", "meditation"),
    ("running_count", "running"),
    ("strength_count", "strength"),
    ("stretching_count", "stretching"),
    ("walking_count", "walking"),
    ("yoga_count", "yoga"),
)


def _count_sensor(key: str, slug: str) -> PelotonSensorEntityDescription:
    return PelotonSensorEntityDescription(
        key=key,
        translation_key=key,
        unique_suffix=key,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.user.workout_counts.get(slug),
    )


SENSORS: tuple[PelotonSensorEntityDescription, ...] = (
    PelotonSensorEntityDescription(
        key="start_time",
        translation_key="start_time",
        unique_suffix="start_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_start_time,
    ),
    PelotonSensorEntityDescription(
        key="end_time",
        translation_key="end_time",
        unique_suffix="end_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_end_time,
    ),
    PelotonSensorEntityDescription(
        key="duration",
        translation_key="duration",
        unique_suffix="duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_duration,
    ),
    PelotonSensorEntityDescription(
        key="leaderboard_rank",
        translation_key="leaderboard_rank",
        unique_suffix="leaderboard:_rank",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.workout.leaderboard_rank if data.workout else None,
    ),
    PelotonSensorEntityDescription(
        key="leaderboard_total_users",
        translation_key="leaderboard_total_users",
        unique_suffix="leaderboard:_total_users",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            data.workout.total_leaderboard_users if data.workout else None
        ),
    ),
    PelotonSensorEntityDescription(
        # Called "Power Output" before; it is the workout's total work (energy).
        # Per-workout totals reset at each workout start (last_reset), so
        # long-term statistics count every workout in full.
        key="total_work",
        translation_key="total_work",
        unique_suffix="power_output",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        last_reset_fn=_start_time,
        value_fn=_total_work,
    ),
    PelotonSensorEntityDescription(
        key="distance",
        translation_key="distance",
        unique_suffix="distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        unit_fn=_length_unit,
        value_fn=_distance,
    ),
    PelotonSensorEntityDescription(
        key="total_calories",
        translation_key="total_calories",
        unique_suffix="total_calories",
        native_unit_of_measurement=UnitOfEnergy.KILO_CALORIE,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        last_reset_fn=_start_time,
        value_fn=lambda data: _summary_value(data, "total_calories", "calories"),
    ),
    PelotonSensorEntityDescription(
        key="active_calories",
        translation_key="active_calories",
        unique_suffix="active_calories",
        native_unit_of_measurement=UnitOfEnergy.KILO_CALORIE,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        last_reset_fn=_start_time,
        value_fn=lambda data: _summary_value(data, "active_calories"),
    ),
    PelotonSensorEntityDescription(
        key="total_output",
        translation_key="total_output",
        unique_suffix="total_output",
        native_unit_of_measurement=UnitOfEnergy.KILO_JOULE,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        last_reset_fn=_start_time,
        value_fn=lambda data: _summary_value(data, "total_output"),
    ),
    # Heart rate reads unknown between workouts: 0 bpm is never a real value.
    *_metric_sensors("heart_rate", BEATS_PER_MINUTE, idle=None),
    *_metric_sensors("resistance", PERCENTAGE, idle=0),
    *_speed_sensors(),
    *_metric_sensors("cadence", REVOLUTIONS_PER_MINUTE, idle=0),
    *_metric_sensors(
        "output", UnitOfPower.WATT, idle=0, device_class=SensorDeviceClass.POWER
    ),
    PelotonSensorEntityDescription(
        key="total_workouts",
        translation_key="total_workouts",
        unique_suffix="total_workouts",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.user.total_workouts,
    ),
    *(_count_sensor(key, slug) for key, slug in WORKOUT_COUNTS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelotonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Peloton sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        PelotonSensor(coordinator, description) for description in SENSORS
    )


class PelotonSensor(PelotonEntity, SensorEntity):
    """A value from the latest workout or the profile."""

    entity_description: PelotonSensorEntityDescription

    def __init__(
        self,
        coordinator: PelotonCoordinator,
        description: PelotonSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.unique_suffix)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value from the latest coordinator data."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def last_reset(self) -> datetime | None:
        """Return when a per-workout total started (the workout start)."""
        if (last_reset_fn := self.entity_description.last_reset_fn) is not None:
            value = last_reset_fn(self.coordinator.data)
            return dt_util.as_utc(value) if value is not None else None
        return super().last_reset

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, from the account's settings where it depends on them."""
        if (unit_fn := self.entity_description.unit_fn) is not None:
            return unit_fn(self.coordinator.data)
        return super().native_unit_of_measurement
