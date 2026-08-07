"""Tests for light-group configuration migration."""

from custom_components.magic_areas.const import (
    AREA_STATE_ACCENT,
    AREA_STATE_BRIGHT,
    AREA_STATE_EXTENDED,
    AREA_STATE_OCCUPIED,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS_ACTIVATION,
    CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    CONF_OVERHEAD_LIGHTS_REQUIRE_DARK,
    CONF_OVERHEAD_LIGHTS_STATE_RULES,
    CONF_OVERHEAD_LIGHTS_STATES,
    CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT,
    CONF_SLEEP_LIGHTS_ACTIVATION,
    CONF_SLEEP_LIGHTS_STATES,
    LIGHT_GROUP_ACTIVATION_OCCUPIED,
    LIGHT_GROUP_ACTIVATION_DISABLED,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
)
from custom_components.magic_areas.helpers.light_groups import (
    migrate_light_groups_in_config,
)


def test_migrate_legacy_light_group_configuration() -> None:
    """Legacy state and brightness fields are converted and removed."""
    config = {
        CONF_ENABLED_FEATURES: {
            CONF_FEATURE_LIGHT_GROUPS: {
                CONF_OVERHEAD_LIGHTS_STATES: [
                    AREA_STATE_OCCUPIED,
                    AREA_STATE_EXTENDED,
                ],
                CONF_OVERHEAD_LIGHTS_STATE_RULES: [
                    [AREA_STATE_OCCUPIED, AREA_STATE_ACCENT]
                ],
                CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [
                    AREA_STATE_BRIGHT,
                    AREA_STATE_ACCENT,
                ],
                CONF_OVERHEAD_LIGHTS_REQUIRE_DARK: False,
                CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT: False,
                CONF_SLEEP_LIGHTS_STATES: [],
            }
        }
    }

    migrated, changed = migrate_light_groups_in_config(config)
    light_config = migrated[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]

    assert changed is True
    assert (
        light_config[CONF_OVERHEAD_LIGHTS_ACTIVATION] == LIGHT_GROUP_ACTIVATION_OCCUPIED
    )
    assert light_config[CONF_OVERHEAD_LIGHTS_BLOCKING_STATES] == [AREA_STATE_ACCENT]
    assert (
        light_config[CONF_OVERHEAD_LIGHTS_BRIGHTNESS] == LIGHT_GROUP_BRIGHTNESS_TURN_OFF
    )
    assert CONF_OVERHEAD_LIGHTS_STATES not in light_config
    assert CONF_OVERHEAD_LIGHTS_STATE_RULES not in light_config
    assert CONF_OVERHEAD_LIGHTS_REQUIRE_DARK not in light_config
    assert CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT not in light_config
    assert light_config[CONF_SLEEP_LIGHTS_ACTIVATION] == LIGHT_GROUP_ACTIVATION_DISABLED


def test_light_group_migration_is_idempotent() -> None:
    """Running the migration twice leaves the new config untouched."""
    config = {
        CONF_ENABLED_FEATURES: {
            CONF_FEATURE_LIGHT_GROUPS: {
                CONF_OVERHEAD_LIGHTS_ACTIVATION: LIGHT_GROUP_ACTIVATION_OCCUPIED,
                CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [],
                CONF_OVERHEAD_LIGHTS_BRIGHTNESS: LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
            }
        }
    }

    migrated, _ = migrate_light_groups_in_config(config)
    migrated_again, changed_again = migrate_light_groups_in_config(migrated)

    assert changed_again is False
    assert migrated_again == migrated


def test_migrate_combined_legacy_brightness_behavior() -> None:
    """Legacy dark-on and bright-off flags retain both behaviors."""
    config = {
        CONF_ENABLED_FEATURES: {
            CONF_FEATURE_LIGHT_GROUPS: {
                CONF_OVERHEAD_LIGHTS_REQUIRE_DARK: True,
                CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT: True,
            }
        }
    }

    migrated, changed = migrate_light_groups_in_config(config)
    light_config = migrated[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]

    assert changed is True
    assert (
        light_config[CONF_OVERHEAD_LIGHTS_BRIGHTNESS]
        == LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF
    )
