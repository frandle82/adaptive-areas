"""Tests for deterministic Area cover decisions."""

from datetime import UTC, datetime, timedelta

import pytest
import voluptuous as vol

from custom_components.adaptive_areas.const import (
    CONF_COVER_CLOSE_BRIGHTNESS,
    CONF_COVER_CLOSE_BRIGHTNESS_ENABLED,
    CONF_COVER_CLOSE_ENABLED,
    CONF_COVER_CLOSE_SLEEP_STARTED,
    CONF_COVER_CLOSE_WINDOW,
    CONF_COVER_FORECAST_ENABLED,
    CONF_COVER_FORECAST_THRESHOLD,
    CONF_COVER_OPEN_BRIGHTNESS,
    CONF_COVER_OPEN_BRIGHTNESS_ENABLED,
    CONF_COVER_OPEN_ENABLED,
    CONF_COVER_OPEN_SLEEP_ENDED,
    CONF_COVER_OPEN_SUN_ENABLED,
    CONF_COVER_OPEN_SUN_ELEVATION,
    CONF_COVER_OPEN_WINDOW,
    CONF_COVER_MANUAL_OVERRIDE_MINUTES,
    CONF_COVER_SHADING_BRIGHTNESS_ENABLED,
    CONF_COVER_SHADING_BRIGHTNESS_THRESHOLD,
    CONF_COVER_SHADING_COVERS,
    CONF_COVER_SHADING_ENABLED,
    CONF_COVER_SHADING_SCOPE,
    CONF_COVER_SHADING_SOURCE,
    CONF_COVER_TEMPERATURE_THRESHOLD,
    COVER_SHADING_SCOPE_SELECTED,
    COVER_SHADING_SOURCE_AREA_CLIMATE,
    COVER_SHADING_SOURCE_ENTITY,
    COVER_CONTROL_FEATURE_SCHEMA,
)
from custom_components.adaptive_areas.helpers.cover.models import (
    CoverAction,
    CoverInputs,
)
from custom_components.adaptive_areas.helpers.cover.strategy import CoverStrategy

NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
COVERS = ("cover.south", "cover.west")


def decide(config: dict, **kwargs):
    """Evaluate with safe known defaults."""
    return CoverStrategy(config, COVERS).evaluate(
        CoverInputs(now=NOW, trigger="input_changed", **kwargs)
    )


@pytest.mark.parametrize(
    ("trigger", "extra", "reason"),
    [
        ("window_open", {CONF_COVER_OPEN_WINDOW: True}, "window_open"),
        ("sleep_ended", {CONF_COVER_OPEN_SLEEP_ENDED: True}, "sleep_ended"),
    ],
)
def test_open_edge_sources(trigger: str, extra: dict, reason: str) -> None:
    """Window and sleep edges request opening only when enabled."""
    decision = CoverStrategy({CONF_COVER_OPEN_ENABLED: True, **extra}, COVERS).evaluate(
        CoverInputs(now=NOW, trigger=trigger)
    )
    assert decision.action == CoverAction.OPEN
    assert decision.reason == reason


def test_open_sun_brightness_and_sleep_gate() -> None:
    """Continuous open sources respect their exact boundary and sleep gate."""
    sun = decide(
        {
            CONF_COVER_OPEN_ENABLED: True,
            CONF_COVER_OPEN_SUN_ENABLED: True,
            CONF_COVER_OPEN_SUN_ELEVATION: -3,
        },
        sun_elevation=-3,
    )
    assert sun.reason == "sun_open"
    brightness = decide(
        {
            CONF_COVER_OPEN_ENABLED: True,
            CONF_COVER_OPEN_BRIGHTNESS_ENABLED: True,
            CONF_COVER_OPEN_BRIGHTNESS: 300,
        },
        brightness=300,
        sleep=True,
    )
    assert brightness.blocked_by == "blocked_sleep"


def test_close_window_protection_and_pending_close() -> None:
    """A protected close remains pending until the window closes."""
    config = {
        CONF_COVER_CLOSE_ENABLED: True,
        CONF_COVER_CLOSE_SLEEP_STARTED: True,
        CONF_COVER_CLOSE_WINDOW: True,
    }
    blocked = CoverStrategy(config, COVERS).evaluate(
        CoverInputs(now=NOW, trigger="sleep_started", windows_open=True)
    )
    assert blocked.blocked_by == "blocked_window_open"
    resumed = CoverStrategy(config, COVERS).evaluate(
        CoverInputs(now=NOW, trigger="window_closed", pending_close=True)
    )
    assert resumed.action == CoverAction.CLOSE
    assert resumed.reason == "window_closed"


@pytest.mark.parametrize(
    ("heat", "reason"),
    [("recommended", "indoor_heat"), ("required", "indoor_heat_required")],
)
def test_area_climate_shading(heat: str, reason: str) -> None:
    """Area Climate demand maps to stable shading reasons."""
    decision = decide(
        {
            CONF_COVER_SHADING_ENABLED: True,
            CONF_COVER_SHADING_SOURCE: COVER_SHADING_SOURCE_AREA_CLIMATE,
        },
        area_climate_enabled=True,
        area_climate_heat=heat,
    )
    assert decision.action == CoverAction.SHADE
    assert decision.reason == reason


@pytest.mark.parametrize(
    ("value", "expected"),
    [(23.999, CoverAction.NONE), (24, CoverAction.SHADE), (24.001, CoverAction.SHADE)],
)
def test_fallback_temperature_boundary(value: float, expected: CoverAction) -> None:
    """Fallback temperature uses an inclusive threshold."""
    decision = decide(
        {
            CONF_COVER_SHADING_ENABLED: True,
            CONF_COVER_SHADING_SOURCE: COVER_SHADING_SOURCE_ENTITY,
            CONF_COVER_TEMPERATURE_THRESHOLD: 24,
        },
        fallback_temperature=value,
    )
    assert decision.action == expected


@pytest.mark.parametrize(
    ("brightness", "expected"),
    [
        (9999.999, CoverAction.NONE),
        (10000, CoverAction.SHADE),
        (10000.001, CoverAction.SHADE),
    ],
)
def test_brightness_gate_boundary(brightness: float, expected: CoverAction) -> None:
    """The brightness gate uses an inclusive threshold."""
    decision = decide(
        {
            CONF_COVER_SHADING_ENABLED: True,
            CONF_COVER_SHADING_SOURCE: COVER_SHADING_SOURCE_AREA_CLIMATE,
            CONF_COVER_SHADING_BRIGHTNESS_ENABLED: True,
            CONF_COVER_SHADING_BRIGHTNESS_THRESHOLD: 10000,
        },
        area_climate_enabled=True,
        area_climate_heat="recommended",
        brightness=brightness,
    )
    assert decision.action == expected


def test_forecast_shading_selected_covers_and_missing_forecast() -> None:
    """Forecast heat shades only selected covers and tolerates missing data."""
    config = {
        CONF_COVER_SHADING_ENABLED: True,
        CONF_COVER_SHADING_SOURCE: COVER_SHADING_SOURCE_AREA_CLIMATE,
        CONF_COVER_FORECAST_ENABLED: True,
        CONF_COVER_FORECAST_THRESHOLD: 25,
        CONF_COVER_SHADING_SCOPE: COVER_SHADING_SCOPE_SELECTED,
        CONF_COVER_SHADING_COVERS: ["cover.west"],
    }
    hot = decide(
        config,
        area_climate_enabled=True,
        area_climate_heat="none",
        forecast_temperature=25,
    )
    assert hot.reason == "forecast_heat"
    assert hot.covers == ("cover.west",)
    assert decide(config, area_climate_enabled=True).action == CoverAction.NONE


def test_conditions_unknown_and_manual_override_block() -> None:
    """Closed gates and active manual overrides block normal movement."""
    condition = decide(
        {
            CONF_COVER_SHADING_ENABLED: True,
            CONF_COVER_SHADING_SOURCE: COVER_SHADING_SOURCE_AREA_CLIMATE,
        },
        area_climate_enabled=True,
        area_climate_heat="required",
        shading_condition=False,
    )
    assert condition.blocked_by == "blocked_condition"
    override = decide(
        {
            CONF_COVER_CLOSE_ENABLED: True,
            CONF_COVER_CLOSE_BRIGHTNESS_ENABLED: True,
            CONF_COVER_CLOSE_BRIGHTNESS: 100,
        },
        brightness=50,
        manual_override_until=NOW + timedelta(minutes=30),
    )
    assert override.blocked_by == "blocked_manual_override"


def test_unknown_area_climate_never_falls_back() -> None:
    """Unknown enabled Area Climate data cannot select the entity fallback."""
    decision = decide(
        {
            CONF_COVER_SHADING_ENABLED: True,
            CONF_COVER_SHADING_SOURCE: COVER_SHADING_SOURCE_AREA_CLIMATE,
            CONF_COVER_TEMPERATURE_THRESHOLD: 24,
        },
        area_climate_enabled=True,
        area_climate_heat="unknown",
        fallback_temperature=30,
    )
    assert decision.action == CoverAction.NONE


@pytest.mark.parametrize("minutes", [15, 30, 60, 120])
def test_manual_override_duration_values(minutes: int) -> None:
    """All documented manual override durations validate."""
    assert (
        COVER_CONTROL_FEATURE_SCHEMA({CONF_COVER_MANUAL_OVERRIDE_MINUTES: minutes})[
            CONF_COVER_MANUAL_OVERRIDE_MINUTES
        ]
        == minutes
    )


@pytest.mark.parametrize("minutes", [0, 1441])
def test_manual_override_duration_boundaries_reject_invalid(minutes: int) -> None:
    """Override duration validation rejects values outside the safe range."""
    with pytest.raises(vol.Invalid):
        COVER_CONTROL_FEATURE_SCHEMA({CONF_COVER_MANUAL_OVERRIDE_MINUTES: minutes})
