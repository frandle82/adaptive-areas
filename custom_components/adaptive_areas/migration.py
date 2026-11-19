"""Pure planning primitives for the deferred Single-GlobalEntry migration."""

import asyncio
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import (
    async_entries_for_config_entry,
)
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    CONF_ID,
    CONF_MIGRATION,
    GLOBAL_ENTRY_UNIQUE_ID,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.helpers.area import (
    transfer_area_devices_to_container,
    transfer_area_entities_to_container,
)

_LOGGER = logging.getLogger(__name__)


class MigrationPhase(StrEnum):
    """Persisted checkpoints; execution is intentionally not wired yet."""

    PRECHECK = "precheck"
    PREPARE = "prepare"
    TRANSFER_CONFIG = "transfer_config"
    UNLOAD_OLD = "unload_old"
    TRANSFER_REGISTRY = "transfer_registry"
    TRANSFER_STORES = "transfer_stores"
    ACTIVATE_GLOBAL = "activate_global"
    VERIFY = "verify"
    REMOVE_OLD = "remove_old"
    CLEANUP = "cleanup"
    COMPLETE = "complete"


@dataclass(frozen=True)
class MigrationState:
    """Minimal restart-safe state kept on the future GlobalEntry."""

    migration_version: int
    migration_phase: MigrationPhase
    source_entry_ids: list[str]
    target_entry_id: str | None
    area_ids: list[str]
    removed_source_entry_ids: list[str] = field(default_factory=list)
    snapshot: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize this persisted migration checkpoint."""
        data = asdict(self)
        data["migration_phase"] = self.migration_phase.value
        data["removed_source_entry_ids"] = self.removed_source_entry_ids
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MigrationState:
        """Restore one persisted migration checkpoint."""
        return cls(
            migration_version=int(data["migration_version"]),
            migration_phase=MigrationPhase(data["migration_phase"]),
            source_entry_ids=list(data["source_entry_ids"]),
            target_entry_id=data.get("target_entry_id"),
            area_ids=list(data["area_ids"]),
            removed_source_entry_ids=list(data.get("removed_source_entry_ids", [])),
            snapshot=data.get("snapshot"),
        )


@dataclass(frozen=True)
class MigrationSnapshot:
    """Serializable recovery envelope; registry capture is added in block 3."""

    entities: list[dict[str, Any]]
    devices: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        """Serialize registry recovery data."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MigrationSnapshot:
        """Restore registry recovery data."""
        return cls(list(data.get("entities", [])), list(data.get("devices", [])))


def capture_registry_snapshot(
    hass: HomeAssistant, source_entry_ids: list[str]
) -> MigrationSnapshot:
    """Capture ownership and user-facing registry state before a future transfer."""
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    entities = [
        {
            "entity_id": entry.entity_id,
            "unique_id": entry.unique_id,
            "config_entry_id": entry.config_entry_id,
            "device_id": entry.device_id,
            "area_id": entry.area_id,
            "name": entry.name,
            "disabled_by": entry.disabled_by,
            "hidden_by": entry.hidden_by,
        }
        for source_id in source_entry_ids
        for entry in entity_registry.entities.get_entries_for_config_entry_id(source_id)
    ]
    devices = [
        {
            "id": device.id,
            "identifiers": list(device.identifiers),
            "config_entries": [device.config_entry_id],
            "area_id": device.area_id,
            "name": device.name,
            "name_by_user": device.name_by_user,
        }
        for source_id in source_entry_ids
        for device in async_entries_for_config_entry(device_registry, source_id)
    ]
    return MigrationSnapshot(entities, devices)


def rollback_registry_snapshot(
    hass: HomeAssistant, snapshot: MigrationSnapshot
) -> None:
    """Restore ownership only; all user-facing registry attributes stay untouched."""
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    for entity in snapshot.entities:
        if entity_registry.async_get(entity["entity_id"]) is not None:
            entity_registry.async_update_entity(
                entity["entity_id"], config_entry_id=entity["config_entry_id"]
            )
    for device in snapshot.devices:
        current = device_registry.async_get(device["id"])
        if current is None:
            continue
        previous = set(device["config_entries"])
        # A device has exactly one owner in HA 2026.10+, so restoring ownership is
        # an immediate move to the single legacy entry (not add/remove calls).
        if len(previous) == 1 and current.config_entry_id not in previous:
            (legacy_entry_id,) = previous
            device_registry.async_update_device(
                current.id, new_config_entry_id=legacy_entry_id
            )


@dataclass(frozen=True)
class MigrationPlan:
    """Side-effect-free precheck result."""

    sources: list[ConfigEntry]
    target: ConfigEntry | None
    target_creation_required: bool
    areas: dict[str, dict[str, Any]]


class MigrationPrecheckError(ValueError):
    """The migration cannot safely be planned."""


class GlobalEntryFactoryError(RuntimeError):
    """Home Assistant did not provide a valid GlobalEntry factory result."""


class MigrationTransferError(RuntimeError):
    """Ownership transfer or recovery did not complete safely."""


class MigrationRemoveError(RuntimeError):
    """Legacy entries cannot safely cross the forward-recovery boundary."""


class MigrationCleanupError(RuntimeError):
    """Temporary migration metadata could not be cleaned up safely."""


@dataclass(frozen=True)
class MigrationVerifyResult:
    """Read-only result of the isolated activation verification gate."""

    success: bool
    errors: list[str]
    warnings: list[str]


def is_global_entry(entry: ConfigEntry) -> bool:
    """Identify a container through its dedicated persisted marker."""
    return (
        entry.unique_id == GLOBAL_ENTRY_UNIQUE_ID
        or bool(entry.data.get(CONF_GLOBAL_ENTRY))
        or bool(entry.options.get(CONF_GLOBAL_ENTRY))
    )


def effective_area_config(entry: ConfigEntry) -> dict[str, Any]:
    """Match legacy runtime semantics without deriving defaults."""
    config = dict(entry.data)
    config.update(entry.options)
    return config


def precheck(entries: list[ConfigEntry]) -> MigrationPlan:
    """Validate legacy entries and build a mutation-free migration plan."""
    targets = [entry for entry in entries if is_global_entry(entry)]
    if len(targets) > 1:
        raise MigrationPrecheckError("multiple global entries")
    sources = [entry for entry in entries if not is_global_entry(entry)]
    if not sources:
        raise MigrationPrecheckError("no legacy entries")
    areas: dict[str, dict[str, Any]] = {}
    for entry in sources:
        if entry.version > AdaptiveConfigEntryVersion.MAJOR:
            raise MigrationPrecheckError("unsupported legacy version")
        config = effective_area_config(entry)
        area_id = config.get(CONF_ID)
        if not isinstance(area_id, str) or not area_id:
            raise MigrationPrecheckError("missing area id")
        if area_id in areas:
            raise MigrationPrecheckError("duplicate area id")
        areas[area_id] = config
    target = targets[0] if targets else None
    if target is not None and target.options.get(CONF_MIGRATION):
        MigrationState.from_dict(target.options[CONF_MIGRATION])
    return MigrationPlan(sources, target, target is None, areas)


def prepare_global_options(plan: MigrationPlan) -> dict[str, Any]:
    """Return the exact future GlobalEntry option model without persisting it."""
    return {CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: dict(plan.areas)}


def verify_prepared_configuration(
    plan: MigrationPlan, prepared: dict[str, Any]
) -> bool:
    """Ensure every effective legacy configuration is preserved byte-for-byte."""
    areas = prepared.get(CONF_AREAS)
    return isinstance(areas, dict) and areas == plan.areas


def get_global_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return actual container entries, never similarly named legacy entries."""
    return [
        entry for entry in hass.config_entries.async_entries() if is_global_entry(entry)
    ]


async def async_get_or_create_global_entry(
    hass: HomeAssistant, initial_options: dict[str, Any] | None = None
) -> ConfigEntry:
    """Create one registered migration container through HA's ConfigFlow manager."""
    lock = hass.data.setdefault(
        f"{GLOBAL_ENTRY_UNIQUE_ID}_factory_lock", asyncio.Lock()
    )
    async with lock:
        entries = get_global_entries(hass)
        if len(entries) > 1:
            raise GlobalEntryFactoryError("multiple global entries")
        if entries:
            entry = entries[0]
        else:
            result = await hass.config_entries.flow.async_init(
                "adaptive_areas",
                context={"source": "migration"},
                data=initial_options or {},
            )
            if result.get("type") != "create_entry" or not result.get("result"):
                raise GlobalEntryFactoryError(
                    "global entry factory did not create entry"
                )
            entry = result["result"]
        if (
            entry.domain != "adaptive_areas"
            or entry.unique_id != GLOBAL_ENTRY_UNIQUE_ID
            or entry.version != AdaptiveConfigEntryVersion.MAJOR
            or hass.config_entries.async_get_entry(entry.entry_id) is not entry
        ):
            raise GlobalEntryFactoryError("invalid global entry factory result")
        return entry


def transfer_area_ownership(
    hass: HomeAssistant,
    *,
    old_entry_id: str,
    global_entry_id: str,
    area: Any,
) -> MigrationSnapshot:
    """Atomically transfer one Area and roll it back on every local failure."""
    snapshot = capture_registry_snapshot(hass, [old_entry_id])
    try:
        transfer_area_entities_to_container(
            hass, old_entry_id=old_entry_id, global_entry_id=global_entry_id, area=area
        )
        transfer_area_devices_to_container(
            hass,
            old_entry_id=old_entry_id,
            global_entry_id=global_entry_id,
            area_id=area.id,
        )
    except Exception as err:
        try:
            rollback_registry_snapshot(hass, snapshot)
        except Exception as rollback_err:
            raise MigrationTransferError(
                "transfer and rollback failed"
            ) from rollback_err
        raise MigrationTransferError("ownership transfer failed") from err
    return snapshot


async def async_unload_legacy_entries(
    hass: HomeAssistant, entries: list[ConfigEntry]
) -> None:
    """Unload legacy entries only; deletion is guarded by the verify gate."""
    failed = [
        entry.entry_id
        for entry in entries
        if not await hass.config_entries.async_unload(entry.entry_id)
    ]
    if failed:
        raise MigrationTransferError(
            "failed to unload legacy entries: " + ", ".join(failed)
        )


def _remaining_source_entry_ids(state: MigrationState) -> list[str]:
    """Return source IDs in their persisted, deterministic removal order."""
    removed = set(state.removed_source_entry_ids or [])
    return [entry_id for entry_id in state.source_entry_ids if entry_id not in removed]


def _store_migration_state(
    hass: HomeAssistant, target: ConfigEntry, state: MigrationState
) -> None:
    """Persist a checkpoint without changing the prepared global configuration."""
    hass.config_entries.async_update_entry(
        target,
        options={**target.options, CONF_MIGRATION: state.as_dict()},
    )


def _validate_removal_preconditions(
    hass: HomeAssistant, state: MigrationState, verify_result: MigrationVerifyResult
) -> tuple[ConfigEntry, list[ConfigEntry]]:
    """Reject every destructive removal unless the verified transfer is intact."""
    if not verify_result.success:
        raise MigrationRemoveError("global entry verification did not succeed")
    if state.target_entry_id is None:
        raise MigrationRemoveError("missing target entry id")
    if len(state.source_entry_ids) != len(set(state.source_entry_ids)):
        raise MigrationRemoveError("duplicate source entry id")
    if state.target_entry_id in state.source_entry_ids:
        raise MigrationRemoveError("target entry is listed as a source")

    target = hass.config_entries.async_get_entry(state.target_entry_id)
    if target is None or not is_global_entry(target):
        raise MigrationRemoveError("missing or invalid global target entry")

    sources: list[ConfigEntry] = []
    for entry_id in _remaining_source_entry_ids(state):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise MigrationRemoveError(f"source entry unexpectedly missing: {entry_id}")
        if entry.domain != "adaptive_areas" or is_global_entry(entry):
            raise MigrationRemoveError(f"invalid legacy source entry: {entry_id}")
        if entry.state is not ConfigEntryState.NOT_LOADED:
            raise MigrationRemoveError(
                f"legacy source entry is not unloaded: {entry_id}"
            )
        sources.append(entry)

    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    for entry in sources:
        if any(
            entity.platform == "adaptive_areas"
            for entity in entity_registry.entities.get_entries_for_config_entry_id(
                entry.entry_id
            )
        ):
            raise MigrationRemoveError(
                f"legacy entity ownership remains: {entry.entry_id}"
            )
        if any(
            any(
                domain == "adaptive_areas"
                and identifier.startswith("adaptive_area_device_")
                for domain, identifier in device.identifiers
            )
            for device in async_entries_for_config_entry(
                device_registry, entry.entry_id
            )
        ):
            raise MigrationRemoveError(
                f"legacy device ownership remains: {entry.entry_id}"
            )
    return target, sources


async def async_remove_legacy_entries(
    hass: HomeAssistant,
    *,
    state: MigrationState,
    verify_result: MigrationVerifyResult,
) -> MigrationState:
    """Remove verified source entries and checkpoint each irreversible success.

    Before the first successful removal registry rollback is possible.  Afterwards
    the persisted ``removed_source_entry_ids`` forms a forward-recovery boundary:
    removed entries are never recreated and retries only handle remaining sources.
    """
    if state.migration_phase is MigrationPhase.COMPLETE:
        return state
    target, sources = _validate_removal_preconditions(hass, state, verify_result)
    removed = list(state.removed_source_entry_ids or [])
    for entry in sorted(sources, key=lambda source: source.entry_id):
        _LOGGER.info("Removing legacy Adaptive Areas entry %s", entry.entry_id)
        try:
            await hass.config_entries.async_remove(entry.entry_id)
        except Exception as err:
            checkpoint = MigrationState(
                state.migration_version,
                MigrationPhase.REMOVE_OLD,
                state.source_entry_ids,
                state.target_entry_id,
                state.area_ids,
                removed,
                state.snapshot,
            )
            _store_migration_state(hass, target, checkpoint)
            _LOGGER.warning(
                "Removing legacy Adaptive Areas entry %s failed", entry.entry_id
            )
            raise MigrationRemoveError(
                f"failed to remove source entry: {entry.entry_id}"
            ) from err
        removed.append(entry.entry_id)
        checkpoint = MigrationState(
            state.migration_version,
            MigrationPhase.REMOVE_OLD,
            state.source_entry_ids,
            state.target_entry_id,
            state.area_ids,
            removed,
            state.snapshot,
        )
        _store_migration_state(hass, target, checkpoint)
        _LOGGER.info("Legacy Adaptive Areas entry %s removed", entry.entry_id)
    return checkpoint if sources else state


async def async_cleanup_migration(
    hass: HomeAssistant, state: MigrationState
) -> MigrationState:
    """Discard temporary recovery metadata only after all sources are removed."""
    if state.migration_phase is MigrationPhase.COMPLETE:
        return state
    if set(state.source_entry_ids) != set(state.removed_source_entry_ids or []):
        raise MigrationCleanupError("legacy source entries remain")
    if state.target_entry_id is None:
        raise MigrationCleanupError("missing target entry id")
    target = hass.config_entries.async_get_entry(state.target_entry_id)
    if target is None or not is_global_entry(target):
        raise MigrationCleanupError("missing or invalid global target entry")
    if target.unique_id != GLOBAL_ENTRY_UNIQUE_ID:
        raise MigrationCleanupError("invalid global target unique id")
    if target.version != AdaptiveConfigEntryVersion.MAJOR:
        raise MigrationCleanupError("invalid global target version")
    if get_global_entries(hass) != [target]:
        raise MigrationCleanupError("global entry invariant failed")
    if any(
        hass.config_entries.async_get_entry(entry_id) is not None
        for entry_id in state.source_entry_ids
    ):
        raise MigrationCleanupError("legacy source entry still exists")
    configured = target.options.get(CONF_AREAS, target.data.get(CONF_AREAS, {}))
    if not isinstance(configured, dict) or not set(state.area_ids).issubset(configured):
        raise MigrationCleanupError("global areas invariant failed")

    cleanup_state = MigrationState(
        state.migration_version,
        MigrationPhase.CLEANUP,
        state.source_entry_ids,
        state.target_entry_id,
        state.area_ids,
        state.removed_source_entry_ids,
        state.snapshot,
    )
    _store_migration_state(hass, target, cleanup_state)
    complete_state = MigrationState(
        state.migration_version,
        MigrationPhase.COMPLETE,
        [],
        state.target_entry_id,
        [],
        [],
    )
    try:
        _store_migration_state(hass, target, complete_state)
    except Exception as err:
        raise MigrationCleanupError("migration cleanup did not complete") from err
    _LOGGER.info("Adaptive Areas Single-GlobalEntry migration cleanup completed")
    return complete_state


async def async_activate_global_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Activate one prepared GlobalEntry or clean up any partial runtime."""
    from custom_components.adaptive_areas.helpers.area import (
        get_runtime_areas_for_entry,
    )

    try:
        if entry.state is not ConfigEntryState.NOT_LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
        if not await hass.config_entries.async_setup(entry.entry_id):
            raise MigrationTransferError("global entry setup failed")
        # Meta aggregate managers discover child entities on the next loop turn.
        # VERIFY must observe that settled registry state, not an incomplete setup.
        await hass.async_block_till_done()
        configured = entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS, {}))
        runtime_ids = [area.id for area in get_runtime_areas_for_entry(hass, entry)]
        if (
            not isinstance(configured, dict)
            or set(runtime_ids) != set(configured)
            or len(runtime_ids) != len(set(runtime_ids))
        ):
            raise MigrationTransferError("global runtime area count mismatch")
    except Exception as err:
        await hass.config_entries.async_unload(entry.entry_id)
        raise MigrationTransferError("global entry activation failed") from err


def verify_global_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    snapshot: MigrationSnapshot,
) -> MigrationVerifyResult:
    """Verify configuration, runtime and transferred registry identity without mutation."""
    from custom_components.adaptive_areas.helpers.area import (
        get_runtime_areas_for_entry,
    )

    errors: list[str] = []
    configured = entry.options.get(CONF_AREAS, entry.data.get(CONF_AREAS, {}))
    if not isinstance(configured, dict):
        errors.append("invalid global areas configuration")
        configured = {}
    if CONF_GLOBAL_OPTIONS not in entry.options:
        errors.append("missing global options")
    runtime_ids = [area.id for area in get_runtime_areas_for_entry(hass, entry)]
    if set(runtime_ids) != set(configured) or len(runtime_ids) != len(set(runtime_ids)):
        errors.append("global runtime areas mismatch")
    entity_registry = async_get_entity_registry(hass)
    for saved in snapshot.entities:
        current = entity_registry.async_get(saved["entity_id"])
        if current is None:
            errors.append(f"missing entity: {saved['entity_id']}")
        elif current.unique_id != saved["unique_id"]:
            errors.append(f"entity unique id mismatch: {saved['entity_id']}")
        elif current.config_entry_id != entry.entry_id:
            errors.append(f"entity ownership mismatch: {saved['entity_id']}")
        elif any(
            getattr(current, field) != saved[field]
            for field in ("device_id", "area_id", "name", "disabled_by", "hidden_by")
        ):
            errors.append(f"entity identity mismatch: {saved['entity_id']}")
    device_registry = async_get_device_registry(hass)
    for saved in snapshot.devices:
        current = device_registry.async_get(saved["id"])
        if current is None:
            errors.append(f"missing device: {saved['id']}")
        elif (
            entry.entry_id != current.config_entry_id
            or current.area_id != saved["area_id"]
        ):
            errors.append(f"device ownership mismatch: {saved['id']}")
        elif set(current.identifiers) != set(saved["identifiers"]):
            errors.append(f"device identifiers mismatch: {saved['id']}")
    generated = [
        entity
        for entity in entity_registry.entities.get_entries_for_config_entry_id(
            entry.entry_id
        )
        if entity.platform == "adaptive_areas"
    ]
    unique_ids = [entity.unique_id for entity in generated]
    if len(unique_ids) != len(set(unique_ids)):
        errors.append("duplicate generated entity unique id")
    if any(entity.entity_id.rsplit("_", 1)[-1].isdigit() for entity in generated):
        errors.append("duplicate generated entity id")
    return MigrationVerifyResult(not errors, errors, [])


def _advance_state(
    hass: HomeAssistant,
    target: ConfigEntry,
    state: MigrationState,
    phase: MigrationPhase,
    *,
    snapshot: MigrationSnapshot | None = None,
) -> MigrationState:
    """Persist one successful checkpoint; phases always denote the next action."""
    advanced = MigrationState(
        state.migration_version,
        phase,
        state.source_entry_ids,
        state.target_entry_id,
        state.area_ids,
        state.removed_source_entry_ids,
        snapshot.as_dict() if snapshot is not None else state.snapshot,
    )
    _store_migration_state(hass, target, advanced)
    return advanced


async def async_run_single_global_entry_migration(  # noqa: C901
    hass: HomeAssistant,
) -> MigrationState:
    """Run the explicit Repair-only N→1 migration from its persisted checkpoint."""
    entries = hass.config_entries.async_entries("adaptive_areas")
    globals_ = get_global_entries(hass)
    if len(globals_) > 1:
        raise MigrationPrecheckError("multiple global entries")

    target = globals_[0] if globals_ else None
    state = (
        MigrationState.from_dict(target.options[CONF_MIGRATION])
        if target is not None and target.options.get(CONF_MIGRATION)
        else None
    )
    if state is not None and state.migration_phase is MigrationPhase.COMPLETE:
        return state

    if state is None:
        plan = precheck(entries)
        target = plan.target
        if plan.target_creation_required:
            factory_state = MigrationState(
                1,
                MigrationPhase.PREPARE,
                [entry.entry_id for entry in plan.sources],
                None,
                sorted(plan.areas),
            )
            target = await async_get_or_create_global_entry(
                hass,
                {
                    **prepare_global_options(plan),
                    CONF_MIGRATION: factory_state.as_dict(),
                },
            )
        if target is None or not is_global_entry(target):
            raise MigrationPrecheckError("missing global entry")
        state = MigrationState(
            1,
            MigrationPhase.PREPARE,
            [entry.entry_id for entry in plan.sources],
            target.entry_id,
            sorted(plan.areas),
        )
        _store_migration_state(hass, target, state)
    else:
        target = hass.config_entries.async_get_entry(state.target_entry_id or "")
        if target is None and state.target_entry_id is None and len(globals_) == 1:
            target = globals_[0]
            state = MigrationState(
                state.migration_version,
                state.migration_phase,
                state.source_entry_ids,
                target.entry_id,
                state.area_ids,
                state.removed_source_entry_ids,
                state.snapshot,
            )
            _store_migration_state(hass, target, state)
        if target is None or not is_global_entry(target):
            raise MigrationPrecheckError("missing persisted global entry")

    sources = [
        hass.config_entries.async_get_entry(entry_id)
        for entry_id in state.source_entry_ids
        if entry_id not in state.removed_source_entry_ids
    ]
    if any(source is None for source in sources):
        if state.migration_phase not in (
            MigrationPhase.REMOVE_OLD,
            MigrationPhase.CLEANUP,
        ):
            raise MigrationPrecheckError("persisted source entry is missing")
    source_entries = [source for source in sources if source is not None]

    if state.migration_phase is MigrationPhase.PREPARE:
        plan = precheck(source_entries)
        prepared = prepare_global_options(plan)
        hass.config_entries.async_update_entry(
            target,
            options={**target.options, **prepared, CONF_MIGRATION: state.as_dict()},
        )
        if not verify_prepared_configuration(plan, target.options):
            raise MigrationPrecheckError("prepared global configuration mismatch")
        state = _advance_state(hass, target, state, MigrationPhase.UNLOAD_OLD)

    if state.migration_phase is MigrationPhase.UNLOAD_OLD:
        await async_unload_legacy_entries(hass, source_entries)
        state = _advance_state(hass, target, state, MigrationPhase.TRANSFER_REGISTRY)

    if state.migration_phase is MigrationPhase.TRANSFER_REGISTRY:
        from custom_components.adaptive_areas.helpers.area import (
            get_adaptive_area_for_config_entry,
        )

        snapshots: list[MigrationSnapshot] = []
        try:
            for source in sorted(source_entries, key=lambda entry: entry.entry_id):
                area = get_adaptive_area_for_config_entry(hass, source)
                if area is None:
                    raise MigrationTransferError(
                        f"legacy Area unavailable: {source.entry_id}"
                    )
                snapshots.append(
                    transfer_area_ownership(
                        hass,
                        old_entry_id=source.entry_id,
                        global_entry_id=target.entry_id,
                        area=area,
                    )
                )
        except Exception:
            for snapshot in reversed(snapshots):
                rollback_registry_snapshot(hass, snapshot)
            raise
        snapshot = MigrationSnapshot(
            [entity for item in snapshots for entity in item.entities],
            [device for item in snapshots for device in item.devices],
        )
        state = _advance_state(
            hass, target, state, MigrationPhase.TRANSFER_STORES, snapshot=snapshot
        )

    if state.migration_phase is MigrationPhase.TRANSFER_STORES:
        # Stores are keyed by stable area ID and deliberately need no key rewrite.
        state = _advance_state(hass, target, state, MigrationPhase.ACTIVATE_GLOBAL)

    snapshot = MigrationSnapshot.from_dict(state.snapshot or {})
    if state.migration_phase is MigrationPhase.ACTIVATE_GLOBAL:
        try:
            await async_activate_global_entry(hass, target)
        except Exception:
            rollback_registry_snapshot(hass, snapshot)
            _advance_state(
                hass,
                target,
                state,
                MigrationPhase.TRANSFER_REGISTRY,
                snapshot=MigrationSnapshot([], []),
            )
            raise
        state = _advance_state(hass, target, state, MigrationPhase.VERIFY)

    if state.migration_phase is MigrationPhase.VERIFY:
        result = verify_global_entry(hass, target, snapshot)
        if not result.success:
            await hass.config_entries.async_unload(target.entry_id)
            rollback_registry_snapshot(hass, snapshot)
            _advance_state(
                hass,
                target,
                state,
                MigrationPhase.TRANSFER_REGISTRY,
                snapshot=MigrationSnapshot([], []),
            )
            raise MigrationTransferError(
                "verification failed: " + "; ".join(result.errors)
            )
        state = _advance_state(hass, target, state, MigrationPhase.REMOVE_OLD)

    if state.migration_phase is MigrationPhase.REMOVE_OLD:
        state = await async_remove_legacy_entries(
            hass, state=state, verify_result=verify_global_entry(hass, target, snapshot)
        )
        if set(state.source_entry_ids) == set(state.removed_source_entry_ids):
            state = _advance_state(hass, target, state, MigrationPhase.CLEANUP)

    if state.migration_phase is MigrationPhase.CLEANUP:
        state = await async_cleanup_migration(hass, state)
    return state
