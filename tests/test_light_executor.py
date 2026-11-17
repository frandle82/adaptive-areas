"""Dispatch-only coverage for the future Light runtime executor."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.adaptive_areas.helpers.light_executor import (
    async_execute_light_decision,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyDecision,
    LightPolicyReason,
)
from custom_components.adaptive_areas.helpers.sources import (
    LightSourceSnapshot,
    LightTargetSource,
)


def _snapshot(*targets: LightTargetSource) -> LightSourceSnapshot:
    return LightSourceSnapshot("area", targets, None, False, None, (), False, None)


def _decision(action: LightPolicyAction, reason: LightPolicyReason) -> LightPolicyDecision:
    return LightPolicyDecision(action, reason)


@pytest.mark.parametrize(
    ("action", "service"),
    [(LightPolicyAction.TURN_ON, "turn_on"), (LightPolicyAction.TURN_OFF, "turn_off")],
)
async def test_executor_dispatches_one_sorted_call(action, service) -> None:
    """On/off decisions dispatch every available target in one stable call."""
    async_call = AsyncMock()
    hass = SimpleNamespace(services=SimpleNamespace(async_call=async_call))
    snapshot = _snapshot(
        LightTargetSource("light.wall", True),
        LightTargetSource("light.ceiling", True),
        LightTargetSource("light.wall", True),
        LightTargetSource("light.floor", False),
    )
    decision = _decision(action, LightPolicyReason.UNOCCUPIED)

    result = await async_execute_light_decision(hass, snapshot, decision)

    assert result.executed
    assert result.target_entity_ids == ("light.ceiling", "light.wall")
    async_call.assert_awaited_once_with(
        "light", service, {"entity_id": result.target_entity_ids}, blocking=True
    )
    assert snapshot.targets[2].entity_id == "light.wall"
    assert decision.reason is LightPolicyReason.UNOCCUPIED


@pytest.mark.parametrize("action", [LightPolicyAction.HOLD, LightPolicyAction.NO_ACTION])
async def test_executor_skips_non_dispatch_actions(action) -> None:
    """HOLD and NO_ACTION never call Home Assistant services."""
    async_call = AsyncMock()
    hass = SimpleNamespace(services=SimpleNamespace(async_call=async_call))

    result = await async_execute_light_decision(
        hass,
        _snapshot(LightTargetSource("light.room", True)),
        _decision(action, LightPolicyReason.WITHIN_HYSTERESIS),
    )

    assert not result.executed
    assert result.target_entity_ids == ()
    async_call.assert_not_awaited()


async def test_executor_skips_empty_or_unavailable_targets_and_propagates_errors() -> None:
    """No target is a no-op; service failures never report a false success."""
    async_call = AsyncMock()
    hass = SimpleNamespace(services=SimpleNamespace(async_call=async_call))
    decision = _decision(LightPolicyAction.TURN_ON, LightPolicyReason.OCCUPIED_AND_DARK)

    assert not (await async_execute_light_decision(hass, _snapshot(), decision)).executed
    assert not (
        await async_execute_light_decision(
            hass, _snapshot(LightTargetSource("light.room", False)), decision
        )
    ).executed
    async_call.assert_not_awaited()

    async_call.side_effect = RuntimeError("service unavailable")
    with pytest.raises(RuntimeError, match="service unavailable"):
        await async_execute_light_decision(
            hass, _snapshot(LightTargetSource("light.room", True)), decision
        )
