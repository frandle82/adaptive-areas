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
    EMPTY_STRING,
    EVENT_MAGICAREAS_AREA_STATE_CHANGED,
    LIGHT_GROUP_BLOCKING_STATES,
    LIGHT_GROUP_ACTIVATION,
    LIGHT_GROUP_ACTIVATION_DISABLED,
    LIGHT_GROUP_ACTIVATION_OCCUPIED,
    LIGHT_GROUP_BRIGHTNESS,
    LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
    LIGHT_GROUP_CATEGORIES,
    LIGHT_GROUP_DEFAULT_ICON,
    LIGHT_GROUP_ICONS,
    AreaStates,
    LightGroupCategory,
    MagicAreasFeatureInfoLightGroups,
    MagicAreasFeatures,
)
from custom_components.magic_areas.helpers.area import get_area_from_config_entry
from custom_components.magic_areas.helpers.light_groups import (
    migrate_light_group_feature_config,
)
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
        self.activation = LIGHT_GROUP_ACTIVATION_DISABLED
        self.blocking_states = []
        self.require_dark = True
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
            feature_config, _ = migrate_light_group_feature_config(
                area.feature_config(MagicAreasFeatures.LIGHT_GROUPS)
            )
            self.activation = feature_config[LIGHT_GROUP_ACTIVATION[self.category]]
            self.blocking_states = feature_config.get(
                LIGHT_GROUP_BLOCKING_STATES[self.category], []
            )
            brightness = feature_config[LIGHT_GROUP_BRIGHTNESS[self.category]]
            self.require_dark = brightness == LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK
            self.turn_off_when_bright = brightness == LIGHT_GROUP_BRIGHTNESS_TURN_OFF
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
            self.schedule_update_ha_state()

        if AreaStates.CLEAR in new_states:
            self.reset_control()
            return False

        if self.activation == LIGHT_GROUP_ACTIVATION_DISABLED:
            self.logger.debug("%s: Automatic activation is disabled.", self.name)
            return False

        if not self.area.is_occupied():
            self.logger.debug("%s: Area is not occupied.", self.name)
            self.controlled = True
            return self._turn_off()

        active_blockers = self._active_blocking_states()
        if active_blockers:
            self.logger.debug(
                "%s: Blocking room states active: %s.", self.name, active_blockers
            )
            self.controlled = True
            return self._turn_off()

        activation_matches = (
            self.activation == LIGHT_GROUP_ACTIVATION_OCCUPIED
            or self.area.has_state(self.activation)
        )
        if not activation_matches:
            self.logger.debug("%s: Activation condition is not active.", self.name)
            self.controlled = True
            return self._turn_off()

        if self.area.has_state(AreaStates.BRIGHT):
            if self.turn_off_when_bright:
                self.logger.debug("%s: Area is bright; turning group off.", self.name)
                self.controlled = True
                return self._turn_off(force=True)

            if self.require_dark:
                self.logger.debug(
                    "%s: Area is bright; preserving group state because dark-on is enabled.",
                    self.name,
                )
                return False

        if self.manual_override:
            self._set_manual_override(False)

        self.logger.debug("%s: Controlling room state is active.", self.name)
        self.controlled = True
        return self._turn_on()

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

    def _turn_on(self):
        """Turn on light if it's not already on and if we're controlling it."""
        if not self.controlling:
            return False

        if self.is_on:
            return False

        if self.require_dark and self.area.has_state(AreaStates.BRIGHT):
            self.logger.debug(
                "%s: Area is bright and this group requires darkness, skipping turn-on.",
                self.name,
            )
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
