"""Adaptive Areas component for Home Assistant."""

from collections.abc import Callable
from datetime import UTC, datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_NAME
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import (
    EVENT_DEVICE_REGISTRY_UPDATED,
    EventDeviceRegistryUpdatedData,
    async_entries_for_area,
    async_get as async_get_device_registry,
)
from homeassistant.helpers.area_registry import EVENT_AREA_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import (
    EVENT_ENTITY_REGISTRY_UPDATED,
    EventEntityRegistryUpdatedData,
    async_get as async_get_entity_registry,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.floor_registry import EVENT_FLOOR_REGISTRY_UPDATED

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    AREA_TYPE_META,
    AREA_TYPE_INTERIOR,
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_ENABLED_FEATURES,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_DISABLED_FANS,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_FEATURE_ENVIRONMENT,
    CONF_FEATURE_ROOM_USAGE,
    CONF_FEATURE_SWITCH_GROUPS,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_EXCLUDE_ENTITIES,
    CONF_ROOM_CATEGORY,
    CONF_PRESENCE_MINUTES_TO_DUE,
    CONF_PRESENCE_SECONDS_TO_DUE,
    CONF_TRACK_ROOM_USAGE,
    CONF_RELOAD_ON_REGISTRY_CHANGE,
    CONF_SLEEP_SWITCHES,
    CONF_SLEEP_SWITCHES_ACTION,
    CONF_SLEEP_SWITCHES_ACT_ON,
    CONF_SLEEP_SWITCHES_STATES,
    CONF_TASK_SWITCHES,
    CONF_TASK_SWITCHES_ACTION,
    CONF_TASK_SWITCHES_ACT_ON,
    CONF_TASK_SWITCHES_STATES,
    CONF_TYPE,
    DATA_AREA_OBJECT,
    DATA_TRACKED_LISTENERS,
    DEFAULT_RELOAD_ON_REGISTRY_CHANGE,
    DEFAULT_ROOM_CATEGORY,
    DEFAULT_PRESENCE_MINUTES_TO_DUE,
    MODULE_DATA,
    AdaptiveConfigEntryVersion,
)
from custom_components.adaptive_areas.helpers.area import (
    get_adaptive_area_for_config_entry,
)
from custom_components.adaptive_areas.helpers.light_groups import (
    migrate_light_groups_in_config,
)
from custom_components.adaptive_areas.repairs import (
    async_evaluate_config_entry,
    async_remove_config_entry_issues,
)
from custom_components.adaptive_areas.services import (
    async_setup_services,
    async_unload_services,
)

_LOGGER = logging.getLogger(__name__)

_MIGRATED_AREA_EVALUATION_KEYS = (
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_ENVIRONMENT_PASSIVE_COOLING_DELTA,
    CONF_ENVIRONMENT_HUMIDITY_DURATION,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_DISABLED_FANS,
)

_REMOVED_MANUAL_POLLUTANT_KEYS = (
    "manual_co2_sensors",
    "manual_pm25_sensors",
    "manual_pm10_sensors",
    "manual_co_sensors",
    "manual_no2_sensors",
    "manual_ozone_sensors",
    "manual_voc_sensors",
    "manual_aqi_sensors",
    "manual_voc_parts_sensors",
    "manual_co2_unit",
    "manual_pm25_unit",
    "manual_pm10_unit",
    "manual_co_unit",
    "manual_no2_unit",
    "manual_ozone_unit",
    "manual_voc_unit",
)


def _eligible_primary_sources(
    hass: HomeAssistant, config_entry: ConfigEntry, config: dict[str, Any]
) -> dict[SensorDeviceClass, list[str]]:
    """Find unambiguous RC5 Area climate candidates without guessing."""
    area_id = config.get(CONF_ID)
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    entity_ids = {
        entry.entity_id
        for entry in entity_registry.entities.get_entries_for_area_id(area_id)
    }
    for device in async_entries_for_area(device_registry, area_id):
        entity_ids.update(
            entry.entity_id
            for entry in entity_registry.entities.get_entries_for_device_id(device.id)
        )
    entity_ids.update(config.get(CONF_INCLUDE_ENTITIES, []))
    excluded = set(config.get(CONF_EXCLUDE_ENTITIES, []))
    result = {
        SensorDeviceClass.TEMPERATURE: [],
        SensorDeviceClass.HUMIDITY: [],
    }
    for entity_id in sorted(entity_ids - excluded):
        entry = entity_registry.async_get(entity_id)
        state = hass.states.get(entity_id)
        if not entity_id.startswith("sensor.") or state is None:
            continue
        if entry is not None and (
            entry.disabled or entry.config_entry_id == config_entry.entry_id
        ):
            continue
        device_class = state.attributes.get(ATTR_DEVICE_CLASS)
        if device_class in result:
            result[device_class].append(entity_id)
    return result


def _migrate_primary_area_sources(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    data: dict[str, Any],
    options: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool, bool]:
    """Select only a single deterministic RC5 candidate per indoor dimension."""
    combined = {**data, **options}
    if combined.get(CONF_TYPE) != AREA_TYPE_INTERIOR:
        return data, options, False, False
    candidates = _eligible_primary_sources(hass, config_entry, combined)
    migrated_data = dict(data)
    migrated_options = dict(options)
    target = migrated_options if options else migrated_data
    data_changed = False
    options_changed = False
    for key, device_class in (
        (CONF_AREA_TEMPERATURE_SENSOR, SensorDeviceClass.TEMPERATURE),
        (CONF_AREA_HUMIDITY_SENSOR, SensorDeviceClass.HUMIDITY),
    ):
        if key in combined or len(candidates[device_class]) != 1:
            continue
        target[key] = candidates[device_class][0]
        if options:
            options_changed = True
        else:
            data_changed = True
    return migrated_data, migrated_options, data_changed, options_changed


def _migrate_area_evaluation_config(
    config: dict[str, Any] | None,
    *,
    regular_area: bool = True,
) -> tuple[dict[str, Any], bool]:
    """Flatten legacy settings while preserving explicit feature intent."""
    if not isinstance(config, dict):
        return {}, False
    migrated = dict(config)
    changed = False
    enabled = migrated.get(CONF_ENABLED_FEATURES)
    if isinstance(enabled, dict) and CONF_FEATURE_ENVIRONMENT in enabled:
        enabled = dict(enabled)
        legacy = enabled.get(CONF_FEATURE_ENVIRONMENT)
        enabled[CONF_FEATURE_ENVIRONMENT] = {}
        migrated[CONF_ENABLED_FEATURES] = enabled
        if isinstance(legacy, dict):
            for key in _MIGRATED_AREA_EVALUATION_KEYS:
                if key in legacy and key not in migrated:
                    migrated[key] = legacy[key]
                    changed = True
            if legacy:
                changed = True
    if regular_area and CONF_ROOM_CATEGORY not in migrated:
        migrated[CONF_ROOM_CATEGORY] = DEFAULT_ROOM_CATEGORY
        changed = True
    return migrated, changed


def _remove_manual_pollutant_config(
    config: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Remove superseded pollutant type and unit overrides."""
    migrated = dict(config)
    changed = False
    for key in _REMOVED_MANUAL_POLLUTANT_KEYS:
        if key in migrated:
            migrated.pop(key)
            changed = True
    return migrated, changed


def _migrate_room_usage_feature(
    data: dict[str, Any], options: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], bool, bool]:
    """Move legacy top-level Room Usage toggle into enabled features."""

    def migrate_threshold(feature_config: dict[str, Any]) -> bool:
        """Convert a legacy seconds threshold to minutes in place."""
        legacy_seconds = feature_config.pop(CONF_PRESENCE_SECONDS_TO_DUE, None)
        if CONF_PRESENCE_MINUTES_TO_DUE in feature_config:
            return legacy_seconds is not None
        try:
            minutes = (
                max(1 / 60, float(legacy_seconds) / 60)
                if legacy_seconds is not None
                else DEFAULT_PRESENCE_MINUTES_TO_DUE
            )
        except TypeError, ValueError:
            minutes = DEFAULT_PRESENCE_MINUTES_TO_DUE
        feature_config[CONF_PRESENCE_MINUTES_TO_DUE] = minutes
        return True

    migrated_data = dict(data)
    migrated_options = dict(options)
    legacy_enabled = bool(
        migrated_options.get(
            CONF_TRACK_ROOM_USAGE,
            migrated_data.get(CONF_TRACK_ROOM_USAGE, False),
        )
    )
    data_changed = CONF_TRACK_ROOM_USAGE in migrated_data
    options_changed = CONF_TRACK_ROOM_USAGE in migrated_options
    migrated_data.pop(CONF_TRACK_ROOM_USAGE, None)
    migrated_options.pop(CONF_TRACK_ROOM_USAGE, None)

    data_features = dict(migrated_data.get(CONF_ENABLED_FEATURES, {}))
    options_features = dict(migrated_options.get(CONF_ENABLED_FEATURES, {}))
    configured_in_options = CONF_FEATURE_ROOM_USAGE in options_features
    configured_in_data = CONF_FEATURE_ROOM_USAGE in data_features

    if legacy_enabled and not (configured_in_options or configured_in_data):
        if options:
            options_features[CONF_FEATURE_ROOM_USAGE] = {}
            configured_in_options = True
            options_changed = True
        else:
            data_features[CONF_FEATURE_ROOM_USAGE] = {}
            configured_in_data = True
            data_changed = True

    if configured_in_options:
        feature_config = options_features.get(CONF_FEATURE_ROOM_USAGE)
        feature_config = (
            dict(feature_config) if isinstance(feature_config, dict) else {}
        )
        if migrate_threshold(feature_config):
            options_changed = True
        options_features[CONF_FEATURE_ROOM_USAGE] = feature_config
        migrated_options[CONF_ENABLED_FEATURES] = options_features
    if configured_in_data:
        feature_config = data_features.get(CONF_FEATURE_ROOM_USAGE)
        feature_config = (
            dict(feature_config) if isinstance(feature_config, dict) else {}
        )
        if migrate_threshold(feature_config):
            data_changed = True
        data_features[CONF_FEATURE_ROOM_USAGE] = feature_config
        migrated_data[CONF_ENABLED_FEATURES] = data_features
    return migrated_data, migrated_options, data_changed, options_changed


def _sanitize_switch_groups_options(
    options: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    """Remove persisted switch-group related settings from options."""
    if not isinstance(options, dict):
        return {}, False

    cleaned_options = dict(options)
    changed = False

    enabled_features = cleaned_options.get(CONF_ENABLED_FEATURES, {})
    if (
        isinstance(enabled_features, dict)
        and CONF_FEATURE_SWITCH_GROUPS in enabled_features
    ):
        updated_enabled_features = dict(enabled_features)
        updated_enabled_features.pop(CONF_FEATURE_SWITCH_GROUPS, None)
        cleaned_options[CONF_ENABLED_FEATURES] = updated_enabled_features
        changed = True

    # Legacy safety net: remove any old top-level switch-group keys if present.
    switch_group_keys = (
        CONF_SLEEP_SWITCHES,
        CONF_SLEEP_SWITCHES_STATES,
        CONF_SLEEP_SWITCHES_ACT_ON,
        CONF_SLEEP_SWITCHES_ACTION,
        CONF_TASK_SWITCHES,
        CONF_TASK_SWITCHES_STATES,
        CONF_TASK_SWITCHES_ACT_ON,
        CONF_TASK_SWITCHES_ACTION,
    )
    for key in switch_group_keys:
        if key in cleaned_options:
            cleaned_options.pop(key)
            changed = True

    return cleaned_options, changed


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up the component."""

    remove_reload_timer: Callable[[], None] | None = None
    remove_repair_timer: Callable[[], None] | None = None

    cleaned_options, options_changed = _sanitize_switch_groups_options(
        dict(config_entry.options)
    )
    if options_changed:
        _LOGGER.info(
            "%s: Removing persisted switch groups settings from config entry options.",
            config_entry.data[ATTR_NAME],
        )
        hass.config_entries.async_update_entry(config_entry, options=cleaned_options)

    @callback
    def _async_reload_entry(*args, **kwargs) -> None:
        """Coalesce registry events into one config entry reload."""
        nonlocal remove_reload_timer

        if not hass.is_running or remove_reload_timer is not None:
            return

        @callback
        def _reload(_now=None) -> None:
            nonlocal remove_reload_timer
            remove_reload_timer = None
            hass.config_entries.async_update_entry(
                config_entry,
                data={**config_entry.data, "entity_ts": datetime.now(UTC)},
            )

        remove_reload_timer = async_call_later(hass, 0, _reload)

    @callback
    def _cancel_scheduled_reload() -> None:
        nonlocal remove_reload_timer
        if remove_reload_timer is not None:
            remove_reload_timer()
            remove_reload_timer = None

    @callback
    def _async_schedule_repair_evaluation(*args, **kwargs) -> None:
        """Coalesce registry events into one Repair evaluation."""
        nonlocal remove_repair_timer
        if not hass.is_running or remove_repair_timer is not None:
            return

        @callback
        def _evaluate(_now=None) -> None:
            nonlocal remove_repair_timer
            remove_repair_timer = None
            hass.async_create_task(
                async_evaluate_config_entry(hass, config_entry),
                f"evaluate repairs for {config_entry.entry_id}",
            )

        remove_repair_timer = async_call_later(hass, 0, _evaluate)

    @callback
    def _cancel_scheduled_repair_evaluation() -> None:
        nonlocal remove_repair_timer
        if remove_repair_timer is not None:
            remove_repair_timer()
            remove_repair_timer = None

    @callback
    def _async_registry_updated(
        event: (
            Event[EventEntityRegistryUpdatedData]
            | Event[EventDeviceRegistryUpdatedData]
        ),
    ) -> None:
        """Reload integration when entity registry is updated."""

        _async_schedule_repair_evaluation()

        area_data: dict[str, Any] = dict(config_entry.data)
        if config_entry.options:
            area_data.update(config_entry.options)

        # Check if disabled
        if not area_data.get(
            CONF_RELOAD_ON_REGISTRY_CHANGE, DEFAULT_RELOAD_ON_REGISTRY_CHANGE
        ):
            _LOGGER.debug(
                "%s: Auto-Reloading disabled for this area skipping...",
                config_entry.data[ATTR_NAME],
            )
            return

        _LOGGER.debug(
            "%s: Reloading entry due entity registry change",
            config_entry.data[ATTR_NAME],
        )

        _async_reload_entry()

    async def _async_setup_integration(*args, **kwargs) -> bool:
        """Load integration when Hass has finished starting."""
        _LOGGER.debug("Setting up entry for %s", config_entry.data[ATTR_NAME])

        repair_summary = await async_evaluate_config_entry(hass, config_entry)
        if repair_summary["missing_area"]:
            _LOGGER.error("Unable to set up Adaptive Areas entry: area is missing")
            return False

        adaptive_area: AdaptiveArea | None = get_adaptive_area_for_config_entry(
            hass, config_entry
        )
        if adaptive_area is None:
            return False
        await adaptive_area.initialize()

        _LOGGER.debug(
            "%s: Adaptive Area (%s) created: %s",
            adaptive_area.name,
            adaptive_area.id,
            str(adaptive_area.config),
        )

        # Setup config uptate listener
        tracked_listeners: list[Callable] = []
        tracked_listeners.append(config_entry.add_update_listener(async_update_options))
        tracked_listeners.append(_cancel_scheduled_reload)
        tracked_listeners.append(_cancel_scheduled_repair_evaluation)
        for event_type in (
            EVENT_ENTITY_REGISTRY_UPDATED,
            EVENT_DEVICE_REGISTRY_UPDATED,
            EVENT_AREA_REGISTRY_UPDATED,
            EVENT_FLOOR_REGISTRY_UPDATED,
        ):
            tracked_listeners.append(
                hass.bus.async_listen(event_type, _async_schedule_repair_evaluation)
            )

        @callback
        def _async_backing_registry_updated(event: Event) -> None:
            """Reload when the backing Area or floor changes."""
            _async_schedule_repair_evaluation()
            target_id = event.data.get("area_id") or event.data.get("floor_id")
            if target_id == adaptive_area.id:
                _async_reload_entry()

        # Watch for area changes.
        if not adaptive_area.is_meta():
            tracked_listeners.append(
                hass.bus.async_listen(
                    EVENT_AREA_REGISTRY_UPDATED, _async_backing_registry_updated
                )
            )
            tracked_listeners.append(
                hass.bus.async_listen(
                    EVENT_ENTITY_REGISTRY_UPDATED,
                    _async_registry_updated,
                    adaptive_area.make_entity_registry_filter(),
                )
            )
            tracked_listeners.append(
                hass.bus.async_listen(
                    EVENT_DEVICE_REGISTRY_UPDATED,
                    _async_registry_updated,
                    adaptive_area.make_device_registry_filter(),
                )
            )
        elif adaptive_area.floor_id:
            tracked_listeners.append(
                hass.bus.async_listen(
                    EVENT_FLOOR_REGISTRY_UPDATED, _async_backing_registry_updated
                )
            )
        hass.data[MODULE_DATA][config_entry.entry_id] = {
            DATA_AREA_OBJECT: adaptive_area,
            DATA_TRACKED_LISTENERS: tracked_listeners,
        }

        # Setup platforms
        await hass.config_entries.async_forward_entry_setups(
            config_entry, adaptive_area.available_platforms()
        )
        async_setup_services(hass)
        return True

    hass.data.setdefault(MODULE_DATA, {})

    return await _async_setup_integration()


async def async_update_options(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update options."""
    _LOGGER.debug(
        "Detected options change for entry %s, reloading", config_entry.entry_id
    )
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    if MODULE_DATA not in hass.data:
        _LOGGER.warning(
            "Module data object for Adaptive Areas not found, possibly already removed."
        )
        return False

    data = hass.data[MODULE_DATA]

    if config_entry.entry_id not in data:
        _LOGGER.debug(
            "Config entry '%s' not on data dictionary, probably already unloaded. Skipping.",
            config_entry.entry_id,
        )
        return True

    area_data = data[config_entry.entry_id]
    area = area_data[DATA_AREA_OBJECT]

    all_unloaded = await hass.config_entries.async_unload_platforms(
        config_entry, area.available_platforms()
    )

    if area.room_usage is not None:
        await area.room_usage.async_unload()
    area.unload()

    for tracked_listener in area_data[DATA_TRACKED_LISTENERS]:
        tracked_listener()

    if all_unloaded:
        data.pop(config_entry.entry_id)

    if not data:
        async_unload_services(hass)
        hass.data.pop(MODULE_DATA)

    return True


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Remove Repair issues owned by a deleted config entry."""
    await async_remove_config_entry_issues(hass, config_entry)


# Update config version
async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.info(
        "%s: Migrating configuration from version %s.%s, current config: %s",
        config_entry.data[ATTR_NAME],
        config_entry.version,
        config_entry.minor_version,
        str(config_entry.data),
    )

    if config_entry.version > AdaptiveConfigEntryVersion.MAJOR:
        # This means the user has downgraded from a future version
        _LOGGER.warning(
            "%s: Major version downgrade detection, skipping migration.",
            config_entry.data[ATTR_NAME],
        )

        return False

    migrated_data, data_changed = migrate_light_groups_in_config(
        dict(config_entry.data)
    )
    migrated_options, options_changed = migrate_light_groups_in_config(
        dict(config_entry.options)
    )
    regular_area = config_entry.data.get(CONF_TYPE) != AREA_TYPE_META
    migrated_data, evaluation_data_changed = _migrate_area_evaluation_config(
        migrated_data, regular_area=regular_area
    )
    migrated_options, evaluation_options_changed = _migrate_area_evaluation_config(
        migrated_options, regular_area=regular_area
    )
    data_changed |= evaluation_data_changed
    options_changed |= evaluation_options_changed
    migrated_data, pollutant_data_changed = _remove_manual_pollutant_config(
        migrated_data
    )
    migrated_options, pollutant_options_changed = _remove_manual_pollutant_config(
        migrated_options
    )
    data_changed |= pollutant_data_changed
    options_changed |= pollutant_options_changed
    (
        migrated_data,
        migrated_options,
        usage_data_changed,
        usage_options_changed,
    ) = _migrate_room_usage_feature(migrated_data, migrated_options)
    data_changed |= usage_data_changed
    options_changed |= usage_options_changed
    if config_entry.minor_version < 4:
        (
            migrated_data,
            migrated_options,
            primary_data_changed,
            primary_options_changed,
        ) = _migrate_primary_area_sources(
            hass, config_entry, migrated_data, migrated_options
        )
        data_changed |= primary_data_changed
        options_changed |= primary_options_changed

    update: dict[str, Any] = {
        "minor_version": AdaptiveConfigEntryVersion.MINOR,
        "version": AdaptiveConfigEntryVersion.MAJOR,
    }
    if data_changed:
        update["data"] = migrated_data
    if options_changed:
        update["options"] = migrated_options

    hass.config_entries.async_update_entry(config_entry, **update)

    _LOGGER.info(
        "Migration to configuration version %s.%s successful: %s",
        config_entry.version,
        config_entry.minor_version,
        str(config_entry.data),
    )

    return True
