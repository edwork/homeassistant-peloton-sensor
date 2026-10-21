"""Base entity for Peloton."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_NAME, TOLERATED_FAILED_POLLS
from .coordinator import PelotonCoordinator


class PelotonEntity(CoordinatorEntity[PelotonCoordinator]):
    """An entity of one Peloton account (one device per account)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PelotonCoordinator, unique_suffix: str) -> None:
        """Initialize the entity.

        ``unique_suffix`` keeps the unique_ids of earlier versions, which were
        built from the old display names (for example "heart_rate:_average").
        """
        super().__init__(coordinator)
        user_id = coordinator.user_id
        user = coordinator.data.user
        owner = user.first_name or user.username
        self._attr_unique_id = f"{user_id}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(user_id))},
            name=f"{owner} on Peloton" if owner else INTEGRATION_NAME,
            manufacturer="Peloton",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://members.onepeloton.com",
        )

    @property
    def available(self) -> bool:
        """Stay available through a few failed polls.

        A short outage then does not turn the workout sensor (and anything
        automated on it) unavailable.
        """
        return super().available or (
            self.coordinator.data is not None
            and self.coordinator.failed_polls <= TOLERATED_FAILED_POLLS
        )
