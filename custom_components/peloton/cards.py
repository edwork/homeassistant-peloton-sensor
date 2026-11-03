"""Serve the workout card and load it on every frontend page."""

import hashlib
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARDS_FILE = Path(__file__).parent / "dist" / "peloton-cards.js"
CARDS_URL = "/peloton_static/peloton-cards.js"
# The served URL with its content hash, or None when the card is not served.
DATA_CARDS: HassKey[str | None] = HassKey(f"{DOMAIN}_cards")


def _file_digest(path: Path) -> str | None:
    """Return a short content hash of the file, or None if it does not exist."""
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return None
    return hashlib.sha256(content).hexdigest()[:16]


async def async_register_cards(hass: HomeAssistant) -> None:
    """Serve the card file and add it to every frontend page.

    Runs once per Home Assistant run, because static paths cannot be added
    twice or removed. Never raises: without the card, the integration still
    works.
    """
    if DATA_CARDS in hass.data:
        return
    hass.data[DATA_CARDS] = None
    if hass.http is None:
        return
    try:
        digest = await hass.async_add_executor_job(_file_digest, CARDS_FILE)
        if digest is None:
            _LOGGER.warning(
                "Peloton card file %s is missing; the workout card is not available",
                CARDS_FILE,
            )
            return
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARDS_URL, str(CARDS_FILE), cache_headers=True)]
        )
        # The hash changes the URL whenever the file changes, so browsers do
        # not keep an old card for the 31 days of the cache headers.
        url = f"{CARDS_URL}?v={digest}"
        if "frontend" in hass.config.components:
            add_extra_js_url(hass, url)
        hass.data[DATA_CARDS] = url
    except (OSError, RuntimeError) as err:
        _LOGGER.warning("Could not register the Peloton workout card: %s", err)
