"""Data update coordinator for Peloton."""

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PelotonAuthError,
    PelotonClient,
    PelotonError,
    PelotonRateLimitError,
    PelotonUser,
    PerformanceGraph,
    UserSettings,
    Workout,
)
from .const import (
    CONF_ACTIVE_INTERVAL,
    CONF_IDLE_INTERVAL,
    CONF_MAX_WORKOUT_MINUTES,
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_MAX_WORKOUT_MINUTES,
    DOMAIN,
    MAX_RETRY_AFTER,
    PERFORMANCE_GRAPH_EVERY_N,
    PROFILE_REFRESH_INTERVAL,
    RATE_LIMIT_BACKOFF,
    RATE_LIMIT_MAX_BACKOFF,
    TOLERATED_FAILED_POLLS,
    WORKOUT_GRACE,
)

_LOGGER = logging.getLogger(__name__)

type PelotonConfigEntry = ConfigEntry[PelotonCoordinator]


@dataclass(frozen=True, slots=True)
class PelotonData:
    """Everything the entities show."""

    user: PelotonUser
    settings: UserSettings
    # Latest workout with all fields, or None when the account has none.
    workout: Workout | None
    performance_graph: PerformanceGraph | None
    # Time zone of the latest workout (UTC if missing or unknown).
    timezone: tzinfo
    # True while the latest workout is in progress and not abandoned.
    active: bool


def workout_active(workout: Workout | None, now: datetime, max_minutes: float) -> bool:
    """Return True if the workout is in progress and not abandoned.

    A class workout counts as abandoned once its class length plus
    WORKOUT_GRACE has passed since it started. Workouts without a class length
    (Just Ride, free runs) count as abandoned after ``max_minutes``.
    """
    if workout is None or not workout.is_in_progress:
        return False
    # Fall back to the creation time; without either there is nothing to
    # measure against.
    start = workout.start_time if workout.start_time is not None else workout.created_at
    if start is None:
        return True
    ride = workout.ride
    if ride is not None and ride.is_class and ride.duration:
        limit = timedelta(seconds=ride.duration) + WORKOUT_GRACE
    else:
        limit = timedelta(minutes=max_minutes)
    return now.timestamp() < start + limit.total_seconds()


async def async_resolve_timezone(name: str | None) -> tzinfo:
    """Return the workout's time zone, or UTC if it is missing or unknown."""
    if name:
        try:
            zone = await dt_util.async_get_time_zone(name)
        except ValueError, OSError:
            # zoneinfo rejects keys that are not normalized relative paths, and
            # the file system rejects overlong ones.
            zone = None
        if zone is not None:
            return zone
    return dt_util.UTC


class PelotonCoordinator(DataUpdateCoordinator[PelotonData]):
    """Poll Peloton for the latest workout.

    Between workouts each poll is one request (the latest workout from the
    workout list), every ``idle_interval`` seconds. While a workout is in
    progress, its details and performance graph are fetched every
    ``active_interval`` seconds. Details are also fetched once when the latest
    workout changes and hourly. The profile and settings are refreshed hourly
    and when the latest workout changes.
    """

    config_entry: PelotonConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: PelotonConfigEntry, client: PelotonClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL)
            ),
        )
        self.client = client
        # Failed polls in a row; entities stay available for a few of them.
        self.failed_polls = 0
        # Rate-limited polls in a row, for the backoff without Retry-After.
        self._rate_limited_polls = 0
        self._user: PelotonUser | None = None
        self._settings: UserSettings | None = None
        self._profile_fetched_at = dt_util.utcnow()
        # (id, status) of the latest workout list row at the last successful poll.
        self._last_row: tuple[str, str | None] | None = None

    @property
    def user_id(self) -> str | None:
        """Return the Peloton user id of this account."""
        return self.client.user_id

    @property
    def _max_workout_minutes(self) -> float:
        return self.config_entry.options.get(
            CONF_MAX_WORKOUT_MINUTES, DEFAULT_MAX_WORKOUT_MINUTES
        )

    async def _async_setup(self) -> None:
        """Fetch the profile and settings once before the first update."""
        try:
            await self._async_refresh_profile()
        except PelotonError as err:
            raise self._translate(err) from err

    async def _async_refresh_profile(self) -> None:
        self._user = await self.client.async_get_me()
        self._settings = await self.client.async_get_settings()
        self._profile_fetched_at = dt_util.utcnow()

    async def _async_update_data(self) -> PelotonData:
        """Fetch the latest workout and pick the next polling interval."""
        try:
            data = await self._async_fetch()
        except Exception as err:
            delay = self._retry_delay(err)
            self._count_failure(err, delay)
            if isinstance(err, PelotonError):
                raise self._translate(err, delay) from err
            # Unexpected errors keep their traceback in Home Assistant's log.
            raise
        self.failed_polls = 0
        self._rate_limited_polls = 0
        options = self.config_entry.options
        seconds = (
            options.get(CONF_ACTIVE_INTERVAL, DEFAULT_ACTIVE_INTERVAL)
            if data.active
            else options.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL)
        )
        self.update_interval = timedelta(seconds=seconds)
        return data

    def _count_failure(self, err: Exception, delay: float | None) -> None:
        """Count a failed poll; entities stay available for a few of them.

        After an auth error polling stops, and after a long rate-limit wait the
        next poll is far away, so in both cases entities go unavailable at once
        instead of showing old data (such as a workout that has ended).
        """
        interval = self.update_interval.total_seconds() if self.update_interval else 0
        if isinstance(err, PelotonAuthError) or (
            delay is not None and delay > interval * TOLERATED_FAILED_POLLS
        ):
            self.failed_polls = max(self.failed_polls + 1, TOLERATED_FAILED_POLLS + 1)
        else:
            self.failed_polls += 1
        if self.failed_polls == TOLERATED_FAILED_POLLS + 1:
            # Home Assistant does not notify entities about a failure that
            # follows another failure, so tell them their data is now too old
            # to show.
            self.async_update_listeners()

    def _retry_delay(self, err: Exception) -> float | None:
        """Return how long to wait before the next poll after a rate limit.

        Peloton's Retry-After is used when present, never shorter than the
        normal interval and never longer than MAX_RETRY_AFTER. Without one, the
        wait starts at RATE_LIMIT_BACKOFF and doubles with each rate-limited
        poll in a row. Call once per failed poll.
        """
        if not isinstance(err, PelotonRateLimitError):
            return None
        self._rate_limited_polls += 1
        if err.retry_after is None:
            return min(
                RATE_LIMIT_BACKOFF * 2 ** (self._rate_limited_polls - 1),
                RATE_LIMIT_MAX_BACKOFF,
            )
        interval = self.update_interval.total_seconds() if self.update_interval else 0
        return min(max(err.retry_after, interval), MAX_RETRY_AFTER)

    def _translate(self, err: PelotonError, delay: float | None = None) -> Exception:
        """Map a client error to the exception Home Assistant expects."""
        if isinstance(err, PelotonAuthError):
            return ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            )
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"error": str(err)},
            retry_after=delay,
        )

    async def _async_fetch(self) -> PelotonData:
        previous = self.data
        now = dt_util.utcnow()
        latest = await self.client.async_get_latest_workout()
        profile_stale = now - self._profile_fetched_at >= PROFILE_REFRESH_INTERVAL

        workout = previous.workout if previous else None
        graph = previous.performance_graph if previous else None
        # Compare with the list row of the previous successful poll, not with
        # the cached detail: the two are separate reads and can disagree, for
        # example when a workout ends between them.
        row = (
            (latest.id, latest.status)
            if latest is not None and latest.id is not None
            else None
        )
        changed = row != self._last_row
        if latest is None or latest.id is None:
            workout, graph = None, None
        elif (
            changed
            or graph is None
            or profile_stale
            or workout_active(latest, now, self._max_workout_minutes)
        ):
            workout = await self.client.async_get_workout(latest.id)
            graph = await self.client.async_get_performance_graph(
                latest.id, every_n=PERFORMANCE_GRAPH_EVERY_N
            )

        # Workout counts change when a workout starts or ends.
        if (
            self._user is None
            or self._settings is None
            or profile_stale
            or (changed and previous is not None)
        ):
            await self._async_refresh_profile()
        user, settings = self._user, self._settings
        if user is None or settings is None:  # pragma: no cover - set just above
            raise PelotonError("Profile not loaded")

        self._last_row = row
        return PelotonData(
            user=user,
            settings=settings,
            workout=workout,
            performance_graph=graph,
            timezone=await async_resolve_timezone(
                workout.timezone if workout else None
            ),
            active=workout_active(workout, now, self._max_workout_minutes),
        )
