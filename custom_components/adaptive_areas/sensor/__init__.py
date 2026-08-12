"""Sensor controls for adaptive areas."""

from collections import Counter
import logging

from homeassistant.components.sensor.const import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_AGGREGATES_SENSOR_DEVICE_CLASSES,
    CONF_FEATURE_AGGREGATION,
    DEFAULT_AGGREGATES_MIN_ENTITIES,
    DEFAULT_AGGREGATES_SENSOR_DEVICE_CLASSES,
    AdaptiveAreasFeatureInfoAggregates,
    AdaptiveAreasFeatureInfoEnvironment,
    EnvironmentState,
)
from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.helpers.area import get_area_from_config_entry
from custom_components.adaptive_areas.sensor.base import AreaSensorGroupSensor
from custom_components.adaptive_areas.util import cleanup_removed_entries

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the area sensor config entry."""

    area: AdaptiveArea | None = get_area_from_config_entry(hass, config_entry)
    assert area is not None

    entities_to_add = []

    if area.has_feature(CONF_FEATURE_AGGREGATION):
        entities_to_add.extend(create_aggregate_sensors(area))

    if area.environment is not None:
        entities_to_add.append(EnvironmentSensor(area))

    if entities_to_add:
        async_add_entities(entities_to_add)

    if SENSOR_DOMAIN in area.adaptive_entities:
        cleanup_removed_entries(
            area.hass, entities_to_add, area.adaptive_entities[SENSOR_DOMAIN]
        )


def create_aggregate_sensors(area: AdaptiveArea) -> list[Entity]:
    """Create the aggregate sensors for the area."""

    eligible_entities: dict[str, list[str]] = {}
    unit_of_measurement_map: dict[str, list[str]] = {}

    aggregates = []

    if SENSOR_DOMAIN not in area.entities:
        return []

    if not area.has_feature(CONF_FEATURE_AGGREGATION):
        return []

    for entity in area.entities[SENSOR_DOMAIN]:
        entity_state = area.hass.states.get(entity[ATTR_ENTITY_ID])
        if not entity_state:
            continue

        if (
            ATTR_DEVICE_CLASS not in entity_state.attributes
            or not entity_state.attributes[ATTR_DEVICE_CLASS]
        ):
            _LOGGER.debug(
                "Entity %s does not have device_class defined",
                entity[ATTR_ENTITY_ID],
            )
            continue

        if (
            ATTR_UNIT_OF_MEASUREMENT not in entity_state.attributes
            or not entity_state.attributes[ATTR_UNIT_OF_MEASUREMENT]
        ):
            _LOGGER.debug(
                "Entity %s does not have unit_of_measurement defined",
                entity[ATTR_ENTITY_ID],
            )
            continue

        device_class = entity_state.attributes[ATTR_DEVICE_CLASS]

        # Dictionary of sensors by device class.
        if device_class not in eligible_entities:
            eligible_entities[device_class] = []

        # Dictionary of seen unit of measurements by device class.
        if device_class not in unit_of_measurement_map:
            unit_of_measurement_map[device_class] = []

        unit_of_measurement_map[device_class].append(
            entity_state.attributes[ATTR_UNIT_OF_MEASUREMENT]
        )
        eligible_entities[device_class].append(entity[ATTR_ENTITY_ID])

    # Create aggregates
    for device_class, entities in eligible_entities.items():
        if len(entities) < area.feature_config(CONF_FEATURE_AGGREGATION).get(
            CONF_AGGREGATES_MIN_ENTITIES, DEFAULT_AGGREGATES_MIN_ENTITIES
        ):
            continue

        if device_class not in area.feature_config(CONF_FEATURE_AGGREGATION).get(
            CONF_AGGREGATES_SENSOR_DEVICE_CLASSES,
            DEFAULT_AGGREGATES_SENSOR_DEVICE_CLASSES,
        ):
            continue

        _LOGGER.debug(
            "%s: Creating aggregate sensor for device_class '%s' with %d entities",
            area.slug,
            device_class,
            len(entities),
        )

        try:
            # Infer most-popular unit of measurement
            unit_of_measurements = Counter(unit_of_measurement_map[device_class])
            most_common_unit_of_measurement = unit_of_measurements.most_common(1)[0][0]

            aggregates.append(
                AreaAggregateSensor(
                    area=area,
                    device_class=device_class,
                    entity_ids=entities,
                    unit_of_measurement=most_common_unit_of_measurement,
                )
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s: Error creating '%s' aggregate sensor: %s",
                area.slug,
                device_class,
                str(e),
            )

    return aggregates


class AreaAggregateSensor(AreaSensorGroupSensor):
    """Aggregate sensor for the area."""

    feature_info = AdaptiveAreasFeatureInfoAggregates()


class EnvironmentSensor(AdaptiveEntity, SensorEntity):
    """Expose the unified environmental assessment as one low-churn sensor."""

    feature_info = AdaptiveAreasFeatureInfoEnvironment()
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [str(state) for state in EnvironmentState]

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize the Environment sensor."""
        AdaptiveEntity.__init__(self, area, domain=SENSOR_DOMAIN)
        SensorEntity.__init__(self)

    async def async_added_to_hass(self) -> None:
        """Subscribe to assessment transitions."""
        await super().async_added_to_hass()
        assert self.area.environment is not None
        self.async_on_remove(
            self.area.environment.register_listener(self._assessment_changed)
        )
        self._assessment_changed()

    def _assessment_changed(self) -> None:
        """Publish stable assessment outputs and transparent source attribution."""
        if self.area.environment is None:
            return
        assessment = self.area.environment.assessment
        pollutants = assessment.get("pollutants", {})
        self._attr_native_value = str(assessment.get("state", "unknown"))
        self._attr_extra_state_attributes = {
            "comfort": str(assessment.get("comfort", "unknown")),
            "comfort_confidence": assessment.get("comfort_confidence", "unknown"),
            "comfort_quality": assessment.get("comfort_quality", "unknown"),
            "room_category": str(assessment.get("room_category", "unknown")),
            "thermal_profile": assessment.get("thermal_profile", {}),
            "humidity": str(assessment.get("humidity", "unknown")),
            "mould_risk": str(assessment.get("mould_risk", "unknown")),
            "air_quality": str(assessment.get("air_quality", "unknown")),
            "ventilation": str(assessment.get("ventilation", "unknown")),
            "cooling": str(assessment.get("cooling", "unknown")),
            "temperature": assessment.get("temperature"),
            "relative_humidity": assessment.get("relative_humidity"),
            "dew_point": assessment.get("dew_point"),
            "absolute_humidity": assessment.get("absolute_humidity"),
            "humidity_ratio": assessment.get("humidity_ratio"),
            "enthalpy": assessment.get("enthalpy"),
            "humidex": assessment.get("humidex"),
            "apparent_temperature": assessment.get("apparent_temperature"),
            "surface_temperature": assessment.get("surface_temperature"),
            "surface_relative_humidity": assessment.get("surface_relative_humidity"),
            "mould_quality": assessment.get("mould_quality", "unknown"),
            "mould_warning_duration_seconds": assessment.get(
                "mould_warning_duration_seconds", 0
            ),
            "outdoor_temperature": assessment.get("outdoor_temperature"),
            "outdoor_relative_humidity": assessment.get("outdoor_relative_humidity"),
            "outdoor_humidity_ratio": assessment.get("outdoor_humidity_ratio"),
            "outdoor_enthalpy": assessment.get("outdoor_enthalpy"),
            "moisture_ventilation": assessment.get("moisture_ventilation", "unknown"),
            "pollutant_measurements": dict(pollutants),
            "pollutant_assessments": assessment.get("pollutant_assessments", {}),
            "source_entities": assessment.get("source_entities", {}),
            "window_recommendation": str(
                assessment.get("window_recommendation", "none")
            ),
            "ventilation_fan_request": str(
                assessment.get("ventilation_fan_request", "none")
            ),
            "circulation_fan_request": str(
                assessment.get("circulation_fan_request", "none")
            ),
            "available_capabilities": sorted(
                capability
                for capability, available in assessment.get("capabilities", {}).items()
                if available
            ),
            "room_usage": str(assessment.get("room_usage", "unknown")),
            "cleaning_recommendation": str(
                assessment.get("cleaning_recommendation", "unknown")
            ),
            "current_occupancy_duration": assessment.get("current_occupancy_duration"),
            "occupied_duration_today": assessment.get("occupied_duration_today"),
            "occupancy_sessions_today": assessment.get("occupancy_sessions_today"),
            "time_since_last_occupancy": assessment.get("time_since_last_occupancy"),
            "humidity_warning_duration_seconds": assessment.get(
                "humidity_warning_duration_seconds", 0
            ),
            "last_occupied": assessment.get("last_occupied"),
            "last_cleared": assessment.get("last_cleared"),
            "context": assessment.get("context", ""),
            "reason_codes": list(assessment.get("reason_codes", [])),
            # Compatibility alias retained for 1.3 release-candidate users.
            "decision_context": list(assessment.get("reason_codes", [])),
        }
        self.async_write_ha_state()
