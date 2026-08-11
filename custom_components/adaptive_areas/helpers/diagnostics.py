"""Privacy helpers for Adaptive Areas diagnostics."""

from typing import Any

from homeassistant.const import ATTR_DEVICE_CLASS, STATE_ON
from homeassistant.core import HomeAssistant


def safe_entity_descriptor(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Describe an entity without exposing its object ID or state payload."""
    domain = entity_id.partition(".")[0]
    state = hass.states.get(entity_id)
    return {
        "reference": f"{domain}.<redacted>",
        "domain": domain,
        "device_class": state.attributes.get(ATTR_DEVICE_CLASS) if state else None,
        "active": bool(state and state.state == STATE_ON),
        "available": state is not None and state.state != "unavailable",
    }
