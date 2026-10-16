"""Diagnostics for Peloton."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import PelotonConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    "access_token",
    "refresh_token",
    "id_token",
    "id",
    "user_id",
    "first_name",
    "image_url",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PelotonConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, without tokens or personal data."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "failed_polls": coordinator.failed_polls,
        },
        "data": async_redact_data(
            {
                "user": asdict(data.user),
                "settings": asdict(data.settings),
                "workout": asdict(data.workout) if data.workout else None,
                "performance_graph": (
                    asdict(data.performance_graph) if data.performance_graph else None
                ),
                "timezone": str(data.timezone),
                "active": data.active,
            },
            TO_REDACT,
        ),
    }
