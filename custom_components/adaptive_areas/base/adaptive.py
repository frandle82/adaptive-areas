"""Classes for Adaptive Areas and Meta Areas."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
import logging
from time import monotonic
from typing import Any

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.switch.const import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_ON,
    EntityCategory,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import (
    EventDeviceRegistryUpdatedData,
    async_entries_for_area,
    async_get as devicereg_async_get,
)
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_registry import (
    EVENT_ENTITY_REGISTRY_UPDATED,
    EventEntityRegistryUpdatedData,
    RegistryEntry,
    async_get as entityreg_async_get,
)
from homeassistant.util import slugify

from custom_components.adaptive_areas.const import (
    AREA_STATE_OCCUPIED,
    AREA_TYPE_EXTERIOR,
    AREA_TYPE_INTERIOR,
    AREA_TYPE_META,
    CONF_ENABLED_FEATURES,
    CONF_BLE_TRACKER_ENTITIES,
    CONF_EXCLUDE_ENTITIES,
    CONF_FEATURE_AGGREGATION,
    CONF_FEATURE_BLE_TRACKERS,
    CONF_FEATURE_ENVIRONMENT,
    CONF_FEATURE_ROOM_USAGE,
    CONF_FEATURE_PRESENCE_HOLD,
    CONF_FEATURE_WASP_IN_A_BOX,
    CONF_IGNORE_DIAGNOSTIC_ENTITIES,
    CONF_INCLUDE_ENTITIES,
    CONF_RELOAD_ON_REGISTRY_CHANGE,
    CONF_TYPE,
    CONFIGURABLE_AREA_STATE_MAP,
    DEFAULT_IGNORE_DIAGNOSTIC_ENTITIES,
    DEFAULT_RELOAD_ON_REGISTRY_CHANGE,
    ADAPTIVE_AREAS_COMPONENTS,
    ADAPTIVE_AREAS_COMPONENTS_GLOBAL,
    ADAPTIVE_AREAS_COMPONENTS_META,
    META_AREA_GLOBAL,
    AdaptiveAreasEvents,
    AdaptiveAreasFeatureInfoBLETrackers,
    AdaptiveAreasFeatureInfoPresenceHold,
    AdaptiveAreasFeatureInfoPresenceTracking,
    AdaptiveAreasFeatureInfoWaspInABox,
    MetaAreaAutoReloadSettings,
    MetaAreaType,
)
from custom_components.adaptive_areas.helpers.decision_trace import (
    DecisionTrace,
    safe_record,
)
from custom_components.adaptive_areas.helpers.entity_identity import (
    area_id_from_device_identifiers,
    resolve_generated_entity_id,
)
from custom_components.adaptive_areas.helpers.environment import (
    POLLUTANT_NAMES,
    AreaEnvironmentEngine,
)
from custom_components.adaptive_areas.helpers.room_usage import RoomUsageEngine
from custom_components.adaptive_areas.helpers.sources import (
    physical_presence_source_ids,
)
from custom_components.adaptive_areas.repairs import configured_entity_references

# Classes

META_AREA_INITIAL_LOAD_DEBOUNCE = 2


class BasicArea:
    """An interchangeable area object for Adaptive Areas to consume."""

    id: str
    name: str
    icon: str | None = None
    floor_id: str | None = None
    is_meta: bool = False


class AdaptiveArea:
    """Adaptive Area class.

    Tracks entities and updates area states and secondary states.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        area: BasicArea,
        config: ConfigEntry,
        area_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the adaptive area with all the stuff."""
        self.hass: HomeAssistant = hass
        self.name: str = area.name
        # Default to the icon for the area.
        self.icon: str | None = area.icon
        self.id: str = area.id
        self.slug: str = slugify(self.name)
        self.hass_config: ConfigEntry = config
        self.initialized: bool = False
        self.floor_id: str | None = area.floor_id
        self.logger = logging.getLogger(__name__)

        # Faster lookup lists
        self._area_entities: list[str] = []
        self._area_devices: list[str] = []

        # Timestamp for initialization / reload tests
        self.timestamp: datetime = datetime.now(UTC)
        self.reloading: bool = False
        self._remove_load_listener: Callable[[], None] | None = None
        self._remove_dispatcher_listener: Callable[[], None] | None = None
        self._remove_registry_listener: Callable[[], None] | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._remove_reload_timer: Callable[[], None] | None = None

        # The container owns the lifecycle; a GlobalEntry supplies one local
        # configuration per Area. Legacy entries retain their merged config.
        if area_config is None:
            area_config = dict(config.data)
            if config.options:
                area_config.update(config.options)
        self.config = area_config

        self.entities: dict[str, list[dict[str, str]]] = {}
        self.adaptive_entities: dict[str, list[dict[str, str]]] = {}

        self.last_changed: datetime = datetime.now(UTC)

        self.states: list[str] = []

        self.loaded_platforms: list[str] = []
        # The light control switch of this Area while it is added to Home Assistant.
        self.light_control_switch: Any | None = None
        self.decision_trace = DecisionTrace()
        self.environment: AreaEnvironmentEngine | None = None
        self.room_usage: RoomUsageEngine | None = None

        self.logger.debug("%s: Primed for initialization.", self.name)

    def finalize_init(self):
        """Finalize initialization of the area."""
        self.initialized = True
        self.logger.debug(
            "%s (%s) initialized.", self.name, "Meta-Area" if self.is_meta() else "Area"
        )

        @callback
        def _notify_load(initial_load: bool) -> None:
            """Notify that area is loaded."""
            self._remove_load_listener = None
            # Announce area type loaded
            async_dispatcher_send(
                self.hass,
                AdaptiveAreasEvents.AREA_LOADED,
                self.area_type,
                self.floor_id,
                self.id,
                initial_load,
            )

        # Wait for Hass to have started before announcing load events.
        if self.hass.is_running:
            _notify_load(False)
        else:

            @callback
            def _home_assistant_started(_event) -> None:
                _notify_load(True)

            self._remove_load_listener = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _home_assistant_started
            )

    def unload(self) -> None:
        """Remove listeners and scheduled work owned by the area."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None
        for remove_callback_name in (
            "_remove_load_listener",
            "_remove_dispatcher_listener",
            "_remove_registry_listener",
            "_remove_reload_timer",
        ):
            remove_callback = getattr(self, remove_callback_name)
            if remove_callback is not None:
                remove_callback()
                setattr(self, remove_callback_name, None)
        if self.environment is not None:
            self.environment.unload()
            self.environment = None
        if self.room_usage is not None:
            self.room_usage.unload()
            self.room_usage = None
        self.decision_trace.clear()

    def trace_decision(self, **kwargs) -> None:
        """Safely add an entry to this area's in-memory decision trace."""
        safe_record(self.decision_trace, area_state=self.states, **kwargs)

    def is_occupied(self) -> bool:
        """Return if area is occupied."""
        return self.has_state(AREA_STATE_OCCUPIED)

    def has_state(self, state) -> bool:
        """Check if area has a given state."""
        return state in self.states

    def has_configured_state(self, state) -> bool:
        """Check if area supports a given state."""
        state_opts = CONFIGURABLE_AREA_STATE_MAP.get(state, None)

        if not state_opts:
            return False

        state_entity, state_value = state_opts

        if state_entity and state_value:
            return True

        return False

    def has_feature(self, feature) -> bool:
        """Check if area has a given feature."""
        enabled_features = self.config.get(CONF_ENABLED_FEATURES)

        # Deal with legacy
        if isinstance(enabled_features, list):
            return feature in enabled_features

        # Handle everything else
        if not isinstance(enabled_features, dict):
            self.logger.warning(
                "%s: Invalid configuration for %s", self.name, CONF_ENABLED_FEATURES
            )
            return False

        return feature in enabled_features

    def feature_config(self, feature) -> dict:
        """Return configuration for a given feature."""
        if not self.has_feature(feature):
            self.logger.debug("%s: Feature '%s' not enabled.", self.name, feature)
            return {}

        options = self.config.get(CONF_ENABLED_FEATURES, {})

        if not options:
            self.logger.debug("%s: No feature config found for %s", self.name, feature)

        return options.get(feature, {})

    def available_platforms(self):
        """Return available platforms to area type."""
        available_platforms = []

        if not self.is_meta():
            available_platforms = ADAPTIVE_AREAS_COMPONENTS
        else:
            available_platforms = (
                ADAPTIVE_AREAS_COMPONENTS_GLOBAL
                if self.id == META_AREA_GLOBAL.lower()
                else ADAPTIVE_AREAS_COMPONENTS_META
            )

        return available_platforms

    @property
    def area_type(self):
        """Return the area type."""
        return self.config.get(CONF_TYPE)

    def is_meta(self) -> bool:
        """Return if area is Meta or not."""
        return self.area_type == AREA_TYPE_META

    def is_interior(self):
        """Return if area type is interior or not."""
        return self.area_type == AREA_TYPE_INTERIOR

    def is_exterior(self):
        """Return if area type is exterior or not."""
        return self.area_type == AREA_TYPE_EXTERIOR

    def _is_adaptive_area_entity(self, entity: RegistryEntry) -> bool:
        """Return if entity belongs to this integration instance."""
        return entity.config_entry_id == self.hass_config.entry_id

    def _should_exclude_entity(self, entity: RegistryEntry) -> bool:
        """Exclude entity."""

        # Is adaptive_area entity?
        if entity.config_entry_id == self.hass_config.entry_id:
            return True

        # Is disabled?
        if entity.disabled:
            return True

        # Is in the exclusion list?
        if entity.entity_id in self.config.get(CONF_EXCLUDE_ENTITIES, []):
            return True

        # Are we excluding DIAGNOSTIC and CONFIG?
        if self.config.get(
            CONF_IGNORE_DIAGNOSTIC_ENTITIES, DEFAULT_IGNORE_DIAGNOSTIC_ENTITIES
        ):
            if entity.entity_category == EntityCategory.CONFIG:
                return True
            if entity.entity_category == EntityCategory.DIAGNOSTIC:
                state = self.hass.states.get(entity.entity_id)
                is_room_climate_source = (
                    self.has_feature(CONF_FEATURE_ENVIRONMENT)
                    and entity.domain == "sensor"
                    and state is not None
                    and state.attributes.get(ATTR_DEVICE_CLASS) in POLLUTANT_NAMES
                )
                if not is_room_climate_source:
                    return True

        return False

    async def load_entities(self) -> None:
        """Load entities into entity list."""

        entity_list: list[RegistryEntry] = []
        include_entities = self.config.get(CONF_INCLUDE_ENTITIES)

        entity_registry = entityreg_async_get(self.hass)
        device_registry = devicereg_async_get(self.hass)

        # Add entities from devices in this area
        devices_in_area = async_entries_for_area(device_registry, self.id)
        for device in devices_in_area:
            entity_list.extend(
                [
                    entity
                    for entity in entity_registry.entities.get_entries_for_device_id(
                        device.id
                    )
                    if not self._should_exclude_entity(entity)
                ]
            )
            self._area_devices.append(device.id)

        # Add entities that are specifically set as this area but device is not or has no device.
        entities_in_area = entity_registry.entities.get_entries_for_area_id(self.id)
        entity_list.extend(
            [
                entity
                for entity in entities_in_area
                if entity.entity_id not in entity_list
                and not self._should_exclude_entity(entity)
            ]
        )

        if include_entities and isinstance(include_entities, list):
            for include_entity in include_entities:
                entity_entry = entity_registry.async_get(include_entity)
                if entity_entry:
                    entity_list.append(entity_entry)

        self.load_entity_list(entity_list)

        self.logger.debug(
            "%s: Found area entities: %s",
            self.name,
            str(self.entities),
        )

    def load_adaptive_entities(self):
        """Load adaptive areas-generated entities."""
        from custom_components.adaptive_areas.helpers.area import (
            generated_entities_for_area,
        )

        self.adaptive_entities = {}

        for entity_id in [
            entity.entity_id for entity in generated_entities_for_area(self.hass, self)
        ]:
            entity_domain = entity_id.split(".")[0]

            if entity_domain not in self.adaptive_entities:
                self.adaptive_entities[entity_domain] = []

            self.adaptive_entities[entity_domain].append(
                self.get_entity_dict(entity_id)
            )

        self.logger.debug(
            "%s: Loaded Adaptive Areas entities: %s",
            self.name,
            str(self.adaptive_entities),
        )

    def get_entity_dict(self, entity_id) -> dict[str, str]:
        """Return entity_id in a dictionary with attributes (if available)."""

        # Get latest state and create object
        latest_state = self.hass.states.get(entity_id)
        entity_dict = {ATTR_ENTITY_ID: entity_id}

        if latest_state:
            # Need to exclude entity_id if present but latest_state.attributes
            # is a ReadOnlyDict so we can't remove it, need to iterate and select
            # all keys that are NOT entity_id
            for attr_key, attr_value in latest_state.attributes.items():
                if attr_key != ATTR_ENTITY_ID:
                    entity_dict[attr_key] = attr_value

        return entity_dict

    def load_entity_list(self, entity_list: list[RegistryEntry]) -> None:
        """Populate entity list with loaded entities."""
        self.logger.debug("%s: Original entity list: %s", self.name, str(entity_list))

        for entity in entity_list:
            if entity.entity_id in self._area_entities:
                continue
            self.logger.debug("%s: Loading entity: %s", self.name, entity.entity_id)

            try:
                updated_entity = self.get_entity_dict(entity.entity_id)

                if not entity.domain:
                    self.logger.warning(
                        "%s: Entity domain not found for %s", self.name, entity
                    )
                    continue
                if entity.domain not in self.entities:
                    self.entities[entity.domain] = []

                self.entities[entity.domain].append(updated_entity)

                self._area_entities.append(entity.entity_id)

            # Adding pylint exception because this is a last-resort hail-mary catch-all
            # pylint: disable-next=broad-exception-caught
            except Exception as err:
                self.logger.error(
                    "%s: Unable to load entity '%s': %s",
                    self.name,
                    entity,
                    str(err),
                )

        # Load our own entities
        self.load_adaptive_entities()

    def get_presence_sensors(self) -> list[str]:
        """Return list of entities used for presence tracking."""

        sensors: list[str] = []

        sensors.extend(
            physical_presence_source_ids(
                self.hass,
                self.hass_config,
                self.config,
                loaded_entity_ids=(
                    entity[ATTR_ENTITY_ID]
                    for entities in self.entities.values()
                    for entity in entities
                    if entity and ATTR_ENTITY_ID in entity
                ),
            )
        )

        # Generated presence sources are resolved through the entity registry, so a
        # renamed or suffixed entity ID is still the tracked source.
        # Append presence_hold switch as a presence_sensor
        if self.has_feature(CONF_FEATURE_PRESENCE_HOLD):
            sensors.append(
                resolve_generated_entity_id(
                    self.hass,
                    AdaptiveAreasFeatureInfoPresenceHold,
                    SWITCH_DOMAIN,
                    self.slug,
                )
            )

        # Append BLE Tracker monitor as a presence_sensor
        if self.has_feature(CONF_FEATURE_BLE_TRACKERS) and self.feature_config(
            CONF_FEATURE_BLE_TRACKERS
        ).get(CONF_BLE_TRACKER_ENTITIES, []):
            sensors.append(
                resolve_generated_entity_id(
                    self.hass,
                    AdaptiveAreasFeatureInfoBLETrackers,
                    BINARY_SENSOR_DOMAIN,
                    self.slug,
                )
            )

        # Append Wasp In The Box sensor as presence monitor
        if self.has_feature(CONF_FEATURE_AGGREGATION) and self.has_feature(
            CONF_FEATURE_WASP_IN_A_BOX
        ):
            sensors.append(
                resolve_generated_entity_id(
                    self.hass,
                    AdaptiveAreasFeatureInfoWaspInABox,
                    BINARY_SENSOR_DOMAIN,
                    self.slug,
                )
            )

        return sensors

    def area_state_entity_id(self) -> str:
        """Return the registered entity ID of this Area's presence state entity."""
        return resolve_generated_entity_id(
            self.hass,
            AdaptiveAreasFeatureInfoPresenceTracking,
            BINARY_SENSOR_DOMAIN,
            self.slug,
        )

    async def initialize(self, _=None) -> None:
        """Initialize area."""
        total_start = monotonic()
        self.logger.debug("%s: Initializing area...", self.name)

        step_start = monotonic()
        await self.load_entities()
        self.logger.debug(
            "Adaptive Areas [%s]: entity discovery: %.0f ms",
            self.name,
            (monotonic() - step_start) * 1000,
        )

        if not self.is_meta() and self.has_feature(CONF_FEATURE_ENVIRONMENT):
            self.logger.debug("Area Climate enabled for %s", self.name)
            step_start = monotonic()
            self.environment = AreaEnvironmentEngine(self, activate=False)
            self.logger.debug(
                "Adaptive Areas [%s]: environment init: %.0f ms",
                self.name,
                (monotonic() - step_start) * 1000,
            )
        else:
            self.logger.debug("Area Climate disabled for %s", self.name)

        if not self.is_meta() and self.has_feature(CONF_FEATURE_ROOM_USAGE):
            step_start = monotonic()
            self.room_usage = await RoomUsageEngine.async_create(self)
            self.logger.debug(
                "Adaptive Areas [%s]: room usage init: %.0f ms",
                self.name,
                (monotonic() - step_start) * 1000,
            )

        step_start = monotonic()
        self.finalize_init()
        self.logger.debug(
            "Adaptive Areas [%s]: finalize init: %.0f ms",
            self.name,
            (monotonic() - step_start) * 1000,
        )
        self.logger.debug(
            "Adaptive Areas [%s]: initialize total: %.0f ms",
            self.name,
            (monotonic() - total_start) * 1000,
        )

    def has_entities(self, domain):
        """Check if area has entities."""
        return domain in self.entities

    def make_entity_registry_filter(self):
        """Create entity register filter for this area."""

        @callback
        def _entity_registry_filter(event_data: EventEntityRegistryUpdatedData) -> bool:
            """Filter entity registry events relevant to this area."""

            if not self._reload_on_registry_change():
                return False

            entity_id = event_data["entity_id"]

            # Only this Area's own configuration counts, never another Area's.
            if entity_id in configured_entity_references(self.config):
                return True

            action = event_data["action"]
            entity_registry = entityreg_async_get(self.hass)
            entity_entry = entity_registry.async_get(entity_id)
            if entity_entry is not None and self._is_adaptive_area_entity(entity_entry):
                # Our own entities never trigger a reload, except a rename of one of this
                # Area's entities: consumers resolve the registered ID at setup.
                from custom_components.adaptive_areas.helpers.area import (
                    entity_belongs_to_area,
                )

                return (
                    action == "update"
                    and "entity_id" in event_data.get("changes", {})
                    and entity_belongs_to_area(entity_entry, self)
                )

            def _belongs_to_area() -> bool:
                if entity_entry is None:
                    return False
                if entity_entry.area_id is not None:
                    return entity_entry.area_id == self.id
                if entity_entry.device_id is None:
                    return False
                return self._device_belongs_to_area(entity_entry.device_id)

            if (
                action == "update"
                and "changes" in event_data
                and "area_id" in event_data["changes"]
            ):
                # Removed from our area
                if event_data["changes"]["area_id"] == self.id:
                    return True

                # Is from our area
                if _belongs_to_area():
                    return True

                return False

            if action == "update":
                relevant_changes = {
                    "area_id",
                    "device_id",
                    "disabled_by",
                    "disabled",
                }
                if not relevant_changes.intersection(event_data.get("changes", {})):
                    return False

            if action == "remove" and entity_id in self._area_entities:
                return True

            if action == "create":
                # Is from our area
                if _belongs_to_area():
                    return True

            return False

        return _entity_registry_filter

    def _reload_on_registry_change(self) -> bool:
        """Return this Area's own registry reload setting (a local Area option)."""
        return bool(
            self.config.get(
                CONF_RELOAD_ON_REGISTRY_CHANGE, DEFAULT_RELOAD_ON_REGISTRY_CHANGE
            )
        )

    def _device_belongs_to_area(self, device_id: str) -> bool:
        """Return whether a device's own or inherited Area matches this Area."""
        device_registry = devicereg_async_get(self.hass)
        device_entry = device_registry.async_get(device_id)
        if device_entry is None:
            return False
        if device_entry.area_id is not None:
            return device_entry.area_id == self.id
        parent_device_id = getattr(device_entry, "parent_device_id", None)
        if parent_device_id is None:
            return False
        parent_device = device_registry.async_get(parent_device_id)
        return bool(parent_device and parent_device.area_id == self.id)

    def make_device_registry_filter(self):
        """Create device register filter for this area."""

        @callback
        def _device_registry_filter(event_data: EventDeviceRegistryUpdatedData) -> bool:
            """Filter device registry events relevant to this area."""

            if not self._reload_on_registry_change():
                return False

            # Ignore our own devices. The event carries the registry device ID, so the
            # owner is read from the device's identifiers, not from the ID text.
            device_entry = devicereg_async_get(self.hass).async_get(
                event_data["device_id"]
            )
            if (
                device_entry is not None
                and area_id_from_device_identifiers(device_entry.identifiers)
                is not None
            ):
                return False

            action = event_data["action"]

            if (
                action == "update"
                and "changes" in event_data
                and "area_id" in event_data["changes"]
            ):
                # Removed from our area
                if event_data["changes"]["area_id"] == self.id:
                    return True

            if action == "update" and "area_id" not in event_data.get("changes", {}):
                return False

            # Was from our area?
            if event_data["device_id"] in self._area_devices:
                return True

            # Is from our area
            if self._device_belongs_to_area(event_data["device_id"]):
                return True

            return False

        return _device_registry_filter


class AdaptiveMetaArea(AdaptiveArea):
    """Adaptive Meta Area class."""

    def __init__(
        self,
        hass: HomeAssistant,
        area: BasicArea,
        config: ConfigEntry,
        area_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the meta adaptive area with all the stuff."""
        super().__init__(hass, area, config, area_config)
        self.child_areas: list[str] = self.get_child_areas()

    def get_presence_sensors(self) -> list[str]:
        """Return list of entities used for presence tracking."""

        sensors: list[str] = []

        # MetaAreas track their children
        for child_area in self.child_areas:
            sensors.append(
                resolve_generated_entity_id(
                    self.hass,
                    AdaptiveAreasFeatureInfoPresenceTracking,
                    BINARY_SENSOR_DOMAIN,
                    child_area,
                )
            )
        return sensors

    def get_active_areas(self):
        """Return areas that are occupied."""

        active_areas = []

        for area in self.child_areas:
            try:
                entity_id = f"binary_sensor.area_{area}"
                entity = self.hass.states.get(entity_id)

                if not entity:
                    self.logger.debug("%s: Unable to get area state entity.", area)
                    continue

                if entity.state == STATE_ON:
                    active_areas.append(area)

            # Adding pylint exception because this is a last-resort hail-mary catch-all
            # pylint: disable-next=broad-exception-caught
            except Exception as e:
                self.logger.error(
                    "%s: Unable to get active area state: %s", area, str(e)
                )

        return active_areas

    def get_child_areas(self):
        """Return areas that a Meta area is watching."""
        areas: list[str] = []
        from custom_components.adaptive_areas.helpers.area import iter_runtime_areas

        for area in iter_runtime_areas(self.hass):

            if area.is_meta():
                continue

            if self.floor_id:
                if self.floor_id == area.floor_id:
                    areas.append(area.slug)
            else:
                if (
                    self.id == MetaAreaType.GLOBAL
                    or area.config.get(CONF_TYPE) == self.id
                ):
                    areas.append(area.slug)

        return areas

    async def initialize(self, _=None) -> None:
        """Initialize Meta area."""
        if self.initialized:
            self.logger.debug("%s: Already initialized, ignoring.", self.name)
            return None

        self.logger.debug("%s: Initializing meta area...", self.name)

        await self.load_entities()

        self.finalize_init()

    @callback
    def async_refresh_sources(self) -> None:
        """Coalesce source refreshes of one event burst into a single load.

        Child entities register or disappear in bursts. One task is started
        lazily (no eager start) and reads the registry when it runs, so every
        change made before it runs is included. Home Assistant tracks the task,
        so async_block_till_done() waits for it. Before initialize() the first
        load runs there, so this is a no-op.
        """
        if not self.initialized or self._refresh_task is not None:
            return
        self._refresh_task = self.hass.async_create_task(
            self._async_run_refresh(),
            f"adaptive_areas refresh sources {self.slug}",
            eager_start=False,
        )

    async def _async_run_refresh(self) -> None:
        """Run one coalesced refresh of the child Areas and the source list."""
        self._refresh_task = None
        if not self.initialized:
            return
        self.child_areas = self.get_child_areas()
        await self.load_entities()

    async def load_entities(self) -> None:
        """Load entities into entity list."""

        entity_registry = entityreg_async_get(self.hass)
        entity_list: list[RegistryEntry] = []
        # Rebuild from the registry on every load so removed children are dropped.
        self.entities = {}
        self._area_entities = []

        from custom_components.adaptive_areas.helpers.area import iter_runtime_areas

        for area in iter_runtime_areas(self.hass):

            if area.slug not in self.child_areas:
                continue

            # Force loading of Adaptive Areas entities
            area.load_adaptive_entities()

            for entities in area.adaptive_entities.values():
                for entity in entities:
                    if not isinstance(entity[ATTR_ENTITY_ID], str):
                        self.logger.debug(
                            "%s: Entity ID is not a string: '%s' (probably a group, skipping)",
                            self.name,
                            str(entity[ATTR_ENTITY_ID]),
                        )
                        continue

                    # Skip excluded entities
                    if entity[ATTR_ENTITY_ID] in self.config.get(
                        CONF_EXCLUDE_ENTITIES, []
                    ):
                        continue

                    entity_entry = entity_registry.async_get(entity[ATTR_ENTITY_ID])
                    if not entity_entry:
                        self.logger.debug(
                            "%s: Adaptive Entity not found on Entity Registry: %s",
                            self.name,
                            entity[ATTR_ENTITY_ID],
                        )
                        continue
                    entity_list.append(entity_entry)

        self.load_entity_list(entity_list)

        self.logger.debug(
            "%s: Loaded entities for meta area: %s", self.name, str(self.entities)
        )

    def finalize_init(self) -> None:
        """Finalize Meta-Area initialization."""

        self.initialized = True
        self._remove_dispatcher_listener = async_dispatcher_connect(
            self.hass, AdaptiveAreasEvents.AREA_LOADED, self._handle_loaded_area
        )
        self._remove_registry_listener = self.hass.bus.async_listen(
            EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_removed
        )

    @callback
    def _handle_registry_removed(
        self, event: Event[EventEntityRegistryUpdatedData]
    ) -> None:
        """Drop a removed child entity from this Meta Area's sources."""
        if (
            event.data["action"] == "remove"
            and event.data["entity_id"] in self._area_entities
        ):
            self.async_refresh_sources()

    @callback
    def _handle_loaded_area(
        self,
        area_type: str,
        floor_id: int | None,
        area_id: str,
        initial_load: bool = False,
    ) -> None:
        """Handle area loaded signals."""

        self.logger.debug(
            "%s: Received area loaded signal (type=%s, floor_id=%s, area_id=%s)",
            self.name,
            area_type,
            floor_id,
            area_id,
        )

        # Don't act while hass is not running
        if not self.hass.is_running:
            return

        # Ignore if already handling it
        if self.reloading:
            return

        # An Area of the same config entry (the GlobalEntry) is set up together with this
        # Meta Area: children are resolved after all Areas exist and sources refresh when
        # child entities register. Reloading the shared entry here would reload every
        # Area. Only an Area of another (legacy) entry needs this Meta Area reloaded.
        from custom_components.adaptive_areas.helpers.area import (
            get_runtime_areas_for_entry,
        )

        if any(
            area.id == area_id
            for area in get_runtime_areas_for_entry(self.hass, self.hass_config)
        ):
            return

        # Handle Global
        if self.slug == MetaAreaType.GLOBAL:
            self.schedule_reload(initial_load)
            return

        # Handle all non-Global meta-areas including floors
        self.logger.debug(
            "SS %s, AT %s, AI %s, CA: %s",
            self.slug,
            area_type,
            area_id,
            str(self.child_areas),
        )
        if area_type == self.slug or area_id in self.child_areas:
            self.schedule_reload(initial_load)

    def schedule_reload(self, initial_load: bool = False) -> None:
        """Schedule one reload after related area-load events settle."""
        if self._remove_reload_timer is not None:
            self._remove_reload_timer()
            self._remove_reload_timer = None

        delay = (
            META_AREA_INITIAL_LOAD_DEBOUNCE
            if initial_load
            else MetaAreaAutoReloadSettings.DELAY
        )
        self.reloading = True

        @callback
        def _reload(_now=None) -> None:
            self._remove_reload_timer = None
            self.logger.debug("%s: Reloading entry.", self.name)
            self.hass.config_entries.async_schedule_reload(self.hass_config.entry_id)

        self._remove_reload_timer = async_call_later(self.hass, delay, _reload)
