"""Tests for the persistent adaptive Cleaning Tracker."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from homeassistant.const import ATTR_AREA_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from custom_components.adaptive_areas.const import (
    ATTR_SCORE,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_ROOM_USAGE,
    CONF_PRESENCE_MINUTES_TO_DUE,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
    SERVICE_MARK_CLEANED,
    SERVICE_RESET,
    SERVICE_SET_SCORE,
    AdaptiveAreasEvents,
)

from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)


def _entry(area_id: MockAreaIds, threshold_minutes: float) -> MockConfigEntry:
    """Create a current-version Cleaning Tracker config entry."""
    data = get_basic_config_entry_data(area_id)
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_ROOM_USAGE: {CONF_PRESENCE_MINUTES_TO_DUE: threshold_minutes}
    }
    return MockConfigEntry(domain=DOMAIN, data=data, version=2, minor_version=8)


def _score_entity(area_id: MockAreaIds) -> str:
    return f"sensor.adaptive_areas_room_usage_{area_id}"


def _due_entity(area_id: MockAreaIds) -> str:
    return f"binary_sensor.adaptive_areas_room_usage_{area_id}_cleaning_due"


async def test_two_areas_accumulate_independently_and_services_support_multiple(
    hass: HomeAssistant,
    freezer,
) -> None:
    """Parallel Areas do not share counters and services accept Area lists."""
    kitchen_entry = _entry(MockAreaIds.KITCHEN, 2)
    living_entry = _entry(MockAreaIds.LIVING_ROOM, 2)
    entries = [kitchen_entry, living_entry]
    await init_integration(
        hass,
        entries,
        areas=[MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM],
    )
    kitchen = hass.data[MODULE_DATA][kitchen_entry.entry_id][DATA_AREA_OBJECT]
    living = hass.data[MODULE_DATA][living_entry.entry_id][DATA_AREA_OBJECT]
    assert kitchen.room_usage is not None
    assert living.room_usage is not None

    kitchen.states = ["occupied"]
    async_dispatcher_send(
        hass, AdaptiveAreasEvents.AREA_STATE_CHANGED, kitchen.id, ([], [])
    )
    freezer.tick(40)
    await kitchen.room_usage._async_periodic_update(dt_util.utcnow())
    assert kitchen.room_usage.assessment["cumulative_presence_seconds"] == 40
    assert living.room_usage.assessment["cumulative_presence_seconds"] == 0

    freezer.tick(80)
    await kitchen.room_usage._async_periodic_update(dt_util.utcnow())
    assert kitchen.room_usage.assessment["score"] == 100
    assert hass.states.get(_due_entity(MockAreaIds.KITCHEN)).state == STATE_ON
    assert hass.states.get(_due_entity(MockAreaIds.LIVING_ROOM)).state == STATE_OFF

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_SCORE,
        {ATTR_AREA_ID: [kitchen.id, living.id], ATTR_SCORE: 75},
        blocking=True,
    )
    assert hass.states.get(_score_entity(MockAreaIds.KITCHEN)).state == "75.0"
    assert hass.states.get(_score_entity(MockAreaIds.LIVING_ROOM)).state == "75.0"

    await hass.services.async_call(
        DOMAIN,
        SERVICE_MARK_CLEANED,
        {ATTR_AREA_ID: [kitchen.id, living.id]},
        blocking=True,
    )
    for area_id in (MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM):
        state = hass.states.get(_score_entity(area_id))
        assert state is not None
        assert state.state == "0.0"
        assert state.attributes["last_cleaned"] is not None

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_SCORE,
        {ATTR_AREA_ID: [kitchen.id, living.id], ATTR_SCORE: 100},
        blocking=True,
    )
    for area_id in (MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM):
        assert hass.states.get(_due_entity(area_id)).state == STATE_ON

    await hass.services.async_call(
        DOMAIN,
        SERVICE_RESET,
        {ATTR_AREA_ID: [kitchen.id, living.id]},
        blocking=True,
    )
    for area_id in (MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM):
        state = hass.states.get(_score_entity(area_id))
        assert state is not None
        assert state.state == "0.0"
        assert state.attributes["last_cleaned"] is None
        assert hass.states.get(_due_entity(area_id)).state == STATE_OFF
    assert await kitchen.room_usage._store.async_load() is None
    assert await living.room_usage._store.async_load() is None

    await shutdown_integration(hass, entries)


async def test_persistence_and_clean_unload_reload(
    hass: HomeAssistant,
) -> None:
    """A reload restores state and retires the old engine's callbacks."""
    entry = _entry(MockAreaIds.KITCHEN, 10)
    await init_integration(hass, [entry])
    old_area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    old_engine = old_area.room_usage
    assert old_engine is not None

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_SCORE,
        {ATTR_AREA_ID: [old_area.id], ATTR_SCORE: 37.5},
        blocking=True,
    )
    assert old_engine.assessment["cumulative_presence_seconds"] == 225

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    new_area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert new_area is not old_area
    assert new_area.room_usage is not old_engine
    assert old_engine._remove_listener is None
    assert old_engine._remove_interval is None
    restored = hass.states.get(_score_entity(MockAreaIds.KITCHEN))
    assert restored is not None
    assert restored.state == "37.5"
    assert restored.attributes["cumulative_presence_seconds"] == 225
    assert hass.services.has_service(DOMAIN, SERVICE_MARK_CLEANED)

    await shutdown_integration(hass, [entry])
    assert not hass.services.has_service(DOMAIN, SERVICE_MARK_CLEANED)


async def test_set_score_validation(hass: HomeAssistant) -> None:
    """The service rejects scores outside the public 0..100 contract."""
    entry = _entry(MockAreaIds.KITCHEN, 100)
    await init_integration(hass, [entry])

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_SCORE,
            {ATTR_AREA_ID: [MockAreaIds.KITCHEN], ATTR_SCORE: 101},
            blocking=True,
        )

    area = hass.data[MODULE_DATA][entry.entry_id][DATA_AREA_OBJECT]
    assert area.room_usage is not None
    original_score = area.room_usage.assessment["score"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_SCORE,
            {
                ATTR_AREA_ID: [MockAreaIds.KITCHEN, "missing_area"],
                ATTR_SCORE: 50,
            },
            blocking=True,
        )
    assert area.room_usage.assessment["score"] == original_score

    await shutdown_integration(hass, [entry])
