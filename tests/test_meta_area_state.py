"""Test for meta area changes and how the system handles it."""

import logging
from types import SimpleNamespace

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import (
    DATA_AREA_OBJECT,
    MODULE_DATA,
    AreaStates,
)
from custom_components.adaptive_areas.helpers.meta_summary import meta_cleaning_summary

from tests.const import MockAreaIds
from tests.helpers import assert_state
from tests.mocks import MockBinarySensor

_LOGGER = logging.getLogger(__name__)


# Tests


async def test_meta_area_primary_state_change(
    hass: HomeAssistant,
    entities_binary_sensor_motion_all_areas_with_meta: dict[
        MockAreaIds, list[MockBinarySensor]
    ],
    _setup_integration_all_areas_with_meta,
) -> None:
    """Test primary state changes between meta areas."""

    # Test initialization
    for (
        area_id,
        entity_list,
    ) in entities_binary_sensor_motion_all_areas_with_meta.items():
        assert entity_list is not None
        assert len(entity_list) == 1

        entity_ids = [entity.entity_id for entity in entity_list]

        # Check area sensor is created
        area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{area_id}_area_state"
        area_binary_sensor = hass.states.get(area_sensor_entity_id)
        assert area_binary_sensor is not None
        assert area_binary_sensor.state == STATE_OFF
        assert set(entity_ids).issubset(
            set(area_binary_sensor.attributes["presence_sensors"])
        )
        assert AreaStates.CLEAR in area_binary_sensor.attributes["states"]

    # Entity Ids
    kitchen_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.KITCHEN.value}_area_state"
    backyard_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.BACKYARD.value}_area_state"
    master_bedroom_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.MASTER_BEDROOM.value}_area_state"
    interior_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.INTERIOR.value}_area_state"
    exterior_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.EXTERIOR.value}_area_state"
    global_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.GLOBAL.value}_area_state"
    ground_level_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.GROUND_LEVEL.value}_area_state"
    first_floor_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.FIRST_FLOOR.value}_area_state"
    second_floor_area_sensor_entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{MockAreaIds.SECOND_FLOOR.value}_area_state"

    # Toggle interior area and check interior meta area
    kitchen_motion_sensor_id = entities_binary_sensor_motion_all_areas_with_meta[
        MockAreaIds.KITCHEN
    ][0].entity_id
    hass.states.async_set(kitchen_motion_sensor_id, STATE_ON)
    await hass.async_block_till_done()

    kitchen_motion_sensor_state = hass.states.get(kitchen_motion_sensor_id)
    assert_state(kitchen_motion_sensor_state, STATE_ON)

    kitchen_area_sensor_state = hass.states.get(kitchen_area_sensor_entity_id)
    assert_state(kitchen_area_sensor_state, STATE_ON)

    interior_area_sensor_state = hass.states.get(interior_area_sensor_entity_id)
    assert_state(interior_area_sensor_state, STATE_ON)

    exterior_area_sensor_state = hass.states.get(exterior_area_sensor_entity_id)
    assert_state(exterior_area_sensor_state, STATE_OFF)

    global_area_sensor_state = hass.states.get(global_area_sensor_entity_id)
    assert_state(global_area_sensor_state, STATE_ON)
    assert interior_area_sensor_state.attributes["child_area_count"] == 6
    assert interior_area_sensor_state.attributes["occupied_area_count"] == 1
    assert interior_area_sensor_state.attributes["clear_area_count"] == 5
    assert exterior_area_sensor_state.attributes["child_area_count"] == 2
    assert global_area_sensor_state.attributes["child_area_count"] == 8
    assert global_area_sensor_state.attributes["occupied_area_count"] == 1

    hass.states.async_set(kitchen_motion_sensor_id, STATE_OFF)
    await hass.async_block_till_done()

    kitchen_motion_sensor_state = hass.states.get(kitchen_motion_sensor_id)
    assert_state(kitchen_motion_sensor_state, STATE_OFF)

    kitchen_area_sensor_state = hass.states.get(kitchen_area_sensor_entity_id)
    assert_state(kitchen_area_sensor_state, STATE_OFF)

    interior_area_sensor_state = hass.states.get(interior_area_sensor_entity_id)
    assert_state(interior_area_sensor_state, STATE_OFF)

    exterior_area_sensor_state = hass.states.get(exterior_area_sensor_entity_id)
    assert_state(exterior_area_sensor_state, STATE_OFF)

    global_area_sensor_state = hass.states.get(global_area_sensor_entity_id)
    assert_state(global_area_sensor_state, STATE_OFF)

    # Toggle exterior area
    backyard_motion_sensor_id = entities_binary_sensor_motion_all_areas_with_meta[
        MockAreaIds.BACKYARD
    ][0].entity_id
    hass.states.async_set(backyard_motion_sensor_id, STATE_ON)
    await hass.async_block_till_done()

    backyard_motion_sensor_state = hass.states.get(backyard_motion_sensor_id)
    assert_state(backyard_motion_sensor_state, STATE_ON)

    backyard_area_sensor_state = hass.states.get(backyard_area_sensor_entity_id)
    assert_state(backyard_area_sensor_state, STATE_ON)

    interior_area_sensor_state = hass.states.get(interior_area_sensor_entity_id)
    assert_state(interior_area_sensor_state, STATE_OFF)

    exterior_area_sensor_state = hass.states.get(exterior_area_sensor_entity_id)
    assert_state(exterior_area_sensor_state, STATE_ON)

    global_area_sensor_state = hass.states.get(global_area_sensor_entity_id)
    assert_state(global_area_sensor_state, STATE_ON)

    hass.states.async_set(backyard_motion_sensor_id, STATE_OFF)
    await hass.async_block_till_done()

    backyard_motion_sensor_state = hass.states.get(kitchen_motion_sensor_id)
    assert_state(backyard_motion_sensor_state, STATE_OFF)

    backyard_area_sensor_state = hass.states.get(backyard_area_sensor_entity_id)
    assert_state(backyard_area_sensor_state, STATE_OFF)

    interior_area_sensor_state = hass.states.get(interior_area_sensor_entity_id)
    assert_state(interior_area_sensor_state, STATE_OFF)

    exterior_area_sensor_state = hass.states.get(exterior_area_sensor_entity_id)
    assert_state(exterior_area_sensor_state, STATE_OFF)

    global_area_sensor_state = hass.states.get(global_area_sensor_entity_id)
    assert_state(global_area_sensor_state, STATE_OFF)

    # Floors
    ground_level_area_sensor_state = hass.states.get(ground_level_area_sensor_entity_id)
    assert_state(ground_level_area_sensor_state, STATE_OFF)

    hass.states.async_set(backyard_motion_sensor_id, STATE_ON)
    await hass.async_block_till_done()

    ground_level_area_sensor_state = hass.states.get(ground_level_area_sensor_entity_id)
    assert_state(ground_level_area_sensor_state, STATE_ON)

    hass.states.async_set(backyard_motion_sensor_id, STATE_OFF)
    await hass.async_block_till_done()

    ground_level_area_sensor_state = hass.states.get(ground_level_area_sensor_entity_id)
    assert_state(ground_level_area_sensor_state, STATE_OFF)

    first_floor_area_sensor_state = hass.states.get(first_floor_area_sensor_entity_id)
    assert_state(first_floor_area_sensor_state, STATE_OFF)

    hass.states.async_set(kitchen_motion_sensor_id, STATE_ON)
    await hass.async_block_till_done()

    first_floor_area_sensor_state = hass.states.get(first_floor_area_sensor_entity_id)
    assert_state(first_floor_area_sensor_state, STATE_ON)

    hass.states.async_set(kitchen_motion_sensor_id, STATE_OFF)
    await hass.async_block_till_done()

    first_floor_area_sensor_state = hass.states.get(first_floor_area_sensor_entity_id)
    assert_state(first_floor_area_sensor_state, STATE_OFF)

    second_floor_area_sensor_state = hass.states.get(second_floor_area_sensor_entity_id)
    assert_state(second_floor_area_sensor_state, STATE_OFF)

    hass.states.async_set(master_bedroom_area_sensor_entity_id, STATE_ON)
    await hass.async_block_till_done()
    assert_state(hass.states.get(second_floor_area_sensor_entity_id), STATE_ON)
    hass.states.async_set(master_bedroom_area_sensor_entity_id, STATE_OFF)
    await hass.async_block_till_done()
    assert_state(hass.states.get(second_floor_area_sensor_entity_id), STATE_OFF)


async def test_meta_cleaning_summary_scopes_and_most_due_are_deterministic(
    hass: HomeAssistant,
    _setup_integration_all_areas_with_meta,
) -> None:
    """Meta cleaning summaries reuse child trackers and respect hierarchy scope."""
    areas = {
        runtime[DATA_AREA_OBJECT].id: runtime[DATA_AREA_OBJECT]
        for runtime in hass.data[MODULE_DATA].values()
    }
    assessments = {
        MockAreaIds.KITCHEN: {
            "due": False,
            "cleaning_state": "soon_due",
            "score": 90,
            "overdue_minutes": 0,
        },
        MockAreaIds.LIVING_ROOM: {
            "due": True,
            "cleaning_state": "due",
            "score": 100,
            "overdue_minutes": 5,
        },
        MockAreaIds.BACKYARD: {
            "due": True,
            "cleaning_state": "overdue",
            "score": 100,
            "overdue_minutes": 20,
        },
    }
    for area_id, assessment in assessments.items():
        areas[area_id].room_usage = SimpleNamespace(assessment=assessment)

    interior = meta_cleaning_summary(areas[MockAreaIds.INTERIOR])
    exterior = meta_cleaning_summary(areas[MockAreaIds.EXTERIOR])
    global_summary = meta_cleaning_summary(areas[MockAreaIds.GLOBAL])
    first_floor = meta_cleaning_summary(areas[MockAreaIds.FIRST_FLOOR])

    assert interior["cleaning_due_areas"] == [MockAreaIds.LIVING_ROOM]
    assert interior["cleaning_soon_due_areas"] == [MockAreaIds.KITCHEN]
    assert interior["most_due_area"] == MockAreaIds.LIVING_ROOM
    assert exterior["cleaning_overdue_areas"] == [MockAreaIds.BACKYARD]
    assert global_summary["cleaning_due_count"] == 2
    assert global_summary["most_due_area"] == MockAreaIds.BACKYARD
    assert global_summary["most_overdue_minutes"] == 20
    assert first_floor["cleaning_due_count"] == 1
    assert first_floor["cleaning_soon_due_count"] == 1
    for area_id in assessments:
        areas[area_id].room_usage = None
