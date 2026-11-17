"""End-to-end lifecycle coverage for the explicit migration orchestrator."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    DOMAIN,
)
from custom_components.adaptive_areas.helpers.area import get_runtime_areas_for_entry
from custom_components.adaptive_areas.migration import (
    MigrationPhase,
    async_run_single_global_entry_migration,
    get_global_entries,
)
from tests.const import MockAreaIds
from tests.helpers import get_basic_config_entry_data, init_integration


async def test_repair_orchestrator_migrates_multi_area_runtime_without_new_entities(
    hass,
) -> None:
    """Three running legacy Areas become one running container without ID churn."""
    area_ids = [
        MockAreaIds.KITCHEN,
        MockAreaIds.LIVING_ROOM,
        MockAreaIds.MASTER_BEDROOM,
    ]
    legacy = [
        MockConfigEntry(domain=DOMAIN, data=get_basic_config_entry_data(area_id))
        for area_id in area_ids
    ]
    await init_integration(hass, legacy, areas=area_ids)
    entity_registry = async_get_entity_registry(hass)
    before = {
        entity.entity_id: entity.unique_id
        for entry in legacy
        for entity in entity_registry.entities.get_entries_for_config_entry_id(
            entry.entry_id
        )
        if entity.platform == DOMAIN
    }

    state = await async_run_single_global_entry_migration(hass)

    assert state.migration_phase is MigrationPhase.COMPLETE
    (global_entry,) = get_global_entries(hass)
    assert not hass.config_entries.async_entries(DOMAIN, include_ignore=False)[1:]
    assert set(global_entry.options[CONF_AREAS]) == {area.value for area in area_ids}
    assert {area.id for area in get_runtime_areas_for_entry(hass, global_entry)} == {
        area.value for area in area_ids
    }
    after = {
        entity.entity_id: entity.unique_id
        for entity in entity_registry.entities.get_entries_for_config_entry_id(
            global_entry.entry_id
        )
        if entity.platform == DOMAIN
    }
    assert after == before
