"""Binary sensor control for adaptive areas."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_ENTITY_ID
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import (
    EVENT_ENTITY_REGISTRY_UPDATED,
    async_get as async_get_entity_registry,
)

from custom_components.adaptive_areas.base.adaptive import (
    AdaptiveArea,
    AdaptiveMetaArea,
)
from custom_components.adaptive_areas.binary_sensor.base import (
    AreaSensorGroupBinarySensor,
)
from custom_components.adaptive_areas.binary_sensor.ble_tracker import (
    AreaBLETrackerBinarySensor,
)
from custom_components.adaptive_areas.binary_sensor.presence import (
    AreaStateBinarySensor,
    MetaAreaStateBinarySensor,
)
from custom_components.adaptive_areas.binary_sensor.wasp_in_a_box import (
    AreaWaspInABoxBinarySensor,
)
from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_BINARY_SENSOR_DEVICE_CLASSES,
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_BLE_TRACKER_ENTITIES,
    CONF_FEATURE_AGGREGATION,
    CONF_FEATURE_BLE_TRACKERS,
    CONF_FEATURE_HEALTH,
    CONF_FEATURE_ROOM_USAGE,
    CONF_FEATURE_WASP_IN_A_BOX,
    CONF_HEALTH_SENSOR_DEVICE_CLASSES,
    DEFAULT_AGGREGATES_BINARY_SENSOR_DEVICE_CLASSES,
    DEFAULT_HEALTH_SENSOR_DEVICE_CLASSES,
    AdaptiveAreasFeatureInfoAggregates,
    AdaptiveAreasFeatureInfoHealth,
    AdaptiveAreasFeatureInfoRoomUsage,
)
from custom_components.adaptive_areas.base.entities import BinaryAdaptiveEntity
from custom_components.adaptive_areas.helpers.area import get_area_from_config_entry
from custom_components.adaptive_areas.helpers.sources import area_entity_ids
from custom_components.adaptive_areas.threshold import create_illuminance_threshold
from custom_components.adaptive_areas.util import cleanup_removed_entries

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BinaryAggregateSourceGroup:
    """Discovered binary sensor sources for one device class."""

    device_class: str
    entity_ids: list[str]


def discover_binary_aggregate_source_groups(
    area: AdaptiveArea,
) -> list[BinaryAggregateSourceGroup]:
    """Discover binary aggregate sources, including own generated entities."""
    if not area.has_feature(CONF_FEATURE_AGGREGATION):
        return []

    config = area.feature_config(CONF_FEATURE_AGGREGATION)
    allowed = config.get(
        CONF_AGGREGATES_BINARY_SENSOR_DEVICE_CLASSES,
        DEFAULT_AGGREGATES_BINARY_SENSOR_DEVICE_CLASSES,
    )
    min_entities = config.get(CONF_AGGREGATES_MIN_ENTITIES, 0)
    entity_ids = area_entity_ids(
        area.hass, area.hass_config, area.config, domain=BINARY_SENSOR_DOMAIN
    )
    # Generated thresholds belong to this config entry and are intentionally
    # excluded by area_entity_ids; include them once they exist in the registry.
    registry = async_get_entity_registry(area.hass)
    entity_ids.update(
        entry.entity_id
        for entry in registry.entities.get_entries_for_config_entry_id(
            area.hass_config.entry_id
        )
        if entry.domain == BINARY_SENSOR_DOMAIN
    )

    grouped: dict[str, list[str]] = {}
    for entity_id in sorted(entity_ids):
        state = area.hass.states.get(entity_id)
        device_class = state.attributes.get(ATTR_DEVICE_CLASS) if state else None
        if device_class not in allowed:
            continue
        if entity_id.startswith(
            f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_aggregates_{area.slug}_aggregate_"
        ):
            continue
        grouped.setdefault(device_class, []).append(entity_id)

    return [
        BinaryAggregateSourceGroup(device_class, ids)
        for device_class, ids in grouped.items()
        if len(ids) >= min_entities
    ]


class AreaAggregateBinarySensorManager:
    """Keep binary aggregate sources synchronized with registry discovery."""

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize the manager."""
        self.area = area
        self._aggregates: dict[str, AreaAggregateBinarySensor] = {}
        self._remove_refresh: Callable[[], None] | None = None
        self._pending_add_entities: AddEntitiesCallback | None = None

    def create_sensors(self) -> list[AreaAggregateBinarySensor]:
        """Create initially discoverable aggregates."""
        entities = []
        for group in discover_binary_aggregate_source_groups(self.area):
            aggregate = AreaAggregateBinarySensor(
                self.area, group.device_class, group.entity_ids
            )
            self._aggregates[group.device_class] = aggregate
            entities.append(aggregate)
        return entities

    @callback
    def async_start(self, async_add_entities: AddEntitiesCallback) -> None:
        """Start registry and source metadata tracking."""
        self._pending_add_entities = async_add_entities
        self.area.hass_config.async_on_unload(self._cleanup)
        self.area.hass_config.async_on_unload(
            self.area.hass.bus.async_listen(
                EVENT_ENTITY_REGISTRY_UPDATED, self._registry_changed
            )
        )
        self.area.hass_config.async_on_unload(
            self.area.hass.bus.async_listen(
                EVENT_DEVICE_REGISTRY_UPDATED, self._registry_changed
            )
        )
        self._schedule_refresh()

    @callback
    def _registry_changed(self, _event: Event) -> None:
        """Refresh after entities enter or leave the area registry."""
        self._schedule_refresh()

    @callback
    def _schedule_refresh(self) -> None:
        """Coalesce registry bursts into one refresh."""
        if self._remove_refresh is not None:
            return

        @callback
        def _run(_now=None) -> None:
            self._remove_refresh = None
            self._refresh()

        handle = self.area.hass.loop.call_soon(_run)
        self._remove_refresh = handle.cancel

    @callback
    def _refresh(self) -> None:
        """Update existing aggregates or add newly eligible ones."""
        new_entities = []
        seen = set()
        for group in discover_binary_aggregate_source_groups(self.area):
            seen.add(group.device_class)
            aggregate = self._aggregates.get(group.device_class)
            if aggregate is None:
                aggregate = AreaAggregateBinarySensor(
                    self.area, group.device_class, group.entity_ids
                )
                self._aggregates[group.device_class] = aggregate
                new_entities.append(aggregate)
            else:
                aggregate.async_set_entity_ids(group.entity_ids)
        for device_class, aggregate in self._aggregates.items():
            if device_class not in seen:
                aggregate.async_set_entity_ids([])
        if new_entities and self._pending_add_entities is not None:
            self._pending_add_entities(new_entities)

    @callback
    def _cleanup(self) -> None:
        """Clean up pending refresh callbacks."""
        if self._remove_refresh is not None:
            self._remove_refresh()
            self._remove_refresh = None


# Classes


class AreaAggregateBinarySensor(AreaSensorGroupBinarySensor):
    """Aggregate sensor for the area."""

    feature_info = AdaptiveAreasFeatureInfoAggregates()


class AreaHealthBinarySensor(AreaSensorGroupBinarySensor):
    """Aggregate sensor for the area."""

    feature_info = AdaptiveAreasFeatureInfoHealth()


class CleaningDueBinarySensor(BinaryAdaptiveEntity, BinarySensorEntity):
    """Report whether an Area's Cleaning Score has reached its threshold."""

    feature_info = AdaptiveAreasFeatureInfoRoomUsage()
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, area: AdaptiveArea) -> None:
        """Initialize the cleaning-due sensor."""
        BinaryAdaptiveEntity.__init__(self, area, domain=BINARY_SENSOR_DOMAIN)
        BinarySensorEntity.__init__(self)

    async def async_added_to_hass(self) -> None:
        """Subscribe to Cleaning Tracker updates."""
        await super().async_added_to_hass()
        assert self.area.room_usage is not None
        self.async_on_remove(
            self.area.room_usage.register_listener(self._assessment_changed)
        )
        self._assessment_changed()

    def _assessment_changed(self) -> None:
        """Publish the current due state."""
        if self.area.room_usage is None:
            return
        assessment = self.area.room_usage.assessment
        self._attr_is_on = assessment["due"]
        self._attr_extra_state_attributes = {
            "cleaning_score": assessment["score"],
            "cleaning_state": str(assessment["cleaning_state"]),
            "cumulative_presence_seconds": assessment["cumulative_presence_seconds"],
            "presence_minutes_since_cleaning": assessment[
                "presence_minutes_since_cleaning"
            ],
            "presence_minutes_to_due": assessment["presence_minutes_to_due"],
            "remaining_minutes_to_due": assessment["remaining_minutes_to_due"],
            "overdue_minutes": assessment["overdue_minutes"],
            "last_cleaned": assessment["last_cleaned"],
            "current_occupancy_duration_seconds": assessment[
                "current_occupancy_duration_seconds"
            ],
        }
        self.async_write_ha_state()


# Setup


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the area binary sensor config entry."""

    area: AdaptiveArea | AdaptiveMetaArea | None = get_area_from_config_entry(
        hass, config_entry
    )
    assert area is not None

    entities = []
    aggregate_manager = None

    # Create main presence sensor
    if area.is_meta() and isinstance(area, AdaptiveMetaArea):
        entities.append(MetaAreaStateBinarySensor(area))
    else:
        entities.append(AreaStateBinarySensor(area))

    # Create extra sensors
    if area.has_feature(CONF_FEATURE_AGGREGATION):
        aggregate_manager = AreaAggregateBinarySensorManager(area)
        entities.extend(aggregate_manager.create_sensors())
        illuminance_threshold_sensor = create_illuminance_threshold(hass, area)
        if illuminance_threshold_sensor:
            entities.append(illuminance_threshold_sensor)

        # Wasp in a box
        if area.has_feature(CONF_FEATURE_WASP_IN_A_BOX) and not area.is_meta():
            entities.extend(create_wasp_in_a_box_sensor(area))

    if area.has_feature(CONF_FEATURE_HEALTH):
        entities.extend(create_health_sensors(area))

    if area.has_feature(CONF_FEATURE_BLE_TRACKERS):
        entities.extend(create_ble_tracker_sensor(area))

    if area.room_usage is not None and area.has_feature(CONF_FEATURE_ROOM_USAGE):
        entities.append(CleaningDueBinarySensor(area))

    # Add all entities
    async_add_entities(entities)

    if aggregate_manager is not None:
        aggregate_manager.async_start(async_add_entities)

    # Cleanup
    if BINARY_SENSOR_DOMAIN in area.adaptive_entities:
        cleanup_removed_entries(
            area.hass, entities, area.adaptive_entities[BINARY_SENSOR_DOMAIN]
        )


def create_wasp_in_a_box_sensor(
    area: AdaptiveArea,
) -> list[AreaWaspInABoxBinarySensor]:
    """Add the Wasp in a box sensor for the area."""

    if not area.has_feature(CONF_FEATURE_WASP_IN_A_BOX) or not area.has_feature(
        CONF_FEATURE_AGGREGATION
    ):
        return []

    try:
        return [AreaWaspInABoxBinarySensor(area)]
    except Exception as e:  # pylint: disable=broad-exception-caught
        _LOGGER.error(
            "%s: Error creating wasp in a box sensor: %s",
            area.slug,
            str(e),
        )
        return []


def create_ble_tracker_sensor(area: AdaptiveArea) -> list[AreaBLETrackerBinarySensor]:
    """Add the BLE tracker sensor for the area."""
    if not area.has_feature(CONF_FEATURE_BLE_TRACKERS):
        return []

    if not area.feature_config(CONF_FEATURE_BLE_TRACKERS).get(
        CONF_BLE_TRACKER_ENTITIES, []
    ):
        return []

    try:
        return [
            AreaBLETrackerBinarySensor(
                area,
            )
        ]
    except Exception as e:  # pylint: disable=broad-exception-caught
        _LOGGER.error(
            "%s: Error creating BLE tracker sensor: %s",
            area.slug,
            str(e),
        )
        return []


def create_health_sensors(area: AdaptiveArea) -> list[AreaHealthBinarySensor]:
    """Add the health sensors for the area."""
    if not area.has_feature(CONF_FEATURE_HEALTH):
        return []

    if BINARY_SENSOR_DOMAIN not in area.entities:
        return []

    distress_entities: list[str] = []

    health_sensor_device_classes = area.feature_config(CONF_FEATURE_HEALTH).get(
        CONF_HEALTH_SENSOR_DEVICE_CLASSES, DEFAULT_HEALTH_SENSOR_DEVICE_CLASSES
    )

    for entity in area.entities[BINARY_SENSOR_DOMAIN]:
        if ATTR_DEVICE_CLASS not in entity:
            continue

        if entity[ATTR_DEVICE_CLASS] not in health_sensor_device_classes:
            continue

        distress_entities.append(entity[ATTR_ENTITY_ID])

    if not distress_entities:
        _LOGGER.debug(
            "%s: No binary sensor found for configured device classes: %s.",
            area.name,
            str(health_sensor_device_classes),
        )
        return []

    _LOGGER.debug(
        "%s: Creating health sensor with the following entities: %s",
        area.slug,
        str(distress_entities),
    )

    try:
        return [
            AreaHealthBinarySensor(
                area,
                device_class=BinarySensorDeviceClass.PROBLEM,
                entity_ids=distress_entities,
            )
        ]
    except Exception as e:  # pylint: disable=broad-exception-caught
        _LOGGER.error(
            "%s: Error creating area health sensor: %s",
            area.slug,
            str(e),
        )
        return []


def create_aggregate_sensors(area: AdaptiveArea) -> list[Entity]:
    """Create the aggregate sensors for the area."""
    # Create aggregates
    if not area.has_feature(CONF_FEATURE_AGGREGATION):
        return []

    aggregates: list[Entity] = []

    # Check BINARY_SENSOR_DOMAIN entities, count by device_class
    if BINARY_SENSOR_DOMAIN not in area.entities:
        return []

    device_class_entities: dict[str, list[str]] = {}

    for entity in area.entities[BINARY_SENSOR_DOMAIN]:
        if ATTR_DEVICE_CLASS not in entity:
            continue

        if entity[ATTR_DEVICE_CLASS] not in device_class_entities:
            device_class_entities[entity[ATTR_DEVICE_CLASS]] = []

        device_class_entities[entity[ATTR_DEVICE_CLASS]].append(entity["entity_id"])

    for device_class, entity_list in device_class_entities.items():
        if len(entity_list) < area.feature_config(CONF_FEATURE_AGGREGATION).get(
            CONF_AGGREGATES_MIN_ENTITIES, 0
        ):
            continue

        if device_class not in area.feature_config(CONF_FEATURE_AGGREGATION).get(
            CONF_AGGREGATES_BINARY_SENSOR_DEVICE_CLASSES,
            DEFAULT_AGGREGATES_BINARY_SENSOR_DEVICE_CLASSES,
        ):
            continue

        _LOGGER.debug(
            "Creating aggregate sensor for device_class '%s' with %s entities (%s)",
            device_class,
            len(entity_list),
            area.slug,
        )
        try:
            aggregates.append(
                AreaAggregateBinarySensor(area, device_class, entity_list)
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "%s: Error creating '%s' aggregate sensor: %s",
                area.slug,
                device_class,
                str(e),
            )

    return aggregates
