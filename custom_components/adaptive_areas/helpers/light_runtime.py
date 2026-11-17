"""Event-driven runtime for configured Light policies."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.adaptive_areas.const import CONF_FEATURE_LIGHT
from custom_components.adaptive_areas.helpers.light_executor import (
    async_execute_light_decision,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    evaluate_light_policy,
    light_policy_config_from_feature,
)
from custom_components.adaptive_areas.helpers.sources import light_source_snapshot

_LOGGER = logging.getLogger(__name__)


class LightRuntimeManager:
    """Evaluate one configured regular Area from targeted source changes."""

    def __init__(self, area) -> None:
        self.area = area
        self.hass: HomeAssistant = area.hass
        self._removers: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._last_dispatched_action: LightPolicyAction | None = None
        self._unloaded = False

    @classmethod
    async def async_create(cls, area) -> LightRuntimeManager | None:
        """Create only for regular Areas with a complete Light policy."""
        if area.is_meta() or not area.has_feature(CONF_FEATURE_LIGHT):
            return None
        try:
            policy = light_policy_config_from_feature(area.feature_config(CONF_FEATURE_LIGHT))
        except ValueError:
            return None
        if policy is None:
            return None
        manager = cls(area)
        await manager.async_setup()
        return manager

    async def async_setup(self) -> None:
        """Install the current targeted source listeners and evaluate once."""
        snapshot = light_source_snapshot(self.area)
        if snapshot is None:
            return
        presence = snapshot.presence_source_entity_ids
        if presence:
            self._removers.append(
                async_track_state_change_event(self.hass, presence, self._async_trigger)
            )
        if snapshot.illuminance_entity_id:
            self._removers.append(
                async_track_state_change_event(
                    self.hass, [snapshot.illuminance_entity_id], self._async_trigger
                )
            )
        target_ids = [target.entity_id for target in snapshot.targets]
        if target_ids:
            self._removers.append(
                async_track_state_change_event(
                    self.hass, target_ids, self._async_target_availability_change
                )
            )
        await self.async_evaluate()

    @callback
    def _async_trigger(self, _event: Event) -> None:
        if not self._unloaded:
            self.hass.async_create_task(self.async_evaluate())

    @callback
    def _async_target_availability_change(self, event: Event) -> None:
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        old_available = old is not None and old.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        new_available = new is not None and new.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        if old_available != new_available:
            self._async_trigger(event)

    async def async_evaluate(self) -> None:
        """Resolve fresh sources, evaluate policy, and dispatch once if needed."""
        async with self._lock:
            if self._unloaded:
                return
            try:
                policy = light_policy_config_from_feature(
                    self.area.feature_config(CONF_FEATURE_LIGHT)
                )
                snapshot = light_source_snapshot(self.area)
                if policy is None or snapshot is None:
                    self._last_dispatched_action = None
                    return
                decision = evaluate_light_policy(snapshot, policy)
                if decision.action in (LightPolicyAction.HOLD, LightPolicyAction.NO_ACTION):
                    self._last_dispatched_action = None
                    return
                if decision.action is self._last_dispatched_action:
                    return
                result = await async_execute_light_decision(self.hass, snapshot, decision)
                if result.executed:
                    self._last_dispatched_action = decision.action
            except Exception:
                _LOGGER.exception("Light policy dispatch failed for Area %s", self.area.id)

    def unload(self) -> None:
        """Remove all targeted listeners owned by this manager."""
        self._unloaded = True
        for remove in self._removers:
            remove()
        self._removers.clear()
