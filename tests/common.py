"""Helpers shared by the integration tests."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.peloton.const import DEFAULT_IDLE_INTERVAL, DOMAIN

from .peloton_api import USER_ID


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and set it up."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def advance(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    delta: timedelta = timedelta(seconds=DEFAULT_IDLE_INTERVAL),
) -> None:
    """Move time forward (one idle interval by default) and let polls run."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def state_of(hass: HomeAssistant, suffix: str) -> State:
    """Return the state of the entity with unique_id f"{USER_ID}_{suffix}".

    Looks the entity up by unique_id so the tests do not depend on the
    entity_id a fresh install happens to get (see test_fresh_install_entity_ids).
    """
    domain = "binary_sensor" if suffix == "workout" else "sensor"
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{USER_ID}_{suffix}"
    )
    assert entity_id is not None, suffix
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state
