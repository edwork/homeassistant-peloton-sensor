"""The Peloton integration."""

import logging

from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    PelotonAuthError,
    PelotonClient,
    PelotonError,
    PelotonRateLimitError,
    PelotonTokens,
    async_login_and_identify,
    async_revoke,
)
from .const import DOMAIN
from .coordinator import PelotonConfigEntry, PelotonCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: PelotonConfigEntry) -> bool:
    """Set up Peloton from a config entry."""
    session = async_get_clientsession(hass)
    if CONF_TOKEN in entry.data:
        tokens = _stored_tokens(entry)
    else:
        tokens = await _async_migrate_password_entry(hass, entry)

    @callback
    def _async_save_tokens(new_tokens: PelotonTokens) -> None:
        """Store refreshed tokens so a restart does not need a login."""
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: new_tokens.as_dict()}
        )

    client = PelotonClient(session, tokens, _async_save_tokens)
    coordinator = PelotonCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PelotonConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PelotonConfigEntry) -> None:
    """Revoke the refresh token when the entry is deleted (best effort)."""
    refresh_token = (entry.data.get(CONF_TOKEN) or {}).get("refresh_token")
    if not refresh_token:
        return
    try:
        await async_revoke(async_get_clientsession(hass), refresh_token)
    except PelotonError as err:
        _LOGGER.debug("Could not revoke the refresh token: %s", err)


async def async_migrate_entry(hass: HomeAssistant, entry: PelotonConfigEntry) -> bool:
    """Migrate old config entries. No network calls happen here.

    Version 3 stores tokens instead of the password. Version 2 entries keep
    their password until the next setup logs in once and replaces it with
    tokens (see _async_migrate_password_entry).
    """
    if entry.version > 3:  # pragma: no cover - Home Assistant 2026.4+ checks first
        # Downgraded from a newer version of the integration. Home Assistant
        # 2026.3 still calls this for such entries; later releases refuse them.
        return False
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry, unique_id=entry.data[CONF_USERNAME], version=2
        )
    if entry.version == 2:
        _LOGGER.debug("Migrating Peloton config entry to version 3")
        hass.config_entries.async_update_entry(entry, version=3)
    return True


def _stored_tokens(entry: PelotonConfigEntry) -> PelotonTokens:
    """Return the stored tokens, or start reauth if they are unusable."""
    try:
        return PelotonTokens.from_dict(entry.data[CONF_TOKEN])
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err


async def _async_migrate_password_entry(
    hass: HomeAssistant, entry: PelotonConfigEntry
) -> PelotonTokens:
    """Replace the stored password of an old entry with tokens.

    This is the only password login outside the config flow, and it happens
    once per entry. After a network or rate-limit error the password is kept
    and setup is retried later. A rejected password is deleted at once, so it
    is never sent again; reauth then asks for the current one.
    """
    password = entry.data.get(CONF_PASSWORD)
    username = entry.data.get(CONF_USERNAME)
    if not password or not username:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        )
    try:
        tokens = await async_login_and_identify(
            async_get_clientsession(hass), username, password
        )
    except PelotonAuthError as err:
        hass.config_entries.async_update_entry(entry, data={CONF_USERNAME: username})
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    except PelotonRateLimitError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="rate_limited"
        ) from err
    except PelotonError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    unique_id = entry.unique_id
    if not any(
        other.unique_id == tokens.user_id
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ):
        unique_id = tokens.user_id
    hass.config_entries.async_update_entry(
        entry,
        data={CONF_USERNAME: username, CONF_TOKEN: tokens.as_dict()},
        unique_id=unique_id,
    )
    _LOGGER.debug("Replaced the stored password with tokens")
    return tokens
