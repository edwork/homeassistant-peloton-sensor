"""Sensors for the latest Peloton workout and workout counts."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PelotonConfigEntry, PelotonCoordinator
from .stats import PelotonStat


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelotonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one sensor per stat."""
    coordinator = entry.runtime_data
    async_add_entities(
        (PelotonStatSensor(coordinator, stat) for stat in coordinator.data.stats),
        True,
    )


class PelotonStatSensor(CoordinatorEntity[PelotonCoordinator], SensorEntity):
    """One value from the latest workout or the profile."""

    def __init__(self, coordinator: PelotonCoordinator, stat: PelotonStat) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        user_id = coordinator.user_id
        first_name = coordinator.data.user.first_name
        self.stat_name = stat.name
        self._attr_name = f"{first_name} on Peloton: {stat.name}"
        self._attr_unique_id = f"{user_id}_{stat.name.replace(' ', '_').lower()}"
        self._attr_device_info = {"identifiers": {(DOMAIN, user_id)}}
        self._attr_entity_category = stat.entity_category
        self._attr_entity_registry_enabled_default = (
            stat.entity_registry_enabled_default
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the state from the matching stat."""
        for stat in self.coordinator.data.stats:
            if stat.name == self.stat_name:
                self._attr_native_value = stat.native_value
                self._attr_native_unit_of_measurement = stat.native_unit_of_measurement
                self._attr_device_class = stat.device_class
                self._attr_state_class = stat.state_class
                if stat.icon:
                    self._attr_icon = stat.icon
        self.async_write_ha_state()
