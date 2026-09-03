"""Config Flow for Adaptive Area."""

from collections.abc import Mapping
import importlib.util
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.components.climate.const import (
    ATTR_PRESET_MODES,
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.sensor.const import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch.const import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_ENTITY_ID, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.area_registry import async_get as areareg_async_get
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import (
    async_entries_for_area,
    async_get as devicereg_async_get,
)
from homeassistant.helpers.entity_registry import async_get as entityreg_async_get
from homeassistant.helpers.selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import slugify

from .const import (
    _DOMAIN_SCHEMA,
    ADDITIONAL_LIGHT_TRACKING_ENTITIES,
    ALL_BINARY_SENSOR_DEVICE_CLASSES,
    ALL_PRESENCE_DEVICE_PLATFORMS,
    ALL_SENSOR_DEVICE_CLASSES,
    AREA_STATE_DARK,
    AREA_STATE_ACCENT,
    AREA_STATE_EXTENDED,
    AREA_STATE_OCCUPIED,
    AREA_STATE_SLEEP,
    AREA_TYPE_EXTERIOR,
    AREA_TYPE_INTERIOR,
    AREA_TYPE_META,
    AREA_EVALUATION_OPTIONS_SCHEMA,
    BUILTIN_AREA_STATES,
    CLIMATE_CONTROL_FEATURE_SCHEMA_ENTITY_SELECT,
    CLIMATE_CONTROL_FEATURE_SCHEMA_PRESET_SELECT,
    CONF_ACCENT_ENTITY,
    CONF_ACCENT_LIGHTS,
    CONF_ACCENT_LIGHTS_ACTIVATION,
    CONF_ACCENT_LIGHTS_BLOCKING_STATES,
    CONF_ACCENT_LIGHTS_BRIGHTNESS,
    CONF_AGGREGATES_BINARY_SENSOR_DEVICE_CLASSES,
    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD,
    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS,
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_AGGREGATES_SENSOR_DEVICE_CLASSES,
    CONF_BLE_TRACKER_ENTITIES,
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_CLEAR_TIMEOUT,
    CONF_CLIMATE_CONTROL_ENTITY_ID,
    CONF_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD,
    CONF_CLIMATE_CONTROL_PRESET_CLEAR,
    CONF_CLIMATE_CONTROL_PRESET_EXTENDED,
    CONF_CLIMATE_CONTROL_PRESET_OCCUPIED,
    CONF_CLIMATE_CONTROL_PRESET_SLEEP,
    CONF_DARK_ENTITY,
    CONF_ENABLED_FEATURES,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXTENDED_TIME,
    CONF_EXTENDED_TIMEOUT,
    CONF_FAN_GROUPS_REQUIRED_STATE,
    CONF_FAN_GROUPS_SETPOINT,
    CONF_FAN_GROUPS_TRACKED_DEVICE_CLASS,
    CONF_FEATURE_AGGREGATION,
    CONF_FEATURE_AREA_AWARE_MEDIA_PLAYER,
    CONF_FEATURE_BLE_TRACKERS,
    CONF_FEATURE_CLIMATE_CONTROL,
    CONF_FEATURE_ENVIRONMENT,
    CONF_FEATURE_FAN_GROUPS,
    CONF_FEATURE_HEALTH,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_FEATURE_LIST,
    CONF_FEATURE_LIST_GLOBAL,
    CONF_FEATURE_LIST_META,
    CONF_FEATURE_PRESENCE_HOLD,
    CONF_FEATURE_ROOM_USAGE,
    CONF_FEATURE_SWITCH_GROUPS,
    CONF_FEATURE_WASP_IN_A_BOX,
    CONF_HEALTH_SENSOR_DEVICE_CLASSES,
    CONF_ID,
    CONF_IGNORE_DIAGNOSTIC_ENTITIES,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_INCLUDE_ENTITIES,
    CONF_KEEP_ONLY_ENTITIES,
    CONF_NOTIFICATION_DEVICES,
    CONF_NOTIFY_STATES,
    CONF_OVERHEAD_LIGHTS,
    CONF_OVERHEAD_LIGHTS_ACTIVATION,
    CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    CONF_PRESENCE_CONTROL_ENTITIES,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_HOLD_TIMEOUT,
    CONF_PRESENCE_MINUTES_TO_DUE,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    CONF_RELOAD_ON_REGISTRY_CHANGE,
    CONF_ROOM_CATEGORY,
    CONF_SECONDARY_STATES,
    CONF_SECONDARY_STATES_CALCULATION_MODE,
    CONF_SLEEP_ENTITY,
    CONF_SLEEP_LIGHTS,
    CONF_SLEEP_LIGHTS_ACTIVATION,
    CONF_SLEEP_LIGHTS_BLOCKING_STATES,
    CONF_SLEEP_LIGHTS_BRIGHTNESS,
    CONF_SLEEP_SWITCHES,
    CONF_SLEEP_SWITCHES_ACT_ON,
    CONF_SLEEP_SWITCHES_STATES,
    CONF_SLEEP_SWITCHES_ACTION,
    CONF_SLEEP_TIMEOUT,
    CONF_TASK_LIGHTS,
    CONF_TASK_LIGHTS_ACTIVATION,
    CONF_TASK_LIGHTS_BLOCKING_STATES,
    CONF_TASK_LIGHTS_BRIGHTNESS,
    CONF_TASK_SWITCHES,
    CONF_TASK_SWITCHES_ACT_ON,
    CONF_TASK_SWITCHES_STATES,
    CONF_TASK_SWITCHES_ACTION,
    CONF_TYPE,
    CONF_WASP_IN_A_BOX_DELAY,
    CONF_WASP_IN_A_BOX_WASP_DEVICE_CLASSES,
    CONF_WASP_IN_A_BOX_WASP_TIMEOUT,
    CONFIG_FLOW_ENTITY_FILTER_BOOL,
    CONFIG_FLOW_ENTITY_FILTER_EXT,
    CONFIGURABLE_AREA_STATE_MAP,
    CONFIGURABLE_FEATURES,
    DATA_AREA_OBJECT,
    DISTRESS_SENSOR_CLASSES,
    DOMAIN,
    EMPTY_STRING,
    FAN_GROUPS_ALLOWED_TRACKED_DEVICE_CLASS,
    LIGHT_GROUP_ACT_ON_OPTIONS,
    LIGHT_GROUP_ACTIVATION_DISABLED,
    LIGHT_GROUP_BRIGHTNESS_OPTIONS,
    LIGHT_GROUP_FEATURE_SCHEMA,
    ADAPTIVEAREAS_UNIQUEID_PREFIX,
    META_AREA_BASIC_OPTIONS_SCHEMA,
    META_AREA_GLOBAL,
    META_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA,
    META_AREA_SCHEMA,
    META_AREA_SECONDARY_STATES_SCHEMA,
    MODULE_DATA,
    NON_CONFIGURABLE_FEATURES_META,
    OPTIONS_AGGREGATES,
    OPTIONS_AREA,
    OPTIONS_AREA_AWARE_MEDIA_PLAYER,
    OPTIONS_AREA_META,
    OPTIONS_BLE_TRACKERS,
    OPTIONS_CLIMATE_CONTROL,
    OPTIONS_CLIMATE_CONTROL_ENTITY_SELECT,
    OPTIONS_FAN_GROUP,
    OPTIONS_AREA_EVALUATION,
    OPTIONS_HEALTH_SENSOR,
    OPTIONS_LIGHT_GROUP,
    OPTIONS_PRESENCE_HOLD,
    OPTIONS_ROOM_USAGE,
    OPTIONS_PRESENCE_TRACKING,
    OPTIONS_PRESENCE_TRACKING_META,
    OPTIONS_SWITCH_GROUP,
    OPTIONS_SECONDARY_STATES,
    OPTIONS_SECONDARY_STATES_META,
    OPTIONS_WASP_IN_A_BOX,
    PRESENCE_CONTROL_ENTITY_DOMAINS,
    REGULAR_AREA_BASIC_OPTIONS_SCHEMA,
    REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA,
    REGULAR_AREA_SCHEMA,
    SECONDARY_STATES_SCHEMA,
    WASP_IN_A_BOX_WASP_DEVICE_CLASSES,
    CalculationMode,
    AdaptiveAreasFeatures,
    AdaptiveConfigEntryVersion,
    MetaAreaType,
    SelectorTranslationKeys,
    RoomCategory,
    SWITCH_GROUP_ACTION_OPTIONS,
)
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.helpers.area import (
    basic_area_from_floor,
    basic_area_from_meta,
    basic_area_from_object,
)
from custom_components.adaptive_areas.helpers.light_groups import (
    migrate_light_groups_in_config,
)

_LOGGER = logging.getLogger(__name__)

EMPTY_ENTRY = [""]
LEGACY_DOMAIN = "magic_areas"
LEGACY_IMPORT_PREFIX = "(Import Magic Areas)"
HAS_FLOOR_REGISTRY = (
    importlib.util.find_spec("homeassistant.helpers.floor_registry") is not None
)


def _replace_legacy_entity_ids(value: Any) -> Any:
    """Point imported Magic Areas entity IDs at Adaptive Areas entities."""
    if isinstance(value, str):
        return value.replace(f"{LEGACY_DOMAIN}_", f"{DOMAIN}_")
    if isinstance(value, Mapping):
        return {key: _replace_legacy_entity_ids(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_legacy_entity_ids(item) for item in value]
    return value


def _remove_legacy_environmental_sensors(config: dict[str, Any]) -> dict[str, Any]:
    """Discard Magic Areas `health`/Umweltsensoren during import."""
    cleaned = dict(config)
    enabled = cleaned.get(CONF_ENABLED_FEATURES)
    if isinstance(enabled, dict) and CONF_FEATURE_HEALTH in enabled:
        enabled = dict(enabled)
        enabled.pop(CONF_FEATURE_HEALTH, None)
        cleaned[CONF_ENABLED_FEATURES] = enabled
    return cleaned


class ConfigBase:
    """Base class for config flow."""

    config_entry = None

    # Selector builder
    def _build_selector_boolean(self):
        """Build a boolean toggle selector."""
        return BooleanSelector(BooleanSelectorConfig())

    def _build_selector_select(
        self, options=None, multiple=False, translation_key=EMPTY_STRING
    ):
        """Build a <select> selector."""
        if not options:
            options = []

        return SelectSelector(
            SelectSelectorConfig(
                options=options,
                multiple=multiple,
                mode=SelectSelectorMode.DROPDOWN,
                translation_key=translation_key,
            )
        )

    def _build_selector_entity_simple(
        self, options=None, multiple=False, force_include=False
    ):
        """Build a <select> selector with predefined settings."""
        if not options:
            options = []
        return NullableEntitySelector(
            EntitySelectorConfig(include_entities=options, multiple=multiple)
        )

    def _build_selector_number(
        self,
        *,
        min_value: float = 0,
        max_value: float = 9999,
        mode: NumberSelectorMode = NumberSelectorMode.BOX,
        step: float = 1,
        unit_of_measurement: str = "seconds",
    ):
        """Build a number selector."""
        return NumberSelector(
            NumberSelectorConfig(
                min=min_value,
                max=max_value,
                mode=mode,
                step=step,
                unit_of_measurement=unit_of_measurement,
            )
        )

    def _build_options_schema(
        self,
        options,
        *,
        saved_options: dict | None = None,
        dynamic_validators=None,
        selectors=None,
    ) -> vol.Schema:
        """Build schema for configuration options."""
        _LOGGER.debug(
            "ConfigFlow: Building schema from options: %s - dynamic_validators: %s",
            str(options),
            str(dynamic_validators),
        )

        if not dynamic_validators:
            dynamic_validators = {}

        if not selectors:
            selectors = {}

        if saved_options is None and self.config_entry:
            saved_options = self.config_entry.options

        _LOGGER.debug(
            "ConfigFlow: Data for pre-populating fields: %s", str(saved_options)
        )

        schema = {
            vol.Optional(
                name,
                description={
                    "suggested_value": (
                        saved_options.get(name)
                        if saved_options and saved_options.get(name) is not None
                        else default
                    )
                },
                default=default,
            ): (
                selectors[name]
                if name in selectors
                else dynamic_validators.get(name, validation)
            )
            for name, default, validation in options
        }

        _LOGGER.debug("ConfigFlow: Built schema: %s", str(schema))

        return vol.Schema(schema)


class NullableEntitySelector(EntitySelector):
    """Entity selector that supports null values."""

    def __call__(self, data):
        """Validate the passed selection, if passed."""

        if data in (None, ""):
            return data

        return super().__call__(data)  # type: ignore


class ConfigFlow(config_entries.ConfigFlow, ConfigBase, domain=DOMAIN):
    """Handle a config flow for Adaptive Areas."""

    VERSION = AdaptiveConfigEntryVersion.MAJOR
    MINOR_VERSION = AdaptiveConfigEntryVersion.MINOR

    @callback
    def _legacy_import_choices(self) -> dict[str, config_entries.ConfigEntry]:
        """Return importable Magic Areas entries keyed by display label."""
        configured_area_ids = {
            str(area_id)
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if (area_id := entry.data.get(CONF_ID) or entry.unique_id)
        }
        choices: dict[str, config_entries.ConfigEntry] = {}

        for entry in sorted(
            self.hass.config_entries.async_entries(LEGACY_DOMAIN),
            key=lambda legacy_entry: (
                legacy_entry.title.casefold(),
                legacy_entry.entry_id,
            ),
        ):
            area_id = entry.data.get(CONF_ID) or entry.unique_id
            if not area_id or str(area_id) in configured_area_ids:
                continue

            title = entry.title or entry.data.get(CONF_NAME) or str(area_id)
            label = f"{LEGACY_IMPORT_PREFIX} {title}"
            if label in choices:
                label = f"{label} [{entry.entry_id[:8]}]"
            choices[label] = entry

        return choices

    async def _async_import_legacy_entry(
        self, legacy_entry: config_entries.ConfigEntry
    ):
        """Create an Adaptive Areas entry from a Magic Areas entry."""
        area_id = legacy_entry.data.get(CONF_ID) or legacy_entry.unique_id
        if not area_id:
            return self.async_abort(reason="invalid_area")

        await self.async_set_unique_id(str(area_id))
        self._abort_if_unique_id_configured()

        migrated_data = _replace_legacy_entity_ids(dict(legacy_entry.data))
        migrated_options = _replace_legacy_entity_ids(dict(legacy_entry.options))
        migrated_data = _remove_legacy_environmental_sensors(migrated_data)
        migrated_options = _remove_legacy_environmental_sensors(migrated_options)
        migrated_data, _ = migrate_light_groups_in_config(migrated_data)
        migrated_options, _ = migrate_light_groups_in_config(migrated_options)

        title = legacy_entry.title or migrated_data.get(CONF_NAME) or str(area_id)
        _LOGGER.info(
            "Importing Magic Areas config entry %s as Adaptive Areas area %s",
            legacy_entry.entry_id,
            area_id,
        )
        return self.async_create_entry(
            title=title,
            data=migrated_data,
            options=migrated_options,
        )

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        reserved_names = []
        non_floor_meta_areas = [
            meta_area_type
            for meta_area_type in MetaAreaType
            if meta_area_type != MetaAreaType.FLOOR
        ]

        # Load registries
        area_registry = areareg_async_get(self.hass)
        areas = [
            basic_area_from_object(area) for area in area_registry.async_list_areas()
        ]
        area_ids = [area.id for area in areas]

        # Load floors meta-areas (if supported by the running HA version)
        floors = []
        if HAS_FLOOR_REGISTRY:
            from homeassistant.helpers.floor_registry import (
                async_get as floorreg_async_get,
            )

            floor_registry = floorreg_async_get(self.hass)
            floors = floor_registry.async_list_floors()

        for floor in floors:
            # Prevent conflicts between meta areas and existing areas
            if floor.floor_id in area_ids:
                _LOGGER.warning(
                    "ConfigFlow: You have an area with a reserved name '%s'. This will prevent from using the %s Meta area.",
                    floor.floor_id,
                    floor.floor_id,
                )
                continue

            _LOGGER.debug(
                "ConfigFlow: Appending Meta Area %s to the list of areas",
                floor.floor_id,
            )
            area = basic_area_from_floor(floor)
            reserved_names.append(area.id)
            areas.append(area)

        # Add standard meta areas to area list
        for meta_area in non_floor_meta_areas:
            # Prevent conflicts between meta areas and existing areas
            if meta_area in area_ids:
                _LOGGER.warning(
                    "ConfigFlow: You have an area with a reserved name '%s'. This will prevent from using the %s Meta area.",
                    meta_area,
                    meta_area,
                )
                continue

            _LOGGER.debug(
                "ConfigFlow: Appending Meta Area %s to the list of areas", meta_area
            )
            area = basic_area_from_meta(meta_area)
            reserved_names.append(area.id)
            areas.append(area)

        legacy_import_choices = self._legacy_import_choices()

        if user_input is not None:
            selected_name = user_input[CONF_NAME]
            if legacy_entry := legacy_import_choices.get(selected_name):
                return await self._async_import_legacy_entry(legacy_entry)

            # Look up area object by name
            area_object = None

            for area in areas:
                area_name = selected_name

                # Handle meta area name append
                if area_name.startswith("(Meta)"):
                    area_name = " ".join(area_name.split(" ")[1:])

                if area.name == area_name:
                    area_object = area
                    break

            # Fail if area name not found,
            # this should never happen in ideal conditions.
            if not area_object:
                return self.async_abort(reason="invalid_area")

            # Reserve unique name / already configured check
            await self.async_set_unique_id(area_object.id)
            self._abort_if_unique_id_configured()

            # Create area entry with default config
            config_entry = _DOMAIN_SCHEMA({f"{area_object.id}": {}})[area_object.id]
            extra_opts = {CONF_NAME: area_object.name, CONF_ID: area_object.id}
            config_entry.update(extra_opts)

            # Handle Meta area
            if slugify(area_object.id) in reserved_names:
                _LOGGER.debug(
                    "ConfigFlow: Meta area %s found, setting correct type.",
                    area_object.id,
                )
                config_entry.update({CONF_TYPE: AREA_TYPE_META})

            return self.async_create_entry(title=area_object.name, data=config_entry)

        # Filter out already-configured areas
        configured_areas = []
        ma_data = self.hass.data.get(MODULE_DATA, {})

        for config_data in ma_data.values():
            configured_areas.append(config_data[DATA_AREA_OBJECT].id)

        available_areas = [area for area in areas if area.id not in configured_areas]

        if not available_areas and not legacy_import_choices:
            return self.async_abort(reason="no_more_areas")

        # Slight ordering trick so Meta areas are at the bottom
        available_area_names = sorted(legacy_import_choices)
        available_area_names.extend(
            sorted(
                [area.name for area in available_areas if area.id not in reserved_names]
            )
        )
        available_area_names.extend(
            sorted(
                [
                    f"(Meta) {area.name}"
                    for area in available_areas
                    if area.id in reserved_names
                ]
            )
        )

        schema = vol.Schema({vol.Required(CONF_NAME): vol.In(available_area_names)})

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow, ConfigBase):
    """Handle a option flow for Adaptive Lighting."""

    area: AdaptiveArea

    def __init__(self):
        """Initialize options flow."""
        self.data: dict[str, Any] = {}
        self.all_entities = []
        self.area_entities = []
        self.all_area_entities = []
        self.all_lights = []
        self.all_media_players = []
        self.all_binary_entities = []
        self.all_light_tracking_entities = []
        self.area_options = {}
        super().__init__()

    def _get_feature_list(self) -> list[str]:
        """Return list of available features for area type."""

        feature_list = CONF_FEATURE_LIST
        area_type = self.area.config.get(CONF_TYPE)
        if area_type == AREA_TYPE_META:
            feature_list = CONF_FEATURE_LIST_META
        if self.area.id == META_AREA_GLOBAL.lower():
            feature_list = CONF_FEATURE_LIST_GLOBAL

        feature_list = list(feature_list)
        if area_type == AREA_TYPE_META:
            feature_list = [
                feature
                for feature in feature_list
                if feature != CONF_FEATURE_ENVIRONMENT
            ]

        # Hide switch groups from UI feature selection.
        feature_list = [
            feature for feature in feature_list if feature != CONF_FEATURE_SWITCH_GROUPS
        ]

        return feature_list

    def _get_configurable_features(self) -> list[str]:
        """Return configurable features for area type."""
        filtered_configurable_features = list(CONFIGURABLE_FEATURES.keys())
        if self.area.is_meta():
            for feature in NON_CONFIGURABLE_FEATURES_META:
                if feature in filtered_configurable_features:
                    filtered_configurable_features.remove(feature)
        # Hide switch groups from UI feature configuration menu.
        if CONF_FEATURE_SWITCH_GROUPS in filtered_configurable_features:
            filtered_configurable_features.remove(CONF_FEATURE_SWITCH_GROUPS)

        return filtered_configurable_features

    def _remove_switch_groups_settings(self) -> bool:
        """Remove persisted switch-groups settings from current options."""
        changed = False

        enabled_features = self.area_options.get(CONF_ENABLED_FEATURES, {})
        if (
            isinstance(enabled_features, dict)
            and CONF_FEATURE_SWITCH_GROUPS in enabled_features
        ):
            updated_enabled_features = dict(enabled_features)
            updated_enabled_features.pop(CONF_FEATURE_SWITCH_GROUPS, None)
            self.area_options[CONF_ENABLED_FEATURES] = updated_enabled_features
            changed = True

        # Legacy safety net: drop old top-level switch-group keys if present.
        for key in (
            CONF_SLEEP_SWITCHES,
            CONF_SLEEP_SWITCHES_STATES,
            CONF_SLEEP_SWITCHES_ACT_ON,
            CONF_SLEEP_SWITCHES_ACTION,
            CONF_TASK_SWITCHES,
            CONF_TASK_SWITCHES_STATES,
            CONF_TASK_SWITCHES_ACT_ON,
            CONF_TASK_SWITCHES_ACTION,
        ):
            if key in self.area_options:
                self.area_options.pop(key)
                changed = True

        return changed

    async def _update_options(self):
        """Update config entry options."""
        self._remove_switch_groups_settings()
        return self.async_create_entry(title="", data=dict(self.area_options))

    async def async_step_init(self, user_input=None):
        """Initialize the options flow."""

        self.data = self.hass.data[MODULE_DATA][self.config_entry.entry_id]
        self.area = self.data[DATA_AREA_OBJECT]

        _LOGGER.debug(
            "OptionsFlow: Initializing options flow for area %s", self.area.name
        )
        _LOGGER.debug(
            "OptionsFlow: Options in config entry for area %s: %s",
            self.area.name,
            str(self.config_entry.options),
        )

        # Return all relevant entities
        self.all_entities = sorted(
            self.resolve_groups(
                entity_id
                for entity_id in self.hass.states.async_entity_ids()
                if entity_id.split(".")[0] in CONFIG_FLOW_ENTITY_FILTER_EXT
            )
        )

        # Return all relevant area entities that exists
        # in self.all_entities
        filtered_area_entities = []
        for domain in CONFIG_FLOW_ENTITY_FILTER_EXT:
            filtered_area_entities.extend(
                [
                    entity["entity_id"]
                    for entity in self.area.entities.get(domain, [])
                    if entity["entity_id"] in self.all_entities
                ]
            )

        self.area_entities = sorted(self.resolve_groups(filtered_area_entities))

        # General exclusions are authoritative for optional Area Climate,
        # including explicit and automatically discovered exterior sources.
        evaluation_source_candidates = {
            entity_id
            for key in (
                CONF_AREA_TEMPERATURE_SENSOR,
                CONF_AREA_HUMIDITY_SENSOR,
                CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
                CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
                CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
            )
            if (entity_id := self.area.config.get(key))
        }
        for runtime in self.hass.data.get(MODULE_DATA, {}).values():
            candidate_area = runtime.get(DATA_AREA_OBJECT)
            if candidate_area is None or not candidate_area.is_exterior():
                continue
            for entity in candidate_area.entities.get(SENSOR_DOMAIN, []):
                entity_id = entity[ATTR_ENTITY_ID]
                state = self.hass.states.get(entity_id)
                if state and state.attributes.get(ATTR_DEVICE_CLASS) in (
                    "temperature",
                    "humidity",
                ):
                    evaluation_source_candidates.add(entity_id)

        # All binary entities
        self.all_binary_entities = sorted(
            self.resolve_groups(
                entity_id
                for entity_id in self.all_entities
                if entity_id.split(".")[0] in CONFIG_FLOW_ENTITY_FILTER_BOOL
            )
        )

        self.all_area_entities = sorted(
            self.area_entities
            + self.config_entry.options.get(CONF_EXCLUDE_ENTITIES, [])
            + list(evaluation_source_candidates)
        )

        self.all_lights = sorted(
            self.resolve_groups(
                entity["entity_id"]
                for entity in self.area.entities.get(LIGHT_DOMAIN, [])
                if entity["entity_id"] in self.all_entities
            )
        )
        self.all_media_players = sorted(
            self.resolve_groups(
                entity["entity_id"]
                for entity in self.area.entities.get(MEDIA_PLAYER_DOMAIN, [])
                if entity["entity_id"] in self.all_entities
            )
        )

        # Compile all binary sensors of light device class
        eligible_light_tracking_entities = []
        for entity in self.all_entities:
            e_component = entity.split(".")[0]

            if e_component == BINARY_SENSOR_DOMAIN:
                entity_object = self.hass.states.get(entity)
                if not entity_object:
                    continue
                entity_object_attributes = entity_object.attributes
                if (
                    ATTR_DEVICE_CLASS in entity_object_attributes
                    and entity_object_attributes[ATTR_DEVICE_CLASS]
                    == BinarySensorDeviceClass.LIGHT
                ):
                    eligible_light_tracking_entities.append(entity)

        # Add additional entities to eligitible entities
        eligible_light_tracking_entities.extend(ADDITIONAL_LIGHT_TRACKING_ENTITIES)

        self.all_light_tracking_entities = sorted(
            self.resolve_groups(eligible_light_tracking_entities)
        )

        area_schema = META_AREA_SCHEMA if self.area.is_meta() else REGULAR_AREA_SCHEMA
        self.area_options = area_schema(dict(self.config_entry.options))
        self._remove_switch_groups_settings()

        _LOGGER.debug(
            "%s: Loaded area options: %s", self.area.name, str(self.area_options)
        )

        return await self.async_step_show_menu()

    async def async_step_show_menu(self, user_input=None):
        """Show options selection menu."""
        # Show options menu
        menu_options: list = [
            "area_config",
            "presence_tracking",
            "secondary_states",
            "select_features",
        ]
        # Add entries for features
        menu_options_features = []
        configurable_features = self._get_configurable_features()
        for feature in self.area_options.get(CONF_ENABLED_FEATURES, {}):
            if feature not in configurable_features:
                continue
            menu_options_features.append(f"feature_conf_{feature}")

        menu_options.extend(sorted(menu_options_features))
        menu_options.append("finish")

        return self.async_show_menu(step_id="show_menu", menu_options=menu_options)

    @staticmethod
    def resolve_groups(raw_list):
        """Resolve entities from groups."""
        resolved_list = []
        for item in raw_list:
            if isinstance(item, list):
                for item_child in item:
                    resolved_list.append(item_child)
                continue
            resolved_list.append(item)

        return list(dict.fromkeys(resolved_list))

    async def async_step_area_config(self, user_input=None):
        """Gather basic settings for the area."""
        errors: dict[str, str] = {}
        if user_input is not None:
            _LOGGER.debug(
                "OptionsFlow: Validating area %s base config: %s",
                self.area.name,
                str(user_input),
            )
            options_schema = (
                META_AREA_BASIC_OPTIONS_SCHEMA
                if self.area.is_meta()
                else REGULAR_AREA_BASIC_OPTIONS_SCHEMA
            )
            try:
                validated = options_schema(user_input)
                self.area_options.update(validated)
            except vol.MultipleInvalid as validation:
                errors = {
                    str(error.path[0]): str(error.msg) for error in validation.errors
                }
                _LOGGER.debug(
                    "OptionsFlow: Found the following errors for area %s: %s",
                    self.area.name,
                    str(errors),
                )
            # Adding pylint exception because this is a last-resort hail-mary catch-all
            # pylint: disable-next=broad-exception-caught
            except Exception as e:
                _LOGGER.warning(
                    "OptionsFlow: Unexpected error caught on area %s: %s",
                    self.area.name,
                    str(e),
                )
            else:
                _LOGGER.debug(
                    "OptionsFlow: Saving area %s base config: %s",
                    self.area.name,
                    str(self.area_options),
                )

                return await self.async_step_show_menu()

        presence_control_entities = [
            entity_id
            for domain in PRESENCE_CONTROL_ENTITY_DOMAINS
            for entity_id in self.hass.states.async_entity_ids(domain)
        ]

        all_selectors = {
            CONF_TYPE: self._build_selector_select(
                sorted([AREA_TYPE_INTERIOR, AREA_TYPE_EXTERIOR]),
                translation_key=SelectorTranslationKeys.AREA_TYPE,
            ),
            CONF_INCLUDE_ENTITIES: self._build_selector_entity_simple(
                self.all_entities, multiple=True
            ),
            CONF_EXCLUDE_ENTITIES: self._build_selector_entity_simple(
                self.all_area_entities, multiple=True
            ),
            CONF_PRESENCE_CONTROL_ENTITIES: self._build_selector_entity_simple(
                sorted(presence_control_entities), multiple=True
            ),
            CONF_RELOAD_ON_REGISTRY_CHANGE: self._build_selector_boolean(),
            CONF_IGNORE_DIAGNOSTIC_ENTITIES: self._build_selector_boolean(),
        }

        options = OPTIONS_AREA_META if self.area.is_meta() else OPTIONS_AREA
        selectors = {}

        # Apply options for given area type (regular/meta)
        option_keys = [option[0] for option in options]
        for option_key in option_keys:
            selectors[option_key] = all_selectors[option_key]

        data_schema = self._build_options_schema(
            options=options, saved_options=self.area_options, selectors=selectors
        )

        return self.async_show_form(
            step_id="area_config",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_presence_tracking(self, user_input=None):
        """Gather basic settings for the area."""
        errors: dict[str, str] = {}
        if user_input is not None:
            _LOGGER.debug(
                "OptionsFlow: Validating area %s presence tracking config: %s",
                self.area.name,
                str(user_input),
            )
            options_schema = (
                META_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA
                if self.area.is_meta()
                else REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA
            )
            try:
                self.area_options.update(options_schema(user_input))
            except vol.MultipleInvalid as validation:
                errors = {
                    str(error.path[0]): str(error.msg) for error in validation.errors
                }
                _LOGGER.debug(
                    "OptionsFlow: Found the following errors for area %s: %s",
                    self.area.name,
                    str(errors),
                )
            # Adding pylint exception because this is a last-resort hail-mary catch-all
            # pylint: disable-next=broad-exception-caught
            except Exception as e:
                _LOGGER.warning(
                    "OptionsFlow: Unexpected error caught on area %s: %s",
                    self.area.name,
                    str(e),
                )
            else:
                _LOGGER.debug(
                    "OptionsFlow: Saving area %s base config: %s",
                    self.area.name,
                    str(self.area_options),
                )

                return await self.async_step_show_menu()

        all_selectors = {
            CONF_PRESENCE_DEVICE_PLATFORMS: self._build_selector_select(
                sorted(ALL_PRESENCE_DEVICE_PLATFORMS), multiple=True
            ),
            CONF_PRESENCE_SENSOR_DEVICE_CLASS: self._build_selector_select(
                sorted(ALL_BINARY_SENSOR_DEVICE_CLASSES), multiple=True
            ),
            CONF_KEEP_ONLY_ENTITIES: self._build_selector_entity_simple(
                sorted(self.area.get_presence_sensors()), multiple=True
            ),
            CONF_CLEAR_TIMEOUT: self._build_selector_number(
                unit_of_measurement="minutes"
            ),
        }

        options = (
            OPTIONS_PRESENCE_TRACKING_META
            if self.area.is_meta()
            else OPTIONS_PRESENCE_TRACKING
        )
        selectors = {}

        # Apply options for given area type (regular/meta)
        option_keys = [option[0] for option in options]
        for option_key in option_keys:
            selectors[option_key] = all_selectors[option_key]

        data_schema = self._build_options_schema(
            options=options, saved_options=self.area_options, selectors=selectors
        )

        return self.async_show_form(
            step_id="presence_tracking",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_secondary_states(self, user_input=None):
        """Gather secondary states settings for the area."""
        errors: dict[str, str] = {}
        if user_input is not None:
            _LOGGER.debug(
                "OptionsFlow: Validating area %s secondary states config: %s",
                self.area.name,
                str(user_input),
            )
            area_state_schema = (
                META_AREA_SECONDARY_STATES_SCHEMA
                if self.area.is_meta()
                else SECONDARY_STATES_SCHEMA
            )
            try:
                self.area_options[CONF_SECONDARY_STATES].update(
                    area_state_schema(user_input)
                )
            except vol.MultipleInvalid as validation:
                errors = {
                    str(error.path[0]): str(error.msg) for error in validation.errors
                }
                _LOGGER.debug(
                    "OptionsFlow: Found the following errors for area %s: %s",
                    self.area.name,
                    str(errors),
                )
            # Adding pylint exception because this is a last-resort hail-mary catch-all
            # pylint: disable-next=broad-exception-caught
            except Exception as e:
                _LOGGER.warning(
                    "OptionsFlow: Unexpected error caught for area %s: %s",
                    self.area.name,
                    str(e),
                )
            else:
                _LOGGER.debug(
                    "OptionsFlow: Saving area secondary state config for area %s: %s",
                    self.area.name,
                    str(self.area_options),
                )
                return await self.async_step_show_menu()

        return self.async_show_form(
            step_id="secondary_states",
            data_schema=self._build_options_schema(
                options=(
                    OPTIONS_SECONDARY_STATES_META
                    if self.area.is_meta()
                    else OPTIONS_SECONDARY_STATES
                ),
                saved_options=self.area_options.get(CONF_SECONDARY_STATES, {}),
                dynamic_validators={
                    CONF_DARK_ENTITY: vol.In(
                        EMPTY_ENTRY + self.all_light_tracking_entities
                    ),
                    CONF_SLEEP_ENTITY: vol.In(EMPTY_ENTRY + self.all_binary_entities),
                    CONF_ACCENT_ENTITY: vol.In(EMPTY_ENTRY + self.all_binary_entities),
                    CONF_SECONDARY_STATES_CALCULATION_MODE: vol.In(CalculationMode),
                },
                selectors={
                    CONF_DARK_ENTITY: self._build_selector_entity_simple(
                        self.all_light_tracking_entities
                    ),
                    CONF_SLEEP_ENTITY: self._build_selector_entity_simple(
                        self.all_binary_entities
                    ),
                    CONF_ACCENT_ENTITY: self._build_selector_entity_simple(
                        self.all_binary_entities
                    ),
                    CONF_SLEEP_TIMEOUT: self._build_selector_number(
                        unit_of_measurement="minutes"
                    ),
                    CONF_EXTENDED_TIME: self._build_selector_number(
                        unit_of_measurement="minutes"
                    ),
                    CONF_EXTENDED_TIMEOUT: self._build_selector_number(
                        unit_of_measurement="minutes"
                    ),
                    CONF_SECONDARY_STATES_CALCULATION_MODE: self._build_selector_select(
                        options=list(CalculationMode),
                        translation_key=SelectorTranslationKeys.CALCULATION_MODE,
                    ),
                },
            ),
            errors=errors,
        )

    async def async_step_select_features(self, user_input=None):
        """Ask the user to select features to enable for the area."""

        feature_list = self._get_feature_list()

        if user_input is not None:
            selected_features = [
                feature for feature, is_selected in user_input.items() if is_selected
            ]

            _LOGGER.debug(
                "OptionsFlow: Selected features for area %s: %s",
                self.area.name,
                str(selected_features),
            )

            if CONF_ENABLED_FEATURES not in self.area_options:
                self.area_options[CONF_ENABLED_FEATURES] = {}

            for c_feature in feature_list:
                if c_feature in selected_features:
                    if c_feature not in self.area_options.get(
                        CONF_ENABLED_FEATURES, {}
                    ):
                        self.area_options[CONF_ENABLED_FEATURES][c_feature] = {}
                else:
                    # Remove feature if we had previously enabled
                    if c_feature in self.area_options.get(CONF_ENABLED_FEATURES, {}):
                        self.area_options[CONF_ENABLED_FEATURES].pop(c_feature)

            return await self.async_step_show_menu()

        _LOGGER.debug(
            "OptionsFlow: Selecting features for area %s from %s",
            self.area.name,
            feature_list,
        )

        return self.async_show_form(
            step_id="select_features",
            data_schema=self._build_options_schema(
                options=[(feature, False, bool) for feature in feature_list],
                saved_options={
                    feature: (
                        feature in self.area_options.get(CONF_ENABLED_FEATURES, {})
                    )
                    for feature in feature_list
                },
            ),
        )

    async def async_step_finish(self, user_input=None):
        """Save options and exit options flow."""
        _LOGGER.debug(
            "OptionsFlow: All features configured for area %s, saving config: %s",
            self.area.name,
            str(self.area_options),
        )
        return await self._update_options()

    async def async_step_feature_conf_light_groups(self, user_input=None):
        """Configure the light groups feature."""

        activation_keys = {
            CONF_OVERHEAD_LIGHTS_ACTIVATION,
            CONF_SLEEP_LIGHTS_ACTIVATION,
            CONF_ACCENT_LIGHTS_ACTIVATION,
            CONF_TASK_LIGHTS_ACTIVATION,
        }
        blocking_state_keys = {
            CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
            CONF_SLEEP_LIGHTS_BLOCKING_STATES,
            CONF_ACCENT_LIGHTS_BLOCKING_STATES,
            CONF_TASK_LIGHTS_BLOCKING_STATES,
        }
        brightness_keys = {
            CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
            CONF_SLEEP_LIGHTS_BRIGHTNESS,
            CONF_ACCENT_LIGHTS_BRIGHTNESS,
            CONF_TASK_LIGHTS_BRIGHTNESS,
        }

        secondary_states = self.area_options.get(CONF_SECONDARY_STATES, {})
        if not isinstance(secondary_states, dict):
            secondary_states = {}

        available_activation_modes = [
            LIGHT_GROUP_ACTIVATION_DISABLED,
            AREA_STATE_OCCUPIED,
            AREA_STATE_EXTENDED,
        ]
        available_blocking_states = [AREA_STATE_EXTENDED]
        if secondary_states.get(CONF_SLEEP_ENTITY):
            available_activation_modes.append(AREA_STATE_SLEEP)
            available_blocking_states.append(AREA_STATE_SLEEP)
        if secondary_states.get(CONF_ACCENT_ENTITY):
            available_activation_modes.append(AREA_STATE_ACCENT)
            available_blocking_states.append(AREA_STATE_ACCENT)

        dynamic_validators = {
            CONF_OVERHEAD_LIGHTS: cv.multi_select(self.all_lights),
            CONF_SLEEP_LIGHTS: cv.multi_select(self.all_lights),
            CONF_ACCENT_LIGHTS: cv.multi_select(self.all_lights),
            CONF_TASK_LIGHTS: cv.multi_select(self.all_lights),
            **{key: vol.In(available_activation_modes) for key in activation_keys},
            **{
                key: cv.multi_select(available_blocking_states)
                for key in blocking_state_keys
            },
            **{key: vol.In(LIGHT_GROUP_BRIGHTNESS_OPTIONS) for key in brightness_keys},
        }
        selectors = {
            CONF_OVERHEAD_LIGHTS: self._build_selector_entity_simple(
                self.all_lights, multiple=True
            ),
            CONF_SLEEP_LIGHTS: self._build_selector_entity_simple(
                self.all_lights, multiple=True
            ),
            CONF_ACCENT_LIGHTS: self._build_selector_entity_simple(
                self.all_lights, multiple=True
            ),
            CONF_TASK_LIGHTS: self._build_selector_entity_simple(
                self.all_lights, multiple=True
            ),
            **{
                key: self._build_selector_select(
                    available_activation_modes,
                    translation_key=SelectorTranslationKeys.LIGHT_ACTIVATION,
                )
                for key in activation_keys
            },
            **{
                key: self._build_selector_select(
                    available_blocking_states,
                    multiple=True,
                    translation_key=SelectorTranslationKeys.AREA_STATES,
                )
                for key in blocking_state_keys
            },
            **{
                key: self._build_selector_select(
                    LIGHT_GROUP_BRIGHTNESS_OPTIONS,
                    translation_key=SelectorTranslationKeys.LIGHT_BRIGHTNESS,
                )
                for key in brightness_keys
            },
        }

        def _validate_light_group_config(raw_input):
            """Reject unavailable and self-contradictory room-state rules."""
            for activation_key in activation_keys:
                if (
                    activation_key in raw_input
                    and raw_input[activation_key] not in available_activation_modes
                ):
                    raise vol.MultipleInvalid(
                        [vol.Invalid("unavailable activation", path=[activation_key])]
                    )
            for blockers_key in blocking_state_keys:
                invalid_blockers = set(raw_input.get(blockers_key, [])) - set(
                    available_blocking_states
                )
                if invalid_blockers:
                    raise vol.MultipleInvalid(
                        [vol.Invalid("unavailable blocker", path=[blockers_key])]
                    )

            activation_blocking_pairs = (
                (CONF_OVERHEAD_LIGHTS_ACTIVATION, CONF_OVERHEAD_LIGHTS_BLOCKING_STATES),
                (CONF_SLEEP_LIGHTS_ACTIVATION, CONF_SLEEP_LIGHTS_BLOCKING_STATES),
                (CONF_ACCENT_LIGHTS_ACTIVATION, CONF_ACCENT_LIGHTS_BLOCKING_STATES),
                (CONF_TASK_LIGHTS_ACTIVATION, CONF_TASK_LIGHTS_BLOCKING_STATES),
            )
            for activation_key, blockers_key in activation_blocking_pairs:
                activation = raw_input.get(activation_key)
                if activation in raw_input.get(blockers_key, []):
                    raise vol.MultipleInvalid(
                        [vol.Invalid("activation is blocked", path=[blockers_key])]
                    )

            return LIGHT_GROUP_FEATURE_SCHEMA(raw_input)

        return await self.do_feature_config(
            name=CONF_FEATURE_LIGHT_GROUPS,
            options=OPTIONS_LIGHT_GROUP,
            dynamic_validators=dynamic_validators,
            selectors=selectors,
            user_input=user_input,
            custom_schema=_validate_light_group_config,
        )

    async def async_step_feature_conf_fan_groups(self, user_input=None):
        """Configure the fan groups feature."""

        available_states = [AREA_STATE_OCCUPIED, AREA_STATE_EXTENDED]

        return await self.do_feature_config(
            name=CONF_FEATURE_FAN_GROUPS,
            options=(OPTIONS_FAN_GROUP),
            dynamic_validators={
                CONF_FAN_GROUPS_REQUIRED_STATE: vol.In(EMPTY_ENTRY + available_states),
            },
            selectors={
                CONF_FAN_GROUPS_REQUIRED_STATE: self._build_selector_select(
                    EMPTY_ENTRY + available_states,
                    translation_key=SelectorTranslationKeys.AREA_STATES,
                ),
                CONF_FAN_GROUPS_TRACKED_DEVICE_CLASS: self._build_selector_select(
                    EMPTY_ENTRY + FAN_GROUPS_ALLOWED_TRACKED_DEVICE_CLASS
                ),
                CONF_FAN_GROUPS_SETPOINT: self._build_selector_number(
                    unit_of_measurement=EMPTY_STRING, step=0.5
                ),
            },
            user_input=user_input,
        )

    def _current_area_entity_ids(self) -> set[str]:
        """Return entities assigned directly or through a device to this HA Area."""
        entity_registry = entityreg_async_get(self.hass)
        device_registry = devicereg_async_get(self.hass)
        entity_ids = {
            entry.entity_id
            for entry in entity_registry.entities.get_entries_for_area_id(self.area.id)
        }
        for device in async_entries_for_area(device_registry, self.area.id):
            entity_ids.update(
                entry.entity_id
                for entry in entity_registry.entities.get_entries_for_device_id(
                    device.id
                )
            )
        return entity_ids

    async def async_step_feature_conf_environment(self, user_input=None):
        """Configure Area Climate roles."""
        entity_registry = entityreg_async_get(self.hass)
        area_entity_ids = self._current_area_entity_ids()

        def is_adaptive_sensor(entity_id: str) -> bool:
            """Return whether an entity is generated by Adaptive Areas."""
            registry_entry = entity_registry.async_get(entity_id)
            return entity_id.startswith(
                f"{SENSOR_DOMAIN}.{ADAPTIVEAREAS_UNIQUEID_PREFIX}_"
            ) or bool(
                registry_entry
                and (
                    registry_entry.platform == DOMAIN
                    or registry_entry.config_entry_id == self.config_entry.entry_id
                )
            )

        sensor_candidates = sorted(
            entity_id
            for entity_id in area_entity_ids
            if entity_id.startswith(f"{SENSOR_DOMAIN}.")
            and not is_adaptive_sensor(entity_id)
        )

        def permitted_candidates(key: str) -> set[str]:
            """Preserve only this field's legacy selection outside the Area."""
            permitted = set(sensor_candidates)
            saved = self.area_options.get(key, [])
            if isinstance(saved, str):
                saved = [saved]
            permitted.update(
                entity_id
                for entity_id in saved
                if entity_id.startswith(f"{SENSOR_DOMAIN}.")
                and not is_adaptive_sensor(entity_id)
            )
            return permitted

        def device_class(entity_id: str) -> str | None:
            """Return state or registry device class for automatic suggestions."""
            state = self.hass.states.get(entity_id)
            value = state.attributes.get(ATTR_DEVICE_CLASS) if state else None
            if value is None and (entry := entity_registry.async_get(entity_id)):
                value = entry.device_class or entry.original_device_class
            return str(value) if value is not None else None

        display_options = dict(self.area_options)
        for key, expected_class in (
            (CONF_AREA_TEMPERATURE_SENSOR, "temperature"),
            (CONF_AREA_HUMIDITY_SENSOR, "humidity"),
        ):
            automatic = [
                entity_id
                for entity_id in sensor_candidates
                if device_class(entity_id) == expected_class
            ]
            if not display_options.get(key) and len(automatic) == 1:
                display_options[key] = automatic[0]

        window_entities = []
        for entity_id in area_entity_ids:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            domain = entity_id.split(".", 1)[0]
            if domain == BINARY_SENSOR_DOMAIN and state.attributes.get(
                ATTR_DEVICE_CLASS
            ) in ("window", "opening"):
                window_entities.append(entity_id)

        errors: dict[str, str] = {}
        if user_input is not None:
            raw_input = dict(user_input)
            for key in (
                CONF_AREA_TEMPERATURE_SENSOR,
                CONF_AREA_HUMIDITY_SENSOR,
                CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
            ):
                entity_id = raw_input.get(key, "")
                if entity_id and entity_id not in permitted_candidates(key):
                    errors[key] = "invalid_primary_source"
            if not errors:
                try:
                    validated = AREA_EVALUATION_OPTIONS_SCHEMA(raw_input)
                except vol.MultipleInvalid as validation:
                    errors = {
                        str(error.path[0]): str(error.msg)
                        for error in validation.errors
                    }
                else:
                    # Legacy explicit outdoor sources remain stored runtime
                    # fallbacks, but are no longer writable through regular UI.
                    validated.pop(CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE, None)
                    validated.pop(CONF_ENVIRONMENT_OUTDOOR_HUMIDITY, None)
                    if self.area.is_exterior():
                        for key in (
                            CONF_ROOM_CATEGORY,
                            CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
                            CONF_ENVIRONMENT_WINDOWS,
                            CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
                            CONF_ENVIRONMENT_HUMIDITY_DURATION,
                        ):
                            validated.pop(key, None)
                    if not errors:
                        self.area_options.update(validated)
                        return await self.async_step_show_menu()

        options = list(OPTIONS_AREA_EVALUATION)
        if self.area.is_exterior():
            exterior_hidden = {
                CONF_ROOM_CATEGORY,
                CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
                CONF_ENVIRONMENT_WINDOWS,
                CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
                CONF_ENVIRONMENT_HUMIDITY_DURATION,
            }
            options = [option for option in options if option[0] not in exterior_hidden]
        dynamic_validators = {}
        selectors = {}
        climate_sensor_keys = (
            CONF_AREA_TEMPERATURE_SENSOR,
            CONF_AREA_HUMIDITY_SENSOR,
            CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
        )
        dynamic_validators.update(
            {
                key: (
                    vol.In(EMPTY_ENTRY + sensor_candidates)
                    if not self.area_options.get(key)
                    else vol.In(EMPTY_ENTRY + sorted(permitted_candidates(key)))
                )
                for key in climate_sensor_keys
            }
        )
        selectors.update(
            {
                key: self._build_selector_entity_simple(EMPTY_ENTRY + sensor_candidates)
                for key in climate_sensor_keys
            }
        )
        selectors[CONF_ROOM_CATEGORY] = self._build_selector_select(
            list(RoomCategory),
            translation_key=SelectorTranslationKeys.ROOM_CATEGORY,
        )
        if not self.area.is_exterior():
            dynamic_validators.update(
                {
                    CONF_ENVIRONMENT_WINDOWS: cv.multi_select(sorted(window_entities)),
                }
            )
            selectors.update(
                {
                    CONF_ENVIRONMENT_WINDOWS: self._build_selector_entity_simple(
                        sorted(window_entities), multiple=True
                    ),
                    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA: self._build_selector_number(
                        unit_of_measurement="K", step=0.5
                    ),
                    CONF_ENVIRONMENT_HUMIDITY_DURATION: self._build_selector_number(
                        unit_of_measurement="minutes", max_value=1440
                    ),
                }
            )

        return self.async_show_form(
            step_id="feature_conf_environment",
            data_schema=self._build_options_schema(
                options=options,
                saved_options=display_options,
                dynamic_validators=dynamic_validators,
                selectors=selectors,
            ),
            errors=errors,
        )

    async def async_step_feature_conf_switch_groups(self, user_input=None):
        """Configure the switch groups feature."""

        available_states = BUILTIN_AREA_STATES.copy()
        secondary_states_config = self.area_options.get(CONF_SECONDARY_STATES)
        if not isinstance(secondary_states_config, dict):
            secondary_states_config = {}

        switch_states_exempt = [AREA_STATE_DARK]
        for extra_state, extra_state_entity in CONFIGURABLE_AREA_STATE_MAP.items():
            if extra_state in switch_states_exempt:
                continue
            if secondary_states_config.get(extra_state_entity, None):
                available_states.append(extra_state)

        all_switches = [
            entity_id
            for entity_id in self.all_entities
            if (
                entity_id.split(".")[0] == SWITCH_DOMAIN
                and not entity_id.split(".")[1].startswith(
                    ADAPTIVEAREAS_UNIQUEID_PREFIX
                )
            )
        ]

        return await self.do_feature_config(
            name=CONF_FEATURE_SWITCH_GROUPS,
            options=OPTIONS_SWITCH_GROUP,
            dynamic_validators={
                CONF_SLEEP_SWITCHES: cv.multi_select(all_switches),
                CONF_SLEEP_SWITCHES_STATES: cv.multi_select(available_states),
                CONF_SLEEP_SWITCHES_ACT_ON: cv.multi_select(LIGHT_GROUP_ACT_ON_OPTIONS),
                CONF_SLEEP_SWITCHES_ACTION: vol.In(SWITCH_GROUP_ACTION_OPTIONS),
                CONF_TASK_SWITCHES: cv.multi_select(all_switches),
                CONF_TASK_SWITCHES_STATES: cv.multi_select(available_states),
                CONF_TASK_SWITCHES_ACT_ON: cv.multi_select(LIGHT_GROUP_ACT_ON_OPTIONS),
                CONF_TASK_SWITCHES_ACTION: vol.In(SWITCH_GROUP_ACTION_OPTIONS),
            },
            selectors={
                CONF_SLEEP_SWITCHES: self._build_selector_entity_simple(
                    all_switches, multiple=True
                ),
                CONF_SLEEP_SWITCHES_STATES: self._build_selector_select(
                    available_states,
                    multiple=True,
                    translation_key=SelectorTranslationKeys.AREA_STATES,
                ),
                CONF_SLEEP_SWITCHES_ACT_ON: self._build_selector_select(
                    LIGHT_GROUP_ACT_ON_OPTIONS,
                    multiple=True,
                    translation_key=SelectorTranslationKeys.CONTROL_ON,
                ),
                CONF_SLEEP_SWITCHES_ACTION: self._build_selector_select(
                    SWITCH_GROUP_ACTION_OPTIONS
                ),
                CONF_TASK_SWITCHES: self._build_selector_entity_simple(
                    all_switches, multiple=True
                ),
                CONF_TASK_SWITCHES_STATES: self._build_selector_select(
                    available_states,
                    multiple=True,
                    translation_key=SelectorTranslationKeys.AREA_STATES,
                ),
                CONF_TASK_SWITCHES_ACT_ON: self._build_selector_select(
                    LIGHT_GROUP_ACT_ON_OPTIONS,
                    multiple=True,
                    translation_key=SelectorTranslationKeys.CONTROL_ON,
                ),
                CONF_TASK_SWITCHES_ACTION: self._build_selector_select(
                    SWITCH_GROUP_ACTION_OPTIONS
                ),
            },
            user_input=user_input,
        )

    async def async_step_feature_conf_climate_control(self, user_input=None):
        """Configure the climate control feature."""

        all_climate_entities = [
            entity_id
            for entity_id in self.all_entities
            if (
                entity_id.split(".")[0] == CLIMATE_DOMAIN
                and not entity_id.split(".")[1].startswith(
                    ADAPTIVEAREAS_UNIQUEID_PREFIX
                )
            )
        ]

        return await self.do_feature_config(
            name=AdaptiveAreasFeatures.CLIMATE_CONTROL,
            options=OPTIONS_CLIMATE_CONTROL_ENTITY_SELECT,
            custom_schema=CLIMATE_CONTROL_FEATURE_SCHEMA_ENTITY_SELECT,
            merge_options=True,
            dynamic_validators={
                CONF_CLIMATE_CONTROL_ENTITY_ID: vol.In(all_climate_entities),
            },
            selectors={
                CONF_CLIMATE_CONTROL_ENTITY_ID: self._build_selector_entity_simple(
                    all_climate_entities
                )
            },
            user_input=user_input,
            return_to=self.async_step_feature_conf_climate_control_select_presets,
        )

    async def async_step_feature_conf_climate_control_select_presets(
        self, user_input=None
    ):
        """Configure the climate control feature."""

        climate_entity_id: str | None = None

        if (
            ATTR_ENTITY_ID
            in self.area_options[CONF_ENABLED_FEATURES][
                AdaptiveAreasFeatures.CLIMATE_CONTROL
            ]
        ):
            climate_entity_id = self.area_options[CONF_ENABLED_FEATURES][
                AdaptiveAreasFeatures.CLIMATE_CONTROL
            ][ATTR_ENTITY_ID]

        if not climate_entity_id:
            return self.async_abort(reason="no_entity_selected")

        entity_registry = entityreg_async_get(self.hass)
        entity_object = entity_registry.async_get(climate_entity_id)

        if not entity_object:
            return self.async_abort(reason="invalid_entity")

        if (
            not entity_object.capabilities
            or ATTR_PRESET_MODES not in entity_object.capabilities
        ):
            return self.async_abort(reason="climate_no_preset_support")

        available_preset_modes = entity_object.capabilities[ATTR_PRESET_MODES]
        _LOGGER.debug(
            "OptionsFlow (%s): Available preset modes for %s: %s",
            self.area.name,
            climate_entity_id,
            str(available_preset_modes),
        )

        selectors = {
            CONF_CLIMATE_CONTROL_PRESET_CLEAR: self._build_selector_select(
                EMPTY_ENTRY + available_preset_modes,
                translation_key=SelectorTranslationKeys.CLIMATE_PRESET_LIST,
            ),
            CONF_CLIMATE_CONTROL_PRESET_OCCUPIED: self._build_selector_select(
                EMPTY_ENTRY + available_preset_modes,
                translation_key=SelectorTranslationKeys.CLIMATE_PRESET_LIST,
            ),
            CONF_CLIMATE_CONTROL_PRESET_SLEEP: self._build_selector_select(
                EMPTY_ENTRY + available_preset_modes,
                translation_key=SelectorTranslationKeys.CLIMATE_PRESET_LIST,
            ),
            CONF_CLIMATE_CONTROL_PRESET_EXTENDED: self._build_selector_select(
                EMPTY_ENTRY + available_preset_modes,
                translation_key=SelectorTranslationKeys.CLIMATE_PRESET_LIST,
            ),
            CONF_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD: self._build_selector_number(
                unit_of_measurement="minutes"
            ),
        }

        return await self.do_feature_config(
            name=CONF_FEATURE_CLIMATE_CONTROL,
            step_name="feature_conf_climate_control_select_presets",
            options=OPTIONS_CLIMATE_CONTROL,
            custom_schema=CLIMATE_CONTROL_FEATURE_SCHEMA_PRESET_SELECT,
            merge_options=True,
            dynamic_validators={
                CONF_CLIMATE_CONTROL_PRESET_CLEAR: vol.In(
                    EMPTY_ENTRY + available_preset_modes
                ),
                CONF_CLIMATE_CONTROL_PRESET_OCCUPIED: vol.In(
                    EMPTY_ENTRY + available_preset_modes
                ),
                CONF_CLIMATE_CONTROL_PRESET_SLEEP: vol.In(
                    EMPTY_ENTRY + available_preset_modes
                ),
                CONF_CLIMATE_CONTROL_PRESET_EXTENDED: vol.In(
                    EMPTY_ENTRY + available_preset_modes
                ),
                CONF_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD: cv.positive_int,
            },
            selectors=selectors,
            user_input=user_input,
        )

    async def async_step_feature_conf_health(self, user_input=None):
        """Configure the climate groups feature."""

        return await self.do_feature_config(
            name=CONF_FEATURE_HEALTH,
            options=OPTIONS_HEALTH_SENSOR,
            dynamic_validators={
                CONF_HEALTH_SENSOR_DEVICE_CLASSES: vol.In(
                    EMPTY_ENTRY + DISTRESS_SENSOR_CLASSES
                ),
            },
            selectors={
                CONF_HEALTH_SENSOR_DEVICE_CLASSES: self._build_selector_select(
                    EMPTY_ENTRY + DISTRESS_SENSOR_CLASSES, multiple=True
                )
            },
            user_input=user_input,
        )

    async def async_step_feature_conf_area_aware_media_player(self, user_input=None):
        """Configure the area aware media player feature."""

        available_states = [AREA_STATE_OCCUPIED, AREA_STATE_EXTENDED, AREA_STATE_SLEEP]

        return await self.do_feature_config(
            name=CONF_FEATURE_AREA_AWARE_MEDIA_PLAYER,
            options=OPTIONS_AREA_AWARE_MEDIA_PLAYER,
            dynamic_validators={
                CONF_NOTIFICATION_DEVICES: cv.multi_select(self.all_media_players),
                CONF_NOTIFY_STATES: cv.multi_select(available_states),
            },
            selectors={
                CONF_NOTIFICATION_DEVICES: self._build_selector_entity_simple(
                    self.all_media_players, multiple=True
                ),
                CONF_NOTIFY_STATES: self._build_selector_select(
                    available_states,
                    multiple=True,
                    translation_key=SelectorTranslationKeys.AREA_STATES,
                ),
            },
            user_input=user_input,
        )

    async def async_step_feature_conf_aggregates(self, user_input=None):
        """Configure the sensor aggregates feature."""

        selectors = {
            CONF_AGGREGATES_MIN_ENTITIES: self._build_selector_number(
                unit_of_measurement="entities"
            ),
            CONF_AGGREGATES_BINARY_SENSOR_DEVICE_CLASSES: self._build_selector_select(
                sorted(ALL_BINARY_SENSOR_DEVICE_CLASSES), multiple=True
            ),
            CONF_AGGREGATES_SENSOR_DEVICE_CLASSES: self._build_selector_select(
                sorted(ALL_SENSOR_DEVICE_CLASSES), multiple=True
            ),
            CONF_AGGREGATES_ILLUMINANCE_THRESHOLD: self._build_selector_number(
                unit_of_measurement="lx",
                mode=NumberSelectorMode.SLIDER,
                min_value=0,
                max_value=1000,
            ),
            CONF_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS: self._build_selector_number(
                unit_of_measurement="%",
                mode=NumberSelectorMode.SLIDER,
                min_value=0,
                max_value=100,
            ),
        }

        return await self.do_feature_config(
            name=CONF_FEATURE_AGGREGATION,
            options=OPTIONS_AGGREGATES,
            selectors=selectors,
            user_input=user_input,
        )

    async def async_step_feature_conf_presence_hold(self, user_input=None):
        """Configure the sensor presence_hold feature."""

        selectors = {
            CONF_PRESENCE_HOLD_TIMEOUT: self._build_selector_number(
                min_value=0, unit_of_measurement="minutes"
            )
        }

        return await self.do_feature_config(
            name=CONF_FEATURE_PRESENCE_HOLD,
            options=OPTIONS_PRESENCE_HOLD,
            selectors=selectors,
            user_input=user_input,
        )

    async def async_step_feature_conf_room_usage(self, user_input=None):
        """Configure the Cleaning Tracker feature."""
        selectors = {
            CONF_PRESENCE_MINUTES_TO_DUE: self._build_selector_number(
                min_value=1 / 60,
                step=1 / 60,
                unit_of_measurement="minutes",
            )
        }
        return await self.do_feature_config(
            name=CONF_FEATURE_ROOM_USAGE,
            options=OPTIONS_ROOM_USAGE,
            selectors=selectors,
            user_input=user_input,
        )

    async def async_step_feature_conf_ble_trackers(self, user_input=None):
        """Configure the sensor BLE trackers feature."""

        selectors = {
            CONF_BLE_TRACKER_ENTITIES: self._build_selector_entity_simple(
                [
                    entity_id
                    for entity_id in self.all_entities
                    if (
                        entity_id.split(".")[0] == SENSOR_DOMAIN
                        and not entity_id.split(".")[1].startswith(
                            ADAPTIVEAREAS_UNIQUEID_PREFIX
                        )
                    )
                ],
                multiple=True,
            ),
        }

        return await self.do_feature_config(
            name=CONF_FEATURE_BLE_TRACKERS,
            options=OPTIONS_BLE_TRACKERS,
            selectors=selectors,
            user_input=user_input,
        )

    async def async_step_feature_conf_wasp_in_a_box(self, user_input=None):
        """Configure the sensor Wasp in a Box feature."""

        selectors = {
            CONF_WASP_IN_A_BOX_DELAY: self._build_selector_number(
                min_value=0, unit_of_measurement="seconds"
            ),
            CONF_WASP_IN_A_BOX_WASP_TIMEOUT: self._build_selector_number(
                min_value=0, unit_of_measurement="minutes"
            ),
            CONF_WASP_IN_A_BOX_WASP_DEVICE_CLASSES: self._build_selector_select(
                sorted(WASP_IN_A_BOX_WASP_DEVICE_CLASSES), multiple=True
            ),
        }

        return await self.do_feature_config(
            name=CONF_FEATURE_WASP_IN_A_BOX,
            options=OPTIONS_WASP_IN_A_BOX,
            selectors=selectors,
            user_input=user_input,
        )

    async def do_feature_config(
        self,
        *,
        name,
        options,
        dynamic_validators=None,
        selectors=None,
        user_input=None,
        custom_schema=None,
        return_to=None,
        merge_options=False,
        step_name=None,
    ):
        """Execute step for a generic feature."""
        errors: dict[str, str] = {}

        if not dynamic_validators:
            dynamic_validators = {}

        if not selectors:
            selectors = {}

        if user_input is not None:
            _LOGGER.debug(
                "OptionsFlow: Validating %s feature config for area %s: %s",
                name,
                self.area.name,
                str(user_input),
            )
            try:
                if custom_schema:
                    validated_input = custom_schema(user_input)
                else:
                    if not CONFIGURABLE_FEATURES[name]:
                        raise ValueError(f"No schema found for {name}")
                    validated_input = CONFIGURABLE_FEATURES[name](user_input)
            except vol.MultipleInvalid as validation:
                errors = {
                    str(error.path[0]): "malformed_input" for error in validation.errors
                }
                _LOGGER.debug("OptionsFlow: Found the following errors: %s", errors)
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.warning(
                    "OptionsFlow: Unexpected error caught on area %s: %s",
                    self.area.name,
                    str(e),
                )
            else:
                _LOGGER.debug(
                    "OptionsFlow: Saving %s feature config for area %s: %s",
                    name,
                    self.area.name,
                    str(validated_input),
                )
                if merge_options:
                    if name not in self.area_options[CONF_ENABLED_FEATURES]:
                        self.area_options[CONF_ENABLED_FEATURES][name] = {}

                    self.area_options[CONF_ENABLED_FEATURES][name].update(
                        validated_input
                    )
                else:
                    self.area_options[CONF_ENABLED_FEATURES][name] = validated_input

                _LOGGER.debug(
                    "%s: Area options for %s: %s",
                    self.area.name,
                    name,
                    self.area_options[CONF_ENABLED_FEATURES][name],
                )

                if return_to:
                    return await return_to()

                return await self.async_step_show_menu()

        _LOGGER.debug(
            "OptionsFlow: Config entry options for area %s: %s",
            self.area.name,
            str(self.config_entry.options),
        )

        saved_options = self.area_options.get(CONF_ENABLED_FEATURES, {})

        if not step_name:
            step_name = f"feature_conf_{name}"

        return self.async_show_form(
            step_id=step_name,
            data_schema=self._build_options_schema(
                options=options,
                saved_options=saved_options.get(name, {}),
                dynamic_validators=dynamic_validators,
                selectors=selectors,
            ),
            errors=errors,
        )
