"""Tests for Adaptive Areas Repair issue lifecycle."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
import re

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.floor_registry import async_get as async_get_floor_registry

from custom_components.adaptive_areas.const import (
    CONF_BLE_TRACKER_ENTITIES,
    CONF_CLIMATE_CONTROL_ENTITY_ID,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_FEATURE_AGGREGATION,
    CONF_FEATURE_BLE_TRACKERS,
    CONF_FEATURE_CLIMATE_CONTROL,
    CONF_FEATURE_WASP_IN_A_BOX,
    CONF_INCLUDE_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_FEATURE_ENVIRONMENT,
    CONF_NAME,
    CONF_OVERHEAD_LIGHTS,
    CONF_TASK_SWITCHES,
    CONF_TYPE,
    DOMAIN,
    AreaType,
)
from custom_components.adaptive_areas.repairs import (
    ISSUE_ENVIRONMENT_WITHOUT_SOURCES,
    ISSUE_INVALID_ENTITIES,
    ISSUE_INVALID_FEATURE_CONFIGURATION,
    ISSUE_MISSING_AREA,
    ISSUE_MISSING_ENTITIES,
    ISSUE_NO_PRESENCE_SOURCES,
    REPAIR_ISSUE_CATEGORIES,
    async_evaluate_config_entry,
    async_remove_config_entry_issues,
)

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import get_basic_config_entry_data


def _issue(registry: ir.IssueRegistry, category: str, entry: MockConfigEntry):
    return registry.async_get_issue(DOMAIN, f"{category}_{entry.entry_id}")


def _register_entity(
    hass: HomeAssistant,
    entity_id: str,
    *,
    area_id: str | None = None,
    device_class: str | None = None,
) -> None:
    """Register one test entity without requiring a live state."""
    domain, object_id = entity_id.split(".", 1)
    entry = async_get_entity_registry(hass).async_get_or_create(
        domain,
        "test",
        object_id,
        suggested_object_id=object_id,
        original_device_class=device_class,
    )
    if area_id is not None:
        async_get_entity_registry(hass).async_update_entity(
            entry.entity_id, area_id=area_id
        )


async def test_missing_area_issue_created_and_removed(hass: HomeAssistant) -> None:
    """A deleted backing Area creates one deterministic error issue."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    registry = ir.async_get(hass)

    await async_evaluate_config_entry(hass, entry)
    issue = _issue(registry, ISSUE_MISSING_AREA, entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    await async_evaluate_config_entry(hass, entry)
    assert len(registry.issues) == 1

    area = async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    assert area.id == data["id"]
    await async_evaluate_config_entry(hass, entry)
    assert _issue(registry, ISSUE_MISSING_AREA, entry) is None


async def test_missing_entity_issue_ignores_unavailable_and_cleans_up(
    hass: HomeAssistant,
) -> None:
    """Unavailable states exist; only absent explicit references are missing."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = ["binary_sensor.configured_motion"]
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    area = async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    assert area.id == data["id"]
    registry = ir.async_get(hass)

    await async_evaluate_config_entry(hass, entry)
    issue = _issue(registry, ISSUE_MISSING_ENTITIES, entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING

    hass.states.async_set("binary_sensor.configured_motion", STATE_UNAVAILABLE)
    await async_evaluate_config_entry(hass, entry)
    assert _issue(registry, ISSUE_MISSING_ENTITIES, entry) is None

    hass.states.async_set("binary_sensor.configured_motion", STATE_UNKNOWN)
    await async_evaluate_config_entry(hass, entry)
    assert _issue(registry, ISSUE_MISSING_ENTITIES, entry) is None


async def test_registry_only_entity_is_not_missing(hass: HomeAssistant) -> None:
    """A registry entry without a State is still an existing reference."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = ["sensor.registry_only"]
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    _register_entity(hass, "sensor.registry_only")

    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["count"] == 0


async def test_missing_explicit_environment_reference_is_repaired(
    hass: HomeAssistant,
) -> None:
    """Deleted explicit environmental sources are reported by category."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_ENVIRONMENT: {
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.deleted_outdoor"
        }
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    area = async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    assert area.id == data["id"]

    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["category_counts"] == {"room_climate": 1}


async def test_deleted_primary_area_sensor_is_repaired(hass: HomeAssistant) -> None:
    """Missing primary source creates a Repair only while evaluation is enabled."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_AREA_TEMPERATURE_SENSOR] = "sensor.deleted_room_temperature"
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    area = async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    assert area.id == data["id"]

    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["count"] == 0

    data[CONF_ENABLED_FEATURES] = {CONF_FEATURE_ENVIRONMENT: {}}
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["category_counts"] == {"area_climate": 1}


async def test_presence_sources_are_structural_and_meta_areas_are_skipped(
    hass: HomeAssistant,
) -> None:
    """Presence Repairs ignore transient state and derived meta presence."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    async_get_area_registry(hass).async_create(name=data[CONF_NAME])

    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["presence"] == {
        "source_count": 0,
        "problem": ISSUE_NO_PRESENCE_SOURCES,
    }
    assert _issue(ir.async_get(hass), ISSUE_NO_PRESENCE_SOURCES, entry) is not None

    _register_entity(
        hass,
        "binary_sensor.motion",
        area_id=data["id"],
        device_class=BinarySensorDeviceClass.MOTION,
    )
    hass.states.async_set("binary_sensor.motion", STATE_UNAVAILABLE)
    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["presence"]["source_count"] == 1
    assert _issue(ir.async_get(hass), ISSUE_NO_PRESENCE_SOURCES, entry) is None
    hass.states.async_set("binary_sensor.motion", STATE_UNKNOWN)
    assert (await async_evaluate_config_entry(hass, entry))["presence"][
        "problem"
    ] is None

    meta_data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    meta_data[CONF_TYPE] = AreaType.META
    meta_entry = MockConfigEntry(domain=DOMAIN, data=meta_data)
    assert (await async_evaluate_config_entry(hass, meta_entry))["presence"][
        "problem"
    ] is None


async def test_floor_entry_counts_as_existing_area(hass: HomeAssistant) -> None:
    """A floor-backed meta entry does not create a missing-Area issue."""
    floor = async_get_floor_registry(hass).async_create("Upstairs")
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update({"id": floor.floor_id, CONF_TYPE: AreaType.META})
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    assert not (await async_evaluate_config_entry(hass, entry))["missing_area"]


async def test_environment_requires_any_structural_measurement(
    hass: HomeAssistant,
) -> None:
    """One temperature, humidity, or pollutant capability is sufficient."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    assert (await async_evaluate_config_entry(hass, entry))["environment"][
        "enabled"
    ] is False

    for entity_id, device_class, expected in (
        ("sensor.temperature", SensorDeviceClass.TEMPERATURE, "temperature"),
        ("sensor.humidity", SensorDeviceClass.HUMIDITY, "humidity"),
        ("sensor.co2", SensorDeviceClass.CO2, "co2"),
    ):
        enabled_data = dict(data)
        enabled_data[CONF_ENABLED_FEATURES] = {CONF_FEATURE_ENVIRONMENT: {}}
        enabled_entry = MockConfigEntry(domain=DOMAIN, data=enabled_data)
        empty = await async_evaluate_config_entry(hass, enabled_entry)
        assert empty["environment"]["problem"] == ISSUE_ENVIRONMENT_WITHOUT_SOURCES
        _register_entity(hass, entity_id, area_id=data["id"], device_class=device_class)
        hass.states.async_set(entity_id, STATE_UNAVAILABLE)
        restored = await async_evaluate_config_entry(hass, enabled_entry)
        assert expected in restored["environment"]["capabilities"]
        assert restored["environment"]["problem"] is None
        assert (
            _issue(
                ir.async_get(hass),
                ISSUE_ENVIRONMENT_WITHOUT_SOURCES,
                enabled_entry,
            )
            is None
        )
        async_get_entity_registry(hass).async_remove(entity_id)
        hass.states.async_remove(entity_id)


async def test_invalid_entity_roles_are_aggregated(hass: HomeAssistant) -> None:
    """Only existing, unambiguously wrong role domains are invalid."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = ["sensor.generic"]
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_CLIMATE_CONTROL: {
            CONF_CLIMATE_CONTROL_ENTITY_ID: "sensor.wrong_climate"
        },
        "light_groups": {CONF_OVERHEAD_LIGHTS: ["switch.wrong_light"]},
        CONF_FEATURE_ENVIRONMENT: {
            CONF_ENVIRONMENT_VENTILATION_FANS: ["switch.wrong_fan"]
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    for entity_id in (
        "sensor.generic",
        "sensor.wrong_climate",
        "switch.wrong_light",
        "switch.wrong_fan",
    ):
        _register_entity(hass, entity_id)

    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["invalid_entities"] == {
        "count": 3,
        "categories": ["climate_control", "light_groups", "room_climate"],
        "category_counts": {
            "climate_control": 1,
            "light_groups": 1,
            "room_climate": 1,
        },
    }
    assert _issue(ir.async_get(hass), ISSUE_INVALID_ENTITIES, entry) is not None

    fixed = dict(data)
    fixed[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_CLIMATE_CONTROL: {CONF_CLIMATE_CONTROL_ENTITY_ID: "climate.room"},
        "light_groups": {CONF_OVERHEAD_LIGHTS: ["light.ceiling"]},
        CONF_FEATURE_ENVIRONMENT: {
            CONF_ENVIRONMENT_VENTILATION_FANS: ["fan.ventilation"]
        },
    }
    fixed_entry = MockConfigEntry(domain=DOMAIN, data=fixed, entry_id=entry.entry_id)
    for entity_id in ("climate.room", "light.ceiling", "fan.ventilation"):
        _register_entity(hass, entity_id)
    assert (await async_evaluate_config_entry(hass, fixed_entry))["invalid_entities"][
        "count"
    ] == 0
    assert _issue(ir.async_get(hass), ISSUE_INVALID_ENTITIES, entry) is None


async def test_valid_role_domains_and_generic_includes_are_not_invalid(
    hass: HomeAssistant,
) -> None:
    """Supported domains pass while generic filters remain unrestricted."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = ["sensor.generic"]
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_CLIMATE_CONTROL: {CONF_CLIMATE_CONTROL_ENTITY_ID: "climate.room"},
        "light_groups": {CONF_OVERHEAD_LIGHTS: ["light.ceiling"]},
        "switch_groups": {CONF_TASK_SWITCHES: ["switch.task"]},
        CONF_FEATURE_ENVIRONMENT: {
            CONF_ENVIRONMENT_WINDOWS: ["binary_sensor.window"],
            CONF_ENVIRONMENT_VENTILATION_FANS: ["fan.ventilation"],
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    for entity_id in (
        "sensor.generic",
        "climate.room",
        "light.ceiling",
        "switch.task",
        "binary_sensor.window",
        "fan.ventilation",
    ):
        _register_entity(hass, entity_id)
    assert (await async_evaluate_config_entry(hass, entry))["invalid_entities"][
        "count"
    ] == 0


async def test_registry_event_reevaluates_presence_repair(
    hass: HomeAssistant,
    basic_config_entry: MockConfigEntry,
    _setup_integration_basic,
) -> None:
    """A relevant registry update clears the Repair without polling."""
    registry = ir.async_get(hass)
    assert _issue(registry, ISSUE_NO_PRESENCE_SOURCES, basic_config_entry) is not None
    _register_entity(
        hass,
        "binary_sensor.new_motion",
        area_id=basic_config_entry.data["id"],
        device_class=BinarySensorDeviceClass.MOTION,
    )
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    assert _issue(registry, ISSUE_NO_PRESENCE_SOURCES, basic_config_entry) is None


async def test_invalid_feature_configuration_is_one_issue_and_cleans_up(
    hass: HomeAssistant,
) -> None:
    """Feature prerequisites use one aggregated deterministic issue."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_WASP_IN_A_BOX: {},
        CONF_FEATURE_BLE_TRACKERS: {},
        CONF_FEATURE_CLIMATE_CONTROL: {},
    }
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["feature_configuration"]["count"] == 3
    assert len(summary["feature_configuration"]["features"]) == 3
    assert (
        _issue(ir.async_get(hass), ISSUE_INVALID_FEATURE_CONFIGURATION, entry)
        is not None
    )

    fixed = dict(data)
    fixed[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_AGGREGATION: {},
        CONF_FEATURE_WASP_IN_A_BOX: {},
        CONF_FEATURE_BLE_TRACKERS: {CONF_BLE_TRACKER_ENTITIES: ["sensor.tracker"]},
        CONF_FEATURE_CLIMATE_CONTROL: {CONF_CLIMATE_CONTROL_ENTITY_ID: "climate.room"},
    }
    fixed_entry = MockConfigEntry(domain=DOMAIN, data=fixed, entry_id=entry.entry_id)
    assert (await async_evaluate_config_entry(hass, fixed_entry))[
        "feature_configuration"
    ]["count"] == 0
    assert (
        _issue(ir.async_get(hass), ISSUE_INVALID_FEATURE_CONFIGURATION, entry) is None
    )


async def test_cleanup_removes_every_issue_category(hass: HomeAssistant) -> None:
    """Deleting an entry removes all deterministic Repair categories."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    registry = ir.async_get(hass)
    for category in REPAIR_ISSUE_CATEGORIES:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{category}_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=category,
        )
    await async_remove_config_entry_issues(hass, entry)
    assert not registry.issues


def test_repair_translation_keys_exist() -> None:
    """English and German issue keys and placeholders remain aligned."""
    import json
    from pathlib import Path

    translations = Path("custom_components/adaptive_areas/translations")
    english = json.loads((translations / "en.json").read_text())
    german = json.loads((translations / "de.json").read_text())
    strings = json.loads(
        Path("custom_components/adaptive_areas/strings.json").read_text()
    )
    assert english["issues"].keys() == german["issues"].keys()
    assert set(english["issues"]) == set(REPAIR_ISSUE_CATEGORIES)
    assert strings["issues"] == english["issues"]
    for issue_id in english["issues"]:
        english_placeholders = set(
            re.findall(r"{([^{}]+)}", english["issues"][issue_id]["description"])
        )
        german_placeholders = set(
            re.findall(r"{([^{}]+)}", german["issues"][issue_id]["description"])
        )
        assert english_placeholders == german_placeholders
