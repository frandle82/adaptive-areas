"""Base classes for sensor component."""

import logging
import math
from typing import Any

from homeassistant.components.group.sensor import ATTR_MEAN, ATTR_SUM, SensorGroup
from homeassistant.components.sensor.const import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    AGGREGATE_MODE_SUM,
    AGGREGATE_MODE_TOTAL_INCREASING_SENSOR,
    AGGREGATE_MODE_TOTAL_SENSOR,
    DEFAULT_SENSOR_PRECISION,
    EMPTY_STRING,
)

_LOGGER = logging.getLogger(__name__)


class AreaSensorGroupSensor(AdaptiveEntity, SensorGroup):
    """Sensor for the adaptive area, group sensor with all the stuff in it."""

    def __init__(
        self,
        area: AdaptiveArea,
        device_class: str,
        entity_ids: list[str],
        unit_of_measurement: str,
    ) -> None:
        """Initialize an area sensor group sensor."""

        AdaptiveEntity.__init__(
            self, area=area, domain=SENSOR_DOMAIN, translation_key=device_class
        )

        final_unit_of_measurement = None

        # Resolve unit of measurement
        unit_attr_name = f"{device_class}_unit"
        if hasattr(area.hass.config.units, unit_attr_name):
            final_unit_of_measurement = getattr(area.hass.config.units, unit_attr_name)
        else:
            final_unit_of_measurement = unit_of_measurement

        self._attr_suggested_display_precision = DEFAULT_SENSOR_PRECISION

        sensor_device_class: SensorDeviceClass | None = (
            SensorDeviceClass(device_class) if device_class else None
        )
        self.device_class = sensor_device_class

        state_class = SensorStateClass.MEASUREMENT

        if device_class in AGGREGATE_MODE_TOTAL_INCREASING_SENSOR:
            state_class = SensorStateClass.TOTAL_INCREASING
        elif device_class in AGGREGATE_MODE_TOTAL_SENSOR:
            state_class = SensorStateClass.TOTAL

        SensorGroup.__init__(
            self,
            hass=area.hass,
            device_class=sensor_device_class,
            entity_ids=entity_ids,
            ignore_non_numeric=True,
            sensor_type=ATTR_SUM if device_class in AGGREGATE_MODE_SUM else ATTR_MEAN,
            state_class=state_class,
            unit_of_measurement=final_unit_of_measurement,
            name=EMPTY_STRING,
            unique_id=self._attr_unique_id,
        )
        delattr(self, "_attr_name")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return unchanged group attributes plus source quality metadata."""
        attributes = dict(super().extra_state_attributes)
        available_states = [
            state
            for entity_id in self._entity_ids
            if (state := self.hass.states.get(entity_id)) is not None
            and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        ]
        numeric_values: list[float] = []
        for state in available_states:
            try:
                value = float(state.state)
            except TypeError, ValueError:
                continue
            if math.isfinite(value):
                numeric_values.append(value)
        minimum = min(numeric_values) if numeric_values else None
        maximum = max(numeric_values) if numeric_values else None
        attributes.update(
            {
                "source_count": len(self._entity_ids),
                "available_count": len(available_states),
                "unavailable_count": len(self._entity_ids) - len(available_states),
                "minimum": minimum,
                "maximum": maximum,
                "spread": (
                    maximum - minimum
                    if minimum is not None and maximum is not None
                    else None
                ),
                "source_units": sorted(
                    {
                        str(unit)
                        for state in available_states
                        if (unit := state.attributes.get("unit_of_measurement"))
                    }
                ),
                "source_device_class": (
                    str(self.device_class) if self.device_class is not None else None
                ),
            }
        )
        return attributes
