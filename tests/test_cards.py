"""Tests for serving the workout card."""

from collections.abc import Generator
import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import patch

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.peloton import cards
from custom_components.peloton.const import DOMAIN

from .common import setup_integration
from .conftest import USER_ID, USERNAME

CARD_SOURCE = b'customElements.define("peloton-test", class extends HTMLElement {});\n'


@pytest.fixture
def cards_file(tmp_path: Path) -> Generator[Path]:
    """Serve a stand-in card file instead of the build output."""
    path = tmp_path / "peloton-cards.js"
    path.write_bytes(CARD_SOURCE)
    with patch.object(cards, "CARDS_FILE", path):
        yield path


@pytest.fixture
def frontend_events(hass: HomeAssistant) -> list[tuple[str, str]]:
    """Stand in for the frontend integration and record extra module changes.

    The test requirements do not include home-assistant-frontend, so the
    frontend integration cannot be set up. This is the state it leaves behind
    on 2026.3 and 2026.10 alike: a UrlManager under DATA_EXTRA_MODULE_URL.
    """
    events: list[tuple[str, str]] = []
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(
        lambda change, url: events.append((change, url)), []
    )
    hass.config.components.add("frontend")
    return events


def _card_url() -> str:
    digest = hashlib.sha256(CARD_SOURCE).hexdigest()[:16]
    return f"{cards.CARDS_URL}?v={digest}"


@pytest.mark.usefixtures("mock_api", "cards_file")
async def test_card_served_and_loaded(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    hass_client_no_auth: ClientSessionGenerator,
    frontend_events: list[tuple[str, str]],
) -> None:
    """The card is served without auth, cached, and loaded on every page."""
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    url = _card_url()
    assert hass.data[cards.DATA_CARDS] == url
    assert hass.data[DATA_EXTRA_MODULE_URL].urls == frozenset({url})
    assert frontend_events == [("added", url)]

    # Set up diagnostics before the first test client: once a client has
    # started the app, its router may be frozen and diagnostics cannot add
    # its view.
    assert await async_setup_component(hass, "diagnostics", {})
    client = await hass_client_no_auth()
    response = await client.get(url)
    assert response.status == 200
    assert response.content_type == "text/javascript"
    assert response.headers["Cache-Control"] == "public, max-age=2678400"
    assert await response.read() == CARD_SOURCE

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )
    assert diagnostics["cards"] == url


@pytest.mark.usefixtures("mock_api", "cards_file")
async def test_card_registered_once(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    frontend_events: list[tuple[str, str]],
) -> None:
    """A second call, a reload and the removal of the entry change nothing."""
    await setup_integration(hass, mock_config_entry)
    url = _card_url()

    await cards.async_register_cards(hass)
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert frontend_events == [("added", url)]

    assert await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DATA_EXTRA_MODULE_URL].urls == frozenset({url})
    client = await hass_client_no_auth()
    assert (await client.get(url)).status == 200


@pytest.mark.usefixtures("cards_file")
async def test_card_registered_when_entry_setup_fails(
    hass: HomeAssistant, frontend_events: list[tuple[str, str]]
) -> None:
    """The card is served even if no entry can be set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        unique_id=USER_ID,
        data={CONF_USERNAME: USERNAME, CONF_TOKEN: {}},
    )
    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert frontend_events == [("added", _card_url())]


@pytest.mark.usefixtures("mock_api", "cards_file")
async def test_card_without_frontend(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    """Without the frontend the file is served but no page loads it."""
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "frontend" not in hass.config.components
    assert DATA_EXTRA_MODULE_URL not in hass.data
    client = await hass_client_no_auth()
    assert (await client.get(_card_url())).status == 200


@pytest.mark.usefixtures("mock_api")
async def test_card_file_missing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    hass_client_no_auth: ClientSessionGenerator,
    frontend_events: list[tuple[str, str]],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without a built card file a warning is logged and nothing is added."""
    with patch.object(cards, "CARDS_FILE", tmp_path / "peloton-cards.js"):
        await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "the workout card is not available" in caplog.text
    assert hass.data[cards.DATA_CARDS] is None
    assert frontend_events == []
    # Set up diagnostics before the first test client: once a client has
    # started the app, its router may be frozen and diagnostics cannot add
    # its view.
    assert await async_setup_component(hass, "diagnostics", {})
    client = await hass_client_no_auth()
    assert (await client.get(cards.CARDS_URL)).status == 404

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )
    assert diagnostics["cards"] is None


@pytest.mark.usefixtures("mock_api")
async def test_card_file_unreadable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    frontend_events: list[tuple[str, str]],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An error while reading the card file does not stop the setup."""
    # Reading a directory raises IsADirectoryError, an OSError.
    with patch.object(cards, "CARDS_FILE", tmp_path):
        await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "Could not register the Peloton workout card" in caplog.text
    assert hass.data[cards.DATA_CARDS] is None
    assert frontend_events == []


@pytest.mark.usefixtures("mock_api")
async def test_card_route_taken(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    cards_file: Path,
    frontend_events: list[tuple[str, str]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A route that is already registered does not stop the setup."""
    assert await async_setup_component(hass, "http", {})
    await hass.http.async_register_static_paths(
        [StaticPathConfig(cards.CARDS_URL, str(cards_file), cache_headers=False)]
    )

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "Could not register the Peloton workout card" in caplog.text
    assert hass.data[cards.DATA_CARDS] is None
    assert frontend_events == []


@pytest.mark.usefixtures("cards_file")
async def test_card_without_http(hass: HomeAssistant) -> None:
    """Nothing is registered when the http integration is not loaded."""
    assert hass.http is None

    await cards.async_register_cards(hass)

    assert hass.data[cards.DATA_CARDS] is None


@pytest.mark.skipif(
    importlib.util.find_spec("hass_frontend") is None,
    reason="home-assistant-frontend is not installed",
)
@pytest.mark.usefixtures("mock_api", "cards_file")
async def test_card_in_frontend_page(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    """With the real frontend, the page imports the card."""
    assert await async_setup_component(hass, "frontend", {})
    await setup_integration(hass, mock_config_entry)

    client = await hass_client()
    with patch(
        "homeassistant.components.onboarding.async_is_onboarded", return_value=True
    ):
        response = await client.get("/")
    assert _card_url() in await response.text()
