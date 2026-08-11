"""Presence hold switch."""

from homeassistant.const import EntityCategory

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_PRESENCE_HOLD_TIMEOUT,
    DEFAULT_PRESENCE_HOLD_TIMEOUT,
    AdaptiveAreasFeatureInfoPresenceHold,
    AdaptiveAreasFeatures,
)
from custom_components.adaptive_areas.switch.base import ResettableSwitchBase


class PresenceHoldSwitch(ResettableSwitchBase):
    """Switch to enable/disable presence hold."""

    feature_info = AdaptiveAreasFeatureInfoPresenceHold()
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize the switch."""

        timeout = area.feature_config(AdaptiveAreasFeatures.PRESENCE_HOLD).get(
            CONF_PRESENCE_HOLD_TIMEOUT, DEFAULT_PRESENCE_HOLD_TIMEOUT
        )

        ResettableSwitchBase.__init__(self, area, timeout=timeout)
