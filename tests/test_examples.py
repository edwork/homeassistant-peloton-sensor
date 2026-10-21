"""Tests for the example dashboard, markdown card and fan blueprint."""

from datetime import timedelta
from pathlib import Path
import re
import shutil
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
import yaml

from custom_components.peloton.sensor import WORKOUT_COUNTS

from .common import setup_integration
from .conftest import load_fixture
from .test_entities import (
    BINARY_SENSOR_ATTRIBUTES,
    EXPECTED_ENTITIES,
    in_progress_detail,
    in_progress_list,
)

ROOT = Path(__file__).parent.parent
DASHBOARD = ROOT / "examples" / "dashboard.yaml"
MARKDOWN_CARD = ROOT / "examples" / "markdown_card.yaml"
BLUEPRINT = ROOT / "blueprints" / "automation" / "peloton" / "workout_fan.yaml"

# The examples use this placeholder; the test install's prefix is "test".
PLACEHOLDER = "name_on_peloton"
PREFIX = "test_on_peloton"
WORKOUT = "binary_sensor.test_on_peloton_workout"


def _example(path: Path) -> str:
    return path.read_text().replace(PLACEHOLDER, PREFIX)


def _markdown_templates() -> dict[str, str]:
    dashboard = yaml.safe_load(_example(DASHBOARD))
    cards = [card for section in dashboard["sections"] for card in section["cards"]]
    (dashboard_markdown,) = [c["content"] for c in cards if c["type"] == "markdown"]
    return {
        "dashboard": dashboard_markdown,
        "markdown_card": yaml.safe_load(_example(MARKDOWN_CARD))["content"],
    }


@pytest.mark.parametrize("path", [DASHBOARD, MARKDOWN_CARD], ids=lambda p: p.name)
def test_examples_reference_real_entities(path: Path) -> None:
    """Every entity id and attribute in the examples exists in the integration."""
    text = _example(path)
    fresh_ids = set(EXPECTED_ENTITIES.values())
    referenced = set(re.findall(r"(?:binary_sensor|sensor)\.test_on_peloton_\w+", text))
    # The markdown card builds sensor ids from a prefix and a name.
    referenced |= {
        f"sensor.{PREFIX}_{name}" for name in re.findall(r"value\('(\w+)'", text)
    }
    assert referenced
    assert referenced <= fresh_ids
    attributes = set(re.findall(r"state_attr\(w, '(\w+)'\)", text))
    assert attributes
    assert attributes <= set(BINARY_SENSOR_ATTRIBUTES)


@pytest.mark.parametrize("workouts_json", [load_fixture("api/workouts_empty.json")])
@pytest.mark.usefixtures("mock_api")
async def test_markdown_without_workouts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The markdown renders for an account without workouts."""
    await setup_integration(hass, mock_config_entry)

    for name, content in _markdown_templates().items():
        rendered = Template(content, hass).async_render(parse_result=False)
        assert "\nNo workouts yet." in f"\n{rendered}", name


@pytest.mark.usefixtures("mock_api")
async def test_markdown_completed_workout(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The markdown shows the latest workout and no live values."""
    await setup_integration(hass, mock_config_entry)

    for name, content in _markdown_templates().items():
        rendered = Template(content, hass).async_render(parse_result=False)
        assert "30 min Synthetic Ride" in rendered, name
        assert "Synthetic Instructor" in rendered, name
        assert "### Now" not in rendered, name
    card = Template(_markdown_templates()["markdown_card"], hass).async_render(
        parse_result=False
    )
    # Headings and table rows must stay on their own lines.
    assert "\n### Latest workout\n" in f"\n{card}"
    assert "\n| Total output | 360 kJ |\n" in card
    assert "\n| Distance | 16.90 km |\n" in card
    assert ", 30 min\n" in card


@pytest.mark.parametrize(
    ("workouts_json", "workout_json"),
    [(in_progress_list(), in_progress_detail())],
    ids=["in_progress"],
)
@pytest.mark.usefixtures("mock_api")
async def test_markdown_card_during_workout(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """During a workout the markdown card shows live values."""
    freezer.move_to("2025-10-09 09:00:00+00:00")
    await setup_integration(hass, mock_config_entry)

    rendered = Template(_markdown_templates()["markdown_card"], hass).async_render(
        parse_result=False
    )
    assert "\n### Now\n| | |\n|:--|--:|\n" in f"\n{rendered}"
    assert "\n| Cadence | 88 rpm |\n" in rendered
    assert "\n| Speed | 32.8 km/h |\n" in rendered


def test_dashboard_structure() -> None:
    """The dashboard is a sections view whose live cards depend on the workout."""
    dashboard = yaml.safe_load(_example(DASHBOARD))
    assert dashboard["type"] == "sections"
    cards = [card for section in dashboard["sections"] for card in section["cards"]]
    gauges = [card for card in cards if card["type"] == "gauge"]
    assert gauges
    for card in gauges:
        assert card["visibility"] == [
            {"condition": "state", "entity": WORKOUT, "state": "on"},
            {
                "condition": "state",
                "entity": card["entity"],
                "state_not": ["unknown", "unavailable"],
            },
        ]


@pytest.fixture
async def fan_automation(hass: HomeAssistant, tmp_path: Path) -> None:
    """Set up an automation from the blueprint for a fake workout sensor and fan."""
    hass.config.config_dir = str(tmp_path)
    target = tmp_path / "blueprints" / "automation" / "peloton"
    target.mkdir(parents=True)
    shutil.copy(BLUEPRINT, target / "workout_fan.yaml")
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"fan": {}}}
    )
    hass.states.async_set(WORKOUT, STATE_OFF, {"workout_type": "cycling"})
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "peloton/workout_fan.yaml",
                    # The other inputs use the blueprint defaults (5 minutes,
                    # skip meditation).
                    "input": {"workout_sensor": WORKOUT, "fan": ["input_boolean.fan"]},
                }
            }
        },
    )
    await hass.async_block_till_done()


def _set(hass: HomeAssistant, state: str, **attributes: Any) -> None:
    hass.states.async_set(WORKOUT, state, {"workout_type": "cycling"} | attributes)


async def _wait(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float
) -> None:
    """Let time pass in 10 s steps, so timers fire close to their due time."""
    for _ in range(round(minutes * 6)):
        freezer.tick(timedelta(seconds=10))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


@pytest.mark.usefixtures("fan_automation")
async def test_blueprint_turns_fan_on_and_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The fan runs during the workout and stops after the delay."""
    _set(hass, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get("input_boolean.fan").state == STATE_ON

    _set(hass, STATE_OFF)
    await _wait(hass, freezer, 4)
    assert hass.states.get("input_boolean.fan").state == STATE_ON
    await _wait(hass, freezer, 2)
    assert hass.states.get("input_boolean.fan").state == STATE_OFF


@pytest.mark.usefixtures("fan_automation")
async def test_blueprint_skips_workout_types(hass: HomeAssistant) -> None:
    """Skipped workout types do not start the fan."""
    _set(hass, STATE_ON, workout_type="meditation")
    await hass.async_block_till_done()

    assert hass.states.get("input_boolean.fan").state == STATE_OFF


@pytest.mark.usefixtures("fan_automation")
async def test_blueprint_new_workout_during_delay(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A workout that starts during the off delay keeps the fan running."""
    _set(hass, STATE_ON)
    await hass.async_block_till_done()
    _set(hass, STATE_OFF)
    await _wait(hass, freezer, 3)
    _set(hass, STATE_ON)
    await _wait(hass, freezer, 5)

    assert hass.states.get("input_boolean.fan").state == STATE_ON


@pytest.mark.usefixtures("fan_automation")
async def test_blueprint_unavailable_sensor(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Unavailable counts as ended; coming back on during a workout restarts the fan."""
    _set(hass, STATE_ON)
    await hass.async_block_till_done()
    _set(hass, STATE_UNAVAILABLE)
    await _wait(hass, freezer, 2)
    # The delay counts from leaving "on"; unavailable -> off does not restart it.
    _set(hass, STATE_OFF)
    await _wait(hass, freezer, 2)
    assert hass.states.get("input_boolean.fan").state == STATE_ON
    await _wait(hass, freezer, 2)
    assert hass.states.get("input_boolean.fan").state == STATE_OFF

    _set(hass, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    _set(hass, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get("input_boolean.fan").state == STATE_ON


@pytest.mark.usefixtures("fan_automation")
async def test_blueprint_sensor_unavailable_for_long(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The fan is turned off when the sensor stays unavailable for the delay."""
    _set(hass, STATE_ON)
    await hass.async_block_till_done()
    _set(hass, STATE_UNAVAILABLE)
    await _wait(hass, freezer, 6)

    assert hass.states.get("input_boolean.fan").state == STATE_OFF


@pytest.mark.usefixtures("fan_automation")
async def test_blueprint_ignores_idle_reload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A reload or outage while idle (off -> unavailable -> off) leaves the fan alone."""
    await hass.services.async_call(
        "input_boolean", "turn_on", {"entity_id": "input_boolean.fan"}, blocking=True
    )
    _set(hass, STATE_UNAVAILABLE)
    await _wait(hass, freezer, 1)
    _set(hass, STATE_OFF)
    await _wait(hass, freezer, 10)

    assert hass.states.get("input_boolean.fan").state == STATE_ON


def test_blueprint_workout_types_match_integration() -> None:
    """The skip options are the workout_type values the integration reports."""
    inputs = load_yaml(BLUEPRINT)["blueprint"]["input"]
    select = inputs["skip_workout_types"]["selector"]["select"]
    values = {option["value"] for option in select["options"]}

    assert values == {slug for _, slug in WORKOUT_COUNTS}
    assert set(inputs["skip_workout_types"]["default"]) <= values
