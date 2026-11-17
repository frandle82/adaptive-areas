"""Read-only source-model coverage for the future Light runtime."""

from types import SimpleNamespace

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import (
    RegistryEntryDisabler,
    RegistryEntryHider,
    async_get as async_get_entity_registry,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    AREA_STATE_OCCUPIED,
    AREA_TYPE_INTERIOR,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_ID,
    CONF_NAME,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    CONF_TYPE,
    DOMAIN,
)
from custom_components.adaptive_areas.helpers.sources import light_source_snapshot


def _area(hass, name: str, features: dict, global_light_sensor: str | None = None):
    area_entry = async_get_area_registry(hass).async_create(name)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: global_light_sensor}},
    )
    entry.add_to_hass(hass)
    area = AdaptiveArea(
        hass,
        SimpleNamespace(id=area_entry.id, name=name, icon=None, floor_id=None),
        entry,
        {
            CONF_ID: area_entry.id,
            CONF_NAME: name,
            CONF_TYPE: AREA_TYPE_INTERIOR,
            CONF_PRESENCE_DEVICE_PLATFORMS: ["binary_sensor"],
            CONF_PRESENCE_SENSOR_DEVICE_CLASS: [BinarySensorDeviceClass.MOTION],
            CONF_ENABLED_FEATURES: features,
        },
    )
    return area, area_entry, entry


def _entity(
    hass,
    source_entry,
    domain: str,
    object_id: str,
    *,
    area_id: str | None = None,
    device_id: str | None = None,
    state: str = "off",
    attributes: dict | None = None,
):
    registry_entry = async_get_entity_registry(hass).async_get_or_create(
        domain,
        "test",
        object_id,
        suggested_object_id=object_id,
        config_entry=source_entry,
        device_id=device_id,
        original_device_class=(attributes or {}).get(ATTR_DEVICE_CLASS),
    )
    if area_id is not None:
        async_get_entity_registry(hass).async_update_entity(
            registry_entry.entity_id, area_id=area_id
        )
    hass.states.async_set(registry_entry.entity_id, state, attributes or {})
    return registry_entry


def test_light_targets_reuse_area_entity_discovery_without_mutation(hass) -> None:
    """Discover only enabled-Area lights across direct and device assignments."""
    area, living, entry = _area(hass, "Wohnzimmer", {CONF_FEATURE_LIGHT: {}})
    kitchen = async_get_area_registry(hass).async_create("Küche")
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    device_registry = async_get_device_registry(hass)
    living_device = device_registry.async_get_or_create(
        config_entry_id=source_entry.entry_id,
        identifiers={("test", "living_floor_lamp")},
    )
    device_registry.async_update_device(living_device.id, area_id=living.id)

    ceiling = _entity(hass, source_entry, "light", "ceiling", area_id=living.id)
    floor_lamp = _entity(
        hass,
        source_entry,
        "light",
        "floor_lamp",
        area_id=living.id,
        device_id=living_device.id,
    )
    unavailable = _entity(
        hass,
        source_entry,
        "light",
        "unavailable",
        area_id=living.id,
        state=STATE_UNAVAILABLE,
    )
    hidden = _entity(hass, source_entry, "light", "hidden", area_id=living.id)
    async_get_entity_registry(hass).async_update_entity(
        hidden.entity_id, hidden_by=RegistryEntryHider.USER
    )
    disabled = _entity(hass, source_entry, "light", "disabled", area_id=living.id)
    async_get_entity_registry(hass).async_update_entity(
        disabled.entity_id, disabled_by=RegistryEntryDisabler.USER
    )
    _entity(hass, source_entry, "light", "kitchen", area_id=kitchen.id)
    _entity(hass, source_entry, "switch", "decorative_light", area_id=living.id)
    _entity(hass, source_entry, "sensor", "lux", area_id=living.id)
    own_light = _entity(hass, entry, "light", "adaptive_areas_own", area_id=living.id)

    entities_before = set(async_get_entity_registry(hass).entities)
    config_before = dict(area.config)
    snapshot = light_source_snapshot(area)

    assert snapshot is not None
    assert snapshot.target_light_entity_ids == tuple(
        sorted(
            (
                ceiling.entity_id,
                floor_lamp.entity_id,
                hidden.entity_id,
                unavailable.entity_id,
            )
        )
    )
    assert {target.entity_id: target.available for target in snapshot.targets} == {
        ceiling.entity_id: True,
        floor_lamp.entity_id: True,
        hidden.entity_id: True,
        unavailable.entity_id: False,
    }
    assert disabled.entity_id not in snapshot.target_light_entity_ids
    assert own_light.entity_id not in snapshot.target_light_entity_ids
    assert set(async_get_entity_registry(hass).entities) == entities_before
    assert area.config == config_before


def test_light_snapshot_keeps_global_sources_and_presence_read_only(hass) -> None:
    """Model missing and unavailable sources without discovering fallbacks."""
    area, living, entry = _area(
        hass,
        "Wohnzimmer",
        {CONF_FEATURE_LIGHT: {}, CONF_FEATURE_LIGHT_GROUPS: {}},
        "sensor.outdoor_illuminance",
    )
    source_entry = MockConfigEntry(domain="test", data={})
    source_entry.add_to_hass(hass)
    illuminance = _entity(
        hass,
        source_entry,
        "sensor",
        "outdoor_illuminance",
        state="125.4",
        attributes={ATTR_DEVICE_CLASS: SensorDeviceClass.ILLUMINANCE},
    )
    presence = _entity(
        hass,
        source_entry,
        "binary_sensor",
        "motion",
        area_id=living.id,
        state=STATE_ON,
        attributes={ATTR_DEVICE_CLASS: BinarySensorDeviceClass.MOTION},
    )
    area.states = [AREA_STATE_OCCUPIED]
    options_before = dict(entry.options)

    snapshot = light_source_snapshot(area)

    assert snapshot is not None
    assert snapshot.illuminance_entity_id == illuminance.entity_id
    assert snapshot.illuminance_available is True
    assert snapshot.illuminance_value == 125.4
    assert snapshot.presence_source_entity_ids == (presence.entity_id,)
    assert snapshot.presence_available is True
    assert snapshot.presence_state is True
    assert entry.options == options_before

    hass.states.async_set(presence.entity_id, STATE_OFF)
    area.states = []
    vacant = light_source_snapshot(area)
    assert vacant is not None
    assert vacant.presence_available is True
    assert vacant.presence_state is False

    hass.states.async_set(illuminance.entity_id, STATE_UNAVAILABLE)
    hass.states.async_set(presence.entity_id, STATE_UNAVAILABLE)
    unavailable = light_source_snapshot(area)
    assert unavailable is not None
    assert unavailable.illuminance_entity_id == illuminance.entity_id
    assert unavailable.illuminance_available is False
    assert unavailable.illuminance_value is None
    assert unavailable.presence_available is False
    assert unavailable.presence_state is None

    entry.options[CONF_GLOBAL_OPTIONS][CONF_GLOBAL_LIGHT_SENSOR] = "sensor.missing"
    missing = light_source_snapshot(area)
    assert missing is not None
    assert missing.illuminance_entity_id == "sensor.missing"
    assert missing.illuminance_available is False
    assert missing.illuminance_value is None

    entry.options[CONF_GLOBAL_OPTIONS][CONF_GLOBAL_LIGHT_SENSOR] = None
    no_source = light_source_snapshot(area)
    assert no_source is not None
    assert no_source.illuminance_entity_id is None
    assert no_source.illuminance_available is False
    assert no_source.illuminance_value is None


def test_light_snapshot_is_gated_by_new_feature_only(hass) -> None:
    """Legacy light groups never activate the new source model."""
    disabled, _, _ = _area(hass, "Ohne Licht", {})
    legacy, _, _ = _area(hass, "Nur Lichtgruppen", {CONF_FEATURE_LIGHT_GROUPS: {}})
    enabled, _, _ = _area(
        hass,
        "Beide Lichtfunktionen",
        {CONF_FEATURE_LIGHT: {}, CONF_FEATURE_LIGHT_GROUPS: {}},
    )

    assert light_source_snapshot(disabled) is None
    assert light_source_snapshot(legacy) is None
    assert light_source_snapshot(enabled) is not None
