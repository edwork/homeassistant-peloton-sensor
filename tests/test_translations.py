"""Check that strings.json and translations/en.json agree."""

import json
from pathlib import Path
import re
from typing import Any

import homeassistant

COMPONENT = Path(__file__).parent.parent / "custom_components" / "peloton"
KEY = re.compile(r"\[%key:(.+)%\]")


def _flatten(node: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        flat: dict[str, str] = {}
        for key, value in node.items():
            flat |= _flatten(value, f"{prefix}{key}.")
        return flat
    return {prefix.rstrip("."): node}


def test_en_json_matches_strings_json() -> None:
    """en.json has the same keys; literal texts match; references resolve."""
    strings = _flatten(json.loads((COMPONENT / "strings.json").read_text()))
    english = _flatten(json.loads((COMPONENT / "translations" / "en.json").read_text()))
    core = json.loads(
        (Path(homeassistant.__file__).parent / "strings.json").read_text()
    )

    assert strings.keys() == english.keys()
    for key, text in strings.items():
        if match := KEY.fullmatch(text):
            node: Any = core
            for part in match.group(1).split("::"):
                node = node[part]
            assert isinstance(node, str), key
        else:
            assert english[key] == text, key
