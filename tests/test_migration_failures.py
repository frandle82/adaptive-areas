"""Failure boundaries for the explicit Single-GlobalEntry migration."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas import migration as migration_module
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
    MigrationPrecheckError,
    MigrationSnapshot,
    MigrationState,
    MigrationTransferError,
    MigrationPhase,
    async_activate_global_entry,
    async_get_or_create_global_entry,
    async_run_single_global_entry_migration,
    transfer_area_ownership,
    verify_global_entry,
)
from custom_components.adaptive_areas.repairs import (
    ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION,
    async_evaluate_single_global_entry_migration,
)
from tests.const import MockAreaIds
from tests.helpers import get_basic_config_entry_data


def _entry(area: MockAreaIds) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=get_basic_config_entry_data(area))


def test_persistent_store_keys_are_area_id_based() -> None:
    """Migration never needs an entry-ID rewrite for Energy or cleaning state."""
    from pathlib import Path

    energy_source = Path("custom_components/adaptive_areas/sensor/base.py").read_text()
    usage_source = Path(
        "custom_components/adaptive_areas/helpers/room_usage.py"
    ).read_text()
    assert 'f"{_ENERGY_STORAGE_KEY}.{area.id}"' in energy_source
    assert 'f"{STORAGE_KEY_PREFIX}.{area.id}"' in usage_source


def _verify_fixture(hass):
    """Create one valid transferred entity/device pair and its exact snapshot."""
    target = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    target.add_to_hass(hass)
    devices = async_get_device_registry(hass)
    device = devices.async_get_or_create(
        config_entry_id=target.entry_id,
        identifiers={(DOMAIN, f"{ADAPTIVE_DEVICE_ID_PREFIX}kitchen")},
    )
    entities = async_get_entity_registry(hass)
    entity = entities.async_get_or_create(
        "sensor", DOMAIN, "verify_kitchen", config_entry=target, device_id=device.id
    )
    snapshot = MigrationSnapshot(
        [
            {
                "entity_id": entity.entity_id,
                "unique_id": entity.unique_id,
                "config_entry_id": "legacy",
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
                "config_entries": ["legacy"],
                "area_id": None,
                "name": device.name,
                "name_by_user": device.name_by_user,
            }
        ],
    )
    return target, entity, device, snapshot


async def test_verify_success_is_read_only(hass) -> None:
    """A valid VERIFY has no registry or config side effects."""
    target, entity, device, snapshot = _verify_fixture(hass)
    before = (
        async_get_entity_registry(hass).async_get(entity.entity_id),
        async_get_device_registry(hass).async_get(device.id),
        dict(target.options),
    )
    assert verify_global_entry(hass, target, snapshot).success
    after = (
        async_get_entity_registry(hass).async_get(entity.entity_id),
        async_get_device_registry(hass).async_get(device.id),
        dict(target.options),
    )
    assert after == before


async def test_verify_collects_registry_identity_failures_without_mutating(
    hass,
) -> None:
    """Entity/device area and custom-name drift are reported together, never repaired."""
    target, entity, device, snapshot = _verify_fixture(hass)
    entities = async_get_entity_registry(hass)
    devices = async_get_device_registry(hass)
    entities.async_update_entity(entity.entity_id, name="changed", area_id="wrong-area")
    devices.async_update_device(device.id, area_id="wrong-area")
    before = (
        entities.async_get(entity.entity_id),
        devices.async_get(device.id),
        dict(target.options),
    )
    result = verify_global_entry(hass, target, snapshot)
    assert not result.success
    assert any("entity identity mismatch" in error for error in result.errors)
    assert any("device ownership mismatch" in error for error in result.errors)
    assert (
        entities.async_get(entity.entity_id),
        devices.async_get(device.id),
        dict(target.options),
    ) == before


async def test_factory_failure_preserves_every_legacy_entry(hass, monkeypatch) -> None:
    """A factory error happens before unload, registry transfer, or removal."""
    sources = [_entry(MockAreaIds.KITCHEN), _entry(MockAreaIds.LIVING_ROOM)]
    for source in sources:
        source.add_to_hass(hass)

    async def fail_factory(*_args, **_kwargs):
        raise GlobalEntryFactoryError("factory unavailable")

    monkeypatch.setattr(
        "custom_components.adaptive_areas.migration.async_get_or_create_global_entry",
        fail_factory,
    )
    with pytest.raises(GlobalEntryFactoryError):
        await async_run_single_global_entry_migration(hass)
    assert {entry.entry_id for entry in hass.config_entries.async_entries(DOMAIN)} == {
        entry.entry_id for entry in sources
    }


async def test_duplicate_legacy_area_id_blocks_before_factory(hass) -> None:
    """Precheck rejects ambiguous source ownership without destructive work."""
    first = _entry(MockAreaIds.KITCHEN)
    second = _entry(MockAreaIds.KITCHEN)
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    with pytest.raises(MigrationPrecheckError, match="duplicate"):
        await async_run_single_global_entry_migration(hass)
    assert hass.config_entries.async_entries(DOMAIN) == [first, second]


async def test_factory_rejects_invalid_result_without_mutating_legacy(
    hass, monkeypatch
) -> None:
    """An invalid ConfigFlow result cannot become a migration container."""
    source = _entry(MockAreaIds.KITCHEN)
    source.add_to_hass(hass)
    invalid = MockConfigEntry(domain=DOMAIN, unique_id="wrong-global")

    async def invalid_flow(*_args, **_kwargs):
        return {"type": "create_entry", "result": invalid}

    monkeypatch.setattr(hass.config_entries.flow, "async_init", invalid_flow)
    with pytest.raises(GlobalEntryFactoryError, match="invalid"):
        await async_get_or_create_global_entry(hass)
    assert hass.config_entries.async_entries(DOMAIN) == [source]


async def test_prepare_persistence_failure_stops_before_legacy_unload(
    hass, monkeypatch
) -> None:
    """A failed prepared-config checkpoint cannot advance to unload."""
    sources = [_entry(MockAreaIds.KITCHEN), _entry(MockAreaIds.LIVING_ROOM)]
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_GLOBAL_OPTIONS: {},
            CONF_AREAS: {},
            CONF_MIGRATION: MigrationState(
                1,
                MigrationPhase.PREPARE,
                [source.entry_id for source in sources],
                None,
                [MockAreaIds.KITCHEN.value, MockAreaIds.LIVING_ROOM.value],
            ).as_dict(),
        },
    )
    target.add_to_hass(hass)
    for source in sources:
        source.add_to_hass(hass)
    original_update = hass.config_entries.async_update_entry

    def fail_prepare(entry, **kwargs):
        if entry is target and CONF_MIGRATION in kwargs.get("options", {}):
            raise RuntimeError("storage unavailable")
        return original_update(entry, **kwargs)

    monkeypatch.setattr(hass.config_entries, "async_update_entry", fail_prepare)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await async_run_single_global_entry_migration(hass)
    assert all(entry.state is ConfigEntryState.NOT_LOADED for entry in sources)
    assert target.options[CONF_AREAS] == {}


async def test_partial_legacy_unload_stops_before_registry_transfer(
    hass, monkeypatch
) -> None:
    """A partial unload is never followed by ownership transfer or removal."""
    sources = [_entry(MockAreaIds.KITCHEN), _entry(MockAreaIds.LIVING_ROOM)]
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_GLOBAL_OPTIONS: {},
            CONF_AREAS: {
                MockAreaIds.KITCHEN.value: dict(sources[0].data),
                MockAreaIds.LIVING_ROOM.value: dict(sources[1].data),
            },
            CONF_MIGRATION: MigrationState(
                1,
                MigrationPhase.UNLOAD_OLD,
                [source.entry_id for source in sources],
                None,
                [MockAreaIds.KITCHEN.value, MockAreaIds.LIVING_ROOM.value],
            ).as_dict(),
        },
    )
    target.add_to_hass(hass)
    for source in sources:
        source.add_to_hass(hass)
    await hass.config_entries.async_unload(sources[0].entry_id)

    async def fail_unload(_hass, _entries):
        raise MigrationTransferError("legacy unload failed")

    monkeypatch.setattr(migration_module, "async_unload_legacy_entries", fail_unload)
    with pytest.raises(MigrationTransferError, match="legacy unload failed"):
        await async_run_single_global_entry_migration(hass)
    assert (
        target.options[CONF_MIGRATION]["migration_phase"] == MigrationPhase.UNLOAD_OLD
    )
    assert hass.config_entries.async_get_entry(sources[1].entry_id) is sources[1]


async def test_area_transfer_rolls_back_entities_when_device_transfer_fails(
    hass, monkeypatch
) -> None:
    """The per-Area ownership transfer is atomic across entities and device."""
    source = _entry(MockAreaIds.KITCHEN)
    target = MockConfigEntry(domain=DOMAIN)
    source.add_to_hass(hass)
    target.add_to_hass(hass)
    entity = async_get_entity_registry(hass).async_get_or_create(
        "sensor", DOMAIN, "kitchen_sensor", config_entry=source
    )

    def move_entities(*_args, **_kwargs):
        async_get_entity_registry(hass).async_update_entity(
            entity.entity_id, config_entry_id=target.entry_id
        )

    def fail_devices(*_args, **_kwargs):
        raise RuntimeError("device update failed")

    monkeypatch.setattr(
        migration_module, "transfer_area_entities_to_container", move_entities
    )
    monkeypatch.setattr(
        migration_module, "transfer_area_devices_to_container", fail_devices
    )
    with pytest.raises(MigrationTransferError, match="ownership transfer failed"):
        transfer_area_ownership(
            hass,
            old_entry_id=source.entry_id,
            global_entry_id=target.entry_id,
            area=object(),
        )
    assert (
        async_get_entity_registry(hass).async_get(entity.entity_id).config_entry_id
        == source.entry_id
    )


async def test_verify_failures_are_read_only_and_block_success(hass) -> None:
    """Identity, owner and duplicate churn violations are verification-only failures."""
    target = MockConfigEntry(domain=DOMAIN, data={CONF_GLOBAL_ENTRY: True})
    target.add_to_hass(hass)
    device_registry = async_get_device_registry(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=target.entry_id,
        identifiers={(DOMAIN, f"{ADAPTIVE_DEVICE_ID_PREFIX}kitchen")},
    )
    entity_registry = async_get_entity_registry(hass)
    entity = entity_registry.async_get_or_create(
        "sensor", DOMAIN, "kitchen_sensor", config_entry=target, device_id=device.id
    )
    snapshot = MigrationSnapshot(
        [
            {
                "entity_id": entity.entity_id,
                "unique_id": entity.unique_id,
                "config_entry_id": "legacy",
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
                "config_entries": ["legacy"],
                "area_id": None,
                "name": device.name,
                "name_by_user": device.name_by_user,
            }
        ],
    )
    before_entity = entity_registry.async_get(entity.entity_id)
    before_device = device_registry.async_get(device.id)
    result = verify_global_entry(hass, target, snapshot)
    assert not result.success
    assert "missing global options" in result.errors
    assert entity_registry.async_get(entity.entity_id) == before_entity
    assert device_registry.async_get(device.id) == before_device


async def test_verify_blocks_churned_suffix_entity_id(hass) -> None:
    """A generated ``_2`` ID is evidence of registry churn, never a success."""
    target = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    target.add_to_hass(hass)
    entity = async_get_entity_registry(hass).async_get_or_create(
        "sensor", DOMAIN, "migration_churn_2", config_entry=target
    )
    result = verify_global_entry(hass, target, MigrationSnapshot([], []))
    assert not result.success
    assert "duplicate generated entity id" in result.errors
    assert async_get_entity_registry(hass).async_get(entity.entity_id) is entity


def _transfer_checkpoint(hass):
    """Create a three-source transfer checkpoint without advancing its phase."""
    sources = [
        _entry(MockAreaIds.KITCHEN),
        _entry(MockAreaIds.LIVING_ROOM),
        _entry(MockAreaIds.MASTER_BEDROOM),
    ]
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    target.add_to_hass(hass)
    for source in sources:
        source.add_to_hass(hass)
    state = MigrationState(
        1,
        MigrationPhase.TRANSFER_REGISTRY,
        [source.entry_id for source in sources],
        target.entry_id,
        [
            MockAreaIds.KITCHEN.value,
            MockAreaIds.LIVING_ROOM.value,
            MockAreaIds.MASTER_BEDROOM.value,
        ],
    )
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: state.as_dict()}
    )
    return sources, target


async def test_multi_area_transfer_failure_rolls_back_completed_area(
    hass, monkeypatch
) -> None:
    """A failure in Area B restores Area A and never reaches activation."""
    sources, target = _transfer_checkpoint(hass)
    ordered_sources = sorted(sources, key=lambda source: source.entry_id)
    entity_registry = async_get_entity_registry(hass)
    first = entity_registry.async_get_or_create(
        "sensor", DOMAIN, "kitchen_transfer", config_entry=ordered_sources[0]
    )
    before_owner = first.config_entry_id
    calls: list[str] = []

    def fake_area(_hass, entry, _config=None):
        return SimpleNamespace(id=entry.data["id"])

    def transfer(hass, *, old_entry_id, global_entry_id, area):
        calls.append(old_entry_id)
        if old_entry_id == ordered_sources[1].entry_id:
            raise MigrationTransferError("Area B transfer failed")
        snapshot = migration_module.capture_registry_snapshot(hass, [old_entry_id])
        entity_registry.async_update_entity(
            first.entity_id, config_entry_id=global_entry_id
        )
        return snapshot

    async def forbidden_activation(*_args, **_kwargs):
        raise AssertionError("activation must not run after transfer failure")

    monkeypatch.setattr(
        "custom_components.adaptive_areas.helpers.area.get_adaptive_area_for_config_entry",
        fake_area,
    )
    monkeypatch.setattr(migration_module, "transfer_area_ownership", transfer)
    monkeypatch.setattr(
        migration_module, "async_activate_global_entry", forbidden_activation
    )
    with pytest.raises(MigrationTransferError, match="Area B transfer failed"):
        await async_run_single_global_entry_migration(hass)
    assert calls == [ordered_sources[0].entry_id, ordered_sources[1].entry_id]
    assert entity_registry.async_get(first.entity_id).config_entry_id == before_owner
    assert (
        MigrationState.from_dict(target.options[CONF_MIGRATION]).migration_phase
        is MigrationPhase.TRANSFER_REGISTRY
    )
    assert all(
        hass.config_entries.async_get_entry(source.entry_id) is source
        for source in sources
    )


async def test_rollback_failure_stays_at_transfer_registry(hass, monkeypatch) -> None:
    """A failed rollback is surfaced as an unrecoverable transfer error, not success."""
    source = _entry(MockAreaIds.KITCHEN)
    target = MockConfigEntry(domain=DOMAIN)
    source.add_to_hass(hass)
    target.add_to_hass(hass)
    entity = async_get_entity_registry(hass).async_get_or_create(
        "sensor", DOMAIN, "rollback_failure", config_entry=source
    )

    def move_entities(*_args, **_kwargs):
        async_get_entity_registry(hass).async_update_entity(
            entity.entity_id, config_entry_id=target.entry_id
        )

    monkeypatch.setattr(
        migration_module, "transfer_area_entities_to_container", move_entities
    )
    monkeypatch.setattr(
        migration_module,
        "transfer_area_devices_to_container",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("device failed")),
    )
    monkeypatch.setattr(
        migration_module,
        "rollback_registry_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("rollback failed")
        ),
    )
    with pytest.raises(MigrationTransferError, match="transfer and rollback failed"):
        transfer_area_ownership(
            hass,
            old_entry_id=source.entry_id,
            global_entry_id=target.entry_id,
            area=object(),
        )


async def test_activation_failure_returns_to_transfer_registry_without_remove(
    hass, monkeypatch
) -> None:
    """Activation errors cleanly stop before VERIFY, REMOVE and CLEANUP."""
    sources, target = _transfer_checkpoint(hass)
    state = MigrationState(
        1,
        MigrationPhase.ACTIVATE_GLOBAL,
        [source.entry_id for source in sources],
        target.entry_id,
        [
            MockAreaIds.KITCHEN.value,
            MockAreaIds.LIVING_ROOM.value,
            MockAreaIds.MASTER_BEDROOM.value,
        ],
    )
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: state.as_dict()}
    )
    calls = 0

    async def fail_activation(*_args, **_kwargs):
        raise MigrationTransferError("runtime count mismatch")

    async def forbidden_remove(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("remove must not run")

    monkeypatch.setattr(
        migration_module, "async_activate_global_entry", fail_activation
    )
    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", forbidden_remove
    )
    with pytest.raises(MigrationTransferError, match="runtime count mismatch"):
        await async_run_single_global_entry_migration(hass)
    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.migration_phase is MigrationPhase.TRANSFER_REGISTRY
    assert calls == 0
    assert [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.unique_id == GLOBAL_ENTRY_UNIQUE_ID
    ] == [target]


@pytest.mark.parametrize(
    "runtime_ids",
    [
        [MockAreaIds.KITCHEN.value, MockAreaIds.LIVING_ROOM.value],
        [
            MockAreaIds.KITCHEN.value,
            MockAreaIds.KITCHEN.value,
            MockAreaIds.MASTER_BEDROOM.value,
        ],
        [
            MockAreaIds.KITCHEN.value,
            MockAreaIds.LIVING_ROOM.value,
            MockAreaIds.DINING_ROOM.value,
        ],
    ],
    ids=["count", "duplicate", "wrong-area"],
)
async def test_activation_rejects_invalid_runtime_area_set(
    hass, monkeypatch, runtime_ids
) -> None:
    """Activation rejects incomplete, duplicate and wrong-Area container runtimes."""
    target = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_GLOBAL_ENTRY: True},
        options={
            CONF_AREAS: {
                MockAreaIds.KITCHEN.value: {},
                MockAreaIds.LIVING_ROOM.value: {},
                MockAreaIds.MASTER_BEDROOM.value: {},
            },
        },
    )
    target.add_to_hass(hass)
    unloads = 0

    async def successful_setup(_entry_id):
        return True

    async def tracked_unload(_entry_id):
        nonlocal unloads
        unloads += 1
        return True

    monkeypatch.setattr(hass.config_entries, "async_setup", successful_setup)
    monkeypatch.setattr(hass.config_entries, "async_unload", tracked_unload)
    monkeypatch.setattr(
        "custom_components.adaptive_areas.helpers.area.get_runtime_areas_for_entry",
        lambda *_args: [SimpleNamespace(id=area_id) for area_id in runtime_ids],
    )
    with pytest.raises(MigrationTransferError, match="activation failed"):
        await async_activate_global_entry(hass, target)
    assert unloads == 1


async def test_verify_blocks_missing_entity_and_replacement(hass) -> None:
    """A replacement cannot satisfy a snapshot whose original entity disappeared."""
    target, entity, _device, snapshot = _verify_fixture(hass)
    registry = async_get_entity_registry(hass)
    registry.async_remove(entity.entity_id)
    replacement = registry.async_get_or_create(
        "sensor", DOMAIN, "verify_kitchen_2", config_entry=target
    )
    result = verify_global_entry(hass, target, snapshot)
    assert not result.success
    assert f"missing entity: {entity.entity_id}" in result.errors
    assert registry.async_get(replacement.entity_id) is replacement


async def test_verify_blocks_wrong_entity_owner_and_device_link(hass) -> None:
    """Owner and device-link drift are failures without any registry repair."""
    target, entity, device, snapshot = _verify_fixture(hass)
    legacy = MockConfigEntry(domain=DOMAIN)
    legacy.add_to_hass(hass)
    entities = async_get_entity_registry(hass)
    entities.async_update_entity(
        entity.entity_id, config_entry_id=legacy.entry_id, device_id=None
    )
    before = entities.async_get(entity.entity_id)
    result = verify_global_entry(hass, target, snapshot)
    assert not result.success
    assert f"entity ownership mismatch: {entity.entity_id}" in result.errors
    assert entities.async_get(entity.entity_id) == before
    assert device.id == snapshot.entities[0]["device_id"]


async def test_verify_blocks_wrong_device_owner(hass) -> None:
    """The original device must retain GlobalEntry ownership."""
    target, entity, device, snapshot = _verify_fixture(hass)
    devices = async_get_device_registry(hass)
    devices.async_update_device(device.id, remove_config_entry_id=target.entry_id)
    before = devices.async_get(device.id)
    result = verify_global_entry(hass, target, snapshot)
    assert not result.success
    assert f"missing device: {device.id}" in result.errors
    assert devices.async_get(device.id) == before is None
    assert async_get_entity_registry(hass).async_get(entity.entity_id) is None


@pytest.mark.parametrize("missing", ["entity", "device"])
async def test_orchestrated_verify_failure_never_reaches_remove_or_cleanup(
    hass, monkeypatch, missing
) -> None:
    """VERIFY failures retain legacy entries and the Repair boundary."""
    target, entity, device, snapshot = _verify_fixture(hass)
    source = _entry(MockAreaIds.KITCHEN)
    source.add_to_hass(hass)
    snapshot = MigrationSnapshot(
        [{**snapshot.entities[0], "config_entry_id": source.entry_id}],
        [{**snapshot.devices[0], "config_entries": [source.entry_id]}],
    )
    state = MigrationState(
        1,
        MigrationPhase.VERIFY,
        [source.entry_id],
        target.entry_id,
        [],
        snapshot=snapshot.as_dict(),
    )
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: state.as_dict()}
    )
    if missing == "entity":
        async_get_entity_registry(hass).async_remove(entity.entity_id)
    else:
        async_get_device_registry(hass).async_update_device(
            device.id, remove_config_entry_id=target.entry_id
        )
    remove_calls = 0

    async def forbidden_remove(*_args, **_kwargs):
        nonlocal remove_calls
        remove_calls += 1
        raise AssertionError("remove must not run")

    monkeypatch.setattr(
        migration_module, "async_remove_legacy_entries", forbidden_remove
    )
    with pytest.raises(MigrationTransferError, match="verification failed"):
        await async_run_single_global_entry_migration(hass)
    assert remove_calls == 0
    checkpoint = MigrationState.from_dict(target.options[CONF_MIGRATION])
    assert checkpoint.migration_phase is MigrationPhase.TRANSFER_REGISTRY
    assert hass.config_entries.async_get_entry(source.entry_id) is source
    await async_evaluate_single_global_entry_migration(hass)
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION)
        is not None
    )
    if missing == "entity":
        restored_device = async_get_device_registry(hass).async_get(device.id)
        assert restored_device is not None
        assert restored_device.config_entries == {source.entry_id}


async def test_verify_blocks_stale_original_device_and_replacement_link(hass) -> None:
    """A legal replacement Device cannot hide entity device-link churn."""
    target, entity, original, snapshot = _verify_fixture(hass)
    devices = async_get_device_registry(hass)
    replacement = devices.async_get_or_create(
        config_entry_id=target.entry_id,
        identifiers={(DOMAIN, f"{ADAPTIVE_DEVICE_ID_PREFIX}kitchen_replacement")},
    )
    entities = async_get_entity_registry(hass)
    entities.async_update_entity(entity.entity_id, device_id=replacement.id)
    before = (
        entities.async_get(entity.entity_id),
        devices.async_get(original.id),
        devices.async_get(replacement.id),
        dict(target.options),
    )
    result = verify_global_entry(hass, target, snapshot)
    assert not result.success
    assert f"entity identity mismatch: {entity.entity_id}" in result.errors
    assert devices.async_get(original.id) is not None
    assert (
        entities.async_get(entity.entity_id),
        devices.async_get(original.id),
        devices.async_get(replacement.id),
        dict(target.options),
    ) == before


async def test_verify_blocks_regular_device_identifier_change(hass) -> None:
    """A supported Device Registry identifier update invalidates the snapshot."""
    target, _entity, device, snapshot = _verify_fixture(hass)
    devices = async_get_device_registry(hass)
    devices.async_update_device(
        device.id,
        new_identifiers={(DOMAIN, f"{ADAPTIVE_DEVICE_ID_PREFIX}kitchen_changed")},
    )
    result = verify_global_entry(hass, target, snapshot)
    assert not result.success
    assert f"device identifiers mismatch: {device.id}" in result.errors
