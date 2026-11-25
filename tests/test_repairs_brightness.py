"""Repair diagnosis for missing brightness inputs of brightness-dependent light groups.

Reports only: the tests check the reasons, never a repaired or invented configuration.
"""

from __future__ import annotations

import pytest

from custom_components.adaptive_areas.const import (
    CONF_AREA_ILLUMINANCE_SENSOR,
    CONF_ENABLED_FEATURES,
    CONF_DARK_ENTITY,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_OVERHEAD_LIGHTS,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    CONF_RETAINED_FEATURES,
    CONF_SECONDARY_STATES,
    CONF_SLEEP_LIGHTS,
    CONF_SLEEP_LIGHTS_BRIGHTNESS,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    LIGHT_GROUP_BRIGHTNESS_IGNORE,
    LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
)
from custom_components.adaptive_areas.repairs import (
    get_brightness_configuration_problems,
)

LIGHTS = ["light.kitchen_ceiling"]
VALID_LIMITS = {"turn_on_below": 90.0, "turn_off_above": 110.0}


def _config(
    mode: str | None, *, light=None, sensor=None, groups_enabled=True, extra=None
):
    group = {CONF_OVERHEAD_LIGHTS: LIGHTS}
    if mode is not None:
        group[CONF_OVERHEAD_LIGHTS_BRIGHTNESS] = mode
    enabled = {}
    if groups_enabled:
        enabled[CONF_FEATURE_LIGHT_GROUPS] = group
    if light is not None:
        enabled[CONF_FEATURE_LIGHT] = light
    config = {CONF_ENABLED_FEATURES: enabled}
    if sensor:
        config[CONF_AREA_ILLUMINANCE_SENSOR] = sensor
    config.update(extra or {})
    return config


def test_valid_limits_and_source_report_nothing() -> None:
    """Valid numeric limits and a source produce no repair reason."""
    config = _config(
        LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, light=VALID_LIMITS, sensor="sensor.lux"
    )
    assert get_brightness_configuration_problems(config) == []


@pytest.mark.parametrize(
    "mode",
    [
        LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
        LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
        LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
    ],
)
def test_every_brightness_dependent_mode_needs_limits_and_source(mode) -> None:
    """Every brightness-dependent mode needs limits and a source."""
    reasons = get_brightness_configuration_problems(_config(mode))
    assert reasons == ["missing_brightness_limits", "missing_light_sensor"]


def test_ignore_mode_requires_nothing() -> None:
    """Mode ignore requires no brightness input."""
    assert (
        get_brightness_configuration_problems(_config(LIGHT_GROUP_BRIGHTNESS_IGNORE))
        == []
    )


def test_missing_mode_requires_nothing() -> None:
    """A group without a brightness mode requires no brightness input."""
    assert get_brightness_configuration_problems(_config(None)) == []


def test_disabled_light_groups_report_nothing() -> None:
    """Disabled light groups never produce repair reasons."""
    config = _config(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, groups_enabled=False)
    assert get_brightness_configuration_problems(config) == []


def test_legacy_dark_entity_without_limits_is_its_own_reason() -> None:
    """A legacy dark entity without limits gets its own reason."""
    config = _config(
        LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
        sensor="sensor.lux",
        extra={CONF_SECONDARY_STATES: {CONF_DARK_ENTITY: "binary_sensor.dark"}},
    )
    assert get_brightness_configuration_problems(config) == [
        "legacy_dark_entity_without_limits"
    ]


def test_invalid_limits_are_reported_not_repaired() -> None:
    """Invalid limits are reported and the configuration stays unchanged."""
    bad = {"turn_on_below": 120.0, "turn_off_above": 100.0}
    config = _config(
        LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, light=bad, sensor="sensor.lux"
    )
    assert get_brightness_configuration_problems(config) == [
        "invalid_brightness_limits"
    ]
    assert config[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT] == bad  # never changed


def test_global_sensor_satisfies_the_source_requirement() -> None:
    """A configured global light sensor satisfies the source requirement."""
    config = _config(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, light=VALID_LIMITS)
    assert (
        get_brightness_configuration_problems(
            config, global_light_sensor="sensor.global"
        )
        == []
    )


def test_retained_light_limits_count_while_light_feature_is_disabled() -> None:
    """Retained light limits count while the light feature is disabled."""
    config = _config(
        LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
        sensor="sensor.lux",
        extra={CONF_RETAINED_FEATURES: {CONF_FEATURE_LIGHT: VALID_LIMITS}},
    )
    assert get_brightness_configuration_problems(config) == []


def test_any_group_triggers_the_check() -> None:
    """Any brightness-dependent group triggers the check."""
    config = _config(LIGHT_GROUP_BRIGHTNESS_IGNORE)
    config[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS][CONF_SLEEP_LIGHTS] = [
        "light.bed"
    ]
    config[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS][
        CONF_SLEEP_LIGHTS_BRIGHTNESS
    ] = LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK
    assert get_brightness_configuration_problems(config) == [
        "missing_brightness_limits",
        "missing_light_sensor",
    ]


def test_global_options_key_is_read_by_the_helper_only_when_passed() -> None:
    """The helper reads the global sensor only when the caller passes it."""
    config = _config(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, light=VALID_LIMITS)
    config[CONF_GLOBAL_OPTIONS] = {CONF_GLOBAL_LIGHT_SENSOR: "sensor.global"}
    # The helper does not look into global options by itself; the caller passes the sensor.
    assert get_brightness_configuration_problems(config) == ["missing_light_sensor"]
