"""Regression coverage for presence source selection (include/exclude/device class)."""

from types import SimpleNamespace

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    AREA_TYPE_INTERIOR,
    CONF_EXCLUDE_ENTITIES,
    CONF_GLOBAL_ENTRY,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_NAME,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    CONF_TYPE,
    DOMAIN,
)


def _area(hass, name: str, extra: dict):
    area_entry = async_get_area_registry(hass).async_create(name)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_GLOBAL_ENTRY: True}, options={})
    entry.add_to_hass(hass)
    config = {
        CONF_ID: area_entry.id,
        CONF_NAME: name,
        CONF_TYPE: AREA_TYPE_INTERIOR,
        CONF_PRESENCE_DEVICE_PLATFORMS: ["binary_sensor"],
        CONF_PRESENCE_SENSOR_DEVICE_CLASS: [BinarySensorDeviceClass.MOTION],
        **extra,
    }
    area = AdaptiveArea(
        hass,
        SimpleNamespace(id=area_entry.id, name=name, icon=None, floor_id=None),
        entry,
        config,
    )
    return area


def test_included_state_only_motion_sensor_is_presence_source(hass) -> None:
    """A user-selected sensor without registry entry must count when included."""
    hass.states.async_set(
        "binary_sensor.template_motion",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.MOTION},
    )
    area = _area(
        hass,
        "Flur",
        {CONF_INCLUDE_ENTITIES: ["binary_sensor.template_motion"]},
    )

    assert "binary_sensor.template_motion" in area.get_presence_sensors()


def test_excluded_entity_is_not_presence_source(hass) -> None:
    """Exclude wins over include for presence sources."""
    hass.states.async_set(
        "binary_sensor.template_motion",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.MOTION},
    )
    area = _area(
        hass,
        "Bad",
        {
            CONF_INCLUDE_ENTITIES: ["binary_sensor.template_motion"],
            CONF_EXCLUDE_ENTITIES: ["binary_sensor.template_motion"],
        },
    )

    assert "binary_sensor.template_motion" not in area.get_presence_sensors()


def test_explicit_include_bypasses_device_class_filter(hass) -> None:
    """Explicit binary_sensor includes count regardless of device class."""
    hass.states.async_set("binary_sensor.no_class", STATE_ON, {})
    hass.states.async_set(
        "binary_sensor.door_presence",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.DOOR},
    )
    area = _area(
        hass,
        "Dusche",
        {
            CONF_INCLUDE_ENTITIES: [
                "binary_sensor.no_class",
                "binary_sensor.door_presence",
            ]
        },
    )

    sources = area.get_presence_sensors()
    assert "binary_sensor.no_class" in sources
    assert "binary_sensor.door_presence" in sources


def test_automatic_discovery_keeps_device_class_filter(hass) -> None:
    """Without an explicit include, a door sensor is still not a presence source."""
    hass.states.async_set(
        "binary_sensor.auto_door",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.DOOR},
    )
    area = _area(hass, "Diele", {})
    assert "binary_sensor.auto_door" not in area.get_presence_sensors()


def test_exclude_beats_explicit_door_include(hass) -> None:
    """Exclusion wins even when the same entity is explicitly included."""
    hass.states.async_set(
        "binary_sensor.door_presence",
        STATE_ON,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.DOOR},
    )
    area = _area(
        hass,
        "Keller",
        {
            CONF_INCLUDE_ENTITIES: ["binary_sensor.door_presence"],
            CONF_EXCLUDE_ENTITIES: ["binary_sensor.door_presence"],
        },
    )
    assert "binary_sensor.door_presence" not in area.get_presence_sensors()


def test_explicit_door_source_activity_is_evaluated_from_state(hass) -> None:
    """Selected sources count as active only for on/open style states."""
    from custom_components.adaptive_areas.helpers.sources import (
        is_presence_source_active,
    )

    assert is_presence_source_active(hass, "binary_sensor.door_presence", STATE_ON)
    for state in (STATE_OFF, STATE_UNKNOWN, STATE_UNAVAILABLE):
        assert not is_presence_source_active(
            hass, "binary_sensor.door_presence", state
        ), state
