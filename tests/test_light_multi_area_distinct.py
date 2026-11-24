"""Runtime isolation of two Areas with distinct lamps (real HA, real service calls).

Ownership freedom alone does not prove isolation at runtime. These tests check, per step, which
physical lamp each automatic call targets, and that one Area's occupation, brightness, unload,
reload or manual action never reaches the other Area's lamp. Automatic calls carry no user
context; a user action is recognised by its context. No sleeps.
"""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    LIGHT_GROUP_BRIGHTNESS_IGNORE,
)
from tests import test_light_coordination_regression as regression
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    LUX,
    _bright,
    probe_devices,
)
from tests.test_light_ownership_runtime import (  # noqa: F401
    LIGHT,
    LIGHT_B,
    LIVING_OVERHEAD,
    _automatic,
    _dark,
    _free,
    _occupy,
    _run,
    _valid,
    setup_lamps,
)

pytestmark = pytest.mark.usefixtures("probe_devices", "lamps")


def _lamp_calls(events: list[dict], lamp: str) -> list[dict]:
    """Automatic calls whose target is this lamp, directly or through a group."""
    return [e for e in _automatic(events) if lamp in e["targets"]]


async def _lux_unknown(hass: HomeAssistant) -> None:
    hass.states.async_set(LUX, "unavailable", {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()


async def test_each_area_switches_only_its_own_lamp(hass) -> None:
    """Occupation of A reaches only A's lamp; occupation of B reaches only B's lamp."""
    per = await _run(hass, _valid(), [_dark, _occupy("a"), _occupy("b")])
    assert _lamp_calls(per[1], LIGHT) and not _lamp_calls(per[1], LIGHT_B)
    assert _lamp_calls(per[2], LIGHT_B) and not _lamp_calls(per[2], LIGHT)


async def test_occupation_of_one_area_does_not_switch_the_other(hass) -> None:
    """A's occupation sends nothing to B's lamp and nothing to B's group."""
    per = await _run(hass, _valid(), [_dark, _occupy("a")])
    assert _lamp_calls(per[1], LIGHT_B) == []
    assert [e for e in _automatic(per[1]) if e["targets"] == [LIVING_OVERHEAD]] == []


async def test_both_areas_react_independently(hass) -> None:
    """A's vacancy switches A's lamp off; B's occupation state is untouched by it."""
    per = await _run(hass, _valid(), [_dark, _occupy("a"), _occupy("b"), _free("a")])
    assert _lamp_calls(per[3], LIGHT)
    assert _lamp_calls(per[3], LIGHT_B) == []


async def test_brightness_is_respected_per_configuration(hass) -> None:
    """A uses 'ignore' brightness, B requires darkness: bright occupation switches only A on."""
    entries = _valid()
    groups_a = entries["a"].data[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]
    groups_a[CONF_OVERHEAD_LIGHTS_BRIGHTNESS] = LIGHT_GROUP_BRIGHTNESS_IGNORE
    per = await _run(hass, entries, [_bright, _occupy("a"), _occupy("b")])
    assert _lamp_calls(per[1], LIGHT)
    assert _lamp_calls(per[2], LIGHT_B) == []


async def test_unknown_brightness_switches_neither_area_on(hass) -> None:
    """UNKNOWN brightness: both require-dark Areas stay off."""
    per = await _run(hass, _valid(), [_lux_unknown, _occupy("a"), _occupy("b")])
    assert _automatic(per[1]) == []
    assert _automatic(per[2]) == []


async def test_unload_of_a_does_not_change_b(hass) -> None:
    """Unloading A sends nothing; B's later vacancy switches only B's lamp."""
    entries = _valid()

    async def _unload_a(hass_: HomeAssistant) -> None:
        assert await hass_.config_entries.async_unload(entries["a"].entry_id)
        await hass_.async_block_till_done()

    per = await _run(
        hass,
        entries,
        [_dark, _occupy("a"), _occupy("b"), _unload_a, _free("b")],
    )
    # Step 3 is A's unload: no automatic call at all. Step 4 is B's vacancy.
    assert _automatic(per[3]) == []
    assert _lamp_calls(per[4], LIGHT) == []
    assert _lamp_calls(per[4], LIGHT_B)


async def test_reload_of_a_gives_one_new_generation_and_no_old_calls(hass) -> None:
    """Reloading A: the new generation occupies once; B's lamp stays untouched."""
    entries = _valid()

    async def _reload_a(hass_: HomeAssistant) -> None:
        assert await hass_.config_entries.async_reload(entries["a"].entry_id)
        await hass_.async_block_till_done()
        await regression._enable_group_control(hass_)

    per = await _run(
        hass,
        entries,
        [_dark, _reload_a, _free("a"), _occupy("a")],
    )
    assert _lamp_calls(per[2], LIGHT_B) == []
    assert len(_lamp_calls(per[3], LIGHT)) == 1
    assert _lamp_calls(per[3], LIGHT_B) == []


async def test_manual_action_stays_on_its_own_light(hass) -> None:
    """A user switches A's lamp on: a user call, never an automatic call for B."""

    async def _user_on_a(hass_: HomeAssistant) -> None:
        await hass_.services.async_call(
            "light",
            "turn_on",
            {ATTR_ENTITY_ID: LIGHT},
            blocking=True,
            context=Context(user_id=regression.PROBE_USER[0]),
        )
        await hass_.async_block_till_done()

    per = await _run(hass, _valid(), [_dark, _occupy("b"), _user_on_a])
    user = [e for e in per[2] if e["user"]]
    assert [(e["service"], LIGHT in e["targets"]) for e in user] == [("turn_on", True)]
    assert _lamp_calls(per[2], LIGHT_B) == []
