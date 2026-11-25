"""Brightness-mode matrix through the real light chain (Phase 7 regression).

Each mode is run through the real integration (state -> brightness -> area state -> group
decision -> native light service call). The expected numbers of automatic ON and OFF calls follow
the transition table of helpers/light_transition.py; a command is sent only when the group is not
already in the target state (duplicate suppression). UNKNOWN never switches a light.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests import test_light_coordination_regression as regression
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    _bright,
    _dark,
    _free,
    _occupy,
    _unknown,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

MODES = ["ignore", "require_dark", "turn_off", "dark_on_bright_off"]

# Scenario -> expected (ON, OFF) counts of the overhead group per mode. The vacancy OFF is
# owned by the ALL group (OFF only) and is therefore not counted here; see the ALL test below.
SCENARIOS = {
    "dark_occupy_bright_dark_free": (
        [_dark, _occupy, _bright, _dark, _free],
        {
            "ignore": (1, 0),
            "require_dark": (1, 0),
            "turn_off": (2, 1),
            "dark_on_bright_off": (2, 1),
        },
    ),
    "bright_occupy_dark_bright_free": (
        [_bright, _occupy, _dark, _bright, _free],
        {
            "ignore": (1, 0),
            "require_dark": (1, 0),
            "turn_off": (1, 1),
            "dark_on_bright_off": (1, 1),
        },
    ),
    "dark_occupy_outage_free": (
        [_dark, _occupy, _unknown, _free],
        dict.fromkeys(MODES, (1, 0)),
    ),
}


def _entry(mode: str) -> MockConfigEntry:
    entry = regression._entry()
    features = entry.data[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]
    features[CONF_OVERHEAD_LIGHTS_BRIGHTNESS] = mode
    return entry


def _ons(step: dict) -> list:
    return [c for c in step["calls"] if c[0] == "turn_on" and "overhead" in c[1]]


def _offs(step: dict) -> list:
    return [c for c in step["calls"] if c[0] == "turn_off" and "overhead" in c[1]]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("scenario", list(SCENARIOS))
async def test_mode_matches_transition_table(
    hass: HomeAssistant, mode, scenario
) -> None:
    """Automatic ON and OFF calls per mode and scenario match the transition table."""
    steps, expected = SCENARIOS[scenario]
    per = await regression.run_probe(hass, _entry(mode), steps)
    on_count = sum(len(_ons(step)) for step in per)
    off_count = sum(len(_offs(step)) for step in per)
    assert (on_count, off_count) == expected[mode]


@pytest.mark.parametrize("mode", MODES)
async def test_vacancy_off_is_sent_by_the_all_group(hass: HomeAssistant, mode) -> None:
    """Vacancy switches off through the ALL group in every mode; the overhead group sends none."""
    steps = [_dark, _occupy, _free]
    per = await regression.run_probe(hass, _entry(mode), steps)
    all_offs = [
        c
        for step in per
        for c in step["calls"]
        if c[0] == "turn_off" and "all_lights" in c[1]
    ]
    assert len(all_offs) >= 1
    assert all(c[0] == "turn_off" for c in all_offs)
