"""Fan groups & control for Adaptive Areas."""

import logging

from homeassistant.components.fan import DOMAIN as FAN_DOMAIN
from homeassistant.components.group.fan import FanGroup
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_FEATURE_FAN_GROUPS,
    EMPTY_STRING,
    AdaptiveAreasFeatureInfoFanGroups,
)
from custom_components.adaptive_areas.helpers.area import get_area_from_config_entry
from custom_components.adaptive_areas.util import cleanup_removed_entries

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the Area config entry."""

    area: AdaptiveArea | None = get_area_from_config_entry(hass, config_entry)
    assert area is not None

    # Check feature availability
    if not area.has_feature(CONF_FEATURE_FAN_GROUPS):
        return []

    # Check if there are any fan entities
    if not area.has_entities(FAN_DOMAIN):
        _LOGGER.debug("%s: No %s entities for area.", area.name, FAN_DOMAIN)
        return

    fan_entities: list[str] = [e["entity_id"] for e in area.entities[FAN_DOMAIN]]

    try:
        fan_groups: list[AreaFanGroup] = [AreaFanGroup(area, fan_entities)]
        if fan_groups:
            async_add_entities(fan_groups)
    except Exception as e:  # pylint: disable=broad-exception-caught
        _LOGGER.error(
            "%s: Error creating fan group: %s",
            area.slug,
            str(e),
        )

    if FAN_DOMAIN in area.adaptive_entities:
        cleanup_removed_entries(
            area.hass, fan_groups, area.adaptive_entities[FAN_DOMAIN]
        )


class AreaFanGroup(AdaptiveEntity, FanGroup):
    """Fan Group."""

    feature_info = AdaptiveAreasFeatureInfoFanGroups()

    def __init__(self, area: AdaptiveArea, entities: list[str]) -> None:
        """Init the fan group for the area."""
        AdaptiveEntity.__init__(self, area=area, domain=FAN_DOMAIN)
        FanGroup.__init__(
            self,
            entities=entities,
            name=EMPTY_STRING,
            unique_id=self.unique_id,
        )

        delattr(self, "_attr_name")
