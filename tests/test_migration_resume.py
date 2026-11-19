"""Restart-safe checkpoints for the Single-GlobalEntry migration."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.device_registry import (
    async_entries_for_config_entry,
)
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import (
    RegistryEntryDisabler,
    RegistryEntryHider,
    async_get as async_get_entity_registry,
)
from custom_components.adaptive_areas import migration as migration_module
from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    CONF_MIGRATION,
    DOMAIN,
    GLOBAL_ENTRY_UNIQUE_ID,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.helpers.area import get_runtime_areas_for_entry
from custom_components.adaptive_areas.migration import (
    MigrationRemoveError,
    MigrationPhase,
    MigrationState,
    async_run_single_global_entry_migration,
    async_unload_legacy_entries,
    get_global_entries,
)
from custom_components.adaptive_areas.repairs import (
    ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION,
    async_evaluate_single_global_entry_migration,
)
from tests.const import MockAreaIds
from tests.helpers import get_basic_config_entry_data, init_integration


async def _checkpoint_after_registry_transfer(hass, monkeypatch):
    """Create a real three-Area transfer checkpoint immediately before activation."""
    area_ids = [
        MockAreaIds.KITCHEN,
        MockAreaIds.LIVING_ROOM,
        MockAreaIds.MASTER_BEDROOM,
    ]
    sources = [
        MockConfigEntry(domain=DOMAIN, data=get_basic_config_entry_data(area))
        for area in area_ids
    ]
    await init_integration(hass, sources, areas=area_ids)
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    area_registry = async_get_area_registry(hass)
    for index, source in enumerate(sources):
        entity = next(
            entry
            for entry in entity_registry.entities.get_entries_for_config_entry_id(
                source.entry_id
            )
            if entry.platform == DOMAIN and entry.device_id is not None
        )
        entity_registry.async_update_entity(
            entity.entity_id,
            name=f"Custom {index}",
            disabled_by=RegistryEntryDisabler.USER,
            hidden_by=RegistryEntryHider.USER,
            area_id=area_registry.async_get_area_by_name(area_ids[index].value).id,
        )
        device_registry.async_update_device(
            entity.device_id,
            area_id=area_registry.async_get_area_by_name(area_ids[index].value).id,
        )
    await async_unload_legacy_entries(hass, sources)

    state = MigrationState(
        1,
        MigrationPhase.TRANSFER_REGISTRY,
        [entry.entry_id for entry in sources],
        None,
        [area.value for area in area_ids],
    )
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_GLOBAL_OPTIONS: {},
            CONF_AREAS: {
                area.value: get_basic_config_entry_data(area) for area in area_ids
            },
            CONF_MIGRATION: state.as_dict(),
        },
    )
    target.add_to_hass(hass)
    state = MigrationState(
        state.migration_version,
        state.migration_phase,
        state.source_entry_ids,
        target.entry_id,
        state.area_ids,
    )
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: state.as_dict()}
    )

    original_advance = migration_module._advance_state

    def stop_before_activation(hass, target, state, phase, **kwargs):
        advanced = original_advance(hass, target, state, phase, **kwargs)
        if phase is MigrationPhase.ACTIVATE_GLOBAL:
            raise RuntimeError("restart before activation")
        return advanced

    monkeypatch.setattr(migration_module, "_advance_state", stop_before_activation)
    with pytest.raises(RuntimeError, match="restart before activation"):
        await async_run_single_global_entry_migration(hass)
    monkeypatch.setattr(migration_module, "_advance_state", original_advance)
    return area_ids, sources, target


async def _checkpoint_before_remove(hass, monkeypatch):
    """Reach the verified removal boundary without removing a legacy entry."""
    area_ids, sources, target = await _checkpoint_after_registry_transfer(
        hass, monkeypatch
    )
    original_advance = migration_module._advance_state

    def stop_after_activation(hass, target, state, phase, **kwargs):
        advanced = original_advance(hass, target, state, phase, **kwargs)
        if phase is MigrationPhase.VERIFY:
            raise RuntimeError("restart after activation")
        return advanced

    monkeypatch.setattr(migration_module, "_advance_state", stop_after_activation)
    with pytest.raises(RuntimeError, match="restart after activation"):
        await async_run_single_global_entry_migration(hass)
    monkeypatch.setattr(migration_module, "_advance_state", original_advance)

    async def stop_before_remove(*_args, **_kwargs):
        raise RuntimeError("remove boundary")

    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", stop_before_remove
    )
    with pytest.raises(RuntimeError, match="remove boundary"):
        await async_run_single_global_entry_migration(hass)
    monkeypatch.undo()
    return area_ids, sources, target


def _registry_identity(hass, target):
    """Return the user-facing registry fields that a resume must preserve."""
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    entities = {
        entry.entity_id: (
            entry.entity_id,
            entry.unique_id,
            entry.config_entry_id,
            entry.device_id,
            entry.area_id,
            entry.name,
            entry.disabled_by,
            entry.hidden_by,
        )
        for entry in entity_registry.entities.get_entries_for_config_entry_id(
            target.entry_id
        )
        if entry.platform == DOMAIN
    }
    devices = {
        entry.id: (
            entry.id,
            entry.identifiers,
            {entry.config_entry_id},
            entry.area_id,
        )
        for entry in async_entries_for_config_entry(device_registry, target.entry_id)
    }
    return entities, devices


async def test_factory_resume_checkpoints_existing_container_without_recreating_it(
    hass, monkeypatch
) -> None:
    """A serialized factory checkpoint recovers its real registered target."""
    sources = [
        MockConfigEntry(domain=DOMAIN, data=get_basic_config_entry_data(area))
        for area in (MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM)
    ]
    state = MigrationState(
        1,
        MigrationPhase.PREPARE,
        [entry.entry_id for entry in sources],
        None,
        [area.value for area in (MockAreaIds.KITCHEN, MockAreaIds.LIVING_ROOM)],
    )
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_GLOBAL_OPTIONS: {},
            CONF_AREAS: {},
            CONF_MIGRATION: state.as_dict(),
        },
    )
    target.add_to_hass(hass)
    for source in sources:
        source.add_to_hass(hass)

    async def stop_before_unload(*_args, **_kwargs):
        raise RuntimeError("test interruption")

    factory_calls = 0

    async def forbidden_factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("existing target must not use the factory")

    monkeypatch.setattr(
        "custom_components.adaptive_areas.migration.async_unload_legacy_entries",
        stop_before_unload,
    )
    monkeypatch.setattr(
        "custom_components.adaptive_areas.migration.async_get_or_create_global_entry",
        forbidden_factory,
    )

    # Simulate persisted state loaded by a fresh orchestrator invocation.
    assert (
        MigrationState.from_dict(target.options[CONF_MIGRATION]).target_entry_id is None
    )
    with pytest.raises(RuntimeError, match="interruption"):
        await async_run_single_global_entry_migration(hass)

    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.target_entry_id == target.entry_id
    assert checkpoint.migration_phase is MigrationPhase.UNLOAD_OLD
    assert get_global_entries(hass) == [target]
    assert factory_calls == 0
    assert target.options[CONF_AREAS] == {
        MockAreaIds.KITCHEN.value: sources[0].data,
        MockAreaIds.LIVING_ROOM.value: sources[1].data,
    }


async def test_transfer_registry_restart_keeps_ownership_until_explicit_retry(
    hass, monkeypatch
) -> None:
    """A real registry transfer resumes at activation without identity churn."""
    area_ids, sources, target = await _checkpoint_after_registry_transfer(
        hass, monkeypatch
    )
    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.migration_phase is MigrationPhase.ACTIVATE_GLOBAL
    assert checkpoint.snapshot is not None
    before = _registry_identity(hass, target)
    assert before[0] and before[1]
    assert all(entry.state is ConfigEntryState.NOT_LOADED for entry in sources)
    assert get_runtime_areas_for_entry(hass, target) == []
    assert len({entry[4] for entry in before[0].values()}) == len(area_ids)

    await async_evaluate_single_global_entry_migration(hass)
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    # A restart only reloads persisted state; it never invokes the orchestrator.
    restored = MigrationState.from_dict(checkpoint.as_dict())
    assert restored.migration_phase is MigrationPhase.ACTIVATE_GLOBAL
    assert _registry_identity(hass, target) == before

    original_advance = migration_module._advance_state
    transfer_calls = 0
    real_transfer = migration_module.transfer_area_ownership

    def tracked_transfer(*args, **kwargs):
        nonlocal transfer_calls
        transfer_calls += 1
        return real_transfer(*args, **kwargs)

    def stop_after_activation(hass, target, state, phase, **kwargs):
        advanced = original_advance(hass, target, state, phase, **kwargs)
        if phase is MigrationPhase.VERIFY:
            raise RuntimeError("restart after activation")
        return advanced

    monkeypatch.setattr(migration_module, "transfer_area_ownership", tracked_transfer)
    monkeypatch.setattr(migration_module, "_advance_state", stop_after_activation)
    with pytest.raises(RuntimeError, match="restart after activation"):
        await async_run_single_global_entry_migration(hass)
    assert transfer_calls == 0
    assert _registry_identity(hass, target) == before
    assert all(
        hass.config_entries.async_get_entry(entry.entry_id) is entry
        for entry in sources
    )


async def test_activate_global_restart_does_not_duplicate_runtime_before_repair_retry(
    hass, monkeypatch
) -> None:
    """An activated container has one runtime per Area and resumes at verify."""
    area_ids, sources, target = await _checkpoint_after_registry_transfer(
        hass, monkeypatch
    )
    original_advance = migration_module._advance_state

    def stop_after_activation(hass, target, state, phase, **kwargs):
        advanced = original_advance(hass, target, state, phase, **kwargs)
        if phase is MigrationPhase.VERIFY:
            raise RuntimeError("restart after activation")
        return advanced

    monkeypatch.setattr(migration_module, "_advance_state", stop_after_activation)
    with pytest.raises(RuntimeError, match="restart after activation"):
        await async_run_single_global_entry_migration(hass)
    monkeypatch.setattr(migration_module, "_advance_state", original_advance)

    runtime_ids = [area.id for area in get_runtime_areas_for_entry(hass, target)]
    assert target.state is ConfigEntryState.LOADED
    assert set(runtime_ids) == {area.value for area in area_ids}
    assert len(runtime_ids) == len(set(runtime_ids))
    assert all(entry.state is ConfigEntryState.NOT_LOADED for entry in sources)
    before = _registry_identity(hass, target)
    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.migration_phase is MigrationPhase.VERIFY

    await async_evaluate_single_global_entry_migration(hass)
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    assert (
        MigrationState.from_dict(checkpoint.as_dict()).migration_phase
        is MigrationPhase.VERIFY
    )
    assert [
        area.id for area in get_runtime_areas_for_entry(hass, target)
    ] == runtime_ids

    async def stop_before_remove(*_args, **_kwargs):
        raise RuntimeError("remove boundary")

    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", stop_before_remove
    )
    with pytest.raises(RuntimeError, match="remove boundary"):
        await async_run_single_global_entry_migration(hass)
    assert [
        area.id for area in get_runtime_areas_for_entry(hass, target)
    ] == runtime_ids
    assert _registry_identity(hass, target) == before
    assert all(
        hass.config_entries.async_get_entry(entry.entry_id) is entry
        for entry in sources
    )


async def test_verify_resume_is_read_only_until_remove_old_is_explicitly_allowed(
    hass, monkeypatch
) -> None:
    """VERIFY can be repeated at the removal boundary without changing state."""
    _area_ids, sources, target = await _checkpoint_after_registry_transfer(
        hass, monkeypatch
    )
    original_advance = migration_module._advance_state

    def stop_after_activation(hass, target, state, phase, **kwargs):
        advanced = original_advance(hass, target, state, phase, **kwargs)
        if phase is MigrationPhase.VERIFY:
            raise RuntimeError("restart after activation")
        return advanced

    monkeypatch.setattr(migration_module, "_advance_state", stop_after_activation)
    with pytest.raises(RuntimeError, match="restart after activation"):
        await async_run_single_global_entry_migration(hass)
    monkeypatch.setattr(migration_module, "_advance_state", original_advance)
    before_identity = _registry_identity(hass, target)
    before_options = dict(target.options)

    async def stop_before_remove(*_args, **_kwargs):
        raise RuntimeError("remove boundary")

    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", stop_before_remove
    )
    with pytest.raises(RuntimeError, match="remove boundary"):
        await async_run_single_global_entry_migration(hass)
    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.migration_phase is MigrationPhase.REMOVE_OLD
    assert _registry_identity(hass, target) == before_identity
    assert target.options[CONF_AREAS] == before_options[CONF_AREAS]
    assert all(
        hass.config_entries.async_get_entry(entry.entry_id) is entry
        for entry in sources
    )


async def test_partial_remove_restart_only_removes_remaining_source_on_repair_retry(
    hass, monkeypatch
) -> None:
    """A persisted partial removal is forward-only and keeps registry identity."""
    _area_ids, sources, target = await _checkpoint_before_remove(hass, monkeypatch)
    before = _registry_identity(hass, target)
    original_remove = hass.config_entries.async_remove
    remove_calls: list[str] = []

    async def fail_third_remove(entry_id: str) -> None:
        remove_calls.append(entry_id)
        if len(remove_calls) == 3:
            raise RuntimeError("interrupted removal")
        await original_remove(entry_id)

    monkeypatch.setattr(hass.config_entries, "async_remove", fail_third_remove)
    with pytest.raises(MigrationRemoveError, match="failed to remove"):
        await async_run_single_global_entry_migration(hass)
    partial = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert partial.migration_phase is MigrationPhase.REMOVE_OLD
    assert partial.removed_source_entry_ids == remove_calls[:2]
    assert partial.snapshot is not None
    assert all(
        hass.config_entries.async_get_entry(entry_id) is None
        for entry_id in remove_calls[:2]
    )
    assert hass.config_entries.async_get_entry(remove_calls[2]) is not None
    assert _registry_identity(hass, target) == before

    restored = MigrationState.from_dict(partial.as_dict())
    assert restored == partial
    await async_evaluate_single_global_entry_migration(hass)
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    assert _registry_identity(hass, target) == before

    monkeypatch.setattr(hass.config_entries, "async_remove", original_remove)

    async def forbid_earlier_phase(*_args, **_kwargs):
        raise AssertionError("partial remove must not revisit an earlier phase")

    async def stop_at_cleanup(*_args, **_kwargs):
        raise RuntimeError("cleanup boundary")

    monkeypatch.setattr(
        migration_module, "async_get_or_create_global_entry", forbid_earlier_phase
    )
    monkeypatch.setattr(
        migration_module, "async_activate_global_entry", forbid_earlier_phase
    )
    monkeypatch.setattr(migration_module, "async_cleanup_migration", stop_at_cleanup)
    with pytest.raises(RuntimeError, match="cleanup boundary"):
        await async_run_single_global_entry_migration(hass)
    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.migration_phase is MigrationPhase.CLEANUP
    assert checkpoint.removed_source_entry_ids == remove_calls
    assert checkpoint.snapshot is not None
    assert all(
        hass.config_entries.async_get_entry(entry_id) is None
        for entry_id in remove_calls
    )
    assert _registry_identity(hass, target) == before


async def test_cleanup_resume_discards_only_temporary_migration_snapshot(
    hass, monkeypatch
) -> None:
    """A cleanup checkpoint keeps the active container and clears recovery data only."""
    _area_ids, sources, target = await _checkpoint_before_remove(hass, monkeypatch)

    async def stop_after_cleanup_checkpoint(*_args, **_kwargs):
        raise RuntimeError("complete boundary")

    monkeypatch.setattr(
        migration_module, "async_cleanup_migration", stop_after_cleanup_checkpoint
    )
    with pytest.raises(RuntimeError, match="complete boundary"):
        await async_run_single_global_entry_migration(hass)
    cleanup = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert cleanup.migration_phase is MigrationPhase.CLEANUP
    assert cleanup.snapshot is not None
    assert all(
        hass.config_entries.async_get_entry(entry.entry_id) is None for entry in sources
    )
    before = _registry_identity(hass, target)

    restored = MigrationState.from_dict(cleanup.as_dict())
    assert restored == cleanup
    await async_evaluate_single_global_entry_migration(hass)
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    assert _registry_identity(hass, target) == before

    monkeypatch.undo()
    complete = await async_run_single_global_entry_migration(hass)
    assert complete.migration_phase is MigrationPhase.COMPLETE
    assert complete.snapshot is None
    assert target.options[CONF_MIGRATION]["snapshot"] is None
    assert _registry_identity(hass, target) == before


async def test_complete_restart_is_a_noop_without_a_migration_repair(
    hass, monkeypatch
) -> None:
    """COMPLETE survives a state round-trip without recreating runtime or entries."""
    area_ids, sources, target = await _checkpoint_before_remove(hass, monkeypatch)
    complete = await async_run_single_global_entry_migration(hass)
    assert complete.migration_phase is MigrationPhase.COMPLETE
    before = _registry_identity(hass, target)
    runtime_ids = [area.id for area in get_runtime_areas_for_entry(hass, target)]
    assert set(runtime_ids) == {area.value for area in area_ids}
    assert len(runtime_ids) == len(set(runtime_ids))
    assert all(
        hass.config_entries.async_get_entry(entry.entry_id) is None for entry in sources
    )

    restored = MigrationState.from_dict(complete.as_dict())
    assert restored == complete
    assert await async_run_single_global_entry_migration(hass) == complete
    await async_evaluate_single_global_entry_migration(hass)
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION)
        is None
    )
    assert _registry_identity(hass, target) == before
    assert [
        area.id for area in get_runtime_areas_for_entry(hass, target)
    ] == runtime_ids
    assert len({entry[1] for entry in before[0].values()}) == len(before[0])
