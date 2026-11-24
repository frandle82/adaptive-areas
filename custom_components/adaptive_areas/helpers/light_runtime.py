"""Event-driven runtime for configured Light policies."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import replace
from collections.abc import Callable

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.adaptive_areas.const import (
    CONF_FEATURE_LIGHT,
    AdaptiveAreasEvents,
)
from custom_components.adaptive_areas.helpers.light_origin import (
    complete_request,
    current_area_signal,
    fail_request,
    new_policy_context,
)
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
from custom_components.adaptive_areas.helpers.light_ownership_runtime import (
    conflicted_lights,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    evaluate_light_policy,
    light_policy_config_from_feature,
)
from custom_components.adaptive_areas.helpers.sources import (
    automatic_group_lights,
    light_source_snapshot,
)

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
        try:
            await manager.async_setup()
        except BaseException:
            # Listeners installed before the failure must not stay subscribed.
            manager.unload()
            raise
        return manager

    async def async_setup(self) -> None:
        """Install the current targeted source listeners and evaluate once."""
        snapshot = light_source_snapshot(self.area)
        if snapshot is None:
            return
        # Presence is not a direct trigger: a source event arrives before the Area's
        # presence update, so evaluating on it would read a stale occupancy. The Area
        # state signal is sent after the update, so the policy re-evaluates on it.
        self._removers.append(
            async_dispatcher_connect(
                self.hass,
                AdaptiveAreasEvents.AREA_STATE_CHANGED,
                self._async_area_state_changed,
            )
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
    def _async_area_state_changed(self, area_id, _states_tuple) -> None:
        """Re-evaluate after this Area's presence update has been applied."""
        if self._unloaded or str(area_id) != str(self.area.id):
            return
        # Captured now, in the same callback that the light groups use: policy and
        # groups decide on one occupancy, even if the Area changes again before the task runs.
        self.hass.async_create_task(
            self.async_evaluate(
                light_source_snapshot(self.area),
                signal_id=current_area_signal(self.area),
            )
        )

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

    async def async_evaluate(self, snapshot=None, signal_id=None) -> None:
        """Resolve sources, evaluate policy, and dispatch once if needed.

        A snapshot captured at the Area state signal is used as is, so the policy decides
        on the same occupancy as the light groups that handled the same signal.
        """
        async with self._lock:
            if self._unloaded:
                return
            try:
                policy = light_policy_config_from_feature(
                    self.area.feature_config(CONF_FEATURE_LIGHT)
                )
                if snapshot is None:
                    snapshot = light_source_snapshot(self.area)
                if policy is None or snapshot is None:
                    self._last_dispatched_action = None
                    return
                # Automatically controlled group lights belong to the group automation only.
                # The policy never switches them (no double command for one physical light).
                # Lights with a runtime ownership conflict are never a policy target either:
                # no Area may switch a light that another Area also controls automatically.
                group_lights = automatic_group_lights(self.area) | conflicted_lights(
                    self.hass
                )
                policy_snapshot = replace(
                    snapshot,
                    targets=tuple(
                        target
                        for target in snapshot.targets
                        if target.entity_id not in group_lights
                    ),
                )
                decision = evaluate_light_policy(policy_snapshot, policy)
                self._manual_override_state = reset_manual_override_for_presence(
                    previous_state=self._manual_override_state,
                    occupied=(
                        snapshot.presence_state if snapshot.presence_available else None
                    ),
                )
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
                context = new_policy_context(
                    self.area,
                    signal_id,
                    service=(
                        "turn_on"
                        if decision.action is LightPolicyAction.TURN_ON
                        else "turn_off"
                    ),
                    target=",".join(
                        sorted(
                            t.entity_id for t in policy_snapshot.targets if t.available
                        )
                    ),
                )
                self._own_action_context_ids.append(context.id)
                try:
                    result = await async_execute_light_decision(
                        self.hass, policy_snapshot, decision, context=context
                    )
                except BaseException:
                    # Includes task cancellation: the request must not stay pending.
                    fail_request(self.area, context.id)
                    # A failed attempt is not repeated for an unchanged decision basis. A
                    # real change of the decision basis resets the marker (see above).
                    self._last_dispatched_action = decision.action
                    raise
                complete_request(self.area, context.id)
                if result.executed:
                    self._last_dispatched_action = decision.action
            except Exception:
                _LOGGER.exception(
                    "Light policy dispatch failed for Area %s", self.area.id
                )

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
        self._manual_override_state = LightManualOverrideState()
        self._own_action_context_ids.clear()
        for remove in list(self._removers):
            try:
                remove()
            except Exception:
                _LOGGER.exception(
                    "Failed to remove a light listener of Area %s", self.area.id
                )
        self._removers.clear()
