"""B01: a nested native light group is one indivisible unit.

A group that would switch an excluded lamp through its own members is never switched
automatically, and the save of such a configuration is refused. Real config entry,
real setup; the nested group is a light state with an `entity_id` list (the native form).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.area_config import async_update_area
from custom_components.adaptive_areas.const import (
    CONF_ACCENT_LIGHTS,
    CONF_ACCENT_LIGHTS_ACTIVATION,
    CONF_ENABLED_FEATURES,
    CONF_EXCLUDE_ENTITIES,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_INCLUDE_ENTITIES,
    DOMAIN,
    LIGHT_GROUP_ACTIVATION_OCCUPIED,
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

MOTION = "binary_sensor.probe_motion_kitchen"
LAMP = "light.accent_lamp"
NESTED = "light.nested_accent"
GROUP = "light.adaptive_areas_light_groups_kitchen_accent_lights"
SWITCH = "switch.adaptive_areas_light_groups_kitchen_light_control"


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


async def _setup(
    hass: HomeAssistant, members: list[str], exclude: list[str]
) -> tuple[MockConfigEntry, list[dict]]:
    await setup_mock_entities(
        hass,
        LIGHT_DOMAIN,
        {
            MockAreaIds.KITCHEN: [
                MockLight(name="accent_lamp", state="off", unique_id="u_accent")
            ]
        },
    )
    # The native nested group: a light state that lists its members in `entity_id`.
    hass.states.async_set(NESTED, "off", {"entity_id": [LAMP]})
    data = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    data[CONF_INCLUDE_ENTITIES] = [MOTION]
    data[CONF_EXCLUDE_ENTITIES] = exclude
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
        CONF_FEATURE_LIGHT_GROUPS: {
            CONF_ACCENT_LIGHTS: members,
            CONF_ACCENT_LIGHTS_ACTIVATION: LIGHT_GROUP_ACTIVATION_OCCUPIED,
        },
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX}},
    )
    calls: list[dict] = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, lambda event: _record(event, calls))
    hass.states.async_set(MOTION, "off", {"device_class": "motion"})
    await init_integration(hass, [entry], areas=[])
    await hass.async_block_till_done()
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    hass.states.async_set(LUX, "50", {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()
    hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion"})
    await hass.async_block_till_done()
    return entry, calls


async def test_nested_group_without_exclusion_is_controlled(
    hass: HomeAssistant,
) -> None:
    """The nested group is the configured member; the group entity forwards to its lamps."""
    _entry, calls = await _setup(hass, [NESTED], [])
    try:
        group = hass.states.get(GROUP)
        assert group is not None and group.attributes["lights"] == [NESTED]
        assert any(NESTED in c["targets"] and not c["user"] for c in calls)
    finally:
        await shutdown_integration(hass, [])


async def test_nested_group_that_switches_an_excluded_lamp_is_not_controlled(
    hass: HomeAssistant,
) -> None:
    """Excluded lamp inside a nested group: the whole group is not switched, no member call."""
    _entry, calls = await _setup(hass, [NESTED], [LAMP])
    try:
        assert hass.states.get(GROUP) is None
        automatic = [c for c in calls if not c["user"]]
        assert not any(
            NESTED in c["targets"] or LAMP in c["targets"] for c in automatic
        )
    finally:
        await shutdown_integration(hass, [])


async def test_saving_a_nested_group_with_an_excluded_lamp_is_refused(
    hass: HomeAssistant,
) -> None:
    """The configuration is refused at save; nothing changes."""
    await _setup(hass, [], [])
    try:
        (entry,) = hass.config_entries.async_entries(DOMAIN)
        before = dict(entry.options)
        with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
            errors = await async_update_area(
                hass,
                entry,
                {
                    CONF_EXCLUDE_ENTITIES: [LAMP],
                    CONF_ENABLED_FEATURES: {
                        CONF_FEATURE_LIGHT_GROUPS: {CONF_ACCENT_LIGHTS: [NESTED]}
                    },
                },
            )
        assert CONF_ENABLED_FEATURES in errors
        assert LAMP in errors[CONF_ENABLED_FEATURES]
        assert dict(entry.options) == before
    finally:
        await shutdown_integration(hass, [])


async def test_unloaded_area_sends_no_automatic_group_call(hass: HomeAssistant) -> None:
    """Unload removes the automation: a later occupation sends no automatic call."""
    entry, calls = await _setup(hass, [NESTED], [])
    try:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        calls.clear()
        hass.states.async_set(MOTION, "off", {"device_class": "motion"})
        await hass.async_block_till_done()
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion"})
        await hass.async_block_till_done()
        assert not [
            c
            for c in calls
            if not c["user"] and (NESTED in c["targets"] or GROUP in c["targets"])
        ]
    finally:
        await shutdown_integration(hass, [])
