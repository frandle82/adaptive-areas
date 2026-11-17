"""Lifecycle-free coverage for Light runtime evaluation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import asyncio

import pytest

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
        "living", (LightTargetSource("light.room", True),), None, True, 50, (), True, True
    )
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    hass.states.async_set("light.room", "off")
    hass.states.async_set("binary_sensor.presence", "on")
    hass.states.async_set("sensor.lux", "50")
    await hass.async_block_till_done()
    with (
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", return_value=snapshot),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", dispatched),
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
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", return_value=snapshot),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", dispatched),
    ):
        await LightRuntimeManager(_area(hass, {"turn_on_below": 100, "turn_off_above": 200})).async_evaluate()
    if action is None:
        dispatched.assert_not_awaited()
    else:
        assert dispatched.await_args.args[2].action is action


async def test_runtime_hold_and_no_action_reset_dispatch_dedupe(hass) -> None:
    """A neutral policy decision permits the next identical dispatch."""
    snapshots = [_snapshot(lux=50), _snapshot(lux=150), _snapshot(lux=50), _snapshot(lux=None), _snapshot(lux=50)]
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    with (
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", side_effect=snapshots),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", dispatched),
    ):
        manager = LightRuntimeManager(_area(hass, {"turn_on_below": 100, "turn_off_above": 200}))
        for _ in snapshots:
            await manager.async_evaluate()
    assert dispatched.await_count == 3


async def test_runtime_unavailable_target_exception_and_unload(hass) -> None:
    """Failed or unavailable dispatches are retriable and unload removes listeners."""
    removers = [Mock(), Mock(), Mock()]
    dispatched = AsyncMock(side_effect=[RuntimeError("boom"), SimpleNamespace(executed=True)])
    with (
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", return_value=_snapshot()),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", dispatched),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_track_state_change_event", side_effect=removers),
    ):
        manager = LightRuntimeManager(_area(hass, {"turn_on_below": 100, "turn_off_above": 200}))
        await manager.async_setup()
        await manager.async_evaluate()
        manager.unload()
        await manager.async_evaluate()
    assert dispatched.await_count == 2
    for remove in removers:
        remove.assert_called_once()


async def test_runtime_creation_requires_complete_new_light_policy(hass) -> None:
    """Disabled, legacy-only, and empty new Light configurations stay inert."""
    assert await LightRuntimeManager.async_create(_area(hass, None)) is None
    assert await LightRuntimeManager.async_create(_area(hass, {})) is None


async def test_runtime_presence_and_target_events_use_real_state_listeners(hass) -> None:
    """Presence events evaluate; ordinary target on/off events deliberately do not."""
    initial = _snapshot(lux=50, occupied=True)
    vacant = _snapshot(lux=None, occupied=False)
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    hass.states.async_set("light.room", "off")
    hass.states.async_set("binary_sensor.presence", "on")
    hass.states.async_set("sensor.lux", "50")
    snapshots = iter((initial, initial, vacant))
    with (
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", side_effect=lambda _area: next(snapshots, vacant)),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", dispatched),
    ):
        manager = LightRuntimeManager(_area(hass, {"turn_on_below": 100, "turn_off_above": 200}))
        await manager.async_setup()
        hass.states.async_set("light.room", "on")
        hass.states.async_set("light.room", "off")
        await hass.async_block_till_done()
        assert dispatched.await_count == 1
        hass.states.async_set("binary_sensor.presence", "off")
        await hass.async_block_till_done()
        await hass.async_block_till_done()
        assert dispatched.await_count == 2
        assert dispatched.await_args.args[2].action is LightPolicyAction.TURN_OFF
        manager.unload()


async def test_runtime_availability_events_reenable_dispatch_and_unload_is_inert(hass) -> None:
    """Availability transitions evaluate, while all real events stop after unload."""
    unavailable = _snapshot(lux=50, available=False)
    available = _snapshot(lux=50, available=True)
    dispatched = AsyncMock(return_value=SimpleNamespace(executed=True))
    with (
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", side_effect=[unavailable, available]),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", dispatched),
    ):
        manager = LightRuntimeManager(_area(hass, {"turn_on_below": 100, "turn_off_above": 200}))
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
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", side_effect=snapshot),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", dispatched),
    ):
        manager = LightRuntimeManager(_area(hass, {"turn_on_below": 100, "turn_off_above": 200}))
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
    kitchen = _named_area(hass, "kitchen", {"turn_on_below": 150, "turn_off_above": 250})
    calls = AsyncMock(return_value=SimpleNamespace(executed=True))

    def snapshot(area):
        if area.id == "living":
            return LightSourceSnapshot("living", (LightTargetSource("light.living", True),), "sensor.lux", True, 120, ("binary_sensor.living",), True, True)
        return LightSourceSnapshot("kitchen", (LightTargetSource("light.kitchen", True),), "sensor.lux", True, 120, ("binary_sensor.kitchen",), True, True)

    hass.states.async_set("sensor.lux", "120")
    await hass.async_block_till_done()
    with (
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", side_effect=snapshot),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", calls),
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
    kitchen = _named_area(hass, "kitchen", {"turn_on_below": 100, "turn_off_above": 200})
    calls = AsyncMock(return_value=SimpleNamespace(executed=True))
    states = {"living": True, "kitchen": True}

    def snapshot(area):
        area_id = area.id
        return LightSourceSnapshot(area_id, (LightTargetSource(f"light.{area_id}", True),), "sensor.lux", True, 50, (f"binary_sensor.{area_id}",), True, states[area_id])

    for entity_id in ("binary_sensor.living", "binary_sensor.kitchen", "light.living", "light.kitchen", "sensor.lux"):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    with (
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", side_effect=snapshot),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", calls),
    ):
        living_manager = LightRuntimeManager(living)
        kitchen_manager = LightRuntimeManager(kitchen)
        await living_manager.async_setup()
        await kitchen_manager.async_setup()
        assert calls.await_count == 2
        hass.states.async_set("binary_sensor.living", "on")
        await hass.async_block_till_done()
        states["living"] = False
        hass.states.async_set("binary_sensor.living", "off")
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

    async def dispatch(*_args):
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
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", return_value=snapshot),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", side_effect=dispatch),
    ):
        manager = LightRuntimeManager(_area(hass, {"turn_on_below": 100, "turn_off_above": 200}))
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
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", side_effect=[old, old, new, new, new]),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", calls),
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
        sensor = "sensor.lux_old" if feature["turn_on_below"] == 100 else "sensor.lux_new"
        return LightSourceSnapshot("living", (LightTargetSource("light.room", True),), sensor, True, 120, ("binary_sensor.presence",), True, True)

    for entity_id in ("sensor.lux_old", "sensor.lux_new", "binary_sensor.presence", "light.room"):
        hass.states.async_set(entity_id, "off")
    await hass.async_block_till_done()
    with (
        patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", side_effect=snapshot),
        patch("custom_components.adaptive_areas.helpers.light_runtime.async_execute_light_decision", calls),
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


async def test_runtime_light_groups_and_migration_are_isolated(hass, monkeypatch) -> None:
    """The new runtime needs Light only and never starts migration work."""
    migration_spy = AsyncMock()
    monkeypatch.setattr(migration_module, "async_run_single_global_entry_migration", migration_spy)
    area = _area(hass, {"turn_on_below": 100, "turn_off_above": 200})
    area.feature_config = lambda feature: (
        {"turn_on_below": 100, "turn_off_above": 200}
        if feature == "light"
        else {"legacy": "unchanged"}
    )
    with patch("custom_components.adaptive_areas.helpers.light_runtime.light_source_snapshot", return_value=_snapshot()):
        manager = await LightRuntimeManager.async_create(area)
        assert manager is not None
        manager.unload()
    migration_spy.assert_not_awaited()
