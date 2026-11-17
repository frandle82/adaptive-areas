"""Pure-policy coverage for the future Light runtime."""

from copy import deepcopy

import pytest

from custom_components.adaptive_areas.helpers.light_policy import (
    CONF_TURN_OFF_ABOVE,
    CONF_TURN_ON_BELOW,
    CONF_VACANCY_DELAY,
    LightPolicyAction,
    LightPolicyConfig,
    LightPolicyDecision,
    LightPolicyReason,
    evaluate_light_policy,
    light_policy_config_from_feature,
    light_vacancy_delay_from_feature,
)
from custom_components.adaptive_areas.helpers.sources import (
    LightSourceSnapshot,
    LightTargetSource,
)


def _snapshot(
    *,
    targets: tuple[LightTargetSource, ...] = (LightTargetSource("light.room", True),),
    illuminance_available: bool = True,
    illuminance_value: float | None = 150.0,
    presence_available: bool = True,
    presence_state: bool | None = True,
) -> LightSourceSnapshot:
    return LightSourceSnapshot(
        area_id="living_room",
        targets=targets,
        illuminance_entity_id="sensor.outdoor_lux",
        illuminance_available=illuminance_available,
        illuminance_value=illuminance_value,
        presence_source_entity_ids=("binary_sensor.motion",),
        presence_available=presence_available,
        presence_state=presence_state,
    )


def _assert_decision(
    decision: LightPolicyDecision,
    action: LightPolicyAction,
    reason: LightPolicyReason,
) -> None:
    """Keep the policy result contract explicit in each scenario."""
    assert decision.action is action
    assert decision.reason is reason


def test_policy_guards_missing_config_and_targets() -> None:
    """A valid light feature waits for both policy and actionable targets."""
    configured = LightPolicyConfig(100, 200)

    decision = evaluate_light_policy(_snapshot(), None)
    _assert_decision(
        decision,
        LightPolicyAction.NO_ACTION,
        LightPolicyReason.POLICY_NOT_CONFIGURED,
    )

    decision = evaluate_light_policy(_snapshot(targets=()), configured)
    _assert_decision(
        decision, LightPolicyAction.NO_ACTION, LightPolicyReason.NO_TARGETS
    )

    decision = evaluate_light_policy(
        _snapshot(targets=(LightTargetSource("light.room", False),)), configured
    )
    _assert_decision(
        decision,
        LightPolicyAction.NO_ACTION,
        LightPolicyReason.NO_AVAILABLE_TARGETS,
    )


def test_policy_presence_guards_precede_illuminance() -> None:
    """Vacancy turns off without Lux; unknown occupancy never guesses."""
    configured = LightPolicyConfig(100, 200)

    _assert_decision(
        evaluate_light_policy(
            _snapshot(
                presence_state=False,
                illuminance_available=False,
                illuminance_value=None,
            ),
            configured,
        ),
        LightPolicyAction.TURN_OFF,
        LightPolicyReason.UNOCCUPIED,
    )
    _assert_decision(
        evaluate_light_policy(
            _snapshot(presence_available=False, presence_state=None), configured
        ),
        LightPolicyAction.NO_ACTION,
        LightPolicyReason.PRESENCE_UNAVAILABLE,
    )
    _assert_decision(
        evaluate_light_policy(
            _snapshot(illuminance_available=False, illuminance_value=None), configured
        ),
        LightPolicyAction.NO_ACTION,
        LightPolicyReason.ILLUMINANCE_UNAVAILABLE,
    )


@pytest.mark.parametrize(
    ("illuminance", "action", "reason"),
    [
        (50, LightPolicyAction.TURN_ON, LightPolicyReason.OCCUPIED_AND_DARK),
        (100, LightPolicyAction.TURN_ON, LightPolicyReason.OCCUPIED_AND_DARK),
        (150, LightPolicyAction.HOLD, LightPolicyReason.WITHIN_HYSTERESIS),
        (200, LightPolicyAction.TURN_OFF, LightPolicyReason.OCCUPIED_AND_BRIGHT),
        (500, LightPolicyAction.TURN_OFF, LightPolicyReason.OCCUPIED_AND_BRIGHT),
    ],
)
def test_policy_uses_inclusive_hysteresis_boundaries(
    illuminance, action, reason
) -> None:
    """The lower boundary turns on and the upper boundary turns off."""
    decision = evaluate_light_policy(
        _snapshot(illuminance_value=illuminance), LightPolicyConfig(100, 200)
    )

    _assert_decision(decision, action, reason)


def test_policy_allows_partial_target_availability_without_mutation() -> None:
    """One available target is enough; policy evaluation is entirely read-only."""
    snapshot = _snapshot(
        targets=(
            LightTargetSource("light.available", True),
            LightTargetSource("light.unavailable", False),
        ),
        illuminance_value=50,
    )
    config = LightPolicyConfig(100, 200)
    snapshot_before = deepcopy(snapshot)
    config_before = deepcopy(config)

    first = evaluate_light_policy(snapshot, config)
    second = evaluate_light_policy(snapshot, config)

    _assert_decision(
        first, LightPolicyAction.TURN_ON, LightPolicyReason.OCCUPIED_AND_DARK
    )
    assert second == first
    assert snapshot == snapshot_before
    assert config == config_before


@pytest.mark.parametrize(
    ("turn_on_below", "turn_off_above"),
    [
        (-1, 100),
        (100, -1),
        (100, 100),
        (200, 100),
        (float("nan"), 100),
        (100, float("inf")),
        (float("-inf"), 100),
    ],
)
def test_policy_config_rejects_invalid_hysteresis(
    turn_on_below, turn_off_above
) -> None:
    """Thresholds must be finite, non-negative, and ordered."""
    with pytest.raises(ValueError):
        LightPolicyConfig(turn_on_below, turn_off_above)


def test_policy_config_adapter_is_read_only_and_requires_a_complete_mapping() -> None:
    """Persisted Light feature data maps to policy configuration without defaults."""
    feature = {CONF_TURN_ON_BELOW: 75.5, CONF_TURN_OFF_ABOVE: 150.25}

    assert light_policy_config_from_feature({}) is None
    assert light_policy_config_from_feature(feature) == LightPolicyConfig(75.5, 150.25)
    assert feature == {CONF_TURN_ON_BELOW: 75.5, CONF_TURN_OFF_ABOVE: 150.25}
    with pytest.raises(ValueError):
        light_policy_config_from_feature({CONF_TURN_ON_BELOW: 100})


@pytest.mark.parametrize("delay", [0, 30, 30.5])
def test_vacancy_delay_adapter_accepts_optional_finite_seconds(delay) -> None:
    """Delay remains separate from Lux policy while retaining zero."""
    feature = {
        CONF_TURN_ON_BELOW: 100,
        CONF_TURN_OFF_ABOVE: 200,
        CONF_VACANCY_DELAY: delay,
    }
    assert light_policy_config_from_feature(feature) == LightPolicyConfig(100, 200)
    assert light_vacancy_delay_from_feature(feature) == float(delay)


@pytest.mark.parametrize("delay", [-1, float("nan"), float("inf"), True, "30"])
def test_vacancy_delay_adapter_rejects_invalid_values(delay) -> None:
    """Delay validation never accepts invalid numeric lookalikes."""
    with pytest.raises((TypeError, ValueError)):
        light_vacancy_delay_from_feature({CONF_VACANCY_DELAY: delay})
