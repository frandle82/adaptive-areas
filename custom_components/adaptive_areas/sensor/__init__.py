"""Sensor controls for adaptive areas."""

from collections import Counter
from dataclasses import dataclass
import logging

from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.components.sensor.const import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    ATTR_UNIT_OF_MEASUREMENT,
)
from homeassistant.core import Event, HomeAssistant, callback
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
from custom_components.adaptive_areas.helpers.sources import (
    area_entity_ids,
    entity_device_class,
)
from custom_components.adaptive_areas.sensor.base import (
    AreaEnergyAggregateSensor,
    AreaSensorGroupSensor,
)
from custom_components.adaptive_areas.util import cleanup_removed_entries

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AggregateSourceGroup:
    """Discovered sources for one aggregate device class."""

    device_class: str
    entity_ids: list[str]
    unit_of_measurement: str


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the area sensor config entry."""

    area: AdaptiveArea | None = get_area_from_config_entry(hass, config_entry)
    assert area is not None

    entities_to_add = []

    aggregate_manager: AreaAggregateSensorManager | None = None
    if area.has_feature(CONF_FEATURE_AGGREGATION):
        aggregate_manager = AreaAggregateSensorManager(area)
        entities_to_add.extend(aggregate_manager.create_sensors())

    if area.environment is not None:
        entities_to_add.append(EnvironmentSensor(area))

    if entities_to_add:
        async_add_entities(entities_to_add)

    if aggregate_manager is not None:
        aggregate_manager.async_start(async_add_entities)

    if SENSOR_DOMAIN in area.adaptive_entities:
        cleanup_removed_entries(
            area.hass, entities_to_add, area.adaptive_entities[SENSOR_DOMAIN]
        )


def discover_aggregate_source_groups(area: AdaptiveArea) -> list[AggregateSourceGroup]:
    """Discover aggregate source groups for the area."""

    eligible_entities: dict[str, list[str]] = {}
    unit_of_measurement_map: dict[str, list[str]] = {}

    if not area.has_feature(CONF_FEATURE_AGGREGATION):
        return []

    entity_ids = area_entity_ids(
        area.hass, area.hass_config, area.config, domain=SENSOR_DOMAIN
    )
    entity_ids.update(
        entity[ATTR_ENTITY_ID]
        for entity in area.entities.get(SENSOR_DOMAIN, [])
        if isinstance(entity.get(ATTR_ENTITY_ID), str)
    )

    for entity_id in sorted(entity_ids):
        device_class = entity_device_class(area.hass, entity_id)
        if device_class is None or device_class not in area.feature_config(
            CONF_FEATURE_AGGREGATION
        ).get(
            CONF_AGGREGATES_SENSOR_DEVICE_CLASSES,
            DEFAULT_AGGREGATES_SENSOR_DEVICE_CLASSES,
        ):
            _LOGGER.debug(
                "Entity %s does not have device_class defined",
                entity_id,
            )
            continue

        entity_state = area.hass.states.get(entity_id)
        if (
            entity_state is None
            or ATTR_UNIT_OF_MEASUREMENT not in entity_state.attributes
            or not entity_state.attributes[ATTR_UNIT_OF_MEASUREMENT]
        ):
            _LOGGER.debug(
                "Entity %s does not have unit_of_measurement defined",
                entity_id,
            )
            continue

        # Dictionary of sensors by device class.
        if device_class not in eligible_entities:
            eligible_entities[device_class] = []

        # Dictionary of seen unit of measurements by device class.
        if device_class not in unit_of_measurement_map:
            unit_of_measurement_map[device_class] = []

        unit_of_measurement_map[device_class].append(
            entity_state.attributes[ATTR_UNIT_OF_MEASUREMENT]
        )
        eligible_entities[device_class].append(entity_id)

    groups: list[AggregateSourceGroup] = []
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

            groups.append(
                AggregateSourceGroup(
                    device_class=device_class,
                    entity_ids=entities,
                    unit_of_measurement=most_common_unit_of_measurement,
                ),
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s: Error discovering '%s' aggregate sensor: %s",
                area.slug,
                device_class,
                str(e),
            )

    return groups


def create_aggregate_sensors(area: AdaptiveArea) -> list[Entity]:
    """Create the aggregate sensors for the area."""
    aggregates = []
    for group in discover_aggregate_source_groups(area):
        aggregates.append(_create_aggregate_sensor(area, group))
    return aggregates


class AreaAggregateSensor(AreaSensorGroupSensor):
    """Aggregate sensor for the area."""

    feature_info = AdaptiveAreasFeatureInfoAggregates()


def _create_aggregate_sensor(
    area: AdaptiveArea, group: AggregateSourceGroup
) -> AreaAggregateSensor | AreaEnergyAggregateSensor:
    """Create the appropriate implementation for an aggregate group."""
    sensor_class = (
        AreaEnergyAggregateSensor
        if group.device_class == SensorDeviceClass.ENERGY
        else AreaAggregateSensor
    )
    return sensor_class(
        area=area,
        device_class=group.device_class,
        entity_ids=group.entity_ids,
        unit_of_measurement=group.unit_of_measurement,
    )


class AreaAggregateSensorManager:
    """Refresh area aggregate sensors when source metadata becomes available."""

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize the aggregate sensor manager."""
        self.area = area
        self._sensors: dict[str, AreaAggregateSensor | AreaEnergyAggregateSensor] = {}
        self._known_source_ids: set[str] = set()

    def create_sensors(self) -> list[AreaAggregateSensor | AreaEnergyAggregateSensor]:
        """Create initial aggregate sensors."""
        sensors = []
        for group in discover_aggregate_source_groups(self.area):
            sensor = _create_aggregate_sensor(self.area, group)
            self._sensors[group.device_class] = sensor
            self._known_source_ids.update(group.entity_ids)
            sensors.append(sensor)
        self._refresh_known_source_ids()
        return sensors

    @callback
    def async_start(self, async_add_entities: AddEntitiesCallback) -> None:
        """Start listening for source discovery changes."""
        self.area.hass_config.async_on_unload(
            self.area.hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                self._state_changed,
            )
        )
        self.area.hass_config.async_on_unload(
            self.area.hass.bus.async_listen(
                EVENT_ENTITY_REGISTRY_UPDATED,
                self._registry_changed,
            )
        )
        self.area.hass_config.async_on_unload(
            self.area.hass.bus.async_listen(
                EVENT_DEVICE_REGISTRY_UPDATED,
                self._registry_changed,
            )
        )
        self.async_refresh(async_add_entities)

    @callback
    def _refresh_known_source_ids(self) -> None:
        """Refresh all registry-known Area sensor candidates."""
        self._known_source_ids = area_entity_ids(
            self.area.hass,
            self.area.hass_config,
            self.area.config,
            domain=SENSOR_DOMAIN,
        )

    @callback
    def _state_changed(self, event: Event) -> None:
        """Refresh discovery when a known candidate gains useful metadata."""
        entity_id = event.data.get(ATTR_ENTITY_ID)
        if entity_id not in self._known_source_ids:
            return
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if old_state is not None and (
            old_state.attributes.get(ATTR_DEVICE_CLASS)
            == new_state.attributes.get(ATTR_DEVICE_CLASS)
            and old_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            == new_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        ):
            return
        if new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        self.async_refresh(prune_missing=False)

    @callback
    def _registry_changed(self, _event: Event) -> None:
        """Refresh discovery after registry membership may have changed."""
        self._refresh_known_source_ids()
        self.async_refresh(prune_missing=True)

    @callback
    def async_refresh(
        self,
        async_add_entities: AddEntitiesCallback | None = None,
        *,
        prune_missing: bool = False,
    ) -> None:
        """Refresh existing aggregate sensors and add newly discovered ones."""
        new_sensors: list[AreaAggregateSensor | AreaEnergyAggregateSensor] = []
        seen_device_classes: set[str] = set()
        for group in discover_aggregate_source_groups(self.area):
            seen_device_classes.add(group.device_class)
            self._known_source_ids.update(group.entity_ids)
            if group.device_class in self._sensors:
                entity_ids = group.entity_ids
                if not prune_missing:
                    entity_ids = sorted(
                        {
                            *self._sensors[group.device_class].source_entity_ids,
                            *group.entity_ids,
                        }
                    )
                self._sensors[group.device_class].async_set_entity_ids(entity_ids)
                continue
            sensor = _create_aggregate_sensor(self.area, group)
            self._sensors[group.device_class] = sensor
            new_sensors.append(sensor)
        if prune_missing:
            for device_class, sensor in self._sensors.items():
                if device_class not in seen_device_classes:
                    sensor.async_set_entity_ids([])
        if new_sensors and async_add_entities is not None:
            async_add_entities(new_sensors)


class EnvironmentSensor(AdaptiveEntity, SensorEntity):
    """Expose Area Climate assessment under stable environment IDs."""

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

    @staticmethod
    def _used_entity_ids(
        assessment: dict, source_key: str = "source_entities"
    ) -> list[str]:
        """Return a flat list of entities that contributed to the assessment."""
        entity_ids: set[str] = set()
        for source in assessment.get(source_key, {}).values():
            entity_id = source.get("entity_id")
            if (
                source.get("available")
                and isinstance(entity_id, str)
                and entity_id.startswith("sensor.")
            ):
                entity_ids.add(entity_id)
            entity_ids.update(
                entity["entity_id"]
                for entity in source.get("entities", [])
                if entity.get("entity_id", "").startswith("sensor.")
            )
        return sorted(entity_ids)

    def _assessment_changed(self) -> None:
        """Publish stable assessment outputs and transparent source attribution."""
        if self.area.environment is None:
            return
        assessment = self.area.environment.assessment
        self._attr_native_value = str(assessment.get("state", "unknown"))
        if self.area.is_exterior():
            self._attr_extra_state_attributes = {
                "temperature": assessment.get("temperature"),
                "relative_humidity": assessment.get("relative_humidity"),
                "humidity": str(assessment.get("humidity", "unknown")),
                "pollutant_state": str(assessment.get("pollutant_state", "unknown")),
                "dew_point": assessment.get("dew_point"),
                "absolute_humidity": assessment.get("absolute_humidity"),
                "humidity_ratio": assessment.get("humidity_ratio"),
                "enthalpy": assessment.get("enthalpy"),
                "air_quality": str(assessment.get("air_quality", "unknown")),
                "pollutant_measurements": dict(assessment.get("pollutants", {})),
                "pollutant_assessments": assessment.get("pollutant_assessments", {}),
                "source_entities": self._used_entity_ids(assessment),
                "ignored_sources": assessment.get("ignored_sources", {}),
                "available_capabilities": sorted(
                    capability
                    for capability, available in assessment.get(
                        "capabilities", {}
                    ).items()
                    if available
                ),
                "context": assessment.get("context", ""),
                "reason_codes": list(assessment.get("reason_codes", [])),
                "recommended_action": str(assessment.get("recommended_action", "none")),
                "secondary_actions": list(assessment.get("secondary_actions", [])),
                "recommendation_reason_codes": list(
                    assessment.get("recommendation_reason_codes", [])
                ),
            }
            self.async_write_ha_state()
            return
        attributes = {
            "comfort": str(assessment.get("comfort", "unknown")),
            "room_category": str(assessment.get("room_category", "unknown")),
            "humidity": str(assessment.get("humidity", "unknown")),
            "mould_risk": str(assessment.get("mould_risk", "unknown")),
            "pollutant_state": str(assessment.get("pollutant_state", "unknown")),
            "dominant_indoor_pollutant": assessment.get(
                "dominant_indoor_pollutant", "unknown"
            ),
            "air_quality": str(assessment.get("air_quality", "unknown")),
            "ventilation_demand": str(assessment.get("ventilation_demand", "unknown")),
            "ventilation_activity": str(
                assessment.get("ventilation_activity", "inactive")
            ),
            "ventilation_strategy": str(
                assessment.get("ventilation_strategy", "unknown")
            ),
            "air_cleaning_recommendation": str(
                assessment.get("air_cleaning_recommendation", "unknown")
            ),
            "cooling": str(assessment.get("cooling", "unknown")),
            "moisture_ventilation": assessment.get("moisture_ventilation", "unknown"),
            "air_exchange_suitability": str(
                assessment.get("air_exchange_suitability", "unknown")
            ),
            "outdoor_pollutant_measurements": assessment.get("outdoor_pollutants", {}),
            "indoor_pollutant_measurements": dict(
                assessment.get("indoor_pollutant_measurements", {})
            ),
            "indoor_pollutant_assessments": assessment.get(
                "indoor_pollutant_assessments", {}
            ),
            # Deprecated compatibility aliases.
            "pollutant_measurements": dict(assessment.get("pollutants", {})),
            "pollutant_assessments": assessment.get("pollutant_assessments", {}),
            "indoor_source_entities": self._used_entity_ids(
                assessment, "indoor_source_entities"
            ),
            "outdoor_source_entities": self._used_entity_ids(
                assessment, "outdoor_source_entities"
            ),
            "source_entities": self._used_entity_ids(assessment),
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
            "context": assessment.get("context", ""),
            "indoor_reason_codes": list(assessment.get("indoor_reason_codes", [])),
            "mitigation_reason_codes": list(
                assessment.get("mitigation_reason_codes", [])
            ),
            "reason_codes": list(assessment.get("reason_codes", [])),
            "recommended_action": str(assessment.get("recommended_action", "none")),
            "secondary_actions": list(assessment.get("secondary_actions", [])),
            "recommendation_reason_codes": list(
                assessment.get("recommendation_reason_codes", [])
            ),
        }
        self._attr_extra_state_attributes = attributes
        self.async_write_ha_state()
