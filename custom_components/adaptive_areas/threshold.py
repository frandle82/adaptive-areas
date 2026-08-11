"""Platform file for Adaptive Areas threhsold sensors."""

import logging

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.components.sensor.const import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
)
from homeassistant.components.threshold.binary_sensor import ThresholdSensor
from homeassistant.const import ATTR_DEVICE_CLASS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD,
    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS,
    CONF_AGGREGATES_SENSOR_DEVICE_CLASSES,
    CONF_FEATURE_AGGREGATION,
    DEFAULT_AGGREGATES_ILLUMINANCE_THRESHOLD,
    DEFAULT_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS,
    DEFAULT_AGGREGATES_SENSOR_DEVICE_CLASSES,
    EMPTY_STRING,
    AdaptiveAreasFeatureInfoThrehsold,
)

_LOGGER = logging.getLogger(__name__)


def create_illuminance_threshold(
    hass: HomeAssistant, area: AdaptiveArea
) -> Entity | None:
    """Create threhsold light binary sensor based off illuminance aggregate."""

    if not area.has_feature(CONF_FEATURE_AGGREGATION):
        return None

    illuminance_threshold = area.feature_config(CONF_FEATURE_AGGREGATION).get(
        CONF_AGGREGATES_ILLUMINANCE_THRESHOLD, DEFAULT_AGGREGATES_ILLUMINANCE_THRESHOLD
    )

    if illuminance_threshold == 0:
        return None

    if SensorDeviceClass.ILLUMINANCE not in area.feature_config(
        CONF_FEATURE_AGGREGATION
    ).get(
        CONF_AGGREGATES_SENSOR_DEVICE_CLASSES, DEFAULT_AGGREGATES_SENSOR_DEVICE_CLASSES
    ):
        return None

    if SENSOR_DOMAIN not in area.entities:
        return None

    illuminance_sensors = [
        sensor
        for sensor in area.entities[SENSOR_DOMAIN]
        if ATTR_DEVICE_CLASS in sensor
        and sensor[ATTR_DEVICE_CLASS] == SensorDeviceClass.ILLUMINANCE
    ]

    if not illuminance_sensors:
        return None

    illuminance_threshold_hysteresis_percentage = area.feature_config(
        CONF_FEATURE_AGGREGATION
    ).get(
        CONF_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS,
        DEFAULT_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS,
    )
    illuminance_threshold_hysteresis = 0

    if illuminance_threshold_hysteresis_percentage > 0:
        illuminance_threshold_hysteresis = illuminance_threshold * (
            illuminance_threshold_hysteresis_percentage / 100
        )

    illuminance_aggregate_entity_id = (
        f"{SENSOR_DOMAIN}.adaptive_areas_aggregates_{area.slug}_aggregate_illuminance"
    )

    _LOGGER.debug(
        "Creating illuminance threhsold sensor for area '%s': Threhsold: %d, Hysteresis: %d (%d%%)",
        area.slug,
        illuminance_threshold,
        illuminance_threshold_hysteresis,
        illuminance_threshold_hysteresis_percentage,
    )

    try:
        return AreaThresholdSensor(
            hass=hass,
            area=area,
            device_class=BinarySensorDeviceClass.LIGHT,
            entity_id=illuminance_aggregate_entity_id,
            upper=illuminance_threshold,
            hysteresis=illuminance_threshold_hysteresis,
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        _LOGGER.error(
            "%s: Error creating calculated light sensor: %s",
            area.slug,
            str(e),
        )
        return None


class AreaThresholdSensor(AdaptiveEntity, ThresholdSensor):
    """Threshold sensor based off aggregates."""

    feature_info = AdaptiveAreasFeatureInfoThrehsold()

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        area: AdaptiveArea,
        device_class: BinarySensorDeviceClass,
        entity_id: str,
        upper: int | None = None,
        lower: int | None = None,
        hysteresis: int = 0,
    ) -> None:
        """Initialize an area sensor group binary sensor."""

        AdaptiveEntity.__init__(
            self, area, domain=BINARY_SENSOR_DOMAIN, translation_key=device_class
        )
        ThresholdSensor.__init__(
            self,
            entity_id=entity_id,
            name=EMPTY_STRING,
            unique_id=self.unique_id,
            lower=lower,
            upper=upper,
            hysteresis=hysteresis,
            device_class=device_class,
        )
        delattr(self, "_attr_name")
