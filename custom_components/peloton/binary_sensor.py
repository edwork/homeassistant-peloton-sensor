"""Binary sensor showing whether a Peloton workout is in progress."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PelotonConfigEntry, PelotonCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelotonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the workout binary sensor."""
    async_add_entities([PelotonLastWorkout(entry.runtime_data)], True)


class PelotonLastWorkout(CoordinatorEntity[PelotonCoordinator], BinarySensorEntity):
    """On while the latest workout is in progress."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: PelotonCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        user_id = coordinator.user_id
        first_name = coordinator.data.user.first_name
        self._attr_name = f"{first_name} on Peloton: Workout"
        self._attr_unique_id = f"{user_id}_workout"
        self._attr_extra_state_attributes = {}
        self._attr_device_info = {
            "identifiers": {(DOMAIN, user_id)},
            "name": f"{first_name} on Peloton",
            "manufacturer": "Peloton",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the state from the latest workout."""
        workout = self.coordinator.data.workout
        self._attr_is_on = workout is not None and workout.is_in_progress
        self._attr_icon = "mdi:bike-fast" if self._attr_is_on else "mdi:bike"
        ride = workout.ride if workout else None
        self._attr_extra_state_attributes = {
            "Workout Type": workout.fitness_discipline if workout else None,
            "Device Type": workout.device_type if workout else None,
            "Ride Title": ride.title if ride else None,
            "Ride Description": ride.description if ride else None,
            "Workout Image": ride.image_url if ride else None,
            "FTP": workout.ftp if workout else None,
            "Instructor": ride.instructor_name if ride else None,
            "Paused": bool(workout and workout.is_paused),
        }
        self.async_write_ha_state()
