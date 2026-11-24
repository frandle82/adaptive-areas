"""Panel save path and runtime check for light ownership inside the GlobalEntry (real HA)."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.area_config import async_update_area
from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_ENTRY,
    CONF_OVERHEAD_LIGHTS,
    CONF_SLEEP_LIGHTS,
    DOMAIN,
)
from custom_components.adaptive_areas.helpers.light_ownership_runtime import (
    runtime_ownership_conflicts,
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
KITCHEN = MockAreaIds.KITCHEN.value
LIVING = MockAreaIds.LIVING_ROOM.value


def _area(area: MockAreaIds, groups: dict) -> dict:
    cfg = get_basic_config_entry_data(area)
    cfg[CONF_ENABLED_FEATURES] = {CONF_FEATURE_LIGHT_GROUPS: groups}
    return cfg


def _container(areas: dict) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_AREAS: areas},
        version=2,
        minor_version=11,
    )


def _light_groups(entry: MockConfigEntry, area_id: str) -> dict:
    cfg = entry.options[CONF_AREAS][area_id]
    return cfg.get(CONF_ENABLED_FEATURES, {}).get(CONF_FEATURE_LIGHT_GROUPS, {})


async def test_panel_save_refuses_a_light_of_another_area_and_keeps_the_config(
    hass: HomeAssistant,
) -> None:
    """Living room cannot take the kitchen's overhead lamp: refused, nothing stored."""
    container = _container(
        {
            KITCHEN: _area(MockAreaIds.KITCHEN, {CONF_OVERHEAD_LIGHTS: [LIGHT_A]}),
            LIVING: _area(MockAreaIds.LIVING_ROOM, {}),
        }
    )
    await init_integration(
        hass, [container], areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]
    )
    try:
        before = dict(container.options[CONF_AREAS][LIVING])
        details: dict = {}
        errors = await async_update_area(
            hass,
            LIVING,
            {
                CONF_ENABLED_FEATURES: {
                    CONF_FEATURE_LIGHT_GROUPS: {CONF_OVERHEAD_LIGHTS: [LIGHT_A]}
                }
            },
            details,
        )
        assert errors == {CONF_OVERHEAD_LIGHTS: "light_ownership_conflict_overhead"}
        assert details == {CONF_OVERHEAD_LIGHTS: {"light": LIGHT_A, "area": KITCHEN}}
        assert dict(container.options[CONF_AREAS][LIVING]) == before
    finally:
        await shutdown_integration(hass, [container])


async def test_panel_save_accepts_distinct_lights_across_areas(
    hass: HomeAssistant,
) -> None:
    """Distinct lamps in two Areas of one GlobalEntry are saved."""
    container = _container(
        {
            KITCHEN: _area(MockAreaIds.KITCHEN, {CONF_OVERHEAD_LIGHTS: [LIGHT_A]}),
            LIVING: _area(MockAreaIds.LIVING_ROOM, {}),
        }
    )
    await init_integration(
        hass, [container], areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]
    )
    try:
        errors = await async_update_area(
            hass,
            LIVING,
            {
                CONF_ENABLED_FEATURES: {
                    CONF_FEATURE_LIGHT_GROUPS: {CONF_OVERHEAD_LIGHTS: [LIGHT_B]}
                }
            },
        )
        assert errors == {}
        assert _light_groups(container, LIVING)[CONF_OVERHEAD_LIGHTS] == [LIGHT_B]
    finally:
        await shutdown_integration(hass, [container])


async def test_panel_save_refuses_a_second_group_of_the_same_area(
    hass: HomeAssistant,
) -> None:
    """Overhead and sleep of one Area on the same lamp: refused, names the other group."""
    container = _container({KITCHEN: _area(MockAreaIds.KITCHEN, {})})
    await init_integration(hass, [container], areas=[MockAreaIds.KITCHEN])
    try:
        details: dict = {}
        errors = await async_update_area(
            hass,
            KITCHEN,
            {
                CONF_ENABLED_FEATURES: {
                    CONF_FEATURE_LIGHT_GROUPS: {
                        CONF_OVERHEAD_LIGHTS: [LIGHT_A],
                        CONF_SLEEP_LIGHTS: [LIGHT_A],
                    }
                }
            },
            details,
        )
        assert errors == {CONF_OVERHEAD_LIGHTS: "light_ownership_conflict_sleep"}
        assert details[CONF_OVERHEAD_LIGHTS]["light"] == LIGHT_A
        assert _light_groups(container, KITCHEN) == {}
    finally:
        await shutdown_integration(hass, [container])


async def test_runtime_check_sees_stored_areas_of_the_global_entry(
    hass: HomeAssistant,
) -> None:
    """A stored conflict between two Areas of the GlobalEntry is a runtime conflict."""
    container = _container(
        {
            KITCHEN: _area(MockAreaIds.KITCHEN, {CONF_OVERHEAD_LIGHTS: [LIGHT_A]}),
            LIVING: _area(MockAreaIds.LIVING_ROOM, {CONF_OVERHEAD_LIGHTS: [LIGHT_A]}),
        }
    )
    await init_integration(
        hass, [container], areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM]
    )
    try:
        conflicts = runtime_ownership_conflicts(hass)
        assert [c.light for c in conflicts] == [LIGHT_A]
    finally:
        await shutdown_integration(hass, [container])


async def test_panel_save_refuses_a_light_home_assistant_does_not_know(
    hass: HomeAssistant,
) -> None:
    """Ownership cannot be verified for an unknown lamp: the light group save is refused."""
    container = _container({KITCHEN: _area(MockAreaIds.KITCHEN, {})})
    await init_integration(hass, [container], areas=[MockAreaIds.KITCHEN])
    try:
        details: dict = {}
        errors = await async_update_area(
            hass,
            KITCHEN,
            {
                CONF_ENABLED_FEATURES: {
                    CONF_FEATURE_LIGHT_GROUPS: {
                        CONF_OVERHEAD_LIGHTS: ["light.unknown_lamp"]
                    }
                }
            },
            details,
        )
        assert errors == {CONF_OVERHEAD_LIGHTS: "light_entity_unknown"}
        assert details[CONF_OVERHEAD_LIGHTS] == {
            "light": "light.unknown_lamp",
            "area": "",
        }
        assert _light_groups(container, KITCHEN) == {}
    finally:
        await shutdown_integration(hass, [container])


async def test_unrelated_save_ignores_a_stored_light_that_is_unknown(
    hass: HomeAssistant,
) -> None:
    """An unrelated Area edit is not blocked by a stored lamp that no longer exists."""
    container = _container(
        {KITCHEN: _area(MockAreaIds.KITCHEN, {CONF_OVERHEAD_LIGHTS: ["light.gone"]})}
    )
    await init_integration(hass, [container], areas=[MockAreaIds.KITCHEN])
    try:
        errors = await async_update_area(
            hass, KITCHEN, {"include_entities": ["sensor.after"]}
        )
        assert errors == {}
        assert container.options[CONF_AREAS][KITCHEN]["include_entities"] == [
            "sensor.after"
        ]
    finally:
        await shutdown_integration(hass, [container])
