"""Threshold model of the Light feature: validation, read-only adapter and retired keys.

Decisions for brightness-dependent groups are tested through helpers/brightness.py and the
group path (see test_brightness_classification.py and test_light_sensor_recovery.py).
"""

import pytest

from custom_components.adaptive_areas.helpers.brightness import (
    CONF_TURN_OFF_ABOVE,
    CONF_TURN_ON_BELOW,
    CONF_VACANCY_DELAY,
    LightPolicyConfig,
    light_policy_config_from_feature,
)


@pytest.mark.parametrize(
    ("turn_on_below", "turn_off_above"),
    [
        (-1, 100),
        (100, -1),
        (0, 0),
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


def test_retired_vacancy_delay_is_tolerated_and_ignored() -> None:
    """Old stored options with any vacancy_delay value still load; the value has no effect."""
    for legacy in (None, 0, 30, "anything"):
        policy = light_policy_config_from_feature(
            {"turn_on_below": 100, "turn_off_above": 200, CONF_VACANCY_DELAY: legacy}
        )
        assert (policy.turn_on_below, policy.turn_off_above) == (100, 200)
