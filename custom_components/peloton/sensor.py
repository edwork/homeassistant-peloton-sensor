"""Implementation of Home Assistant Sensor entity."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant import core
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_platform import DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

latest_stats: dict = {}
latest_workout: dict = {}


@dataclass
class PelotonStat:
    """Hold stats from latest workout endpoint."""

    name: str
    native_value: Any
    native_unit_of_measurement: str | None
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    icon: str | None


@dataclass
class PelotonMetric:
    """Hold stats from workout metrics endpoint."""

    max_val: int | float | None
    avg_val: int | float | None
    value: int | float | None
    unit: str | None  # Useful for mph vs kmph
    device_class: SensorDeviceClass | None


@dataclass
class PelotonSummary:
    """Hold summary stats from latest workout endpoint."""

    total: int | float | None
    unit: str  # Useful for mph vs kmph
    device_class: SensorDeviceClass | None


async def async_setup_entry(
    hass: core.HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,  # pylint: disable=unused-argument
    discovery_info: DiscoveryInfoType | None = None,  # pylint: disable=unused-argument
) -> None:
    """Set up entities using the binary sensor platform from this config entry."""

    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug("Creating Peloton binary sensors")

    async_add_entities(
        (
            PelotonStatSensor(coordinator=coordinator, stat_name=peloton_stat.name)
            for peloton_stat in coordinator.data.get("quant_data", [])
            if isinstance(peloton_stat, PelotonStat)
        ),
        True,
    )


class PelotonStatSensor(SensorEntity, CoordinatorEntity):  # type: ignore
    """Quantative data sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator, stat_name: str) -> None:
        """Initialize quant stat sensor."""
        super().__init__(coordinator)

        self.stat_name = stat_name
        self.coordinator = coordinator

        user_id = coordinator.data.get("workout_stats_summary", {}).get("user_id")

        self._attr_name = f"{coordinator.data.get('user_profile',{}).get('first_name')} on Peloton: {stat_name}"

        self._attr_unique_id = f"{user_id}_{stat_name.replace(' ','_').lower()}"

        self._attr_device_info: DeviceInfo | None = {"identifiers": {(DOMAIN, user_id)}}

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()

    @callback  # type: ignore
    def _handle_coordinator_update(self) -> None:
        """Update the entity when coordinator is updated."""

        peloton_stat: PelotonStat
        for peloton_stat in self.coordinator.data.get("quant_data", []):
            if peloton_stat.name == self.stat_name:
                self._attr_native_value = peloton_stat.native_value
                self._attr_native_unit_of_measurement = (
                    peloton_stat.native_unit_of_measurement
                )
                self._attr_device_class = peloton_stat.device_class
                self._attr_state_class = peloton_stat.state_class

                if peloton_stat.icon:
                    self._attr_icon = peloton_stat.icon

        self.async_write_ha_state()
