"""Tests for cover-control runtime state."""

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.adaptive_areas.const import (
    CONF_COVER_MANUAL_OVERRIDE_ENABLED,
    CONF_COVER_MANUAL_OVERRIDE_MINUTES,
    CONF_COVER_FORECAST_ENABLED,
    CONF_COVER_FORECAST_ENTITY,
)
from custom_components.adaptive_areas.helpers.cover.controller import (
    OWN_COMMAND_WINDOW,
    AreaCoverController,
)


def _controller(
    hass: HomeAssistant, minutes: int = 30, extra: dict | None = None
) -> AreaCoverController:
    """Build a minimal controller without starting listeners."""
    config = {
        CONF_COVER_MANUAL_OVERRIDE_ENABLED: True,
        CONF_COVER_MANUAL_OVERRIDE_MINUTES: minutes,
    }
    config.update(extra or {})
    area = SimpleNamespace(
        hass=hass,
        entities={"cover": [{"entity_id": "cover.test"}]},
        feature_config=lambda _feature: config,
        has_state=lambda _state: False,
        has_feature=lambda _feature: False,
        trace_decision=lambda **_kwargs: None,
        environment=None,
        id="test",
        config={},
    )
    return AreaCoverController(area)


def test_own_command_does_not_start_manual_override(hass: HomeAssistant) -> None:
    """A state transition in the plausible own-command window is ignored."""
    controller = _controller(hass)
    controller._mark_own_command("cover.test", dt_util.utcnow())

    controller._detect_manual_movement("cover.test")

    assert controller.runtime.manual_override_until is None


def test_external_command_starts_configured_manual_override(
    hass: HomeAssistant,
) -> None:
    """A movement outside the own-command window starts the configured pause."""
    controller = _controller(hass, minutes=60)
    now = dt_util.utcnow()
    controller._mark_own_command(
        "cover.test", now - OWN_COMMAND_WINDOW - timedelta(seconds=1)
    )

    controller._detect_manual_movement("cover.test")

    assert controller.runtime.manual_override_until is not None
    remaining = controller.runtime.manual_override_until - now
    assert (
        timedelta(minutes=59, seconds=59)
        <= remaining
        <= timedelta(minutes=60, seconds=1)
    )
    controller.async_stop()


async def test_forecast_uses_home_assistant_weather_service(
    hass: HomeAssistant,
) -> None:
    """Preventive shading obtains a simple maximum from HA forecast data."""

    async def forecast(_call: ServiceCall) -> dict:
        return {
            "weather.home": {"forecast": [{"temperature": 23}, {"temperature": 27}]}
        }

    hass.services.async_register(
        "weather",
        "get_forecasts",
        forecast,
        supports_response=SupportsResponse.ONLY,
    )
    controller = _controller(
        hass,
        extra={
            CONF_COVER_FORECAST_ENABLED: True,
            CONF_COVER_FORECAST_ENTITY: "weather.home",
        },
    )

    await controller._async_update_forecast()

    assert controller.runtime.forecast_temperature == 27


async def test_manual_override_expiry_requests_reevaluation(
    hass: HomeAssistant,
) -> None:
    """The timer clears a temporary override and safely re-evaluates."""
    controller = _controller(hass, minutes=15)
    start = dt_util.utcnow()
    controller._detect_manual_movement("cover.test")
    assert controller.runtime.manual_override_until is not None

    async_fire_time_changed(hass, start + timedelta(minutes=15, seconds=1))
    await hass.async_block_till_done()

    assert controller.runtime.manual_override_until is None
    assert controller.runtime.last_decision.blocked_by == "blocked_unavailable"
    controller.async_stop()
