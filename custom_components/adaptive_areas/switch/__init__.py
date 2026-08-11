"""Platform file for Adaptive Area's switch entities."""

import logging

from homeassistant.components.group.switch import SwitchGroup
from homeassistant.components.switch.const import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EntityCategory,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    DEFAULT_LIGHT_GROUP_ACT_ON,
    EMPTY_STRING,
    EVENT_ADAPTIVEAREAS_AREA_STATE_CHANGED,
    LIGHT_GROUP_ACT_ON_DARK_CHANGE,
    LIGHT_GROUP_ACT_ON_EXTENDED_CHANGE,
    LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
    LIGHT_GROUP_ACT_ON_SLEEP_CHANGE,
    LIGHT_GROUP_ACT_ON_STATE_CHANGE,
    SWITCH_GROUP_ACTION,
    SWITCH_GROUP_ACTION_TURN_ON,
    SWITCH_GROUP_ACT_ON,
    SWITCH_GROUP_CATEGORIES,
    SWITCH_GROUP_DEFAULT_ICON,
    SWITCH_GROUP_ICONS,
    SWITCH_GROUP_STATES,
    AreaStates,
    AdaptiveAreasFeatureInfoLightGroups,
    AdaptiveAreasFeatureInfoSwitchGroups,
    AdaptiveAreasFeatures,
    SwitchGroupCategory,
)
from custom_components.adaptive_areas.helpers.area import get_area_from_config_entry
from custom_components.adaptive_areas.switch.base import SwitchBase
from custom_components.adaptive_areas.switch.climate_control import ClimateControlSwitch
from custom_components.adaptive_areas.switch.fan_control import FanControlSwitch
from custom_components.adaptive_areas.switch.media_player_control import (
    MediaPlayerControlSwitch,
)
from custom_components.adaptive_areas.switch.presence_hold import PresenceHoldSwitch
from custom_components.adaptive_areas.util import cleanup_removed_entries

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the area switch config entry."""

    area: AdaptiveArea | None = get_area_from_config_entry(hass, config_entry)
    assert area is not None

    switch_entities = []

    if area.has_feature(AdaptiveAreasFeatures.PRESENCE_HOLD) and not area.is_meta():
        try:
            switch_entities.append(PresenceHoldSwitch(area))
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s: Error loading presence hold switch: %s", area.name, str(e)
            )

    if area.has_feature(AdaptiveAreasFeatures.LIGHT_GROUPS) and not area.is_meta():
        try:
            switch_entities.append(LightControlSwitch(area))
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s: Error loading light control switch: %s", area.name, str(e)
            )

    if (
        area.has_feature(AdaptiveAreasFeatures.MEDIA_PLAYER_GROUPS)
        and not area.is_meta()
    ):
        try:
            switch_entities.append(MediaPlayerControlSwitch(area))
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s: Error loading media player control switch: %s", area.name, str(e)
            )

    if area.has_feature(AdaptiveAreasFeatures.FAN_GROUPS) and not area.is_meta():
        try:
            switch_entities.append(FanControlSwitch(area))
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("%s: Error loading fan control switch: %s", area.name, str(e))

    if area.has_feature(AdaptiveAreasFeatures.SWITCH_GROUPS) and not area.is_meta():
        try:
            switch_entities.extend(_build_switch_groups(area))
            switch_entities.append(SwitchGroupControlSwitch(area))
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("%s: Error loading switch groups: %s", area.name, str(e))

    if area.has_feature(AdaptiveAreasFeatures.CLIMATE_CONTROL):
        try:
            switch_entities.append(ClimateControlSwitch(area))
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s: Error loading climate control switch: %s", area.name, str(e)
            )

    if switch_entities:
        async_add_entities(switch_entities)

    if SWITCH_DOMAIN in area.adaptive_entities:
        cleanup_removed_entries(
            area.hass, switch_entities, area.adaptive_entities[SWITCH_DOMAIN]
        )


class LightControlSwitch(SwitchBase):
    """Switch to enable/disable light control."""

    feature_info = AdaptiveAreasFeatureInfoLightGroups()
    _attr_entity_category = EntityCategory.CONFIG


class SwitchGroupControlSwitch(SwitchBase):
    """Switch to enable/disable switch group automation."""

    feature_info = AdaptiveAreasFeatureInfoSwitchGroups()
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize switch group control."""
        super().__init__(area, translation_key="switch_group_control")


def _build_switch_groups(area: AdaptiveArea) -> list[AreaSwitchGroup]:
    """Build switch group entities for a regular area."""
    if not area.has_entities(SWITCH_DOMAIN):
        _LOGGER.debug("%s: No switch entities for switch groups.", area.name)
        return []

    available_switches = [e["entity_id"] for e in area.entities[SWITCH_DOMAIN]]
    switch_groups: list[AreaSwitchGroup] = []
    child_groups: list[AreaSwitchGroup] = []
    assigned_switches: list[str] = []

    for category in SWITCH_GROUP_CATEGORIES:
        category_switches = [
            switch_entity
            for switch_entity in area.feature_config(
                AdaptiveAreasFeatures.SWITCH_GROUPS
            ).get(category, {})
            if switch_entity in available_switches
        ]
        if not category_switches:
            continue

        switch_group = AreaSwitchGroup(area, category_switches, category)
        switch_groups.append(switch_group)
        child_groups.append(switch_group)
        assigned_switches.extend(category_switches)

    unique_assigned_switches = list(dict.fromkeys(assigned_switches))
    if unique_assigned_switches:
        switch_groups.append(
            AreaSwitchGroup(
                area,
                unique_assigned_switches,
                category=SwitchGroupCategory.ALL,
                child_groups=child_groups,
            )
        )

    return switch_groups


class AdaptiveSwitchGroup(AdaptiveEntity, SwitchGroup):
    """Switch Group base entity."""

    feature_info = AdaptiveAreasFeatureInfoSwitchGroups()

    def __init__(self, area, entities, translation_key: str | None = None):
        """Init base switch group."""
        self._group_entities = entities
        AdaptiveEntity.__init__(
            self,
            area,
            domain=SWITCH_DOMAIN,
            translation_key=translation_key,
        )
        SwitchGroup.__init__(
            self,
            entity_ids=entities,
            name=EMPTY_STRING,
            unique_id=self.unique_id,
            mode=False,
        )
        delattr(self, "_attr_name")


class AreaSwitchGroup(AdaptiveSwitchGroup):
    """Adaptive Area switch group with optional area-state automation."""

    def __init__(self, area, entities, category=None, child_groups=None):
        """Initialize switch group."""
        translation_key = (
            "switch_group" if category == SwitchGroupCategory.ALL else category
        )
        AdaptiveSwitchGroup.__init__(
            self, area, entities, translation_key=translation_key
        )

        self._child_groups = child_groups or []
        self.category = category
        self.assigned_states = []
        self.act_on = []
        self.action = SWITCH_GROUP_ACTION_TURN_ON
        self.controlling = True
        self.controlled = False

        self._icon = SWITCH_GROUP_DEFAULT_ICON
        if self.category and self.category != SwitchGroupCategory.ALL:
            self._icon = SWITCH_GROUP_ICONS.get(
                self.category, SWITCH_GROUP_DEFAULT_ICON
            )

        if self.category and self.category != SwitchGroupCategory.ALL:
            feature_config = area.feature_config(AdaptiveAreasFeatures.SWITCH_GROUPS)
            self.assigned_states = feature_config.get(
                SWITCH_GROUP_STATES[self.category], []
            )
            self.act_on = feature_config.get(
                SWITCH_GROUP_ACT_ON[self.category], DEFAULT_LIGHT_GROUP_ACT_ON
            )
            self.act_on = self._normalize_act_on(self.act_on)
            self.action = feature_config.get(
                SWITCH_GROUP_ACTION[self.category], SWITCH_GROUP_ACTION_TURN_ON
            )

        self._attr_extra_state_attributes["switches"] = self._group_entities
        self._attr_extra_state_attributes["controlling"] = self.controlling
        self._attr_extra_state_attributes["action"] = self.action

        if self.category == SwitchGroupCategory.ALL:
            self._attr_extra_state_attributes["child_ids"] = []

    @property
    def icon(self):
        """Return icon."""
        return self._icon

    async def async_added_to_hass(self) -> None:
        """Restore state and setup listeners."""
        last_state = await self.async_get_last_state()
        if last_state and "controlling" in last_state.attributes:
            self.controlling = last_state.attributes["controlling"]
            self._attr_extra_state_attributes["controlling"] = self.controlling

        await self._setup_listeners()
        await super().async_added_to_hass()

        if self.category == SwitchGroupCategory.ALL:
            self._attr_extra_state_attributes["child_ids"] = [
                child_group.entity_id
                for child_group in self._child_groups
                if child_group.entity_id
            ]
            self.schedule_update_ha_state()

    async def _setup_listeners(self, _=None) -> None:
        """Set up listeners for area and entity state changes."""
        async_dispatcher_connect(
            self.hass, EVENT_ADAPTIVEAREAS_AREA_STATE_CHANGED, self.area_state_changed
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.entity_id], self.group_state_changed
            )
        )

    @callback
    def area_state_changed(self, area_id, states_tuple):
        """Handle area state changes."""
        if area_id != self.area.id or not self.is_control_enabled():
            return False

        if self.category == SwitchGroupCategory.ALL:
            return self._state_change_primary(states_tuple)

        return self._state_change_secondary(states_tuple)

    def _state_change_primary(self, states_tuple):
        """Primary switch group follows clear-state reset."""
        new_states, _ = states_tuple
        if AreaStates.CLEAR in new_states:
            self.reset_control()
            return self._apply_action(False)
        return False

    def _state_change_secondary(self, states_tuple):
        """Handle switch automation for category groups."""
        new_states, _ = states_tuple
        if AreaStates.CLEAR in new_states:
            self.reset_control()
            return self._apply_action(False)

        if (
            AreaStates.OCCUPIED in new_states
            and LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE not in self.act_on
        ):
            return False

        if (
            AreaStates.DARK in new_states
            and LIGHT_GROUP_ACT_ON_DARK_CHANGE not in self.act_on
        ):
            return False

        if (
            AreaStates.EXTENDED in new_states
            and LIGHT_GROUP_ACT_ON_EXTENDED_CHANGE not in self.act_on
        ):
            return False

        if (
            AreaStates.SLEEP in new_states
            and LIGHT_GROUP_ACT_ON_SLEEP_CHANGE not in self.act_on
        ):
            return False

        if not self.assigned_states or not self.area.is_occupied():
            return False

        valid_states = [
            state for state in self.assigned_states if self.area.has_state(state)
        ]
        if valid_states:
            self.controlled = True
            return self._apply_action(True)

        return self._apply_action(False)

    def _apply_action(self, state_active: bool):
        """Apply configured action or inverse action."""
        should_turn_on = (
            self.action == SWITCH_GROUP_ACTION_TURN_ON and state_active
        ) or (self.action != SWITCH_GROUP_ACTION_TURN_ON and not state_active)
        if should_turn_on:
            return self._turn_on()
        return self._turn_off()

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

        return list(dict.fromkeys(normalized))

    def _turn_on(self):
        """Turn switch group on if controllable."""
        if not self.controlling or self.is_on:
            return False

        self.controlled = True
        self.hass.async_create_task(
            self.hass.services.async_call(
                SWITCH_DOMAIN,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: self.entity_id},
                blocking=True,
            )
        )
        return True

    def _turn_off(self):
        """Turn switch group off if controllable."""
        if not self.controlling or not self.is_on:
            return False

        self.controlled = True
        self.hass.async_create_task(
            self.hass.services.async_call(
                SWITCH_DOMAIN,
                SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: self.entity_id},
                blocking=True,
            )
        )
        return True

    def is_control_enabled(self):
        """Check if switch group automation is enabled."""
        entity_id = f"{SWITCH_DOMAIN}.adaptive_areas_switch_groups_{self.area.slug}_switch_group_control"
        switch_entity = self.hass.states.get(entity_id)
        return bool(switch_entity and switch_entity.state.lower() == STATE_ON)

    def reset_control(self):
        """Reset control status."""
        self.controlling = True
        self._attr_extra_state_attributes["controlling"] = self.controlling
        self.schedule_update_ha_state()

    @callback
    def group_state_changed(self, _):
        """Handle manual intervention."""
        if not self.area.is_occupied():
            self.reset_control()
            return

        if self.category == SwitchGroupCategory.ALL:
            self.controlling = any(
                child_group.controlling for child_group in self._child_groups
            )
            self.schedule_update_ha_state()
            return

        if self.controlled:
            self.controlled = False
        else:
            self.controlling = False
            self.schedule_update_ha_state()
