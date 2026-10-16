"""Binary sensor showing whether a Peloton workout is in progress."""

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PelotonConfigEntry, PelotonCoordinator
from .entity import PelotonEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelotonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the workout binary sensor."""
    async_add_entities([PelotonWorkoutBinarySensor(entry.runtime_data)])


class PelotonWorkoutBinarySensor(PelotonEntity, BinarySensorEntity):
    """On while a workout is in progress (and not abandoned)."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "workout"

    def __init__(self, coordinator: PelotonCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "workout")

    @property
    def is_on(self) -> bool:
        """Return True while the latest workout is in progress."""
        return self.coordinator.data.active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Describe the latest workout."""
        workout = self.coordinator.data.workout
        ride = workout.ride if workout else None
        return {
            "workout_type": workout.fitness_discipline if workout else None,
            "device_type": workout.device_type if workout else None,
            "ride_title": ride.title if ride else None,
            "ride_description": ride.description if ride else None,
            "workout_image": ride.image_url if ride else None,
            "ftp": workout.ftp if workout else None,
            "instructor": ride.instructor_name if ride else None,
            "paused": bool(workout and workout.is_paused),
        }
