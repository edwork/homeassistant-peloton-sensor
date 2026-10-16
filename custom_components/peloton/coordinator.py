"""Data update coordinator for Peloton."""

from dataclasses import dataclass, field
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
    PelotonUser,
    PerformanceGraph,
    UserSettings,
    Workout,
)
from .const import (
    DOMAIN,
    PERFORMANCE_GRAPH_EVERY_N,
    PROFILE_REFRESH_INTERVAL,
    SCAN_INTERVAL,
)
from .stats import PelotonStat, async_build_stats

_LOGGER = logging.getLogger(__name__)

type PelotonConfigEntry = ConfigEntry[PelotonCoordinator]


@dataclass
class PelotonData:
    """Everything the entities show."""

    user: PelotonUser
    settings: UserSettings
    # Latest workout with all fields, or None when the account has none.
    workout: Workout | None
    performance_graph: PerformanceGraph | None
    stats: list[PelotonStat] = field(default_factory=list)


class PelotonCoordinator(DataUpdateCoordinator[PelotonData]):
    """Poll Peloton for the latest workout.

    Each poll lists the latest workout (one request). The workout's details
    and performance graph are fetched again only while it is in progress, when
    a different workout appears, or when its status changes; otherwise the
    previous ones are reused. The profile and settings are refreshed hourly
    and whenever the latest workout changes.
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
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._user: PelotonUser | None = None
        self._settings: UserSettings | None = None
        self._profile_fetched_at = dt_util.utcnow()
        # (id, status) of the latest workout list row at the last successful poll.
        self._last_row: tuple[str, str | None] | None = None

    @property
    def user_id(self) -> str | None:
        """Return the Peloton user id of this account."""
        return self.client.user_id

    async def _async_setup(self) -> None:
        """Fetch the profile and settings once before the first update."""
        try:
            await self._async_refresh_profile()
        except PelotonAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except PelotonError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_refresh_profile(self) -> None:
        self._user = await self.client.async_get_me()
        self._settings = await self.client.async_get_settings()
        self._profile_fetched_at = dt_util.utcnow()

    async def _async_update_data(self) -> PelotonData:
        """Fetch the latest workout, reusing unchanged details."""
        try:
            return await self._async_fetch()
        except PelotonAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except PelotonError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_fetch(self) -> PelotonData:
        previous = self.data
        latest = await self.client.async_get_latest_workout()
        profile_stale = (
            dt_util.utcnow() - self._profile_fetched_at >= PROFILE_REFRESH_INTERVAL
        )

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
        elif changed or latest.is_in_progress or graph is None or profile_stale:
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
            stats=await async_build_stats(user, settings, workout, graph),
        )
