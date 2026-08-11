"""Classes for Adaptive Areas and Meta Areas."""

from collections.abc import Callable
from datetime import UTC, datetime
import logging

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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import (
    EventDeviceRegistryUpdatedData,
    async_get as devicereg_async_get,
)
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_registry import (
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
    CONF_EXCLUDE_ENTITIES,
    CONF_FEATURE_AGGREGATION,
    CONF_FEATURE_BLE_TRACKERS,
    CONF_FEATURE_PRESENCE_HOLD,
    CONF_FEATURE_WASP_IN_A_BOX,
    CONF_IGNORE_DIAGNOSTIC_ENTITIES,
    CONF_INCLUDE_ENTITIES,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    CONF_TYPE,
    CONFIGURABLE_AREA_STATE_MAP,
    DATA_AREA_OBJECT,
    DEFAULT_IGNORE_DIAGNOSTIC_ENTITIES,
    DEFAULT_PRESENCE_DEVICE_PLATFORMS,
    ADAPTIVE_AREAS_COMPONENTS,
    ADAPTIVE_AREAS_COMPONENTS_GLOBAL,
    ADAPTIVE_AREAS_COMPONENTS_META,
    ADAPTIVE_DEVICE_ID_PREFIX,
    ADAPTIVEAREAS_UNIQUEID_PREFIX,
    META_AREA_GLOBAL,
    MODULE_DATA,
    AdaptiveAreasEvents,
    MetaAreaAutoReloadSettings,
    MetaAreaType,
)
from custom_components.adaptive_areas.helpers.decision_trace import (
    DecisionTrace,
    safe_record,
)
from custom_components.adaptive_areas.repairs import (
    get_configured_entity_references,
)

# Classes


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
        self._remove_reload_timer: Callable[[], None] | None = None

        # Merged options
        area_config = dict(config.data)
        if config.options:
            area_config.update(config.options)
        self.config = area_config

        self.entities: dict[str, list[dict[str, str]]] = {}
        self.adaptive_entities: dict[str, list[dict[str, str]]] = {}

        self.last_changed: datetime = datetime.now(UTC)

        self.states: list[str] = []

        self.loaded_platforms: list[str] = []
        self.decision_trace = DecisionTrace()

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
            self._remove_load_listener = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, lambda _: _notify_load(True)
            )

    def unload(self) -> None:
        """Remove listeners and scheduled work owned by the area."""
        for remove_callback_name in (
            "_remove_load_listener",
            "_remove_dispatcher_listener",
            "_remove_reload_timer",
        ):
            remove_callback = getattr(self, remove_callback_name)
            if remove_callback is not None:
                remove_callback()
                setattr(self, remove_callback_name, None)
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
            if entity.entity_category in [
                EntityCategory.CONFIG,
                EntityCategory.DIAGNOSTIC,
            ]:
                return True

        return False

    async def load_entities(self) -> None:
        """Load entities into entity list."""

        entity_list: list[RegistryEntry] = []
        include_entities = self.config.get(CONF_INCLUDE_ENTITIES)

        entity_registry = entityreg_async_get(self.hass)
        device_registry = devicereg_async_get(self.hass)

        # Add entities from devices in this area
        devices_in_area = device_registry.devices.get_devices_for_area_id(self.id)
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

        entity_registry = entityreg_async_get(self.hass)
        self.adaptive_entities = {}

        # Add magic are entities
        entities_for_config_id = (
            entity_registry.entities.get_entries_for_config_entry_id(
                self.hass_config.entry_id
            )
        )

        for entity_id in [entity.entity_id for entity in entities_for_config_id]:
            entity_domain = entity_id.split(".")[0]

            if entity_domain not in self.adaptive_entities:
                self.adaptive_entities[entity_domain] = []

            self.adaptive_entities[entity_domain].append(
                self.get_entity_dict(entity_id)
            )

        self.logger.debug(
            "%s: Loaded magic entities: %s", self.name, str(self.adaptive_entities)
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

        valid_presence_platforms = self.config.get(
            CONF_PRESENCE_DEVICE_PLATFORMS, DEFAULT_PRESENCE_DEVICE_PLATFORMS
        )

        for component, entities in self.entities.items():
            if component not in valid_presence_platforms:
                continue

            for entity in entities:
                if not entity:
                    continue

                if component == BINARY_SENSOR_DOMAIN:
                    if ATTR_DEVICE_CLASS not in entity:
                        continue

                    if entity[ATTR_DEVICE_CLASS] not in self.config.get(
                        CONF_PRESENCE_SENSOR_DEVICE_CLASS, []
                    ):
                        continue

                sensors.append(entity[ATTR_ENTITY_ID])

        # Append presence_hold switch as a presence_sensor
        if self.has_feature(CONF_FEATURE_PRESENCE_HOLD):
            presence_hold_switch_id = (
                f"{SWITCH_DOMAIN}.adaptive_areas_presence_hold_{self.slug}"
            )
            sensors.append(presence_hold_switch_id)

        # Append BLE Tracker monitor as a presence_sensor
        if self.has_feature(CONF_FEATURE_BLE_TRACKERS):
            ble_tracker_sensor_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_ble_trackers_{self.slug}_ble_tracker_monitor"
            sensors.append(ble_tracker_sensor_id)

        # Append Wasp In The Box sensor as presence monitor
        if self.has_feature(CONF_FEATURE_AGGREGATION) and self.has_feature(
            CONF_FEATURE_WASP_IN_A_BOX
        ):
            wasp_in_the_box_sensor_id = (
                f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_wasp_in_a_box_{self.slug}"
            )
            sensors.append(wasp_in_the_box_sensor_id)

        return sensors

    async def initialize(self, _=None) -> None:
        """Initialize area."""
        self.logger.debug("%s: Initializing area...", self.name)

        await self.load_entities()

        self.finalize_init()

    def has_entities(self, domain):
        """Check if area has entities."""
        return domain in self.entities

    def make_entity_registry_filter(self):
        """Create entity register filter for this area."""

        @callback
        def _entity_registry_filter(event_data: EventEntityRegistryUpdatedData) -> bool:
            """Filter entity registry events relevant to this area."""

            entity_id = event_data["entity_id"]

            if entity_id in get_configured_entity_references(self.hass_config):
                return True

            # Ignore our own stuff
            _, entity_part = entity_id.split(".")
            if entity_part.startswith(ADAPTIVEAREAS_UNIQUEID_PREFIX):
                return False

            action = event_data["action"]
            entity_registry = entityreg_async_get(self.hass)
            entity_entry = entity_registry.async_get(entity_id)

            if (
                action == "update"
                and "changes" in event_data
                and "area_id" in event_data["changes"]
            ):
                # Removed from our area
                if event_data["changes"]["area_id"] == self.id:
                    return True

                # Is from our area
                if entity_entry and entity_entry.area_id == self.id:
                    return True

                return False

            if action in ("create", "remove"):
                # Is from our area
                if entity_entry and entity_entry.area_id == self.id:
                    return True

            return False

        return _entity_registry_filter

    def make_device_registry_filter(self):
        """Create device register filter for this area."""

        @callback
        def _device_registry_filter(event_data: EventDeviceRegistryUpdatedData) -> bool:
            """Filter device registry events relevant to this area."""

            # Ignore our own stuff
            if event_data["device_id"].startswith(ADAPTIVE_DEVICE_ID_PREFIX):
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

            # Was from our area?
            if event_data["device_id"] in self._area_devices:
                return True

            device_registry = devicereg_async_get(self.hass)
            device_entry = device_registry.async_get(event_data["device_id"])

            # Is from our area
            if device_entry and device_entry.area_id == self.id:
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
    ) -> None:
        """Initialize the meta adaptive area with all the stuff."""
        super().__init__(hass, area, config)
        self.child_areas: list[str] = self.get_child_areas()

    def get_presence_sensors(self) -> list[str]:
        """Return list of entities used for presence tracking."""

        sensors: list[str] = []

        # MetaAreas track their children
        for child_area in self.child_areas:
            entity_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_presence_tracking_{child_area}_area_state"
            sensors.append(entity_id)
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
        data = self.hass.data[MODULE_DATA]
        areas: list[str] = []

        for area_info in data.values():
            area: AdaptiveArea = area_info[DATA_AREA_OBJECT]

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

    async def load_entities(self) -> None:
        """Load entities into entity list."""

        entity_registry = entityreg_async_get(self.hass)
        entity_list: list[RegistryEntry] = []

        data = self.hass.data[MODULE_DATA]
        for area_info in data.values():
            area: AdaptiveArea = area_info[DATA_AREA_OBJECT]

            if area.slug not in self.child_areas:
                continue

            # Force loading of magic entities
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

        # Handle Global
        if self.slug == MetaAreaType.GLOBAL:
            self.schedule_reload(initial_load)
            return

        # Handle all non-Global meta-areas including floors
        self.logger.info(
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
        if self.reloading:
            return

        delay = 0 if initial_load else MetaAreaAutoReloadSettings.DELAY
        self.reloading = True

        @callback
        def _reload(_now=None) -> None:
            self._remove_reload_timer = None
            self.logger.info("%s: Reloading entry.", self.name)
            self.hass.config_entries.async_schedule_reload(self.hass_config.entry_id)

        self._remove_reload_timer = async_call_later(self.hass, delay, _reload)
