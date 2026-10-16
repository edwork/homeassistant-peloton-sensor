"""Shared fixtures for Peloton tests."""

import asyncio
from collections.abc import AsyncGenerator, Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

from aiohttp import ClientSession
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"

USERNAME = "testrider"
PASSWORD = "not-a-real-password"
USER_ID = "0123456789abcdef0123456789abcdef"


def load_fixture(name: str) -> Any:
    """Load a JSON fixture from tests/fixtures."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant to load the integration under test."""


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Create entities that are disabled by default as enabled."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


@pytest.fixture
async def session(aioclient_mock: AiohttpClientMocker) -> AsyncGenerator[ClientSession]:
    """Return an aiohttp session whose requests are answered by aioclient_mock."""
    client_session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield client_session
    await client_session.close()


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry shaped like the current VERSION 2 entries."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=f"Peloton: {USERNAME}",
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )


@pytest.fixture
def workout() -> dict[str, Any]:
    """Return the latest workout the mocked API reports (complete by default)."""
    return load_fixture("workout_complete.json")


@pytest.fixture
def mock_peloton(workout: dict[str, Any]) -> Generator[MagicMock]:
    """Patch the pylotoncycle client used by setup and the config flow.

    The returned mock is the class; ``mock_peloton.return_value`` is the client.
    """
    client = MagicMock()
    client.username = USERNAME
    client.userid = USER_ID
    client.GetMe.return_value = load_fixture("me.json")
    client.GetSettings.return_value = load_fixture("settings.json")
    client.GetRecentWorkouts.return_value = [workout]
    client.GetWorkoutMetricsById.return_value = load_fixture("performance_graph.json")
    with (
        patch(
            "custom_components.peloton.PylotonCycle", return_value=client
        ) as mock_class,
        patch("custom_components.peloton.config_flow.PylotonCycle", new=mock_class),
    ):
        yield mock_class
