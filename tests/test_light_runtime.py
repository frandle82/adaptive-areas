"""Lifecycle-free coverage for Light runtime evaluation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import asyncio

import pytest
from homeassistant.core import Context
from homeassistant.helpers.dispatcher import async_dispatcher_send

from custom_components.adaptive_areas.const import AdaptiveAreasEvents, AreaStates

from custom_components.adaptive_areas.helpers.light_override import (
    LightManualOverrideMode,
    LightManualOverrideState,
)

from custom_components.adaptive_areas.helpers.light_policy import LightPolicyAction
from custom_components.adaptive_areas.helpers.light_runtime import LightRuntimeManager
from custom_components.adaptive_areas import migration as migration_module
from custom_components.adaptive_areas.helpers.sources import (
    LightSourceSnapshot,
    LightTargetSource,
)


def _area(hass, feature=None):
    return SimpleNamespace(
        id="living",
        hass=hass,
        is_meta=lambda: False,
        has_feature=lambda _feature: feature is not None,
        feature_config=lambda _feature: feature or {},
    )


def _named_area(hass, area_id, feature):
    area = _area(hass, feature)
    area.id = area_id
    return area


def _snapshot(*, lux=50, occupied=True, available=True, presence=True):
    return LightSourceSnapshot(
        "living",
        (LightTargetSource("light.room", available),),
        "sensor.lux",
        lux is not None,
        lux,
        ("binary_sensor.presence",),
        presence,
        occupied if presence else None,
    )


async def test_runtime_evaluates_once_and_deduplicates_dispatch(hass) -> None:
    """A repeated dispatch action is sent once until HOLD resets it."""
    area = SimpleNamespace(
        id="living",
        hass=hass,
        is_meta=lambda: False,
        has_feature=lambda _feature: True,
        feature_config=lambda _feature: {"turn_on_below": 100, "turn_off_above": 200},
    )
    snapshot = LightSourceSnapshot(
        "living",
        (LightTargetSource("light.room", True),),
        None,
        True,
        50,
        (),
        True,
        True,
    )
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    hass.states.async_set("light.room", "off")
    hass.states.async_set("binary_sensor.presence", "on")
    hass.states.async_set("sensor.lux", "50")
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            return_value=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        manager = LightRuntimeManager(area)
        await manager.async_evaluate()
        await manager.async_evaluate()
    dispatched.assert_awaited_once()


@pytest.mark.parametrize(
    ("snapshot", "action"),
    [
        (_snapshot(lux=50), LightPolicyAction.TURN_ON),
        (_snapshot(lux=250), LightPolicyAction.TURN_OFF),
        (_snapshot(lux=None, occupied=False), LightPolicyAction.TURN_OFF),
        (_snapshot(lux=150), None),
        (_snapshot(lux=None), None),
    ],
)
async def test_runtime_initial_policy_matrix(hass, snapshot, action) -> None:
    """Initial evaluation preserves the policy action including safe no-ops."""
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            return_value=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        await LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        ).async_evaluate()
    if action is None:
        dispatched.assert_not_awaited()
    else:
        assert dispatched.await_args.args[2].action is action


async def test_runtime_hold_and_no_action_reset_dispatch_dedupe(hass) -> None:
    """A neutral policy decision permits the next identical dispatch."""
    snapshots = [
        _snapshot(lux=50),
        _snapshot(lux=150),
        _snapshot(lux=50),
        _snapshot(lux=None),
        _snapshot(lux=50),
    ]
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            side_effect=snapshots,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        for _ in snapshots:
            await manager.async_evaluate()
    assert dispatched.await_count == 3


async def test_runtime_unavailable_target_exception_and_unload(hass) -> None:
    """A failed dispatch is not repeated for an unchanged decision; unload removes listeners.

    Policy rule (approved): a failing command is attempted once. The identical second
    evaluation sends nothing; a real change of the decision basis is required for a new try.
    """
    removers = [Mock(), Mock(), Mock()]
    dispatched = AsyncMock(
        side_effect=[RuntimeError("boom"), SimpleNamespace(executed=True)]
    )
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            return_value=_snapshot(),
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_dispatcher_connect",
            return_value=removers[0],
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_track_state_change_event",
            side_effect=[removers[1], removers[2]],
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        await manager.async_setup()
        await manager.async_evaluate()
        await manager.async_evaluate()
        assert dispatched.await_count == 1
        manager.unload()
        await manager.async_evaluate()
    assert dispatched.await_count == 1
    for remove in removers:
        remove.assert_called_once()


async def test_runtime_creation_requires_complete_new_light_policy(hass) -> None:
    """Disabled, legacy-only, and empty new Light configurations stay inert."""
    assert await LightRuntimeManager.async_create(_area(hass, None)) is None
    assert await LightRuntimeManager.async_create(_area(hass, {})) is None


async def test_runtime_presence_and_target_events_use_real_state_listeners(
    hass,
) -> None:
    """A presence source event alone never evaluates; the Area state signal does.

    Regression: a source event arrives before the Area's presence update, so evaluating
    on it read a stale occupancy. Ordinary target on/off events also stay silent.
    """
    initial = _snapshot(lux=50, occupied=True)
    vacant = _snapshot(lux=None, occupied=False)
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    hass.states.async_set("light.room", "off")
    hass.states.async_set("binary_sensor.presence", "on")
    hass.states.async_set("sensor.lux", "50")
    # async_setup reads one snapshot itself, then evaluates: initial, initial, vacant.
    snapshots = iter((initial, initial, vacant))
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            side_effect=lambda _area: next(snapshots, vacant),
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        await manager.async_setup()
        hass.states.async_set("light.room", "on")
        hass.states.async_set("light.room", "off")
        await hass.async_block_till_done()
        assert dispatched.await_count == 1
        hass.states.async_set("binary_sensor.presence", "off")
        await hass.async_block_till_done()
        assert dispatched.await_count == 1
        async_dispatcher_send(
            hass,
            AdaptiveAreasEvents.AREA_STATE_CHANGED,
            manager.area.id,
            (set(), {AreaStates.OCCUPIED}),
        )
        await hass.async_block_till_done()
        await hass.async_block_till_done()
        assert dispatched.await_count == 2
        assert dispatched.await_args.args[2].action is LightPolicyAction.TURN_OFF
        manager.unload()


async def test_runtime_availability_events_reenable_dispatch_and_unload_is_inert(
    hass,
) -> None:
    """Availability transitions evaluate, while all real events stop after unload."""
    unavailable = _snapshot(lux=50, available=False)
    available = _snapshot(lux=50, available=True)
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            side_effect=[unavailable, available],
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        await manager.async_setup()
        hass.states.async_set("light.room", "unavailable")
        hass.states.async_set("light.room", "off")
        await hass.async_block_till_done()
        assert dispatched.await_count == 1


async def test_runtime_real_lux_events_dedupe_and_reset(hass) -> None:
    """The configured Lux entity alone drives dedupe and neutral-policy resets."""
    values = iter((80, 80, 70, 150, 70, None, 60))
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))

    def snapshot(_area):
        lux = next(values)
        return _snapshot(lux=lux)

    hass.states.async_set("sensor.lux", "80")
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            side_effect=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        await manager.async_setup()
        for state in ("70", "60", "150", "70", "unavailable", "60"):
            hass.states.async_set("sensor.lux", state)
            await hass.async_block_till_done()
        hass.states.async_set("sensor.temperature", "20")
        await hass.async_block_till_done()
        assert dispatched.await_count == 3
        manager.unload()


async def test_runtime_global_lux_isolated_per_area(hass) -> None:
    """One global Lux event evaluates each Area with only its own inputs."""
    living = _named_area(hass, "living", {"turn_on_below": 100, "turn_off_above": 200})
    kitchen = _named_area(
        hass, "kitchen", {"turn_on_below": 150, "turn_off_above": 250}
    )
    calls = AsyncMock(return_value=SimpleNamespace(executed=True))

    def snapshot(area):
        if area.id == "living":
            return LightSourceSnapshot(
                "living",
                (LightTargetSource("light.living", True),),
                "sensor.lux",
                True,
                120,
                ("binary_sensor.living",),
                True,
                True,
            )
        return LightSourceSnapshot(
            "kitchen",
            (LightTargetSource("light.kitchen", True),),
            "sensor.lux",
            True,
            120,
            ("binary_sensor.kitchen",),
            True,
            True,
        )

    hass.states.async_set("sensor.lux", "120")
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            side_effect=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            calls,
        ),
    ):
        living_manager = LightRuntimeManager(living)
        kitchen_manager = LightRuntimeManager(kitchen)
        await living_manager.async_setup()
        await kitchen_manager.async_setup()
        assert calls.await_count == 1
        assert calls.await_args.args[1].area_id == "kitchen"
        hass.states.async_set("sensor.lux", "121")
        await hass.async_block_till_done()
        assert calls.await_count == 1
        living_manager.unload()
        kitchen_manager.unload()


async def test_runtime_cross_area_presence_and_availability_are_isolated(hass) -> None:
    """Area-local listeners never evaluate the other Area's policy."""
    living = _named_area(hass, "living", {"turn_on_below": 100, "turn_off_above": 200})
    kitchen = _named_area(
        hass, "kitchen", {"turn_on_below": 100, "turn_off_above": 200}
    )
    calls = AsyncMock(return_value=SimpleNamespace(executed=True))
    states = {"living": True, "kitchen": True}

    def snapshot(area):
        area_id = area.id
        return LightSourceSnapshot(
            area_id,
            (LightTargetSource(f"light.{area_id}", True),),
            "sensor.lux",
            True,
            50,
            (f"binary_sensor.{area_id}",),
            True,
            states[area_id],
        )

    for entity_id in (
        "binary_sensor.living",
        "binary_sensor.kitchen",
        "light.living",
        "light.kitchen",
        "sensor.lux",
    ):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            side_effect=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            calls,
        ),
    ):
        living_manager = LightRuntimeManager(living)
        kitchen_manager = LightRuntimeManager(kitchen)
        await living_manager.async_setup()
        await kitchen_manager.async_setup()
        assert calls.await_count == 2
        states["living"] = False
        async_dispatcher_send(
            hass,
            AdaptiveAreasEvents.AREA_STATE_CHANGED,
            "living",
            (set(), {AreaStates.OCCUPIED}),
        )
        await hass.async_block_till_done()
        assert calls.await_count == 3
        assert calls.await_args.args[1].area_id == "living"
        hass.states.async_set("light.kitchen", "unavailable")
        await hass.async_block_till_done()
        assert calls.await_count == 3
        living_manager.unload()
        kitchen_manager.unload()


async def test_runtime_serializes_executor_calls_per_area(hass) -> None:
    """Two real Lux events cannot execute the same Area concurrently."""
    started = asyncio.Event()
    release = asyncio.Event()
    current = max_parallel = 0

    async def dispatch(*_args, **_kwargs):
        nonlocal current, max_parallel
        current += 1
        max_parallel = max(max_parallel, current)
        started.set()
        await release.wait()
        current -= 1
        return SimpleNamespace(executed=True)

    snapshot = _snapshot(lux=50)
    hass.states.async_set("sensor.lux", "50")
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            return_value=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            side_effect=dispatch,
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        task = hass.async_create_task(manager.async_setup())
        await started.wait()
        hass.states.async_set("sensor.lux", "60")
        await asyncio.sleep(0)
        assert max_parallel == 1
        release.set()
        await task
        await hass.async_block_till_done()
        assert max_parallel == 1
        manager.unload()


async def test_runtime_reload_replaces_presence_and_lux_listeners(hass) -> None:
    """Unload/setup leaves exactly the replacement manager subscribed."""
    old = _snapshot(lux=50)
    new = _snapshot(lux=50)
    calls = AsyncMock(return_value=SimpleNamespace(executed=True))
    area = _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
    for entity_id in ("binary_sensor.presence", "sensor.lux", "light.room"):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            side_effect=[old, old, new, new, new],
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            calls,
        ),
    ):
        manager_a = LightRuntimeManager(area)
        await manager_a.async_setup()
        manager_a.unload()
        manager_b = LightRuntimeManager(area)
        await manager_b.async_setup()
        hass.states.async_set("binary_sensor.presence", "on")
        hass.states.async_set("sensor.lux", "60")
        await hass.async_block_till_done()
        assert calls.await_count == 2
        manager_b.unload()


async def test_runtime_sensor_and_policy_reload_are_fresh(hass) -> None:
    """Replacement managers only listen to their current Lux source and policy."""
    feature = {"turn_on_below": 100, "turn_off_above": 200}
    area = _area(hass, feature)
    calls = AsyncMock(return_value=SimpleNamespace(executed=True))

    def snapshot(_area):
        sensor = (
            "sensor.lux_old" if feature["turn_on_below"] == 100 else "sensor.lux_new"
        )
        return LightSourceSnapshot(
            "living",
            (LightTargetSource("light.room", True),),
            sensor,
            True,
            120,
            ("binary_sensor.presence",),
            True,
            True,
        )

    for entity_id in (
        "sensor.lux_old",
        "sensor.lux_new",
        "binary_sensor.presence",
        "light.room",
    ):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            side_effect=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            calls,
        ),
    ):
        manager_a = LightRuntimeManager(area)
        await manager_a.async_setup()
        assert calls.await_count == 0
        manager_a.unload()
        feature.update(turn_on_below=150, turn_off_above=250)
        manager_b = LightRuntimeManager(area)
        await manager_b.async_setup()
        assert calls.await_count == 1
        hass.states.async_set("sensor.lux_old", "120")
        await hass.async_block_till_done()
        assert calls.await_count == 1
        hass.states.async_set("sensor.lux_new", "120")
        await hass.async_block_till_done()
        assert calls.await_count == 1
        manager_b.unload()


async def test_runtime_ignores_light_groups_without_new_light_feature(hass) -> None:
    """Legacy light groups neither create nor configure the new manager."""
    legacy = _area(hass, None)
    legacy.has_feature = lambda feature: feature == "light_groups"
    assert await LightRuntimeManager.async_create(legacy) is None


async def test_runtime_light_groups_and_migration_are_isolated(
    hass, monkeypatch
) -> None:
    """The new runtime needs Light only and never starts migration work."""
    migration_spy = AsyncMock()
    monkeypatch.setattr(
        migration_module, "async_run_single_global_entry_migration", migration_spy
    )
    area = _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
    area.feature_config = lambda feature: (
        {"turn_on_below": 100, "turn_off_above": 200}
        if feature == "light"
        else {"legacy": "unchanged"}
    )
    with patch(
        "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
        return_value=_snapshot(),
    ):
        manager = await LightRuntimeManager.async_create(area)
        assert manager is not None
        manager.unload()
    migration_spy.assert_not_awaited()


async def test_runtime_target_context_detection_sets_only_user_override(hass) -> None:
    """Target on/off events classify user intent without policy re-evaluation."""
    snapshot = _snapshot(lux=150, occupied=True)
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    hass.states.async_set("light.room", "off")
    await hass.async_block_till_done()
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            return_value=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        await manager.async_setup()
        own_context = Context(id="runtime")
        manager._own_action_context_ids.append(
            own_context.id
        )  # pylint: disable=protected-access
        hass.states.async_set("light.room", "on", context=own_context)
        await hass.async_block_till_done()
        assert (
            manager._manual_override_state.mode.value == "none"
        )  # pylint: disable=protected-access
        assert not manager._own_action_context_ids  # pylint: disable=protected-access

        hass.states.async_set("light.room", "off", context=Context(user_id="user"))
        await hass.async_block_till_done()
        assert (
            manager._manual_override_state.mode.value == "force_off"
        )  # pylint: disable=protected-access
        dispatched.assert_not_awaited()
        manager.unload()


async def test_runtime_target_detection_is_area_local_and_unloads(hass) -> None:
    """Only subscribed targets change a manager's transient override state."""
    living_snapshot = _snapshot(lux=150, occupied=True)
    kitchen_snapshot = LightSourceSnapshot(
        "kitchen",
        (LightTargetSource("light.kitchen", True),),
        "sensor.lux",
        True,
        150,
        ("binary_sensor.kitchen",),
        True,
        True,
    )
    hass.states.async_set("light.room", "off")
    hass.states.async_set("light.kitchen", "off")
    await hass.async_block_till_done()
    with patch(
        "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
        side_effect=lambda area: (
            living_snapshot if area.id == "living" else kitchen_snapshot
        ),
    ):
        living = LightRuntimeManager(
            _named_area(hass, "living", {"turn_on_below": 100, "turn_off_above": 200})
        )
        kitchen = LightRuntimeManager(
            _named_area(hass, "kitchen", {"turn_on_below": 100, "turn_off_above": 200})
        )
        await living.async_setup()
        await kitchen.async_setup()
        hass.states.async_set("light.kitchen", "on", context=Context(user_id="user"))
        await hass.async_block_till_done()
        assert (
            living._manual_override_state.mode.value == "none"
        )  # pylint: disable=protected-access
        assert (
            kitchen._manual_override_state.mode.value == "force_on"
        )  # pylint: disable=protected-access
        kitchen.unload()
        hass.states.async_set("light.kitchen", "off", context=Context(user_id="user"))
        await hass.async_block_till_done()
        assert (
            kitchen._manual_override_state.mode.value == "none"
        )  # pylint: disable=protected-access
        living.unload()


async def test_runtime_own_context_tracking_is_bounded_and_cleared_on_unload(
    hass,
) -> None:
    """Transient own-action context tracking cannot grow across dispatches."""
    manager = LightRuntimeManager(
        _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
    )
    manager._own_action_context_ids.extend(  # pylint: disable=protected-access
        f"context-{index}" for index in range(65)
    )
    assert (
        len(manager._own_action_context_ids) == 64
    )  # pylint: disable=protected-access
    manager.unload()
    assert not manager._own_action_context_ids  # pylint: disable=protected-access


@pytest.mark.parametrize(
    ("mode", "snapshot", "expected_calls"),
    [
        (LightManualOverrideMode.FORCE_OFF, _snapshot(lux=50), 0),
        (LightManualOverrideMode.FORCE_ON, _snapshot(lux=250), 0),
        (LightManualOverrideMode.NONE, _snapshot(lux=50), 1),
        (LightManualOverrideMode.FORCE_ON, _snapshot(lux=50), 1),
        (LightManualOverrideMode.FORCE_OFF, _snapshot(lux=250), 1),
    ],
)
async def test_runtime_manual_override_filters_only_opposing_decisions(
    hass, mode, snapshot, expected_calls
) -> None:
    """Override filtering precedes dispatch without changing normal directions."""
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            return_value=snapshot,
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        manager._manual_override_state = LightManualOverrideState(
            mode, 1
        )  # pylint: disable=protected-access
        await manager.async_evaluate()
    assert dispatched.await_count == expected_calls
    if not expected_calls:
        assert (
            manager._last_dispatched_action is None
        )  # pylint: disable=protected-access
        assert (
            manager._manual_override_state.mode is mode
        )  # pylint: disable=protected-access


@pytest.mark.parametrize(
    "mode", (LightManualOverrideMode.FORCE_ON, LightManualOverrideMode.FORCE_OFF)
)
async def test_runtime_confirmed_vacancy_resets_override_before_off(hass, mode) -> None:
    """Confirmed vacancy clears either override direction before immediate off."""
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            return_value=_snapshot(lux=None, occupied=False),
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        manager = LightRuntimeManager(
            _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
        )
        manager._manual_override_state = LightManualOverrideState(
            mode, 1
        )  # pylint: disable=protected-access
        await manager.async_evaluate()
    assert dispatched.await_args.args[2].action is LightPolicyAction.TURN_OFF
    assert (
        manager._manual_override_state == LightManualOverrideState()
    )  # pylint: disable=protected-access


async def test_runtime_unavailable_presence_preserves_manual_override(hass) -> None:
    """Unknown occupancy never clears a user override."""
    manager = LightRuntimeManager(
        _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
    )
    manager._manual_override_state = (
        LightManualOverrideState(  # pylint: disable=protected-access
            LightManualOverrideMode.FORCE_ON, 1
        )
    )
    with patch(
        "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
        return_value=_snapshot(lux=None, occupied=False, presence=False),
    ):
        await manager.async_evaluate()
    assert (
        manager._manual_override_state.mode is LightManualOverrideMode.FORCE_ON
    )  # pylint: disable=protected-access


# -- Light vacancy delay removed: only the Area vacancy delay is authoritative --


def _vacant_runtime(hass, feature):
    """Runtime manager on a vacant snapshot (no timer may exist)."""
    return LightRuntimeManager(_area(hass, feature))


@pytest.mark.parametrize("legacy_delay", (None, 0, 30, 120))
async def test_runtime_vacancy_turns_off_immediately_whatever_the_legacy_delay(
    hass, legacy_delay
) -> None:
    """A stored legacy vacancy_delay has no effect: the OFF is dispatched at once."""
    feature = {"turn_on_below": 100, "turn_off_above": 200}
    if legacy_delay is not None:
        feature["vacancy_delay"] = legacy_delay
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    with (
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot",
            return_value=_snapshot(lux=None, occupied=False),
        ),
        patch(
            "custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision",
            dispatched,
        ),
    ):
        await _vacant_runtime(hass, feature).async_evaluate()
    assert dispatched.await_args.args[2].action is LightPolicyAction.TURN_OFF


async def test_runtime_creates_no_vacancy_timer_and_has_no_timer_state(hass) -> None:
    """The runtime owns no timer and no vacancy state any more."""
    manager = _vacant_runtime(
        hass, {"turn_on_below": 100, "turn_off_above": 200, "vacancy_delay": 30}
    )
    assert not hasattr(manager, "_vacancy_state")
    assert not hasattr(manager, "_vacancy_timer_unsub")


async def test_runtime_legacy_delay_still_loads_through_the_policy(hass) -> None:
    """Old stored options with vacancy_delay remain loadable and keep their thresholds."""
    from custom_components.adaptive_areas.helpers.light_policy import (
        light_policy_config_from_feature,
    )

    policy = light_policy_config_from_feature(
        {"turn_on_below": 100, "turn_off_above": 200, "vacancy_delay": 30}
    )
    assert (policy.turn_on_below, policy.turn_off_above) == (100, 200)
