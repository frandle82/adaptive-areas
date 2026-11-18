"""Isolation tests for the Repair-only Single-GlobalEntry migration trigger."""

from types import SimpleNamespace

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers import issue_registry as ir

from custom_components.adaptive_areas import async_setup_entry
from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    CONF_MIGRATION,
    DOMAIN,
    GLOBAL_ENTRY_UNIQUE_ID,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.adaptive_areas.migration import MigrationPhase, MigrationState
from custom_components.adaptive_areas.repairs import (
    ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION,
    SingleGlobalEntryMigrationRepairFlow,
    async_evaluate_single_global_entry_migration,
)
from custom_components.adaptive_areas.websocket import async_register_websocket_commands

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import get_basic_config_entry_data, init_integration


class _Connection:
    """Minimal WebSocket connection for the registered production handlers."""

    user = SimpleNamespace(is_admin=True)

    def __init__(self) -> None:
        self.result = None
        self.subscriptions = {}

    def send_result(self, _message_id, result=None) -> None:
        """Capture a successful WebSocket response."""
        self.result = result

    def send_event(self, _message_id, _event) -> None:
        """Subscription events are irrelevant for this isolation check."""


def _registry_identity(hass) -> tuple[list[tuple], list[tuple]]:
    """Return immutable ownership identities for both registries."""
    entities = async_get_entity_registry(hass)
    devices = async_get_device_registry(hass)
    return (
        sorted(
            (entry.entity_id, entry.unique_id, entry.config_entry_id, entry.device_id)
            for entry in entities.entities.values()
        ),
        sorted(
            (entry.id, tuple(sorted(entry.config_entries)), entry.identifiers)
            for entry in devices.devices.values()
        ),
    )


def _entry_identity(hass) -> list[tuple]:
    """Return immutable ConfigEntry data and option snapshots."""
    return sorted(
        (
            entry.entry_id,
            dict(entry.data),
            dict(entry.options),
            entry.state,
        )
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


async def _partial_migration(
    hass,
) -> tuple[MockConfigEntry, MockConfigEntry, MigrationState]:
    """Create a real legacy runtime beside a persisted partial global checkpoint."""
    source = MockConfigEntry(
        domain=DOMAIN, data=get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    )
    await init_integration(hass, [source])
    target = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GLOBAL_ENTRY_UNIQUE_ID,
        version=AdaptiveConfigEntryVersion.MAJOR,
        data={CONF_GLOBAL_ENTRY: True},
        options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
    )
    target.add_to_hass(hass)
    state = MigrationState(
        1,
        MigrationPhase.TRANSFER_REGISTRY,
        [source.entry_id],
        target.entry_id,
        [DEFAULT_MOCK_AREA.value],
    )
    restored = MigrationState.from_dict(state.as_dict())
    hass.config_entries.async_update_entry(
        target, options={**target.options, CONF_MIGRATION: restored.as_dict()}
    )
    await async_evaluate_single_global_entry_migration(hass)
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )
    return source, target, restored


def _forbid_migration_side_effects(monkeypatch) -> dict[str, int]:
    """Fail the test if a normal path enters any destructive migration action."""
    from custom_components.adaptive_areas import migration as migration_module

    calls = {"orchestrator": 0, "factory": 0, "remove": 0, "cleanup": 0}

    async def forbidden(name: str, *_args, **_kwargs):
        calls[name] += 1
        raise AssertionError(f"normal path called migration {name}")

    monkeypatch.setattr(
        migration_module,
        "async_run_single_global_entry_migration",
        lambda *args, **kwargs: forbidden("orchestrator", *args, **kwargs),
    )
    monkeypatch.setattr(
        migration_module,
        "async_get_or_create_global_entry",
        lambda *args, **kwargs: forbidden("factory", *args, **kwargs),
    )
    monkeypatch.setattr(
        migration_module,
        "async_remove_legacy_entries",
        lambda *args, **kwargs: forbidden("remove", *args, **kwargs),
    )
    monkeypatch.setattr(
        migration_module,
        "async_cleanup_migration",
        lambda *args, **kwargs: forbidden("cleanup", *args, **kwargs),
    )
    return calls


async def _call(hass, command: str, **data) -> _Connection:
    """Invoke a registered production WebSocket command through its schema."""
    connection = _Connection()
    handler, schema = hass.data["websocket_api"][command]
    message = {"id": 1, "type": command, **data}
    handler(hass, connection, message if schema is False else schema(message))
    await hass.async_block_till_done()
    return connection


async def test_setup_and_reload_do_not_resume_partial_migration(
    hass, monkeypatch
) -> None:
    """Normal legacy and global setup paths only retain the visible Repair state."""
    source, target, state = await _partial_migration(hass)
    calls = _forbid_migration_side_effects(monkeypatch)
    before_entries = _entry_identity(hass)
    before_registry = _registry_identity(hass)

    assert await hass.config_entries.async_reload(source.entry_id)
    await hass.async_block_till_done()
    assert source.state is ConfigEntryState.LOADED
    assert not await async_setup_entry(hass, target)

    assert calls == {"orchestrator": 0, "factory": 0, "remove": 0, "cleanup": 0}
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == state
    assert _registry_identity(hass) == before_registry
    assert _entry_identity(hass) == before_entries
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


@pytest.mark.parametrize(
    ("command", "data"),
    [
        ("adaptive_areas/get_overview", {}),
        ("adaptive_areas/get_area", {"area_id": DEFAULT_MOCK_AREA.value}),
        ("adaptive_areas/get_area_configuration", {}),
        (
            "adaptive_areas/get_light_runtime_status",
            {"area_id": DEFAULT_MOCK_AREA.value},
        ),
        ("adaptive_areas/subscribe_updates", {}),
        ("adaptive_areas/get_diagnostics", {}),
    ],
)
async def test_dashboard_read_paths_do_not_resume_partial_migration(
    hass, monkeypatch, command, data
) -> None:
    """Every panel WebSocket read is inert while a Repair remains available."""
    source, target, state = await _partial_migration(hass)
    _ = source
    calls = _forbid_migration_side_effects(monkeypatch)
    before_entries = _entry_identity(hass)
    before_registry = _registry_identity(hass)
    async_register_websocket_commands(hass)

    connection = await _call(hass, command, **data)

    assert connection.result is not None or command.endswith("subscribe_updates")
    if command.endswith("get_area_configuration"):
        assert [area["entry_id"] for area in connection.result["areas"]] == [
            source.entry_id
        ]
    assert calls == {"orchestrator": 0, "factory": 0, "remove": 0, "cleanup": 0}
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == state
    assert _registry_identity(hass) == before_registry
    assert _entry_identity(hass) == before_entries
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION
    )


async def test_native_diagnostics_does_not_resume_partial_migration(
    hass, monkeypatch
) -> None:
    """Native diagnostics remains an inert read of a partial migration install."""
    source, target, state = await _partial_migration(hass)
    calls = _forbid_migration_side_effects(monkeypatch)
    before_entries = _entry_identity(hass)
    before_registry = _registry_identity(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, source)

    assert diagnostics["integration"]["name"] == "Adaptive Areas"
    assert calls == {"orchestrator": 0, "factory": 0, "remove": 0, "cleanup": 0}
    assert MigrationState.from_dict(target.options[CONF_MIGRATION]) == state
    assert _registry_identity(hass) == before_registry
    assert _entry_identity(hass) == before_entries


async def test_repair_confirmation_is_the_only_migration_trigger(
    hass, monkeypatch
) -> None:
    """Opening Repair is inert; its explicit confirmation calls the orchestrator once."""
    _source, _target, _state = await _partial_migration(hass)
    from custom_components.adaptive_areas import migration as migration_module

    calls = 0

    async def tracked_orchestrator(_hass):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(
        migration_module,
        "async_run_single_global_entry_migration",
        tracked_orchestrator,
    )
    flow = SingleGlobalEntryMigrationRepairFlow()
    flow.hass = hass

    assert (await flow.async_step_init(None))["type"] == "form"
    assert calls == 0
    assert (await flow.async_step_init({}))["type"] == "create_entry"
    assert calls == 1
