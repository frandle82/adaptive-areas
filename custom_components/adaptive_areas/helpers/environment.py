"""Capability-aware, deterministic Area Environment evaluation."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.unit_conversion import TemperatureConverter

from custom_components.adaptive_areas.const import (
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_COMFORT_MAX,
    CONF_ENVIRONMENT_COMFORT_MIN,
    CONF_ENVIRONMENT_DISABLED_FANS,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_FEATURE_ENVIRONMENT,
    CONF_FEATURE_HEALTH,
    CONF_TRACK_ROOM_USAGE,
    DATA_AREA_OBJECT,
    DEFAULT_ENVIRONMENT_COMFORT_MAX,
    DEFAULT_ENVIRONMENT_COMFORT_MIN,
    DEFAULT_ENVIRONMENT_HUMIDITY_DURATION,
    DEFAULT_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    MODULE_DATA,
    AdaptiveAreasEvents,
    AirQualityState,
    CirculationFanRequest,
    CleaningRecommendation,
    ComfortState,
    CoolingState,
    EnvironmentState,
    HumidityState,
    MouldRiskState,
    RoomUsageState,
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
    """Configured-band offsets and anti-flap tolerance."""

    cold_offset: float = -2.0
    warm_offset: float = 2.0
    hot_offset: float = 5.0
    hysteresis: float = 0.3
    basis: str = "published Magnus dew point and Canadian humidex formulas"


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
    dew_point_depression: float = 3.0
    basis: str = "UBA moisture guidance; AA conservative persistence model"


@dataclass(frozen=True)
class UsagePolicy:
    """Deterministic, non-scientific home-automation usage bands."""

    normal_seconds: int = 30 * 60
    high_seconds: int = 2 * 60 * 60
    normal_sessions: int = 2
    high_sessions: int = 4
    basis: str = "Adaptive Areas operational policy"


@dataclass(frozen=True)
class VentilationPolicy:
    """Indoor CO2 ventilation bands and clearing hysteresis."""

    recommended: float = 1000.0
    required: float = 1400.0
    urgent: float = 2000.0
    clear: float = 850.0
    basis: str = "UBA indoor CO2 hygiene bands"


# Central policies keep every operational boundary and its provenance reviewable.
COMFORT_POLICY = ComfortPolicy()
HUMIDITY_POLICY = HumidityPolicy()
MOULD_POLICY = MouldPolicy()
USAGE_POLICY = UsagePolicy()
VENTILATION_POLICY = VentilationPolicy()


# WHO values require stated averaging periods. PM, CO, and NO2 use observed rolling
# 24-hour samples; other rows are documented Adaptive Areas operational bands.
AIR_QUALITY_MATRIX: dict[SensorDeviceClass, EvaluationBand] = {
    SensorDeviceClass.CO2: EvaluationBand(1000, 1400, 2000, PARTS_PER_MILLION, "UBA"),
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
    SensorDeviceClass.AQI: EvaluationBand(50, 100, 150, None, "AQI-operational"),
    SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS: EvaluationBand(
        250, 500, 1000, MICROGRAMS_PER_CUBIC_METER, "AA-operational"
    ),
    SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS: EvaluationBand(
        220, 660, 2200, "ppb", "AA-operational"
    ),
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
    """Evaluate environment and optional room usage without device control."""

    def __init__(self, area) -> None:
        """Initialize capability discovery, histories, and listeners."""
        self.area = area
        self.environment_enabled = area.has_feature(CONF_FEATURE_ENVIRONMENT)
        self.usage_enabled = bool(area.config.get(CONF_TRACK_ROOM_USAGE, False))
        self.config = (
            area.feature_config(CONF_FEATURE_ENVIRONMENT)
            if self.environment_enabled
            else {}
        )
        self.comfort_min = float(
            self.config.get(
                CONF_ENVIRONMENT_COMFORT_MIN, DEFAULT_ENVIRONMENT_COMFORT_MIN
            )
        )
        self.comfort_max = float(
            self.config.get(
                CONF_ENVIRONMENT_COMFORT_MAX, DEFAULT_ENVIRONMENT_COMFORT_MAX
            )
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
        self._sensor_ids = (
            self._discover_sensor_ids() if self.environment_enabled else {}
        )
        self._window_ids = (
            self._discover_window_ids() if self.environment_enabled else []
        )
        self.outdoor_temperature_entity = self.config.get(
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE, ""
        )
        self.health_entity = (
            f"binary_sensor.adaptive_areas_health_{self.area.slug}"
            if area.has_feature(CONF_FEATURE_HEALTH)
            else ""
        )
        self._humidity_history: deque[tuple[datetime, float]] = deque(maxlen=60)
        self._humidity_warning_since: datetime | None = None
        self._pollutant_history: dict[str, deque[tuple[datetime, float]]] = {
            str(device_class): deque(maxlen=288)
            for device_class in (
                SensorDeviceClass.PM25,
                SensorDeviceClass.PM10,
                SensorDeviceClass.CO,
                SensorDeviceClass.NITROGEN_DIOXIDE,
            )
        }
        self._last_pollutant_sample: dict[str, float] = {}
        self._ventilation_latched = False
        self._had_window_need = False
        now = datetime.now(UTC)
        self._usage_day: date = now.date()
        self._usage_occupied = area.is_occupied()
        self._occupied_since: datetime | None = now if self._usage_occupied else None
        self._last_occupied: datetime | None = now if self._usage_occupied else None
        self._last_cleared: datetime | None = None
        self._occupied_seconds_today = 0.0
        self._occupancy_sessions_today = 1 if self._usage_occupied else 0
        self._last_dominant_decision: str | None = None
        self._last_comfort = ComfortState.UNKNOWN
        self._listeners: list[Callable[[], None]] = []
        self._subscribers: list[Callable[[], None]] = []
        self.assessment: dict[str, Any] = {}
        tracked = {
            entity_id
            for entity_ids in self._sensor_ids.values()
            for entity_id in entity_ids
        } | set(self._window_ids)
        if self.outdoor_temperature_entity:
            tracked.add(self.outdoor_temperature_entity)
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
        self.evaluate(trace=False)

    def _discover_sensor_ids(self) -> dict[str, list[str]]:
        supported = set(AIR_QUALITY_MATRIX) | {
            SensorDeviceClass.TEMPERATURE,
            SensorDeviceClass.HUMIDITY,
        }
        result = {str(device_class): [] for device_class in supported}
        for entity in self.area.entities.get("sensor", []):
            state = self.area.hass.states.get(entity[ATTR_ENTITY_ID])
            if state and state.attributes.get(ATTR_DEVICE_CLASS) in supported:
                result[str(state.attributes[ATTR_DEVICE_CLASS])].append(
                    entity[ATTR_ENTITY_ID]
                )
        return result

    def _discover_window_ids(self) -> list[str]:
        explicit = self.config.get(CONF_ENVIRONMENT_WINDOWS, [])
        if explicit:
            return list(dict.fromkeys(explicit))
        return [
            entity[ATTR_ENTITY_ID]
            for entity in self.area.entities.get("binary_sensor", [])
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
        self._update_usage_transition()
        self.evaluate()

    def register_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an assessment listener and return its unsubscribe callback."""
        self._subscribers.append(listener)

        def remove() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return remove

    def _values(
        self, device_class: SensorDeviceClass, *, prefer_aggregate: bool = True
    ) -> list[float]:
        aggregate_id = f"sensor.adaptive_areas_aggregates_{self.area.slug}_aggregate_{device_class}"
        candidate_ids = [*self._sensor_ids.get(str(device_class), [])]
        if prefer_aggregate:
            candidate_ids.insert(0, aggregate_id)
        values: list[float] = []
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
            if entity_id == aggregate_id:
                return [value]
            values.append(value)
        return values

    def _outdoor_temperature(self) -> float | None:
        if self.outdoor_temperature_entity:
            state = self.area.hass.states.get(self.outdoor_temperature_entity)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    value = float(state.state)
                    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                    return (
                        TemperatureConverter.convert(
                            value, unit, UnitOfTemperature.CELSIUS
                        )
                        if unit and unit != UnitOfTemperature.CELSIUS
                        else value
                    )
                except TypeError, ValueError:
                    pass
        values: list[float] = []
        for runtime in self.area.hass.data.get(MODULE_DATA, {}).values():
            exterior = runtime.get(DATA_AREA_OBJECT)
            if exterior is None or exterior is self.area or not exterior.is_exterior():
                continue
            for entity in exterior.entities.get("sensor", []):
                state = self.area.hass.states.get(entity[ATTR_ENTITY_ID])
                if (
                    not state
                    or state.attributes.get(ATTR_DEVICE_CLASS)
                    != SensorDeviceClass.TEMPERATURE
                ):
                    continue
                try:
                    value = float(state.state)
                    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                    values.append(
                        TemperatureConverter.convert(
                            value, unit, UnitOfTemperature.CELSIUS
                        )
                        if unit and unit != UnitOfTemperature.CELSIUS
                        else value
                    )
                except TypeError, ValueError:
                    continue
        return mean(values) if values else None

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
        """Calculate published Canadian humidex at warm temperatures."""
        vapour_pressure = 6.11 * math.exp(
            5417.753 * (1 / 273.16 - 1 / (dew_point + 273.15))
        )
        return temperature + 0.5555 * (vapour_pressure - 10)

    def _comfort(
        self, temperature: float | None, humidity: float | None
    ) -> tuple[ComfortState, str, float | None, float | None]:
        if temperature is None:
            return ComfortState.UNKNOWN, "unknown", None, None
        dew_point = (
            self._dew_point(temperature, humidity) if humidity is not None else None
        )
        apparent = (
            self._humidex(temperature, dew_point)
            if dew_point is not None and temperature >= 20
            else temperature
        )
        confidence = "full" if humidity is not None else "limited"
        if apparent < self.comfort_min + COMFORT_POLICY.cold_offset:
            comfort = ComfortState.COLD
        elif apparent < self.comfort_min:
            comfort = ComfortState.COOL
        elif apparent <= self.comfort_max:
            comfort = ComfortState.COMFORTABLE
        elif apparent <= self.comfort_max + COMFORT_POLICY.warm_offset:
            comfort = ComfortState.WARM
        elif apparent < self.comfort_max + COMFORT_POLICY.hot_offset:
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
            abs(apparent - boundary) <= COMFORT_POLICY.hysteresis
            for boundary in boundaries
        ):
            comfort = self._last_comfort
        self._last_comfort = comfort
        return comfort, confidence, dew_point, apparent

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
        if value > HUMIDITY_POLICY.warning:
            self._humidity_warning_since = self._humidity_warning_since or now
        elif value < HUMIDITY_POLICY.normal:
            self._humidity_warning_since = None
        duration = (
            (now - self._humidity_warning_since).total_seconds()
            if self._humidity_warning_since
            else 0.0
        )
        return duration >= self.humidity_duration_minutes * 60, rapid, duration

    @staticmethod
    def _mould_risk(
        temperature: float | None,
        humidity: float | None,
        dew_point: float | None,
        duration: float,
    ) -> MouldRiskState:
        if temperature is None or humidity is None or dew_point is None:
            return MouldRiskState.UNKNOWN
        dew_point_depression = temperature - dew_point
        if duration >= MOULD_POLICY.high_seconds and (
            humidity >= 70 or dew_point_depression <= MOULD_POLICY.dew_point_depression
        ):
            return MouldRiskState.HIGH
        if (
            duration >= MOULD_POLICY.elevated_seconds
            or humidity > HUMIDITY_POLICY.very_high
        ):
            return MouldRiskState.ELEVATED
        return MouldRiskState.LOW

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
        self, device_class: SensorDeviceClass, value: float
    ) -> float:
        key = str(device_class)
        now = datetime.now(UTC)
        history = self._pollutant_history[key]
        while history and (now - history[0][0]).total_seconds() > 86400:
            history.popleft()
        if not history or self._last_pollutant_sample.get(key) != value:
            history.append((now, value))
            self._last_pollutant_sample[key] = value
        return mean(sample for _, sample in history)

    def _air_quality(self) -> tuple[AirQualityState, dict[str, float], list[str]]:
        worst = AirQualityState.UNKNOWN
        measurements: dict[str, float] = {}
        reasons: list[str] = []
        reason_names = {
            SensorDeviceClass.CO2: "co2",
            SensorDeviceClass.PM25: "pm25",
            SensorDeviceClass.PM10: "pm10",
            SensorDeviceClass.CO: "co",
            SensorDeviceClass.NITROGEN_DIOXIDE: "no2",
            SensorDeviceClass.AQI: "aqi",
            SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS: "voc",
            SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS: "voc",
        }
        for device_class, band in AIR_QUALITY_MATRIX.items():
            values = self._values(device_class, prefer_aggregate=False)
            if not values:
                continue
            value = max(values)
            if device_class in (
                SensorDeviceClass.PM25,
                SensorDeviceClass.PM10,
                SensorDeviceClass.CO,
                SensorDeviceClass.NITROGEN_DIOXIDE,
            ):
                value = self._rolling_pollutant(device_class, value)
            name = reason_names[device_class]
            measurements[name] = round(value, 2)
            state = self._classify_air_value(value, band)
            if state in (
                AirQualityState.DEGRADED,
                AirQualityState.POOR,
                AirQualityState.CRITICAL,
            ):
                reasons.append(f"high_{name}")
            if AIR_QUALITY_RANK[state] > AIR_QUALITY_RANK[worst]:
                worst = state
        return worst, measurements, reasons

    def _ventilation(
        self, co2: float | None, humidity: float | None, sustained: bool, rapid: bool
    ) -> tuple[VentilationState, list[str]]:
        reasons: list[str] = []
        state = VentilationState.UNKNOWN
        if co2 is not None:
            if co2 > VENTILATION_POLICY.urgent:
                state, reasons = VentilationState.URGENT, ["very_high_co2"]
            elif co2 > VENTILATION_POLICY.required:
                state, reasons = VentilationState.REQUIRED, ["high_co2"]
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

    def _reset_usage_day(self, now: datetime) -> None:
        if now.date() == self._usage_day:
            return
        self._usage_day = now.date()
        self._occupied_seconds_today = 0.0
        self._occupancy_sessions_today = 1 if self._usage_occupied else 0
        if self._usage_occupied:
            self._occupied_since = now

    def _update_usage_transition(self) -> None:
        if not self.usage_enabled:
            return
        now = datetime.now(UTC)
        self._reset_usage_day(now)
        occupied = self.area.is_occupied()
        if occupied == self._usage_occupied:
            return
        self._usage_occupied = occupied
        if occupied:
            self._occupied_since = now
            self._last_occupied = now
            self._occupancy_sessions_today += 1
        else:
            if self._occupied_since:
                self._occupied_seconds_today += (
                    now - self._occupied_since
                ).total_seconds()
            self._occupied_since = None
            self._last_cleared = now

    def _usage(self) -> dict[str, Any]:
        if not self.usage_enabled:
            return {
                "room_usage": RoomUsageState.UNKNOWN,
                "cleaning_recommendation": CleaningRecommendation.UNKNOWN,
            }
        now = datetime.now(UTC)
        self._reset_usage_day(now)
        current = (
            (now - self._occupied_since).total_seconds()
            if self._usage_occupied and self._occupied_since
            else 0.0
        )
        total = self._occupied_seconds_today + current
        if total == 0 and self._occupancy_sessions_today == 0:
            usage = RoomUsageState.UNUSED
        elif (
            total >= USAGE_POLICY.high_seconds
            or self._occupancy_sessions_today >= USAGE_POLICY.high_sessions
        ):
            usage = RoomUsageState.HIGH
        elif (
            total >= USAGE_POLICY.normal_seconds
            or self._occupancy_sessions_today >= USAGE_POLICY.normal_sessions
        ):
            usage = RoomUsageState.NORMAL
        else:
            usage = RoomUsageState.LOW
        if self._usage_occupied:
            cleaning = CleaningRecommendation.POSTPONE
        elif usage == RoomUsageState.HIGH:
            cleaning = CleaningRecommendation.PREFERRED
        else:
            cleaning = CleaningRecommendation.ALLOWED
        return {
            "room_usage": usage,
            "cleaning_recommendation": cleaning,
            "current_occupancy_duration": int(current),
            "occupied_duration_today": int(total),
            "occupancy_sessions_today": self._occupancy_sessions_today,
            "time_since_last_occupancy": (
                int((now - self._last_cleared).total_seconds())
                if self._last_cleared
                else None
            ),
            "last_occupied": (
                self._last_occupied.isoformat() if self._last_occupied else None
            ),
            "last_cleared": (
                self._last_cleared.isoformat() if self._last_cleared else None
            ),
        }

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
        cleaning = assessment["cleaning_recommendation"]
        if cleaning == CleaningRecommendation.POSTPONE:
            return "cleaning_postponed_occupied", text["clean_postpone"]
        if cleaning == CleaningRecommendation.PREFERRED:
            return "cleaning_preferred_room_clear", text["clean_preferred"]
        if cleaning == CleaningRecommendation.ALLOWED and self.usage_enabled:
            return "cleaning_allowed_room_clear", text["clean_allowed"]
        capabilities = assessment["capabilities"]
        if all(
            capabilities.get(key) for key in ("temperature", "humidity", "air_quality")
        ):
            return "environment_good", text["good"]
        return "environment_partial", text["partial"]

    def evaluate(self, *, trace: bool = True) -> None:
        """Evaluate all available dimensions and notify subscribers."""
        temperature_values = self._values(SensorDeviceClass.TEMPERATURE)
        humidity_values = self._values(SensorDeviceClass.HUMIDITY)
        temperature = mean(temperature_values) if temperature_values else None
        humidity = mean(humidity_values) if humidity_values else None
        comfort, confidence, dew_point, apparent = self._comfort(temperature, humidity)
        humidity_state = self._humidity(humidity)
        sustained, rapid, humidity_duration = self._humidity_signals(humidity)
        mould_risk = self._mould_risk(
            temperature, humidity, dew_point, humidity_duration
        )
        air_quality, pollutants, air_reasons = self._air_quality()
        co2_values = self._values(SensorDeviceClass.CO2, prefer_aggregate=False)
        co2 = max(co2_values) if co2_values else None
        ventilation, ventilation_reasons = self._ventilation(
            co2, humidity, sustained, rapid
        )
        outdoor = self._outdoor_temperature() if self.environment_enabled else None
        reasons = [*air_reasons, *ventilation_reasons]
        if mould_risk == MouldRiskState.ELEVATED:
            reasons.append("mould_risk_elevated")
        elif mould_risk == MouldRiskState.HIGH:
            reasons.append("mould_risk_high")

        if temperature is None:
            cooling = CoolingState.UNKNOWN
        elif apparent is not None and apparent <= self.comfort_max:
            cooling = CoolingState.NOT_REQUIRED
        elif outdoor is None:
            cooling = CoolingState.UNKNOWN
            reasons.append("room_too_warm")
        elif outdoor <= temperature - self.cooling_delta:
            cooling = CoolingState.PASSIVE_RECOMMENDED
            reasons.extend(
                ("room_too_warm", "outdoor_air_cooler", "passive_cooling_available")
            )
        else:
            cooling = CoolingState.ACTIVE_RECOMMENDED
            reasons.extend(
                ("room_too_warm", "outdoor_air_warmer", "active_cooling_recommended")
            )

        ventilation_need = ventilation in (
            VentilationState.RECOMMENDED,
            VentilationState.REQUIRED,
            VentilationState.URGENT,
            VentilationState.VENTILATING,
        )
        window = WindowRecommendation.NONE
        if self._window_ids and (
            ventilation_need or cooling == CoolingState.PASSIVE_RECOMMENDED
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
        elif (
            temperature is not None
            and outdoor is not None
            and temperature > self.comfort_max
            and outdoor > temperature
        ):
            window = WindowRecommendation.KEEP_CLOSED
            self._had_window_need = False
        elif not self.windows_open:
            self._had_window_need = False

        if (
            ventilation in (VentilationState.REQUIRED, VentilationState.URGENT)
            or rapid
            or any(
                reason
                in {"high_co2", "very_high_co2", "high_humidity", "rapid_humidity_rise"}
                for reason in reasons
            )
        ):
            ventilation_request = VentilationFanRequest.HIGH
        elif ventilation in (
            VentilationState.RECOMMENDED,
            VentilationState.VENTILATING,
        ):
            ventilation_request = VentilationFanRequest.LOW
        else:
            ventilation_request = VentilationFanRequest.NONE

        circulation_request = CirculationFanRequest.NONE
        if self.area.is_occupied():
            circulation_request = {
                ComfortState.WARM: CirculationFanRequest.LOW,
                ComfortState.HOT: CirculationFanRequest.MEDIUM,
                ComfortState.VERY_HOT: CirculationFanRequest.HIGH,
            }.get(comfort, CirculationFanRequest.NONE)

        usage = self._usage()
        cleaning = usage["cleaning_recommendation"]
        if usage["room_usage"] == RoomUsageState.HIGH:
            reasons.append("room_usage_high")
        if cleaning == CleaningRecommendation.POSTPONE:
            reasons.append("cleaning_postponed_occupied")
        elif cleaning == CleaningRecommendation.PREFERRED:
            reasons.append("cleaning_preferred_room_clear")
        elif cleaning == CleaningRecommendation.ALLOWED and self.usage_enabled:
            reasons.append("room_clear")
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
            or comfort not in (ComfortState.COMFORTABLE, ComfortState.UNKNOWN)
        )
        any_environment = any(
            value is not None for value in (temperature, humidity, *pollutants.values())
        )
        overall = (
            EnvironmentState.ACTION_REQUIRED
            if critical or required
            else (
                EnvironmentState.ATTENTION
                if attention
                else (
                    EnvironmentState.GOOD
                    if any_environment or self.usage_enabled
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
            "outdoor_temperature": outdoor is not None,
            "room_usage": self.usage_enabled,
            "health": health_state is not None,
        }
        assessment = {
            "state": overall,
            "comfort": comfort,
            "comfort_confidence": confidence,
            "humidity": humidity_state,
            "mould_risk": mould_risk,
            "air_quality": air_quality,
            "ventilation": ventilation,
            "cooling": cooling,
            "temperature": round(temperature, 2) if temperature is not None else None,
            "relative_humidity": round(humidity, 2) if humidity is not None else None,
            "dew_point": round(dew_point, 2) if dew_point is not None else None,
            "apparent_temperature": (
                round(apparent, 2) if apparent is not None else None
            ),
            "pollutants": pollutants,
            "window_recommendation": window,
            "ventilation_fan_request": ventilation_request,
            "circulation_fan_request": circulation_request,
            "capabilities": capabilities,
            "health_alert": health_alert,
            "reason_codes": list(dict.fromkeys(reasons)),
            "humidity_warning_duration_seconds": int(humidity_duration),
            **usage,
        }
        dominant_decision, context = self._context(assessment)
        assessment["dominant_decision"] = dominant_decision
        assessment["context"] = context
        self.assessment = assessment
        if trace and dominant_decision != self._last_dominant_decision:
            self.area.trace_decision(
                feature="environment",
                trigger="environment_input_changed",
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
            "apparent_temperature",
        )
        assessment_keys = (
            "state",
            "comfort",
            "comfort_confidence",
            "humidity",
            "mould_risk",
            "air_quality",
            "ventilation",
            "cooling",
            "room_usage",
            "health_alert",
        )
        return {
            "capabilities": dict(self.assessment.get("capabilities", {})),
            "derived": {key: self.assessment.get(key) for key in derived_keys},
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
                "cleaning": str(
                    self.assessment.get("cleaning_recommendation", "unknown")
                ),
            },
            "context": self.assessment.get("context", ""),
            "reason_codes": list(self.assessment.get("reason_codes", [])),
            "humidity_warning_duration_seconds": self.assessment.get(
                "humidity_warning_duration_seconds", 0
            ),
        }

    def unload(self) -> None:
        """Release listeners, subscribers, and bounded histories."""
        for remove_listener in self._listeners:
            remove_listener()
        self._listeners.clear()
        self._subscribers.clear()
        self._humidity_history.clear()
        for history in self._pollutant_history.values():
            history.clear()
