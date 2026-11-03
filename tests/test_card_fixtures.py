"""Contract fixtures for the workout card.

Each scenario sets up the integration against the mocked API and compares
what the card reads from Home Assistant with frontend/test/fixtures/
<scenario>.json. The files have the shape of the frontend's hass object
(states, entities and devices), so the card tests run against the states,
attributes and translation keys this integration really produces.

After an intended change, rewrite the files with
PELOTON_UPDATE_CARD_FIXTURES=1 and run the card tests.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
import json
import os
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.json import json_dumps
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from homeassistant.util.yaml import load_yaml
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.peloton.api.const import API_BASE
from custom_components.peloton.const import DOMAIN, TOLERATED_FAILED_POLLS

from .common import advance, setup_integration
from .conftest import JSON_HEADERS, USER_ID, load_fixture
from .test_entities import (
    _register_graph,
    in_progress_detail,
    in_progress_list,
    rower_graph,
    tread_graph,
)
from .test_examples import BLUEPRINT

ROOT = Path(__file__).parent.parent
COMPONENT = ROOT / "custom_components" / "peloton"
FIXTURES = ROOT / "frontend" / "test" / "fixtures"
UPDATE = os.environ.get("PELOTON_UPDATE_CARD_FIXTURES") == "1"

# Biome formats the fixtures with this line width (frontend/biome.json).
LINE_WIDTH = 100

DURING = "2025-10-09 09:00:00+00:00"  # 7 minutes into the 30 minute class
AFTER = "2025-10-09 10:00:00+00:00"  # the class ended at 09:23:20

type Scenario = Callable[
    [HomeAssistant, AiohttpClientMocker, FrozenDateTimeFactory, MockConfigEntry],
    Awaitable[None],
]


def _pre_roll_graph() -> dict[str, Any]:
    """Return the performance graph of a ride before its first sample.

    As recorded on a real ride: every value is null except the calories,
    which are 0, and the metrics have no samples yet.
    """
    graph = load_fixture("performance_graph.json")
    for summary in graph["summaries"] + graph["average_summaries"]:
        summary["value"] = 0 if summary["slug"] == "calories" else None
    for metric in graph["metrics"]:
        metric |= {"average_value": None, "max_value": None, "values": []}
    return graph


async def _no_workouts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    freezer.move_to(AFTER)
    _register_graph(
        aioclient_mock,
        load_fixture("performance_graph.json"),
        load_fixture("api/workout.json"),
        load_fixture("api/workouts_empty.json"),
    )
    await setup_integration(hass, entry)


async def _pre_roll(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    freezer.move_to(DURING)
    _register_graph(
        aioclient_mock,
        _pre_roll_graph(),
        in_progress_detail(
            total_work=0.0, leaderboard_rank=None, total_leaderboard_users=None
        ),
        in_progress_list(),
    )
    await setup_integration(hass, entry)


async def _active_cycling(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    freezer.move_to(DURING)
    _register_graph(
        aioclient_mock,
        load_fixture("performance_graph.json"),
        in_progress_detail(),
        in_progress_list(),
    )
    await setup_integration(hass, entry)


async def _paused(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    # Peloton drops the leaderboard rank after the first pause.
    freezer.move_to(DURING)
    _register_graph(
        aioclient_mock,
        load_fixture("performance_graph.json"),
        in_progress_detail(is_paused=True, leaderboard_rank=None),
        in_progress_list(),
    )
    await setup_integration(hass, entry)


async def _finished_cycling(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    freezer.move_to(AFTER)
    _register_graph(
        aioclient_mock,
        load_fixture("performance_graph.json"),
        load_fixture("api/workout.json"),
    )
    await setup_integration(hass, entry)


async def _strength_in_progress(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    freezer.move_to(DURING)
    _register_graph(
        aioclient_mock,
        {"duration": 1800, "summaries": [], "metrics": []},
        in_progress_detail(
            fitness_discipline="strength",
            leaderboard_rank=None,
            total_leaderboard_users=None,
        ),
        in_progress_list(fitness_discipline="strength"),
    )
    await setup_integration(hass, entry)


async def _rower(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    freezer.move_to(AFTER)
    _register_graph(
        aioclient_mock,
        rower_graph(),
        load_fixture("api/workout.json") | {"fitness_discipline": "caesar"},
    )
    await setup_integration(hass, entry)


async def _tread(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    freezer.move_to(DURING)
    _register_graph(
        aioclient_mock,
        tread_graph(),
        in_progress_detail(fitness_discipline="running"),
        in_progress_list(fitness_discipline="running"),
    )
    await setup_integration(hass, entry)


async def _unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    await _finished_cycling(hass, aioclient_mock, freezer, entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{API_BASE}/api/user/{USER_ID}/workouts",
        status=503,
        text="unavailable",
        headers=JSON_HEADERS,
    )
    for _ in range(TOLERATED_FAILED_POLLS + 1):
        await advance(hass, freezer, timedelta(seconds=60))
    assert entry.runtime_data.failed_polls == TOLERATED_FAILED_POLLS + 1


async def _disabled_metric(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry,
) -> None:
    # The user disabled the three cadence sensors.
    entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    for kind in ("average", "max", "current"):
        entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{USER_ID}_cadence:_{kind}",
            config_entry=entry,
            suggested_object_id=f"test_on_peloton_cadence_{kind}",
            disabled_by=er.RegistryEntryDisabler.USER,
        )
    await _active_cycling(hass, aioclient_mock, freezer, entry)


# Scenario name (the fixture file name) -> setup, and the expected state of
# the workout binary sensor.
SCENARIOS: dict[str, tuple[Scenario, str]] = {
    "no_workouts": (_no_workouts, STATE_OFF),
    "pre_roll": (_pre_roll, STATE_ON),
    "active_cycling": (_active_cycling, STATE_ON),
    "paused": (_paused, STATE_ON),
    "finished_cycling": (_finished_cycling, STATE_OFF),
    "strength_in_progress": (_strength_in_progress, STATE_ON),
    "rower": (_rower, STATE_OFF),
    "tread": (_tread, STATE_ON),
    "unavailable": (_unavailable, STATE_UNAVAILABLE),
    "disabled_metric": (_disabled_metric, STATE_ON),
}


def _snapshot(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    """Return the integration's part of the frontend's hass object.

    Disabled entities are left out, as in Home Assistant's
    config/entity_registry/list_for_display. Registry ids are random, so
    device ids become "device-1", "device-2", ...; last_changed,
    last_updated and context are not included.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    devices = sorted(
        dr.async_entries_for_config_entry(device_registry, entry.entry_id),
        key=lambda device: sorted(device.identifiers),
    )
    device_ids = {
        device.id: f"device-{index}" for index, device in enumerate(devices, 1)
    }

    entities: dict[str, Any] = {}
    states: dict[str, Any] = {}
    for registry_entry in sorted(
        er.async_entries_for_config_entry(entity_registry, entry.entry_id),
        key=lambda registry_entry: registry_entry.entity_id,
    ):
        if registry_entry.disabled_by is not None:
            continue
        entity_id = registry_entry.entity_id
        # The keys the frontend expands from the display entry ("ei", "pl",
        # "di", "tk", "dp"); absent values are left out, as there.
        display: dict[str, Any] = {
            "entity_id": entity_id,
            "platform": registry_entry.platform,
        }
        if registry_entry.device_id is not None:
            display["device_id"] = device_ids[registry_entry.device_id]
        if registry_entry.translation_key is not None:
            display["translation_key"] = registry_entry.translation_key
        sensor_options = registry_entry.options.get("sensor", {})
        precision = sensor_options.get("display_precision")
        if precision is None:
            precision = sensor_options.get("suggested_display_precision")
        if registry_entry.domain == "sensor" and precision is not None:
            display["display_precision"] = precision
        entities[entity_id] = display
        if (state := hass.states.get(entity_id)) is not None:
            states[entity_id] = {
                "state": state.state,
                "attributes": json.loads(json_dumps(dict(state.attributes))),
            }

    return {
        "states": states,
        "entities": entities,
        "devices": {
            device_ids[device.id]: {
                "identifiers": sorted([list(pair) for pair in device.identifiers]),
                "name": device.name,
                "name_by_user": device.name_by_user,
                "disabled_by": device.disabled_by,
            }
            for device in devices
        },
    }


def _format(value: Any, indent: str = "", used: int = 0) -> str:
    """Return JSON as Biome formats it.

    Objects are expanded one key per line; arrays without objects stay on
    one line when they fit. `used` is the width of the text before the value.
    """
    inner = indent + "  "
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = []
        for key, item in sorted(value.items()):
            prefix = f"{json.dumps(key)}: "
            items.append(
                f"{inner}{prefix}{_format(item, inner, len(inner) + len(prefix))}"
            )
        return "{\n" + ",\n".join(items) + f"\n{indent}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        flat = json.dumps(value)
        if "{" not in flat and used + len(flat) + 1 <= LINE_WIDTH:
            return flat
        items = [f"{inner}{_format(item, inner, len(inner))}" for item in value]
        return "[\n" + ",\n".join(items) + f"\n{indent}]"
    return json.dumps(value)


@pytest.fixture(autouse=True)
def imperial(hass: HomeAssistant) -> None:
    """Use US customary units, matching the imperial Peloton settings."""
    hass.config.units = US_CUSTOMARY_SYSTEM


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_card_fixture(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    scenario: str,
) -> None:
    """The card's fixture matches what the integration writes for the scenario."""
    setup, workout_state = SCENARIOS[scenario]
    await setup(hass, aioclient_mock, freezer, mock_config_entry)

    snapshot = _snapshot(hass, mock_config_entry)
    workout_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{USER_ID}_workout"
    )
    assert snapshot["states"][workout_id]["state"] == workout_state

    text = _format(snapshot) + "\n"
    path = FIXTURES / f"{scenario}.json"
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    assert path.is_file(), (
        f"{path.name} is missing; run with PELOTON_UPDATE_CARD_FIXTURES=1"
    )
    assert json.loads(path.read_text()) == snapshot, (
        f"{path.name} is out of date; run with PELOTON_UPDATE_CARD_FIXTURES=1"
    )
    assert path.read_text() == text, f"{path.name} is not formatted as generated"


def test_no_stale_fixtures() -> None:
    """Every fixture file belongs to a scenario."""
    assert {path.stem for path in FIXTURES.glob("*.json")} == set(SCENARIOS)


@pytest.mark.usefixtures("mock_api", "entity_registry_enabled_by_default")
async def test_translation_keys_are_unique(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """The card maps entities by translation key, across both platforms."""
    await setup_integration(hass, mock_config_entry)

    keys = [
        registry_entry.translation_key
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
    ]
    assert None not in keys
    assert len(keys) == len(set(keys))
    strings = json.loads((COMPONENT / "strings.json").read_text())["entity"]
    assert not set(strings["sensor"]) & set(strings["binary_sensor"])
    assert set(keys) == set(strings["sensor"]) | set(strings["binary_sensor"])


@pytest.mark.parametrize(
    "path",
    [COMPONENT / "strings.json", COMPONENT / "translations" / "en.json"],
    ids=lambda path: path.name,
)
def test_workout_types_have_names(path: Path) -> None:
    """Every workout_type the blueprint offers has a state translation."""
    select = load_yaml(BLUEPRINT)["blueprint"]["input"]["skip_workout_types"]
    slugs = {option["value"] for option in select["selector"]["select"]["options"]}
    workout = json.loads(path.read_text())["entity"]["binary_sensor"]["workout"]
    names = workout["state_attributes"]["workout_type"]["state"]

    assert slugs <= names.keys()
    assert all(isinstance(names[slug], str) and names[slug] for slug in slugs)
