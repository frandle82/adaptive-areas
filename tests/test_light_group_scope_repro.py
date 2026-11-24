"""B01 regression: an explicitly configured accent-group lamp is controlled (Option C).

The lamp is registered in another HA Area, so the HA-Area lookup does not find it. The
configured group membership alone must make it a group member. Real config entry, real
setup, real service events. Automatic calls carry no user context.
"""

from __future__ import annotations

import pytest
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

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

ACCENT_GROUP = "light.adaptive_areas_light_groups_kitchen_accent_lights"
MOTION = "binary_sensor.probe_motion_kitchen"
LAMP = "light.accent_lamp"

pytestmark = pytest.mark.usefixtures("probe_devices")


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
    hass: HomeAssistant,
    lamp_area: MockAreaIds | None,
    *,
    exclude: list[str] | None = None,
    include: list[str] | None = None,
    group_lamp: str = LAMP,
    enable_control: bool = True,
    activation: str | None = LIGHT_GROUP_ACTIVATION_OCCUPIED,
) -> list[dict]:
    if lamp_area is not None:
        await setup_mock_entities(
            hass,
            LIGHT_DOMAIN,
            {
                lamp_area: [
                    MockLight(name="accent_lamp", state="off", unique_id="u_accent")
                ]
            },
        )
    data = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    data[CONF_INCLUDE_ENTITIES] = [MOTION, *(include or [])]
    if exclude:
        data[CONF_EXCLUDE_ENTITIES] = exclude
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
        CONF_FEATURE_LIGHT_GROUPS: {
            CONF_ACCENT_LIGHTS: [group_lamp],
            **({CONF_ACCENT_LIGHTS_ACTIVATION: activation} if activation else {}),
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
    if enable_control:
        switch = "switch.adaptive_areas_light_groups_kitchen_light_control"
        await hass.services.async_call(
            "switch", "turn_on", {ATTR_ENTITY_ID: switch}, blocking=True
        )
        await hass.async_block_till_done()
    hass.states.async_set(LUX, "50", {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()
    hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion"})
    await hass.async_block_till_done()
    return calls


async def test_configured_lamp_outside_area_is_controlled(hass: HomeAssistant) -> None:
    """The configured lamp is in another HA Area; the group still controls it."""
    calls = await _setup(hass, MockAreaIds.LIVING_ROOM)
    try:
        group = hass.states.get(ACCENT_GROUP)
        assert group is not None
        assert group.attributes["lights"] == [LAMP]
        assert group.state == STATE_ON
        automatic = [c for c in calls if not c["user"]]
        assert any(
            c["service"] == "turn_on" and ACCENT_GROUP in c["targets"]
            for c in automatic
        )
    finally:
        await shutdown_integration(hass, [])


async def test_excluded_configured_lamp_is_not_a_member(hass: HomeAssistant) -> None:
    """An explicit exclusion wins over the group configuration."""
    await _setup(hass, MockAreaIds.KITCHEN, exclude=[LAMP])
    try:
        group = hass.states.get(ACCENT_GROUP)
        assert group is None or LAMP not in group.attributes.get("lights", [])
    finally:
        await shutdown_integration(hass, [])


async def test_missing_configured_lamp_creates_no_member(hass: HomeAssistant) -> None:
    """A configured entity that does not exist is not a group member."""
    await _setup(hass, None, group_lamp="light.does_not_exist")
    try:
        group = hass.states.get(ACCENT_GROUP)
        assert group is None
    finally:
        await shutdown_integration(hass, [])


async def test_configured_lamp_also_in_include_entities(hass: HomeAssistant) -> None:
    """Being in include_entities as well changes nothing: one member, one group call."""
    calls = await _setup(hass, MockAreaIds.LIVING_ROOM, include=[LAMP])
    try:
        group = hass.states.get(ACCENT_GROUP)
        assert group is not None and group.attributes["lights"] == [LAMP]
        automatic = [c for c in calls if not c["user"]]
        assert any(ACCENT_GROUP in c["targets"] for c in automatic)
    finally:
        await shutdown_integration(hass, [])


async def test_group_keeps_control_after_reload(hass: HomeAssistant) -> None:
    """A reload creates a fresh group that still controls the configured lamp."""
    calls = await _setup(hass, MockAreaIds.LIVING_ROOM)
    try:
        (entry,) = hass.config_entries.async_entries(DOMAIN)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        calls.clear()
        hass.states.async_set(MOTION, "off", {"device_class": "motion"})
        await hass.async_block_till_done()
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion"})
        await hass.async_block_till_done()
        group = hass.states.get(ACCENT_GROUP)
        assert group is not None and group.state == STATE_ON
        assert any(ACCENT_GROUP in c["targets"] and not c["user"] for c in calls)
    finally:
        await shutdown_integration(hass, [])


async def test_all_group_switches_off_configured_lamp_at_clear(
    hass: HomeAssistant,
) -> None:
    """At final CLEAR the ALL group switches the configured lamp off, never on."""
    calls = await _setup(hass, MockAreaIds.LIVING_ROOM)
    try:
        all_group = "light.adaptive_areas_light_groups_kitchen_all_lights"
        assert hass.states.get(all_group).attributes["lights"] == [LAMP]
        calls.clear()
        hass.states.async_set(MOTION, "off", {"device_class": "motion"})
        await hass.async_block_till_done()
        automatic = [c for c in calls if not c["user"]]
        assert any(
            c["service"] == "turn_off" and LAMP in c["targets"] for c in automatic
        )
        assert not any(
            c["service"] == "turn_on" and all_group in c["targets"] for c in automatic
        )
    finally:
        await shutdown_integration(hass, [])


async def test_diagnosis_shows_group_control_not_policy_only(
    hass: HomeAssistant,
) -> None:
    """D07: an active native group is shown as the control path; the lamp is not policy-only."""
    from custom_components.adaptive_areas.dashboard import build_light_runtime_status
    from custom_components.adaptive_areas.helpers.area import iter_runtime_areas

    await _setup(hass, MockAreaIds.LIVING_ROOM)
    try:
        kitchen = next(a for a in iter_runtime_areas(hass) if a.slug == "kitchen")
        control = build_light_runtime_status(hass, kitchen)["light"]["control_path"]
        assert control["group_active"] is True
        accent = next(g for g in control["groups"] if g["category"] == "accent_lights")
        assert accent["entity_id"] == ACCENT_GROUP
        assert accent["members"] == [LAMP]
        assert LAMP not in control["policy_only"]["entity_ids"]
    finally:
        await shutdown_integration(hass, [])
