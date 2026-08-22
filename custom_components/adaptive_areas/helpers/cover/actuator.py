"""Safe Home Assistant service actuation for cover decisions."""

from collections.abc import Callable
from datetime import datetime, timedelta
import logging

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    CoverEntityFeature,
)
from homeassistant.components.cover.const import (
    ATTR_POSITION,
    DOMAIN as COVER_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .models import CoverDecision

_LOGGER = logging.getLogger(__name__)

POSITION_TOLERANCE = 2
COMMAND_DEDUP_WINDOW = timedelta(seconds=10)


class CoverActuator:
    """Translate decisions into deduplicated HA cover service calls."""

    def __init__(
        self,
        hass: HomeAssistant,
        mark_own_command: Callable[[str, datetime], None],
    ) -> None:
        """Initialize the actuator."""
        self.hass = hass
        self._mark_own_command = mark_own_command
        self._in_flight: set[tuple[str, int]] = set()
        self._last_commands: dict[str, tuple[int, datetime]] = {}

    async def async_apply(
        self, decision: CoverDecision
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Apply a decision and return unsupported and unavailable covers."""
        if decision.target_position is None:
            return (), ()
        unsupported: list[str] = []
        unavailable: list[str] = []
        for entity_id in decision.covers:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                unavailable.append(entity_id)
                continue
            current = state.attributes.get(ATTR_CURRENT_POSITION)
            try:
                if (
                    current is not None
                    and abs(float(current) - decision.target_position)
                    <= POSITION_TOLERANCE
                ):
                    continue
            except TypeError, ValueError:
                pass
            command = (entity_id, decision.target_position)
            if command in self._in_flight:
                continue
            now = dt_util.utcnow()
            last = self._last_commands.get(entity_id)
            if (
                last is not None
                and last[0] == decision.target_position
                and now - last[1] <= COMMAND_DEDUP_WINDOW
            ):
                continue
            features = int(state.attributes.get(ATTR_SUPPORTED_FEATURES, 0))
            if (
                decision.target_position not in (0, 100)
                and not features & CoverEntityFeature.SET_POSITION
            ):
                unsupported.append(entity_id)
                continue
            service = SERVICE_SET_COVER_POSITION
            data = {ATTR_ENTITY_ID: entity_id, ATTR_POSITION: decision.target_position}
            if decision.target_position == 100:
                service = SERVICE_OPEN_COVER
                data.pop(ATTR_POSITION)
            elif decision.target_position == 0:
                service = SERVICE_CLOSE_COVER
                data.pop(ATTR_POSITION)
            self._in_flight.add(command)
            self._last_commands[entity_id] = (decision.target_position, now)
            self._mark_own_command(entity_id, now)
            try:
                await self.hass.services.async_call(
                    COVER_DOMAIN, service, data, blocking=True
                )
            except Exception:  # noqa: BLE001 - device service failures stay isolated
                _LOGGER.exception("Cover command failed for %s", entity_id)
            finally:
                self._in_flight.discard(command)
        return tuple(unsupported), tuple(unavailable)
