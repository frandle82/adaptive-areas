"""Unified, capability-aware Area Environment Engine."""

from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
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
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.unit_conversion import TemperatureConverter

from custom_components.adaptive_areas.const import (
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_DISABLED_FANS,
    CONF_ENVIRONMENT_COMFORT_MAX,
    CONF_ENVIRONMENT_COMFORT_MIN,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_ENVIRONMENT_WINDOWS,
    DEFAULT_ENVIRONMENT_COMFORT_MAX,
    DEFAULT_ENVIRONMENT_COMFORT_MIN,
    DEFAULT_ENVIRONMENT_HUMIDITY_DURATION,
    DEFAULT_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    MODULE_DATA,
    DATA_AREA_OBJECT,
    CirculationFanRequest,
    ComfortState,
    CoolingState,
    EnvironmentState,
    HumidityState,
    VentilationFanRequest,
    VentilationState,
    WindowRecommendation,
    AdaptiveAreasEvents,
)


class AreaEnvironmentEngine:
    """Evaluate available environmental inputs without controlling devices."""

    def __init__(self, area) -> None:
        """Discover capabilities and initialize assessment state."""
        self.area = area
        self.config = area.feature_config("environment")
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
        self._sensor_ids = self._discover_sensor_ids()
        self._window_ids = self._discover_window_ids()
        self.outdoor_temperature_entity = self.config.get(
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE, ""
        )
        self._humidity_history: deque[tuple[datetime, float]] = deque(maxlen=30)
        self._humidity_warning_since: datetime | None = None
        self._ventilation_latched = False
        self._had_window_need = False
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
        """Discover supported Area sensors once using existing entity filtering."""
        supported = {
            SensorDeviceClass.TEMPERATURE,
            SensorDeviceClass.HUMIDITY,
            SensorDeviceClass.CO2,
            SensorDeviceClass.AQI,
            SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
            SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        }
        result: dict[str, list[str]] = {
            str(device_class): [] for device_class in supported
        }
        for entity in self.area.entities.get("sensor", []):
            state = self.area.hass.states.get(entity[ATTR_ENTITY_ID])
            if state is None:
                continue
            device_class = state.attributes.get(ATTR_DEVICE_CLASS)
            if device_class in supported:
                result[str(device_class)].append(entity[ATTR_ENTITY_ID])
        return result

    def _discover_window_ids(self) -> list[str]:
        """Use explicit openings or automatically discovered windows only."""
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
        """Re-evaluate after a relevant sensor or opening changes."""
        self.evaluate()

    @callback
    def _area_state_changed(self, area_id: str, _states_tuple) -> None:
        """Refresh occupancy-dependent requests for this Area only."""
        if area_id == self.area.id:
            self.evaluate()

    def register_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to assessment changes."""
        self._subscribers.append(listener)

        def remove() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return remove

    def _values(self, device_class: SensorDeviceClass) -> list[float]:
        """Return valid numeric values, preferring a generated aggregate."""
        aggregate_id = f"sensor.adaptive_areas_aggregates_{self.area.slug}_aggregate_{device_class}"
        candidate_ids = [aggregate_id, *self._sensor_ids.get(str(device_class), [])]
        values: list[float] = []
        for entity_id in candidate_ids:
            state = self.area.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                continue
            try:
                value = float(state.state)
            except TypeError, ValueError:
                continue
            if device_class == SensorDeviceClass.TEMPERATURE:
                unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                if unit and unit != UnitOfTemperature.CELSIUS:
                    try:
                        value = TemperatureConverter.convert(
                            value, unit, UnitOfTemperature.CELSIUS
                        )
                    except ValueError:
                        continue
            # A valid aggregate replaces its source sensors.
            if entity_id == aggregate_id:
                return [value]
            values.append(value)
        return values

    def _outdoor_temperature(self) -> float | None:
        """Return explicit or valid exterior-Area temperature in Celsius."""
        if self.outdoor_temperature_entity:
            state = self.area.hass.states.get(self.outdoor_temperature_entity)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    value = float(state.state)
                    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                    if unit and unit != UnitOfTemperature.CELSIUS:
                        value = TemperatureConverter.convert(
                            value, unit, UnitOfTemperature.CELSIUS
                        )
                    return value
                except TypeError, ValueError:
                    pass

        exterior_values: list[float] = []
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
                    if unit and unit != UnitOfTemperature.CELSIUS:
                        value = TemperatureConverter.convert(
                            value, unit, UnitOfTemperature.CELSIUS
                        )
                    exterior_values.append(value)
                except TypeError, ValueError:
                    continue
        return mean(exterior_values) if exterior_values else None

    def _comfort(self, temperature: float | None) -> ComfortState:
        if temperature is None:
            return ComfortState.UNKNOWN
        if temperature < self.comfort_min - 2:
            return ComfortState.COLD
        if temperature < self.comfort_min:
            return ComfortState.COOL
        if temperature <= self.comfort_max:
            return ComfortState.COMFORTABLE
        if temperature <= self.comfort_max + 2:
            return ComfortState.WARM
        if temperature <= self.comfort_max + 4:
            return ComfortState.HOT
        return ComfortState.VERY_HOT

    @staticmethod
    def _humidity(value: float | None) -> HumidityState:
        if value is None:
            return HumidityState.UNKNOWN
        if value < 35:
            return HumidityState.VERY_DRY
        if value < 40:
            return HumidityState.DRY
        if value <= 60:
            return HumidityState.NORMAL
        if value <= 65:
            return HumidityState.ELEVATED
        if value <= 75:
            return HumidityState.HIGH
        return HumidityState.VERY_HIGH

    def _humidity_signals(self, value: float | None) -> tuple[bool, bool, list[str]]:
        """Return sustained/rapid humidity signals and reason codes."""
        if value is None:
            self._humidity_warning_since = None
            return False, False, []
        now = datetime.now(UTC)
        self._humidity_history.append((now, value))
        while (
            self._humidity_history
            and (now - self._humidity_history[0][0]).total_seconds() > 300
        ):
            self._humidity_history.popleft()
        rapid = bool(
            self._humidity_history
            and value - self._humidity_history[0][1] >= 15
            and len(self._humidity_history) > 1
        )
        if value > 65:
            self._humidity_warning_since = self._humidity_warning_since or now
        else:
            self._humidity_warning_since = None
        sustained = bool(
            self._humidity_warning_since
            and (now - self._humidity_warning_since).total_seconds()
            >= self.humidity_duration_minutes * 60
        )
        reasons = []
        if value > 75:
            reasons.append("high_humidity")
        if sustained:
            reasons.append("prolonged_high_humidity")
        if rapid:
            reasons.append("rapid_humidity_rise")
        return sustained, rapid, reasons

    def _ventilation(
        self,
        co2: float | None,
        humidity: float | None,
        sustained_humidity: bool,
        rapid_humidity: bool,
        voc: float | None,
        aqi: float | None,
    ) -> tuple[VentilationState, list[str]]:
        reasons: list[str] = []
        state = VentilationState.UNKNOWN
        if co2 is not None:
            if co2 > 2000:
                state, reasons = VentilationState.URGENT, ["very_high_co2"]
            elif co2 > 1400:
                state, reasons = VentilationState.REQUIRED, ["high_co2"]
            elif co2 > 1000:
                state, reasons = VentilationState.RECOMMENDED, ["high_co2"]
            elif self._ventilation_latched and co2 >= 850:
                state, reasons = VentilationState.RECOMMENDED, ["co2_hysteresis"]
            else:
                state = VentilationState.NOT_REQUIRED
        if voc is not None and voc > 500:
            reasons.append("high_voc")
            state = max(state, VentilationState.RECOMMENDED, key=self._ventilation_rank)
        if aqi is not None and aqi > 100:
            reasons.append("poor_aqi")
            candidate = (
                VentilationState.REQUIRED if aqi > 150 else VentilationState.RECOMMENDED
            )
            state = max(state, candidate, key=self._ventilation_rank)
        if humidity is not None and (
            humidity > 75 or sustained_humidity or rapid_humidity
        ):
            reasons.extend(
                code
                for code in (
                    "high_humidity" if humidity > 75 else None,
                    "prolonged_high_humidity" if sustained_humidity else None,
                    "rapid_humidity_rise" if rapid_humidity else None,
                )
                if code
            )
            candidate = (
                VentilationState.REQUIRED
                if humidity > 75 or rapid_humidity
                else VentilationState.RECOMMENDED
            )
            state = max(state, candidate, key=self._ventilation_rank)
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
        """Return whether at least one relevant opening is open."""
        return any(
            (state := self.area.hass.states.get(entity_id)) is not None
            and state.state == STATE_ON
            for entity_id in self._window_ids
        )

    def evaluate(self, *, trace: bool = True) -> None:
        """Recompute all independent assessments and notify consumers."""
        previous = dict(self.assessment)
        temperature_values = self._values(SensorDeviceClass.TEMPERATURE)
        humidity_values = self._values(SensorDeviceClass.HUMIDITY)
        co2_values = self._values(SensorDeviceClass.CO2)
        voc_values = self._values(SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS)
        if not voc_values:
            voc_values = self._values(SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS)
        aqi_values = self._values(SensorDeviceClass.AQI)
        temperature = mean(temperature_values) if temperature_values else None
        humidity_value = mean(humidity_values) if humidity_values else None
        co2 = max(co2_values) if co2_values else None
        voc = max(voc_values) if voc_values else None
        aqi = max(aqi_values) if aqi_values else None
        outdoor = self._outdoor_temperature()
        comfort = self._comfort(temperature)
        humidity_state = self._humidity(humidity_value)
        sustained, rapid, humidity_reasons = self._humidity_signals(humidity_value)
        ventilation, reasons = self._ventilation(
            co2, humidity_value, sustained, rapid, voc, aqi
        )
        reasons.extend(humidity_reasons)

        if temperature is None:
            cooling = CoolingState.UNKNOWN
        elif temperature <= self.comfort_max:
            cooling = CoolingState.NOT_REQUIRED
        elif outdoor is None:
            cooling = CoolingState.UNKNOWN
            reasons.append("room_too_warm")
        elif outdoor <= temperature - self.cooling_delta:
            cooling = CoolingState.PASSIVE_RECOMMENDED
            reasons.extend(
                ["room_too_warm", "outdoor_air_cooler", "passive_cooling_available"]
            )
        else:
            cooling = CoolingState.ACTIVE_RECOMMENDED
            reasons.extend(
                ["room_too_warm", "outdoor_air_warmer", "active_cooling_recommended"]
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
                code
                in {
                    "high_co2",
                    "very_high_co2",
                    "high_humidity",
                    "rapid_humidity_rise",
                }
                for code in reasons
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
            if comfort == ComfortState.WARM:
                circulation_request = CirculationFanRequest.LOW
            elif comfort == ComfortState.HOT:
                circulation_request = CirculationFanRequest.MEDIUM
            elif comfort == ComfortState.VERY_HOT:
                circulation_request = CirculationFanRequest.HIGH

        if (
            ventilation in (VentilationState.REQUIRED, VentilationState.URGENT)
            or humidity_state in (HumidityState.HIGH, HumidityState.VERY_HIGH)
            and (sustained or humidity_state == HumidityState.VERY_HIGH)
        ):
            overall = EnvironmentState.ACTION_REQUIRED
        elif (
            ventilation == VentilationState.RECOMMENDED
            or humidity_state == HumidityState.ELEVATED
            or comfort
            in (
                ComfortState.COOL,
                ComfortState.WARM,
                ComfortState.HOT,
                ComfortState.VERY_HOT,
                ComfortState.COLD,
            )
        ):
            overall = EnvironmentState.ATTENTION
        elif all(
            value == "unknown"
            for value in (comfort, humidity_state, ventilation, cooling)
        ):
            overall = EnvironmentState.UNKNOWN
        elif all(
            value != "unknown" for value in (comfort, humidity_state, ventilation)
        ):
            overall = EnvironmentState.GOOD
        else:
            overall = EnvironmentState.UNKNOWN

        capabilities = {
            "temperature": bool(temperature_values),
            "humidity": bool(humidity_values),
            "co2": bool(co2_values),
            "voc": bool(voc_values),
            "aqi": bool(aqi_values),
            "windows": bool(self._window_ids),
            "outdoor_temperature": outdoor is not None,
        }
        self.assessment = {
            "state": overall,
            "comfort": comfort,
            "humidity": humidity_state,
            "ventilation": ventilation,
            "cooling": cooling,
            "window_recommendation": window,
            "ventilation_fan_request": ventilation_request,
            "circulation_fan_request": circulation_request,
            "capabilities": capabilities,
            "reason_codes": list(dict.fromkeys(reasons)),
            "humidity_warning_duration_seconds": (
                int((datetime.now(UTC) - self._humidity_warning_since).total_seconds())
                if self._humidity_warning_since
                else 0
            ),
        }
        if trace and self.assessment != previous:
            self.area.trace_decision(
                feature="environment",
                trigger="environment_input_changed",
                decision=str(overall),
                outcome="evaluated",
                reason_codes=self.assessment["reason_codes"],
            )
        for subscriber in list(self._subscribers):
            subscriber()

    @property
    def ventilation_fans(self) -> list[str]:
        """Return explicitly classified ventilation fans."""
        return list(self.config.get(CONF_ENVIRONMENT_VENTILATION_FANS, []))

    @property
    def circulation_fans(self) -> list[str]:
        """Return explicit circulation fans, defaulting unclassified fans safely."""
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
        """Return privacy-safe current capability and assessment data."""
        return {
            "capabilities": dict(self.assessment.get("capabilities", {})),
            "assessment": {
                key: str(self.assessment.get(key, "unknown"))
                for key in ("state", "comfort", "humidity", "ventilation", "cooling")
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
            "reason_codes": list(self.assessment.get("reason_codes", [])),
            "humidity_warning_duration_seconds": self.assessment.get(
                "humidity_warning_duration_seconds", 0
            ),
        }

    def unload(self) -> None:
        """Release listeners and in-memory history."""
        for remove_listener in self._listeners:
            remove_listener()
        self._listeners.clear()
        self._subscribers.clear()
        self._humidity_history.clear()
