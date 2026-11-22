"""Event-driven runtime for configured Light policies."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from custom_components.adaptive_areas.const import CONF_FEATURE_LIGHT
from custom_components.adaptive_areas.helpers.light_executor import (
    async_execute_light_decision,
)
from custom_components.adaptive_areas.helpers.light_override import (
    LightManualAction,
    LightManualDetection,
    LightManualOverrideState,
    apply_manual_light_action,
    apply_manual_override,
    detect_manual_light_action,
    reset_manual_override_for_presence,
)
from custom_components.adaptive_areas.helpers.light_vacancy import (
    LightVacancyState,
    evaluate_vacancy_delay,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyReason,
    evaluate_light_policy,
    light_policy_config_from_feature,
    light_vacancy_delay_from_feature,
)
from custom_components.adaptive_areas.helpers.sources import light_source_snapshot

_LOGGER = logging.getLogger(__name__)


class LightRuntimeManager:
    """Evaluate one configured regular Area from targeted source changes."""

    def __init__(self, area) -> None:
        """Initialize isolated listeners, dispatch state, and vacancy timing."""
        self.area = area
        self.hass: HomeAssistant = area.hass
        self._removers: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._last_dispatched_action: LightPolicyAction | None = None
        self._vacancy_state = LightVacancyState()
        self._vacancy_timer_unsub: Callable[[], None] | None = None
        self._manual_override_state = LightManualOverrideState()
        self._own_action_context_ids: deque[str] = deque(maxlen=64)
        self._unloaded = False

    @classmethod
    async def async_create(cls, area) -> LightRuntimeManager | None:
        """Create only for regular Areas with a complete Light policy."""
        if area.is_meta() or not area.has_feature(CONF_FEATURE_LIGHT):
            return None
        try:
            policy = light_policy_config_from_feature(
                area.feature_config(CONF_FEATURE_LIGHT)
            )
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
        """Handle availability separately from conservative manual detection."""
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        old_available = old is not None and old.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        )
        new_available = new is not None and new.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        )
        if old_available != new_available:
            self._async_trigger(event)
        detection = detect_manual_light_action(
            old_state=old,
            new_state=new,
            own_context_ids=self._own_action_context_ids,
        )
        if detection is LightManualDetection.OWN_AUTOMATION:
            self._discard_own_context(new.context)
        elif detection is LightManualDetection.MANUAL_ON:
            self._manual_override_state = apply_manual_light_action(
                previous_state=self._manual_override_state,
                manual_action=LightManualAction.TURN_ON,
                now=self.hass.loop.time(),
            )
        elif detection is LightManualDetection.MANUAL_OFF:
            self._manual_override_state = apply_manual_light_action(
                previous_state=self._manual_override_state,
                manual_action=LightManualAction.TURN_OFF,
                now=self.hass.loop.time(),
            )

    def _discard_own_context(self, context: Context) -> None:
        """Forget direct or child context IDs after their target event arrives."""
        for context_id in (context.id, context.parent_id):
            if context_id in self._own_action_context_ids:
                self._own_action_context_ids.remove(context_id)

    async def async_evaluate(self) -> None:
        """Resolve fresh sources, evaluate policy, and dispatch once if needed."""
        async with self._lock:
            if self._unloaded:
                return
            try:
                policy = light_policy_config_from_feature(
                    self.area.feature_config(CONF_FEATURE_LIGHT)
                )
                delay = light_vacancy_delay_from_feature(
                    self.area.feature_config(CONF_FEATURE_LIGHT)
                )
                snapshot = light_source_snapshot(self.area)
                if policy is None or snapshot is None:
                    self._clear_vacancy()
                    self._last_dispatched_action = None
                    return
                decision = evaluate_light_policy(snapshot, policy)
                vacancy = evaluate_vacancy_delay(
                    occupied=(
                        snapshot.presence_state if snapshot.presence_available else None
                    ),
                    now=self.hass.loop.time(),
                    delay=delay,
                    previous_state=self._vacancy_state,
                )
                self._manual_override_state = reset_manual_override_for_presence(
                    previous_state=self._manual_override_state,
                    occupied=(
                        snapshot.presence_state if snapshot.presence_available else None
                    ),
                )
                if (
                    decision.reason is LightPolicyReason.UNOCCUPIED
                    and delay is not None
                    and delay > 0
                    and not vacancy.off_due
                ):
                    self._vacancy_state = vacancy.state
                    if self._vacancy_timer_unsub is None:
                        due_at = vacancy.state.due_at
                        assert due_at is not None
                        self._vacancy_timer_unsub = async_call_later(
                            self.hass,
                            due_at - self.hass.loop.time(),
                            self._async_vacancy_due,
                        )
                    return
                if (
                    snapshot.presence_state is not False
                    or not snapshot.presence_available
                ):
                    self._clear_vacancy()
                elif vacancy.off_due:
                    self._clear_vacancy()
                if decision.action in (
                    LightPolicyAction.HOLD,
                    LightPolicyAction.NO_ACTION,
                ):
                    self._last_dispatched_action = None
                    return
                override = apply_manual_override(
                    override_state=self._manual_override_state,
                    decision=decision,
                )
                if not override.allowed:
                    return
                if decision.action is self._last_dispatched_action:
                    return
                context = Context()
                self._own_action_context_ids.append(context.id)
                result = await async_execute_light_decision(
                    self.hass, snapshot, decision, context=context
                )
                if result.executed:
                    self._last_dispatched_action = decision.action
            except Exception:
                _LOGGER.exception(
                    "Light policy dispatch failed for Area %s", self.area.id
                )

    @callback
    def _async_vacancy_due(self, _now=None) -> None:
        """Re-evaluate fresh sources when the single vacancy deadline expires."""
        self._vacancy_timer_unsub = None
        if not self._unloaded:
            self.hass.async_create_task(self.async_evaluate())

    def _clear_vacancy(self) -> None:
        """Cancel the pending area-local vacancy timer and state."""
        if self._vacancy_timer_unsub is not None:
            self._vacancy_timer_unsub()
            self._vacancy_timer_unsub = None
        self._vacancy_state = LightVacancyState()

    @property
    def vacancy_state(self) -> LightVacancyState:
        """Return the current vacancy state without exposing timer controls."""
        return self._vacancy_state

    @property
    def override_state(self) -> LightManualOverrideState:
        """Return the current manual override state without allowing mutation."""
        return self._manual_override_state

    @property
    def last_dispatched_action(self) -> LightPolicyAction | None:
        """Return the last executed on/off action, or None after a neutral evaluation."""
        return self._last_dispatched_action

    def unload(self) -> None:
        """Remove all targeted listeners owned by this manager."""
        self._unloaded = True
        self._clear_vacancy()
        self._manual_override_state = LightManualOverrideState()
        self._own_action_context_ids.clear()
        for remove in self._removers:
            remove()
        self._removers.clear()
