"""Tests for the non-executing Single-GlobalEntry migration core."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.const import (
    ADAPTIVE_DEVICE_ID_PREFIX,
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    CONF_MIGRATION,
    DOMAIN,
    GLOBAL_ENTRY_UNIQUE_ID,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.migration import (
    GlobalEntryFactoryError,
    MigrationCleanupError,
    MigrationPhase,
    MigrationPrecheckError,
    MigrationRemoveError,
    MigrationState,
    MigrationVerifyResult,
    async_cleanup_migration,
    async_get_or_create_global_entry,
    async_remove_legacy_entries,
    get_global_entries,
    precheck,
    prepare_global_options,
    verify_prepared_configuration,
)
from tests.const import MockAreaIds
from tests.helpers import get_basic_config_entry_data


def _entry(area: MockAreaIds) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=get_basic_config_entry_data(area))


def test_precheck_prepares_lossless_multi_area_model() -> None:
    kitchen, living, global_meta = (
        MockConfigEntry(
            domain=DOMAIN,
            data=get_basic_config_entry_data(MockAreaIds.KITCHEN),
            options={"features": {"light_groups": {"overhead_lights": ["light.x"]}}},
        ),
        _entry(MockAreaIds.LIVING_ROOM),
        _entry(MockAreaIds.GLOBAL),
    )
    plan = precheck([kitchen, living, global_meta])
    prepared = prepare_global_options(plan)
    assert plan.target_creation_required
    assert set(prepared[CONF_AREAS]) == {"kitchen", "living_room", "global"}
    assert prepared[CONF_GLOBAL_OPTIONS] == {}
    assert verify_prepared_configuration(plan, prepared)


def test_precheck_blocks_duplicate_and_partial_state() -> None:
    first = _entry(MockAreaIds.KITCHEN)
    duplicate = _entry(MockAreaIds.KITCHEN)
    with pytest.raises(MigrationPrecheckError, match="duplicate"):
        precheck([first, duplicate])
    partial = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_MIGRATION: {"migration_phase": "invalid"}},
    )
    with pytest.raises((KeyError, ValueError)):
        precheck([first, partial])


def test_migration_state_round_trip() -> None:
    state = MigrationState(
        1, MigrationPhase.TRANSFER_CONFIG, ["old"], "new", ["kitchen"]
    )
    assert MigrationState.from_dict(state.as_dict()) == state


def _removal_fixture(hass, source_count: int = 1):
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_AREAS: {"kitchen": {}}, CONF_GLOBAL_OPTIONS: {}},
    )
    sources = [_entry(MockAreaIds.KITCHEN) for _ in range(source_count)]
    target.add_to_hass(hass)
    for source in sources:
        source.add_to_hass(hass)
        assert source.state is ConfigEntryState.NOT_LOADED
    state = MigrationState(
        1,
        MigrationPhase.REMOVE_OLD,
        [source.entry_id for source in sources],
        target.entry_id,
        ["kitchen"],
    )
    return target, sources, state


def _verified() -> MigrationVerifyResult:
    return MigrationVerifyResult(True, [], [])


async def test_remove_keeps_transferred_entity_and_device_identity(hass) -> None:
    target, (source,), state = _removal_fixture(hass)
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=target.entry_id,
        identifiers={(DOMAIN, f"{ADAPTIVE_DEVICE_ID_PREFIX}kitchen")},
    )
    device_registry.async_update_device(device.id, area_id="kitchen-area")
    entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "kitchen_temperature",
        config_entry=target,
        device_id=device.id,
    )
    result = await async_remove_legacy_entries(
        hass, state=state, verify_result=_verified()
    )
    current_entity = entity_registry.async_get(entity.entity_id)
    current_device = device_registry.async_get(device.id)
    assert result.removed_source_entry_ids == [source.entry_id]
    assert hass.config_entries.async_get_entry(source.entry_id) is None
    assert current_entity is not None
    assert current_entity.entity_id == entity.entity_id
    assert current_entity.unique_id == entity.unique_id
    assert current_entity.config_entry_id == target.entry_id
    assert current_device is not None
    assert current_device.id == device.id
    assert current_device.identifiers == device.identifiers
    assert current_device.area_id == "kitchen-area"
    assert current_device.config_entry_id == target.entry_id


async def test_remove_rejects_failed_verify_gate(hass) -> None:
    _target, _sources, state = _removal_fixture(hass)
    with pytest.raises(MigrationRemoveError, match="verification"):
        await async_remove_legacy_entries(
            hass, state=state, verify_result=MigrationVerifyResult(False, ["x"], [])
        )


async def test_remove_rejects_target_in_source_list(hass) -> None:
    target, _sources, state = _removal_fixture(hass)
    unsafe = MigrationState(
        1, MigrationPhase.REMOVE_OLD, [target.entry_id], target.entry_id, []
    )
    with pytest.raises(MigrationRemoveError, match="target"):
        await async_remove_legacy_entries(hass, state=unsafe, verify_result=_verified())


async def test_remove_rejects_remaining_entity_ownership(hass) -> None:
    _target, (source,), state = _removal_fixture(hass)
    async_get_entity_registry(hass).async_get_or_create(
        "sensor", DOMAIN, "legacy_kitchen", config_entry=source
    )
    with pytest.raises(MigrationRemoveError, match="entity ownership"):
        await async_remove_legacy_entries(hass, state=state, verify_result=_verified())


async def test_remove_rejects_remaining_device_ownership(hass) -> None:
    _target, (source,), state = _removal_fixture(hass)
    async_get_device_registry(hass).async_get_or_create(
        config_entry_id=source.entry_id,
        identifiers={(DOMAIN, f"{ADAPTIVE_DEVICE_ID_PREFIX}kitchen")},
    )
    with pytest.raises(MigrationRemoveError, match="device ownership"):
        await async_remove_legacy_entries(hass, state=state, verify_result=_verified())


async def test_partial_remove_persists_forward_recovery_and_retries(
    hass, monkeypatch
) -> None:
    target, sources, state = _removal_fixture(hass, 2)
    original_remove = hass.config_entries.async_remove
    calls: list[str] = []

    async def fail_second(entry_id: str) -> None:
        calls.append(entry_id)
        if len(calls) == 2:
            raise RuntimeError("boom")
        await original_remove(entry_id)

    monkeypatch.setattr(hass.config_entries, "async_remove", fail_second)
    with pytest.raises(MigrationRemoveError, match="failed to remove"):
        await async_remove_legacy_entries(hass, state=state, verify_result=_verified())
    partial = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert partial.removed_source_entry_ids == [calls[0]]
    assert hass.config_entries.async_get_entry(calls[1]) is not None

    monkeypatch.setattr(hass.config_entries, "async_remove", original_remove)
    retried = await async_remove_legacy_entries(
        hass, state=partial, verify_result=_verified()
    )
    assert retried.removed_source_entry_ids == calls
    assert set(calls) == {source.entry_id for source in sources}


async def test_remove_rejects_unexpected_missing_source(hass) -> None:
    _target, (source,), state = _removal_fixture(hass)
    await hass.config_entries.async_remove(source.entry_id)
    with pytest.raises(MigrationRemoveError, match="unexpectedly missing"):
        await async_remove_legacy_entries(hass, state=state, verify_result=_verified())


async def test_cleanup_completes_only_after_every_source_is_removed(hass) -> None:
    target, (source,), state = _removal_fixture(hass)
    with pytest.raises(MigrationCleanupError, match="remain"):
        await async_cleanup_migration(hass, state)
    await hass.config_entries.async_remove(source.entry_id)
    removed = MigrationState(
        1,
        MigrationPhase.REMOVE_OLD,
        state.source_entry_ids,
        target.entry_id,
        ["kitchen"],
        state.source_entry_ids,
    )
    complete = await async_cleanup_migration(hass, removed)
    assert complete.migration_phase is MigrationPhase.COMPLETE
    assert complete.source_entry_ids == []
    assert complete.removed_source_entry_ids == []
    assert (
        MigrationState.from_dict(target.options[CONF_MIGRATION]).migration_phase
        is MigrationPhase.COMPLETE
    )


async def test_complete_retry_is_a_noop(hass) -> None:
    _target, _sources, state = _removal_fixture(hass)
    complete = MigrationState(
        1,
        MigrationPhase.COMPLETE,
        state.source_entry_ids,
        state.target_entry_id,
        state.area_ids,
        state.source_entry_ids,
    )
    assert (
        await async_remove_legacy_entries(
            hass, state=complete, verify_result=_verified()
        )
        is complete
    )
    assert await async_cleanup_migration(hass, complete) is complete


async def test_cleanup_failure_keeps_recoverable_cleanup_checkpoint(
    hass, monkeypatch
) -> None:
    target, (source,), state = _removal_fixture(hass)
    await hass.config_entries.async_remove(source.entry_id)
    removed = MigrationState(
        1,
        MigrationPhase.REMOVE_OLD,
        state.source_entry_ids,
        target.entry_id,
        ["kitchen"],
        state.source_entry_ids,
    )
    original_update = hass.config_entries.async_update_entry
    update_calls = 0

    def fail_complete(*args, **kwargs):
        nonlocal update_calls
        update_calls += 1
        if update_calls == 2:
            raise RuntimeError("storage unavailable")
        return original_update(*args, **kwargs)

    monkeypatch.setattr(hass.config_entries, "async_update_entry", fail_complete)
    with pytest.raises(MigrationCleanupError, match="did not complete"):
        await async_cleanup_migration(hass, removed)
    assert (
        MigrationState.from_dict(target.options[CONF_MIGRATION]).migration_phase
        is MigrationPhase.CLEANUP
    )


async def test_restart_partial_remove_only_restores_checkpoint(hass) -> None:
    target, (_source,), state = _removal_fixture(hass)
    partial = MigrationState(
        1,
        MigrationPhase.REMOVE_OLD,
        state.source_entry_ids,
        state.target_entry_id,
        state.area_ids,
        [],
    )
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: partial.as_dict()}
    )
    restored = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert restored == partial
    assert hass.config_entries.async_get_entry(state.source_entry_ids[0]) is not None


async def test_restart_during_cleanup_can_resume_cleanup(hass) -> None:
    target, (source,), state = _removal_fixture(hass)
    await hass.config_entries.async_remove(source.entry_id)
    cleanup = MigrationState(
        1,
        MigrationPhase.CLEANUP,
        state.source_entry_ids,
        target.entry_id,
        ["kitchen"],
        state.source_entry_ids,
    )
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: cleanup.as_dict()}
    )
    restored = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert (
        await async_cleanup_migration(hass, restored)
    ).migration_phase is MigrationPhase.COMPLETE


async def test_factory_creates_and_reuses_registered_global_entry(hass) -> None:
    """The internal flow creates one real HA-managed container and reuses it."""
    entry = await async_get_or_create_global_entry(hass)
    assert entry.unique_id == "adaptive_areas_global"
    assert entry.options[CONF_AREAS] == {}
    assert await async_get_or_create_global_entry(hass) is entry
    assert get_global_entries(hass) == [entry]


async def test_factory_blocks_multiple_global_entries(hass) -> None:
    """Conflicting containers never cause a third factory flow."""
    first = MockConfigEntry(domain=DOMAIN, data={CONF_GLOBAL_ENTRY: True})
    second = MockConfigEntry(domain=DOMAIN, data={CONF_GLOBAL_ENTRY: True})
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    with pytest.raises(GlobalEntryFactoryError, match="multiple"):
        await async_get_or_create_global_entry(hass)
