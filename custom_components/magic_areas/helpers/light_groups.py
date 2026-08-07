"""Helpers for light-group configuration migration."""

import logging
from typing import Any

from custom_components.magic_areas.const import (
    AREA_STATE_ACCENT,
    AREA_STATE_BRIGHT,
    AREA_STATE_EXTENDED,
    AREA_STATE_OCCUPIED,
    AREA_STATE_SLEEP,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    LIGHT_GROUP_ACTIVATION,
    LIGHT_GROUP_ACTIVATION_ACCENT,
    LIGHT_GROUP_ACTIVATION_DEFAULTS,
    LIGHT_GROUP_ACTIVATION_DISABLED,
    LIGHT_GROUP_ACTIVATION_EXTENDED,
    LIGHT_GROUP_ACTIVATION_OCCUPIED,
    LIGHT_GROUP_ACTIVATION_SLEEP,
    LIGHT_GROUP_BLOCKING_STATES,
    LIGHT_GROUP_BLOCKING_STATE_OPTIONS,
    LIGHT_GROUP_BRIGHTNESS,
    LIGHT_GROUP_BRIGHTNESS_IGNORE,
    LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
    LIGHT_GROUP_CATEGORIES,
    LIGHT_GROUP_REQUIRE_DARK,
    LIGHT_GROUP_STATE_RULES,
    LIGHT_GROUP_STATES,
    LIGHT_GROUP_STATES_LOGIC_MAP,
    LIGHT_GROUP_TURN_OFF_WHEN_BRIGHT,
    LIGHT_GROUP_ACT_ON,
)

_LOGGER = logging.getLogger(__name__)


def _activation_from_legacy_states(category: str, raw_states: Any) -> str:
    """Map a legacy state list to one unambiguous activation mode."""
    if raw_states is None:
        return LIGHT_GROUP_ACTIVATION_DEFAULTS[category]

    states = set(raw_states) if isinstance(raw_states, (list, tuple, set)) else set()

    if not states:
        return LIGHT_GROUP_ACTIVATION_DISABLED
    if AREA_STATE_OCCUPIED in states:
        return LIGHT_GROUP_ACTIVATION_OCCUPIED
    if states == {AREA_STATE_EXTENDED}:
        return LIGHT_GROUP_ACTIVATION_EXTENDED
    if states == {AREA_STATE_SLEEP}:
        return LIGHT_GROUP_ACTIVATION_SLEEP
    if states == {AREA_STATE_ACCENT}:
        return LIGHT_GROUP_ACTIVATION_ACCENT

    _LOGGER.warning(
        "Light group %s uses legacy state combination %s; migrating to occupied",
        category,
        sorted(states),
    )
    return LIGHT_GROUP_ACTIVATION_OCCUPIED


def migrate_light_group_feature_config(
    feature_config: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Convert one legacy light-group feature config to the simplified model."""
    migrated = dict(feature_config)

    for category in LIGHT_GROUP_CATEGORIES:
        activation_key = LIGHT_GROUP_ACTIVATION[category]
        legacy_states_key = LIGHT_GROUP_STATES[category]
        legacy_rules_key = LIGHT_GROUP_STATE_RULES[category]
        if activation_key not in migrated:
            legacy_states = migrated.get(legacy_states_key)
            legacy_rules = [
                rule
                for rule in migrated.get(legacy_rules_key, [])
                if isinstance(rule, (list, tuple, set)) and rule
            ]
            if (
                legacy_rules
                and not legacy_states
                and len(legacy_rules) == 1
                and len(legacy_rules[0]) == 1
            ):
                activation = _activation_from_legacy_states(category, legacy_rules[0])
            elif legacy_rules:
                _LOGGER.warning(
                    "Light group %s uses legacy rule blocks; migrating to occupied",
                    category,
                )
                activation = LIGHT_GROUP_ACTIVATION_OCCUPIED
            else:
                activation = _activation_from_legacy_states(category, legacy_states)
            migrated[activation_key] = activation

        brightness_key = LIGHT_GROUP_BRIGHTNESS[category]
        legacy_turn_off_key = LIGHT_GROUP_TURN_OFF_WHEN_BRIGHT[category]
        legacy_require_dark_key = LIGHT_GROUP_REQUIRE_DARK[category]
        blockers_key = LIGHT_GROUP_BLOCKING_STATES[category]
        raw_blockers = migrated.get(blockers_key, [])
        blockers = (
            list(raw_blockers) if isinstance(raw_blockers, (list, tuple, set)) else []
        )

        if brightness_key not in migrated:
            if (
                migrated.get(legacy_turn_off_key, False)
                or AREA_STATE_BRIGHT in blockers
            ):
                brightness = LIGHT_GROUP_BRIGHTNESS_TURN_OFF
            elif migrated.get(legacy_require_dark_key, True):
                brightness = LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK
            else:
                brightness = LIGHT_GROUP_BRIGHTNESS_IGNORE
            migrated[brightness_key] = brightness

        migrated[blockers_key] = [
            state for state in blockers if state in LIGHT_GROUP_BLOCKING_STATE_OPTIONS
        ]

        for legacy_key in (
            legacy_states_key,
            legacy_rules_key,
            LIGHT_GROUP_STATES_LOGIC_MAP[category],
            LIGHT_GROUP_ACT_ON[category],
            legacy_require_dark_key,
            legacy_turn_off_key,
        ):
            migrated.pop(legacy_key, None)

    return migrated, migrated != feature_config


def migrate_light_groups_in_config(
    config: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Migrate nested light-group settings in config-entry data or options."""
    migrated = dict(config)
    enabled_features = migrated.get(CONF_ENABLED_FEATURES)
    if not isinstance(enabled_features, dict):
        return migrated, False

    feature_config = enabled_features.get(CONF_FEATURE_LIGHT_GROUPS)
    if not isinstance(feature_config, dict):
        return migrated, False

    migrated_feature, changed = migrate_light_group_feature_config(feature_config)
    if not changed:
        return migrated, False

    migrated_features = dict(enabled_features)
    migrated_features[CONF_FEATURE_LIGHT_GROUPS] = migrated_feature
    migrated[CONF_ENABLED_FEATURES] = migrated_features
    return migrated, True
