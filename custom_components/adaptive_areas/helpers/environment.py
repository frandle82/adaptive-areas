"""Capability-aware, deterministic Area Environment evaluation."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math
from statistics import mean
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.unit_conversion import TemperatureConverter

from custom_components.adaptive_areas.const import (
    AREA_TYPE_EXTERIOR,
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_DISABLED_FANS,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_FEATURE_HEALTH,
    CONF_FEATURE_ENVIRONMENT,
    CONF_EXCLUDE_ENTITIES,
    CONF_INCLUDE_ENTITIES,
    CONF_ROOM_CATEGORY,
    DATA_AREA_OBJECT,
    DEFAULT_ENVIRONMENT_HUMIDITY_DURATION,
    DEFAULT_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    DEFAULT_ROOM_CATEGORY,
    MODULE_DATA,
    AdaptiveAreasEvents,
    AirQualityState,
    CirculationFanRequest,
    ComfortState,
    CoolingState,
    EnvironmentState,
    HumidityState,
    MouldRiskState,
    RoomCategory,
    VentilationFanRequest,
    VentilationState,
    WindowRecommendation,
)

MICROGRAMS_PER_CUBIC_METER = "µg/m³"
MILLIGRAMS_PER_CUBIC_METER = "mg/m³"
PARTS_PER_MILLION = "ppm"


@dataclass(frozen=True)
class EvaluationBand:
    """One maintainable operational evaluation matrix row."""

    degraded: float
    poor: float
    critical: float
    unit: str | None
    basis: str


@dataclass(frozen=True)
class ComfortPolicy:
    """Category-reference offsets and anti-flap tolerance."""

    cold_offset: float = -2.0
    warm_offset: float = 2.0
    hot_offset: float = 5.0
    hysteresis: float = 0.3
    basis: str = "Adaptive Areas operational offsets around UBA room references"


@dataclass(frozen=True)
class ThermalProfile:
    """Room-category thermal reference; not a universal comfort standard."""

    reference: float | None
    comfort_relevant: bool
    activity: str
    basis: str = "UBA room-temperature references; AA operational offsets"


@dataclass(frozen=True)
class HumidityPolicy:
    """Operational indoor-moisture bands."""

    very_dry: float = 35.0
    dry: float = 40.0
    normal: float = 60.0
    warning: float = 65.0
    very_high: float = 75.0
    rapid_rise: float = 15.0
    rapid_window_seconds: int = 300
    basis: str = "UBA long-term 65–70% RH guidance; AA operational bands"


@dataclass(frozen=True)
class MouldPolicy:
    """Conservative moisture-persistence indicator policy."""

    elevated_seconds: int = 6 * 60 * 60
    high_seconds: int = 24 * 60 * 60
    surface_warning: float = 80.0
    room_warning: float = 65.0
    basis: str = "UBA 80% surface-RH / 65–70% room-RH guidance; AA persistence"


@dataclass(frozen=True)
class VentilationPolicy:
    """Indoor CO2 ventilation bands and clearing hysteresis."""

    recommended: float = 1000.0
    urgent: float = 2000.0
    clear: float = 850.0
    basis: str = "UBA indoor CO2 hygiene bands"


# Central policies keep every operational boundary and its provenance reviewable.
COMFORT_POLICY = ComfortPolicy()
HUMIDITY_POLICY = HumidityPolicy()
MOULD_POLICY = MouldPolicy()
VENTILATION_POLICY = VentilationPolicy()

THERMAL_PROFILES: dict[RoomCategory, ThermalProfile] = {
    RoomCategory.LIVING_SEDENTARY: ThermalProfile(20.0, True, "sedentary"),
    RoomCategory.SLEEPING_REST: ThermalProfile(17.0, True, "resting"),
    RoomCategory.HYGIENE_WET: ThermalProfile(23.0, True, "hygiene_wet"),
    RoomCategory.ACTIVE_DOMESTIC: ThermalProfile(18.0, True, "active_domestic"),
    RoomCategory.CIRCULATION_TRANSIENT: ThermalProfile(15.0, True, "transient"),
    RoomCategory.SERVICE_STORAGE: ThermalProfile(None, False, "service_storage"),
    RoomCategory.UNCONDITIONED: ThermalProfile(None, False, "unconditioned"),
    RoomCategory.MANUAL: ThermalProfile(20.0, True, "manual"),
}


# WHO values require 24-hour time-weighted exposure. Higher severity multiples are
# explicitly Adaptive Areas operational policy, not additional WHO thresholds.
AIR_QUALITY_MATRIX: dict[SensorDeviceClass, EvaluationBand] = {
    SensorDeviceClass.CO2: EvaluationBand(1000, 2000, 2000, PARTS_PER_MILLION, "UBA"),
    SensorDeviceClass.PM25: EvaluationBand(
        15, 37.5, 75, MICROGRAMS_PER_CUBIC_METER, "WHO-24h"
    ),
    SensorDeviceClass.PM10: EvaluationBand(
        45, 75, 150, MICROGRAMS_PER_CUBIC_METER, "WHO-24h"
    ),
    SensorDeviceClass.CO: EvaluationBand(
        4, 7, 10, MILLIGRAMS_PER_CUBIC_METER, "WHO-24h"
    ),
    SensorDeviceClass.NITROGEN_DIOXIDE: EvaluationBand(
        25, 50, 100, MICROGRAMS_PER_CUBIC_METER, "WHO-24h"
    ),
    SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS: EvaluationBand(
        950, 950, 950, MICROGRAMS_PER_CUBIC_METER, "UBA-TVOC-precaution"
    ),
}

ROLLING_DEVICE_CLASSES = (
    SensorDeviceClass.PM25,
    SensorDeviceClass.PM10,
    SensorDeviceClass.CO,
    SensorDeviceClass.NITROGEN_DIOXIDE,
)
ROLLING_WINDOW = timedelta(hours=24)
ROLLING_MIN_COVERAGE = timedelta(hours=18)

POLLUTANT_NAMES = {
    SensorDeviceClass.CO2: "co2",
    SensorDeviceClass.PM25: "pm25",
    SensorDeviceClass.PM10: "pm10",
    SensorDeviceClass.CO: "co",
    SensorDeviceClass.NITROGEN_DIOXIDE: "no2",
    SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS: "voc",
    SensorDeviceClass.AQI: "aqi",
    SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS: "voc_parts",
}

AIR_QUALITY_RANK = {
    AirQualityState.UNKNOWN: 0,
    AirQualityState.GOOD: 1,
    AirQualityState.DEGRADED: 2,
    AirQualityState.POOR: 3,
    AirQualityState.CRITICAL: 4,
}

CONTEXT: dict[str, dict[str, str]] = {
    "en": {
        "air_critical": "Air quality is critical: {reason}.",
        "air_co2_critical": "Ventilate immediately: the CO₂ concentration is very high.",
        "air_co2_poor": "Ventilation required: the CO₂ concentration is significantly elevated.",
        "health_alert": "An Area health sensor reports a hazard. Address that warning first.",
        "air_poor": "Air quality is poor: {reason}.",
        "ventilation_urgent": "Ventilate immediately: {reason}.",
        "ventilation_required": "Ventilation required: {reason}.",
        "ventilation_recommended": "Ventilation recommended: {reason}.",
        "mould_high": "Mould risk is high because moisture has persisted. This is a risk indicator, not mould detection.",
        "humidity_high": "Ventilation recommended: humidity has remained high.",
        "thermal_hot": "Room feels very warm. {cooling}",
        "window_open": "Open a relevant window: ventilation or passive cooling is recommended.",
        "window_close": "Ventilation demand has cleared; close the open window.",
        "clean_postpone": "Postpone cleaning: room is currently occupied.",
        "clean_preferred": "Room had high recent use and is now clear. Good time for cleaning.",
        "clean_allowed": "Room is clear; cleaning is allowed.",
        "good": "Available environmental measurements are unremarkable.",
        "partial": "Available measurements show no dominant issue; some environmental dimensions cannot be evaluated.",
        "temperature_not_configured": "No primary Area temperature sensor is configured for temperature assessment.",
        "temperature_unavailable": "Temperature assessment is limited: the configured primary Area temperature sensor is currently unavailable.",
        "humidity_not_configured": "No primary Area humidity sensor is configured for humidity assessment.",
        "humidity_unavailable": "Temperature and humidity assessment is limited: the configured primary Area humidity sensor is currently unavailable.",
        "climate_sources_missing": "Temperature and humidity assessment is unavailable: primary Area temperature and humidity sensors are missing.",
        "co2": "CO₂ concentration is elevated",
        "pm25": "PM2.5 concentration is elevated",
        "pm10": "PM10 concentration is elevated",
        "co": "carbon monoxide concentration is elevated",
        "no2": "nitrogen dioxide concentration is elevated",
        "aqi": "reported air quality index is elevated",
        "voc": "standardized VOC concentration is elevated",
        "humidity": "humidity is too high",
        "cool_passive": "Outdoor air is cooler, so ventilation can provide passive cooling.",
        "cool_active": "Outdoor air is not cooler; active cooling may help.",
        "cool_unknown": "Outdoor temperature is unavailable, so cooling advice is limited.",
    },
    "de": {
        "air_critical": "Die Luftqualität ist kritisch: {reason}.",
        "air_co2_critical": "Sofort lüften: Die CO₂-Konzentration ist sehr hoch.",
        "air_co2_poor": "Lüften erforderlich: Die CO₂-Konzentration ist deutlich erhöht.",
        "health_alert": "Ein Gesundheitswarnsensor des Bereichs meldet eine Gefahr. Diese Warnung hat Vorrang.",
        "air_poor": "Die Luftqualität ist schlecht: {reason}.",
        "ventilation_urgent": "Sofort lüften: {reason}.",
        "ventilation_required": "Lüften erforderlich: {reason}.",
        "ventilation_recommended": "Lüften empfohlen: {reason}.",
        "mould_high": "Das Schimmelrisiko ist wegen anhaltender Feuchtigkeit hoch. Dies ist ein Risikoindikator, keine Schimmelerkennung.",
        "humidity_high": "Lüften empfohlen: Die Luftfeuchtigkeit ist anhaltend hoch.",
        "thermal_hot": "Der Raum fühlt sich sehr warm an. {cooling}",
        "window_open": "Ein relevantes Fenster öffnen: Lüftung oder passive Kühlung wird empfohlen.",
        "window_close": "Der Lüftungsbedarf ist beendet; das offene Fenster schließen.",
        "clean_postpone": "Reinigung verschieben: Der Raum wird derzeit genutzt.",
        "clean_preferred": "Der Raum wurde intensiv genutzt und ist jetzt frei. Ein guter Zeitpunkt für die Reinigung.",
        "clean_allowed": "Der Raum ist frei; eine Reinigung ist möglich.",
        "good": "Raumklima im verfügbaren Messumfang unauffällig.",
        "partial": "Die verfügbaren Messwerte zeigen kein vorrangiges Problem; einige Umweltbereiche sind nicht bewertbar.",
        "temperature_not_configured": "Für die Temperaturbewertung ist kein Temperatursensor des Bereichs festgelegt.",
        "temperature_unavailable": "Die Temperaturbewertung ist eingeschränkt: Der festgelegte Temperatursensor des Bereichs ist derzeit nicht verfügbar.",
        "humidity_not_configured": "Für die Feuchtebewertung ist kein Luftfeuchtigkeitssensor des Bereichs festgelegt.",
        "humidity_unavailable": "Temperatur- und Feuchtebewertung eingeschränkt: Der festgelegte Luftfeuchtigkeitssensor ist derzeit nicht verfügbar.",
        "climate_sources_missing": "Temperatur- und Feuchtebewertung nicht verfügbar: Temperatur- und Luftfeuchtigkeitssensor des Bereichs fehlen.",
        "co2": "die CO₂-Konzentration ist erhöht",
        "pm25": "die Feinstaubbelastung PM2,5 ist erhöht",
        "pm10": "die Feinstaubbelastung PM10 ist erhöht",
        "co": "die Kohlenmonoxidkonzentration ist erhöht",
        "no2": "die Stickstoffdioxidkonzentration ist erhöht",
        "aqi": "der gemeldete Luftqualitätsindex ist erhöht",
        "voc": "die standardisierte VOC-Konzentration ist erhöht",
        "humidity": "die Luftfeuchtigkeit ist zu hoch",
        "cool_passive": "Draußen ist es kühler; Lüften kann passiv kühlen.",
        "cool_active": "Draußen ist es nicht kühler; aktive Kühlung kann helfen.",
        "cool_unknown": "Die Außentemperatur fehlt; die Kühlung ist nur eingeschränkt bewertbar.",
    },
}


class AreaEnvironmentEngine:
    """Evaluate Room Climate without controlling devices."""

    def __init__(self, area) -> None:
        """Initialize capability discovery, histories, and listeners."""
        self.area = area
        self.config = dict(area.config)
        # Read RC4 nested values until config-entry migration has persisted them.
        if area.has_feature(CONF_FEATURE_ENVIRONMENT):
            for key, value in area.feature_config(CONF_FEATURE_ENVIRONMENT).items():
                self.config.setdefault(key, value)
        try:
            self.room_category = RoomCategory(
                self.config.get(CONF_ROOM_CATEGORY, DEFAULT_ROOM_CATEGORY)
            )
        except ValueError:
            self.room_category = RoomCategory(DEFAULT_ROOM_CATEGORY)
        self.thermal_profile = THERMAL_PROFILES[self.room_category]
        self._manual_reference_temperature = self.thermal_profile.reference
        self.comfort_min = (
            self.thermal_profile.reference + COMFORT_POLICY.cold_offset
            if self.thermal_profile.reference is not None
            else None
        )
        self.comfort_max = (
            self.thermal_profile.reference + 4.0
            if self.thermal_profile.reference is not None
            else None
        )
        self.cooling_delta = float(
            self.config.get(
                CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
                DEFAULT_ENVIRONMENT_PASSIVE_COOLING_DELTA,
            )
        )
        self.humidity_duration_minutes = int(
            self.config.get(
                CONF_ENVIRONMENT_HUMIDITY_DURATION,
                DEFAULT_ENVIRONMENT_HUMIDITY_DURATION,
            )
        )
        self._excluded_ids = set(self.config.get(CONF_EXCLUDE_ENTITIES, []))
        self.primary_temperature_entity = self.config.get(
            CONF_AREA_TEMPERATURE_SENSOR, ""
        )
        self.primary_humidity_entity = self.config.get(CONF_AREA_HUMIDITY_SENSOR, "")
        self._sensor_ids = self._discover_sensor_ids()
        self._window_ids = self._discover_window_ids()
        self.outdoor_temperature_entity = self.config.get(
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE, ""
        )
        self.outdoor_humidity_entity = self.config.get(
            CONF_ENVIRONMENT_OUTDOOR_HUMIDITY, ""
        )
        self.surface_temperature_entity = self.config.get(
            CONF_ENVIRONMENT_SURFACE_TEMPERATURE, ""
        )
        self.health_entity = (
            f"binary_sensor.adaptive_areas_health_{self.area.slug}"
            if area.has_feature(CONF_FEATURE_HEALTH)
            else ""
        )
        self._humidity_history: deque[tuple[datetime, float]] = deque(maxlen=60)
        self._humidity_warning_since: datetime | None = None
        self._pollutant_history: dict[str, deque[tuple[datetime, datetime, float]]] = {
            str(device_class): deque(maxlen=2048)
            for device_class in ROLLING_DEVICE_CLASSES
        }
        self._last_pollutant_sample: dict[str, tuple[datetime, float | None]] = {}
        self._source_entities: dict[str, dict[str, Any]] = {}
        self._mould_warning_since: datetime | None = None
        self._ventilation_latched = False
        self._had_window_need = False
        self._last_dominant_decision: str | None = None
        self._last_primary_status: dict[str, bool] = {}
        self._last_comfort = ComfortState.UNKNOWN
        self._listeners: list[Callable[[], None]] = []
        self._remove_outdoor_listener: Callable[[], None] | None = None
        self._subscribers: list[Callable[[], None]] = []
        self.assessment: dict[str, Any] = {}
        tracked = {
            entity_id
            for entity_ids in self._sensor_ids.values()
            for entity_id in entity_ids
        } | set(self._window_ids)
        if self.primary_temperature_entity:
            tracked.add(self.primary_temperature_entity)
        if self.primary_humidity_entity:
            tracked.add(self.primary_humidity_entity)
        if self.outdoor_temperature_entity:
            tracked.add(self.outdoor_temperature_entity)
        if self.outdoor_humidity_entity:
            tracked.add(self.outdoor_humidity_entity)
        if self.surface_temperature_entity:
            tracked.add(self.surface_temperature_entity)
        if self.health_entity:
            tracked.add(self.health_entity)
        if tracked:
            self._listeners.append(
                async_track_state_change_event(
                    area.hass, sorted(tracked), self._state_changed
                )
            )
        self._listeners.append(
            async_dispatcher_connect(
                area.hass,
                AdaptiveAreasEvents.AREA_STATE_CHANGED,
                self._area_state_changed,
            )
        )
        self._listeners.append(
            async_dispatcher_connect(
                area.hass,
                AdaptiveAreasEvents.AREA_LOADED,
                self._area_loaded,
            )
        )
        self._refresh_outdoor_listener()
        self.evaluate(trace=False)
        self.area.logger.debug(
            "Primary temperature source: %s",
            self.primary_temperature_entity or "not configured",
        )
        self.area.logger.debug(
            "Primary humidity source: %s",
            self.primary_humidity_entity or "not configured",
        )
        self.area.logger.debug(
            "Pollutant sources: %s",
            {
                POLLUTANT_NAMES[device_class]: entity_ids
                for device_class, entity_ids in (
                    (device_class, self._sensor_ids.get(str(device_class), []))
                    for device_class in POLLUTANT_NAMES
                )
                if entity_ids
            },
        )
        self.area.logger.debug(
            "Evaluated capabilities: %s",
            sorted(
                key for key, value in self.assessment["capabilities"].items() if value
            ),
        )
        self.area.logger.debug(
            "Initial Room Climate state: %s", self.assessment["state"]
        )

    def _exterior_sensor_ids(self) -> list[str]:
        """Return currently eligible automatic exterior temperature/RH sources."""
        explicit = {
            self.outdoor_temperature_entity,
            self.outdoor_humidity_entity,
        }
        result: set[str] = set()
        for runtime in self.area.hass.data.get(MODULE_DATA, {}).values():
            exterior = runtime.get(DATA_AREA_OBJECT)
            if exterior is None or exterior is self.area or not exterior.is_exterior():
                continue
            for entity in exterior.entities.get("sensor", []):
                entity_id = entity[ATTR_ENTITY_ID]
                state = self.area.hass.states.get(entity_id)
                if (
                    entity_id not in self._excluded_ids
                    and entity_id not in explicit
                    and state is not None
                    and state.attributes.get(ATTR_DEVICE_CLASS)
                    in (SensorDeviceClass.TEMPERATURE, SensorDeviceClass.HUMIDITY)
                ):
                    result.add(entity_id)
        return sorted(result)

    def _refresh_outdoor_listener(self) -> None:
        """Refresh automatic-source listeners after exterior Areas load/reload."""
        if self._remove_outdoor_listener is not None:
            self._remove_outdoor_listener()
            self._remove_outdoor_listener = None
        entity_ids = self._exterior_sensor_ids()
        if entity_ids:
            self._remove_outdoor_listener = async_track_state_change_event(
                self.area.hass, entity_ids, self._state_changed
            )

    @callback
    def _area_loaded(
        self,
        area_type: str,
        _floor_id: int | None,
        _area_id: str,
        _initial_load: bool = False,
    ) -> None:
        """Refresh discovery after an exterior Area becomes available."""
        if area_type != AREA_TYPE_EXTERIOR:
            return
        self._refresh_outdoor_listener()
        self.evaluate()

    def _discover_sensor_ids(self) -> dict[str, list[str]]:
        """Discover current pollutant sensors assigned to or included by the Area."""
        supported = set(AIR_QUALITY_MATRIX) | {
            SensorDeviceClass.AQI,
            SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        }
        result = {str(device_class): [] for device_class in supported}
        dedicated_sources = {
            self.config.get(CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE),
            self.config.get(CONF_ENVIRONMENT_OUTDOOR_HUMIDITY),
            self.config.get(CONF_ENVIRONMENT_SURFACE_TEMPERATURE),
        }
        candidate_ids = {
            entity[ATTR_ENTITY_ID] for entity in self.area.entities.get("sensor", [])
        }
        entity_registry = async_get_entity_registry(self.area.hass)
        device_registry = async_get_device_registry(self.area.hass)
        candidate_ids.update(
            entry.entity_id
            for entry in entity_registry.entities.get_entries_for_area_id(self.area.id)
        )
        for device in device_registry.devices.get_devices_for_area_id(self.area.id):
            candidate_ids.update(
                entry.entity_id
                for entry in entity_registry.entities.get_entries_for_device_id(
                    device.id
                )
            )
        candidate_ids.update(self.config.get(CONF_INCLUDE_ENTITIES, []))
        for entity_id in candidate_ids:
            entry = entity_registry.async_get(entity_id)
            if not entity_id.startswith("sensor."):
                continue
            if entry is not None and (
                entry.disabled
                or entry.config_entry_id == self.area.hass_config.entry_id
            ):
                continue
            if entity_id in self._excluded_ids:
                continue
            if entity_id in dedicated_sources:
                continue
            state = self.area.hass.states.get(entity_id)
            if state and state.attributes.get(ATTR_DEVICE_CLASS) in supported:
                result[str(state.attributes[ATTR_DEVICE_CLASS])].append(entity_id)
        for entity_ids in result.values():
            entity_ids.sort()
        return result

    def _primary_value(
        self, entity_id: str, device_class: SensorDeviceClass, source_key: str
    ) -> float | None:
        """Read one configured authoritative indoor source without fallback."""
        source: dict[str, Any] = {
            "mode": "primary",
            "configured": bool(entity_id),
            "available": False,
        }
        if entity_id:
            source.update(self._source_descriptor(entity_id))
        self._source_entities[source_key] = source
        if not entity_id or entity_id in self._excluded_ids:
            return None
        state = self.area.hass.states.get(entity_id)
        if (
            state is None
            or not entity_id.startswith("sensor.")
            or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            or state.attributes.get(ATTR_DEVICE_CLASS) != device_class
        ):
            return None
        try:
            value = float(state.state)
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if (
                device_class == SensorDeviceClass.TEMPERATURE
                and unit
                and unit != UnitOfTemperature.CELSIUS
            ):
                value = TemperatureConverter.convert(
                    value, unit, UnitOfTemperature.CELSIUS
                )
        except TypeError, ValueError:
            return None
        source["available"] = True
        return value

    def _primary_source_reasons(self) -> list[str]:
        """Return stable reason codes for unavailable authoritative inputs."""
        reasons: list[str] = []
        for source_key, entity_id in (
            ("temperature", self.primary_temperature_entity),
            ("humidity", self.primary_humidity_entity),
        ):
            if not entity_id:
                reasons.append(f"primary_{source_key}_sensor_not_configured")
            elif not self._source_entities[source_key]["available"]:
                reasons.append(f"primary_{source_key}_sensor_unavailable")
        return reasons

    def _trace_primary_status(self, *, trace: bool) -> None:
        """Trace source loss/restoration transitions without logging every update."""
        primary_status = {
            key: bool(self._source_entities[key]["available"])
            for key in ("temperature", "humidity")
        }
        if trace and self._last_primary_status:
            for key, available in primary_status.items():
                if available == self._last_primary_status.get(key):
                    continue
                self.area.trace_decision(
                    feature="environment",
                    trigger="primary_environment_source_changed",
                    decision=f"primary_{key}_source_{'restored' if available else 'missing'}",
                    outcome="evaluated",
                    reason_codes=[
                        f"primary_{key}_sensor_{'restored' if available else 'unavailable'}"
                    ],
                )
        self._last_primary_status = primary_status

    def _discover_window_ids(self) -> list[str]:
        explicit = [
            entity_id
            for entity_id in self.config.get(CONF_ENVIRONMENT_WINDOWS, [])
            if entity_id not in self._excluded_ids
        ]
        if explicit:
            return list(dict.fromkeys(explicit))
        return [
            entity[ATTR_ENTITY_ID]
            for entity in self.area.entities.get("binary_sensor", [])
            if entity[ATTR_ENTITY_ID] not in self._excluded_ids
            if (state := self.area.hass.states.get(entity[ATTR_ENTITY_ID])) is not None
            and state.attributes.get(ATTR_DEVICE_CLASS)
            == BinarySensorDeviceClass.WINDOW
        ]

    @callback
    def _state_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.evaluate()

    @callback
    def _area_state_changed(self, area_id: str, _states_tuple) -> None:
        if area_id != self.area.id:
            return
        self.evaluate()

    def register_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an assessment listener and return its unsubscribe callback."""
        self._subscribers.append(listener)

        def remove() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return remove

    def _source_descriptor(self, entity_id: str) -> dict[str, str]:
        state = self.area.hass.states.get(entity_id)
        return {
            "entity_id": entity_id,
            "name": state.name if state is not None else entity_id,
        }

    def _values(self, device_class: SensorDeviceClass) -> list[float]:
        candidate_ids = [*self._sensor_ids.get(str(device_class), [])]
        values: list[float] = []
        used: list[str] = []
        expected_unit = AIR_QUALITY_MATRIX.get(device_class)
        for entity_id in candidate_ids:
            state = self.area.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                continue
            try:
                value = float(state.state)
            except TypeError, ValueError:
                continue
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if device_class == SensorDeviceClass.TEMPERATURE:
                if unit and unit != UnitOfTemperature.CELSIUS:
                    try:
                        value = TemperatureConverter.convert(
                            value, unit, UnitOfTemperature.CELSIUS
                        )
                    except ValueError:
                        continue
            elif expected_unit and unit is not None and expected_unit.unit != unit:
                continue
            values.append(value)
            used.append(entity_id)
        if candidate_ids:
            source_key = POLLUTANT_NAMES.get(device_class, str(device_class))
            self._source_entities[source_key] = {
                "mode": "direct",
                "entities": [
                    self._source_descriptor(entity_id) for entity_id in sorted(used)
                ],
            }
        return values

    def _explicit_value(
        self, entity_id: str, device_class: SensorDeviceClass, source_key: str
    ) -> float | None:
        if not entity_id or entity_id in self._excluded_ids:
            return None
        state = self.area.hass.states.get(entity_id)
        if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                value = float(state.state)
                unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                if (
                    device_class == SensorDeviceClass.TEMPERATURE
                    and unit
                    and unit != UnitOfTemperature.CELSIUS
                ):
                    value = TemperatureConverter.convert(
                        value, unit, UnitOfTemperature.CELSIUS
                    )
                self._source_entities[source_key] = {
                    "mode": "explicit",
                    "entities": [self._source_descriptor(entity_id)],
                }
                return value
            except TypeError, ValueError:
                pass
        self._source_entities[source_key] = {
            "mode": "explicit",
            "entities": [],
        }
        return None

    def _outdoor_value(
        self,
        device_class: SensorDeviceClass,
        explicit_entity: str,
        source_key: str,
    ) -> float | None:
        if explicit_entity:
            return self._explicit_value(explicit_entity, device_class, source_key)
        values: list[float] = []
        used: list[str] = []
        for runtime in self.area.hass.data.get(MODULE_DATA, {}).values():
            exterior = runtime.get(DATA_AREA_OBJECT)
            if exterior is None or exterior is self.area or not exterior.is_exterior():
                continue
            for entity in exterior.entities.get("sensor", []):
                entity_id = entity[ATTR_ENTITY_ID]
                if entity_id in self._excluded_ids:
                    continue
                state = self.area.hass.states.get(entity_id)
                if not state or state.attributes.get(ATTR_DEVICE_CLASS) != device_class:
                    continue
                try:
                    value = float(state.state)
                    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                    if (
                        device_class == SensorDeviceClass.TEMPERATURE
                        and unit
                        and unit != UnitOfTemperature.CELSIUS
                    ):
                        value = TemperatureConverter.convert(
                            value, unit, UnitOfTemperature.CELSIUS
                        )
                    values.append(value)
                    used.append(entity_id)
                except TypeError, ValueError:
                    continue
        self._source_entities[source_key] = {
            "mode": "exterior_area_mean",
            "entities": [
                self._source_descriptor(entity_id) for entity_id in sorted(used)
            ],
        }
        return mean(values) if values else None

    def _outdoor_temperature(self) -> float | None:
        return self._outdoor_value(
            SensorDeviceClass.TEMPERATURE,
            self.outdoor_temperature_entity,
            "outdoor_temperature",
        )

    def _outdoor_humidity(self) -> float | None:
        return self._outdoor_value(
            SensorDeviceClass.HUMIDITY,
            self.outdoor_humidity_entity,
            "outdoor_humidity",
        )

    def _surface_temperature(self) -> float | None:
        return self._explicit_value(
            self.surface_temperature_entity,
            SensorDeviceClass.TEMPERATURE,
            "surface_temperature",
        )

    @staticmethod
    def _dew_point(temperature: float, humidity: float) -> float:
        """Magnus approximation, valid for ordinary indoor conditions."""
        humidity = min(100.0, max(0.1, humidity))
        alpha = math.log(humidity / 100.0) + (17.62 * temperature) / (
            243.12 + temperature
        )
        return 243.12 * alpha / (17.62 - alpha)

    @staticmethod
    def _humidex(temperature: float, dew_point: float) -> float:
        """Calculate the published Canadian humidex."""
        vapour_pressure = 6.11 * math.exp(
            5417.753 * (1 / 273.15 - 1 / (dew_point + 273.15))
        )
        return temperature + 0.5555 * (vapour_pressure - 10)

    @staticmethod
    def _vapour_pressure(temperature: float, humidity: float) -> float:
        """Return water-vapour partial pressure in hPa (Magnus equation)."""
        saturation = 6.112 * math.exp(17.62 * temperature / (243.12 + temperature))
        return saturation * min(100.0, max(0.0, humidity)) / 100.0

    @classmethod
    def _absolute_humidity(cls, temperature: float, humidity: float) -> float:
        """Return absolute humidity in g/m³."""
        return (
            216.7 * cls._vapour_pressure(temperature, humidity) / (temperature + 273.15)
        )

    @classmethod
    def _humidity_ratio(cls, temperature: float, humidity: float) -> float:
        """Return humidity ratio in g water/kg dry air at standard pressure."""
        vapour_pressure = cls._vapour_pressure(temperature, humidity)
        return 1000 * 0.62198 * vapour_pressure / (1013.25 - vapour_pressure)

    @classmethod
    def _enthalpy(cls, temperature: float, humidity: float) -> float:
        """Return moist-air specific enthalpy in kJ/kg dry air."""
        ratio = cls._humidity_ratio(temperature, humidity) / 1000
        return 1.006 * temperature + ratio * (2501 + 1.86 * temperature)

    @classmethod
    def _surface_humidity(
        cls, room_temperature: float, humidity: float, surface_temperature: float
    ) -> float:
        """Estimate surface RH from room vapour pressure and surface temperature."""
        vapour_pressure = cls._vapour_pressure(room_temperature, humidity)
        saturation = cls._vapour_pressure(surface_temperature, 100.0)
        return min(100.0, max(0.0, 100 * vapour_pressure / saturation))

    def _comfort(
        self, temperature: float | None, humidity: float | None
    ) -> tuple[ComfortState, str, float | None, float | None]:
        if not self.thermal_profile.comfort_relevant:
            return ComfortState.NOT_APPLICABLE, "not_applicable", None, None
        if temperature is None:
            return ComfortState.UNKNOWN, "unknown", None, None
        dew_point = (
            self._dew_point(temperature, humidity) if humidity is not None else None
        )
        humidex = (
            self._humidex(temperature, dew_point) if dew_point is not None else None
        )
        quality = "enhanced" if humidity is not None else "basic"
        assert self.comfort_min is not None
        assert self.comfort_max is not None
        if temperature < self.comfort_min + COMFORT_POLICY.cold_offset:
            comfort = ComfortState.COLD
        elif temperature < self.comfort_min:
            comfort = ComfortState.COOL
        elif temperature <= self.comfort_max:
            comfort = ComfortState.COMFORTABLE
        elif temperature <= self.comfort_max + COMFORT_POLICY.warm_offset:
            comfort = ComfortState.WARM
        elif temperature < self.comfort_max + COMFORT_POLICY.hot_offset:
            comfort = ComfortState.HOT
        else:
            comfort = ComfortState.VERY_HOT
        boundaries = (
            self.comfort_min + COMFORT_POLICY.cold_offset,
            self.comfort_min,
            self.comfort_max,
            self.comfort_max + COMFORT_POLICY.warm_offset,
            self.comfort_max + COMFORT_POLICY.hot_offset,
        )
        if self._last_comfort != ComfortState.UNKNOWN and any(
            abs(temperature - boundary) <= COMFORT_POLICY.hysteresis
            for boundary in boundaries
        ):
            comfort = self._last_comfort
        self._last_comfort = comfort
        return comfort, quality, dew_point, humidex

    @staticmethod
    def _humidity(value: float | None) -> HumidityState:
        if value is None:
            return HumidityState.UNKNOWN
        if value < HUMIDITY_POLICY.very_dry:
            return HumidityState.VERY_DRY
        if value < HUMIDITY_POLICY.dry:
            return HumidityState.DRY
        if value <= HUMIDITY_POLICY.normal:
            return HumidityState.NORMAL
        if value <= HUMIDITY_POLICY.warning:
            return HumidityState.ELEVATED
        if value <= HUMIDITY_POLICY.very_high:
            return HumidityState.HIGH
        return HumidityState.VERY_HIGH

    def _humidity_signals(self, value: float | None) -> tuple[bool, bool, float]:
        if value is None:
            self._humidity_warning_since = None
            return False, False, 0.0
        now = datetime.now(UTC)
        self._humidity_history.append((now, value))
        while (
            self._humidity_history
            and (now - self._humidity_history[0][0]).total_seconds()
            > HUMIDITY_POLICY.rapid_window_seconds
        ):
            self._humidity_history.popleft()
        rapid = (
            len(self._humidity_history) > 1
            and value - self._humidity_history[0][1] >= HUMIDITY_POLICY.rapid_rise
        )
        if value >= HUMIDITY_POLICY.warning:
            self._humidity_warning_since = self._humidity_warning_since or now
        elif value < HUMIDITY_POLICY.normal:
            self._humidity_warning_since = None
        duration = (
            (now - self._humidity_warning_since).total_seconds()
            if self._humidity_warning_since
            else 0.0
        )
        return duration >= self.humidity_duration_minutes * 60, rapid, duration

    def _mould_risk(
        self,
        temperature: float | None,
        humidity: float | None,
        surface_humidity: float | None,
    ) -> tuple[MouldRiskState, str, float]:
        if temperature is None or humidity is None:
            self._mould_warning_since = None
            return MouldRiskState.UNKNOWN, "unknown", 0.0
        quality = (
            "surface_based" if surface_humidity is not None else "room_air_estimate"
        )
        proxy = surface_humidity if surface_humidity is not None else humidity
        warning = (
            MOULD_POLICY.surface_warning
            if surface_humidity is not None
            else MOULD_POLICY.room_warning
        )
        clear = warning - 5
        now = datetime.now(UTC)
        if proxy >= warning:
            self._mould_warning_since = self._mould_warning_since or now
        elif proxy < clear:
            self._mould_warning_since = None
        duration = (
            (now - self._mould_warning_since).total_seconds()
            if self._mould_warning_since
            else 0.0
        )
        if duration >= MOULD_POLICY.high_seconds:
            return MouldRiskState.HIGH, quality, duration
        if duration >= MOULD_POLICY.elevated_seconds:
            return MouldRiskState.ELEVATED, quality, duration
        return MouldRiskState.LOW, quality, duration

    @staticmethod
    def _classify_air_value(value: float, band: EvaluationBand) -> AirQualityState:
        if value <= band.degraded:
            return AirQualityState.GOOD
        if value <= band.poor:
            return AirQualityState.DEGRADED
        if value <= band.critical:
            return AirQualityState.POOR
        return AirQualityState.CRITICAL

    def _rolling_pollutant(
        self, device_class: SensorDeviceClass, value: float | None
    ) -> tuple[float | None, float]:
        key = str(device_class)
        now = datetime.now(UTC)
        history = self._pollutant_history[key]
        previous = self._last_pollutant_sample.get(key)
        if previous is not None and previous[0] < now and previous[1] is not None:
            start, previous_value = previous
            if history and history[-1][2] == previous_value and history[-1][1] == start:
                segment_start, _, _ = history.pop()
                history.append((segment_start, now, previous_value))
            else:
                history.append((start, now, previous_value))
        self._last_pollutant_sample[key] = (now, value)
        cutoff = now - ROLLING_WINDOW
        while history and history[0][1] <= cutoff:
            history.popleft()
        weighted = 0.0
        coverage = 0.0
        for start, end, sample in history:
            overlap_start = max(start, cutoff)
            seconds = max(0.0, (min(end, now) - overlap_start).total_seconds())
            weighted += sample * seconds
            coverage += seconds
        return (weighted / coverage if coverage else None, coverage / 3600)

    def _air_quality(
        self,
    ) -> tuple[AirQualityState, dict[str, float], dict[str, Any], list[str]]:
        worst = AirQualityState.UNKNOWN
        measurements: dict[str, float] = {}
        assessments: dict[str, Any] = {}
        reasons: list[str] = []
        limited_coverage = False
        for device_class, band in AIR_QUALITY_MATRIX.items():
            values = self._values(device_class)
            current = max(values) if values else None
            if current is None:
                if device_class in ROLLING_DEVICE_CLASSES and self._sensor_ids.get(
                    str(device_class)
                ):
                    # Close a real source's previous interval during an outage,
                    # but never create history or assessments for absent types.
                    self._rolling_pollutant(device_class, None)
                continue
            name = POLLUTANT_NAMES[device_class]
            measurements[name] = round(current, 2)
            if device_class in ROLLING_DEVICE_CLASSES:
                value, coverage = self._rolling_pollutant(device_class, current)
                quality = (
                    "sufficient"
                    if coverage >= ROLLING_MIN_COVERAGE.total_seconds() / 3600
                    else "limited"
                )
                assessments[name] = {
                    "current": round(current, 2) if current is not None else None,
                    "rolling_24h": round(value, 2) if value is not None else None,
                    "coverage_hours": round(coverage, 2),
                    "quality": quality,
                    "basis": band.basis,
                    "basis_type": "scientific_guideline",
                }
                if quality == "limited" or value is None:
                    limited_coverage = True
                    continue
            elif device_class == SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS:
                state = (
                    AirQualityState.DEGRADED
                    if current > band.degraded
                    else AirQualityState.UNKNOWN
                )
                assessments[name] = {
                    "current": round(current, 2),
                    "quality": "precaution_indicator",
                    "basis": band.basis,
                    "basis_type": "precaution_indicator",
                }
                if state == AirQualityState.DEGRADED:
                    reasons.append("high_voc")
                if AIR_QUALITY_RANK[state] > AIR_QUALITY_RANK[worst]:
                    worst = state
                continue
            else:
                value = current
            state = self._classify_air_value(value, band)
            assessments.setdefault(
                name,
                {
                    "current": round(current, 2) if current is not None else None,
                    "quality": "immediate",
                    "basis": band.basis,
                    "basis_type": "scientific_guideline",
                },
            )
            if state in (
                AirQualityState.DEGRADED,
                AirQualityState.POOR,
                AirQualityState.CRITICAL,
            ):
                reasons.append(f"high_{name}")
            if AIR_QUALITY_RANK[state] > AIR_QUALITY_RANK[worst]:
                worst = state
        for device_class, name in (
            (SensorDeviceClass.AQI, "aqi"),
            (SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS, "voc_parts"),
        ):
            values = self._values(device_class)
            if values:
                measurements[name] = round(max(values), 2)
                assessments[name] = {
                    "current": round(max(values), 2),
                    "quality": "unsupported_scale",
                    "basis_type": "unclassified",
                }
        if limited_coverage and worst == AirQualityState.GOOD:
            worst = AirQualityState.UNKNOWN
        return worst, measurements, assessments, reasons

    def _ventilation(
        self, co2: float | None, humidity: float | None, sustained: bool, rapid: bool
    ) -> tuple[VentilationState, list[str]]:
        reasons: list[str] = []
        state = VentilationState.UNKNOWN
        if co2 is not None:
            if co2 > VENTILATION_POLICY.urgent:
                state, reasons = VentilationState.URGENT, ["very_high_co2"]
            elif co2 > VENTILATION_POLICY.recommended:
                state, reasons = VentilationState.RECOMMENDED, ["high_co2"]
            elif self._ventilation_latched and co2 >= VENTILATION_POLICY.clear:
                state, reasons = VentilationState.RECOMMENDED, ["co2_hysteresis"]
            else:
                state = VentilationState.NOT_REQUIRED
        if humidity is not None and (
            humidity > HUMIDITY_POLICY.very_high or sustained or rapid
        ):
            reasons.extend(
                code
                for code, active in (
                    ("high_humidity", humidity > HUMIDITY_POLICY.very_high),
                    ("prolonged_high_humidity", sustained),
                    ("rapid_humidity_rise", rapid),
                )
                if active
            )
            candidate = (
                VentilationState.REQUIRED
                if humidity > HUMIDITY_POLICY.very_high or rapid
                else VentilationState.RECOMMENDED
            )
            if self._ventilation_rank(candidate) > self._ventilation_rank(state):
                state = candidate
        self._ventilation_latched = state in (
            VentilationState.RECOMMENDED,
            VentilationState.REQUIRED,
            VentilationState.URGENT,
        )
        if self._ventilation_latched and self.windows_open:
            state = VentilationState.VENTILATING
            reasons.append("window_already_open")
        return state, list(dict.fromkeys(reasons))

    @staticmethod
    def _ventilation_rank(state: VentilationState) -> int:
        return {
            VentilationState.UNKNOWN: 0,
            VentilationState.NOT_REQUIRED: 1,
            VentilationState.RECOMMENDED: 2,
            VentilationState.VENTILATING: 3,
            VentilationState.REQUIRED: 4,
            VentilationState.URGENT: 5,
        }[state]

    @property
    def windows_open(self) -> bool:
        """Return whether any relevant window is open."""
        return any(
            (state := self.area.hass.states.get(entity_id)) is not None
            and state.state == STATE_ON
            for entity_id in self._window_ids
        )

    def _context(self, assessment: dict[str, Any]) -> tuple[str, str]:
        language = (
            "de" if str(self.area.hass.config.language).startswith("de") else "en"
        )
        text = CONTEXT[language]
        air_quality = assessment["air_quality"]
        reasons = assessment["reason_codes"]
        reason_map = {
            "high_co2": "co2",
            "very_high_co2": "co2",
            "high_pm25": "pm25",
            "high_pm10": "pm10",
            "high_co": "co",
            "high_no2": "no2",
            "high_aqi": "aqi",
            "high_voc": "voc",
        }
        dominant_reason = next(
            (reason_map[reason] for reason in reasons if reason in reason_map),
            "humidity",
        )
        if assessment["health_alert"]:
            return "health_alert", text["health_alert"]
        if air_quality == AirQualityState.CRITICAL:
            if dominant_reason == "co2":
                return "air_quality_critical", text["air_co2_critical"]
            return "air_quality_critical", text["air_critical"].format(
                reason=text[dominant_reason]
            )
        if air_quality == AirQualityState.POOR:
            if dominant_reason == "co2":
                return "air_quality_poor", text["air_co2_poor"]
            return "air_quality_poor", text["air_poor"].format(
                reason=text[dominant_reason]
            )
        if assessment["ventilation"] == VentilationState.URGENT:
            return "ventilation_urgent", text["ventilation_urgent"].format(
                reason=text[dominant_reason]
            )
        if assessment["ventilation"] == VentilationState.REQUIRED:
            return "ventilation_required", text["ventilation_required"].format(
                reason=text[dominant_reason]
            )
        if assessment["mould_risk"] == MouldRiskState.HIGH:
            return "mould_risk_high", text["mould_high"]
        if assessment["ventilation"] in (
            VentilationState.RECOMMENDED,
            VentilationState.VENTILATING,
        ):
            return "ventilation_recommended", text["ventilation_recommended"].format(
                reason=text[dominant_reason]
            )
        if any(
            reason.startswith("primary_temperature_sensor_") for reason in reasons
        ) and any(reason.startswith("primary_humidity_sensor_") for reason in reasons):
            return "primary_climate_sources_missing", text["climate_sources_missing"]
        for reason, context_key in (
            (
                "primary_temperature_sensor_not_configured",
                "temperature_not_configured",
            ),
            (
                "primary_temperature_sensor_unavailable",
                "temperature_unavailable",
            ),
            ("primary_humidity_sensor_not_configured", "humidity_not_configured"),
            ("primary_humidity_sensor_unavailable", "humidity_unavailable"),
        ):
            if reason in reasons:
                return reason, text[context_key]
        if "prolonged_high_humidity" in reasons:
            return "humidity_persistent", text["humidity_high"]
        if assessment["comfort"] in (ComfortState.HOT, ComfortState.VERY_HOT):
            cooling_key = {
                CoolingState.PASSIVE_RECOMMENDED: "cool_passive",
                CoolingState.ACTIVE_RECOMMENDED: "cool_active",
            }.get(assessment["cooling"], "cool_unknown")
            return "thermal_discomfort", text["thermal_hot"].format(
                cooling=text[cooling_key]
            )
        if assessment["window_recommendation"] == WindowRecommendation.OPEN:
            return "window_open_recommended", text["window_open"]
        if assessment["window_recommendation"] == WindowRecommendation.CLOSE:
            return "window_close_recommended", text["window_close"]
        capabilities = assessment["capabilities"]
        if all(
            capabilities.get(key) for key in ("temperature", "humidity", "air_quality")
        ):
            return "environment_good", text["good"]
        return "environment_partial", text["partial"]

    def _cooling_recommendation(
        self,
        temperature: float | None,
        comfort: ComfortState,
        outdoor: float | None,
        enthalpy: float | None,
        outdoor_enthalpy: float | None,
    ) -> tuple[CoolingState, list[str]]:
        """Return cooling advice limited to available windows and fans."""
        if not self.thermal_profile.comfort_relevant:
            return CoolingState.NOT_REQUIRED, []
        if temperature is None:
            return CoolingState.UNKNOWN, []
        if comfort not in (
            ComfortState.WARM,
            ComfortState.HOT,
            ComfortState.VERY_HOT,
        ):
            return CoolingState.NOT_REQUIRED, []
        if outdoor is None:
            return CoolingState.UNKNOWN, ["room_too_warm"]
        outdoor_cooler = outdoor <= temperature - self.cooling_delta
        passive_cooling_suitable = outdoor_cooler
        moisture_penalty = False
        if passive_cooling_suitable and self._window_ids:
            if (
                enthalpy is not None
                and outdoor_enthalpy is not None
                and outdoor_enthalpy >= enthalpy
            ):
                passive_cooling_suitable = False
                moisture_penalty = True
            else:
                return CoolingState.PASSIVE_RECOMMENDED, [
                    "room_too_warm",
                    "outdoor_air_cooler",
                    "passive_cooling_available",
                ]
        if self.ventilation_fans or self.circulation_fans:
            return CoolingState.ACTIVE_RECOMMENDED, [
                "room_too_warm",
                ("outdoor_air_cooler" if outdoor_cooler else "outdoor_air_warmer"),
                *(["outdoor_air_moisture_penalty"] if moisture_penalty else []),
                "active_cooling_recommended",
            ]
        return CoolingState.UNKNOWN, ["room_too_warm"]

    def set_manual_reference_temperature(self, value: float) -> None:
        """Apply a restored or user-selected manual thermal reference."""
        if self.room_category != RoomCategory.MANUAL:
            return
        self._manual_reference_temperature = value
        self.comfort_min = value + COMFORT_POLICY.cold_offset
        self.comfort_max = value + 4.0
        self.evaluate()

    def evaluate(self, *, trace: bool = True) -> None:
        """Evaluate all available dimensions and notify subscribers."""
        self._source_entities = {}
        temperature = self._primary_value(
            self.primary_temperature_entity,
            SensorDeviceClass.TEMPERATURE,
            "temperature",
        )
        humidity = self._primary_value(
            self.primary_humidity_entity,
            SensorDeviceClass.HUMIDITY,
            "humidity",
        )
        comfort, comfort_quality, dew_point, humidex = self._comfort(
            temperature, humidity
        )
        absolute_humidity = (
            self._absolute_humidity(temperature, humidity)
            if temperature is not None and humidity is not None
            else None
        )
        humidity_ratio = (
            self._humidity_ratio(temperature, humidity)
            if temperature is not None and humidity is not None
            else None
        )
        enthalpy = (
            self._enthalpy(temperature, humidity)
            if temperature is not None and humidity is not None
            else None
        )
        surface_temperature = self._surface_temperature()
        surface_humidity = (
            self._surface_humidity(temperature, humidity, surface_temperature)
            if temperature is not None
            and humidity is not None
            and surface_temperature is not None
            else None
        )
        humidity_state = self._humidity(humidity)
        sustained, rapid, humidity_duration = self._humidity_signals(humidity)
        mould_risk, mould_quality, mould_duration = self._mould_risk(
            temperature, humidity, surface_humidity
        )
        air_quality, pollutants, pollutant_assessments, air_reasons = (
            self._air_quality()
        )
        co2_values = self._values(SensorDeviceClass.CO2)
        co2 = max(co2_values) if co2_values else None
        ventilation, ventilation_reasons = self._ventilation(
            co2, humidity, sustained, rapid
        )
        outdoor = self._outdoor_temperature()
        outdoor_humidity = self._outdoor_humidity()
        outdoor_humidity_ratio = (
            self._humidity_ratio(outdoor, outdoor_humidity)
            if outdoor is not None and outdoor_humidity is not None
            else None
        )
        outdoor_enthalpy = (
            self._enthalpy(outdoor, outdoor_humidity)
            if outdoor is not None and outdoor_humidity is not None
            else None
        )
        reasons = [*air_reasons, *ventilation_reasons]
        reasons.extend(self._primary_source_reasons())
        if mould_risk == MouldRiskState.ELEVATED:
            reasons.append("mould_risk_elevated")
        elif mould_risk == MouldRiskState.HIGH:
            reasons.append("mould_risk_high")

        cooling, cooling_reasons = self._cooling_recommendation(
            temperature, comfort, outdoor, enthalpy, outdoor_enthalpy
        )
        reasons.extend(cooling_reasons)

        ventilation_need = ventilation in (
            VentilationState.RECOMMENDED,
            VentilationState.REQUIRED,
            VentilationState.URGENT,
            VentilationState.VENTILATING,
        )
        humidity_ventilation = any(
            reason
            in {"high_humidity", "prolonged_high_humidity", "rapid_humidity_rise"}
            for reason in ventilation_reasons
        )
        co2_ventilation = any(
            reason in {"high_co2", "very_high_co2", "co2_hysteresis"}
            for reason in ventilation_reasons
        )
        moisture_ventilation = "unknown"
        if humidity_ratio is not None and outdoor_humidity_ratio is not None:
            moisture_ventilation = (
                "favorable"
                if outdoor_humidity_ratio < humidity_ratio
                else "unfavorable"
            )
            reasons.append(
                "outdoor_air_drier"
                if moisture_ventilation == "favorable"
                else "outdoor_air_more_humid"
            )
        air_exchange_suitable = (
            co2_ventilation
            or not humidity_ventilation
            or moisture_ventilation != "unfavorable"
        )
        window = WindowRecommendation.NONE
        if self._window_ids and (
            (ventilation_need and air_exchange_suitable)
            or cooling == CoolingState.PASSIVE_RECOMMENDED
        ):
            self._had_window_need = True
            window = (
                WindowRecommendation.NONE
                if self.windows_open
                else WindowRecommendation.OPEN
            )
            if not self.windows_open:
                reasons.append("window_closed")
        elif self.windows_open and self._had_window_need:
            window = WindowRecommendation.CLOSE
            reasons.append("ventilation_complete")
        elif ventilation_need and not air_exchange_suitable:
            window = WindowRecommendation.KEEP_CLOSED
            reasons.append("outdoor_air_more_humid")
        elif (
            temperature is not None
            and outdoor is not None
            and self.comfort_max is not None
            and temperature > self.comfort_max
            and outdoor > temperature
        ):
            window = WindowRecommendation.KEEP_CLOSED
            self._had_window_need = False
        elif not self.windows_open:
            self._had_window_need = False

        ventilation_request = VentilationFanRequest.NONE
        if self.ventilation_fans:
            if (
                ventilation in (VentilationState.REQUIRED, VentilationState.URGENT)
                or rapid
                or any(
                    reason in {"very_high_co2", "high_humidity", "rapid_humidity_rise"}
                    for reason in reasons
                )
            ):
                ventilation_request = VentilationFanRequest.HIGH
            elif ventilation in (
                VentilationState.RECOMMENDED,
                VentilationState.VENTILATING,
            ):
                ventilation_request = VentilationFanRequest.LOW
        if humidity_ventilation and not co2_ventilation and not air_exchange_suitable:
            ventilation_request = VentilationFanRequest.NONE

        circulation_request = CirculationFanRequest.NONE
        if self.area.is_occupied():
            circulation_request = {
                ComfortState.WARM: CirculationFanRequest.LOW,
                ComfortState.HOT: CirculationFanRequest.MEDIUM,
                ComfortState.VERY_HOT: CirculationFanRequest.HIGH,
            }.get(comfort, CirculationFanRequest.NONE)

        health_state = (
            self.area.hass.states.get(self.health_entity)
            if self.health_entity
            else None
        )
        health_alert = bool(health_state and health_state.state == STATE_ON)
        if health_alert:
            reasons.append("health_alert")
        critical = (
            health_alert
            or air_quality == AirQualityState.CRITICAL
            or ventilation == VentilationState.URGENT
        )
        required = (
            air_quality == AirQualityState.POOR
            or ventilation == VentilationState.REQUIRED
            or mould_risk == MouldRiskState.HIGH
        )
        attention = (
            air_quality == AirQualityState.DEGRADED
            or ventilation
            in (VentilationState.RECOMMENDED, VentilationState.VENTILATING)
            or mould_risk == MouldRiskState.ELEVATED
            or humidity_state
            in (HumidityState.ELEVATED, HumidityState.HIGH, HumidityState.VERY_HIGH)
            or comfort
            not in (
                ComfortState.COMFORTABLE,
                ComfortState.NOT_APPLICABLE,
                ComfortState.UNKNOWN,
            )
        )
        evaluated_dimensions = {
            "comfort": comfort
            not in (ComfortState.UNKNOWN, ComfortState.NOT_APPLICABLE),
            "humidity": humidity_state != HumidityState.UNKNOWN,
            "mould": mould_risk != MouldRiskState.UNKNOWN,
            "air_quality": air_quality != AirQualityState.UNKNOWN,
            "ventilation": ventilation != VentilationState.UNKNOWN,
            "cooling": cooling != CoolingState.UNKNOWN,
        }
        overall = (
            EnvironmentState.ACTION_REQUIRED
            if critical or required
            else (
                EnvironmentState.ATTENTION
                if attention
                else (
                    EnvironmentState.GOOD
                    if any(evaluated_dimensions.values())
                    else EnvironmentState.UNKNOWN
                )
            )
        )
        capabilities = {
            "temperature": temperature is not None,
            "humidity": humidity is not None,
            "co2": "co2" in pollutants,
            "pm25": "pm25" in pollutants,
            "pm10": "pm10" in pollutants,
            "voc": "voc" in pollutants,
            "aqi": "aqi" in pollutants,
            "co": "co" in pollutants,
            "no2": "no2" in pollutants,
            "air_quality": bool(pollutants),
            "windows": bool(self._window_ids),
            "ventilation_fans": bool(self.ventilation_fans),
            "outdoor_temperature": outdoor is not None,
            "outdoor_humidity": outdoor_humidity is not None,
            "surface_temperature": surface_temperature is not None,
            "health": health_state is not None,
        }
        assessment = {
            "state": overall,
            "room_category": self.room_category,
            "thermal_profile": {
                "reference_temperature": self._manual_reference_temperature,
                "activity": self.thermal_profile.activity,
                "basis": self.thermal_profile.basis,
                "basis_type": "scientific_reference_with_operational_offsets",
            },
            "comfort": comfort,
            "comfort_confidence": comfort_quality,
            "thermal_input_quality": (
                "enhanced"
                if temperature is not None and humidity is not None
                else "basic" if temperature is not None else "unavailable"
            ),
            "humidity": humidity_state,
            "mould_risk": mould_risk,
            "air_quality": air_quality,
            "ventilation": ventilation,
            "cooling": cooling,
            "temperature": round(temperature, 2) if temperature is not None else None,
            "relative_humidity": round(humidity, 2) if humidity is not None else None,
            "dew_point": round(dew_point, 2) if dew_point is not None else None,
            "absolute_humidity": (
                round(absolute_humidity, 2) if absolute_humidity is not None else None
            ),
            "humidity_ratio": (
                round(humidity_ratio, 2) if humidity_ratio is not None else None
            ),
            "enthalpy": round(enthalpy, 2) if enthalpy is not None else None,
            "humidex": round(humidex, 2) if humidex is not None else None,
            "apparent_temperature": (
                round(humidex, 2) if humidex is not None else None
            ),
            "mould_quality": mould_quality,
            "mould_warning_duration_seconds": int(mould_duration),
            "outdoor_temperature": round(outdoor, 2) if outdoor is not None else None,
            "outdoor_relative_humidity": (
                round(outdoor_humidity, 2) if outdoor_humidity is not None else None
            ),
            "outdoor_humidity_ratio": (
                round(outdoor_humidity_ratio, 2)
                if outdoor_humidity_ratio is not None
                else None
            ),
            "outdoor_enthalpy": (
                round(outdoor_enthalpy, 2) if outdoor_enthalpy is not None else None
            ),
            "moisture_ventilation": moisture_ventilation,
            "pollutants": pollutants,
            "pollutant_assessments": pollutant_assessments,
            "source_entities": dict(self._source_entities),
            "window_recommendation": window,
            "ventilation_fan_request": ventilation_request,
            "circulation_fan_request": circulation_request,
            "capabilities": capabilities,
            "evaluated_dimensions": sorted(
                key for key, evaluated in evaluated_dimensions.items() if evaluated
            ),
            "health_alert": health_alert,
            "reason_codes": list(dict.fromkeys(reasons)),
            "humidity_warning_duration_seconds": int(humidity_duration),
        }
        if surface_temperature is not None:
            assessment["surface_temperature"] = round(surface_temperature, 2)
        if surface_humidity is not None:
            assessment["surface_relative_humidity"] = round(surface_humidity, 2)
        dominant_decision, context = self._context(assessment)
        assessment["dominant_decision"] = dominant_decision
        assessment["context"] = context
        self.assessment = assessment
        self._trace_primary_status(trace=trace)
        if trace and dominant_decision != self._last_dominant_decision:
            self.area.trace_decision(
                feature="environment",
                trigger="area_input_changed",
                decision=dominant_decision,
                outcome="evaluated",
                reason_codes=assessment["reason_codes"],
            )
        self._last_dominant_decision = dominant_decision
        for subscriber in list(self._subscribers):
            subscriber()

    @property
    def ventilation_fans(self) -> list[str]:
        """Return fans explicitly configured for outdoor-air exchange."""
        return list(self.config.get(CONF_ENVIRONMENT_VENTILATION_FANS, []))

    @property
    def uses_fan_requests(self) -> bool:
        """Return whether explicit Room Climate fan roles opt into requests."""
        return bool(
            self.config.get(CONF_ENVIRONMENT_VENTILATION_FANS)
            or self.config.get(CONF_ENVIRONMENT_CIRCULATION_FANS)
        )

    @property
    def circulation_fans(self) -> list[str]:
        """Return fans classified for indoor-air circulation."""
        explicit = list(self.config.get(CONF_ENVIRONMENT_CIRCULATION_FANS, []))
        if explicit:
            return explicit
        disabled = set(self.config.get(CONF_ENVIRONMENT_DISABLED_FANS, []))
        return [
            entity[ATTR_ENTITY_ID]
            for entity in self.area.entities.get("fan", [])
            if entity[ATTR_ENTITY_ID] not in self.ventilation_fans
            and entity[ATTR_ENTITY_ID] not in disabled
        ]

    def diagnostics(self) -> dict[str, Any]:
        """Return privacy-safe capabilities, outputs, and recommendations."""
        derived_keys = (
            "temperature",
            "relative_humidity",
            "dew_point",
            "absolute_humidity",
            "humidity_ratio",
            "enthalpy",
            "humidex",
            "apparent_temperature",
            "surface_temperature",
            "surface_relative_humidity",
            "outdoor_temperature",
            "outdoor_relative_humidity",
            "outdoor_humidity_ratio",
            "outdoor_enthalpy",
        )
        assessment_keys = (
            "state",
            "comfort",
            "comfort_confidence",
            "thermal_input_quality",
            "humidity",
            "mould_risk",
            "air_quality",
            "ventilation",
            "cooling",
            "health_alert",
        )
        return {
            "capabilities": dict(self.assessment.get("capabilities", {})),
            "derived": {
                key: self.assessment[key]
                for key in derived_keys
                if key in self.assessment and self.assessment[key] is not None
            },
            "assessment": {
                key: str(self.assessment.get(key, "unknown")) for key in assessment_keys
            },
            "recommendations": {
                "window": str(self.assessment.get("window_recommendation", "none")),
                "ventilation_fan": str(
                    self.assessment.get("ventilation_fan_request", "none")
                ),
                "circulation_fan": str(
                    self.assessment.get("circulation_fan_request", "none")
                ),
            },
            "context": self.assessment.get("context", ""),
            "reason_codes": list(self.assessment.get("reason_codes", [])),
            "source_summary": {
                key: {
                    "mode": value.get("mode", "unknown"),
                    "count": len(value.get("entities", [])),
                }
                for key, value in self.assessment.get("source_entities", {}).items()
            },
            "primary_sources": {
                key: {
                    "configured": bool(value.get("configured", False)),
                    "available": bool(value.get("available", False)),
                }
                for key, value in self.assessment.get("source_entities", {}).items()
                if key in ("temperature", "humidity")
            },
            "pollutant_assessments": self.assessment.get("pollutant_assessments", {}),
            "pollutant_sources": {
                key: len(value.get("entities", []))
                for key, value in self.assessment.get("source_entities", {}).items()
                if key in POLLUTANT_NAMES.values() and value.get("entities")
            },
            "humidity_warning_duration_seconds": self.assessment.get(
                "humidity_warning_duration_seconds", 0
            ),
        }

    def unload(self) -> None:
        """Release listeners, subscribers, and bounded histories."""
        if self._remove_outdoor_listener is not None:
            self._remove_outdoor_listener()
            self._remove_outdoor_listener = None
        for remove_listener in self._listeners:
            remove_listener()
        self._listeners.clear()
        self._subscribers.clear()
        self._humidity_history.clear()
        for history in self._pollutant_history.values():
            history.clear()
        self._last_pollutant_sample.clear()
