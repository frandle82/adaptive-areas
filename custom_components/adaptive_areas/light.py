"""Platform file for Adaptive Area's light entities."""

import asyncio
import logging

from homeassistant.components.group.light import FORWARDED_ATTRIBUTES, LightGroup
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_EXCLUDE_ENTITIES,
    DOMAIN,
    EMPTY_STRING,
    EVENT_ADAPTIVEAREAS_AREA_STATE_CHANGED,
    LIGHT_GROUP_BLOCKING_STATES,
    LIGHT_GROUP_ACTIVATION,
    LIGHT_GROUP_ACTIVATION_DISABLED,
    LIGHT_GROUP_ACTIVATION_OCCUPIED,
    LIGHT_GROUP_BRIGHTNESS,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
    LIGHT_GROUP_CATEGORIES,
    LIGHT_GROUP_DEFAULT_ICON,
    LIGHT_GROUP_ICONS,
    SIGNAL_LIGHT_CONTROL_CHANGED,
    AdaptiveAreasEvents,
    AreaStates,
    LightGroupCategory,
    AdaptiveAreasFeatureInfoLightGroups,
    AdaptiveAreasFeatures,
)
from custom_components.adaptive_areas.helpers.area import (
    get_runtime_areas_for_entry,
    iter_runtime_areas,
)
from custom_components.adaptive_areas.helpers.brightness import BrightnessState
from custom_components.adaptive_areas.helpers.light_ownership_runtime import (
    excluded_members_by_group,
    group_is_blocked,
)
from custom_components.adaptive_areas.helpers.light_transition import (
    Override,
    MODE_DARK_ON_BRIGHT_OFF,
    MODE_IGNORE,
    MODE_REQUIRE_DARK,
    MODE_TURN_OFF,
    AreaState,
    GroupConfig,
    TransitionAction,
    initial_decision,
    transition_decision,
)
from custom_components.adaptive_areas.helpers.light_origin import (
    new_light_group_context,
    request_for_context,
)
from custom_components.adaptive_areas.helpers.sources import area_presence_available
from custom_components.adaptive_areas.helpers.light_groups import (
    migrate_light_group_feature_config,
)
from custom_components.adaptive_areas.util import cleanup_removed_entries

_LOGGER = logging.getLogger(__name__)
ATTR_MANUAL_OVERRIDE = "manual_override"


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the area light config entry.

    Regular Areas come before Meta Areas in the runtime order. The light groups a
    child creates here are handed to its Meta Areas directly, so a Meta Area's ALL
    group exists on the very first setup, before the children's groups are in the
    entity registry.
    """
    created: dict[str, list[str]] = {}
    for area in get_runtime_areas_for_entry(hass, config_entry):
        groups = await _async_setup_area(hass, area, async_add_entities, created)
        created[area.id] = [_registered_or_default(hass, group) for group in groups]


def _registered_or_default(hass, group) -> str:
    """Return the registered entity ID of a group, or its default before registration."""
    return (
        er.async_get(hass).async_get_entity_id(LIGHT_DOMAIN, DOMAIN, group.unique_id)
        or group.entity_id
    )


def _meta_member_lights(area: AdaptiveArea, created: dict[str, list[str]]) -> list[str]:
    """Return the members of a Meta Area's ALL group.

    Children set up in this entry contribute the groups they created in this setup.
    Children of other (legacy) entries are known only through the registry, as before.
    """
    excluded = set(area.config.get(CONF_EXCLUDE_ENTITIES, []) or [])
    child_ids = {
        child.id
        for child in iter_runtime_areas(area.hass)
        if not child.is_meta() and child.slug in getattr(area, "child_areas", [])
    }
    members = [
        entity_id
        for child_id in sorted(child_ids & set(created))
        for entity_id in created[child_id]
    ]
    if not child_ids <= set(created):
        members.extend(e["entity_id"] for e in area.entities.get(LIGHT_DOMAIN, []))
    return [
        entity_id for entity_id in dict.fromkeys(members) if entity_id not in excluded
    ]


def _configured_group_lights(
    hass, area: AdaptiveArea, light_entities: list[str], feature_config
) -> list[str]:
    """Explicitly configured group members that may be controlled by this Area's groups.

    A member is accepted when it is a light that exists (state or registry entry) and is
    not excluded by `exclude_entities`. HA-Area membership is not required (Option C).
    Ownership conflicts are checked separately by the runtime.
    """
    excluded = set(area.config.get(CONF_EXCLUDE_ENTITIES, []) or [])
    registry = er.async_get(hass)
    accepted: list[str] = []
    configured = [
        entity_id
        for category in LIGHT_GROUP_CATEGORIES
        for entity_id in feature_config.get(category, {}) or {}
        if str(entity_id).startswith("light.")
    ]
    # A nested group that would switch an excluded lamp is not controlled at all.
    blocked_groups = excluded_members_by_group(hass, configured, excluded)
    for category in LIGHT_GROUP_CATEGORIES:
        for entity_id in feature_config.get(category, {}) or {}:
            if entity_id in blocked_groups:
                _LOGGER.warning(
                    "%s: group member %s not controlled: it would switch excluded lights %s",
                    area.name,
                    entity_id,
                    blocked_groups[entity_id],
                )
                continue
            if entity_id in excluded or not entity_id.startswith("light."):
                continue
            if entity_id in accepted:
                continue
            if (
                entity_id in light_entities
                or hass.states.get(entity_id) is not None
                or registry.async_get(entity_id) is not None
            ):
                accepted.append(entity_id)
    return accepted


async def _async_setup_area(
    hass, area: AdaptiveArea, async_add_entities, created: dict[str, list[str]]
) -> list:
    """Set up lights for one runtime Area and return the groups it created."""

    # Check feature availability
    if not area.has_feature(AdaptiveAreasFeatures.LIGHT_GROUPS):
        return []

    # Lights found through the Home Assistant Area. For a regular Area they are not a
    # precondition: explicitly configured, valid group members are authoritative and
    # need no Home Assistant Area assignment (Option C).
    light_entities = [e["entity_id"] for e in area.entities.get(LIGHT_DOMAIN, [])]

    light_groups = []

    # Create light groups
    if area.is_meta():
        light_entities = _meta_member_lights(area, created)
        if not light_entities:
            _LOGGER.debug("%s: No %s entities for area.", area.name, LIGHT_DOMAIN)
            return []
        light_groups.append(
            AdaptiveLightGroup(
                area, light_entities, translation_key=LightGroupCategory.ALL
            )
        )
    else:
        child_light_groups: list[AreaLightGroup] = []
        feature_config = area.feature_config(AdaptiveAreasFeatures.LIGHT_GROUPS)
        # An explicitly configured group member is authoritative (Option C): it does not
        # need to be found by the HA-Area entity lookup. Ownership is checked at runtime.
        configured_lights = set(
            _configured_group_lights(hass, area, light_entities, feature_config)
        )
        configured_light_entities = list(
            dict.fromkeys(
                light_entity
                for category in LIGHT_GROUP_CATEGORIES
                for light_entity in feature_config.get(category, {})
                if light_entity in configured_lights
            )
        )

        # Create extended light groups
        for category in LIGHT_GROUP_CATEGORIES:
            category_lights = [
                light_entity
                for light_entity in feature_config.get(category, {})
                if light_entity in configured_lights
            ]

            if category_lights:
                _LOGGER.debug(
                    "%s: Creating %s group for area with lights: %s",
                    area.name,
                    category,
                    category_lights,
                )
                light_group_object = AreaLightGroup(area, category_lights, category)
                light_groups.append(light_group_object)
                child_light_groups.append(light_group_object)

        if configured_light_entities:
            _LOGGER.debug(
                "%s: Creating Area light group for area with lights: %s",
                area.name,
                configured_light_entities,
            )
            light_groups.append(
                AreaLightGroup(
                    area,
                    configured_light_entities,
                    category=LightGroupCategory.ALL,
                    child_groups=child_light_groups,
                )
            )

    # Create all groups
    if light_groups:
        async_add_entities(light_groups)

    if LIGHT_DOMAIN in area.adaptive_entities:
        cleanup_removed_entries(
            area.hass, light_groups, area.adaptive_entities[LIGHT_DOMAIN]
        )
    return light_groups


class AdaptiveLightGroup(AdaptiveEntity, LightGroup):
    """Adaptive Light Group for Meta-areas."""

    feature_info = AdaptiveAreasFeatureInfoLightGroups()

    def __init__(self, area, entities, translation_key: str | None = None):
        """Initialize parent class and state."""
        AdaptiveEntity.__init__(
            self, area, domain=LIGHT_DOMAIN, translation_key=translation_key
        )
        LightGroup.__init__(
            self,
            name=EMPTY_STRING,
            unique_id=self.unique_id,
            entity_ids=entities,
            mode=False,
        )
        delattr(self, "_attr_name")

    def _get_active_lights(self) -> list[str]:
        """Return list of lights that are on."""
        active_lights = []
        for entity_id in self._entity_ids:
            light_state = self.hass.states.get(entity_id)
            if not light_state:
                continue
            if light_state.state == STATE_ON:
                active_lights.append(entity_id)

        return active_lights

    async def async_turn_on(self, **kwargs) -> None:
        """Forward the turn_on command to all lights in the light group."""

        data = {
            key: value for key, value in kwargs.items() if key in FORWARDED_ATTRIBUTES
        }

        # A plain turn_on should always target all lights in the group.
        # Restricting to active lights only makes sense for attribute updates
        # (brightness/color/etc.) to avoid turning additional lights on.
        if data:
            active_lights = self._get_active_lights() or self._entity_ids
            _LOGGER.debug(
                "%s: restricting attribute update to active lights: %s",
                self.area.name,
                str(active_lights),
            )
            data[ATTR_ENTITY_ID] = active_lights
        else:
            data[ATTR_ENTITY_ID] = self._entity_ids
            _LOGGER.debug(
                "%s: plain turn_on targets all lights: %s",
                self.area.name,
                str(self._entity_ids),
            )

        _LOGGER.debug("%s: Forwarded turn_on command: %s", self.area.name, data)

        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            data,
            blocking=True,
            context=self._context,
        )


class AreaLightGroup(AdaptiveLightGroup):
    """Adaptive Light Group."""

    # Volatile decision state; the instance attributes set in __init__ shadow these defaults.
    _decision_previous: AreaState | None = None
    _decision_seq: int = 0
    _initial_done: bool = False
    _pending_action: str | None = None
    _failed_action: str | None = None

    def __init__(self, area, entities, category=None, child_groups=None):
        """Initialize light group."""

        AdaptiveLightGroup.__init__(self, area, entities, translation_key=category)

        self._child_groups = child_groups or []

        self.category = category
        self.activation = LIGHT_GROUP_ACTIVATION_DISABLED
        self.blocking_states = []
        self.require_dark = True
        self.turn_off_when_bright = False

        self.controlling = True
        self.manual_override = False
        # Volatile decision state: the previous decision input and the command sequence.
        self._decision_previous: AreaState | None = None
        self._decision_seq = 0
        self._initial_done = False
        # Volatile lifecycle guard: set while this instance is listening, cleared on removal.
        # A reload creates a new instance, so a task of the old instance never sends a command.
        self._active = False
        self._clear_tasks: set[asyncio.Task] = set()

        self._icon = LIGHT_GROUP_DEFAULT_ICON

        if self.category and self.category != LightGroupCategory.ALL:
            self._icon = LIGHT_GROUP_ICONS.get(self.category, LIGHT_GROUP_DEFAULT_ICON)

        # Get assigned states
        if self.category and self.category != LightGroupCategory.ALL:
            feature_config, _ = migrate_light_group_feature_config(
                area.feature_config(AdaptiveAreasFeatures.LIGHT_GROUPS)
            )
            self.activation = feature_config[LIGHT_GROUP_ACTIVATION[self.category]]
            self.blocking_states = feature_config.get(
                LIGHT_GROUP_BLOCKING_STATES[self.category], []
            )
            brightness = feature_config[LIGHT_GROUP_BRIGHTNESS[self.category]]
            self.require_dark = brightness in (
                LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
                LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
            )
            self.turn_off_when_bright = brightness in (
                LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
                LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
            )
        elif self.category == LightGroupCategory.ALL:
            # Parent group should not inherit "turn_off_when_bright" from child
            # categories, otherwise it can immediately turn off lights that a
            # child group just turned on (e.g. task lights in bright rooms).
            # Brightness-based turn-off is handled on the child groups directly.
            self.turn_off_when_bright = False

        # Add static attributes
        self._attr_extra_state_attributes["lights"] = self._entity_ids
        self._attr_extra_state_attributes["controlling"] = self.controlling
        self._attr_extra_state_attributes[ATTR_MANUAL_OVERRIDE] = self.manual_override

        if self.category == LightGroupCategory.ALL:
            self._attr_extra_state_attributes["child_ids"] = []

        self.logger.debug(
            "%s: Light group (%s) created with entities: %s",
            self.area.name,
            category,
            str(self._entity_ids),
        )

    @property
    def icon(self):
        """Return the icon to be used for this entity."""
        return self._icon

    async def async_added_to_hass(self) -> None:
        """Restore state and setup listeners."""
        # Get last state
        last_state = await self.async_get_last_state()

        if last_state:
            self.logger.debug(
                "%s: State restored [state=%s]", self.name, last_state.state
            )
            self._attr_is_on = last_state.state == STATE_ON

            if "controlling" in last_state.attributes:
                controlling = last_state.attributes["controlling"]
                self.controlling = controlling
                self._attr_extra_state_attributes["controlling"] = self.controlling
            self.manual_override = bool(
                last_state.attributes.get(ATTR_MANUAL_OVERRIDE, False)
            )
            self._attr_extra_state_attributes[ATTR_MANUAL_OVERRIDE] = (
                self.manual_override
            )
            if self.manual_override:
                self._trace_override(
                    "state_restored", "manual_override_started", ["override_restored"]
                )
        else:
            self._attr_is_on = False

        self.schedule_update_ha_state()

        # Setup state change listeners
        await self._setup_listeners()
        self._apply_initial_decision()

        await super().async_added_to_hass()

        if self.category == LightGroupCategory.ALL:
            self._attr_extra_state_attributes["child_ids"] = [
                child_group.entity_id
                for child_group in self._child_groups
                if child_group.entity_id
            ]
            self.schedule_update_ha_state()

    async def _setup_listeners(self, _=None) -> None:
        """Set up listeners for area state chagne."""
        self._active = True
        self.async_on_remove(self._async_deactivate)
        # Enabling the automation is a relevant event: the current state is evaluated.
        # The Area's own switch reports it, whatever entity ID the registry gave it.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_LIGHT_CONTROL_CHANGED,
                self._async_control_switch_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                EVENT_ADAPTIVEAREAS_AREA_STATE_CHANGED,
                self.area_state_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                AdaptiveAreasEvents.AREA_PRESENCE_ACTIVITY,
                self.area_presence_activity,
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [
                    self.entity_id,
                ],
                self.group_state_changed,
            )
        )

    # State Change Handling

    @callback
    def area_state_changed(self, area_id, states_tuple):
        """Handle area state change event."""
        if area_id != self.area.id:
            self.logger.debug(
                "%s: Area state change event not for us. Skipping. (req: %s/self: %s)",
                self.name,
                area_id,
                self.area.id,
            )
            return

        self.logger.debug("%s: Light group detected area state change", self.name)

        # Handle all lights group
        if self.category == LightGroupCategory.ALL:
            return self.state_change_primary(states_tuple)

        # Handle light category
        return self.state_change_secondary(states_tuple)

    @callback
    def area_presence_activity(self, area_id: str, reason: str) -> bool:
        """Re-evaluate real-area child lights without resetting manual control."""
        if area_id != self.area.id or self.category == LightGroupCategory.ALL:
            return False
        if not self.is_control_enabled():
            self._trace_group(
                feature="light_groups",
                trigger="presence_activity",
                decision="no_action",
                outcome="skipped",
                reason_codes=["control_disabled"],
            )
            return False
        return self._apply_decision_event("presence_activity")

    def state_change_primary(self, states_tuple):
        """Handle the ALL group on the shared decision path (vacancy OFF only, never ON)."""
        new_states, _lost_states = states_tuple
        if AreaStates.CLEAR in new_states:
            # CLEAR ends a manual override before the decision; a vacancy OFF stays allowed.
            self.reset_control()
        return self._apply_decision_event("area_state_changed")

    def _transition_mode(self) -> str:
        """Map the configured brightness flags to a transition mode."""
        if self.require_dark and self.turn_off_when_bright:
            return MODE_DARK_ON_BRIGHT_OFF
        if self.require_dark:
            return MODE_REQUIRE_DARK
        if self.turn_off_when_bright:
            return MODE_TURN_OFF
        return MODE_IGNORE

    def _brightness_state(self) -> BrightnessState:
        if self.area.has_state(AreaStates.BRIGHT):
            return BrightnessState.BRIGHT
        if self.area.has_state(AreaStates.DARK):
            return BrightnessState.DARK
        return BrightnessState.UNKNOWN

    @callback
    def _async_control_switch_changed(self, area_id: str) -> None:
        """Re-evaluate the current state when the Area's automation is switched on."""
        if area_id == self.area.id and self._active and self.is_control_enabled():
            self._apply_decision_event("automation_enabled")

    @callback
    def _async_deactivate(self) -> None:
        """Stop this instance: a pending automatic OFF is cancelled and never sent.

        A call already handed to Home Assistant cannot be recalled here; it finishes.
        """
        self._active = False
        for task in list(self._clear_tasks):
            task.cancel()
        self._clear_tasks.clear()

    def state_change_secondary(self, states_tuple):
        """Re-evaluate a light group after every area state transition."""
        new_states, lost_states = states_tuple

        if not new_states and not lost_states:
            return False

        if not self.controlling:
            self.logger.debug(
                "%s: Re-enabling automatic control after an area transition.",
                self.name,
            )
            self.controlling = True
            self._attr_extra_state_attributes["controlling"] = True
            self.async_write_ha_state()

        if AreaStates.CLEAR in new_states:
            self.reset_control()
            # The ALL group owns the CLEAR OFF; this only records the new decision input.
            self._decision_previous = self._current_area_state()
            return False

        return self._apply_decision_event("area_state_changed")

    def relevant_states(self):
        """Return relevant states and remove irrelevant ones (opinionated)."""
        relevant_states = self.area.states.copy()

        if self.area.is_occupied():
            relevant_states.append(AreaStates.OCCUPIED)

        return relevant_states

    def _active_blocking_states(self) -> list[str]:
        """Return configured blocking states that are currently active."""
        if not self.blocking_states:
            return []

        return [
            blocking_state
            for blocking_state in self.blocking_states
            if self.area.has_state(blocking_state)
        ]

    # Light Handling

    def _is_own_context(self, context) -> bool:
        """Return whether a state change belongs to a call of this Area's own automation.

        A registered group call (light_origin) is the only own automation. The change's Context
        or its parent must be one of those calls. A user id, a time window or a guess decides nothing.
        """
        candidates = [context.id]
        if context.parent_id is not None:
            candidates.append(context.parent_id)
        return any(
            request_for_context(self.area, candidate) is not None
            for candidate in candidates
        )

    def _all_target_lights_on(self) -> bool:
        """Only skip activation when every member is actually on."""
        return bool(self._entity_ids) and all(
            self.hass.states.is_state(entity_id, STATE_ON)
            for entity_id in self._entity_ids
        )

    def _current_area_state(self) -> AreaState:
        """Decision input of this group now. Unknown presence stays unknown, never vacancy."""
        return AreaState(
            occupied=(
                self.area.is_occupied() if area_presence_available(self.area) else None
            ),
            brightness=self._brightness_state(),
            activation_matches=(
                self.category == LightGroupCategory.ALL
                or self.activation == LIGHT_GROUP_ACTIVATION_OCCUPIED
                or self.area.has_state(self.activation)
            ),
            blocked=bool(self._active_blocking_states()),
            controlling=bool(self.controlling) and self.is_control_enabled(),
            override=Override.FORCE_OFF if self.manual_override else Override.NONE,
        )

    def _group_config(self) -> GroupConfig:
        """Return the configured behaviour of this group for the shared decision path."""
        if self.category == LightGroupCategory.ALL:
            # The ALL group has no activation or blocker of its own: vacancy OFF only.
            return GroupConfig(
                mode=self._transition_mode(), activation_enabled=True, allow_on=False
            )
        return GroupConfig(
            mode=self._transition_mode(),
            activation_enabled=self.activation != LIGHT_GROUP_ACTIVATION_DISABLED,
        )

    def _apply_decision_event(self, trigger: str) -> bool:
        """Shared automatic path for a relevant event of a secondary group.

        An effective blocker ends a manual override first. The decision compares the current
        decision input with the previous one, so identical inputs never send a second command.
        """
        if self._active_blocking_states() and self.manual_override:
            self._set_manual_override(
                False, trigger=trigger, reason_codes=["blocking_state_active"]
            )
        current = self._current_area_state()
        if (
            trigger not in ("presence_activity", "automation_enabled")
            and current != self._decision_previous
        ):
            # A new decision input supersedes a command still pending for the old one and
            # re-allows a command that failed earlier (the same action is decided again).
            self._supersede_pending()
        if trigger in ("presence_activity", "automation_enabled"):
            # Activity restores the desired state of the current valid input (a partly
            # switched group is completed). Duplicates are held back by the pending marker.
            decision = initial_decision(self._group_config(), current)
        else:
            decision = transition_decision(
                self._group_config(), self._decision_previous, current
            )
        self._decision_previous = current
        return self._dispatch_decision(decision, trigger)

    def _supersede_pending(self) -> None:
        """Invalidate a pending command and the failure memory (a new decision input)."""
        self._decision_seq += 1
        self._pending_action = None
        self._failed_action = None

    def _apply_initial_decision(self) -> None:
        """Once per instance (setup or reload): decide from the current valid state only."""
        if self._initial_done:
            return
        self._initial_done = True
        current = self._current_area_state()
        decision = initial_decision(self._group_config(), current)
        self._decision_previous = current
        self._dispatch_decision(decision, "initial")

    def _dispatch_decision(self, decision, trigger: str) -> bool:
        """Hand one decision to the loop; NO_ACTION is traced and sends nothing."""
        if decision.action is TransitionAction.NO_ACTION:
            self._trace_group(
                feature="light_groups",
                trigger=trigger,
                decision="no_action",
                outcome="skipped",
                reason_codes=[decision.reason.value],
                target_count=len(self._entity_ids),
            )
            return False
        self.hass.loop.call_soon_threadsafe(
            self._async_schedule_command, decision.action, trigger
        )
        return True

    @callback
    def _async_schedule_command(self, action, trigger: str) -> None:
        """Register one command on the loop: a new sequence number and a pending marker.

        A command of the same action that is still pending is not duplicated. A different
        action is a new decision and supersedes the older one, which then sends nothing.
        """
        if not self._active:
            return
        if self._pending_action == action.value or self._failed_action == action.value:
            # A failed command is not repeated by a later event for the same action.
            self._trace_group(
                feature="light_groups",
                trigger=trigger,
                decision=(
                    "turn_on" if action is TransitionAction.TURN_ON else "turn_off"
                ),
                outcome="skipped",
                reason_codes=[
                    (
                        "command_pending"
                        if self._pending_action == action.value
                        else "failed_not_retried"
                    )
                ],
                target_count=len(self._entity_ids),
            )
            return
        if self._failed_action and self._failed_action != action.value:
            self._failed_action = None
        self._decision_seq += 1
        seq = self._decision_seq
        self._pending_action = action.value
        task = self.hass.async_create_task(
            self._async_group_command(action, seq, trigger), eager_start=False
        )
        self._clear_tasks.add(task)
        task.add_done_callback(self._clear_tasks.discard)

    async def _async_group_command(self, action, seq: int, trigger: str) -> None:
        """Run one scheduled command and release its pending marker afterwards."""
        try:
            await self._run_group_command(action, seq, trigger)
        finally:
            if self._pending_action == action.value:
                self._pending_action = None

    async def _run_group_command(self, action, seq: int, trigger: str) -> None:
        """Send at most one automatic call for one decision; a failure is never retried.

        Stale decisions (a later decision replaced this one, or the instance was removed),
        disabled automation, a new manual override, a conflicted group and an already fully
        on group are checked immediately before the call.
        """
        turn_on = action is TransitionAction.TURN_ON
        service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF
        decision_name = "turn_on" if turn_on else "turn_off"

        def trace(
            outcome: str, reason: str, exception_class: str | None = None
        ) -> None:
            self._trace_group(
                feature="light_groups",
                trigger=trigger,
                decision=decision_name,
                outcome=outcome,
                reason_codes=[reason],
                target_count=len(self._entity_ids),
                **({"exception_class": exception_class} if exception_class else {}),
            )

        group_state = self.hass.states.get(self.entity_id)
        if not self._active or seq != self._decision_seq or group_state is None:
            trace("skipped", "stale_decision")
            return
        if group_state.state == STATE_UNAVAILABLE:
            # Home Assistant skips an unavailable entity in a service call without an error
            # (a native group is unavailable until Home Assistant has started). Nothing would
            # be switched, so the call is not reported as executed.
            trace("skipped", "group_unavailable")
            return
        if not self.is_control_enabled() or not self.controlling:
            trace("skipped", "control_disabled")
            return
        if self.manual_override:
            trace("skipped", "manual_override_active")
            return
        if group_is_blocked(self.hass, self.entity_id, self._entity_ids):
            trace("skipped", "ownership_conflict")
            return
        if turn_on and self._all_target_lights_on():
            trace("skipped", "already_on")
            return
        if not turn_on and not self.is_on:
            # Already off (for example switched off by the user): an OFF is not needed.
            trace("skipped", "already_off")
            return

        group_context = new_light_group_context(
            self.area,
            service=service,
            target=self.entity_id,
            group=str(self.category),
        )
        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                service,
                {ATTR_ENTITY_ID: self.entity_id},
                blocking=True,
                context=group_context,
            )
        except Exception as err:  # noqa: BLE001 - reported, not retried
            self._failed_action = action.value
            trace("failed", "action_failed", type(err).__name__)
            self.logger.warning("%s: automatic %s failed: %s", self.name, service, err)
            return
        self._failed_action = None
        trace("executed", "action_executed")

    # Control Release

    def is_control_enabled(self):
        """Return whether the Area's light control switch is on.

        The switch registers itself on its Area while it is added to Home Assistant, so
        the state and its changes always come from the same, actually registered
        entity. A renamed or suffixed entity ID makes no difference.
        """
        switch = getattr(self.area, "light_control_switch", None)
        return switch is not None and switch.is_on is True

    def reset_control(self, trigger: str = "area_state_changed"):
        """Reset control status."""
        self.controlling = True
        self._set_manual_override(
            False, trigger=trigger, reason_codes=["presence_cleared"]
        )
        self._attr_extra_state_attributes["controlling"] = self.controlling
        self.async_write_ha_state()
        self.logger.debug("%s: Control Reset.", self.name)

    def _set_manual_override(
        self,
        enabled: bool,
        *,
        trigger: str | None = None,
        reason_codes: list[str] | None = None,
    ) -> None:
        """Set manual override state and expose it as an entity attribute.

        With a trigger, an actual start or end of the override is recorded in the Area's
        bounded decision trace (no entity or user data), so it is traceable what set it.
        """
        changed = bool(self.manual_override) != enabled
        self.manual_override = enabled
        self._attr_extra_state_attributes[ATTR_MANUAL_OVERRIDE] = enabled
        if changed and trigger is not None:
            decision = "manual_override_started" if enabled else "manual_override_ended"
            self._trace_override(trigger, decision, reason_codes or [])
            self.logger.info(
                "%s: %s (%s)", self.name, decision, ", ".join(reason_codes or [])
            )

    def _trace_group(self, **kwargs) -> None:
        """Record a decision of this group in the Area trace, tagged with its category."""
        category = getattr(self, "category", None)
        if category:
            kwargs["group"] = str(category)
        self.area.trace_decision(**kwargs)

    def _trace_override(
        self, trigger: str, decision: str, reason_codes: list[str]
    ) -> None:
        self._trace_group(
            feature="light_groups",
            trigger=trigger,
            decision=decision,
            outcome="tracked",
            reason_codes=reason_codes,
            target_count=len(getattr(self, "_entity_ids", ()) or ()),
        )

    @staticmethod
    def _origin_reason(context) -> str:
        """Classify a foreign change by what its Context proves, without identifying data.

        A user id proves a call under a Home Assistant user account (frontend, app, API
        token or voice assistant), not that a person acted. A parent id proves only that
        the Context was derived from another one (for example an automation, script or
        scene started by an event). Without either, it is not attributable: a device report, a
        physical switch, another integration, an automation without a triggering Context
        (time or sun trigger) or an own call answered after Home Assistant's context window.
        """
        if context is None:
            return "origin_unattributed"
        if context.user_id is not None:
            return "origin_user_account"
        if context.parent_id is not None:
            return "origin_parent_context"
        return "origin_unattributed"

    def handle_group_state_change_primary(self):
        """Handle group state change for primary area state events."""
        if not self._child_groups:
            return

        self.controlling = any(
            child_group.controlling for child_group in self._child_groups
        )
        self.async_write_ha_state()

    def handle_manual_group_state_change(
        self, new_state=None, own=False, context=None
    ) -> bool:
        """Handle manual on/off changes common to parent and child groups.

        `own` is True when the change was caused by this group's own service call, decided
        by the call's context (not by a time window).
        """
        if own:
            self.logger.debug("%s: Group controlled by us.", self.name)
            return True
        # A user's change overtakes any automatic command that is still planned.
        self._supersede_pending()

        self.logger.debug("%s: Group controlled by something else.", self.name)

        origin = ["manual_on", self._origin_reason(context)]
        if new_state == STATE_ON:
            self._set_manual_override(
                True, trigger="group_state_changed", reason_codes=origin
            )
            self.controlling = True
            return True

        if new_state == STATE_OFF and self.area.is_occupied():
            # A complete manual switch-off during occupation is a deliberate decision: the
            # override stays until CLEAR or an effective blocker ends it. Presence activity,
            # brightness and activation changes do not switch the group on again meanwhile.
            self._set_manual_override(
                True,
                trigger="group_state_changed",
                reason_codes=["manual_off", self._origin_reason(context)],
            )
            self.controlling = True
            return True

        return False

    def handle_group_state_change_secondary(
        self, new_state=None, own=False, context=None
    ):
        """Handle group state change for secondary area state events."""
        if self.handle_manual_group_state_change(new_state, own=own, context=context):
            return

        # If it was manually controlled in a way we do not override, stop controlling.
        self.controlling = False

    @callback
    def group_state_changed(self, event):
        """Handle group state change events."""
        # If area is not occupied, ignore
        if not self.area.is_occupied():
            self.reset_control("group_state_changed")
        else:
            origin_event = event.context.origin_event
            new_state = None

            if origin_event.event_type == "state_changed":
                # Skip non ON/OFF state changes
                if (
                    "old_state" not in origin_event.data
                    or not origin_event.data["old_state"]
                    or not origin_event.data["old_state"].state
                    or origin_event.data["old_state"].state
                    not in [
                        STATE_ON,
                        STATE_OFF,
                    ]
                ):
                    return False
                if (
                    "new_state" not in origin_event.data
                    or not origin_event.data["new_state"]
                    or not origin_event.data["new_state"].state
                    or origin_event.data["new_state"].state
                    not in [
                        STATE_ON,
                        STATE_OFF,
                    ]
                ):
                    return False

                # Ignore duplicate state reports (e.g. ON->ON/OFF->OFF),
                # otherwise we may incorrectly mark automation as externally controlled.
                if (
                    origin_event.data["old_state"].state
                    == origin_event.data["new_state"].state
                ):
                    return False

                # Skip restored events
                if (
                    "restored" in origin_event.data["old_state"].attributes
                    and origin_event.data["old_state"].attributes["restored"]
                ):
                    return False

                new_state = origin_event.data["new_state"].state
            else:
                # A service call (user or automation) changed the group itself: its own new
                # state is the decision input.
                group_new = event.data.get("new_state")
                new_state = group_new.state if group_new else None

            own = self._is_own_context(origin_event.context)
            if self.category == LightGroupCategory.ALL:
                self.handle_manual_group_state_change(
                    new_state, own=own, context=event.context
                )
                self.handle_group_state_change_primary()
            else:
                self.handle_group_state_change_secondary(
                    new_state, own=own, context=event.context
                )

        # Update attribute
        self._attr_extra_state_attributes["controlling"] = self.controlling
        self._attr_extra_state_attributes[ATTR_MANUAL_OVERRIDE] = self.manual_override
        self.async_write_ha_state()

        return True
