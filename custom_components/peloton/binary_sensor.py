"""Binary sensor API entity."""
from __future__ import annotations

import logging

from homeassistant import core
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_platform import DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,  # pylint: disable=unused-argument
    discovery_info: DiscoveryInfoType | None = None,  # pylint: disable=unused-argument
) -> None:
    """Set up entities using the binary sensor platform from this config entry."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create a single instance of PelotonLastWorkout.
    async_add_entities(
        ([PelotonLastWorkout(coordinator)]),
        True,
    )


class PelotonLastWorkout(BinarySensorEntity, CoordinatorEntity):  # type: ignore
    """Sensor showing exceptions over next few days."""

    _attr_is_on: bool | None
    _attr_device_class: BinarySensorDeviceClass | str | None = (
        BinarySensorDeviceClass.RUNNING
    )

    def __init__(self, coordinator: DataUpdateCoordinator) -> None:
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator=coordinator)

        self.coordinator = coordinator

        profile: dict = coordinator.data["user_profile"]
        workout_summary: dict = coordinator.data["workout_stats_summary"]

        self._attr_name = f"{profile.get('first_name')} on Peloton: Workout"

        self._attr_unique_id = f"{workout_summary.get('user_id')}_workout"

        if not self.extra_state_attributes:
            self._attr_extra_state_attributes: dict = {}

        self._attr_device_info = {
            "identifiers": {(DOMAIN, workout_summary.get("user_id"))},
            "name": f"{profile.get('first_name')} on Peloton",
            "manufacturer": "Peloton",
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()

    @callback  # type: ignore
    def _handle_coordinator_update(self) -> None:
        """Update the entity when coordinator is updated."""

        latest_workout: dict = self.coordinator.data["workout_stats_summary"]

        if (status := latest_workout.get("status")) == "COMPLETE":
            self._attr_is_on = False
        elif status == "IN_PROGRESS":
            self._attr_is_on = True
        else:
            self._attr_is_on = None

        self._attr_icon = "mdi:bike-fast" if self._attr_is_on else "mdi:bike"

        self._attr_extra_state_attributes.update(
            {
                "Workout Type": latest_workout.get("fitness_discipline"),
                "Device Type": latest_workout.get("device_type"),
                "Ride Title": latest_workout.get("ride", {}).get("title"),
                "Ride Description": latest_workout.get("ride", {}).get("description"),
                "Workout Image": latest_workout.get("ride", {}).get("image_url"),
                "FTP": latest_workout.get("ftp_info", {}).get("ftp"),
                "Instructor": latest_workout.get("instructor_name"),
                "Paused": bool(latest_workout.get("is_paused")),
            }
        )

        self.async_write_ha_state()
