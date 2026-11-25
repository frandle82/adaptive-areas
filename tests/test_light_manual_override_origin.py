"""B02 regression: only a real manual change sets a group's manual override.

Automatic changes of the Area's own automation (group calls and policy calls, including
the mirrored state of a lamp that a disabled group contains) are not manual. A real user
action (a call with a user context) still sets the override. Real setup, real services.
"""

from __future__ import annotations

import pytest
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_ACCENT_LIGHTS,
    CONF_ACCENT_LIGHTS_ACTIVATION,
    CONF_ENABLED_FEATURES,
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

GROUP = "light.adaptive_areas_light_groups_kitchen_accent_lights"
MOTION = "binary_sensor.probe_motion_kitchen"
SWITCH = "switch.adaptive_areas_light_groups_kitchen_light_control"
LAMP = "light.accent_lamp"

pytestmark = pytest.mark.usefixtures("probe_devices")


async def _setup(hass: HomeAssistant, activation: str | None) -> MockConfigEntry:
    await setup_mock_entities(
        hass,
        LIGHT_DOMAIN,
        {
            MockAreaIds.KITCHEN: [
                MockLight(name="accent_lamp", state="off", unique_id="u_accent")
            ]
        },
    )
    data = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    data[CONF_INCLUDE_ENTITIES] = [MOTION]
    groups: dict = {CONF_ACCENT_LIGHTS: [LAMP]}
    if activation is not None:
        groups[CONF_ACCENT_LIGHTS_ACTIVATION] = activation
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
        CONF_FEATURE_LIGHT_GROUPS: groups,
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX}},
    )
    hass.states.async_set(MOTION, "off", {"device_class": "motion"})
    await init_integration(hass, [entry], areas=[])
    await hass.async_block_till_done()
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    await hass.async_block_till_done()
    hass.states.async_set(LUX, "50", {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()
    return entry


async def _occupy(hass: HomeAssistant) -> None:
    hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion"})
    await hass.async_block_till_done()


async def _free(hass: HomeAssistant) -> None:
    hass.states.async_set(MOTION, STATE_OFF, {"device_class": "motion"})
    await hass.async_block_till_done()


def _override(hass: HomeAssistant) -> bool:
    return bool(hass.states.get(GROUP).attributes.get("manual_override"))


async def test_automatic_group_on_and_off_are_not_manual(hass: HomeAssistant) -> None:
    """Occupied group: automatic ON and automatic OFF (vacancy) set no override."""
    await _setup(hass, activation=LIGHT_GROUP_ACTIVATION_OCCUPIED)
    try:
        await _occupy(hass)
        assert hass.states.get(GROUP).state == STATE_ON
        assert _override(hass) is False
        await _free(hass)
        assert hass.states.get(GROUP).state == STATE_OFF
        assert _override(hass) is False
    finally:
        await shutdown_integration(hass, [])


async def test_user_action_is_manual(hass: HomeAssistant) -> None:
    """A real user switch-off while occupied is still a manual override."""
    await _setup(hass, activation=LIGHT_GROUP_ACTIVATION_OCCUPIED)
    try:
        await _occupy(hass)
        assert hass.states.get(GROUP).state == STATE_ON
        user = await hass.auth.async_create_user("b02-user", group_ids=["system-admin"])
        await hass.services.async_call(
            LIGHT_DOMAIN,
            "turn_off",
            {ATTR_ENTITY_ID: GROUP},
            blocking=True,
            context=Context(user_id=user.id),
        )
        await hass.async_block_till_done()
        assert _override(hass) is True
    finally:
        await shutdown_integration(hass, [])


async def test_initial_occupied_evaluation_is_not_manual(hass: HomeAssistant) -> None:
    """Setup while occupied: the initial automatic ON sets no override."""
    await _setup(hass, activation=LIGHT_GROUP_ACTIVATION_OCCUPIED)
    try:
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion"})
        await hass.async_block_till_done()
        (entry,) = hass.config_entries.async_entries(DOMAIN)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(GROUP).state == STATE_ON
        assert _override(hass) is False
    finally:
        await shutdown_integration(hass, [])


async def test_reload_then_automatic_cycle_is_not_manual(hass: HomeAssistant) -> None:
    """After a reload the automatic ON and OFF still set no override."""
    await _setup(hass, activation=LIGHT_GROUP_ACTIVATION_OCCUPIED)
    try:
        (entry,) = hass.config_entries.async_entries(DOMAIN)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await _occupy(hass)
        assert hass.states.get(GROUP).state == STATE_ON
        assert _override(hass) is False
        await _free(hass)
        assert hass.states.get(GROUP).state == STATE_OFF
        assert _override(hass) is False
    finally:
        await shutdown_integration(hass, [])


async def test_manual_on_in_occupied_area_keeps_override(hass: HomeAssistant) -> None:
    """While occupied: a user switch-off sets the override; a user switch-on keeps it."""
    await _setup(hass, activation=LIGHT_GROUP_ACTIVATION_OCCUPIED)
    try:
        await _occupy(hass)
        user = await hass.auth.async_create_user(
            "b02-user-on", group_ids=["system-admin"]
        )
        ctx = Context(user_id=user.id)
        await hass.services.async_call(
            LIGHT_DOMAIN,
            "turn_off",
            {ATTR_ENTITY_ID: GROUP},
            blocking=True,
            context=ctx,
        )
        await hass.async_block_till_done()
        assert _override(hass) is True
        await hass.services.async_call(
            LIGHT_DOMAIN, "turn_on", {ATTR_ENTITY_ID: GROUP}, blocking=True, context=ctx
        )
        await hass.async_block_till_done()
        assert _override(hass) is True
    finally:
        await shutdown_integration(hass, [])


ALL_GROUP = "light.adaptive_areas_light_groups_kitchen_all_lights"


async def test_user_switching_the_member_lamp_is_manual(hass: HomeAssistant) -> None:
    """A real user switch-off of the lamp (not of the group) while occupied is an override."""
    await _setup(hass, activation=LIGHT_GROUP_ACTIVATION_OCCUPIED)
    try:
        await _occupy(hass)
        assert hass.states.get(GROUP).state == STATE_ON
        user = await hass.auth.async_create_user(
            "b02-member", group_ids=["system-admin"]
        )
        await hass.services.async_call(
            LIGHT_DOMAIN,
            "turn_off",
            {ATTR_ENTITY_ID: LAMP},
            blocking=True,
            context=Context(user_id=user.id),
        )
        await hass.async_block_till_done()
        assert _override(hass) is True
    finally:
        await shutdown_integration(hass, [])


async def test_automatic_all_switch_off_at_clear_is_not_manual(
    hass: HomeAssistant,
) -> None:
    """The ALL group switches its lamps off at final CLEAR: neither group marks an override."""
    await _setup(hass, activation=LIGHT_GROUP_ACTIVATION_OCCUPIED)
    try:
        await _occupy(hass)
        await _free(hass)
        assert hass.states.get(GROUP).state == STATE_OFF
        assert hass.states.get(LAMP).state == STATE_OFF
        assert (
            bool(hass.states.get(ALL_GROUP).attributes.get("manual_override")) is False
        )
        assert _override(hass) is False
    finally:
        await shutdown_integration(hass, [])


async def test_user_context_is_never_registered_as_an_automatic_call(
    hass: HomeAssistant,
) -> None:
    """Only the Area's own automatic calls are registered; a user context is not."""
    from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
    from custom_components.adaptive_areas.helpers.light_origin import (
        request_for_context,
    )

    await _setup(hass, activation=LIGHT_GROUP_ACTIVATION_OCCUPIED)
    try:
        await _occupy(hass)
        (area,) = [a for a in iter_runtime_areas(hass) if not a.is_meta()]
        user = await hass.auth.async_create_user(
            "b02-registry", group_ids=["system-admin"]
        )
        user_ctx = Context(user_id=user.id)
        await hass.services.async_call(
            LIGHT_DOMAIN,
            "turn_off",
            {ATTR_ENTITY_ID: GROUP},
            blocking=True,
            context=user_ctx,
        )
        await hass.async_block_till_done()
        assert request_for_context(area, user_ctx.id) is None
        assert _override(hass) is True
    finally:
        await shutdown_integration(hass, [])
