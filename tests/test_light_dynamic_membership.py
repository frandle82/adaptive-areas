"""Dynamic group membership: a runtime change of a native light group, no configuration change.

Real Home Assistant, real config entries, real service events. The native group is a light state
with an `entity_id` list (the native form used by the nested-group tests). Its members change at
runtime; the stored Adaptive Areas configuration does not. The ownership runtime check reads the
current members on every automatic command, so the change is detected without a reload.

Areas: kitchen (A) owns its native group NESTED (member LAMP_A). Living room (B) owns LIGHT_B.
Dining room (C) owns LAMP_C and is never affected.

Step 1 adds LIGHT_B to NESTED: NESTED now contains a lamp owned by B. That is a conflict.
Automatic commands for the conflicted lamp and for A's group are suppressed; C keeps working;
manual service calls still work. Removing the membership again restores the regular control.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_CALL_SERVICE,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import Context, Event, HomeAssistant, callback
import pytest
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
from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
    shutdown_integration,
)
from tests.mocks import MockLight
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    LUX,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

NESTED = "light.nested_kitchen_overhead"
KITCHEN_OVERHEAD = "light.adaptive_areas_light_groups_kitchen_overhead_lights"
LAMP_A = "light.mock_light_1"  # kitchen, member of the native group
LIGHT_B = "light.mock_light_2"  # living room, owned by B
LAMP_C = "light.mock_light_3"  # dining room, unaffected
MOTION = {
    "a": "binary_sensor.probe_motion_kitchen",
    "b": "binary_sensor.probe_motion_living",
    "c": "binary_sensor.probe_motion_dining",
}
AREA = {
    "a": MockAreaIds.KITCHEN,
    "b": MockAreaIds.LIVING_ROOM,
    "c": MockAreaIds.DINING_ROOM,
}

Step = Callable[[HomeAssistant], Any]


@callback
def _record(event: Event, sink: list[dict]) -> None:
    data = event.data
    if data.get("domain") != LIGHT_DOMAIN:
        return
    raw = data.get("service_data", {}).get(ATTR_ENTITY_ID)
    targets = [raw] if isinstance(raw, str) else list(raw or [])
    sink.append(
        {
            "service": data.get("service"),
            "targets": targets,
            "user": bool(event.context and event.context.user_id),
        }
    )


def _area_entry(key: str, lights: list[str], overhead: list[str]) -> MockConfigEntry:
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
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX}},
    )


def _entries() -> dict[str, MockConfigEntry]:
    return {
        "a": _area_entry("a", [LAMP_A], [NESTED]),
        "b": _area_entry("b", [LIGHT_B], [LIGHT_B]),
        "c": _area_entry("c", [LAMP_C], [LAMP_C]),
    }


def _members(hass: HomeAssistant, members: list[str]) -> None:
    """Runtime change of the native group membership: only the group state changes."""
    hass.states.async_set(NESTED, STATE_OFF, {"entity_id": members})


def _occupy(key: str) -> Step:
    async def step(hass: HomeAssistant) -> None:
        hass.states.async_set(MOTION[key], STATE_ON, {"device_class": "motion"})
        await hass.async_block_till_done()

    return step


def _free(key: str) -> Step:
    async def step(hass: HomeAssistant) -> None:
        hass.states.async_set(MOTION[key], STATE_OFF, {"device_class": "motion"})
        await hass.async_block_till_done()

    return step


def _dark_step(hass: HomeAssistant) -> Step:
    async def step(hass: HomeAssistant) -> None:
        hass.states.async_set(LUX, "50", {"unit_of_measurement": "lx"})
        await hass.async_block_till_done()

    return step


def _membership(members: list[str]) -> Step:
    async def step(hass: HomeAssistant) -> None:
        _members(hass, members)
        await hass.async_block_till_done()

    return step


async def _enable(hass: HomeAssistant) -> None:
    for key in AREA:
        switch = f"switch.adaptive_areas_light_groups_{AREA[key].value}_light_control"
        hass.states.async_set(switch, STATE_ON)
        await hass.services.async_call(
            "switch", "turn_on", {ATTR_ENTITY_ID: switch}, blocking=True
        )
    await hass.async_block_till_done()


async def _run(hass: HomeAssistant, steps: list[Step]) -> tuple[list[list[dict]], dict]:
    """Set up three Areas, run the steps; return the light events per step and listener counts."""
    await setup_mock_entities(
        hass,
        LIGHT_DOMAIN,
        {
            MockAreaIds.KITCHEN: [
                MockLight(name="mock_light_1", state="off", unique_id="u_l1")
            ],
            MockAreaIds.LIVING_ROOM: [
                MockLight(name="mock_light_2", state="off", unique_id="u_l2")
            ],
            MockAreaIds.DINING_ROOM: [
                MockLight(name="mock_light_3", state="off", unique_id="u_l3")
            ],
        },
    )
    for key in AREA:
        hass.states.async_set(MOTION[key], STATE_OFF, {"device_class": "motion"})
    hass.states.async_set(NESTED, STATE_OFF, {"entity_id": [LAMP_A]})
    entries = _entries()
    calls: list[dict] = []
    unsubscribe = hass.bus.async_listen(EVENT_CALL_SERVICE, lambda e: _record(e, calls))
    await init_integration(hass, list(entries.values()), areas=list(AREA.values()))
    await hass.async_block_till_done()
    await _enable(hass)
    listeners_before = dict(hass.bus.async_listeners())
    per_step: list[list[dict]] = []
    try:
        for step in steps:
            start = len(calls)
            await step(hass)
            await hass.async_block_till_done()
            per_step.append(list(calls[start:]))
        listeners_after = dict(hass.bus.async_listeners())
    finally:
        unsubscribe()
        await shutdown_integration(hass, list(entries.values()))
    return per_step, {"before": listeners_before, "after": listeners_after}


def _automatic(events: list[dict]) -> list[dict]:
    return [e for e in events if not e["user"]]


def _auto_targets(events: list[dict], service: str | None = None) -> list[str]:
    return [
        t
        for e in _automatic(events)
        if service is None or e["service"] == service
        for t in e["targets"]
    ]


async def test_baseline_group_is_controlled_before_the_membership_change(
    hass: HomeAssistant,
) -> None:
    """Before the change: A's native group gets exactly one automatic ON (no conflict yet)."""
    per, _ = await _run(hass, [_dark_step(hass), _occupy("a")])
    assert _auto_targets(per[1], "turn_on").count(NESTED) == 1


async def test_membership_change_creates_a_conflict_and_is_blocked_at_runtime(
    hass: HomeAssistant,
) -> None:
    """A native group gains a lamp of B: A's group and B's lamp get no automatic command.

    Real service calls are checked, not only the final light states.
    """
    steps = [
        _dark_step(hass),
        _occupy("a"),  # baseline: one ON for NESTED (before the change)
        _free("a"),  # regular clear OFF from A's ALL group
        _membership([LAMP_A, LIGHT_B]),  # runtime change, no config change
        _occupy("a"),  # A's group: suppressed as a unit
        _free("a"),
        _occupy("b"),  # B's lamp is conflicted: no automatic command
        _occupy("c"),  # C is unaffected
    ]
    per, _ = await _run(hass, steps)
    assert NESTED in _auto_targets(per[1], "turn_on")
    after_change = [e for step in per[4:] for e in _automatic(step)]
    assert not any(NESTED in e["targets"] for e in after_change)
    assert not any(LIGHT_B in e["targets"] for e in after_change)
    assert LAMP_C in _auto_targets(per[7], "turn_on")


async def test_conflict_is_detected_without_reload_or_configuration_write(
    hass: HomeAssistant,
) -> None:
    """The production rule sees the conflict from the live group state alone.

    Checked inside the running integration: before the change no lamp is conflicted, after the
    change LIGHT_B is conflicted, and the stored entries are unchanged (no update, no reload).
    """
    from custom_components.adaptive_areas.helpers.light_ownership_runtime import (
        conflicted_lights,
    )

    seen: list[frozenset[str]] = []

    def _probe() -> Step:
        async def step(hass_: HomeAssistant) -> None:
            seen.append(conflicted_lights(hass_))

        return step

    steps = [_probe(), _membership([LAMP_A, LIGHT_B]), _probe()]
    await _run(hass, steps)
    assert seen[0] == frozenset()
    assert LIGHT_B in seen[1]


async def test_manual_service_call_still_works_during_the_conflict(
    hass: HomeAssistant,
) -> None:
    """A user action reaches the conflicted lamp; the manual path is not blocked."""

    async def manual(hass_: HomeAssistant) -> None:
        user = await hass_.auth.async_create_user(
            "dynamic-membership-user", group_ids=["system-admin"]
        )
        await hass_.services.async_call(
            LIGHT_DOMAIN,
            "turn_on",
            {ATTR_ENTITY_ID: LIGHT_B},
            blocking=True,
            context=Context(user_id=user.id),
        )
        await hass_.async_block_till_done()

    steps = [_dark_step(hass), _membership([LAMP_A, LIGHT_B]), manual]
    per, _ = await _run(hass, steps)
    manual_calls = [e for e in per[2] if e["user"] and LIGHT_B in e["targets"]]
    assert manual_calls, "the manual service call must reach the lamp"


async def test_removing_the_conflict_restores_regular_control(
    hass: HomeAssistant,
) -> None:
    """After the conflicting membership is removed, a regular occupation switches A's group on."""
    steps = [
        _dark_step(hass),
        _membership([LAMP_A, LIGHT_B]),
        _occupy("a"),
        _free("a"),
        _membership([LAMP_A]),
        _occupy("a"),
    ]
    per, _ = await _run(hass, steps)
    assert NESTED not in _auto_targets(per[2], "turn_on")
    assert _auto_targets(per[5], "turn_on").count(NESTED) == 1


async def test_all_off_respects_the_actual_ownership(hass: HomeAssistant) -> None:
    """A's clear during the conflict never switches the conflicted lamp of B automatically."""
    steps = [
        _dark_step(hass),
        _membership([LAMP_A, LIGHT_B]),
        _occupy("a"),
        _free("a"),
        _occupy("b"),
        _free("b"),
    ]
    per, _ = await _run(hass, steps)
    assert LIGHT_B not in _auto_targets(per[3], "turn_off")
    assert LIGHT_B not in _auto_targets(per[5], "turn_off")


async def test_no_listener_timer_or_registry_is_added_by_the_change(
    hass: HomeAssistant,
) -> None:
    """The membership change adds no bus listeners; the state change is the only input."""
    steps = [_dark_step(hass), _membership([LAMP_A, LIGHT_B]), _occupy("c")]
    _per, counts = await _run(hass, steps)
    assert counts["before"] == counts["after"]


async def test_dashboard_marks_only_the_conflicted_group_as_ownership_blocked(
    hass: HomeAssistant,
) -> None:
    """The public control_path payload shows ownership_blocked for A's group only, live."""
    from custom_components.adaptive_areas.dashboard import build_light_runtime_status
    from custom_components.adaptive_areas.helpers.area import iter_runtime_areas

    seen: dict[str, dict] = {}

    def _capture(label: str) -> Step:
        async def step(hass_: HomeAssistant) -> None:
            for area in iter_runtime_areas(hass_):
                if area.slug in (AREA["a"].value, AREA["c"].value):
                    seen[f"{label}:{area.slug}"] = build_light_runtime_status(
                        hass_, area
                    )["light"]["control_path"]

        return step

    steps = [_capture("before"), _membership([LAMP_A, LIGHT_B]), _capture("after")]
    await _run(hass, steps)

    native = [
        group
        for group in seen["after:kitchen"]["groups"]
        if group["entity_id"] == KITCHEN_OVERHEAD
    ]
    assert native, "the kitchen overhead group must appear in the control path"
    assert native[0]["ownership_blocked"] is True
    assert all(
        group["ownership_blocked"] is False
        for group in seen["before:kitchen"]["groups"]
    )
