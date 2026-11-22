"""Brightness and light diagnostics: sources, decisions, overrides and dispatch records."""

from __future__ import annotations

import pytest

from custom_components.adaptive_areas.dashboard import (
    _brightness_reason,
    light_policy_diagnostics,
)
from custom_components.adaptive_areas.helpers.light_override import (
    LightManualOverrideMode,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyDecision,
    LightPolicyReason,
)


def _decision(action: LightPolicyAction) -> LightPolicyDecision:
    return LightPolicyDecision(action, LightPolicyReason.OCCUPIED_AND_DARK)


@pytest.mark.parametrize(
    ("dark_source", "expected"),
    [
        (None, "not_configured"),
        ({"status": "missing", "available": False}, "source_missing"),
        ({"status": "unavailable", "available": False}, "source_unavailable"),
        ({"status": "ok", "available": True}, "configured_source"),
    ],
)
def test_brightness_reason_names_the_source_state(dark_source, expected) -> None:
    """The reason states only what the backend knows about the darkness entity."""
    assert _brightness_reason(dark_source) == expected


@pytest.mark.parametrize(
    ("action", "mode", "last", "blocked", "duplicate"),
    [
        # TURN_ON / TURN_OFF without override and without a previous dispatch
        (LightPolicyAction.TURN_ON, LightManualOverrideMode.NONE, None, None, False),
        (LightPolicyAction.TURN_OFF, LightManualOverrideMode.NONE, None, None, False),
        # the same action already dispatched: duplicate, not blocked
        (
            LightPolicyAction.TURN_ON,
            LightManualOverrideMode.NONE,
            LightPolicyAction.TURN_ON,
            None,
            True,
        ),
        # a different action than the last dispatched one is not a duplicate
        (
            LightPolicyAction.TURN_OFF,
            LightManualOverrideMode.NONE,
            LightPolicyAction.TURN_ON,
            None,
            False,
        ),
        # manual intent blocks opposing policy actions
        (
            LightPolicyAction.TURN_ON,
            LightManualOverrideMode.FORCE_OFF,
            None,
            "force_off",
            False,
        ),
        (
            LightPolicyAction.TURN_OFF,
            LightManualOverrideMode.FORCE_ON,
            None,
            "force_on",
            False,
        ),
        # same-direction manual intent does not block
        (
            LightPolicyAction.TURN_ON,
            LightManualOverrideMode.FORCE_ON,
            None,
            None,
            False,
        ),
        (
            LightPolicyAction.TURN_OFF,
            LightManualOverrideMode.FORCE_OFF,
            None,
            None,
            False,
        ),
        # HOLD and NO_ACTION are never blocked nor duplicates
        (
            LightPolicyAction.HOLD,
            LightManualOverrideMode.FORCE_OFF,
            LightPolicyAction.TURN_ON,
            None,
            False,
        ),
        (
            LightPolicyAction.NO_ACTION,
            LightManualOverrideMode.NONE,
            LightPolicyAction.TURN_ON,
            None,
            False,
        ),
    ],
)
def test_policy_diagnostics_separates_wish_block_and_duplicate(
    action, mode, last, blocked, duplicate
) -> None:
    """Policy wish, override block and dispatch duplicate are reported separately."""
    result = light_policy_diagnostics(_decision(action), mode, last)
    assert result == {"blocked_by": blocked, "duplicate": duplicate}
