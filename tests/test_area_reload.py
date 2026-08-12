"""Test for the logic on automatically reloading areas."""

from datetime import datetime
import logging

import pytest

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_registry import (
    EVENT_ENTITY_REGISTRY_UPDATED,
    _EventEntityRegistryUpdatedData_CreateRemove,
    _EventEntityRegistryUpdatedData_Update,
)

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    AdaptiveAreasEvents,
    DATA_AREA_OBJECT,
    MODULE_DATA,
)

from tests.const import MockAreaIds
from tests.helpers import init_integration, shutdown_integration
from tests.mocks import MockBinarySensor

_LOGGER = logging.getLogger(__name__)

# Constants

NORMAL_AREAS = [
    MockAreaIds.KITCHEN.value,
    MockAreaIds.BACKYARD.value,
    MockAreaIds.MASTER_BEDROOM.value,
]
REGULAR_META_AREAS = [
    MockAreaIds.GLOBAL.value,
    MockAreaIds.INTERIOR.value,
    MockAreaIds.EXTERIOR.value,
]
FLOOR_META_AREAS = [
    MockAreaIds.GROUND_LEVEL.value,
    MockAreaIds.FIRST_FLOOR.value,
    MockAreaIds.SECOND_FLOOR.value,
]
ALL_AREAS = NORMAL_AREAS + REGULAR_META_AREAS + FLOOR_META_AREAS


@pytest.fixture(autouse=True)
def immediate_meta_reload(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run coalesced meta-area reload callbacks on the next loop iteration."""

    def _call_later(_hass, _delay, callback):
        handle = hass.loop.call_soon(callback, None)
        return handle.cancel

    monkeypatch.setattr(
        "custom_components.adaptive_areas.base.adaptive.async_call_later", _call_later
    )


# Helpers


def get_config_entry_by_area_name(hass: HomeAssistant, area_name: str) -> str | None:
    """Fetch config_entry_id from an area's name."""
    ma_data = hass.data[MODULE_DATA]
    for entry_id, entry_data in ma_data.items():
        area_data = entry_data[DATA_AREA_OBJECT]
        if area_data.id == area_name.lower():
            return entry_id

    return None


def get_entry_by_area_name(hass: HomeAssistant, area_name: str) -> AdaptiveArea | None:
    """Fetch AdaptiveArea object from an area's name."""
    config_entry_id = get_config_entry_by_area_name(hass, area_name)
    if not config_entry_id:
        return None

    ma_data = hass.data[MODULE_DATA]

    if config_entry_id not in ma_data:
        return None

    return ma_data[config_entry_id][DATA_AREA_OBJECT]


# Tests


async def test_reload_on_entity_area_change(
    hass: HomeAssistant,
    entities_binary_sensor_motion_all_areas_with_meta: dict[
        MockAreaIds, list[MockBinarySensor]
    ],
    _setup_integration_all_areas_with_meta,
) -> None:
    """Test that only corresponding areas reload when an entity changes state."""

    # Check all areas' timestamp
    area_timestamp_map: dict[str, datetime] = {}
    for area in NORMAL_AREAS:
        area_object = get_entry_by_area_name(hass, area)
        assert area_object
        area_timestamp_map[area] = area_object.timestamp

    # Simulate entity changing area_id (this triggers "all areas reload" logic in AdaptiveArea)
    event_data: _EventEntityRegistryUpdatedData_Update = {
        "action": "update",
        "entity_id": "sensor.test",
        "changes": {"area_id": MockAreaIds.KITCHEN.value},
    }
    hass.bus.async_fire(EVENT_ENTITY_REGISTRY_UPDATED, event_data)
    await hass.async_block_till_done()

    await hass.async_block_till_done()

    # Check all areas' timestamp against the previous map
    for area in NORMAL_AREAS:
        area_object = get_entry_by_area_name(hass, area)
        assert area_object
        if area == MockAreaIds.KITCHEN.value:
            assert area_timestamp_map[area] != area_object.timestamp
        else:
            assert area_timestamp_map[area] == area_object.timestamp


async def test_meta_reload_from_single_reload(
    hass: HomeAssistant,
    entities_binary_sensor_motion_all_areas_with_meta: dict[
        MockAreaIds, list[MockBinarySensor]
    ],
    _setup_integration_all_areas_with_meta,
) -> None:
    """Test that the corresponding meta-areas reload when a child area reloads."""

    # Check all areas' timestamp
    area_timestamp_map: dict[str, datetime] = {}
    for area in ALL_AREAS:
        area_object = get_entry_by_area_name(hass, area)
        assert area_object
        area_timestamp_map[area] = area_object.timestamp

    # Simulate entity changing area_id (this triggers "all areas reload" logic in AdaptiveArea)
    kitchen_motion_sensor_id = entities_binary_sensor_motion_all_areas_with_meta[
        MockAreaIds.KITCHEN
    ][0].entity_id

    event_data: _EventEntityRegistryUpdatedData_CreateRemove = {
        "action": "remove",
        "entity_id": kitchen_motion_sensor_id,
    }
    hass.bus.async_fire(EVENT_ENTITY_REGISTRY_UPDATED, event_data)
    await hass.async_block_till_done()

    def _assert_has_reloaded(area_name: str):
        area_object = get_entry_by_area_name(hass, area_name)
        assert area_object
        assert area_object.timestamp != area_timestamp_map[area_name]

    def _assert_has_not_reloaded(area_name: str):
        area_object = get_entry_by_area_name(hass, area_name)
        assert area_object
        assert area_object.timestamp == area_timestamp_map[area_name]

    await hass.async_block_till_done()

    # Check corresponding area reloaded
    _assert_has_reloaded(MockAreaIds.KITCHEN.value)

    # Check corresponding meta-areas reloaded
    _assert_has_reloaded(MockAreaIds.INTERIOR.value)
    _assert_has_reloaded(MockAreaIds.GLOBAL.value)
    _assert_has_reloaded(MockAreaIds.FIRST_FLOOR.value)

    # Check other areas didn't reload
    _assert_has_not_reloaded(MockAreaIds.MASTER_BEDROOM.value)
    _assert_has_not_reloaded(MockAreaIds.BACKYARD.value)
    _assert_has_not_reloaded(MockAreaIds.EXTERIOR.value)
    _assert_has_not_reloaded(MockAreaIds.SECOND_FLOOR.value)
    _assert_has_not_reloaded(MockAreaIds.GROUND_LEVEL.value)


async def test_start_event_does_not_reload_regular_area(
    hass: HomeAssistant,
    basic_config_entry,
) -> None:
    """Do not perform a second full setup when Home Assistant starts."""
    hass.set_state(CoreState.starting)
    loaded: list[tuple] = []

    @callback
    def _loaded(*args) -> None:
        loaded.append(args)

    remove = async_dispatcher_connect(hass, AdaptiveAreasEvents.AREA_LOADED, _loaded)
    await init_integration(hass, [basic_config_entry])
    area = get_entry_by_area_name(hass, basic_config_entry.data["id"])
    assert area is not None
    initial_timestamp = area.timestamp

    # Exercise the deferred startup path independently of integration setup,
    # which moves the test Home Assistant instance to running.
    loaded.clear()
    hass.set_state(CoreState.not_running)
    area.finalize_init()

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    current_area = get_entry_by_area_name(hass, basic_config_entry.data["id"])
    assert current_area is area
    assert current_area.timestamp == initial_timestamp
    assert len(loaded) == 1
    assert loaded[0][-1] is True

    remove()
    await shutdown_integration(hass, [basic_config_entry])


async def test_running_area_emits_area_loaded_once(
    hass: HomeAssistant, basic_config_entry
) -> None:
    """Running startup path dispatches exactly once on event loop."""
    loaded: list[tuple] = []

    @callback
    def _loaded(*args) -> None:
        loaded.append(args)

    remove = async_dispatcher_connect(hass, AdaptiveAreasEvents.AREA_LOADED, _loaded)
    await init_integration(hass, [basic_config_entry])
    await hass.async_block_till_done()

    assert len(loaded) == 1
    assert loaded[0][-1] is False

    remove()
    await shutdown_integration(hass, [basic_config_entry])


async def test_adaptive_entity_reload_is_idempotent(
    hass: HomeAssistant,
    _setup_integration_basic,
) -> None:
    """Repeated registry refreshes must not duplicate generated entities."""
    area = get_entry_by_area_name(hass, MockAreaIds.KITCHEN.value)
    assert area is not None

    area.load_adaptive_entities()
    first_load = {
        domain: list(entities) for domain, entities in area.adaptive_entities.items()
    }
    area.load_adaptive_entities()

    assert area.adaptive_entities == first_load
