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
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    CONF_MIGRATION,
    DOMAIN,
    GLOBAL_ENTRY_UNIQUE_ID,
    AdaptiveConfigEntryVersion,
    AreaType,
)
from custom_components.adaptive_areas.migration import MigrationPhase, MigrationState
from custom_components.adaptive_areas.repairs import (
    ISSUE_ENVIRONMENT_WITHOUT_SOURCES,
    ISSUE_INVALID_ENTITIES,
    ISSUE_INVALID_FEATURE_CONFIGURATION,
    ISSUE_MISSING_AREA,
    ISSUE_MISSING_ENTITIES,
    ISSUE_NO_PRESENCE_SOURCES,
    REPAIR_ISSUE_CATEGORIES,
    REPAIR_ISSUE_TRANSLATION_KEYS,
    ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION,
    async_evaluate_config_entry,
    async_evaluate_single_global_entry_migration,
    async_remove_config_entry_issues,
    SingleGlobalEntryMigrationRepairFlow,
)

from tests.const import DEFAULT_MOCK_AREA, MockAreaIds
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
    monkeypatch,
) -> None:
    """A relevant registry update clears the Repair without polling."""
    monkeypatch.setattr(
        "custom_components.adaptive_areas.async_call_later",
        lambda _hass, _delay, callback: hass.loop.call_soon(callback, None).cancel,
    )
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


async def test_legacy_multi_entry_detection_creates_repair_without_mutation(
    hass,
) -> None:
    """Setup detection creates only the Repair; it never starts migration."""
    first = MockConfigEntry(
        domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    )
    second = MockConfigEntry(
        domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    )
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    await async_evaluate_single_global_entry_migration(hass)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    assert issue is not None
    assert issue.is_fixable
    assert hass.config_entries.async_get_entry(first.entry_id) is first
    assert hass.config_entries.async_get_entry(second.entry_id) is second


async def test_migration_repair_flow_requires_explicit_confirmation(
    hass, monkeypatch
) -> None:
    """Opening the Repair never starts migration; one confirmation starts it once."""
    from custom_components.adaptive_areas import migration as migration_module

    calls = 0

    async def tracked_orchestrator(_hass):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(
        migration_module,
        "async_run_single_global_entry_migration",
        tracked_orchestrator,
    )
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    form = await flow.async_step_init(None)
    assert form["type"] == "form"
    assert calls == 0
    result = await flow.async_step_init({})
    assert result["type"] == "create_entry"
    assert calls == 1


async def test_partial_transfer_restart_waits_for_repair_confirmation(
    hass, monkeypatch
) -> None:
    """A normal partial-state restart detects but never resumes migration."""
    from custom_components.adaptive_areas import migration as migration_module

    sources = [
        MockConfigEntry(
            domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
        ),
        MockConfigEntry(
            domain=DOMAIN, data=get_basic_config_entry_data(MockAreaIds.LIVING_ROOM)
        ),
    ]
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    for source in sources:
        source.add_to_hass(hass)
    target.add_to_hass(hass)
    state = MigrationState(
        1,
        MigrationPhase.TRANSFER_REGISTRY,
        [source.entry_id],
        target.entry_id,
        [DEFAULT_MOCK_AREA.value],
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    before_entities = dict(async_get_entity_registry(hass).entities)
    calls = 0

    async def tracked_orchestrator(_hass):
        nonlocal calls
        calls += 1
        assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
        return restored

    monkeypatch.setattr(
        migration_module,
        "async_run_single_global_entry_migration",
        tracked_orchestrator,
    )
    await async_evaluate_single_global_entry_migration(hass)
    assert calls == 0
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
    assert dict(async_get_entity_registry(hass).entities) == before_entities
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION)
        is not None
    )
    assert [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.unique_id == GLOBAL_ENTRY_UNIQUE_ID
    ] == [target]

    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init(None))["type"] == "form"
    assert calls == 0
    assert (await flow.async_step_init({}))["type"] == "create_entry"
    assert calls == 1


async def test_partial_remove_restart_waits_for_repair_confirmation(
    hass, monkeypatch
) -> None:
    """Restart preserves forward recovery and leaves the final source untouched."""
    from custom_components.adaptive_areas import migration as migration_module

    remaining = MockConfigEntry(
        domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    )
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    remaining.add_to_hass(hass)
    target.add_to_hass(hass)
    state = MigrationState(
        1,
        MigrationPhase.REMOVE_OLD,
        ["removed-a", "removed-b", remaining.entry_id],
        target.entry_id,
        [DEFAULT_MOCK_AREA.value],
        ["removed-a", "removed-b"],
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    calls = 0

    async def tracked(_hass):
        nonlocal calls
        calls += 1
        assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
        return restored

    monkeypatch.setattr(
        migration_module, "async_run_single_global_entry_migration", tracked
    )
    await async_evaluate_single_global_entry_migration(hass)
    assert calls == 0
    assert hass.config_entries.async_get_entry("removed-a") is None
    assert hass.config_entries.async_get_entry("removed-b") is None
    assert hass.config_entries.async_get_entry(remaining.entry_id) is remaining
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


async def test_repair_partial_remove_failure_preserves_forward_recovery(
    hass, monkeypatch
) -> None:
    """Repair checkpoints each successful removal before a later source fails."""
    sources = [
        MockConfigEntry(domain=DOMAIN, data=get_basic_config_entry_data(area))
        for area in (
            DEFAULT_MOCK_AREA,
            MockAreaIds.LIVING_ROOM,
            MockAreaIds.MASTER_BEDROOM,
        )
    ]
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    for source in sources:
        source.add_to_hass(hass)
    target.add_to_hass(hass)
    state = MigrationState(
        1,
        MigrationPhase.REMOVE_OLD,
        [source.entry_id for source in sources],
        target.entry_id,
        [],
    )
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: state.as_dict()}
    )
    ordered = sorted(sources, key=lambda source: source.entry_id)
    original_remove = hass.config_entries.async_remove
    calls: list[str] = []

    async def fail_second(entry_id):
        calls.append(entry_id)
        if len(calls) == 2:
            raise RuntimeError("remove failed")
        await original_remove(entry_id)

    monkeypatch.setattr(hass.config_entries, "async_remove", fail_second)
    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["errors"] == {"base": "migration_failed"}
    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.migration_phase is MigrationPhase.REMOVE_OLD
    assert checkpoint.removed_source_entry_ids == [ordered[0].entry_id]
    assert hass.config_entries.async_get_entry(ordered[0].entry_id) is None
    assert hass.config_entries.async_get_entry(ordered[1].entry_id) is ordered[1]
    assert hass.config_entries.async_get_entry(ordered[2].entry_id) is ordered[2]
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )

    # Persist and reload the irreversible boundary before the next explicit Repair.
    restored = MigrationState.from_dict(checkpoint.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    from custom_components.adaptive_areas import migration as migration_module

    original_orchestrator = migration_module.async_run_single_global_entry_migration
    orchestrator_calls = 0
    factory_calls = 0

    async def tracked_orchestrator(hass):
        nonlocal orchestrator_calls
        orchestrator_calls += 1
        return await original_orchestrator(hass)

    async def forbidden_factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("existing migration target must not use the factory")

    monkeypatch.setattr(
        migration_module,
        "async_run_single_global_entry_migration",
        tracked_orchestrator,
    )
    monkeypatch.setattr(
        migration_module, "async_get_or_create_global_entry", forbidden_factory
    )
    await async_evaluate_single_global_entry_migration(hass)
    assert orchestrator_calls == 0
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
    assert hass.config_entries.async_get_entry(ordered[0].entry_id) is None
    assert hass.config_entries.async_get_entry(ordered[1].entry_id) is ordered[1]
    assert hass.config_entries.async_get_entry(ordered[2].entry_id) is ordered[2]

    async def record_successful_removal(entry_id):
        calls.append(entry_id)
        await original_remove(entry_id)

    monkeypatch.setattr(hass.config_entries, "async_remove", record_successful_removal)
    retry_flow = SingleGlobalEntryMigrationRepairFlow()
    retry_flow.hass = hass
    assert (await retry_flow.async_step_init({}))["type"] == "create_entry"
    assert orchestrator_calls == 1
    assert factory_calls == 0
    assert calls == [
        ordered[0].entry_id,
        ordered[1].entry_id,
        ordered[1].entry_id,
        ordered[2].entry_id,
    ]
    complete = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert complete.migration_phase is MigrationPhase.COMPLETE
    assert all(
        hass.config_entries.async_get_entry(source.entry_id) is None
        for source in sources
    )
    assert [entry.entry_id for entry in hass.config_entries.async_entries(DOMAIN)] == [
        target.entry_id
    ]
    await async_evaluate_single_global_entry_migration(hass)
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION)
        is None
    )


async def test_repair_cleanup_failure_preserves_cleanup_checkpoint(
    hass, monkeypatch
) -> None:
    """A Cleanup failure through Repair retains recovery metadata for retry."""
    from custom_components.adaptive_areas import migration as migration_module
    from custom_components.adaptive_areas.migration import MigrationCleanupError

    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    target.add_to_hass(hass)
    state = MigrationState(
        1,
        MigrationPhase.CLEANUP,
        ["removed"],
        target.entry_id,
        [],
        ["removed"],
        {"entities": [{"entity_id": "preserved"}], "devices": []},
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )

    async def fail_cleanup(*_args, **_kwargs):
        raise MigrationCleanupError("cleanup unavailable")

    monkeypatch.setattr(migration_module, "async_cleanup_migration", fail_cleanup)
    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["errors"] == {"base": "migration_failed"}
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
    assert list(hass.config_entries.async_entries(DOMAIN)) == [target]
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


async def test_repair_verify_failure_keeps_sources_and_blocks_remove(
    hass, monkeypatch
) -> None:
    """Missing transferred entity fails VERIFY through the productive Repair flow."""
    from homeassistant.helpers.device_registry import async_get as async_get_devices

    from custom_components.adaptive_areas import migration as migration_module
    from custom_components.adaptive_areas.migration import MigrationSnapshot

    source = MockConfigEntry(
        domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    )
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    source.add_to_hass(hass)
    target.add_to_hass(hass)
    devices = async_get_devices(hass)
    device = devices.async_get_or_create(
        config_entry_id=target.entry_id,
        identifiers={(DOMAIN, "adaptive_area_device_kitchen")},
    )
    entities = async_get_entity_registry(hass)
    entity = entities.async_get_or_create(
        "sensor", DOMAIN, "repair_verify", config_entry=target, device_id=device.id
    )
    snapshot = MigrationSnapshot(
        [
            {
                "entity_id": entity.entity_id,
                "unique_id": entity.unique_id,
                "config_entry_id": source.entry_id,
                "device_id": device.id,
                "area_id": None,
                "name": None,
                "disabled_by": None,
                "hidden_by": None,
            }
        ],
        [
            {
                "id": device.id,
                "identifiers": list(device.identifiers),
                "config_entries": [source.entry_id],
                "area_id": None,
                "name": device.name,
                "name_by_user": device.name_by_user,
            }
        ],
    )
    state = MigrationState(
        1,
        MigrationPhase.VERIFY,
        [source.entry_id],
        target.entry_id,
        [],
        snapshot=snapshot.as_dict(),
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    entities.async_remove(entity.entity_id)
    remove_calls = cleanup_calls = 0

    async def forbidden_remove(*_args, **_kwargs):
        nonlocal remove_calls
        remove_calls += 1
        raise AssertionError("verify failure must not remove")

    async def forbidden_cleanup(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise AssertionError("verify failure must not cleanup")

    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", forbidden_remove
    )
    monkeypatch.setattr(migration_module, "async_cleanup_migration", forbidden_cleanup)
    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["errors"] == {"base": "migration_failed"}
    assert (
        MigrationState.from_dict(target.options[CONF_MIGRATION]).migration_phase
        is MigrationPhase.TRANSFER_REGISTRY
    )
    assert remove_calls == cleanup_calls == 0
    assert entities.async_get(entity.entity_id) is None
    restored_device = devices.async_get(device.id)
    assert restored_device is not None
    assert restored_device.config_entries == {source.entry_id}
    assert restored_device.identifiers == device.identifiers
    assert hass.config_entries.async_get_entry(source.entry_id) is source
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


async def test_repair_transfer_failure_keeps_transfer_checkpoint(
    hass, monkeypatch
) -> None:
    """A transfer failure through Repair never advances beyond TRANSFER_REGISTRY."""
    from types import SimpleNamespace

    from custom_components.adaptive_areas import migration as migration_module
    from custom_components.adaptive_areas.migration import MigrationTransferError

    source = MockConfigEntry(
        domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    )
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    source.add_to_hass(hass)
    target.add_to_hass(hass)
    state = MigrationState(
        1, MigrationPhase.TRANSFER_REGISTRY, [source.entry_id], target.entry_id, []
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    remove_calls = cleanup_calls = 0

    def fake_area(*_args, **_kwargs):
        return SimpleNamespace(id=DEFAULT_MOCK_AREA.value)

    def fail_transfer(*_args, **_kwargs):
        raise MigrationTransferError("device transfer failed")

    async def forbidden_remove(*_args, **_kwargs):
        nonlocal remove_calls
        remove_calls += 1
        raise AssertionError("transfer failure must not remove")

    async def forbidden_cleanup(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise AssertionError("transfer failure must not cleanup")

    monkeypatch.setattr(
        "custom_components.adaptive_areas.helpers.area.get_adaptive_area_for_config_entry",
        fake_area,
    )
    monkeypatch.setattr(migration_module, "transfer_area_ownership", fail_transfer)
    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", forbidden_remove
    )
    monkeypatch.setattr(migration_module, "async_cleanup_migration", forbidden_cleanup)
    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["errors"] == {"base": "migration_failed"}
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
    assert remove_calls == cleanup_calls == 0
    assert list(hass.config_entries.async_entries(DOMAIN)) == [source, target]
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


async def test_repair_activation_failure_keeps_repair_open_and_sources(
    hass, monkeypatch
) -> None:
    """Activation failure through Repair resets to the existing transfer checkpoint."""
    from custom_components.adaptive_areas import migration as migration_module
    from custom_components.adaptive_areas.migration import MigrationTransferError

    source = MockConfigEntry(
        domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    )
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    source.add_to_hass(hass)
    target.add_to_hass(hass)
    state = MigrationState(
        1, MigrationPhase.ACTIVATE_GLOBAL, [source.entry_id], target.entry_id, []
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    remove_calls = cleanup_calls = 0

    async def fail_activation(*_args, **_kwargs):
        raise MigrationTransferError("activation failed")

    async def forbidden_remove(*_args, **_kwargs):
        nonlocal remove_calls
        remove_calls += 1
        raise AssertionError("activation failure must not remove")

    async def forbidden_cleanup(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise AssertionError("activation failure must not cleanup")

    monkeypatch.setattr(
        migration_module, "async_activate_global_entry", fail_activation
    )
    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", forbidden_remove
    )
    monkeypatch.setattr(migration_module, "async_cleanup_migration", forbidden_cleanup)
    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["errors"] == {"base": "migration_failed"}
    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.migration_phase is MigrationPhase.TRANSFER_REGISTRY
    assert remove_calls == cleanup_calls == 0
    assert hass.config_entries.async_get_entry(source.entry_id) is source
    assert list(hass.config_entries.async_entries(DOMAIN)) == [source, target]
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


async def test_cleanup_restart_waits_for_repair_confirmation(hass, monkeypatch) -> None:
    """Restart never promotes an incomplete cleanup checkpoint to COMPLETE."""
    from custom_components.adaptive_areas import migration as migration_module

    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    target.add_to_hass(hass)
    state = MigrationState(
        1,
        MigrationPhase.CLEANUP,
        ["removed-a", "removed-b"],
        target.entry_id,
        [DEFAULT_MOCK_AREA.value],
        ["removed-a", "removed-b"],
        {"entities": [{"entity_id": "preserved"}], "devices": []},
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    calls = 0

    async def tracked(_hass):
        nonlocal calls
        calls += 1
        assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
        return restored

    monkeypatch.setattr(
        migration_module, "async_run_single_global_entry_migration", tracked
    )
    await async_evaluate_single_global_entry_migration(hass)
    assert calls == 0
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    await flow.async_step_init(None)
    assert calls == 0
    await flow.async_step_init({})
    assert calls == 1


async def test_complete_restart_has_no_repair_or_migration_side_effects(
    hass, monkeypatch
) -> None:
    """A valid COMPLETE checkpoint is stable across detection and explicit no-op."""
    from custom_components.adaptive_areas import migration as migration_module

    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    target.add_to_hass(hass)
    state = MigrationState(
        1, MigrationPhase.COMPLETE, [], target.entry_id, [], [], None
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    before = (
        dict(target.options),
        dict(async_get_entity_registry(hass).entities),
    )
    factory_calls = remove_calls = cleanup_calls = 0

    async def forbidden_factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("COMPLETE must not create a target")

    async def forbidden_remove(*_args, **_kwargs):
        nonlocal remove_calls
        remove_calls += 1
        raise AssertionError("COMPLETE must not remove entries")

    async def forbidden_cleanup(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise AssertionError("COMPLETE must not cleanup again")

    monkeypatch.setattr(
        migration_module, "async_get_or_create_global_entry", forbidden_factory
    )
    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", forbidden_remove
    )
    monkeypatch.setattr(migration_module, "async_cleanup_migration", forbidden_cleanup)
    await async_evaluate_single_global_entry_migration(hass)
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION)
        is None
    )
    assert (
        await migration_module.async_run_single_global_entry_migration(hass) == restored
    )
    assert factory_calls == remove_calls == cleanup_calls == 0
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
    assert (
        dict(target.options),
        dict(async_get_entity_registry(hass).entities),
    ) == before
    assert list(hass.config_entries.async_entries(DOMAIN)) == [target]


async def test_repair_blocks_multiple_global_entries_without_mutation(
    hass, monkeypatch
) -> None:
    """The productive Repair flow refuses ambiguous containers before migration."""
    from custom_components.adaptive_areas import migration as migration_module

    sources = [
        MockConfigEntry(
            domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
        ),
        MockConfigEntry(
            domain=DOMAIN, data=get_basic_config_entry_data(MockAreaIds.LIVING_ROOM)
        ),
    ]
    targets = [
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"{GLOBAL_ENTRY_UNIQUE_ID}_{index}",
            data={CONF_GLOBAL_ENTRY: True},
            options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
        )
        for index in range(2)
    ]
    for source in sources:
        source.add_to_hass(hass)
    for target in targets:
        target.add_to_hass(hass)
    remove_calls = cleanup_calls = factory_calls = 0

    async def forbidden_remove(*_args, **_kwargs):
        nonlocal remove_calls
        remove_calls += 1
        raise AssertionError("blocked precheck must not remove")

    async def forbidden_cleanup(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise AssertionError("blocked precheck must not cleanup")

    async def forbidden_factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("blocked precheck must not create")

    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", forbidden_remove
    )
    monkeypatch.setattr(migration_module, "async_cleanup_migration", forbidden_cleanup)
    monkeypatch.setattr(
        migration_module, "async_get_or_create_global_entry", forbidden_factory
    )
    await async_evaluate_single_global_entry_migration(hass)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    assert issue is not None and not issue.is_fixable
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    result = await flow.async_step_init({})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "migration_failed"}
    assert factory_calls == remove_calls == cleanup_calls == 0
    assert list(hass.config_entries.async_entries(DOMAIN)) == [*sources, *targets]


async def test_repair_blocks_duplicate_legacy_area_ids_without_mutation(
    hass, monkeypatch
) -> None:
    """Duplicate legacy Areas fail through Repair before a target is created."""
    from custom_components.adaptive_areas import migration as migration_module

    sources = [
        MockConfigEntry(
            domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
        )
        for _ in range(2)
    ]
    for source in sources:
        source.add_to_hass(hass)
    before_entries = list(hass.config_entries.async_entries(DOMAIN))
    factory_calls = remove_calls = cleanup_calls = 0

    async def forbidden_factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("duplicate Areas must fail before factory")

    async def forbidden_remove(*_args, **_kwargs):
        nonlocal remove_calls
        remove_calls += 1
        raise AssertionError("duplicate Areas must not remove")

    async def forbidden_cleanup(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise AssertionError("duplicate Areas must not cleanup")

    monkeypatch.setattr(
        migration_module, "async_get_or_create_global_entry", forbidden_factory
    )
    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", forbidden_remove
    )
    monkeypatch.setattr(migration_module, "async_cleanup_migration", forbidden_cleanup)
    await async_evaluate_single_global_entry_migration(hass)
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    result = await flow.async_step_init({})
    assert result["errors"] == {"base": "migration_failed"}
    assert factory_calls == remove_calls == cleanup_calls == 0
    assert list(hass.config_entries.async_entries(DOMAIN)) == before_entries


async def test_repair_blocks_unsupported_legacy_version_without_mutation(
    hass, monkeypatch
) -> None:
    """A formally valid future legacy version stops before the factory."""
    from custom_components.adaptive_areas import migration as migration_module

    sources = [
        MockConfigEntry(
            domain=DOMAIN,
            version=AdaptiveConfigEntryVersion.MAJOR + 1,
            data=get_basic_config_entry_data(DEFAULT_MOCK_AREA),
        ),
        MockConfigEntry(
            domain=DOMAIN,
            data=get_basic_config_entry_data(MockAreaIds.LIVING_ROOM),
        ),
    ]
    for source in sources:
        source.add_to_hass(hass)
    factory_calls = 0

    async def forbidden_factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("unsupported version must fail before factory")

    monkeypatch.setattr(
        migration_module, "async_get_or_create_global_entry", forbidden_factory
    )
    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    result = await flow.async_step_init({})
    assert result["errors"] == {"base": "migration_failed"}
    assert factory_calls == 0
    assert list(hass.config_entries.async_entries(DOMAIN)) == sources
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


async def test_repair_blocks_missing_persisted_target_without_mutation(
    hass, monkeypatch
) -> None:
    """A serializable state with a missing target is not silently repaired."""
    from custom_components.adaptive_areas import migration as migration_module

    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    target.add_to_hass(hass)
    state = MigrationState(
        1, MigrationPhase.TRANSFER_REGISTRY, ["missing-source"], "missing-target", []
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    factory_calls = 0

    async def forbidden_factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("ambiguous state must not create a target")

    monkeypatch.setattr(
        migration_module, "async_get_or_create_global_entry", forbidden_factory
    )
    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    result = await flow.async_step_init({})
    assert result["errors"] == {"base": "migration_failed"}
    assert factory_calls == 0
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == restored
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


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
    assert set(english["issues"]) == set(REPAIR_ISSUE_TRANSLATION_KEYS)
    assert strings["issues"] == english["issues"]
    for issue_id in english["issues"]:
        english_placeholders = set(
            re.findall(r"{([^{}]+)}", english["issues"][issue_id]["description"])
        )
        german_placeholders = set(
            re.findall(r"{([^{}]+)}", german["issues"][issue_id]["description"])
        )
        assert english_placeholders == german_placeholders


async def test_repair_factory_failure_preserves_legacy_entries(
    hass, monkeypatch
) -> None:
    """A Factory failure through Repair has no target or legacy side effect."""
    from custom_components.adaptive_areas import migration as migration_module
    from custom_components.adaptive_areas.migration import GlobalEntryFactoryError

    sources = [
        MockConfigEntry(
            domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
        ),
        MockConfigEntry(
            domain=DOMAIN,
            data=get_basic_config_entry_data(MockAreaIds.LIVING_ROOM),
        ),
    ]
    for source in sources:
        source.add_to_hass(hass)
    before = list(hass.config_entries.async_entries(DOMAIN))

    async def fail_factory(*_args, **_kwargs):
        raise GlobalEntryFactoryError("factory unavailable")

    monkeypatch.setattr(
        migration_module, "async_get_or_create_global_entry", fail_factory
    )
    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["errors"] == {"base": "migration_failed"}
    assert list(hass.config_entries.async_entries(DOMAIN)) == before
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
