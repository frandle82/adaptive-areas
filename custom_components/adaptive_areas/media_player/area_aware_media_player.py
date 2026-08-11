"""Area aware media player, media player component."""

import logging

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_PLAY_MEDIA,
    MediaPlayerEntityFeature,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_IDLE, STATE_ON

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.const import (
    CONF_NOTIFICATION_DEVICES,
    CONF_NOTIFY_STATES,
    DEFAULT_NOTIFICATION_DEVICES,
    DEFAULT_NOTIFY_STATES,
    AreaStates,
    AdaptiveAreasFeatureInfoAreaAwareMediaPlayer,
    AdaptiveAreasFeatures,
)

_LOGGER = logging.getLogger(__name__)


class AreaAwareMediaPlayer(AdaptiveEntity, MediaPlayerEntity):
    """Area-aware media player."""

    feature_info = AdaptiveAreasFeatureInfoAreaAwareMediaPlayer()

    def __init__(self, area, areas):
        """Initialize area-aware media player."""
        AdaptiveEntity.__init__(self, area, domain=MEDIA_PLAYER_DOMAIN)
        MediaPlayerEntity.__init__(self)

        self._attr_extra_state_attributes = {}
        self._state = STATE_IDLE

        self.areas = areas
        self.area = area
        self._tracked_entities = []

        for area_obj in self.areas:
            entity_list = self.get_media_players_for_area(area_obj)
            if entity_list:
                self._tracked_entities.extend(entity_list)

        _LOGGER.debug("AreaAwareMediaPlayer loaded.")

    def update_attributes(self):
        """Update entity attributes."""
        self._attr_extra_state_attributes["areas"] = [
            f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{area.slug}_area_state"
            for area in self.areas
        ]
        self._attr_extra_state_attributes["entity_id"] = self._tracked_entities

    def get_media_players_for_area(self, area):
        """Return media players for a given area."""
        entity_ids = []

        notification_devices = area.feature_config(
            AdaptiveAreasFeatures.AREA_AWARE_MEDIA_PLAYER
        ).get(CONF_NOTIFICATION_DEVICES, DEFAULT_NOTIFICATION_DEVICES)

        _LOGGER.debug("%s: Notification devices: %s", area.name, notification_devices)

        area_media_players = [
            entity["entity_id"] for entity in area.entities[MEDIA_PLAYER_DOMAIN]
        ]

        # Check if media_player entities are notification devices
        for mp in area_media_players:
            if mp in notification_devices:
                entity_ids.append(mp)

        return set(entity_ids)

    async def async_added_to_hass(self):
        """Call when entity about to be added to hass."""

        last_state = await self.async_get_last_state()

        if last_state:
            _LOGGER.debug(
                "%s: Nedia Player restored [state=%s]", self.name, last_state.state
            )
            self._state = last_state.state
        else:
            self._state = STATE_IDLE

        self.set_state()

    @property
    def state(self):
        """Return the state of the media player."""
        return self._state

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return (
            MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        )

    def get_active_areas(self):
        """Return areas that are occupied."""
        active_areas = []

        for area in self.areas:
            area_binary_sensor_name = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{area.slug}_area_state"
            area_binary_sensor_state = self.hass.states.get(area_binary_sensor_name)

            if not area_binary_sensor_state:
                _LOGGER.debug(
                    "%s: No state found for entity '%s'",
                    self.name,
                    area_binary_sensor_name,
                )
                continue

            # Ignore not occupied areas
            if area_binary_sensor_state.state != STATE_ON:
                continue

            # Check notification states
            notification_states = area.feature_config(
                AdaptiveAreasFeatures.AREA_AWARE_MEDIA_PLAYER
            ).get(CONF_NOTIFY_STATES, DEFAULT_NOTIFY_STATES)

            # Check sleep
            if area.has_state(AreaStates.SLEEP) and (
                AreaStates.SLEEP not in notification_states
            ):
                continue

            # Check other states
            has_valid_state = False
            for notification_state in notification_states:
                if area.has_state(notification_state):
                    has_valid_state = True

            # Append area
            if has_valid_state:
                active_areas.append(area)

        return active_areas

    def update_state(self):
        """Update entity state and attributes."""
        self.update_attributes()
        self.schedule_update_ha_state()

    def set_state(self, state=None):
        """Set the entity state."""
        if state:
            self._state = state
        self.update_state()

    async def async_play_media(self, media_type, media_id, **kwargs) -> None:
        """Forward a piece of media to media players in active areas."""

        # Read active areas
        active_areas = self.get_active_areas()

        # Fail early
        if not active_areas:
            _LOGGER.debug("No areas active. Ignoring.")
            self.area.trace_decision(
                feature="area_aware_media_player",
                trigger="play_media",
                decision="no_action",
                outcome="skipped",
                reason_codes=["no_eligible_areas"],
            )
            return

        # Gather media_player entities
        media_players = []
        for area in active_areas:
            media_players.extend(self.get_media_players_for_area(area))

        if not media_players:
            _LOGGER.debug(
                "%s: No media_player entities to forward. Ignoring.", self.name
            )
            self.area.trace_decision(
                feature="area_aware_media_player",
                trigger="play_media",
                decision="no_action",
                outcome="skipped",
                reason_codes=["no_eligible_entities"],
            )
            return

        data = {
            ATTR_MEDIA_CONTENT_ID: media_id,
            ATTR_MEDIA_CONTENT_TYPE: media_type,
            ATTR_ENTITY_ID: media_players,
        }
        if kwargs:
            data.update(kwargs)

        try:
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN, SERVICE_PLAY_MEDIA, data
            )
        except Exception as err:
            self.area.trace_decision(
                feature="area_aware_media_player",
                trigger="play_media",
                decision="play_media",
                outcome="failed",
                reason_codes=["action_failed"],
                target_count=len(media_players),
                exception_class=type(err).__name__,
            )
            raise
        self.area.trace_decision(
            feature="area_aware_media_player",
            trigger="play_media",
            decision="play_media",
            outcome="executed",
            reason_codes=["eligible_area_active", "action_executed"],
            target_count=len(media_players),
        )
