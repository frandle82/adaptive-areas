"""Persistent domain-state coverage for the GlobalEntry migration."""

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from datetime import timedelta

from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.storage import Store
from homeassistant.util.dt import utcnow

from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    CONF_FEATURE_ROOM_USAGE,
    DOMAIN,
    SERVICE_SET_SCORE,
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
from tests.mocks import MockSensor

AREAS = (MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM)


def _energy(area, offset: int) -> list[MockSensor]:
    return [
        MockSensor(
            name=f"energy_{area.value}_{index}",
            unique_id=f"energy_{area.value}_{index}",
            native_value=offset + index,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            extra_state_attributes={"unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR},
        )
        for index in (1, 2)
    ]


async def _stores(hass, area_id: str) -> tuple[dict, dict]:
    energy = await Store(hass, 1, f"energy_aggregate.{area_id}").async_load()
    cleaning = await Store(
        hass, 1, f"adaptive_areas.cleaning_tracker.{area_id}"
    ).async_load()
    assert isinstance(energy, dict) and energy
    assert isinstance(cleaning, dict) and cleaning
    return energy, cleaning


async def test_repair_migration_preserves_area_keyed_persistent_state(hass) -> None:
    """Energy and Cleaning state stay area-keyed through Repair and reload."""
    sources = {
        MockAreaIds.KITCHEN: _energy(MockAreaIds.KITCHEN, 10),
        MockAreaIds.LIVING_ROOM: _energy(MockAreaIds.LIVING_ROOM, 40),
    }
    await setup_mock_entities(hass, "sensor", sources)
    entries = []
    for area in AREAS:
        data = get_basic_config_entry_data(area)
        data[CONF_ENABLED_FEATURES] = {
            CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1},
            CONF_FEATURE_ROOM_USAGE: {},
        }
        entries.append(MockConfigEntry(domain=DOMAIN, data=data))
    await init_integration(hass, entries, areas=list(AREAS))
    scores = {MockAreaIds.KITCHEN: 23, MockAreaIds.LIVING_ROOM: 67}
    for area, score in scores.items():
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_SCORE,
            {"area_id": [area.value], "score": score},
            blocking=True,
        )
    async_fire_time_changed(hass, utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    before = {area.value: await _stores(hass, area.value) for area in AREAS}
    assert before[MockAreaIds.KITCHEN.value] != before[MockAreaIds.LIVING_ROOM.value]
    legacy_ids = {entry.entry_id for entry in entries}

    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["type"] == "create_entry"
    (global_entry,) = get_global_entries(hass)
    assert (
        global_entry.options["migration"]["migration_phase"] == MigrationPhase.COMPLETE
    )
    assert {area.id for area in get_runtime_areas_for_entry(hass, global_entry)} == {
        area.value for area in AREAS
    }
    after = {area.value: await _stores(hass, area.value) for area in AREAS}
    assert after == before
    assert all(
        global_entry.entry_id not in key
        and all(legacy not in key for legacy in legacy_ids)
        for key in [f"energy_aggregate.{area.value}" for area in AREAS]
        + [f"adaptive_areas.cleaning_tracker.{area.value}" for area in AREAS]
    )

    assert await hass.config_entries.async_reload(global_entry.entry_id)
    await hass.async_block_till_done()
    assert {area.value: await _stores(hass, area.value) for area in AREAS} == before
