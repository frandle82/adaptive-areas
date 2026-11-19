"""Native diagnostics coverage for the completed GlobalEntry migration."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.helpers.device_registry import (
    async_entries_for_config_entry,
)
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    DOMAIN,
)
from custom_components.adaptive_areas.diagnostics import (
    async_get_config_entry_diagnostics,
)
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

REGULAR = (
    MockAreaIds.KITCHEN,
    MockAreaIds.LIVING_ROOM,
    MockAreaIds.MASTER_BEDROOM,
)
META = (MockAreaIds.FIRST_FLOOR, MockAreaIds.GLOBAL)


def _identity(hass) -> tuple[dict, dict]:
    """Capture registry ownership without reading internal migration helpers."""
    entities = async_get_entity_registry(hass)
    devices = async_get_device_registry(hass)
    return (
        {item.entity_id: item.config_entry_id for item in entities.entities.values()},
        {
            item.id: (item.config_entry_id,)
            for entry in hass.config_entries.async_entries()
            for item in async_entries_for_config_entry(devices, entry.entry_id)
        },
    )


async def test_repair_migration_exposes_global_container_diagnostics(
    hass, monkeypatch
) -> None:
    """The native endpoint describes every logical Area owned by a GlobalEntry."""
    sources = {
        area: [
            MockBinarySensor(
                name=f"motion_{area.value}",
                unique_id=f"motion_{area.value}",
                device_class=BinarySensorDeviceClass.MOTION,
            )
        ]
        for area in REGULAR
    }
    await setup_mock_entities(hass, "binary_sensor", sources)
    entries = []
    for area in (*REGULAR, *META):
        data = get_basic_config_entry_data(area)
        data[CONF_ENABLED_FEATURES] = {
            CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
        }
        entries.append(MockConfigEntry(domain=DOMAIN, data=data))
    await init_integration(hass, entries, areas=list(REGULAR))
    legacy_ids = {entry.entry_id for entry in entries}

    await async_evaluate_single_global_entry_migration(hass)
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass
    assert (await flow.async_step_init({}))["type"] == "create_entry"
    (global_entry,) = get_global_entries(hass)
    assert (
        global_entry.options["migration"]["migration_phase"] == MigrationPhase.COMPLETE
    )

    import custom_components.adaptive_areas.migration as migration

    calls = 0

    async def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Diagnostics must not migrate")

    monkeypatch.setattr(migration, "async_run_single_global_entry_migration", forbidden)
    before_identity = _identity(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, global_entry)
    assert _identity(hass) == before_identity
    assert calls == 0
    assert diagnostics["configuration"]["runtime_available"] is True
    assert diagnostics["container"] == {
        "logical_area_count": 5,
        "runtime_area_count": 5,
    }
    assert list(diagnostics["areas"]) == sorted(diagnostics["areas"])
    assert set(diagnostics["areas"]) == {area.value for area in (*REGULAR, *META)}
    assert set(diagnostics["areas"]).isdisjoint(legacy_ids)
    assert diagnostics["areas"][MockAreaIds.KITCHEN.value]["type"] == "regular"
    assert diagnostics["areas"][MockAreaIds.FIRST_FLOOR.value]["type"] == "floor"
    assert diagnostics["areas"][MockAreaIds.GLOBAL.value]["type"] == "global"
    assert all(
        item["generated_entity_count"] > 0 for item in diagnostics["areas"].values()
    )

    assert await hass.config_entries.async_reload(global_entry.entry_id)
    await hass.async_block_till_done()
    restarted = await async_get_config_entry_diagnostics(hass, global_entry)
    assert restarted["container"] == diagnostics["container"]
    assert restarted["areas"] == diagnostics["areas"]
