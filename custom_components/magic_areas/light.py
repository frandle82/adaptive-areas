"""Platform file for Magic Area's light entities."""

import logging
from time import monotonic

from homeassistant.components.group.light import FORWARDED_ATTRIBUTES, LightGroup
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.switch.const import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.magic_areas.base.entities import MagicEntity
from custom_components.magic_areas.base.magic import MagicArea
from custom_components.magic_areas.const import (
    AREA_PRIORITY_STATES,
    DEFAULT_LIGHT_GROUP_ACT_ON,
    EMPTY_STRING,
    EVENT_MAGICAREAS_AREA_STATE_CHANGED,
    LIGHT_GROUP_ACT_ON,
    LIGHT_GROUP_ACT_ON_DARK_CHANGE,
    LIGHT_GROUP_ACT_ON_EXTENDED_CHANGE,
    LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
    LIGHT_GROUP_ACT_ON_SLEEP_CHANGE,
    LIGHT_GROUP_ACT_ON_STATE_CHANGE,
    LIGHT_GROUP_BLOCKING_STATES,
    LIGHT_GROUP_CATEGORIES,
    LIGHT_GROUP_DEFAULT_ICON,
    LIGHT_GROUP_ICONS,
    LIGHT_GROUP_STATE_RULES,
    LIGHT_GROUP_STATES,
    LIGHT_GROUP_TURN_OFF_WHEN_BRIGHT,
    AreaStates,
    LightGroupCategory,
    MagicAreasFeatureInfoLightGroups,
    MagicAreasFeatures,
)
from custom_components.magic_areas.helpers.area import get_area_from_config_entry
from custom_components.magic_areas.util import cleanup_removed_entries

_LOGGER = logging.getLogger(__name__)
CONTROL_EVENT_GRACE_SECONDS = 2.0
ATTR_MANUAL_OVERRIDE = "manual_override"


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the area light config entry."""

    area: MagicArea | None = get_area_from_config_entry(hass, config_entry)
    assert area is not None

    # Check feature availability
    if not area.has_feature(MagicAreasFeatures.LIGHT_GROUPS):
        return

    # Check if there are any lights
    if not area.has_entities(LIGHT_DOMAIN):
        _LOGGER.debug("%s: No %s entities for area.", area.name, LIGHT_DOMAIN)
        return

    light_entities = [e["entity_id"] for e in area.entities[LIGHT_DOMAIN]]

    light_groups = []

    # Create light groups
    if area.is_meta():
        light_groups.append(
            MagicLightGroup(
                area, light_entities, translation_key=LightGroupCategory.ALL
            )
        )
    else:
        child_light_groups: list[AreaLightGroup] = []

        # Create extended light groups
        for category in LIGHT_GROUP_CATEGORIES:
            category_lights = [
                light_entity
                for light_entity in area.feature_config(
                    MagicAreasFeatures.LIGHT_GROUPS
                ).get(category, {})
                if light_entity in light_entities
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

        _LOGGER.debug(
            "%s: Creating Area light group for area with lights: %s",
            area.name,
            str([group.unique_id for group in child_light_groups]),
        )
        light_groups.append(
            AreaLightGroup(
                area,
                light_entities,
                category=LightGroupCategory.ALL,
                child_groups=child_light_groups,
            )
        )

    # Create all groups
    if light_groups:
        async_add_entities(light_groups)

    if LIGHT_DOMAIN in area.magic_entities:
        cleanup_removed_entries(
            area.hass, light_groups, area.magic_entities[LIGHT_DOMAIN]
        )


class MagicLightGroup(MagicEntity, LightGroup):
    """Magic Light Group for Meta-areas."""

    feature_info = MagicAreasFeatureInfoLightGroups()

    def __init__(self, area, entities, translation_key: str | None = None):
        """Initialize parent class and state."""
        MagicEntity.__init__(
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


class AreaLightGroup(MagicLightGroup):
    """Magic Light Group."""

    def __init__(self, area, entities, category=None, child_groups=None):
        """Initialize light group."""

        MagicLightGroup.__init__(self, area, entities, translation_key=category)

        self._child_groups = child_groups or []

        self.category = category
        self.assigned_states = []
        self.state_rules = []
        self.act_on = []
        self.blocking_states = []
        self.turn_off_when_bright = False

        self.controlling = True
        self.controlled = False
        self.manual_override = False
        self._last_control_action_ts = 0.0

        self._icon = LIGHT_GROUP_DEFAULT_ICON

        if self.category and self.category != LightGroupCategory.ALL:
            self._icon = LIGHT_GROUP_ICONS.get(self.category, LIGHT_GROUP_DEFAULT_ICON)

        # Get assigned states
        if self.category and self.category != LightGroupCategory.ALL:
            feature_config = area.feature_config(MagicAreasFeatures.LIGHT_GROUPS)
            self.assigned_states = feature_config.get(LIGHT_GROUP_STATES[self.category], [])
            self.state_rules = feature_config.get(
                LIGHT_GROUP_STATE_RULES[self.category], []
            )
            self.act_on = feature_config.get(
                LIGHT_GROUP_ACT_ON[self.category], DEFAULT_LIGHT_GROUP_ACT_ON
            )
            self.act_on = self._normalize_act_on(self.act_on)
            self.blocking_states = feature_config.get(
                LIGHT_GROUP_BLOCKING_STATES[self.category], []
            )
            self.turn_off_when_bright = feature_config.get(
                LIGHT_GROUP_TURN_OFF_WHEN_BRIGHT[self.category],
                False,
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
        else:
            self._attr_is_on = False

        self.schedule_update_ha_state()

        # Setup state change listeners
        await self._setup_listeners()

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
        async_dispatcher_connect(
            self.hass, EVENT_MAGICAREAS_AREA_STATE_CHANGED, self.area_state_changed
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

        automatic_control = self.is_control_enabled()

        if not automatic_control:
            self.logger.debug(
                "%s: Automatic control for light group is disabled, skipping...",
                self.name,
            )
            return False

        self.logger.debug("%s: Light group detected area state change", self.name)

        # Handle all lights group
        if self.category == LightGroupCategory.ALL:
            return self.state_change_primary(states_tuple)

        # Handle light category
        return self.state_change_secondary(states_tuple)

    def state_change_primary(self, states_tuple):
        """Handle primary state change."""
        new_states, _ = states_tuple

        if self.turn_off_when_bright and AreaStates.BRIGHT in new_states:
            self.logger.debug(
                "%s: Parent group turning off due to dark->bright transition and turn_off_when_bright.",
                self.name,
            )
            return self._turn_off(force=True)

        # If area clear
        if AreaStates.CLEAR in new_states:
            self.logger.debug("%s: Area is clear, should turn off lights!", self.name)
            self.reset_control()
            return self._turn_off()

        return False

    def state_change_secondary(self, states_tuple):
        """Handle secondary state change."""
        new_states, lost_states = states_tuple
        configured_rule_states = self._configured_rule_states()
        brightness_state_changed = self._brightness_state_changed(
            new_states, lost_states
        )

        # Re-arm automatic control on meaningful area transitions.
        # This prevents groups from staying permanently disabled after a manual override
        # while the area remains occupied.
        if not self.controlling and (
            AreaStates.OCCUPIED in new_states
            or AreaStates.DARK in new_states
            or AreaStates.BRIGHT in new_states
            or AreaStates.DARK in lost_states
            or AreaStates.BRIGHT in lost_states
            or AreaStates.EXTENDED in new_states
            or AreaStates.SLEEP in new_states
        ):
            self.logger.debug(
                "%s: Re-enabling automatic control due area state transition.",
                self.name,
            )
            self.controlling = True
            self._attr_extra_state_attributes["controlling"] = self.controlling
            self.schedule_update_ha_state()

        if AreaStates.CLEAR in new_states:
            self.logger.debug(
                "%s: Area is clear, reset control state and Noop!", self.name
            )
            self.reset_control()
            return False

        if self.turn_off_when_bright and AreaStates.BRIGHT in new_states:
            if self.manual_override:
                self.logger.debug(
                    "%s: Manual override active, skipping turn_off_when_bright.",
                    self.name,
                )
                return False

            self.logger.debug(
                "%s: Area transitioned to bright and turn_off_when_bright is enabled, turning off.",
                self.name,
            )
            self.controlled = True
            return self._turn_off(force=True)

        if self.manual_override and self._turn_on_conditions_match():
            self.logger.debug(
                "%s: Manual override reset because turn-on conditions match.",
                self.name,
            )
            self._set_manual_override(False)

        # Only react to actual secondary state changes
        if not new_states and not lost_states:
            self.logger.debug("%s: No new or lost states, noop.", self.name)
            return False

        # Do not handle lights that are not tied to a state.
        if not self.assigned_states and not self.state_rules:
            self.logger.debug("%s: No assigned states/state rules. noop.", self.name)
            return False

        # If area clear, do nothing (main group will)
        if not self.area.is_occupied():
            self.logger.debug("%s: Area not occupied, ignoring.", self.name)
            return False

        self.logger.debug(
            "%s: Assigned states: %s. State rules: %s. New states: %s / Lost states %s",
            self.name,
            str(self.assigned_states),
            str(self.state_rules),
            str(new_states),
            str(lost_states),
        )

        # Calculate valid states (if area has states we listen to)
        # and check if area is under one or more priority state
        valid_states = [
            state for state in self.assigned_states if self.area.has_state(state)
        ]
        has_priority_states = any(
            self.area.has_state(state) for state in AREA_PRIORITY_STATES
        )
        non_priority_states = [
            state for state in valid_states if state not in AREA_PRIORITY_STATES
        ]

        self.logger.debug(
            "%s: Has priority states? %s. Non-priority states: %s",
            self.name,
            has_priority_states,
            str(non_priority_states),
        )

        # ACT ON Control
        # Evaluate all relevant trigger changes first, then skip only if none are allowed.
        # This avoids combined state changes being blocked by a single non-configured trigger.
        occupancy_changed = AreaStates.OCCUPIED in new_states
        extended_changed = AreaStates.EXTENDED in new_states
        sleep_changed = AreaStates.SLEEP in new_states

        trigger_changes = [
            (
                "occupancy",
                occupancy_changed,
                LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE in self.act_on
                or AreaStates.OCCUPIED in configured_rule_states,
            ),
            (
                "brightness",
                brightness_state_changed,
                LIGHT_GROUP_ACT_ON_DARK_CHANGE in self.act_on
                or AreaStates.DARK in configured_rule_states
                or AreaStates.BRIGHT in configured_rule_states,
            ),
            (
                "extended",
                extended_changed,
                LIGHT_GROUP_ACT_ON_EXTENDED_CHANGE in self.act_on
                or AreaStates.EXTENDED in configured_rule_states,
            ),
            (
                "sleep",
                sleep_changed,
                LIGHT_GROUP_ACT_ON_SLEEP_CHANGE in self.act_on
                or AreaStates.SLEEP in configured_rule_states,
            ),
        ]
        relevant_changes = [name for name, changed, _ in trigger_changes if changed]
        allowed_changes = [
            name for name, changed, is_allowed in trigger_changes if changed and is_allowed
        ]

        if relevant_changes and not allowed_changes:
            self.logger.debug(
                "%s: Relevant state changes %s detected but none are configured in act_on/rules. Skipping.",
                self.name,
                str(relevant_changes),
            )
            return False

        # Keep backward compatibility for old "state" trigger values.
        if (
            not relevant_changes
            and LIGHT_GROUP_ACT_ON_STATE_CHANGE not in self.act_on
            and not self.state_rules
        ):
            self.logger.debug(
                "Area state change detected but not configured to act on. Skipping."
            )
            return False

        # Prefer priority states when present
        if has_priority_states:
            for non_priority_state in non_priority_states:
                valid_states.remove(non_priority_state)

        if self.state_rules:
            rules_to_evaluate = [list(rule) for rule in self.state_rules if rule]

            if has_priority_states:
                priority_rules = []
                for rule in rules_to_evaluate:
                    priority_rule = [
                        state for state in rule if state in AREA_PRIORITY_STATES
                    ]
                    if priority_rule:
                        priority_rules.append(priority_rule)
                if priority_rules:
                    rules_to_evaluate = priority_rules

            if self.matches_state_rules(rules_to_evaluate):
                active_blocking_states = self._active_blocking_states()
                if active_blocking_states:
                    self.logger.debug(
                        "%s: Blocking states active (%s), rule result discarded.",
                        self.name,
                        str(active_blocking_states),
                    )
                    return False

                self.logger.debug(
                    "%s: State rules matched (%s), Group should turn on!",
                    self.name,
                    str(rules_to_evaluate),
                )
                self.controlled = True
                return self._turn_on()

            self.logger.debug(
                "%s: State rules not matched (%s), Group should turn off!",
                self.name,
                str(rules_to_evaluate),
            )
            self.controlled = True
            return self._turn_off()

        if valid_states:
            active_blocking_states = self._active_blocking_states()
            if active_blocking_states:
                self.logger.debug(
                    "%s: Blocking states active (%s), state match discarded.",
                    self.name,
                    str(active_blocking_states),
                )
                return False

            self.logger.debug(
                "%s: Area has valid states (%s), Group should turn on!",
                self.name,
                str(valid_states),
            )
            self.controlled = True
            return self._turn_on()

        # Only turn lights off if not going into dark state
        if AreaStates.DARK in new_states:
            self.logger.debug(
                "%s: Entering %s state, noop.", self.name, AreaStates.DARK
            )
            return False

        # Keep lights on while the area is dark unless blocked/clear/bright logic above applies.
        if self.area.has_state(AreaStates.DARK):
            self.logger.debug(
                "%s: Area is dark, skipping turn-off logic for secondary group.",
                self.name,
            )
            return False

        # Turn off if we're a PRIORITY_STATE and we're coming out of it
        out_of_priority_states = [
            state
            for state in AREA_PRIORITY_STATES
            if state in self.assigned_states and state in lost_states
        ]
        if out_of_priority_states:
            self.controlled = True
            return self._turn_off()

        # Do not turn off if no new PRIORITY_STATES
        new_priority_states = [
            state for state in AREA_PRIORITY_STATES if state in new_states
        ]
        if not new_priority_states:
            self.logger.debug("%s: No new priority states. Noop.", self.name)
            return False

        self.controlled = True
        return self._turn_off()

    def relevant_states(self):
        """Return relevant states and remove irrelevant ones (opinionated)."""
        relevant_states = self.area.states.copy()

        if self.area.is_occupied():
            relevant_states.append(AreaStates.OCCUPIED)

        return relevant_states

    @staticmethod
    def _normalize_act_on(act_on: list[str] | str | None) -> list[str]:
        """Normalize configured triggers and map legacy state trigger."""
        if not act_on:
            return []

        if isinstance(act_on, str):
            act_on = [act_on]

        normalized = []
        for trigger in act_on:
            if trigger == LIGHT_GROUP_ACT_ON_STATE_CHANGE:
                normalized.extend(
                    [
                        LIGHT_GROUP_ACT_ON_DARK_CHANGE,
                        LIGHT_GROUP_ACT_ON_EXTENDED_CHANGE,
                        LIGHT_GROUP_ACT_ON_SLEEP_CHANGE,
                    ]
                )
                continue
            normalized.append(trigger)

        # Keep insertion order while removing duplicates.
        return list(dict.fromkeys(normalized))

    def matches_state_rules(self, state_rules: list[list[str]]) -> bool:
        """Return True when any non-empty rule block is fully matched."""
        return any(
            all(self.area.has_state(state) for state in rule)
            for rule in state_rules
            if rule
        )

    def _configured_rule_states(self) -> set[str]:
        """Return flattened set of states used by configured rule blocks."""
        return {
            state
            for rule in self.state_rules
            if isinstance(rule, list)
            for state in rule
        }

    @staticmethod
    def _brightness_state_changed(
        new_states: list[str], lost_states: list[str]
    ) -> bool:
        """Return True when area brightness changed in either direction."""
        return any(
            state in (AreaStates.DARK, AreaStates.BRIGHT)
            for state in [*new_states, *lost_states]
        )

    def _active_blocking_states(self) -> list[str]:
        """Return configured blocking states that are currently active."""
        if not self.blocking_states:
            return []

        return [
            blocking_state
            for blocking_state in self.blocking_states
            if self.area.has_state(blocking_state)
        ]

    def _turn_on_conditions_match(self) -> bool:
        """Return True if configured rules or legacy assigned states currently match."""
        if self._active_blocking_states():
            return False

        if self.state_rules:
            rules_to_evaluate = [list(rule) for rule in self.state_rules if rule]
            return self.matches_state_rules(rules_to_evaluate)

        return any(self.area.has_state(state) for state in self.assigned_states)

    # Light Handling

    def _turn_on(self):
        """Turn on light if it's not already on and if we're controlling it."""
        if not self.controlling:
            return False

        if self.is_on:
            return False

        self.controlled = True
        self._last_control_action_ts = monotonic()

        service_data = {ATTR_ENTITY_ID: self.entity_id}
        self.hass.services.call(LIGHT_DOMAIN, SERVICE_TURN_ON, service_data)

        return True

    def _turn_off(self, force: bool = False):
        """Turn off light if it's not already off and we're controlling it."""
        if self.manual_override:
            self.logger.debug(
                "%s: Manual override active, ignoring turn off.", self.name
            )
            return False

        if not force and not self.controlling:
            return False

        if not force and not self.is_on:
            return False

        self._last_control_action_ts = monotonic()
        service_data = {ATTR_ENTITY_ID: self.entity_id}
        self.hass.services.call(LIGHT_DOMAIN, SERVICE_TURN_OFF, service_data)

        return True

    # Control Release

    def is_control_enabled(self):
        """Check if light control is enabled by checking light control switch state."""
        entity_id = (
            f"{SWITCH_DOMAIN}.magic_areas_light_groups_{self.area.slug}_light_control"
        )

        switch_entity = self.hass.states.get(entity_id)

        if not switch_entity:
            return False

        return switch_entity.state.lower() == STATE_ON

    def reset_control(self):
        """Reset control status."""
        self.controlling = True
        self._set_manual_override(False)
        self._attr_extra_state_attributes["controlling"] = self.controlling
        self.schedule_update_ha_state()
        self.logger.debug("{self.name}: Control Reset.")

    def _set_manual_override(self, enabled: bool) -> None:
        """Set manual override state and expose it as an entity attribute."""
        self.manual_override = enabled
        self._attr_extra_state_attributes[ATTR_MANUAL_OVERRIDE] = enabled

    def handle_group_state_change_primary(self):
        """Handle group state change for primary area state events."""
        if not self._child_groups:
            return

        self.controlling = any(
            child_group.controlling for child_group in self._child_groups
        )
        self.schedule_update_ha_state()

    def handle_manual_group_state_change(self, new_state=None) -> bool:
        """Handle manual on/off changes common to parent and child groups."""
        within_control_grace = (
            monotonic() - self._last_control_action_ts
        ) <= CONTROL_EVENT_GRACE_SECONDS

        if self.controlled or within_control_grace:
            self.controlled = False
            self.logger.debug("%s: Group controlled by us.", self.name)
            return True

        self.logger.debug("%s: Group controlled by something else.", self.name)

        if new_state == STATE_ON:
            self._set_manual_override(True)
            self.controlling = True
            return True

        if new_state == STATE_OFF and self.manual_override:
            self._set_manual_override(False)
            self.controlling = True
            return True

        return False

    def handle_group_state_change_secondary(self, new_state=None):
        """Handle group state change for secondary area state events."""
        if self.handle_manual_group_state_change(new_state):
            return

        # If it was manually controlled in a way we do not override, stop controlling.
        self.controlling = False

    def group_state_changed(self, event):
        """Handle group state change events."""
        # If area is not occupied, ignore
        if not self.area.is_occupied():
            self.reset_control()
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

            if self.category == LightGroupCategory.ALL:
                self.handle_manual_group_state_change(new_state)
                self.handle_group_state_change_primary()
            else:
                self.handle_group_state_change_secondary(new_state)

        # Update attribute
        self._attr_extra_state_attributes["controlling"] = self.controlling
        self._attr_extra_state_attributes[ATTR_MANUAL_OVERRIDE] = self.manual_override
        self.schedule_update_ha_state()

        return True
