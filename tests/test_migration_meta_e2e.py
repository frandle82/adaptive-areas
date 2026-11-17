"""Cross-area and Meta aggregate coverage for the completed global migration."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.binary_sensor import (
    discover_binary_aggregate_source_groups,
)
from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    DATA_AREAS,
    DOMAIN,
    MODULE_DATA,
)
from custom_components.adaptive_areas.helpers.area import get_runtime_areas_for_entry
from custom_components.adaptive_areas.migration import (
    MigrationPhase,
    get_global_entries,
)
from custom_components.adaptive_areas.repairs import (
    SingleGlobalEntryMigrationRepairFlow,
    async_evaluate_single_global_entry_migration,
)
from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
)
from tests.mocks import MockBinarySensor

REGULAR_AREAS = (
    MockAreaIds.KITCHEN,
    MockAreaIds.LIVING_ROOM,
    MockAreaIds.MASTER_BEDROOM,
)
FLOOR_META = MockAreaIds.FIRST_FLOOR
GLOBAL_META = MockAreaIds.GLOBAL


def _runtime_areas(hass) -> dict[str, object]:
    """Return every runtime Area keyed by its stable logical Area id."""
    return {
        area.id: area
        for runtime in hass.data[MODULE_DATA].values()
        for area in runtime[DATA_AREAS].values()
    }


def _source_ids(area) -> dict[str, tuple[str, ...]]:
    """Capture sorted binary aggregate members by device class."""
    return {
        group.device_class: tuple(group.entity_ids)
        for group in discover_binary_aggregate_source_groups(area)
    }


async def test_repair_migration_preserves_meta_scoping_and_late_discovery(hass) -> None:
    """A real Repair migration keeps Meta source scopes and dynamic discovery intact."""
    sources = {
        area: [
            MockBinarySensor(
                name=f"motion_{area.value}",
                unique_id=f"motion_{area.value}",
                device_class=BinarySensorDeviceClass.MOTION,
            )
        ]
        for area in REGULAR_AREAS
    }
    await setup_mock_entities(hass, "binary_sensor", sources)
    entries = []
    for area in (*REGULAR_AREAS, FLOOR_META, GLOBAL_META):
        data = get_basic_config_entry_data(area)
        data[CONF_ENABLED_FEATURES] = {
            CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
        }
        entries.append(MockConfigEntry(domain=DOMAIN, data=data))
    await init_integration(hass, entries, areas=list(REGULAR_AREAS))

    before = _runtime_areas(hass)
    assert set(before) == {
        area.value for area in (*REGULAR_AREAS, FLOOR_META, GLOBAL_META)
    }
    assert set(before[FLOOR_META.value].child_areas) == {
        MockAreaIds.KITCHEN.value,
        MockAreaIds.LIVING_ROOM.value,
    }
    assert set(before[GLOBAL_META.value].child_areas) == {
        area.value for area in REGULAR_AREAS
    }
    before_sources = {area_id: _source_ids(area) for area_id, area in before.items()}
    entity_registry = async_get_entity_registry(hass)
    before_entities = {
        entry.entity_id: entry.unique_id
        for entry in entity_registry.entities.values()
        if entry.platform == DOMAIN
    }

    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["type"] == "create_entry"
    (global_entry,) = get_global_entries(hass)
    assert (
        global_entry.options["migration"]["migration_phase"] == MigrationPhase.COMPLETE
    )
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    after = {area.id: area for area in get_runtime_areas_for_entry(hass, global_entry)}
    assert set(after) == set(before)
    assert len(after) == len(set(after)) == 5
    assert set(after[FLOOR_META.value].child_areas) == set(
        before[FLOOR_META.value].child_areas
    )
    assert set(after[GLOBAL_META.value].child_areas) == set(
        before[GLOBAL_META.value].child_areas
    )
    assert {
        area_id: _source_ids(area) for area_id, area in after.items()
    } == before_sources
    assert {
        entry.entity_id: entry.unique_id
        for entry in entity_registry.entities.values()
        if entry.platform == DOMAIN
    } == before_entities
    assert all(
        entry.config_entry_id == global_entry.entry_id
        for entry in entity_registry.entities.values()
        if entry.platform == DOMAIN
    )
    for area in REGULAR_AREAS:
        motion_sources = _source_ids(after[area.value])["motion"]
        assert sources[area][0].entity_id in motion_sources
        assert all(
            other_sources[0].entity_id not in motion_sources
            for other_area, other_sources in sources.items()
            if other_area != area
        )
    floor_sources = _source_ids(after[FLOOR_META.value])["motion"]
    assert all(
        f"binary_sensor.adaptive_areas_aggregates_{area.value}_aggregate_motion"
        in floor_sources
        for area in (MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM)
    )
    assert not any(
        MockAreaIds.MASTER_BEDROOM.value in source for source in floor_sources
    )
    global_sources = _source_ids(after[GLOBAL_META.value])["motion"]
    assert all(
        f"binary_sensor.adaptive_areas_aggregates_{area.value}_aggregate_motion"
        in global_sources
        for area in REGULAR_AREAS
    )
    for area_id, groups in (
        (area_id, _source_ids(area)) for area_id, area in after.items()
    ):
        for entity_ids in groups.values():
            assert len(entity_ids) == len(set(entity_ids))
            assert not any(
                f"adaptive_areas_aggregates_{area_id}_aggregate_" in entity_id
                for entity_id in entity_ids
            )

    late = MockBinarySensor(
        name="motion_kitchen_late",
        unique_id="motion_kitchen_late",
        device_class=BinarySensorDeviceClass.MOTION,
    )
    await setup_mock_entities(hass, "binary_sensor", {MockAreaIds.KITCHEN: [late]})
    await hass.async_block_till_done()
    assert late.entity_id in _source_ids(after[MockAreaIds.KITCHEN.value])["motion"]
    assert late.entity_id not in _source_ids(after[MockAreaIds.LIVING_ROOM.value]).get(
        "motion", ()
    )
    assert late.entity_id not in _source_ids(
        after[MockAreaIds.MASTER_BEDROOM.value]
    ).get("motion", ())
    assert (
        global_entry.options["migration"]["migration_phase"] == MigrationPhase.COMPLETE
    )
    assert _source_ids(after[FLOOR_META.value])["motion"] == floor_sources
    assert _source_ids(after[GLOBAL_META.value])["motion"] == global_sources
    assert await hass.config_entries.async_reload(global_entry.entry_id)
    await hass.async_block_till_done()
    restarted = {
        area.id: area for area in get_runtime_areas_for_entry(hass, global_entry)
    }
    assert set(restarted) == set(after)
    assert len(restarted) == 5
    assert set(restarted[FLOOR_META.value].child_areas) == {
        MockAreaIds.KITCHEN.value,
        MockAreaIds.LIVING_ROOM.value,
    }
    assert set(restarted[GLOBAL_META.value].child_areas) == {
        area.value for area in REGULAR_AREAS
    }
    assert late.entity_id in _source_ids(restarted[MockAreaIds.KITCHEN.value])["motion"]
    assert _source_ids(restarted[FLOOR_META.value])["motion"] == floor_sources
    assert _source_ids(restarted[GLOBAL_META.value])["motion"] == global_sources
    for area_id, area in restarted.items():
        for entity_ids in _source_ids(area).values():
            assert len(entity_ids) == len(set(entity_ids))
            assert not any(
                f"adaptive_areas_aggregates_{area_id}_aggregate_" in entity
                for entity in entity_ids
            )
    for area_id in (FLOOR_META.value, GLOBAL_META.value):
        assert (
            len(
                [
                    entity
                    for entity in entity_registry.entities.values()
                    if entity.entity_id
                    == f"binary_sensor.adaptive_areas_aggregates_{area_id}_aggregate_motion"
                ]
            )
            == 1
        )
