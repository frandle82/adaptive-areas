"""Tests for safe cover service actuation."""

from datetime import datetime

from homeassistant.components.cover import ATTR_CURRENT_POSITION, CoverEntityFeature
from homeassistant.components.cover.const import DOMAIN as COVER_DOMAIN
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.adaptive_areas.helpers.cover.actuator import CoverActuator
from custom_components.adaptive_areas.helpers.cover.models import (
    CoverAction,
    CoverDecision,
)


async def test_actuator_deduplicates_position_and_reports_unsupported(
    hass: HomeAssistant,
) -> None:
    """Reached targets are skipped and unsupported partial covers are diagnosed."""
    calls: list[ServiceCall] = []
    marked: list[tuple[str, datetime]] = []

    async def record(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register(COVER_DOMAIN, "set_cover_position", record)
    hass.states.async_set(
        "cover.reached",
        "open",
        {
            ATTR_CURRENT_POSITION: 34,
            ATTR_SUPPORTED_FEATURES: CoverEntityFeature.SET_POSITION,
        },
    )
    hass.states.async_set(
        "cover.movable",
        "open",
        {
            ATTR_CURRENT_POSITION: 80,
            ATTR_SUPPORTED_FEATURES: CoverEntityFeature.SET_POSITION,
        },
    )
    hass.states.async_set(
        "cover.unsupported",
        "open",
        {ATTR_SUPPORTED_FEATURES: CoverEntityFeature.OPEN},
    )
    actuator = CoverActuator(
        hass, lambda entity_id, now: marked.append((entity_id, now))
    )

    unsupported, unavailable = await actuator.async_apply(
        CoverDecision(
            CoverAction.SHADE,
            35,
            "indoor_heat",
            covers=("cover.reached", "cover.movable", "cover.unsupported"),
        )
    )
    await actuator.async_apply(
        CoverDecision(
            CoverAction.SHADE,
            35,
            "indoor_heat",
            covers=("cover.movable",),
        )
    )

    assert [call.data["entity_id"] for call in calls] == ["cover.movable"]
    assert [entity_id for entity_id, _now in marked] == ["cover.movable"]
    assert unsupported == ("cover.unsupported",)
    assert unavailable == ()


async def test_actuator_isolates_unavailable_covers(hass: HomeAssistant) -> None:
    """Unavailable members do not crash or prevent diagnostics."""
    hass.states.async_set("cover.missing", "unavailable")
    actuator = CoverActuator(hass, lambda _entity_id, _now: None)

    unsupported, unavailable = await actuator.async_apply(
        CoverDecision(
            CoverAction.SHADE,
            35,
            "forecast_heat",
            covers=("cover.missing",),
        )
    )

    assert unsupported == ()
    assert unavailable == ("cover.missing",)
