"""The basic entities for adaptive areas."""

import logging

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    META_AREAS,
    AdaptiveAreasFeatureInfo,
)
from custom_components.adaptive_areas.helpers.entity_identity import (
    area_device_identifier,
    generated_ids,
    generated_translation_key,
)

_LOGGER = logging.getLogger(__name__)


class AdaptiveEntity(RestoreEntity):
    """AdaptiveEntity is the base entity for use with all the magic classes."""

    area: AdaptiveArea
    feature_info: AdaptiveAreasFeatureInfo | None = None
    _extra_identifiers: list[str] | None = None
    _attr_has_entity_name = True

    async def async_internal_added_to_hass(self) -> None:
        """Let Meta Areas reconcile their sources once this entity is registered.

        Home Assistant calls this internal hook for every entity before
        async_added_to_hass and continues the MRO chain, so group and restore
        behaviour stays unchanged.
        """
        await super().async_internal_added_to_hass()
        from custom_components.adaptive_areas.helpers.area import (
            refresh_meta_area_sources,
        )

        refresh_meta_area_sources(self.area.hass)

    def __init__(
        self,
        area: AdaptiveArea,
        domain: str,
        translation_key: str | None = None,
        extra_identifiers: list[str] | None = None,
    ) -> None:
        """Initialize the adaptive area."""
        # Avoiding using super() due multiple inheritance issues
        RestoreEntity.__init__(self)

        if not self.feature_info:
            raise NotImplementedError(f"{self.name}: Feature info not set.")

        self.logger = logging.getLogger(type(self).__module__)
        self.area = area
        self._extra_identifiers = []

        if extra_identifiers:
            self._extra_identifiers.extend(extra_identifiers)

        # Allow supplying of additional translation key parts
        # for dealing with device_classes
        self._attr_translation_key = generated_translation_key(
            self.feature_info, domain, translation_key
        )
        self._attr_translation_placeholders = {}

        # Resolve icon
        self._attr_icon = self.feature_info.icons.get(domain, None)

        # Resolve entity id & unique id from the one shared identity rule.
        self.entity_id, self._attr_unique_id = generated_ids(
            self.feature_info,
            domain,
            self.area.slug,
            translation_key,
            self._extra_identifiers,
        )

        _LOGGER.debug(
            "%s: Initializing entity. (entity_id: %s, unique id: %s, translation_key: %s)",
            self.area.name,
            self.entity_id,
            self._attr_unique_id,
            self._attr_translation_key,
        )

    @property
    def should_poll(self) -> bool:
        """If entity should be polled."""
        return False

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            # The stable Area ID is the device identity; it owns the generated entities.
            identifiers={area_device_identifier(self.area.id)},
            name=self.area.name,
            manufacturer="Adaptive Areas",
            model="Adaptive Area",
            translation_key=(
                self.area.slug
                if (self.area.is_meta() and self.area.name in META_AREAS)
                else None
            ),
        )

    async def restore_state(self) -> None:
        """Restore the state of the entity."""
        last_state = await self.async_get_last_state()

        if last_state is None:
            _LOGGER.debug("%s: New entity created", self.name)
            self._attr_state = STATE_OFF
        else:
            _LOGGER.debug(
                "%s: entity restored [state=%s]",
                self.name,
                last_state.state,
            )
            self._attr_state = last_state.state
            self._attr_extra_state_attributes = dict(last_state.attributes)

        self.schedule_update_ha_state()


class BinaryAdaptiveEntity(AdaptiveEntity):
    """Class for binary-state Adaptive Areas entities."""

    _attr_is_on: bool

    async def restore_state(self) -> None:
        """Restore the state of the entity."""
        last_state = await self.async_get_last_state()

        if last_state is None:
            _LOGGER.debug("%s: New entity created", self.name)
            self._attr_is_on = False
        else:
            _LOGGER.debug(
                "%s: entity restored [state=%s]",
                self.name,
                last_state.state,
            )
            self._attr_is_on = last_state.state == STATE_ON
            self._attr_extra_state_attributes = dict(last_state.attributes)

        self.schedule_update_ha_state()
