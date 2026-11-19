"""Meta Area source discovery stays complete regardless of Area setup order."""

import asyncio

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.base.adaptive import AdaptiveMetaArea
from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_AREAS,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    CONF_GLOBAL_ENTRY,
    DOMAIN,
)
from custom_components.adaptive_areas import binary_sensor as binary_sensor_platform
from custom_components.adaptive_areas import sensor as sensor_platform
from custom_components.adaptive_areas.helpers.area import (
    iter_runtime_areas,
)
from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
)
from tests.mocks import MockBinarySensor, MockSensor

CHILD_AREAS = (MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM)
META_AREAS = (MockAreaIds.FIRST_FLOOR, MockAreaIds.GLOBAL)


def _entries() -> list[MockConfigEntry]:
    entries = []
    for area in (*CHILD_AREAS, *META_AREAS):
        data = get_basic_config_entry_data(area)
        data[CONF_ENABLED_FEATURES] = {
            CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
        }
        entries.append(MockConfigEntry(domain=DOMAIN, data=data))
    return entries


def _entry_for(entries: list[MockConfigEntry], area: MockAreaIds) -> MockConfigEntry:
    return next(entry for entry in entries if entry.data["id"] == area.value)


def _expected_child_aggregates(hass) -> list[str]:
    """Child aggregate entities from the registry (ground truth)."""
    registry = async_get_entity_registry(hass)
    prefixes = tuple(
        f"binary_sensor.adaptive_areas_aggregates_{area.value}_aggregate_"
        for area in CHILD_AREAS
    )
    return sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.entity_id.startswith(prefixes)
    )


def _meta_sources(hass, meta: MockAreaIds) -> list[str]:
    """Aggregate entity IDs that a runtime Meta Area currently lists."""
    (area,) = [a for a in iter_runtime_areas(hass) if a.slug == meta.value]
    return sorted(
        entity["entity_id"]
        for entity in area.entities.get("binary_sensor", [])
        if "_aggregate_" in entity["entity_id"]
    )


async def _setup_child_sources(hass) -> None:
    sources = {
        area: [
            MockBinarySensor(
                name=f"motion_{area.value}",
                unique_id=f"motion_{area.value}",
                device_class=BinarySensorDeviceClass.MOTION,
            )
        ]
        for area in CHILD_AREAS
    }
    await setup_mock_entities(hass, "binary_sensor", sources)


async def test_meta_sources_complete_when_child_entities_register_late(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Child aggregates registered after the Meta Areas loaded are included.

    The Kitchen aggregate addition is held until both Meta Areas completed their
    own load. The gate opens by event, not by timing, so the order is controlled.
    """
    await _setup_child_sources(hass)
    entries = _entries()
    gate = asyncio.Event()
    meta_loads = {MockAreaIds.FIRST_FLOOR.value: 0, MockAreaIds.GLOBAL.value: 0}
    meta_ready = asyncio.Event()

    original_load = AdaptiveMetaArea.load_entities

    async def observed_load(self) -> None:
        await original_load(self)
        if self.slug in meta_loads:
            meta_loads[self.slug] += 1
            # initialize() loads once; the entry's registration boundary loads again.
            if all(count >= 2 for count in meta_loads.values()):
                meta_ready.set()

    original_setup_area = binary_sensor_platform._async_setup_area

    async def gated_setup_area(hass_, area, async_add_entities) -> None:
        if area.slug != MockAreaIds.KITCHEN.value:
            return await original_setup_area(hass_, area, async_add_entities)

        def deferred_add(entities, update_before_add: bool = False) -> None:
            async def _add() -> None:
                await gate.wait()
                async_add_entities(entities, update_before_add)

            hass_.async_create_task(_add())

        return await original_setup_area(hass_, area, deferred_add)

    monkeypatch.setattr(AdaptiveMetaArea, "load_entities", observed_load)
    monkeypatch.setattr(binary_sensor_platform, "_async_setup_area", gated_setup_area)

    setup = hass.async_create_task(
        init_integration(hass, entries, areas=list(CHILD_AREAS))
    )
    await meta_ready.wait()

    # Precondition: the held Kitchen aggregate is not registered yet.
    registered = _expected_child_aggregates(hass)
    assert not any(MockAreaIds.KITCHEN.value in entity_id for entity_id in registered)

    gate.set()
    await setup
    await hass.async_block_till_done()

    expected = _expected_child_aggregates(hass)
    assert any(MockAreaIds.KITCHEN.value in entity_id for entity_id in expected)
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == expected
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == expected


async def test_meta_sources_complete_when_children_finish_before_meta(hass) -> None:
    """Reverse order: children complete first, then the Meta Areas load."""
    await _setup_child_sources(hass)
    await init_integration(hass, _entries(), areas=list(CHILD_AREAS))

    expected = _expected_child_aggregates(hass)
    assert expected
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == expected
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == expected


async def test_meta_sources_unique_and_no_reload_after_child_reload(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child reload refreshes Meta sources without duplicates or Meta reloads."""
    await _setup_child_sources(hass)
    entries = _entries()
    await init_integration(hass, entries, areas=list(CHILD_AREAS))
    expected = _expected_child_aggregates(hass)

    scheduled: list[str] = []
    original_schedule = hass.config_entries.async_schedule_reload

    def recording_schedule(entry_id: str):
        scheduled.append(entry_id)
        return original_schedule(entry_id)

    monkeypatch.setattr(
        hass.config_entries, "async_schedule_reload", recording_schedule
    )

    kitchen = _entry_for(entries, MockAreaIds.KITCHEN)
    assert await hass.config_entries.async_reload(kitchen.entry_id)
    await hass.async_block_till_done()

    assert scheduled == []
    sources = _meta_sources(hass, MockAreaIds.FIRST_FLOOR)
    assert sources == expected
    assert len(sources) == len(set(sources))


def _aggregates_for(hass, areas: tuple[MockAreaIds, ...]) -> list[str]:
    """Registry ground truth for binary aggregates of the given child Areas."""
    registry = async_get_entity_registry(hass)
    prefixes = tuple(
        f"binary_sensor.adaptive_areas_aggregates_{area.value}_aggregate_"
        for area in areas
    )
    return sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.entity_id.startswith(prefixes)
    )


async def test_interior_and_exterior_meta_areas_list_only_their_children(hass) -> None:
    """Interior, Exterior and Global Meta Areas each list the right children."""
    interior_child, exterior_child = MockAreaIds.KITCHEN, MockAreaIds.BACKYARD
    sources = {
        area: [
            MockBinarySensor(
                name=f"motion_{area.value}",
                unique_id=f"motion_{area.value}",
                device_class=BinarySensorDeviceClass.MOTION,
            )
        ]
        for area in (interior_child, exterior_child)
    }
    await setup_mock_entities(hass, "binary_sensor", sources)
    entries = []
    for area in (
        interior_child,
        exterior_child,
        MockAreaIds.INTERIOR,
        MockAreaIds.EXTERIOR,
        MockAreaIds.GLOBAL,
    ):
        data = get_basic_config_entry_data(area)
        data[CONF_ENABLED_FEATURES] = {
            CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
        }
        entries.append(MockConfigEntry(domain=DOMAIN, data=data))
    await init_integration(hass, entries, areas=[interior_child, exterior_child])
    await hass.async_block_till_done()

    interior_expected = _aggregates_for(hass, (interior_child,))
    exterior_expected = _aggregates_for(hass, (exterior_child,))
    assert interior_expected and exterior_expected
    assert _meta_sources(hass, MockAreaIds.INTERIOR) == interior_expected
    assert _meta_sources(hass, MockAreaIds.EXTERIOR) == exterior_expected
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == sorted(
        interior_expected + exterior_expected
    )


async def test_child_refresh_after_meta_unload_is_harmless(hass, caplog) -> None:
    """Refresh after a Meta Area unload logs no error and touches no unloaded Area."""
    await _setup_child_sources(hass)
    entries = _entries()
    await init_integration(hass, entries, areas=list(CHILD_AREAS))
    await hass.async_block_till_done()

    floor = _entry_for(entries, MockAreaIds.FIRST_FLOOR)
    assert await hass.config_entries.async_unload(floor.entry_id)
    await hass.async_block_till_done()
    caplog.clear()

    kitchen = _entry_for(entries, MockAreaIds.KITCHEN)
    assert await hass.config_entries.async_reload(kitchen.entry_id)
    await hass.async_block_till_done()

    assert "Error" not in caplog.text
    assert all(
        area.slug != MockAreaIds.FIRST_FLOOR.value for area in iter_runtime_areas(hass)
    )
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == _expected_child_aggregates(hass)


def _sensor_aggregates_for(hass, areas: tuple[MockAreaIds, ...]) -> list[str]:
    """Registry ground truth for sensor aggregates of the given child Areas."""
    registry = async_get_entity_registry(hass)
    prefixes = tuple(
        f"sensor.adaptive_areas_aggregates_{area.value}_aggregate_" for area in areas
    )
    return sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.entity_id.startswith(prefixes)
    )


async def test_meta_sensor_aggregates_registered_late_are_included(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sensor aggregates registered after the Meta Areas loaded are listed too."""
    temperature_sources = {
        area: [
            MockSensor(
                name=f"temperature_{area.value}",
                unique_id=f"temperature_{area.value}",
                native_value=21.5,
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            )
        ]
        for area in CHILD_AREAS
    }
    await setup_mock_entities(hass, "sensor", temperature_sources)
    entries = _entries()
    gate = asyncio.Event()
    meta_loads = {MockAreaIds.FIRST_FLOOR.value: 0, MockAreaIds.GLOBAL.value: 0}
    meta_ready = asyncio.Event()

    original_load = AdaptiveMetaArea.load_entities

    async def observed_load(self) -> None:
        await original_load(self)
        if self.slug in meta_loads:
            meta_loads[self.slug] += 1
            if all(count >= 2 for count in meta_loads.values()):
                meta_ready.set()

    original_setup_area = sensor_platform._async_setup_area

    async def gated_setup_area(hass_, area, async_add_entities) -> None:
        if area.slug != MockAreaIds.KITCHEN.value:
            return await original_setup_area(hass_, area, async_add_entities)

        def deferred_add(entities, update_before_add: bool = False) -> None:
            async def _add() -> None:
                await gate.wait()
                async_add_entities(entities, update_before_add)

            hass_.async_create_task(_add())

        return await original_setup_area(hass_, area, deferred_add)

    monkeypatch.setattr(AdaptiveMetaArea, "load_entities", observed_load)
    monkeypatch.setattr(sensor_platform, "_async_setup_area", gated_setup_area)

    setup = hass.async_create_task(
        init_integration(hass, entries, areas=list(CHILD_AREAS))
    )
    await meta_ready.wait()
    assert not any(
        MockAreaIds.KITCHEN.value in entity_id
        for entity_id in _sensor_aggregates_for(hass, (MockAreaIds.KITCHEN,))
    )

    gate.set()
    await setup
    await hass.async_block_till_done()

    expected = _sensor_aggregates_for(hass, CHILD_AREAS)
    assert any(MockAreaIds.KITCHEN.value in entity_id for entity_id in expected)
    (floor,) = [
        a for a in iter_runtime_areas(hass) if a.slug == MockAreaIds.FIRST_FLOOR.value
    ]
    listed = sorted(
        entity["entity_id"]
        for entity in floor.entities.get("sensor", [])
        if "_aggregate_" in entity["entity_id"]
    )
    assert listed == expected


async def test_removed_child_aggregates_leave_meta_sources(hass) -> None:
    """Removing a child entry must not leave its aggregates in Meta sources."""
    await _setup_child_sources(hass)
    entries = _entries()
    await init_integration(hass, entries, areas=list(CHILD_AREAS))
    await hass.async_block_till_done()
    full = _expected_child_aggregates(hass)
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == full

    kitchen = _entry_for(entries, MockAreaIds.KITCHEN)
    assert await hass.config_entries.async_remove(kitchen.entry_id)
    await hass.async_block_till_done()

    remaining = [entity_id for entity_id in full if "kitchen" not in entity_id]
    assert _expected_child_aggregates(hass) == remaining
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == remaining
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == remaining


async def test_removed_single_child_entity_leaves_meta_sources(hass) -> None:
    """Removing one child aggregate from the registry drops it from Meta sources."""
    await _setup_child_sources(hass)
    await init_integration(hass, _entries(), areas=list(CHILD_AREAS))
    await hass.async_block_till_done()
    full = _expected_child_aggregates(hass)
    victim = "binary_sensor.adaptive_areas_aggregates_kitchen_aggregate_motion"
    assert victim in full

    async_get_entity_registry(hass).async_remove(victim)
    await hass.async_block_till_done()

    remaining = [entity_id for entity_id in full if entity_id != victim]
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == remaining
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == remaining


async def _setup_interior_exterior(hass) -> list[MockConfigEntry]:
    """Set up one interior and one exterior child with Interior/Exterior/Global Metas."""
    sources = {
        area: [
            MockBinarySensor(
                name=f"motion_{area.value}",
                unique_id=f"motion_{area.value}",
                device_class=BinarySensorDeviceClass.MOTION,
            )
        ]
        for area in (MockAreaIds.KITCHEN, MockAreaIds.BACKYARD)
    }
    await setup_mock_entities(hass, "binary_sensor", sources)
    entries = []
    for area in (
        MockAreaIds.KITCHEN,
        MockAreaIds.BACKYARD,
        MockAreaIds.INTERIOR,
        MockAreaIds.EXTERIOR,
        MockAreaIds.GLOBAL,
    ):
        data = get_basic_config_entry_data(area)
        data[CONF_ENABLED_FEATURES] = {
            CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
        }
        entries.append(MockConfigEntry(domain=DOMAIN, data=data))
    await init_integration(
        hass, entries, areas=[MockAreaIds.KITCHEN, MockAreaIds.BACKYARD]
    )
    await hass.async_block_till_done()
    return entries


async def test_removed_interior_child_leaves_only_interior_and_global(hass) -> None:
    """Removing an interior child updates Interior and Global, not Exterior."""
    entries = await _setup_interior_exterior(hass)
    exterior_before = _meta_sources(hass, MockAreaIds.EXTERIOR)
    assert exterior_before

    kitchen = _entry_for(entries, MockAreaIds.KITCHEN)
    assert await hass.config_entries.async_remove(kitchen.entry_id)
    await hass.async_block_till_done()

    assert _meta_sources(hass, MockAreaIds.INTERIOR) == []
    assert _meta_sources(hass, MockAreaIds.EXTERIOR) == exterior_before
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == exterior_before


async def test_child_unload_then_reload_restores_sources_without_duplicates(
    hass,
) -> None:
    """A temporary child unload keeps registry identity; reload restores one copy."""
    await _setup_child_sources(hass)
    entries = _entries()
    await init_integration(hass, entries, areas=list(CHILD_AREAS))
    await hass.async_block_till_done()
    expected = _expected_child_aggregates(hass)

    kitchen = _entry_for(entries, MockAreaIds.KITCHEN)
    assert await hass.config_entries.async_unload(kitchen.entry_id)
    await hass.async_block_till_done()
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == expected

    assert await hass.config_entries.async_setup(kitchen.entry_id)
    await hass.async_block_till_done()
    sources = _meta_sources(hass, MockAreaIds.FIRST_FLOOR)
    assert sources == expected
    assert len(sources) == len(set(sources))


async def test_unrelated_registry_removal_does_not_refresh_meta(
    hass, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing an entity that is not a Meta source triggers no refresh."""
    await _setup_child_sources(hass)
    await init_integration(hass, _entries(), areas=list(CHILD_AREAS))
    await hass.async_block_till_done()

    calls: list[str] = []
    original = AdaptiveMetaArea.async_refresh_sources

    def counting(self) -> None:
        calls.append(self.slug)
        original(self)

    monkeypatch.setattr(AdaptiveMetaArea, "async_refresh_sources", counting)
    unrelated = MockBinarySensor(
        name="unrelated",
        unique_id="unrelated_outside",
        device_class=BinarySensorDeviceClass.MOTION,
    )
    await setup_mock_entities(hass, "binary_sensor", {MockAreaIds.GARAGE: [unrelated]})
    await hass.async_block_till_done()
    calls.clear()

    async_get_entity_registry(hass).async_remove(unrelated.entity_id)
    await hass.async_block_till_done()
    assert calls == []


async def test_global_entry_container_removal_updates_meta_sources(hass) -> None:
    """In a GlobalEntry container, removing a child entity updates Meta sources."""
    await _setup_child_sources(hass)
    areas = {area.value: get_basic_config_entry_data(area) for area in CHILD_AREAS}
    areas[MockAreaIds.FIRST_FLOOR.value] = get_basic_config_entry_data(
        MockAreaIds.FIRST_FLOOR
    )
    areas[MockAreaIds.GLOBAL.value] = get_basic_config_entry_data(MockAreaIds.GLOBAL)
    for data in areas.values():
        data[CONF_ENABLED_FEATURES] = {
            CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
        }
    container = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_AREAS: areas},
        version=2,
        minor_version=11,
    )
    await init_integration(hass, [container], areas=list(CHILD_AREAS))
    await hass.async_block_till_done()
    full = _expected_child_aggregates(hass)
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == full

    victim = "binary_sensor.adaptive_areas_aggregates_kitchen_aggregate_motion"
    async_get_entity_registry(hass).async_remove(victim)
    await hass.async_block_till_done()

    remaining = [entity_id for entity_id in full if entity_id != victim]
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == remaining
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == remaining


async def test_meta_entry_unload_then_reload_restores_correct_sources(hass) -> None:
    """Unloading and reloading a Meta entry restores its full, unique source list."""
    await _setup_child_sources(hass)
    entries = _entries()
    await init_integration(hass, entries, areas=list(CHILD_AREAS))
    await hass.async_block_till_done()
    expected = _expected_child_aggregates(hass)

    floor_entry = _entry_for(entries, MockAreaIds.FIRST_FLOOR)
    assert await hass.config_entries.async_unload(floor_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(floor_entry.entry_id)
    await hass.async_block_till_done()

    sources = _meta_sources(hass, MockAreaIds.FIRST_FLOOR)
    assert sources == expected
    assert len(sources) == len(set(sources))


async def test_burst_of_removals_drops_every_removed_source(hass) -> None:
    """Several removals in one burst leave no stale and no lost sources."""
    await _setup_child_sources(hass)
    await init_integration(hass, _entries(), areas=list(CHILD_AREAS))
    await hass.async_block_till_done()
    full = _expected_child_aggregates(hass)
    victims = [
        "binary_sensor.adaptive_areas_aggregates_kitchen_aggregate_motion",
        "binary_sensor.adaptive_areas_aggregates_living_room_aggregate_motion",
    ]
    assert all(victim in full for victim in victims)

    registry = async_get_entity_registry(hass)
    for victim in victims:
        registry.async_remove(victim)
    await hass.async_block_till_done()

    remaining = [entity_id for entity_id in full if entity_id not in victims]
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == remaining
    assert _meta_sources(hass, MockAreaIds.GLOBAL) == remaining
