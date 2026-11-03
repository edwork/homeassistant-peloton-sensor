"""One-time fixes for data recorded by earlier versions."""

from collections.abc import Iterable
from datetime import datetime
from functools import partial
import logging

from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api import Workout
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_fix_total_output_statistics(hass: HomeAssistant, user_id: str) -> None:
    """Relabel Total output statistics recorded as "kj" to "kJ".

    Earlier versions passed Peloton's lowercase "kj" through as the unit.
    Home Assistant does not recognise it as an energy unit, so after the
    switch to "kJ" it would stop compiling long-term statistics for the
    sensor and raise repairs. Both are the same unit, so only the label in
    the statistics metadata changes; no values do.
    """
    if "recorder" not in hass.config.components:
        return
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{user_id}_total_output"
    )
    if entity_id is None:
        return

    # Imported here: the recorder is optional (after_dependencies).
    from homeassistant.components.recorder import get_instance  # noqa: PLC0415
    from homeassistant.components.recorder.statistics import get_metadata  # noqa: PLC0415

    instance = get_instance(hass)
    try:
        metadata = await instance.async_add_executor_job(
            partial(get_metadata, hass, statistic_ids={entity_id})
        )
    except Exception:
        _LOGGER.debug("Could not read statistics metadata", exc_info=True)
        return
    if (meta := metadata.get(entity_id)) is None:
        return
    if meta[1].get("unit_of_measurement") != "kj":
        return
    _LOGGER.debug("Relabelling %s statistics from kj to kJ", entity_id)
    instance.async_update_statistics_metadata(
        entity_id,
        new_unit_class="energy",
        new_unit_of_measurement=UnitOfEnergy.KILO_JOULE,
    )


async def async_get_recorded_last_resets(
    hass: HomeAssistant,
    user_id: str,
    workout: Workout | None,
    unique_suffixes: Iterable[str],
) -> dict[str, tuple[str, datetime]]:
    """Return the last_reset the statistics use for the latest workout's totals.

    Version 1.0.0 reported the workout's start_time as the last_reset of the
    per-workout totals. Peloton moves start_time when a workout completes,
    which started a second statistics cycle and counted the workout twice.
    The totals now use created_at, which stays fixed. Switching would change
    last_reset once more for the latest workout and count it again, so where
    the recorder already holds a last_reset of that workout (between its
    created_at and start_time), the sensor keeps it until the next workout.

    The next statistics compile starts from the last compiled short-term
    row, then walks the states recorded since, so the last recorded state
    wins over the row. Returns {unique_suffix: (workout id, last_reset)}.
    """
    if (
        "recorder" not in hass.config.components
        or workout is None
        or workout.id is None
    ):
        return {}
    times = [value for value in (workout.created_at, workout.start_time) if value]
    registry = er.async_get(hass)
    entity_ids = {
        entity_id: suffix
        for suffix in unique_suffixes
        if (
            entity_id := registry.async_get_entity_id(
                "sensor", DOMAIN, f"{user_id}_{suffix}"
            )
        )
        is not None
    }
    if not times or not entity_ids:
        return {}
    earliest, latest = min(times), max(times)

    # Imported here: the recorder is optional (after_dependencies).
    from homeassistant.components.recorder import get_instance  # noqa: PLC0415
    from homeassistant.components.recorder.history import get_significant_states  # noqa: PLC0415
    from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
        get_last_short_term_statistics,
    )

    def recorded(entity_id: str) -> float | None:
        rows = get_last_short_term_statistics(
            hass, 1, entity_id, False, {"last_reset"}
        ).get(entity_id)
        if not rows:
            return None
        last_reset = rows[0].get("last_reset")
        # All states, not only significant ones: the completion can change
        # only the last_reset attribute.
        states = get_significant_states(
            hass,
            dt_util.utc_from_timestamp(rows[0]["end"]),
            None,
            [entity_id],
            significant_changes_only=False,
        ).get(entity_id, [])
        for state in reversed(states):
            # The compile skips states that are not numbers.
            try:
                float(state.state)
            except TypeError, ValueError:
                continue
            value = state.attributes.get("last_reset")
            if isinstance(value, str) and (parsed := dt_util.parse_datetime(value)):
                last_reset = parsed.timestamp()
            break
        return last_reset

    def read() -> dict[str, float]:
        return {
            entity_id: last_reset
            for entity_id in entity_ids
            if (last_reset := recorded(entity_id)) is not None
        }

    try:
        found = await get_instance(hass).async_add_executor_job(read)
    except Exception:
        _LOGGER.debug("Could not read recorded statistics", exc_info=True)
        return {}
    return {
        entity_ids[entity_id]: (workout.id, dt_util.utc_from_timestamp(last_reset))
        for entity_id, last_reset in found.items()
        if earliest <= last_reset <= latest
    }
