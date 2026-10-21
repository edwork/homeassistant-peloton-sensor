"""Tests that the README matches the integration."""

import json
from pathlib import Path
import re

import pytest

from custom_components.peloton.const import (
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_MAX_WORKOUT_MINUTES,
)
from custom_components.peloton.sensor import SENSORS

from .test_entities import BINARY_SENSOR_ATTRIBUTES

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"
DOCS = [
    README,
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "api.md",
    ROOT / "examples" / "README.md",
    ROOT / "assets" / "README.md",
]
TRANSLATIONS = json.loads(
    (ROOT / "custom_components" / "peloton" / "translations" / "en.json").read_text()
)


def _section(heading: str) -> str:
    """Return the README text under a heading, up to the next heading."""
    text = README.read_text()
    start = text.index(f"\n{heading}\n")
    end = text.find("\n#", start + len(heading) + 2)
    return text[start : end if end != -1 else None]


def _table_rows(section: str) -> list[list[str]]:
    """Return the cells of each body row of the first table in a section."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|")
    ]
    return rows[2:]


def test_entity_table_matches_entities() -> None:
    """Every entity is in the README table and the table has no others."""
    documented: set[str] = set()
    for name, _unit, description in _table_rows(_section("## Entities")):
        if match := re.fullmatch(r"(.+) average, (max|best), current", name):
            base, top = match.groups()
            documented |= {f"{base} average", f"{base} {top}", f"{base} current"}
        elif name == "Workout counts":
            types = re.search(r"per type: (.+?)\. ", description)
            assert types
            documented |= {
                f"{kind.capitalize()} count"
                for kind in re.split(r", (?:and )?| and ", types.group(1))
            }
        else:
            documented.add(name)

    entities = TRANSLATIONS["entity"]
    names = {entities["binary_sensor"]["workout"]["name"]} | {
        entities["sensor"][d.translation_key]["name"] for d in SENSORS
    }
    assert documented == names


def test_attribute_table_matches_binary_sensor() -> None:
    """The README lists the workout sensor's attributes."""
    rows = _table_rows(_section("### Workout binary sensor attributes"))
    assert [row[0].strip("`") for row in rows] == list(BINARY_SENSOR_ATTRIBUTES)


def test_option_defaults() -> None:
    """The options table shows the defaults the integration uses."""
    defaults = [row[1] for row in _table_rows(_section("### Options"))]
    assert defaults == [
        f"{DEFAULT_IDLE_INTERVAL} s",
        f"{DEFAULT_ACTIVE_INTERVAL} s",
        f"{DEFAULT_MAX_WORKOUT_MINUTES} min",
    ]


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_docs_are_plain_ascii(path: Path) -> None:
    """The documentation has no emojis or other non-ASCII characters."""
    text = path.read_text()
    assert [c for c in text if ord(c) > 127] == []
