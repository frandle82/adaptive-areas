"""Home Assistant Repair issue detection for Adaptive Areas."""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.floor_registry import async_get as async_get_floor_registry

from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_DARK_ENTITY,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_RETAINED_FEATURES,
    CONF_SECONDARY_STATES,
    LIGHT_GROUP_BRIGHTNESS,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
    AREA_TYPE_META,
    CONF_ACCENT_ENTITY,
    CONF_ACCENT_LIGHTS,
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_BLE_TRACKER_ENTITIES,
    CONF_CLIMATE_CONTROL_ENTITY_ID,
    CONF_AREA_ILLUMINANCE_SENSOR,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_WINDOWS,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_DISABLED_FANS,
    CONF_KEEP_ONLY_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    CONF_FEATURE_BLE_TRACKERS,
    CONF_FEATURE_CLIMATE_CONTROL,
    CONF_FEATURE_ENVIRONMENT,
    CONF_FEATURE_PRESENCE_HOLD,
    CONF_FEATURE_WASP_IN_A_BOX,
    CONF_NOTIFICATION_DEVICES,
    CONF_OVERHEAD_LIGHTS,
    CONF_PRESENCE_CONTROL_ENTITIES,
    CONF_SLEEP_ENTITY,
    CONF_SLEEP_LIGHTS,
    CONF_SLEEP_SWITCHES,
    CONF_TASK_LIGHTS,
    CONF_TASK_SWITCHES,
    CONF_TYPE,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
    MetaAreaType,
)
from custom_components.adaptive_areas.helpers.brightness import (
    light_policy_config_from_feature,
)
from custom_components.adaptive_areas.helpers.environment import (
    POLLUTANT_NAMES,
    get_environment_source_capabilities,
)
from custom_components.adaptive_areas.helpers.sources import (
    physical_presence_source_ids,
)

ISSUE_MISSING_AREA = "missing_area"
ISSUE_MISSING_ENTITIES = "missing_entities"
ISSUE_NO_PRESENCE_SOURCES = "no_presence_sources"
ISSUE_ENVIRONMENT_WITHOUT_SOURCES = "environment_without_sources"
ISSUE_INVALID_ENTITIES = "invalid_entity_references"
ISSUE_INVALID_FEATURE_CONFIGURATION = "invalid_feature_configuration"
ISSUE_BRIGHTNESS_CONFIGURATION = "brightness_configuration"
ISSUE_BRIGHTNESS_SOURCE_MISSING = "brightness_source_missing"
ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION = "single_global_entry_migration"

REPAIR_ISSUE_CATEGORIES = (
    ISSUE_MISSING_AREA,
    ISSUE_MISSING_ENTITIES,
    ISSUE_NO_PRESENCE_SOURCES,
    ISSUE_ENVIRONMENT_WITHOUT_SOURCES,
    ISSUE_INVALID_ENTITIES,
    ISSUE_INVALID_FEATURE_CONFIGURATION,
    ISSUE_BRIGHTNESS_CONFIGURATION,
)
# One brightness issue per entry; its translation key depends on the reasons.
BRIGHTNESS_ISSUE_TRANSLATION_KEYS = (
    "brightness_limits_missing",
    "brightness_limits_missing_and_source",
    "brightness_limits_invalid",
    "brightness_limits_invalid_and_source",
    "brightness_limits_legacy",
    "brightness_limits_legacy_and_source",
    "brightness_source_missing",
)
REPAIR_ISSUE_TRANSLATION_KEYS = (
    *(c for c in REPAIR_ISSUE_CATEGORIES if c != ISSUE_BRIGHTNESS_CONFIGURATION),
    ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION,
    *BRIGHTNESS_ISSUE_TRANSLATION_KEYS,
)


def _migration_issue_id() -> str:
    return ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION


async def async_evaluate_single_global_entry_migration(hass: HomeAssistant) -> None:
    """Detect legacy multi-entry installs without starting a migration."""
    from custom_components.adaptive_areas.migration import (
        MigrationPhase,
        MigrationState,
        get_global_entries,
    )

    entries = hass.config_entries.async_entries(DOMAIN)
    globals_ = get_global_entries(hass)
    state = (
        MigrationState.from_dict(globals_[0].options["migration"])
        if len(globals_) == 1 and globals_[0].options.get("migration")
        else None
    )
    if state is not None and state.migration_phase is MigrationPhase.COMPLETE:
        ir.async_delete_issue(hass, DOMAIN, _migration_issue_id())
        return
    legacy_count = len([entry for entry in entries if entry not in globals_])
    if legacy_count < 2 and state is None:
        ir.async_delete_issue(hass, DOMAIN, _migration_issue_id())
        return
    status = (
        "blocked"
        if len(globals_) > 1
        else "resumable" if state is not None else "required"
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        _migration_issue_id(),
        is_fixable=status != "blocked",
        severity=(
            ir.IssueSeverity.WARNING if status != "blocked" else ir.IssueSeverity.ERROR
        ),
        translation_key=ISSUE_SINGLE_GLOBAL_ENTRY_MIGRATION,
        translation_placeholders={"status": status},
    )


class SingleGlobalEntryMigrationRepairFlow(RepairsFlow):
    """Require explicit confirmation before the destructive migration starts."""

    async def async_step_init(
        self, user_input: dict[str, str] | None
    ) -> RepairsFlowResult:
        """Show confirmation first, then run the sole supported migration trigger."""
        if user_input is None:
            return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
        from custom_components.adaptive_areas.migration import (
            async_run_single_global_entry_migration,
        )

        try:
            await async_run_single_global_entry_migration(self.hass)
        except Exception:  # Repair remains open; technical detail stays in logs.
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({}),
                errors={"base": "migration_failed"},
            )
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a fix flow only for the explicit migration Repair issue."""
    if issue_id != _migration_issue_id():
        raise ValueError(f"unsupported repair issue: {issue_id}")
    return SingleGlobalEntryMigrationRepairFlow()


_ENTITY_REFERENCE_CATEGORIES = {
    CONF_AREA_TEMPERATURE_SENSOR: "area_climate",
    CONF_AREA_HUMIDITY_SENSOR: "area_climate",
    CONF_INCLUDE_ENTITIES: "area_filter",
    CONF_KEEP_ONLY_ENTITIES: "presence",
    CONF_PRESENCE_CONTROL_ENTITIES: "presence",
    CONF_AREA_ILLUMINANCE_SENSOR: "area_illuminance",
    CONF_SLEEP_ENTITY: "secondary_states",
    CONF_ACCENT_ENTITY: "secondary_states",
    CONF_OVERHEAD_LIGHTS: "light_groups",
    CONF_TASK_LIGHTS: "light_groups",
    CONF_ACCENT_LIGHTS: "light_groups",
    CONF_SLEEP_LIGHTS: "light_groups",
    CONF_TASK_SWITCHES: "switch_groups",
    CONF_SLEEP_SWITCHES: "switch_groups",
    CONF_CLIMATE_CONTROL_ENTITY_ID: "climate_control",
    CONF_BLE_TRACKER_ENTITIES: "ble_trackers",
    CONF_NOTIFICATION_DEVICES: "area_aware_media_player",
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "room_climate",
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY: "room_climate",
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE: "room_climate",
    CONF_ENVIRONMENT_WINDOWS: "room_climate",
    CONF_ENVIRONMENT_VENTILATION_FANS: "room_climate",
    CONF_ENVIRONMENT_CIRCULATION_FANS: "room_climate",
    CONF_ENVIRONMENT_DISABLED_FANS: "room_climate",
}

_EXPECTED_ENTITY_DOMAINS = {
    CONF_AREA_ILLUMINANCE_SENSOR: "sensor",
    CONF_CLIMATE_CONTROL_ENTITY_ID: "climate",
    CONF_OVERHEAD_LIGHTS: "light",
    CONF_TASK_LIGHTS: "light",
    CONF_ACCENT_LIGHTS: "light",
    CONF_SLEEP_LIGHTS: "light",
    CONF_TASK_SWITCHES: "switch",
    CONF_SLEEP_SWITCHES: "switch",
    CONF_ENVIRONMENT_WINDOWS: "binary_sensor",
    CONF_ENVIRONMENT_VENTILATION_FANS: "fan",
    CONF_ENVIRONMENT_CIRCULATION_FANS: "fan",
    CONF_ENVIRONMENT_DISABLED_FANS: "fan",
}


def _issue_id(category: str, entry_id: str) -> str:
    """Return a deterministic issue ID for a config entry."""
    return f"{category}_{entry_id}"


def _combined_config(config_entry: ConfigEntry) -> dict[str, Any]:
    """Return data overlaid with options, matching runtime behavior."""
    config = dict(config_entry.data)
    config.update(config_entry.options)
    return config


def _iter_entity_references(
    value: Any, *, category: str = "configuration"
) -> Iterable[tuple[str, str]]:
    """Yield configured entity IDs and their safe feature categories."""
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        item_category = _ENTITY_REFERENCE_CATEGORIES.get(key, category)
        if key in _ENTITY_REFERENCE_CATEGORIES:
            values = item if isinstance(item, list) else [item]
            for entity_id in values:
                if isinstance(entity_id, str) and "." in entity_id:
                    yield entity_id, item_category
            continue
        if isinstance(item, dict):
            yield from _iter_entity_references(item, category=str(key))


def get_missing_entity_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return counts and categories for truly absent configured entities."""
    entity_registry = async_get_entity_registry(hass)
    missing_by_category: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    combined = _combined_config(config_entry)
    enabled_features = combined.get(CONF_ENABLED_FEATURES, {})
    environment_enabled = (
        isinstance(enabled_features, (dict, list))
        and CONF_FEATURE_ENVIRONMENT in enabled_features
    )
    for entity_id, category in _iter_entity_references(combined):
        if category in ("area_climate", "room_climate") and not environment_enabled:
            continue
        if entity_id in seen:
            continue
        seen.add(entity_id)
        if hass.states.get(entity_id) is not None:
            continue
        if entity_registry.async_get(entity_id) is not None:
            continue
        missing_by_category[category] += 1
    return {
        "count": sum(missing_by_category.values()),
        "categories": sorted(missing_by_category),
        "category_counts": dict(sorted(missing_by_category.items())),
    }


def get_configured_entity_references(config_entry: ConfigEntry) -> set[str]:
    """Return explicit references of every Area of an entry (Repair checks)."""
    return configured_entity_references(_combined_config(config_entry))


def configured_entity_references(config: dict[str, Any]) -> set[str]:
    """Return explicit entity references of one configuration (one Area's local config)."""
    return {entity_id for entity_id, _category in _iter_entity_references(config)}


def _enabled_features(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy enabled-feature storage."""
    features = config.get(CONF_ENABLED_FEATURES, {})
    if isinstance(features, dict):
        return features
    if isinstance(features, list):
        return {feature: {} for feature in features}
    return {}


def _feature_config(config: dict[str, Any], feature: str) -> dict[str, Any]:
    """Return one enabled feature's configuration."""
    value = _enabled_features(config).get(feature, {})
    return value if isinstance(value, dict) else {}


def get_invalid_entity_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return existing references whose domains cannot serve their roles."""
    invalid_by_category: dict[str, int] = defaultdict(int)
    entity_registry = async_get_entity_registry(hass)
    config = _combined_config(config_entry)
    features = _enabled_features(config)
    seen: set[tuple[str, str]] = set()

    def inspect(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            expected_domain = _EXPECTED_ENTITY_DOMAINS.get(key)
            if expected_domain is not None:
                category = _ENTITY_REFERENCE_CATEGORIES[key]
                if (
                    category == "room_climate"
                    and CONF_FEATURE_ENVIRONMENT not in features
                ):
                    continue
                values = item if isinstance(item, list) else [item]
                for entity_id in values:
                    marker = (str(entity_id), key)
                    if marker in seen or not isinstance(entity_id, str):
                        continue
                    seen.add(marker)
                    if (
                        hass.states.get(entity_id) is None
                        and entity_registry.async_get(entity_id) is None
                    ):
                        continue
                    if entity_id.partition(".")[0] != expected_domain:
                        invalid_by_category[category] += 1
                continue
            if isinstance(item, dict):
                inspect(item)

    inspect(config)
    return {
        "count": sum(invalid_by_category.values()),
        "categories": sorted(invalid_by_category),
        "category_counts": dict(sorted(invalid_by_category.items())),
    }


def get_presence_source_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Summarize durable presence sources using runtime discovery rules."""
    config = _combined_config(config_entry)
    if config.get(CONF_TYPE) == AREA_TYPE_META:
        return {"source_count": 0, "problem": None}
    features = _enabled_features(config)
    source_count = len(physical_presence_source_ids(hass, config_entry, config))
    if CONF_FEATURE_PRESENCE_HOLD in features:
        source_count += 1
    if CONF_FEATURE_BLE_TRACKERS in features and _feature_config(
        config, CONF_FEATURE_BLE_TRACKERS
    ).get(CONF_BLE_TRACKER_ENTITIES, []):
        source_count += 1
    if CONF_FEATURE_WASP_IN_A_BOX in features and CONF_FEATURE_AGGREGATION in features:
        source_count += 1
    return {
        "source_count": source_count,
        "problem": None if source_count else ISSUE_NO_PRESENCE_SOURCES,
    }


def get_environment_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Summarize structurally available Area Climate dimensions."""
    config = _combined_config(config_entry)
    enabled = CONF_FEATURE_ENVIRONMENT in _enabled_features(config)
    capabilities: set[str] = set()
    if enabled and config.get(CONF_TYPE) != AREA_TYPE_META:
        capabilities.update(get_environment_source_capabilities(hass, config_entry))
        runtime = hass.data.get(MODULE_DATA, {}).get(config_entry.entry_id, {})
        area = runtime.get(DATA_AREA_OBJECT)
        environment = getattr(area, "environment", None)
        if environment is not None:
            measurement_capabilities = {
                "temperature",
                "humidity",
                "air_quality",
                *POLLUTANT_NAMES.values(),
            }
            capabilities.update(
                key
                for key, available in environment.assessment.get(
                    "capabilities", {}
                ).items()
                if available and key in measurement_capabilities
            )
    capability_list = sorted(capabilities)
    problem = (
        ISSUE_ENVIRONMENT_WITHOUT_SOURCES
        if enabled and config.get(CONF_TYPE) != AREA_TYPE_META and not capability_list
        else None
    )
    return {
        "enabled": enabled,
        "capability_count": len(capability_list),
        "capabilities": capability_list,
        "problem": problem,
    }


BRIGHTNESS_DEPENDENT_MODES = frozenset(
    {
        LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
        LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
        LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
    }
)


def get_brightness_configuration_problems(
    config: dict[str, Any], global_light_sensor: str | None = None
) -> list[str]:
    """Return missing or invalid brightness inputs of active brightness-dependent groups.

    Reports only: no sensor is selected and no limit is invented. Groups with mode ignore
    or without lights need nothing. A configured but temporarily unavailable sensor is not a
    configuration problem and is not reported here.
    """
    groups = _feature_config(config, CONF_FEATURE_LIGHT_GROUPS)
    needs_brightness = any(
        groups.get(category)
        and groups.get(LIGHT_GROUP_BRIGHTNESS[category]) in BRIGHTNESS_DEPENDENT_MODES
        for category in LIGHT_GROUP_BRIGHTNESS
    )
    if not needs_brightness:
        return []

    light = _feature_config(config, CONF_FEATURE_LIGHT)
    if not light:
        retained = config.get(CONF_RETAINED_FEATURES) or {}
        light = retained.get(CONF_FEATURE_LIGHT) if isinstance(retained, dict) else None
        light = light if isinstance(light, dict) else {}

    reasons: list[str] = []
    if "turn_on_below" not in light and "turn_off_above" not in light:
        legacy = config.get(CONF_SECONDARY_STATES) or {}
        if isinstance(legacy, dict) and legacy.get(CONF_DARK_ENTITY):
            reasons.append("legacy_dark_entity_without_limits")
        else:
            reasons.append("missing_brightness_limits")
    else:
        try:
            light_policy_config_from_feature(light)
        except TypeError, ValueError:
            reasons.append("invalid_brightness_limits")

    area_sensor = config.get(CONF_AREA_ILLUMINANCE_SENSOR)
    if not area_sensor and not global_light_sensor:
        reasons.append("missing_light_sensor")
    return reasons


def get_feature_configuration_summary(config_entry: ConfigEntry) -> dict[str, Any]:
    """Return stable structural problems for enabled features."""
    config = _combined_config(config_entry)
    features = _enabled_features(config)
    problems: dict[str, list[str]] = {}
    if (
        CONF_FEATURE_WASP_IN_A_BOX in features
        and CONF_FEATURE_AGGREGATION not in features
    ):
        problems[CONF_FEATURE_WASP_IN_A_BOX] = ["missing_aggregation"]
    if CONF_FEATURE_BLE_TRACKERS in features and not _feature_config(
        config, CONF_FEATURE_BLE_TRACKERS
    ).get(CONF_BLE_TRACKER_ENTITIES, []):
        problems[CONF_FEATURE_BLE_TRACKERS] = ["missing_tracker_entities"]
    if CONF_FEATURE_CLIMATE_CONTROL in features and not _feature_config(
        config, CONF_FEATURE_CLIMATE_CONTROL
    ).get(CONF_CLIMATE_CONTROL_ENTITY_ID):
        problems[CONF_FEATURE_CLIMATE_CONTROL] = ["missing_target_entity"]
    return {
        "count": sum(len(reasons) for reasons in problems.values()),
        "features": dict(sorted(problems.items())),
    }


def config_entry_area_exists(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Return whether the regular or meta areas backing an entry still exist.

    A GlobalEntry has no Area of its own: every configured Area must still exist.
    """
    areas = config_entry.options.get(CONF_AREAS, config_entry.data.get(CONF_AREAS))
    if isinstance(areas, dict):
        return not missing_configured_area_ids(hass, areas)
    return _backing_area_exists(hass, config_entry.data.get(CONF_ID))


def missing_configured_area_ids(hass: HomeAssistant, areas: dict) -> list[str]:
    """Return the configured Area IDs whose Home Assistant Area or floor is gone."""
    return sorted(
        str(area_id) for area_id in areas if not _backing_area_exists(hass, area_id)
    )


def _backing_area_exists(hass: HomeAssistant, area_id: Any) -> bool:
    """Return whether the Home Assistant Area, floor or Meta type of one ID exists."""
    if area_id in {
        MetaAreaType.GLOBAL,
        MetaAreaType.INTERIOR,
        MetaAreaType.EXTERIOR,
    }:
        return True
    if async_get_floor_registry(hass).async_get_floor(area_id) is not None:
        return True
    return async_get_area_registry(hass).async_get_area(area_id) is not None


def _configured_global_light_sensor(hass: HomeAssistant) -> str | None:
    """Return the global light sensor configured in any entry's global options, if any."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        options = entry.options.get(CONF_GLOBAL_OPTIONS) or {}
        sensor = (
            options.get(CONF_GLOBAL_LIGHT_SENSOR) if isinstance(options, dict) else None
        )
        if sensor:
            return str(sensor)
    return None


def get_brightness_configuration_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return the brightness configuration reasons of one entry (no entity IDs)."""
    reasons = get_brightness_configuration_problems(
        _combined_config(config_entry), _configured_global_light_sensor(hass)
    )
    return {"reasons": reasons}


def brightness_translation_key(reasons: list[str]) -> str | None:
    """Map brightness reasons to one translation key, or None when nothing is wrong."""
    if not reasons:
        return None
    limit_parts = {
        "invalid_brightness_limits": "limits_invalid",
        "legacy_dark_entity_without_limits": "limits_legacy",
        "missing_brightness_limits": "limits_missing",
    }
    limit = next((limit_parts[r] for r in limit_parts if r in reasons), None)
    if limit is None:
        return ISSUE_BRIGHTNESS_SOURCE_MISSING
    key = f"brightness_{limit}"
    if "missing_light_sensor" in reasons:
        key += "_and_source"
    return key


def get_repair_summary(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Build a privacy-safe repair summary without changing issue state."""
    missing_entities = get_missing_entity_summary(hass, config_entry)
    return {
        "missing_area": not config_entry_area_exists(hass, config_entry),
        "missing_entities": missing_entities,
        "invalid_entities": get_invalid_entity_summary(hass, config_entry),
        "presence": get_presence_source_summary(hass, config_entry),
        "environment": get_environment_summary(hass, config_entry),
        "feature_configuration": get_feature_configuration_summary(config_entry),
        "brightness_configuration": get_brightness_configuration_summary(
            hass, config_entry
        ),
    }


async def async_evaluate_config_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Create and clear deterministic issues for one config entry."""
    summary = get_repair_summary(hass, config_entry)
    missing_area_id = _issue_id(ISSUE_MISSING_AREA, config_entry.entry_id)
    missing_entities_id = _issue_id(ISSUE_MISSING_ENTITIES, config_entry.entry_id)

    if summary["missing_area"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            missing_area_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_MISSING_AREA,
            translation_placeholders={"entry": config_entry.title},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, missing_area_id)

    missing_entities = summary["missing_entities"]
    if missing_entities["count"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            missing_entities_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MISSING_ENTITIES,
            translation_placeholders={
                "entry": config_entry.title,
                "count": str(missing_entities["count"]),
                "category_count": str(len(missing_entities["categories"])),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, missing_entities_id)

    issue_details = (
        (
            ISSUE_NO_PRESENCE_SOURCES,
            not summary["missing_area"] and summary["presence"]["problem"] is not None,
            {"entry": config_entry.title},
        ),
        (
            ISSUE_ENVIRONMENT_WITHOUT_SOURCES,
            not summary["missing_area"]
            and summary["environment"]["problem"] is not None,
            {"entry": config_entry.title},
        ),
        (
            ISSUE_INVALID_ENTITIES,
            bool(summary["invalid_entities"]["count"]),
            {
                "entry": config_entry.title,
                "count": str(summary["invalid_entities"]["count"]),
            },
        ),
        (
            ISSUE_INVALID_FEATURE_CONFIGURATION,
            bool(summary["feature_configuration"]["count"]),
            {
                "entry": config_entry.title,
                "count": str(summary["feature_configuration"]["count"]),
                "feature_count": str(len(summary["feature_configuration"]["features"])),
            },
        ),
    )
    brightness_issue_id = _issue_id(
        ISSUE_BRIGHTNESS_CONFIGURATION, config_entry.entry_id
    )
    brightness_key = (
        None
        if summary["missing_area"]
        else brightness_translation_key(summary["brightness_configuration"]["reasons"])
    )
    if brightness_key is not None:
        ir.async_create_issue(
            hass,
            DOMAIN,
            brightness_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=brightness_key,
            translation_placeholders={"entry": config_entry.title},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, brightness_issue_id)

    for category, active, placeholders in issue_details:
        issue_id = _issue_id(category, config_entry.entry_id)
        if active:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=category,
                translation_placeholders=placeholders,
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    return summary


def active_issue_count(
    hass: HomeAssistant, config_entry: ConfigEntry | None = None
) -> int:
    """Return the number of active integration or config-entry issues."""
    registry = ir.async_get(hass)
    entry_issue_ids = (
        {
            _issue_id(category, config_entry.entry_id)
            for category in REPAIR_ISSUE_CATEGORIES
        }
        if config_entry is not None
        else None
    )
    return sum(
        issue.active
        for (domain, issue_id), issue in registry.issues.items()
        if domain == DOMAIN and (entry_issue_ids is None or issue_id in entry_issue_ids)
    )


async def async_remove_config_entry_issues(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Remove issues after the corresponding config entry is deleted."""
    for category in REPAIR_ISSUE_CATEGORIES:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(category, config_entry.entry_id))
