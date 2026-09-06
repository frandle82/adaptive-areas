"""Base classes for binary sensor component."""

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.components.group.binary_sensor import BinarySensorGroup
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import AGGREGATE_MODE_ALL, EMPTY_STRING


class AreaSensorGroupBinarySensor(AdaptiveEntity, BinarySensorGroup):
    """Group binary sensor for the area."""

    def __init__(
        self,
        area: AdaptiveArea,
        device_class: str,
        entity_ids: list[str],
    ) -> None:
        """Initialize an area sensor group binary sensor."""

        AdaptiveEntity.__init__(
            self, area, domain=BINARY_SENSOR_DOMAIN, translation_key=device_class
        )
        BinarySensorGroup.__init__(
            self,
            device_class=(
                BinarySensorDeviceClass(device_class) if device_class else None
            ),
            name=EMPTY_STRING,
            unique_id=self._attr_unique_id,
            entity_ids=entity_ids,
            mode=device_class in AGGREGATE_MODE_ALL,
        )
        delattr(self, "_attr_name")

    @property
    def extra_state_attributes(self):
        """Return group attributes plus source availability counts."""
        attributes = dict(super().extra_state_attributes or {})
        available = sum(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            for entity_id in self._entity_ids
        )
        attributes.update(
            {
                "source_count": len(self._entity_ids),
                "available_count": available,
                "unavailable_count": len(self._entity_ids) - available,
            }
        )
        return attributes
