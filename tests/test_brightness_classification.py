"""Brightness classification and the volatile tracker (E1-E4, section 2 and 3)."""

from __future__ import annotations

import pytest

from custom_components.adaptive_areas.helpers.brightness import (
    BrightnessReason,
    BrightnessState,
    BrightnessTracker,
    classify_brightness,
)
from custom_components.adaptive_areas.helpers.light_policy import LightPolicyConfig

CFG = LightPolicyConfig(90.0, 110.0)
SRC = "sensor.global_lux"


@pytest.mark.parametrize(
    ("value", "previous", "state", "reason"),
    [
        (80.0, None, BrightnessState.DARK, BrightnessReason.THRESHOLD_DARK),
        (90.0, None, BrightnessState.DARK, BrightnessReason.THRESHOLD_DARK),
        (110.0, None, BrightnessState.BRIGHT, BrightnessReason.THRESHOLD_BRIGHT),
        (120.0, None, BrightnessState.BRIGHT, BrightnessReason.THRESHOLD_BRIGHT),
        (100.0, None, BrightnessState.UNKNOWN, BrightnessReason.BAND_NO_PREVIOUS),
        (100.0, BrightnessState.DARK, BrightnessState.DARK, BrightnessReason.BAND_KEPT),
        (
            100.0,
            BrightnessState.BRIGHT,
            BrightnessState.BRIGHT,
            BrightnessReason.BAND_KEPT,
        ),
        (
            89.99,
            BrightnessState.BRIGHT,
            BrightnessState.DARK,
            BrightnessReason.THRESHOLD_DARK,
        ),
        (
            110.01,
            BrightnessState.DARK,
            BrightnessState.BRIGHT,
            BrightnessReason.THRESHOLD_BRIGHT,
        ),
    ],
)
def test_thresholds_and_band_with_and_without_previous_state(
    value, previous, state, reason
) -> None:
    """DARK at or below 90, BRIGHT at or above 110, band keeps a known state only."""
    result = classify_brightness(value, CFG, previous)
    assert result.state is state
    assert result.reason is reason


def test_zero_percent_hysteresis_has_no_band() -> None:
    """H = 0 %: equal limits. At exactly the threshold the value is DARK (on at or below)."""
    config = LightPolicyConfig(100.0, 100.0)
    assert classify_brightness(100.0, config, None).state is BrightnessState.DARK
    assert classify_brightness(100.1, config, None).state is BrightnessState.BRIGHT
    assert classify_brightness(99.9, config, None).state is BrightnessState.DARK


def test_twenty_percent_example_100_lx_yields_90_and_110() -> None:
    """Stored limits for T = 100 lx and H = 20 % are 90 and 110."""
    # Same exact arithmetic as the panel: T - T*H/200 and T + T*H/200.
    config = LightPolicyConfig(100.0 - 100.0 * 20 / 200, 100.0 + 100.0 * 20 / 200)
    assert (config.turn_on_below, config.turn_off_above) == (90.0, 110.0)


@pytest.mark.parametrize(
    "value",
    [None],
)
def test_missing_reading_is_unknown_never_dark(value) -> None:
    """Unavailable or unknown readings are UNKNOWN, not dark."""
    result = classify_brightness(value, CFG, BrightnessState.DARK)
    assert result.state is BrightnessState.UNKNOWN
    assert result.reason is BrightnessReason.SOURCE_UNAVAILABLE


def test_missing_configuration_is_unknown() -> None:
    """No valid Lux configuration: no brightness assessment at all."""
    result = classify_brightness(10.0, None, BrightnessState.DARK)
    assert result.state is BrightnessState.UNKNOWN
    assert result.reason is BrightnessReason.CONFIG_MISSING


def test_missing_source_is_reported_as_missing_not_unavailable() -> None:
    """Without a configured sensor the reason is source_missing."""
    result = classify_brightness(None, CFG, None, source_configured=False)
    assert result.reason is BrightnessReason.SOURCE_MISSING


def test_tracker_keeps_state_inside_band_and_switches_outside() -> None:
    """Transitions dark -> band -> bright -> band use the last known outside state."""
    tracker = BrightnessTracker()
    assert (
        tracker.update(value=80.0, config=CFG, source_id=SRC).state
        is BrightnessState.DARK
    )
    assert (
        tracker.update(value=100.0, config=CFG, source_id=SRC).state
        is BrightnessState.DARK
    )
    assert (
        tracker.update(value=120.0, config=CFG, source_id=SRC).state
        is BrightnessState.BRIGHT
    )
    assert (
        tracker.update(value=100.0, config=CFG, source_id=SRC).state
        is BrightnessState.BRIGHT
    )


def test_restart_inside_band_is_unknown_until_outside_reading() -> None:
    """E3: a new tracker (restart) without a known state reports UNKNOWN in the band."""
    assert (
        BrightnessTracker().update(value=100.0, config=CFG, source_id=SRC).state
        is BrightnessState.UNKNOWN
    )
    tracker = BrightnessTracker()
    assert (
        tracker.update(value=100.0, config=CFG, source_id=SRC).state
        is BrightnessState.UNKNOWN
    )
    assert (
        tracker.update(value=85.0, config=CFG, source_id=SRC).state
        is BrightnessState.DARK
    )


def test_sensor_failure_forgets_state_and_recovery_in_band_is_unknown() -> None:
    """No old DARK is used during a sensor outage; after recovery the band is UNKNOWN."""
    tracker = BrightnessTracker()
    tracker.update(value=80.0, config=CFG, source_id=SRC)
    during_outage = tracker.update(value=None, config=CFG, source_id=SRC)
    assert during_outage.state is BrightnessState.UNKNOWN
    assert tracker.last_known is None
    assert (
        tracker.update(value=100.0, config=CFG, source_id=SRC).state
        is BrightnessState.UNKNOWN
    )


def test_sensor_change_and_config_change_do_not_carry_state() -> None:
    """A different source or changed limits start without the old memory."""
    tracker = BrightnessTracker()
    tracker.update(value=80.0, config=CFG, source_id=SRC)
    assert (
        tracker.update(value=100.0, config=CFG, source_id="sensor.other").state
        is BrightnessState.UNKNOWN
    )
    tracker = BrightnessTracker()
    tracker.update(value=80.0, config=CFG, source_id=SRC)
    changed = LightPolicyConfig(80.0, 120.0)
    assert (
        tracker.update(value=100.0, config=changed, source_id=SRC).state
        is BrightnessState.UNKNOWN
    )


def test_missing_configuration_clears_memory() -> None:
    """Removing the Lux limits forgets the state; re-adding them starts fresh."""
    tracker = BrightnessTracker()
    tracker.update(value=80.0, config=CFG, source_id=SRC)
    assert (
        tracker.update(value=100.0, config=None, source_id=SRC).reason
        is BrightnessReason.CONFIG_MISSING
    )
    assert (
        tracker.update(value=100.0, config=CFG, source_id=SRC).state
        is BrightnessState.UNKNOWN
    )
