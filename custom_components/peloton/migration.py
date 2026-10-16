"""One-time fixes for data recorded by earlier versions."""

from functools import partial
import logging

from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

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
