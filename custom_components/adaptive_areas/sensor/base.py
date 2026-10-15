"""Base classes for sensor component."""

import logging
import math
from collections.abc import Callable
from typing import Any

from homeassistant.components.group.sensor import ATTR_MEAN, ATTR_SUM, SensorGroup
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor.const import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
)
from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from custom_components.adaptive_areas.base.entities import AdaptiveEntity
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    AGGREGATE_MODE_SUM,
    AGGREGATE_MODE_TOTAL_INCREASING_SENSOR,
    AGGREGATE_MODE_TOTAL_SENSOR,
    DEFAULT_SENSOR_PRECISION,
    EMPTY_STRING,
    AdaptiveAreasFeatureInfoAggregates,
)

_LOGGER = logging.getLogger(__name__)

_ENERGY_STORAGE_VERSION = 1
_ENERGY_STORAGE_KEY = "energy_aggregate"
_ENERGY_RESET_TOLERANCE = 1e-6
_ENERGY_TO_KWH = {
    UnitOfEnergy.JOULE: 1 / 3_600_000,
    UnitOfEnergy.KILO_JOULE: 1 / 3_600,
    UnitOfEnergy.MEGA_JOULE: 1 / 3.6,
    UnitOfEnergy.GIGA_JOULE: 1 / 0.0036,
    UnitOfEnergy.MILLIWATT_HOUR: 1e-6,
    UnitOfEnergy.WATT_HOUR: 1e-3,
    UnitOfEnergy.KILO_WATT_HOUR: 1.0,
    UnitOfEnergy.MEGA_WATT_HOUR: 1_000.0,
    UnitOfEnergy.GIGA_WATT_HOUR: 1_000_000.0,
    UnitOfEnergy.TERA_WATT_HOUR: 1_000_000_000.0,
}


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
        self._remove_member_listener: Callable[[], None] | None = None
        self._added_to_hass = False

    async def async_added_to_hass(self) -> None:
        """Register listeners after Home Assistant has fully added the entity."""
        await AdaptiveEntity.async_added_to_hass(self)
        self._added_to_hass = True
        self._refresh_member_listener()
        self.async_on_remove(self._async_remove_member_listener)
        self.async_update_group_state()

    async def async_will_remove_from_hass(self) -> None:
        """Release dynamic listeners before Home Assistant removes the entity."""
        self._added_to_hass = False
        self._async_remove_member_listener()

    @callback
    def _async_remove_member_listener(self) -> None:
        """Remove the active member listener."""
        if self._remove_member_listener is not None:
            self._remove_member_listener()
            self._remove_member_listener = None

    @callback
    def _refresh_member_listener(self) -> None:
        """Refresh the state listener for the current group members."""
        self._async_remove_member_listener()
        if not self._added_to_hass:
            return

        @callback
        def _async_state_changed_listener(event: Event) -> None:
            """Handle child updates."""
            if not self._added_to_hass:
                return
            self.async_set_context(event.context)
            self.async_update_group_state()
            self.async_write_ha_state()

        # SensorGroup's built-in listener cannot be replaced when group members
        # change. Keep one refreshable listener owned by Adaptive Areas instead.
        self._remove_member_listener = async_track_state_change_event(
            self.hass, self._entity_ids, _async_state_changed_listener
        )

    @callback
    def async_set_entity_ids(self, entity_ids: list[str]) -> bool:
        """Update group members and refresh listeners."""
        ordered_entity_ids = sorted(dict.fromkeys(entity_ids))
        if ordered_entity_ids == self._entity_ids:
            return False
        self._entity_ids = ordered_entity_ids
        if self._added_to_hass:
            self._refresh_member_listener()
            self.async_update_group_state()
            self.async_write_ha_state()
        return True

    @property
    def source_entity_ids(self) -> list[str]:
        """Return current group source entity IDs."""
        return list(self._entity_ids)

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


class AreaEnergyAggregateSensor(AdaptiveEntity, SensorEntity):
    """Persistent, monotonic energy aggregate for an Adaptive Area."""

    feature_info = AdaptiveAreasFeatureInfoAggregates()

    def __init__(
        self,
        area: AdaptiveArea,
        device_class: str,
        entity_ids: list[str],
        unit_of_measurement: str,
    ) -> None:
        """Initialize the energy aggregate."""
        AdaptiveEntity.__init__(
            self, area=area, domain=SENSOR_DOMAIN, translation_key=device_class
        )
        SensorEntity.__init__(self)
        self._entity_ids = sorted(dict.fromkeys(entity_ids))
        self._source_values: dict[str, float] = {}
        self._aggregate_total = 0.0
        self._reset_count = 0
        self._last_reset_source: str | None = None
        self._restored = False
        self._has_persisted_state = False
        self._initialized = False
        self._remove_member_listener: Callable[[], None] | None = None
        self._store: Store[dict[str, Any]] = Store(
            area.hass,
            _ENERGY_STORAGE_VERSION,
            f"{_ENERGY_STORAGE_KEY}.{area.id}",
        )
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_unit_of_measurement = self._target_unit(
            area, unit_of_measurement
        )
        self._attr_suggested_display_precision = DEFAULT_SENSOR_PRECISION

    @staticmethod
    def _target_unit(area: AdaptiveArea, fallback: str) -> str:
        """Return the configured HA energy unit, or the discovered unit."""
        configured = getattr(area.hass.config.units, "energy", None)
        return str(configured or fallback)

    @staticmethod
    def _to_kwh(value: float, unit: str) -> float | None:
        """Normalize a source value to kWh."""
        try:
            factor = _ENERGY_TO_KWH[UnitOfEnergy(unit)]
        except KeyError, ValueError:
            return None
        return value * factor

    def _normalize_state(self, state) -> float | None:
        """Return a finite source value in kWh."""
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            value = float(state.state)
        except TypeError, ValueError:
            return None
        if not math.isfinite(value):
            return None
        unit = state.attributes.get("unit_of_measurement")
        return self._to_kwh(value, str(unit)) if unit else None

    async def async_added_to_hass(self) -> None:
        """Restore tracking state before subscribing to source events."""
        await AdaptiveEntity.async_added_to_hass(self)
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._has_persisted_state = True
            try:
                self._aggregate_total = max(0.0, float(stored.get("total", 0)))
            except TypeError, ValueError:
                self._aggregate_total = 0.0
            sources = stored.get("sources", {})
            if isinstance(sources, dict):
                for entity_id, source in sources.items():
                    if entity_id not in self._entity_ids:
                        continue
                    if isinstance(source, dict):
                        try:
                            value = float(source["last_value_kwh"])
                        except KeyError, TypeError, ValueError:
                            continue
                        if math.isfinite(value):
                            self._source_values[entity_id] = value
            self._restored = bool(stored)
        if not self._has_persisted_state:
            initial_values = {
                entity_id: value
                for entity_id in self._entity_ids
                if (value := self._normalize_state(self.hass.states.get(entity_id)))
                is not None
            }
            self._source_values.update(initial_values)
            self._aggregate_total = sum(initial_values.values())
        else:
            self._process_current_states(initializing=True)
        self._initialized = True
        self._refresh_member_listener()
        self._store.async_delay_save(self._serialize, 1)
        self._publish()

    async def async_will_remove_from_hass(self) -> None:
        """Release the source listener."""
        self._remove_member_listener and self._remove_member_listener()
        self._remove_member_listener = None

    @callback
    def _refresh_member_listener(self) -> None:
        """Keep exactly one listener for the current source set."""
        if self._remove_member_listener is not None:
            self._remove_member_listener()
        self._remove_member_listener = async_track_state_change_event(
            self.hass, self._entity_ids, self._source_changed
        )

    @callback
    def _source_changed(self, event: Event) -> None:
        """Apply one source state transition."""
        if not self._initialized:
            return
        entity_id = event.data.get("entity_id")
        if entity_id not in self._entity_ids:
            return
        new_value = self._normalize_state(event.data.get("new_state"))
        if new_value is None:
            self._publish()
            return
        self._apply_value(entity_id, new_value)
        self._store.async_delay_save(self._serialize, 1)
        self._publish()

    def _apply_value(self, entity_id: str, new_value: float) -> None:
        """Apply one normalized source value to the monotonic total."""
        old_value = self._source_values.get(entity_id)
        if old_value is None:
            self._source_values[entity_id] = new_value
        elif new_value >= old_value - _ENERGY_RESET_TOLERANCE:
            self._aggregate_total += max(0.0, new_value - old_value)
            self._source_values[entity_id] = new_value
        else:
            self._reset_count += 1
            self._last_reset_source = entity_id
            self._source_values[entity_id] = new_value
            self._aggregate_total += new_value

    def _process_current_states(self, *, initializing: bool = False) -> None:
        """Initialize or reconcile currently available source states."""
        for entity_id in self._entity_ids:
            value = self._normalize_state(self.hass.states.get(entity_id))
            if value is None:
                continue
            if entity_id not in self._source_values:
                self._source_values[entity_id] = value
            elif initializing:
                self._apply_value(entity_id, value)
            else:
                self._source_changed(
                    Event(
                        "state_changed",
                        {
                            "entity_id": entity_id,
                            "new_state": self.hass.states.get(entity_id),
                        },
                    )
                )

    def _serialize(self) -> dict[str, Any]:
        """Return the compact persistent representation."""
        return {
            "total": self._aggregate_total,
            "sources": {
                entity_id: {"last_value_kwh": value}
                for entity_id, value in self._source_values.items()
            },
        }

    @property
    def source_entity_ids(self) -> list[str]:
        """Return current group source IDs for dynamic discovery."""
        return list(self._entity_ids)

    @callback
    def async_set_entity_ids(self, entity_ids: list[str]) -> bool:
        """Refresh sources without subtracting removed historical energy."""
        ordered = sorted(dict.fromkeys(entity_ids))
        if ordered == self._entity_ids:
            return False
        for removed in set(self._entity_ids) - set(ordered):
            self._source_values.pop(removed, None)
        self._entity_ids = ordered
        if self._initialized:
            self._refresh_member_listener()
            self._process_current_states()
            self._store.async_delay_save(self._serialize, 1)
            self._publish()
        return True

    def _publish(self) -> None:
        """Publish the current monotonic aggregate and diagnostics."""
        self._attr_native_value = self._aggregate_total
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose source availability without storing per-source details."""
        available = sum(
            self._normalize_state(self.hass.states.get(entity_id)) is not None
            for entity_id in self._entity_ids
        )
        return {
            "source_count": len(self._entity_ids),
            "available_count": available,
            "unavailable_count": len(self._entity_ids) - available,
            "tracked_source_count": len(self._source_values),
            "reset_count": self._reset_count,
            "last_reset_source": self._last_reset_source,
            "restored": self._restored,
        }
