"""Runtime light ownership: a physical light is automatically controlled by one Area at most.

Real Home Assistant, real config entries and real service events. Automatic calls are the
light calls without a user context; a group call also shows its forwarded member calls, so
"no call reaches the lamp" covers group commands too. No sleeps.

Valid configuration (distinct lamps) is tested first. The stored invalid configuration (one
lamp in two Areas) follows; it is blocked at runtime, never repaired or reassigned.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE, STATE_OFF, STATE_ON
from homeassistant.core import Context, Event, HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_INCLUDE_ENTITIES,
    CONF_OVERHEAD_LIGHTS,
    CONF_OVERHEAD_LIGHTS_ACT_ON,
    CONF_OVERHEAD_LIGHTS_STATES,
    DOMAIN,
    LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
    AreaStates,
)
from custom_components.adaptive_areas.helpers.light_ownership_runtime import (
    conflicted_lights,
    runtime_ownership_conflicts,
)
from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
    shutdown_integration,
)
from tests.mocks import MockLight
from tests import test_light_coordination_regression as regression
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    LUX,
    probe_devices,
)

# Motion sensors of the two Areas (probe entities of the shared test harness).
MOTION = {
    "a": "binary_sensor.probe_motion_kitchen",
    "b": "binary_sensor.probe_motion_living",
}


async def _enable(hass: HomeAssistant, area_id: str) -> None:
    switch = f"switch.adaptive_areas_light_groups_{area_id}_light_control"
    hass.states.async_set(switch, STATE_ON)
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: switch}, blocking=True
    )
    await hass.async_block_till_done()


pytestmark = pytest.mark.usefixtures("probe_devices", "lamps")

LIGHT = "light.mock_light_1"  # kitchen, the shared lamp in the invalid configuration
LIGHT_B = "light.mock_light_2"  # living room
POLICY_LAMP = "light.policy_lamp"  # kitchen, in no automatic light group
KITCHEN_ALL = "light.adaptive_areas_light_groups_kitchen_all_lights"
LIVING_ALL = "light.adaptive_areas_light_groups_living_room_all_lights"
LIVING_OVERHEAD = "light.adaptive_areas_light_groups_living_room_overhead_lights"

AREA = {"a": MockAreaIds.KITCHEN, "b": MockAreaIds.LIVING_ROOM}
EVENTS: list[dict] = []
Step = Callable[[HomeAssistant], Awaitable[None]]


@pytest.fixture(name="lamps")
async def setup_lamps(hass: HomeAssistant, probe_devices) -> None:  # noqa: F811
    """Policy-only lamp in the kitchen and a second living-room lamp (mock_light_1 is kitchen)."""
    await setup_mock_entities(
        hass,
        LIGHT_DOMAIN,
        {
            MockAreaIds.KITCHEN: [
                MockLight(
                    name="policy_lamp", state="off", unique_id="unique_policy_lamp"
                )
            ],
            MockAreaIds.LIVING_ROOM: [
                MockLight(name="mock_light_2", state="off", unique_id="unique_light_2")
            ],
        },
    )


@callback
def _record(event: Event) -> None:
    data = event.data
    if data.get("domain") != "light":
        return
    raw = data.get("service_data", {}).get(ATTR_ENTITY_ID)
    targets = [raw] if isinstance(raw, str) else list(raw or [])
    EVENTS.append(
        {
            "service": data.get("service"),
            "targets": targets,
            "user": bool(event.context and event.context.user_id),
        }
    )


def _area_data(key: str, lights: list[str], overhead: list[str]) -> dict:
    data = get_basic_config_entry_data(AREA[key])
    data[CONF_INCLUDE_ENTITIES] = [MOTION[key], *lights]
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
        CONF_FEATURE_LIGHT_GROUPS: {
            CONF_OVERHEAD_LIGHTS: overhead,
            CONF_OVERHEAD_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
            CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
        },
    }
    return data


def _area_entry(key: str, lights: list[str], overhead: list[str]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data=_area_data(key, lights, overhead),
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX}},
    )


async def _motion(hass: HomeAssistant, key: str, state: str) -> None:
    hass.states.async_set(MOTION[key], state, {"device_class": "motion"})
    await hass.async_block_till_done()


def _occupy(key: str) -> Step:
    async def step(hass: HomeAssistant) -> None:
        await _motion(hass, key, STATE_ON)

    return step


def _free(key: str) -> Step:
    async def step(hass: HomeAssistant) -> None:
        await _motion(hass, key, STATE_OFF)

    return step


async def _dark(hass: HomeAssistant) -> None:
    hass.states.async_set(LUX, "50", {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()


async def _run(
    hass: HomeAssistant,
    entries: dict[str, MockConfigEntry],
    steps: list[Step],
) -> list[list[dict]]:
    """Set up both Areas, run the steps, return the light events of each step."""
    EVENTS.clear()
    for key in ("a", "b"):
        hass.states.async_set(MOTION[key], STATE_OFF, {"device_class": "motion"})
    unsubscribe = hass.bus.async_listen(EVENT_CALL_SERVICE, _record)
    await init_integration(hass, list(entries.values()), areas=list(AREA.values()))
    await _enable(hass, AREA["a"].value)
    await _enable(hass, AREA["b"].value)
    per_step: list[list[dict]] = []
    try:
        for step in steps:
            start = len(EVENTS)
            await step(hass)
            await hass.async_block_till_done()
            per_step.append(list(EVENTS[start:]))
    finally:
        unsubscribe()
        await shutdown_integration(hass, list(entries.values()))
    return per_step


def _automatic(events: list[dict]) -> list[dict]:
    return [e for e in events if not e["user"]]


PHYSICAL = {LIGHT, LIGHT_B, POLICY_LAMP}
OVERHEAD = "light.adaptive_areas_light_groups_kitchen_overhead_lights"
ACCENT = "light.adaptive_areas_light_groups_kitchen_accent_lights"


def _lamp_calls_on(events: list[dict], target: str) -> list[dict]:
    """Automatic turn_on calls whose target is this entity (a lamp or a group)."""
    return [
        e
        for e in _automatic(events)
        if e["service"] == "turn_on" and target in e["targets"]
    ]


def _targets(events: list[dict]) -> set[str]:
    """Physical lights targeted by automatic calls (group entity ids are not lights)."""
    return {t for e in _automatic(events) for t in e["targets"] if t in PHYSICAL}


def _no_automatic_call_to(per_step: list[list[dict]], light: str) -> None:
    assert [
        e for step in per_step for e in _automatic(step) if light in e["targets"]
    ] == []


def _valid(lights_a=(LIGHT,), lights_b=(LIGHT_B,)) -> dict[str, MockConfigEntry]:
    return {
        "a": _area_entry("a", list(lights_a), [lights_a[0]]),
        "b": _area_entry("b", list(lights_b), [lights_b[0]]),
    }


def _shared() -> dict[str, MockConfigEntry]:
    """Build the stored invalid configuration: mock_light_1 is a member of both Areas."""
    return {
        "a": _area_entry("a", [LIGHT], [LIGHT]),
        "b": _area_entry("b", [LIGHT], [LIGHT]),
    }


async def test_distinct_lamps_are_controlled_independently(hass: HomeAssistant) -> None:
    """Valid: two Areas with distinct lamps. Each Area's calls reach only its own lamp."""
    per = await _run(
        hass,
        _valid(),
        [_dark, _occupy("a"), _occupy("b"), _free("b")],
    )
    # The kitchen policy-only lamp is in the kitchen Area too; it is not asserted here.
    assert LIGHT in _targets(per[1]) and LIGHT_B not in _targets(per[1])
    assert LIGHT_B in _targets(per[2]) and LIGHT not in _targets(per[2])
    assert LIGHT_B in _targets(per[3]) and LIGHT not in _targets(per[3])


async def test_stored_shared_lamp_is_detected_by_the_runtime_check(
    hass: HomeAssistant,
) -> None:
    """Invalid, stored: the runtime check names the shared lamp; nothing is repaired."""
    conflicts: list[str] = []

    async def _diagnose(hass_: HomeAssistant) -> None:
        conflicts.append(sorted(conflicted_lights(hass_)))
        found = runtime_ownership_conflicts(hass_)
        assert sorted(c.light for c in found) == [LIGHT]

    await _run(hass, _shared(), [_diagnose])
    assert conflicts == [[LIGHT]]


async def test_no_area_switches_the_shared_lamp_automatically(
    hass: HomeAssistant,
) -> None:
    """Invalid, stored: neither Area's occupation nor its vacancy reaches the shared lamp."""
    per = await _run(
        hass,
        _shared(),
        [_dark, _occupy("a"), _occupy("b"), _free("b"), _free("a")],
    )
    _no_automatic_call_to(per, LIGHT)


async def test_group_command_does_not_bypass_the_block(hass: HomeAssistant) -> None:
    """Invalid, stored: B's CLEAR would call its ALL group, which forwards to the shared lamp.

    The group entity is not called at all, so the forwarded member call cannot happen either.
    """
    per = await _run(hass, _shared(), [_dark, _occupy("b"), _free("b")])
    automatic_group_calls = {t for e in _automatic(per[2]) for t in e["targets"]}
    assert LIVING_ALL not in automatic_group_calls
    assert LIGHT not in _targets(per[2])
    _no_automatic_call_to(per, LIGHT)


async def test_partly_conflicted_group_is_suppressed_as_one_unit(
    hass: HomeAssistant,
) -> None:
    """B's overhead group has one conflicted member: the whole group action is suppressed.

    No call to the group entity and no replacement call to its other member (LIGHT_B).
    """
    entries = {
        "a": _area_entry("a", [LIGHT], [LIGHT]),
        "b": _area_entry("b", [LIGHT, LIGHT_B], [LIGHT, LIGHT_B]),
    }
    per = await _run(hass, entries, [_dark, _occupy("b")])
    automatic = [t for e in _automatic(per[1]) for t in e["targets"]]
    assert LIVING_OVERHEAD not in automatic
    assert LIGHT_B not in automatic
    assert LIGHT not in automatic


async def test_conflict_free_group_gets_exactly_one_call(hass: HomeAssistant) -> None:
    """Unaffected: a conflict-free group gets exactly one automatic call to its own entity."""
    entries = {
        "a": _area_entry("a", [LIGHT], [LIGHT]),
        "b": _area_entry("b", [LIGHT_B], [LIGHT_B]),
    }
    per = await _run(hass, entries, [_dark, _occupy("b")])
    calls = [e for e in _automatic(per[1]) if e["targets"] == [LIVING_OVERHEAD]]
    assert len(calls) == 1
    assert calls[0]["service"] == "turn_on"


async def test_manual_group_command_is_not_blocked(hass: HomeAssistant) -> None:
    """Manual: a user command on a conflicted group is not an automatic action and passes."""

    async def _manual_group_off(hass_: HomeAssistant) -> None:
        await hass_.services.async_call(
            "light",
            "turn_off",
            {ATTR_ENTITY_ID: LIVING_OVERHEAD},
            blocking=True,
            context=Context(user_id=regression.PROBE_USER[0]),
        )
        await hass_.async_block_till_done()

    per = await _run(hass, _shared(), [_dark, _manual_group_off])
    manual = [e for e in per[1] if e["user"]]
    # The group call itself is a user call; its member forward inherits the user context.
    assert ("turn_off", [LIVING_OVERHEAD]) in [
        (e["service"], e["targets"]) for e in manual
    ]


async def test_reload_keeps_the_block(hass: HomeAssistant) -> None:
    """Invalid, stored: after a reload of both Areas the shared lamp is still not commanded."""
    entries: dict[str, MockConfigEntry] = {}

    async def _reload(hass_: HomeAssistant) -> None:
        for entry in entries.values():
            await hass_.config_entries.async_reload(entry.entry_id)
        await hass_.async_block_till_done()
        await _enable(hass_, AREA["a"].value)
        await _enable(hass_, AREA["b"].value)

    entries.update(_shared())
    per = await _run(
        hass,
        entries,
        [_dark, _reload, _occupy("a"), _occupy("b"), _free("b")],
    )
    _no_automatic_call_to(per, LIGHT)


async def test_correcting_the_configuration_restores_regular_control(
    hass: HomeAssistant,
) -> None:
    """After the stored conflict is removed (user edits B), the Area controls its lamp again."""
    entries = _shared()

    async def _correct_b(hass_: HomeAssistant) -> None:
        hass_.config_entries.async_update_entry(
            entries["b"], data=_area_data("b", [LIGHT_B], [LIGHT_B])
        )
        await hass_.config_entries.async_reload(entries["b"].entry_id)
        await hass_.async_block_till_done()
        await _enable(hass_, AREA["b"].value)

    per = await _run(
        hass,
        entries,
        [_dark, _occupy("a"), _correct_b, _free("a"), _occupy("a")],
    )
    _no_automatic_call_to(per[:4], LIGHT)
    assert LIGHT in _targets(per[4])


def test_stored_shared_lamp_is_diagnosed_by_the_ownership_check() -> None:
    """A stored configuration with one lamp in two Areas is named by the ownership check.

    Diagnosis only: the options flow refuses new conflicts, the runtime block stops the
    automatic commands, and nothing in the stored configuration is changed.
    """
    from custom_components.adaptive_areas.const import (
        CONF_ENABLED_FEATURES,
        CONF_FEATURE_LIGHT_GROUPS,
    )
    from custom_components.adaptive_areas.helpers.light_ownership import (
        describe,
        find_ownership_conflicts,
    )

    areas = {}
    for key in ("a", "b"):
        entry = _area_entry(key, [LIGHT], [LIGHT])
        groups = entry.data[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]
        areas[f"{entry.entry_id}/{AREA[key].value}"] = groups
    conflicts = find_ownership_conflicts(areas)
    assert [c.light for c in conflicts] == [LIGHT]
    assert sorted(conflicts[0].areas) == sorted(areas)
    (line,) = describe(conflicts)
    assert line.startswith(f"{LIGHT} is a controllable group member of ")


async def test_same_lamp_in_two_groups_of_one_area_blocks_both_groups(hass) -> None:
    """Invalid, stored: overhead and accent of one Area hold the same lamp.

    The individual groups are the ownership units: both are suppressed as a whole, the policy
    never targets the lamp, and the other Area's lamp stays controllable.
    """
    from custom_components.adaptive_areas.const import (
        CONF_ACCENT_LIGHTS,
        CONF_ACCENT_LIGHTS_ACT_ON,
        CONF_ACCENT_LIGHTS_STATES,
        LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
        AreaStates,
    )

    entries = {
        "a": _area_entry("a", [LIGHT], [LIGHT]),
        "b": _area_entry("b", [LIGHT_B], [LIGHT_B]),
    }
    groups = entries["a"].data[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]
    groups[CONF_ACCENT_LIGHTS] = [LIGHT]
    groups[CONF_ACCENT_LIGHTS_ACT_ON] = [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE]
    groups[CONF_ACCENT_LIGHTS_STATES] = [AreaStates.OCCUPIED]
    per = await _run(hass, entries, [_dark, _occupy("a"), _occupy("b")])
    assert _lamp_calls_on(per[1], LIGHT) == []
    assert _lamp_calls_on(per[1], OVERHEAD) == []
    assert _lamp_calls_on(per[1], ACCENT) == []
    assert _lamp_calls_on(per[2], LIGHT_B)
