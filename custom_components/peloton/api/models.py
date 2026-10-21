"""Typed views of Peloton API responses.

Parsing is tolerant: a missing or wrongly typed field becomes None (or an
empty collection) instead of raising, because Peloton changes response
shapes without notice. Numbers accept int or float but never bool.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from typing import Any, Self

from .const import NO_CLASS_RIDE_ID

WORKOUT_COMPLETE = "COMPLETE"
WORKOUT_IN_PROGRESS = "IN_PROGRESS"


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    # json.loads accepts NaN and Infinity; they are not usable values.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


@dataclass(frozen=True, slots=True)
class PelotonUser:
    """The logged-in user (/api/me)."""

    id: str | None
    username: str | None
    first_name: str | None
    total_workouts: int | None
    # Workout count per fitness discipline slug, for example {"cycling": 30}.
    workout_counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: Any) -> Self:
        """Parse /api/me."""
        data = _map(data)
        counts: dict[str, int] = {}
        for entry in _list(data.get("workout_counts")):
            entry = _map(entry)
            slug = _str(entry.get("slug"))
            count = _int(entry.get("count"))
            if slug is not None and count is not None:
                counts[slug] = count
        return cls(
            id=_str(data.get("id")),
            username=_str(data.get("username")),
            first_name=_str(data.get("first_name")),
            total_workouts=_int(data.get("total_workouts")),
            workout_counts=counts,
        )


@dataclass(frozen=True, slots=True)
class UserSettings:
    """User settings (/api/user/{id}/settings)."""

    # "imperial" or "metric".
    distance_unit: str | None

    @classmethod
    def from_api(cls, data: Any) -> Self:
        """Parse /api/user/{id}/settings."""
        return cls(distance_unit=_str(_map(data).get("distance_unit")))


@dataclass(frozen=True, slots=True)
class Ride:
    """The class a workout followed."""

    id: str | None
    title: str | None
    description: str | None
    image_url: str | None
    # Class length in seconds.
    duration: int | None
    instructor_name: str | None

    @property
    def is_class(self) -> bool:
        """Return False for workouts without a class, such as Just Ride."""
        return self.id is not None and self.id != NO_CLASS_RIDE_ID

    @classmethod
    def from_api(cls, data: Any) -> Self:
        """Parse a ride object, with or without the ride.instructor join.

        Workouts without a class still carry an instructor object with a
        placeholder name ("JUST RIDE", "JUST RUN"); that is not an instructor.
        """
        data = _map(data)
        ride_id = _str(data.get("id"))
        instructor_name = (
            None
            if ride_id == NO_CLASS_RIDE_ID
            else _str(_map(data.get("instructor")).get("name"))
        )
        return cls(
            id=ride_id,
            title=_str(data.get("title")),
            description=_str(data.get("description")),
            image_url=_str(data.get("image_url")),
            duration=_int(data.get("duration")),
            instructor_name=instructor_name,
        )


@dataclass(frozen=True, slots=True)
class Workout:
    """A workout.

    Rows from the workout list leave out leaderboard_rank,
    total_leaderboard_users, total_work, ftp and is_paused; those are only
    set when the workout comes from /api/workout/{id}.
    """

    id: str | None
    user_id: str | None
    status: str | None
    fitness_discipline: str | None
    device_type: str | None
    # IANA name or "Etc/GMT+4" style; may be missing or unknown to zoneinfo.
    timezone: str | None
    # Unix timestamps in seconds.
    created_at: int | None
    start_time: int | None
    end_time: int | None
    is_paused: bool | None
    # Joules.
    total_work: float | None
    leaderboard_rank: int | None
    total_leaderboard_users: int | None
    ftp: int | None
    ride: Ride | None

    @property
    def is_in_progress(self) -> bool:
        """Return True while the workout is running (including paused)."""
        return self.status == WORKOUT_IN_PROGRESS

    @classmethod
    def from_api(cls, data: Any) -> Self:
        """Parse a workout from the workout list or /api/workout/{id}."""
        data = _map(data)
        is_paused = data.get("is_paused")
        total_work = _number(data.get("total_work"))
        ride = data.get("ride")
        return cls(
            id=_str(data.get("id")),
            user_id=_str(data.get("user_id")),
            status=_str(data.get("status")),
            fitness_discipline=_str(data.get("fitness_discipline")),
            device_type=_str(data.get("device_type")),
            timezone=_str(data.get("timezone")),
            created_at=_int(data.get("created_at")),
            start_time=_int(data.get("start_time")),
            end_time=_int(data.get("end_time")),
            is_paused=is_paused if isinstance(is_paused, bool) else None,
            total_work=float(total_work) if total_work is not None else None,
            leaderboard_rank=_int(data.get("leaderboard_rank")),
            # Workouts without a leaderboard (Just Ride) report 0 users and an
            # FTP of 0 when none is set; both mean "none".
            total_leaderboard_users=_int(data.get("total_leaderboard_users")) or None,
            ftp=_int(_map(data.get("ftp_info")).get("ftp")) or None,
            ride=Ride.from_api(ride) if isinstance(ride, Mapping) else None,
        )


@dataclass(frozen=True, slots=True)
class Summary:
    """A workout total, such as calories or distance."""

    slug: str
    value: int | float | None
    display_unit: str | None


@dataclass(frozen=True, slots=True)
class Metric:
    """A sampled metric, such as cadence or heart rate.

    For pace metrics (minutes per distance) Peloton's ``max_value`` is the
    fastest pace, which is the smallest number.
    """

    slug: str
    display_unit: str | None
    average: int | float | None
    maximum: int | float | None
    values: tuple[int | float | None, ...] = ()

    @property
    def last(self) -> int | float | None:
        """Return the most recent sample, or None when there are none."""
        return self.values[-1] if self.values else None


def _metric(entry: Mapping[str, Any]) -> Metric | None:
    if (slug := _str(entry.get("slug"))) is None:
        return None
    return Metric(
        slug=slug,
        display_unit=_str(entry.get("display_unit")),
        average=_number(entry.get("average_value")),
        maximum=_number(entry.get("max_value")),
        values=tuple(_number(v) for v in _list(entry.get("values"))),
    )


def _summaries(raw: Any) -> dict[str, Summary]:
    summaries: dict[str, Summary] = {}
    for entry in _list(raw):
        entry = _map(entry)
        if (slug := _str(entry.get("slug"))) is not None:
            summaries[slug] = Summary(
                slug=slug,
                value=_number(entry.get("value")),
                display_unit=_str(entry.get("display_unit")),
            )
    return summaries


@dataclass(frozen=True, slots=True)
class PerformanceGraph:
    """Totals and sampled metrics for one workout.

    ``average_summaries`` holds the averages Peloton shows in its apps
    (avg_output, avg_cadence, avg_speed, ...). They can differ from a metric's
    ``average``: bike speed averages differ because Peloton's displayed value
    is distance over the whole workout.
    """

    duration: int | None
    summaries: dict[str, Summary] = field(default_factory=dict)
    average_summaries: dict[str, Summary] = field(default_factory=dict)
    metrics: dict[str, Metric] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: Any) -> Self:
        """Parse /api/workout/{id}/performance_graph."""
        data = _map(data)
        metrics: dict[str, Metric] = {}
        alternatives: list[Any] = []
        for entry in _list(data.get("metrics")):
            entry = _map(entry)
            if (metric := _metric(entry)) is not None:
                metrics[metric.slug] = metric
            # Tread workouts carry speed only as an alternative to pace.
            alternatives.extend(_list(entry.get("alternatives")))
        for entry in alternatives:
            metric = _metric(_map(entry))
            if metric is not None and metric.slug not in metrics:
                metrics[metric.slug] = metric
        return cls(
            duration=_int(data.get("duration")),
            summaries=_summaries(data.get("summaries")),
            average_summaries=_summaries(data.get("average_summaries")),
            metrics=metrics,
        )
