"""Number controls for Adaptive Areas."""

from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
    NumberDeviceClass,
    NumberEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.const import (
    CONF_FEATURE_ENVIRONMENT,
    CONF_ROOM_CATEGORY,
    AdaptiveAreasFeatureInfoEnvironmentReferenceTemperature,
    RoomCategory,
)
from custom_components.adaptive_areas.helpers.area import get_area_from_config_entry
from custom_components.adaptive_areas.util import cleanup_removed_entries

DEFAULT_MANUAL_REFERENCE_TEMPERATURE = 20.0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up manual Area Climate controls for an Area."""
    area: AdaptiveArea | None = get_area_from_config_entry(hass, config_entry)
    assert area is not None

    entities_to_add: list[NumberEntity] = []
    if (
        area.environment is not None
        and area.has_feature(CONF_FEATURE_ENVIRONMENT)
        and area.config.get(CONF_ROOM_CATEGORY) == RoomCategory.MANUAL
    ):
        entities_to_add.append(EnvironmentReferenceTemperatureNumber(area))

    if entities_to_add:
        async_add_entities(entities_to_add)

    if NUMBER_DOMAIN in area.adaptive_entities:
        cleanup_removed_entries(
            area.hass, entities_to_add, area.adaptive_entities[NUMBER_DOMAIN]
        )


class EnvironmentReferenceTemperatureNumber(AdaptiveEntity, NumberEntity):
    """Set the thermal reference for a manually categorized Area."""

    feature_info = AdaptiveAreasFeatureInfoEnvironmentReferenceTemperature()
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_min_value = 5.0
    _attr_native_max_value = 35.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize the reference-temperature input."""
        AdaptiveEntity.__init__(self, area, domain=NUMBER_DOMAIN)
        NumberEntity.__init__(self)
        self._attr_native_value = DEFAULT_MANUAL_REFERENCE_TEMPERATURE

    async def async_added_to_hass(self) -> None:
        """Restore the previous reference and apply it to Area Climate."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                restored = float(last_state.state)
            except TypeError, ValueError:
                pass
            else:
                self._attr_native_value = min(
                    max(restored, self.native_min_value), self.native_max_value
                )
        self._apply_reference()

    async def async_set_native_value(self, value: float) -> None:
        """Set and immediately apply a manual thermal reference."""
        self._attr_native_value = round(value * 2) / 2
        self._apply_reference()
        self.async_write_ha_state()

    def _apply_reference(self) -> None:
        """Update the live Environment engine."""
        if self.area.environment is not None and self._attr_native_value is not None:
            self.area.environment.set_manual_reference_temperature(
                self._attr_native_value
            )
