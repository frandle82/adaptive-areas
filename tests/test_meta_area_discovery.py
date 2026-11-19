"""Meta Area source discovery stays complete regardless of Area setup order."""

import asyncio

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.base.adaptive import AdaptiveMetaArea
from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    DOMAIN,
)
from custom_components.adaptive_areas import binary_sensor as binary_sensor_platform
from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
from tests.const import MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
)
from tests.mocks import MockBinarySensor

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
    assert _meta_sources(hass, MockAreaIds.FIRST_FLOOR) == list(registered)

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
