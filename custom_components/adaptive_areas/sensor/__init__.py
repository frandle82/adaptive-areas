"""Sensor controls for adaptive areas."""

from collections import Counter
from dataclasses import dataclass
from collections.abc import Callable
import logging

from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.components.sensor.const import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    ATTR_UNIT_OF_MEASUREMENT,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_AGGREGATES_SENSOR_DEVICE_CLASSES,
    CONF_FEATURE_AGGREGATION,
    DEFAULT_AGGREGATES_MIN_ENTITIES,
    DEFAULT_AGGREGATES_SENSOR_DEVICE_CLASSES,
    AdaptiveAreasFeatureInfoAggregates,
    AdaptiveAreasFeatureInfoEnvironment,
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
        self._remove_source_listener: Callable[[], None] | None = None
        self._remove_refresh_timer: Callable[[], None] | None = None
        self._pending_add_entities: AddEntitiesCallback | None = None
        self._pending_prune_missing = False

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
        self._refresh_source_listener()
        self.area.hass_config.async_on_unload(self._cleanup)
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
        self._schedule_refresh(async_add_entities)

    @callback
    def _refresh_known_source_ids(self) -> None:
        """Refresh all registry-known Area sensor candidates."""
        self._known_source_ids = area_entity_ids(
            self.area.hass,
            self.area.hass_config,
            self.area.config,
            domain=SENSOR_DOMAIN,
        )
        self._refresh_source_listener()

    @callback
    def _refresh_source_listener(self) -> None:
        """Listen only to current Area sensor candidates."""
        if self._remove_source_listener is not None:
            self._remove_source_listener()
            self._remove_source_listener = None
        if self._known_source_ids:
            self._remove_source_listener = async_track_state_change_event(
                self.area.hass, sorted(self._known_source_ids), self._state_changed
            )

    @callback
    def _cleanup(self) -> None:
        """Cancel dynamic listeners and pending discovery work."""
        if self._remove_source_listener is not None:
            self._remove_source_listener()
            self._remove_source_listener = None
        if self._remove_refresh_timer is not None:
            self._remove_refresh_timer()
            self._remove_refresh_timer = None

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
        self._schedule_refresh(prune_missing=False)

    @callback
    def _registry_changed(self, _event: Event) -> None:
        """Refresh discovery after registry membership may have changed."""
        self._refresh_known_source_ids()
        self._schedule_refresh(prune_missing=True)

    @callback
    def _schedule_refresh(
        self,
        async_add_entities: AddEntitiesCallback | None = None,
        *,
        prune_missing: bool = False,
    ) -> None:
        """Coalesce registry and metadata bursts into one discovery pass."""
        if async_add_entities is not None:
            self._pending_add_entities = async_add_entities
        self._pending_prune_missing |= prune_missing
        if self._remove_refresh_timer is not None:
            return

        @callback
        def _run(_now=None) -> None:
            self._remove_refresh_timer = None
            add_entities = self._pending_add_entities
            self._pending_add_entities = None
            prune = self._pending_prune_missing
            self._pending_prune_missing = False
            self.async_refresh(add_entities, prune_missing=prune)

        handle = self.area.hass.loop.call_soon(_run)
        self._remove_refresh_timer = handle.cancel

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
    _attr_options = ["off", "on"]

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize the Environment sensor."""
        AdaptiveEntity.__init__(self, area, domain=SENSOR_DOMAIN)
        SensorEntity.__init__(self)
        self._last_public_state: tuple[str, tuple[tuple[str, object], ...]] | None = (
            None
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to assessment transitions."""
        await super().async_added_to_hass()
        assert self.area.environment is not None
        self.async_on_remove(
            self.area.environment.register_listener(self._assessment_changed)
        )
        self._assessment_changed()

    def _build_public_environment_state(
        self, assessment: dict
    ) -> tuple[str, dict[str, object]]:
        """Map the internal assessment to a small qualitative public state."""
        german = str(self.hass.config.language).startswith("de")
        values = {
            "comfortable": "angenehm" if german else "comfortable",
            "cold": "zu kalt" if german else "too cold",
            "cool": "kühl" if german else "cool",
            "warm": "zu warm" if german else "too warm",
            "hot": "zu warm" if german else "too warm",
            "very_hot": "zu warm" if german else "too warm",
            "very_dry": "zu niedrig" if german else "too low",
            "dry": "zu niedrig" if german else "too low",
            "normal": "normal",
            "elevated": "erhöht" if german else "elevated",
            "high": "zu hoch" if german else "too high",
            "very_high": "sehr hoch" if german else "very high",
            "good": "gut" if german else "good",
            "degraded": "eingeschränkt" if german else "limited",
            "poor": "schlecht" if german else "poor",
            "critical": "kritisch" if german else "critical",
            "low": "gering" if german else "low",
        }
        comfort = str(assessment.get("comfort", ""))
        humidity = str(assessment.get("humidity", ""))
        air_quality = str(
            assessment.get("air_quality", assessment.get("pollutant_state", ""))
        )
        pollutant_state = str(assessment.get("pollutant_state", ""))
        mould_risk = str(assessment.get("mould_risk", ""))
        recommendation_codes = [
            str(assessment.get("recommended_action", "none")),
            *[str(action) for action in assessment.get("secondary_actions", [])],
        ]
        recommendations = {
            "none": "Keine Maßnahme nötig" if german else "No action needed",
            "ventilate": "Raum lüften" if german else "Ventilate the room",
            "short_ventilate": (
                "Kurz lüften und Außenluft beachten"
                if german
                else "Ventilate briefly and monitor outdoor air"
            ),
            "close_windows": "Fenster schließen" if german else "Close the windows",
            "cool": "Raum kühlen" if german else "Cool the room",
            "reduce_humidity": (
                "Luftfeuchtigkeit senken" if german else "Reduce humidity"
            ),
            "circulate_air": "Luft bewegen" if german else "Circulate the air",
            "monitor": "Situation beobachten" if german else "Monitor the situation",
            "clean_air": "Luft reinigen" if german else "Clean the air",
        }
        recommendation = next(
            (
                recommendations[code]
                for code in recommendation_codes
                if code in recommendations
            ),
            recommendations["none"],
        )
        notices: list[str] = []
        reason_codes = {str(code) for code in assessment.get("reason_codes", [])}
        notice_map = {
            "humidity_high": (
                "Luftfeuchtigkeit zu hoch" if german else "Humidity too high"
            ),
            "humidity_very_high": (
                "Luftfeuchtigkeit sehr hoch" if german else "Humidity very high"
            ),
            "humidity_dry": (
                "Luftfeuchtigkeit zu niedrig" if german else "Humidity too low"
            ),
            "high_co2": "CO₂ erhöht" if german else "CO₂ elevated",
            "co2_critical": "CO₂ sehr hoch" if german else "CO₂ very high",
            "high_pm25": "Feinstaub erhöht" if german else "PM2.5 elevated",
            "high_pm10": "Feinstaub erhöht" if german else "PM10 elevated",
            "high_voc": "VOC erhöht" if german else "VOC elevated",
            "high_humidity": (
                "Lüften empfohlen: Die Luftfeuchtigkeit ist zu hoch."
                if german
                else "Ventilation recommended: Humidity is too high."
            ),
            "prolonged_high_humidity": (
                "Lüften empfohlen: Die Luftfeuchtigkeit ist anhaltend hoch."
                if german
                else "Ventilation recommended: Humidity has remained high."
            ),
            "rapid_humidity_rise": (
                "Lüften empfohlen: Die Luftfeuchtigkeit steigt schnell."
                if german
                else "Ventilation recommended: Humidity is rising rapidly."
            ),
            "mould_risk_elevated": (
                "Schimmelrisiko erhöht" if german else "Elevated mould risk"
            ),
            "mould_risk_high": "Schimmelrisiko hoch" if german else "High mould risk",
            "primary_temperature_sensor_unavailable": (
                "Temperaturdaten fehlen" if german else "Temperature data missing"
            ),
            "primary_humidity_sensor_unavailable": (
                "Luftfeuchtedaten fehlen" if german else "Humidity data missing"
            ),
        }
        notices.extend(notice_map[code] for code in reason_codes if code in notice_map)
        mitigation_reason_codes = {
            str(code) for code in assessment.get("mitigation_reason_codes", [])
        }
        if "outdoor_air_drier" in mitigation_reason_codes:
            notices.append(
                "Lüften empfohlen: Die Außenluft unterstützt den Feuchteabbau."
                if german
                else "Ventilation recommended: Outdoor air supports moisture removal."
            )
        elif {
            "outdoor_air_more_humid",
            "outdoor_air_quality_unknown",
        } & mitigation_reason_codes:
            notices.append(
                "Lüften derzeit ungünstig: Die Außenluft unterstützt den Feuchteabbau nicht."
                if german
                else "Ventilation is currently unfavorable: Outdoor air does not support moisture removal."
            )
        coverage = assessment.get("air_quality_coverage", {})
        expected = [str(value) for value in coverage.get("expected", [])]
        available = [str(value) for value in coverage.get("available", [])]
        unavailable = [
            str(value) for value in coverage.get("temporarily_unavailable", [])
        ]
        pollutant_names = {
            "co2": "CO₂",
            "pm25": "PM2.5",
            "pm10": "PM10",
            "no2": "NO₂",
            "co": "CO",
            "ozone": "O₃",
            "voc": "VOC",
            "voc_parts": "VOC",
            "pm1": "PM1",
            "aqi": "AQI",
        }

        def _pollutant_list(capabilities: list[str]) -> str:
            labels = [
                pollutant_names.get(capability, capability)
                for capability in capabilities
            ]
            if len(labels) < 2:
                return "".join(labels)
            conjunction = " und " if german else " and "
            return f"{', '.join(labels[:-1])}{conjunction}{labels[-1]}"

        if unavailable and available:
            if german:
                notices.append(
                    "Luftqualität eingeschränkt bewertet: "
                    f"{_pollutant_list(unavailable)} fehlt; Bewertung basiert derzeit "
                    f"auf {_pollutant_list(available)}."
                )
            else:
                notices.append(
                    "Air quality assessed with limited coverage: "
                    f"{_pollutant_list(unavailable)} unavailable; assessment currently "
                    f"based on {_pollutant_list(available)}."
                )
        elif expected and not available:
            if german:
                notices.append(
                    "Luftqualität derzeit nicht bewertbar: "
                    f"{_pollutant_list(expected)} sind nicht verfügbar."
                )
            else:
                notices.append(
                    "Air quality currently unavailable: "
                    f"{_pollutant_list(expected)} are unavailable."
                )
        operation = (
            ("Eingeschränkt" if german else "Limited")
            if any(
                "unavailable" in code or "not_configured" in code
                for code in reason_codes
            )
            else None
        )
        problem = (
            comfort in {"cold", "warm", "hot", "very_hot"}
            or humidity in {"very_dry", "dry", "high", "very_high"}
            or air_quality in {"degraded", "poor", "critical"}
            or pollutant_state in {"elevated", "poor", "critical"}
            or mould_risk in {"elevated", "high"}
            or any(code not in {"none", "monitor"} for code in recommendation_codes)
            or any(
                any(token in code for token in ("high", "critical", "elevated", "poor"))
                for code in reason_codes
            )
        )
        attributes: dict[str, object] = {}
        for key, value in (
            ("comfort", values.get(comfort)),
            ("humidity", values.get(humidity)),
            ("air_quality", values.get(air_quality)),
            ("mould_risk", values.get(mould_risk)),
        ):
            if value is not None:
                attributes[key] = value
        attributes["recommendation"] = recommendation
        if notices:
            attributes["notices"] = sorted(set(notices))
        if operation:
            attributes["operation"] = operation
        used_sensors = self.area.environment.public_used_sensors()
        if used_sensors:
            attributes["used_sensors"] = used_sensors
        return ("on" if problem else "off"), attributes

    def _assessment_changed(self) -> None:
        """Publish only the qualitative, user-facing environment statement."""
        if self.area.environment is None:
            return
        state, attributes = self._build_public_environment_state(
            self.area.environment.assessment
        )
        public = (state, tuple(sorted(attributes.items())))
        if public == self._last_public_state:
            return
        self._last_public_state = public
        self._attr_native_value = state
        self._attr_extra_state_attributes = attributes
        self.async_write_ha_state()
