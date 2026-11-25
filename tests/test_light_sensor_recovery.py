"""Sensor outage and recovery through the full production chain.

Chain: sensor state -> source selection -> brightness classification -> area state -> group
decision -> Home Assistant service call. Runs on the coordination harness (real integration, real
service events). UNKNOWN never means DARK or BRIGHT, a sensor outage alone never switches a light,
and a configured area sensor never falls back to the global sensor.
"""

from __future__ import annotations

from homeassistant.const import (
    STATE_OFF,
)  # noqa: F401
from homeassistant.core import HomeAssistant
import pytest

from custom_components.adaptive_areas.const import (
    CONF_AREA_ILLUMINANCE_SENSOR,
    DOMAIN,
    AreaStates,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests import test_light_coordination_regression as regression
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    _band,
    _bright,
    _dark,
    _entry,
    _free,
    _occupy,
    _unknown,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

AREA_LUX = "sensor.area_lux"


def _ons(step: dict) -> list:
    return [c for c in step["calls"] if c[0] == "turn_on" and "overhead" in c[1]]


def _offs(step: dict) -> list:
    return [c for c in step["calls"] if c[0] == "turn_off"]


async def _lux(hass: HomeAssistant, value: str) -> None:
    await regression._set_lux(hass, value)


async def _lux_90(hass):
    await _lux(hass, "90")


async def _lux_100(hass):
    await _lux(hass, "100")


async def _lux_110(hass):
    await _lux(hass, "110")


async def _lux_111(hass):
    await _lux(hass, "110.1")


async def test_dark_then_outage_then_dark_again_turns_on_only_once(hass) -> None:
    """DARK and occupied switches on; an outage sends nothing; recovered DARK sends nothing more while on."""
    per = await regression.run_probe(hass, _entry(), [_dark, _occupy, _unknown, _dark])
    assert len(_ons(per[1])) == 1
    assert per[2]["calls"] == []
    assert per[3]["calls"] == []


async def test_bright_occupied_outage_then_dark_turns_on_once(hass) -> None:
    """BRIGHT with occupancy keeps the group silent; an outage stays silent; recovered DARK switches on."""
    per = await regression.run_probe(
        hass, _entry(), [_bright, _occupy, _unknown, _dark]
    )
    assert _ons(per[1]) == []
    assert _ons(per[2]) == []
    assert len(_ons(per[3])) == 1


async def test_unknown_band_without_previous_state_is_not_dark(hass) -> None:
    """Inside the band without a previous DARK/BRIGHT state the group stays silent."""
    per = await regression.run_probe(hass, _entry(), [_unknown, _occupy, _band])
    assert _ons(per[1]) == []
    assert _ons(per[2]) == []


async def test_exact_turn_on_boundary_is_dark(hass) -> None:
    """Exactly 90 lx is DARK (documented: turn on at or below) and switches the occupied group on."""
    per = await regression.run_probe(hass, _entry(), [_occupy, _lux_90])
    assert len(_ons(per[1])) == 1


async def test_above_turn_off_boundary_is_bright(hass) -> None:
    """110.1 lx is BRIGHT (documented: turn off at or above) and keeps the require-dark group silent."""
    per = await regression.run_probe(hass, _entry(), [_occupy, _lux_111])
    assert _ons(per[1]) == []


async def test_hysteresis_band_keeps_previous_dark_state(hass) -> None:
    """DARK, then a band value 100 lx: the previous DARK state is kept, no new command."""
    per = await regression.run_probe(hass, _entry(), [_dark, _occupy, _lux_100])
    assert len(_ons(per[1])) == 1
    assert per[2]["calls"] == []


async def test_clear_during_outage_switches_off_regardless_of_brightness(hass) -> None:
    """CLEAR switches off on the normal path even when the brightness sensor is unavailable."""
    per = await regression.run_probe(hass, _entry(), [_dark, _occupy, _unknown, _free])
    assert _offs(per[3]) != []


async def test_configured_area_sensor_outage_does_not_fall_back_to_global(hass) -> None:
    """An unavailable configured area sensor does not use the global DARK value."""
    base = _entry()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**base.data, CONF_AREA_ILLUMINANCE_SENSOR: AREA_LUX},
        options=base.options,
    )
    hass.states.async_set(AREA_LUX, "unavailable")
    per = await regression.run_probe(hass, entry, [_dark, _occupy])
    assert _ons(per[1]) == []


async def _unblock(hass: HomeAssistant) -> None:
    hass.states.async_set(regression.SLEEP, STATE_OFF)
    await hass.async_block_till_done()


async def test_outage_with_manual_override_never_switches_on_automatically(
    hass,
) -> None:
    """A manual OFF sets the override; an outage and a recovered DARK must not switch the group on."""
    per = await regression.run_probe(
        hass, _entry(), [_dark, _occupy, regression._manual_off, _unknown, _dark]
    )
    assert len(_ons(per[1])) == 1
    assert _ons(per[3]) == []
    assert _ons(per[4]) == []


async def test_outage_with_blocker_then_recovery_after_blocker_end(hass) -> None:
    """Blocker active: outage and recovered DARK stay silent.

    After the blocker ends, the normal evaluation applies and the occupied group switches on once.
    """
    per = await regression.run_probe(
        hass,
        _entry(blocking=[AreaStates.SLEEP]),
        [_dark, _occupy, regression._block, _unknown, _dark, _unblock],
    )
    assert len(_ons(per[1])) == 1
    assert _ons(per[3]) == []
    assert _ons(per[4]) == []
    assert len(_ons(per[5])) == 1
