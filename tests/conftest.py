"""Shared fixtures for Peloton tests."""

import asyncio
from collections.abc import AsyncGenerator, Generator
import json
from pathlib import Path
import time
from typing import Any
from unittest.mock import PropertyMock, patch

from aiohttp import ClientSession
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.api.const import API_BASE, REVOKE_URL, TOKEN_URL
from custom_components.peloton.const import DOMAIN

from .peloton_api import ACCESS_TOKEN_LIFETIME, USER_ID, make_jwt, token_response

FIXTURES = Path(__file__).parent / "fixtures"

USERNAME = "testrider"
PASSWORD = "not-a-real-password"
WORKOUT_ID = "fedcba9876543210fedcba9876543210"

JSON_HEADERS = {"content-type": "application/json; charset=utf-8"}


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


def stored_tokens(**changes: Any) -> dict[str, Any]:
    """Return tokens as stored in a version 3 entry, valid for 48 hours."""
    expires_at = time.time() + ACCESS_TOKEN_LIFETIME
    tokens = {
        "access_token": make_jwt({"exp": int(expires_at), "marker": "stored"}),
        "refresh_token": "stored-refresh",
        "expires_at": expires_at,
        "user_id": USER_ID,
    }
    return tokens | changes


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a version 3 config entry holding tokens."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=3,
        title=f"Peloton: {USERNAME}",
        unique_id=USER_ID,
        data={CONF_USERNAME: USERNAME, CONF_TOKEN: stored_tokens()},
    )


@pytest.fixture
def mock_config_entry_v2() -> MockConfigEntry:
    """Return a version 2 config entry that still stores the password."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=f"Peloton: {USERNAME}",
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )


@pytest.fixture
def workouts_json() -> dict[str, Any]:
    """Return the workout list response (latest workout complete by default)."""
    return load_fixture("api/workouts.json")


@pytest.fixture
def workout_json() -> dict[str, Any]:
    """Return the workout detail response."""
    return load_fixture("api/workout.json")


@pytest.fixture
def token_json() -> dict[str, Any]:
    """Return the token endpoint response (a login, with a refresh token)."""
    return token_response(now=time.time())


@pytest.fixture
def settings_json() -> dict[str, Any]:
    """Return the user settings response (imperial units)."""
    return load_fixture("settings.json")


@pytest.fixture
def mock_api(
    aioclient_mock: AiohttpClientMocker,
    token_json: dict[str, Any],
    settings_json: dict[str, Any],
    workouts_json: dict[str, Any],
    workout_json: dict[str, Any],
) -> AiohttpClientMocker:
    """Answer every Peloton endpoint the integration uses."""
    aioclient_mock.post(TOKEN_URL, json=token_json, headers=JSON_HEADERS)
    aioclient_mock.post(REVOKE_URL, text="", headers=JSON_HEADERS)
    aioclient_mock.get(
        f"{API_BASE}/api/me", json=load_fixture("me.json"), headers=JSON_HEADERS
    )
    aioclient_mock.get(
        f"{API_BASE}/api/user/{USER_ID}/settings",
        json=settings_json,
        headers=JSON_HEADERS,
    )
    aioclient_mock.get(
        f"{API_BASE}/api/user/{USER_ID}/workouts",
        json=workouts_json,
        headers=JSON_HEADERS,
    )
    aioclient_mock.get(
        f"{API_BASE}/api/workout/{WORKOUT_ID}/performance_graph",
        json=load_fixture("performance_graph.json"),
        headers=JSON_HEADERS,
    )
    aioclient_mock.get(
        f"{API_BASE}/api/workout/{WORKOUT_ID}", json=workout_json, headers=JSON_HEADERS
    )
    return aioclient_mock
