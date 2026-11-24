"""Options-flow validation of light ownership (real Config Entries, real Options Flow)."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.config_flow import OptionsFlowHandler
from custom_components.adaptive_areas.helpers.area import get_runtime_areas_for_entry
from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS,
    CONF_SLEEP_LIGHTS,
    DOMAIN,
)
from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light import setup_entities_light_two  # noqa: F401

pytestmark = pytest.mark.usefixtures("entities_light_one", "entities_light_two")

LIGHT_A = "light.mock_light_1"
LIGHT_B = "light.mock_light_2"
GROUP_B = "light.probe_group_b"


def _entry(area: MockAreaIds, groups: dict[str, Any]) -> MockConfigEntry:
    options = get_basic_config_entry_data(area)
    options[CONF_ENABLED_FEATURES] = {CONF_FEATURE_LIGHT_GROUPS: groups}
    return MockConfigEntry(
        domain=DOMAIN, data=get_basic_config_entry_data(area), options=options
    )


async def _flow(hass: HomeAssistant, entry: MockConfigEntry) -> OptionsFlowHandler:
    flow = OptionsFlowHandler()
    flow.hass = hass
    flow.handler = entry.entry_id
    await flow.async_step_init()
    return flow


async def test_conflict_across_two_entries_is_refused_and_nothing_changes(hass) -> None:
    """Living room wants the light kitchen already controls: refused, options unchanged."""
    kitchen = _entry(MockAreaIds.KITCHEN, {CONF_OVERHEAD_LIGHTS: [LIGHT_A]})
    living = _entry(MockAreaIds.LIVING_ROOM, {})
    await init_integration(
        hass, [kitchen, living], areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]
    )
    try:
        flow = await _flow(hass, living)
        before = dict(flow.area_options[CONF_ENABLED_FEATURES])
        result = await flow.async_step_feature_conf_light_groups(
            {CONF_OVERHEAD_LIGHTS: [LIGHT_A]}
        )
        assert result["type"] == "form"
        assert result["errors"] == {
            CONF_OVERHEAD_LIGHTS: "light_ownership_conflict_overhead"
        }
        # The message names the lamp, the owning group and the owning Area (real names).
        assert result["description_placeholders"] == {
            "light": LIGHT_A,
            "area": "kitchen",
        }
        assert dict(flow.area_options[CONF_ENABLED_FEATURES]) == before
    finally:
        await shutdown_integration(hass, [kitchen, living])


async def test_distinct_lights_across_two_entries_are_saved(hass) -> None:
    """Two Areas with different physical lights: the regular case saves without error."""
    kitchen = _entry(MockAreaIds.KITCHEN, {CONF_OVERHEAD_LIGHTS: [LIGHT_A]})
    living = _entry(MockAreaIds.LIVING_ROOM, {})
    await init_integration(
        hass, [kitchen, living], areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]
    )
    try:
        flow = await _flow(hass, living)
        result = await flow.async_step_feature_conf_light_groups(
            {CONF_OVERHEAD_LIGHTS: [LIGHT_B]}
        )
        assert not result.get("errors")
        assert flow.area_options[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS][
            CONF_OVERHEAD_LIGHTS
        ] == [LIGHT_B]
    finally:
        await shutdown_integration(hass, [kitchen, living])


async def test_same_light_in_two_groups_of_one_area_is_rejected(hass) -> None:
    """Overhead and sleep of one Area on the same light: one individual group only, rejected.

    Product rule: a physical light belongs to at most one individual light group, within an
    Area as well. The save is refused with the ownership error and nothing is stored.
    """
    kitchen = _entry(MockAreaIds.KITCHEN, {})
    await init_integration(hass, [kitchen], areas=[MockAreaIds.KITCHEN])
    try:
        flow = await _flow(hass, kitchen)
        result = await flow.async_step_feature_conf_light_groups(
            {CONF_OVERHEAD_LIGHTS: [LIGHT_A], CONF_SLEEP_LIGHTS: [LIGHT_A]}
        )
        # The lamp is already in the sleep group: the message names the other group.
        assert result.get("errors") == {
            CONF_OVERHEAD_LIGHTS: "light_ownership_conflict_sleep"
        }
    finally:
        await shutdown_integration(hass, [kitchen])


async def test_light_group_members_are_resolved_before_comparison(hass) -> None:
    """A resolved light group whose member is controlled by another Area: refused."""
    kitchen = _entry(MockAreaIds.KITCHEN, {CONF_OVERHEAD_LIGHTS: [LIGHT_A]})
    living = _entry(MockAreaIds.LIVING_ROOM, {})
    await init_integration(
        hass, [kitchen, living], areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]
    )
    hass.states.async_set(GROUP_B, "on", {"entity_id": [LIGHT_A, LIGHT_B]})
    try:
        flow = await _flow(hass, living)
        result = await flow.async_step_feature_conf_light_groups(
            {CONF_OVERHEAD_LIGHTS: [GROUP_B]}
        )
        assert result["errors"] == {
            CONF_OVERHEAD_LIGHTS: "light_ownership_conflict_overhead"
        }
    finally:
        await shutdown_integration(hass, [kitchen, living])


async def test_unresolvable_group_is_refused_not_treated_as_conflict_free(hass) -> None:
    """A group without any state cannot be verified: refused with its own error key."""
    kitchen = _entry(MockAreaIds.KITCHEN, {})
    await init_integration(hass, [kitchen], areas=[MockAreaIds.KITCHEN])
    try:
        flow = await _flow(hass, kitchen)
        before = dict(flow.area_options[CONF_ENABLED_FEATURES])
        result = await flow.async_step_feature_conf_light_groups(
            {CONF_OVERHEAD_LIGHTS: ["light.missing_group"]}
        )
        # Neither a state nor a registry entry: an unknown entity id (not a group we can read).
        assert result["errors"] == {CONF_OVERHEAD_LIGHTS: "light_entity_unknown"}
        assert dict(flow.area_options[CONF_ENABLED_FEATURES]) == before
    finally:
        await shutdown_integration(hass, [kitchen])


async def test_conflict_inside_one_container_entry_is_refused(hass) -> None:
    """Two Areas in one Config Entry: the second Area cannot take the first Area's light."""
    kitchen_cfg = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    kitchen_cfg[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT_GROUPS: {CONF_OVERHEAD_LIGHTS: [LIGHT_A]}
    }
    living_cfg = get_basic_config_entry_data(MockAreaIds.LIVING_ROOM)
    living_cfg[CONF_ENABLED_FEATURES] = {}
    container = MockConfigEntry(
        domain=DOMAIN,
        data=get_basic_config_entry_data(MockAreaIds.KITCHEN),
        options={
            CONF_AREAS: {
                MockAreaIds.KITCHEN.value: kitchen_cfg,
                MockAreaIds.LIVING_ROOM.value: living_cfg,
            }
        },
        version=2,
    )
    await init_integration(
        hass, [container], areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]
    )
    try:
        living = next(
            a
            for a in get_runtime_areas_for_entry(hass, container)
            if a.id == MockAreaIds.LIVING_ROOM.value
        )
        flow = OptionsFlowHandler()
        flow.hass = hass
        flow.handler = container.entry_id
        flow.area = living
        flow.area_options = {CONF_ENABLED_FEATURES: {}}
        result = await flow.async_step_feature_conf_light_groups(
            {CONF_OVERHEAD_LIGHTS: [LIGHT_A]}
        )
        assert result["errors"] == {
            CONF_OVERHEAD_LIGHTS: "light_ownership_conflict_overhead"
        }
    finally:
        await shutdown_integration(hass, [container])


async def test_unavailable_known_light_does_not_block_saving(hass) -> None:
    """A known physical light that is temporarily unavailable is not a reason to refuse."""
    kitchen = _entry(MockAreaIds.KITCHEN, {})
    await init_integration(hass, [kitchen], areas=[MockAreaIds.KITCHEN])
    hass.states.async_set(LIGHT_B, "unavailable")
    try:
        flow = await _flow(hass, kitchen)
        result = await flow.async_step_feature_conf_light_groups(
            {CONF_OVERHEAD_LIGHTS: [LIGHT_B]}
        )
        assert not result.get("errors")
    finally:
        await shutdown_integration(hass, [kitchen])


async def test_nested_group_conflict_across_two_entries_is_refused(hass) -> None:
    """A nested group in the other Area reaches the light of this Area: refused."""
    kitchen = _entry(MockAreaIds.KITCHEN, {CONF_OVERHEAD_LIGHTS: [LIGHT_A]})
    living = _entry(MockAreaIds.LIVING_ROOM, {})
    await init_integration(
        hass, [kitchen, living], areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]
    )
    inner = "light.probe_inner"
    outer = "light.probe_outer"
    hass.states.async_set(inner, "on", {"entity_id": [LIGHT_A]})
    hass.states.async_set(outer, "on", {"entity_id": [inner]})
    try:
        flow = await _flow(hass, living)
        result = await flow.async_step_feature_conf_light_groups(
            {CONF_OVERHEAD_LIGHTS: [outer]}
        )
        assert result["errors"] == {
            CONF_OVERHEAD_LIGHTS: "light_ownership_conflict_overhead"
        }
    finally:
        await shutdown_integration(hass, [kitchen, living])
