"""Tests for the Peloton integration."""

import importlib
import importlib.util
import sys

# The tests import the pytest-homeassistant plugin (Home Assistant 2026.11 and
# newer). It has no release for older versions, so the minimum job
# (requirements_test_min.txt) installs pytest-homeassistant-custom-component,
# which has the same modules under another name. Register those modules under
# the new name; importing them through the new name would load second copies.
# Add any newly imported submodule here. Remove this when the minimum Home
# Assistant version in hacs.json reaches 2026.11.
if importlib.util.find_spec("pytest_homeassistant") is None:
    for _submodule in (
        "",
        ".common",
        ".components",
        ".components.diagnostics",
        ".components.recorder",
        ".components.recorder.common",
        ".test_util",
        ".test_util.aiohttp",
        ".typing",
    ):
        sys.modules[f"pytest_homeassistant{_submodule}"] = importlib.import_module(
            f"pytest_homeassistant_custom_component{_submodule}"
        )
