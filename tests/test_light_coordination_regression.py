"""Regression tests for the shared light control path (current behaviour and target behaviour).

Characterisation tests (plain asserts) document what the integration does today, including
known faults. Target tests use `xfail(strict=True)`: they describe the desired behaviour and
turn into a failure as soon as the fault is fixed, so the marker must then be removed.

Original probe: real light group control and real light policy on one light.

No policy mock and no patch: the isolation used in test_light.py is deliberately not used.
Every light.turn_on / light.turn_off service call is recorded in order, together with the
result of every policy evaluation and every light group decision trace entry.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE, STATE_OFF, STATE_ON
from homeassistant.core import Context, Event, HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_OVERHEAD_LIGHTS,
    CONF_OVERHEAD_LIGHTS_ACT_ON,
    CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
    CONF_OVERHEAD_LIGHTS_STATES,
    CONF_SECONDARY_STATES,
    CONF_SLEEP_ENTITY,
    DATA_AREA_OBJECT,
    DOMAIN,
    LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
    MODULE_DATA,
    AreaStates,
)
from custom_components.adaptive_areas.helpers.brightness import area_brightness
from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)
from tests.test_light import setup_entities_light_one  # noqa: F401

LUX = "sensor.test_global_lux"
SLEEP = "binary_sensor.probe_sleep"
LIGHT = "light.mock_light_1"
MOTION = ""  # set from the motion fixture


LOG: list[str] = []
PROBE_USER: list[str] = []
CURRENT_ENTRY: list[str] = []
CALLS: list[tuple[str, str]] = []


def _entry(
    blocking: list[str] | None = None, states: list[str] | None = None
) -> MockConfigEntry:
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    group: dict[str, Any] = {
        CONF_OVERHEAD_LIGHTS: [LIGHT],
        CONF_OVERHEAD_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
        CONF_OVERHEAD_LIGHTS_STATES: (
            states if states is not None else [AreaStates.OCCUPIED]
        ),
    }
    if blocking:
        group[CONF_OVERHEAD_LIGHTS_BLOCKING_STATES] = blocking
    data.update(
        {
            CONF_SECONDARY_STATES: {CONF_SLEEP_ENTITY: SLEEP},
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
                CONF_FEATURE_LIGHT_GROUPS: group,
            },
        }
    )
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX}},
    )


@callback
def _on_call(event: Event) -> None:
    data = event.data
    if data.get("domain") == "light" and data.get("service") in ("turn_on", "turn_off"):
        target = data.get("service_data", {}).get(ATTR_ENTITY_ID)
        CALLS.append((data["service"], str(target)))


async def _settle(hass: HomeAssistant) -> None:
    await hass.async_block_till_done()


async def _set_lux(hass: HomeAssistant, value: str) -> None:
    hass.states.async_set(LUX, value, {"unit_of_measurement": "lx"})
    await _settle(hass)


async def _dark(hass):
    await _set_lux(hass, "50")


async def _bright(hass):
    await _set_lux(hass, "120")


async def _band(hass):
    await _set_lux(hass, "100")


async def _unknown(hass):
    hass.states.async_set(LUX, "unavailable")
    await _settle(hass)


async def _occupy(hass):
    hass.states.async_set(MOTION, STATE_ON)
    await _settle(hass)


async def _free(hass):
    hass.states.async_set(MOTION, STATE_OFF)
    await _settle(hass)


def _overhead_group_state(hass: HomeAssistant):
    return hass.states.get(
        f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA.value}_overhead_lights"
    )


def _group_manual_flag(hass: HomeAssistant) -> bool:
    """Manual override of the overhead group, read from its state attribute (no policy runtime)."""
    state = _overhead_group_state(hass)
    return state is not None and state.attributes.get("manual_override") is True


def _group_override_label(hass: HomeAssistant) -> str:
    """Return the override label: force_off after a manual change, otherwise none."""
    return "force_off" if _group_manual_flag(hass) else "none"


async def _block(hass):
    hass.states.async_set(SLEEP, STATE_ON)
    await _settle(hass)


async def _manual_off_no_user(hass):
    """Change without user context: how a physical switch or another automation looks to HA."""
    await hass.services.async_call(
        "light", "turn_off", {ATTR_ENTITY_ID: LIGHT}, blocking=True
    )
    await _settle(hass)
    LOG.append(f"override after no-user off: {_group_override_label(hass)}")


async def _manual_off(hass):
    # A user-originated change (user_id set) is what detect_manual_light_action accepts.
    await hass.services.async_call(
        "light",
        "turn_off",
        {ATTR_ENTITY_ID: LIGHT},
        blocking=True,
        context=Context(user_id=PROBE_USER[0]),
    )
    await _settle(hass)
    LOG.append(f"override after manual off: {_group_override_label(hass)}")
    LOG.append(f"group manual_override: {_group_manual_flag(hass)}")


CONTROL_SWITCH = (
    f"switch.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA.value}_light_control"
)


async def _enable_group_control(hass: HomeAssistant) -> None:
    """Enable the group control switch, the same precondition as test_light_group_basic."""
    hass.states.async_set(CONTROL_SWITCH, STATE_ON)
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: CONTROL_SWITCH}, blocking=True
    )
    await _settle(hass)


async def run_probe(hass: HomeAssistant, entry: MockConfigEntry, steps) -> list[dict]:
    """Run the steps with the real integration; return the calls and policy log per step."""
    hass.bus.async_listen(EVENT_CALL_SERVICE, _on_call)
    CURRENT_ENTRY[:] = [entry.entry_id]
    await init_integration(hass, [entry])
    await _enable_group_control(hass)
    results = []
    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    try:
        for step in steps:
            CALLS.clear()
            LOG.clear()
            await step(hass)
            results.append(
                {
                    "step": step.__name__,
                    "calls": list(CALLS),
                    "policy": list(LOG),
                    "brightness": area_brightness(hass, area).state.value,
                    "occupied": area.is_occupied(),
                    "group_on": hass.states.is_state(
                        f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA.value}_overhead_lights",
                        STATE_ON,
                    ),
                    "light": hass.states.get(LIGHT).state,
                }
            )
    finally:
        await shutdown_integration(hass, [entry])
        return results


@pytest.fixture(name="probe_devices")
async def probe_devices(hass, entities_light_one, entities_binary_sensor_motion_one):
    """Lights and motion sensor exist; the global lux sensor starts bright."""
    global MOTION
    MOTION = entities_binary_sensor_motion_one[0].entity_id
    hass.states.async_set(LUX, "150", {"unit_of_measurement": "lx"})
    hass.states.async_set(SLEEP, STATE_OFF)
    user = await hass.auth.async_create_user("probe-user")
    PROBE_USER[:] = [user.id]
    return hass


SCENARIOS = {
    "S1": ("DARK occupied, no block", lambda: _entry(), [_free, _dark, _occupy]),
    "S2": (
        "DARK occupied, group blocked (sleep)",
        lambda: _entry(blocking=[AreaStates.SLEEP]),
        [_block, _dark, _occupy],
    ),
    "S3": (
        "DARK occupied, activation state missing",
        lambda: _entry(states=[AreaStates.EXTENDED]),
        [_free, _dark, _occupy],
    ),
    "S4": ("DARK->BRIGHT", lambda: _entry(), [_free, _dark, _occupy, _bright]),
    "S5": ("BRIGHT->DARK", lambda: _entry(), [_free, _bright, _occupy, _dark]),
    "S6": (
        "UNKNOWN (sensor unavailable)",
        lambda: _entry(),
        [_free, _dark, _occupy, _unknown],
    ),
    "S7": (
        "band with known previous DARK",
        lambda: _entry(),
        [_free, _dark, _occupy, _band],
    ),
    "S8": (
        "manual OFF with override, then a real lux change",
        lambda: _entry(),
        [_free, _dark, _occupy, _manual_off, _bright, _dark],
    ),
    "S8b": (
        "change without user context, then lux change",
        lambda: _entry(),
        [_free, _dark, _occupy, _manual_off_no_user, _bright, _dark],
    ),
    "S2b": (
        "group blocked (sleep), later lux change DARK",
        lambda: _entry(blocking=[AreaStates.SLEEP]),
        [_block, _free, _dark, _occupy, _bright, _dark],
    ),
    "S3b": (
        "activation state missing, later lux change DARK",
        lambda: _entry(states=[AreaStates.EXTENDED]),
        [_free, _dark, _occupy, _bright, _dark],
    ),
}


@pytest.mark.parametrize("key", list(SCENARIOS))
async def test_probe_scenario(probe_devices, key: str) -> None:
    """One scenario per test: fresh Home Assistant, real policy, real group control."""
    name, make_entry, steps = SCENARIOS[key]
    rows = await run_probe(probe_devices, make_entry(), steps)
    assert len(rows) == len(steps), name


# ---------------------------------------------------------------------------
# Characterisation: current behaviour (documents the known faults)
# ---------------------------------------------------------------------------


def _calls_of(rows, step_name):
    return [row["calls"] for row in rows if row["step"] == step_name][-1]


async def _run_named(probe_devices, key):
    name, make_entry, steps = SCENARIOS[key]
    return await run_probe(probe_devices, make_entry(), steps)


async def test_characterise_duplicate_same_direction_calls(probe_devices) -> None:
    """Current: group entity and policy both switch the same light on in one cycle (S1)."""
    rows = await _run_named(probe_devices, "S1")
    calls = _calls_of(rows, "_occupy")
    light_on_targets = [target for service, target in calls if service == "turn_on"]
    assert len(light_on_targets) >= 2


async def test_characterise_manual_off_with_user_context(probe_devices) -> None:
    """Current: user-context switch-off sets FORCE_OFF; policy then stays silent (S8)."""
    rows = await _run_named(probe_devices, "S8")
    manual = next(row for row in rows if row["step"] == "_manual_off")
    assert ("turn_off", "light.mock_light_1") in manual["calls"]
    assert any(
        "override after manual off: force_off" in entry for entry in manual["policy"]
    )
    final_dark = [row for row in rows if row["step"] == "_dark"][-1]
    assert not any(service == "turn_on" for service, _ in final_dark["calls"])


async def test_change_without_user_context_on_a_group_member_is_manual(
    probe_devices,
) -> None:
    """Group rule: any ON/OFF change of a group member that the group did not command is manual.

    The user id is not needed: a change without user context (physical switch, other automation)
    sets the group override (force_off after an OFF). The former policy rule for ungrouped lamps
    no longer exists, so this is the only automatic path.
    """
    rows = await _run_named(probe_devices, "S8b")
    manual = next(row for row in rows if row["step"] == "_manual_off_no_user")
    assert "override after no-user off: force_off" in manual["policy"]


# ---------------------------------------------------------------------------
# Target behaviour (xfail strict): must start passing once the fault is fixed
# ---------------------------------------------------------------------------


async def test_target_no_contradictory_calls_in_one_cycle(probe_devices) -> None:
    """Target: at most one decision per light and cycle; a group block vetoes policy turn_on."""
    rows = await _run_named(probe_devices, "S2b")
    calls = _calls_of(rows, "_dark")
    assert not (
        any(service == "turn_on" for service, _ in calls)
        and any(service == "turn_off" for service, _ in calls)
    )


async def test_regression_group_reevaluates_after_occupancy(probe_devices) -> None:
    """Presence race fix: after the Area becomes occupied the group decides with occupied=True.

    The decision runs on the Area state signal, which is sent after the presence update. The
    dark occupied group therefore switches on in the occupation step.
    """
    rows = await _run_named(probe_devices, "S1")
    occupy = next(row for row in rows if row["step"] == "_occupy")
    assert any(
        service == "turn_on"
        and target
        == f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA.value}_overhead_lights"
        for service, target in occupy["calls"]
    )


async def test_target_single_turn_on_per_light_per_cycle(probe_devices) -> None:
    """Each decision cycle sends at most one automatic turn_on call to the group entity.

    Home Assistant forwards a group call to its members itself; that forward is not a second
    decision. Ungrouped lamps receive no automatic command (policy-only was removed).
    """
    rows = await _run_named(probe_devices, "S1")
    calls = _calls_of(rows, "_occupy")
    group_calls = [
        target
        for service, target in calls
        if service == "turn_on"
        and target
        == f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA.value}_overhead_lights"
    ]
    assert len(group_calls) <= 1
