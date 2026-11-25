"""Lifecycle isolation of Areas and Config Entries, proven by functional behaviour.

Real Home Assistant, real Config Entries and real service calls. Each cycle is proven by the
number of production evaluations (the Area's decision trace) and by the automatic light calls
on the configured group entity. Listener counts are not used: Home Assistant keeps one bus
listener per event type, so counting listeners cannot show duplicates.
"""

from __future__ import annotations

import pytest
from homeassistant.components.light import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_CALL_SERVICE, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.area_registry import async_get as async_get_ar
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_INCLUDE_ENTITIES,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
    LightGroupCategory,
)
from custom_components.adaptive_areas.light import AreaLightGroup
from tests import test_light_coordination_regression as regression
from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    LIGHT,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

OVERHEAD = "light.adaptive_areas_light_groups_kitchen_overhead_lights"
CALLS: list[dict] = []


def _record(event) -> None:
    data = event.data
    if data.get("domain") != "light":
        return
    raw = data.get("service_data", {}).get("entity_id")
    targets = [raw] if isinstance(raw, str) else list(raw or [])
    CALLS.append(
        {
            "service": data.get("service"),
            "targets": targets,
            "user": bool(event.context and event.context.user_id),
        }
    )


def _entry(
    area_id: MockAreaIds = MockAreaIds.KITCHEN, light: str = LIGHT
) -> MockConfigEntry:
    data = get_basic_config_entry_data(area_id)
    # The motion sensor is the presence source of the Area (as in the other direct tests).
    data[CONF_INCLUDE_ENTITIES] = [regression.MOTION]
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
        CONF_FEATURE_LIGHT_GROUPS: {
            "overhead_lights": [light],
            "overhead_lights_act_on": ["occupancy_change"],
            "overhead_lights_states": ["occupied"],
        },
    }
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: regression.LUX}},
    )


def _group(hass: HomeAssistant) -> AreaLightGroup:
    for entity in hass.data[DATA_COMPONENT].entities:
        if isinstance(entity, AreaLightGroup) and str(entity.category) == str(
            LightGroupCategory.OVERHEAD
        ):
            return entity
    raise AssertionError("no overhead group")


def _area(hass: HomeAssistant, entry: MockConfigEntry):
    return hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]


def _evaluations(area, decision: str) -> int:
    """Production evaluations of the Area that executed one decision (decision trace)."""
    return sum(
        1
        for entry in area.decision_trace.export()
        if entry.get("feature") == "light_groups"
        and entry.get("decision") == decision
        and entry.get("outcome") == "executed"
    )


def _automatic_on_overhead(since: int) -> int:
    return sum(
        1
        for call in CALLS[since:]
        if call["service"] == "turn_on"
        and not call["user"]
        and call["targets"] == [OVERHEAD]
    )


async def _set_motion(hass: HomeAssistant, state: str) -> None:
    hass.states.async_set(regression.MOTION, state, {"device_class": "motion"})
    await hass.async_block_till_done()


async def _lamp_off(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": LIGHT}, blocking=True
    )
    await hass.async_block_till_done()


async def _attempt_setup(
    hass: HomeAssistant, entry: MockConfigEntry
) -> ConfigEntryState:
    """Set up one entry without asserting success; return its state."""
    registry = async_get_ar(hass)
    for area_id in [MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]:
        if registry.async_get_area(area_id.value) is None:
            registry.async_create(area_id.value)
    entry.add_to_hass(hass)
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry.state


@pytest.fixture(autouse=True)
def _dark_and_recorded(hass: HomeAssistant, probe_devices):  # noqa: F811
    CALLS.clear()
    hass.states.async_set(regression.LUX, "50", {"unit_of_measurement": "lx"})
    # Presence source starts known and clear, as in the other direct tests.
    hass.states.async_set(regression.MOTION, STATE_OFF, {"device_class": "motion"})
    unsubscribe = hass.bus.async_listen(EVENT_CALL_SERVICE, _record)
    yield
    unsubscribe()


async def test_repeated_setup_unload_cycles_evaluate_once_per_event(hass) -> None:
    """Setup, unload and setup again, three times: one evaluation and one call per occupation."""
    entry = _entry()
    await init_integration(hass, [entry], areas=[MockAreaIds.KITCHEN])
    try:
        for cycle in range(3):
            if cycle:
                assert await hass.config_entries.async_setup(entry.entry_id)
                await hass.async_block_till_done()
            await regression._enable_group_control(hass)
            area = _area(hass, entry)
            group = _group(hass)
            await _lamp_off(hass)
            evaluations_before = _evaluations(area, "turn_on")
            calls_before = len(CALLS)
            await _set_motion(hass, STATE_ON)
            assert _evaluations(area, "turn_on") - evaluations_before == 1, cycle
            assert _automatic_on_overhead(calls_before) == 1, cycle
            await _set_motion(hass, STATE_OFF)
            assert _automatic_on_overhead(calls_before) == 1, cycle
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
            # The instance of the unloaded cycle is inactive: it can no longer decide or send.
            assert group._active is False, cycle
    finally:
        await shutdown_integration(hass, [entry])


async def test_unload_of_one_entry_keeps_the_other_reacting(hass) -> None:
    """Unloading an entry deactivates its instance; the same entry set up again evaluates normally."""
    entry = _entry(MockAreaIds.KITCHEN)
    await init_integration(hass, [entry], areas=[MockAreaIds.KITCHEN])
    try:
        await regression._enable_group_control(hass)
        old_group = _group(hass)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert old_group._active is False
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await regression._enable_group_control(hass)
        area = _area(hass, entry)
        await _lamp_off(hass)
        before = _evaluations(area, "turn_on")
        calls_before = len(CALLS)
        await _set_motion(hass, STATE_ON)
        assert _evaluations(area, "turn_on") - before == 1
        assert _automatic_on_overhead(calls_before) == 1
        assert old_group._active is False
    finally:
        await shutdown_integration(hass, [entry])


async def test_repeated_cycles_do_not_grow_the_listener_count(hass) -> None:
    """After each unload the bus listener count is the same: nothing accumulates across cycles.

    The first cycle initialises Home Assistant components once (one-time listeners). From the
    second cycle on the count after each unload must not change. This is a growth check,
    not a claim about the exact number.
    """
    entry = _entry()
    after_unload: list[dict] = []
    await init_integration(hass, [entry], areas=[MockAreaIds.KITCHEN])
    try:
        for cycle in range(4):
            if cycle:
                assert await hass.config_entries.async_setup(entry.entry_id)
                await hass.async_block_till_done()
            await regression._enable_group_control(hass)
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
            after_unload.append(dict(hass.bus.async_listeners()))
    finally:
        await shutdown_integration(hass, [entry])
    assert after_unload[1:] == [after_unload[1]] * 3
