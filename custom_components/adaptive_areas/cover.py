"""Cover controls for adaptive areas."""

import logging

from homeassistant.components.cover import (
    DEVICE_CLASSES as COVER_DEVICE_CLASSES,
    CoverDeviceClass,
)
from homeassistant.components.cover.const import DOMAIN as COVER_DOMAIN
from homeassistant.components.group.cover import CoverGroup
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_FEATURE_COVER_GROUPS,
    EMPTY_STRING,
    AdaptiveAreasFeatureInfoCoverGroups,
)
from custom_components.adaptive_areas.helpers.area import get_area_from_config_entry
from custom_components.adaptive_areas.helpers.cover.controller import (
    AreaCoverController,
)
from custom_components.adaptive_areas.util import cleanup_removed_entries

_LOGGER = logging.getLogger(__name__)
DEPENDENCIES = ["adaptive_areas"]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the area cover config entry."""

    area: AdaptiveArea | None = get_area_from_config_entry(hass, config_entry)
    assert area is not None

    # Check feature availability
    if not area.has_feature(CONF_FEATURE_COVER_GROUPS):
        if COVER_DOMAIN in area.adaptive_entities:
            cleanup_removed_entries(area.hass, [], area.adaptive_entities[COVER_DOMAIN])
        return

    # Check if there are any covers
    if not area.has_entities(COVER_DOMAIN):
        _LOGGER.debug("No %s entities for area %s", COVER_DOMAIN, area.name)
        if COVER_DOMAIN in area.adaptive_entities:
            cleanup_removed_entries(area.hass, [], area.adaptive_entities[COVER_DOMAIN])
        return

    entities_to_add = []

    if area.cover_control is None:
        area.cover_control = AreaCoverController(area)
        await area.cover_control.async_start()

    # Append None to the list of device classes to catch those covers that
    # don't have a device class assigned (and put them in their own group)
    for device_class in [*COVER_DEVICE_CLASSES, None]:
        covers_in_device_class = [
            e["entity_id"]
            for e in area.entities[COVER_DOMAIN]
            if e.get("device_class") == device_class
        ]

        if any(covers_in_device_class):
            _LOGGER.debug(
                "Creating %s cover group for %s with covers: %s",
                device_class,
                area.name,
                covers_in_device_class,
            )
            entities_to_add.append(AreaCoverGroup(area, device_class))

    if entities_to_add:
        async_add_entities(entities_to_add)

    if COVER_DOMAIN in area.adaptive_entities:
        cleanup_removed_entries(
            area.hass, entities_to_add, area.adaptive_entities[COVER_DOMAIN]
        )


class AreaCoverGroup(AdaptiveEntity, CoverGroup):
    """Cover group for handling all the covers in the area."""

    feature_info = AdaptiveAreasFeatureInfoCoverGroups()

    def __init__(self, area: AdaptiveArea, device_class: str) -> None:
        """Initialize the cover group."""
        AdaptiveEntity.__init__(
            self, area, domain=COVER_DOMAIN, translation_key=device_class
        )
        sensor_device_class: CoverDeviceClass | None = (
            CoverDeviceClass(device_class) if device_class else None
        )
        self._attr_device_class = sensor_device_class
        self._entities = [
            e
            for e in area.entities[COVER_DOMAIN]
            if e.get("device_class") == device_class
        ]
        CoverGroup.__init__(
            self,
            entities=[e["entity_id"] for e in self._entities],
            name=EMPTY_STRING,
            unique_id=self._attr_unique_id,
        )
        delattr(self, "_attr_name")

    async def async_added_to_hass(self) -> None:
        """Subscribe to cover-control diagnostic transitions."""
        await super().async_added_to_hass()
        if self.area.cover_control is not None:
            self.async_on_remove(
                self.area.cover_control.register_listener(self._decision_changed)
            )
            self._decision_changed()

    def _decision_changed(self) -> None:
        """Publish dashboard-neutral decision diagnostics."""
        if self.area.cover_control is None:
            return
        self._attr_extra_state_attributes.update(self.area.cover_control.diagnostics)
        self.async_write_ha_state()
