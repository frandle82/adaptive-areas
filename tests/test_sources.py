"""Tests for domain-specific presence source discovery and evaluation."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_ON, STATE_OPEN, STATE_PLAYING
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.const import (
    CONF_INCLUDE_ENTITIES,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    DOMAIN,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.helpers.sources import is_presence_source_active

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)


@pytest.mark.parametrize(
    ("entity_id", "state", "expected"),
    [
        ("binary_sensor.motion", STATE_ON, True),
        ("binary_sensor.door", STATE_OPEN, True),
        ("binary_sensor.motion", "off", False),
        ("media_player.tv", STATE_PLAYING, True),
        ("media_player.tv", STATE_ON, True),
        ("media_player.tv", "paused", False),
        ("remote.tv", STATE_ON, True),
        ("remote.tv", STATE_PLAYING, False),
        ("device_tracker.phone", "home", False),
        ("device_tracker.phone", "not_home", False),
        ("device_tracker.phone", "work", False),
        ("device_tracker.phone", "living_room", False),
        ("sensor.arbitrary", STATE_ON, False),
        ("binary_sensor.motion", "unknown", False),
        ("binary_sensor.motion", None, False),
    ],
)
def test_presence_source_states_are_domain_specific(
    hass: HomeAssistant, entity_id, state, expected
) -> None:
    """Only states with defined semantics for the source domain are active."""
    assert is_presence_source_active(hass, entity_id, state) is expected


def test_presence_source_helper_accepts_state_objects(hass: HomeAssistant) -> None:
    """The shared evaluator accepts Home Assistant State objects."""
    state = State("media_player.tv", STATE_PLAYING)

    assert is_presence_source_active(hass, state.entity_id, state)


async def test_device_tracker_uses_only_deterministic_area_states(
    hass: HomeAssistant,
) -> None:
    """Trackers count as sources but only their exact room state is active."""
    tracker_id = "device_tracker.phone"
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    async_get_entity_registry(hass).async_get_or_create(
        "device_tracker",
        "test",
        "phone",
        suggested_object_id="phone",
        config_entry=source_entry,
    )
    hass.states.async_set(tracker_id, "home")

    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = [tracker_id]
    data[CONF_PRESENCE_DEVICE_PLATFORMS] = ["device_tracker"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data,
        version=AdaptiveConfigEntryVersion.MAJOR,
        minor_version=AdaptiveConfigEntryVersion.MINOR,
    )
    await init_integration(hass, [entry])

    area_state = hass.states.get(
        "binary_sensor.adaptive_areas_presence_tracking_kitchen_area_state"
    )
    assert area_state is not None
    assert area_state.state == "off"
    assert area_state.attributes["presence_sensors"] == [tracker_id]
    assert area_state.attributes["configured_source_count"] == 1
    assert area_state.attributes["available_source_count"] == 1
    assert area_state.attributes["active_source_count"] == 0
    assert area_state.attributes["active_sources"] == []

    for non_room_state in ("not_home", "work", "Work", "school"):
        hass.states.async_set(tracker_id, non_room_state)
        await hass.async_block_till_done()
        assert hass.states.get(area_state.entity_id).state == "off"
        assert hass.states.get(area_state.entity_id).attributes["active_sources"] == []

    hass.states.async_set(tracker_id, DEFAULT_MOCK_AREA.value)
    await hass.async_block_till_done()
    active = hass.states.get(area_state.entity_id)
    assert active.state == "on"
    assert active.attributes["active_sources"] == [tracker_id]
    assert active.attributes["active_source_count"] == 1

    hass.states.async_set(tracker_id, DEFAULT_MOCK_AREA.value.title())
    await hass.async_block_till_done()
    by_name = hass.states.get(area_state.entity_id)
    assert by_name.state == "on"
    assert by_name.attributes["active_sources"] == [tracker_id]

    await shutdown_integration(hass, [entry])
