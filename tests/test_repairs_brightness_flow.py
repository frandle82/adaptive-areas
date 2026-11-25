"""End-to-end repair flow for brightness configuration.

Real config entries, the real Home Assistant issue registry and the production evaluation
(async_evaluate_config_entry). Configuration changes go through async_update_entry; no
evaluation step or issue function is mocked.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_AREA_ILLUMINANCE_SENSOR,
    CONF_DARK_ENTITY,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_OVERHEAD_LIGHTS,
    CONF_OVERHEAD_LIGHTS_ACT_ON,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    CONF_OVERHEAD_LIGHTS_STATES,
    CONF_SECONDARY_STATES,
    DOMAIN,
    LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    LIGHT_GROUP_BRIGHTNESS_IGNORE,
    LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
    AreaStates,
)
from custom_components.adaptive_areas.repairs import (
    ISSUE_BRIGHTNESS_CONFIGURATION,
    _issue_id,
    async_evaluate_config_entry,
)
from tests.const import MockAreaIds
from tests.helpers import get_basic_config_entry_data

LIGHT = "light.kitchen_ceiling"
AREA_SENSOR = "sensor.kitchen_lux"
GLOBAL_SENSOR = "sensor.global_lux"
VALID = {"turn_on_below": 90.0, "turn_off_above": 110.0}


def _features(
    mode: str | None, light: dict | None, groups_enabled: bool = True
) -> dict:
    group = {
        CONF_OVERHEAD_LIGHTS: [LIGHT],
        CONF_OVERHEAD_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
        CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
    }
    if mode is not None:
        group[CONF_OVERHEAD_LIGHTS_BRIGHTNESS] = mode
    features: dict = {}
    if groups_enabled:
        features[CONF_FEATURE_LIGHT_GROUPS] = group
    if light is not None:
        features[CONF_FEATURE_LIGHT] = light
    return features


def _ensure_area(hass: HomeAssistant) -> None:
    """Create the Area in the real area registry; a missing Area suppresses brightness checks."""
    registry = ar.async_get(hass)
    if registry.async_get_area(MockAreaIds.KITCHEN.value) is None:
        area = registry.async_create(MockAreaIds.KITCHEN.value.title())
        assert area.id == MockAreaIds.KITCHEN.value, area.id


def _build(
    hass: HomeAssistant,
    features: dict,
    *,
    area_sensor: str | None = AREA_SENSOR,
    global_sensor: str | None = None,
    extra: dict | None = None,
) -> MockConfigEntry:
    _ensure_area(hass)
    data = get_basic_config_entry_data(MockAreaIds.KITCHEN)
    data[CONF_ENABLED_FEATURES] = features
    if area_sensor:
        data[CONF_AREA_ILLUMINANCE_SENSOR] = area_sensor
    if extra:
        data.update(extra)
    options = (
        {CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: global_sensor}}
        if global_sensor
        else {}
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Kitchen", data=data, options=options)
    entry.add_to_hass(hass)
    return entry


def _brightness_issues(hass: HomeAssistant, entry: MockConfigEntry) -> list:
    prefix = _issue_id(ISSUE_BRIGHTNESS_CONFIGURATION, entry.entry_id)
    return [i for i in ir.async_get(hass).issues.values() if i.issue_id == prefix]


async def _evaluate(hass: HomeAssistant, entry: MockConfigEntry) -> str | None:
    """Run the production evaluation and return the translation key of the brightness issue."""
    await async_evaluate_config_entry(hass, entry)
    issues = _brightness_issues(hass, entry)
    assert (
        len(issues) <= 1
    ), "a configuration must never produce duplicate brightness issues"
    return issues[0].translation_key if issues else None


async def test_valid_brightness_configuration_creates_no_issue(hass) -> None:
    """A complete numeric configuration with a source creates no repair."""
    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, VALID))
    assert await _evaluate(hass, entry) is None


async def test_missing_source_creates_source_issue(hass) -> None:
    """Brightness-dependent lights without any brightness source get the source repair."""
    entry = _build(
        hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, VALID), area_sensor=None
    )
    assert await _evaluate(hass, entry) == "brightness_source_missing"


async def test_missing_limits_create_limits_issue(hass) -> None:
    """A source without brightness limits creates the limits repair."""
    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, None))
    assert await _evaluate(hass, entry) == "brightness_limits_missing"


async def test_invalid_limits_create_invalid_issue(hass) -> None:
    """Thresholds in the wrong order create the invalid repair, and the stored values stay unchanged."""
    bad = {"turn_on_below": 120.0, "turn_off_above": 100.0}
    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, bad))
    assert await _evaluate(hass, entry) == "brightness_limits_invalid"
    assert entry.data[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT] == bad


async def test_legacy_dark_entity_creates_legacy_issue(hass) -> None:
    """A former dark entity without limits gets the legacy repair, never a converted value."""
    entry = _build(
        hass,
        _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, None),
        extra={CONF_SECONDARY_STATES: {CONF_DARK_ENTITY: "binary_sensor.old_dark"}},
    )
    assert await _evaluate(hass, entry) == "brightness_limits_legacy"


async def test_several_problems_are_consolidated_into_one_issue(hass) -> None:
    """Missing limits and a missing source produce one combined issue, not two."""
    entry = _build(
        hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, None), area_sensor=None
    )
    assert await _evaluate(hass, entry) == "brightness_limits_missing_and_source"


async def test_repeated_evaluation_creates_no_duplicates(hass) -> None:
    """Evaluating the same configuration again keeps exactly one issue."""
    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, None))
    assert await _evaluate(hass, entry) == "brightness_limits_missing"
    assert await _evaluate(hass, entry) == "brightness_limits_missing"


async def test_configuration_change_resolves_the_issue(hass) -> None:
    """Setting valid limits through a real configuration update removes the repair."""
    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, None))
    assert await _evaluate(hass, entry) == "brightness_limits_missing"
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_ENABLED_FEATURES: _features(
                LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, VALID
            ),
        },
    )
    assert await _evaluate(hass, entry) is None


async def test_reload_like_reevaluation_brings_back_no_stale_issue(hass) -> None:
    """After a fix the issue stays away on re-evaluation; a new problem appears again once."""
    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, VALID))
    assert await _evaluate(hass, entry) is None
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_ENABLED_FEATURES: _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, None),
        },
    )
    assert await _evaluate(hass, entry) == "brightness_limits_missing"
    assert await _evaluate(hass, entry) == "brightness_limits_missing"


async def test_unavailable_sensor_is_not_a_configuration_repair(hass) -> None:
    """A configured but temporarily unavailable sensor creates no repair."""
    hass.states.async_set(AREA_SENSOR, "unavailable")
    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, VALID))
    assert await _evaluate(hass, entry) is None


async def test_global_sensor_satisfies_the_source(hass) -> None:
    """A configured global light sensor satisfies the source requirement without an area sensor."""
    entry = _build(
        hass,
        _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, VALID),
        area_sensor=None,
        global_sensor=GLOBAL_SENSOR,
    )
    assert await _evaluate(hass, entry) is None


async def test_ignore_mode_creates_no_brightness_repair(hass) -> None:
    """Mode ignore never requires brightness inputs."""
    entry = _build(
        hass, _features(LIGHT_GROUP_BRIGHTNESS_IGNORE, None), area_sensor=None
    )
    assert await _evaluate(hass, entry) is None


async def test_disabled_light_groups_create_no_repair(hass) -> None:
    """Disabled light groups never produce a brightness repair."""
    entry = _build(
        hass,
        _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, None, groups_enabled=False),
        area_sensor=None,
    )
    assert await _evaluate(hass, entry) is None


async def test_turn_off_mode_is_checked(hass) -> None:
    """Turn off when bright needs brightness inputs too."""
    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_TURN_OFF, None))
    assert await _evaluate(hass, entry) == "brightness_limits_missing"


async def test_dark_on_bright_off_mode_is_checked(hass) -> None:
    """Dark on, bright off needs brightness inputs."""
    entry = _build(
        hass,
        _features(LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF, None),
        area_sensor=None,
    )
    assert await _evaluate(hass, entry) == "brightness_limits_missing_and_source"


async def test_translations_contain_every_brightness_key_in_every_language() -> None:
    """Each language file has the seven brightness keys with a title and a description."""
    keys = {
        "brightness_limits_missing",
        "brightness_limits_missing_and_source",
        "brightness_limits_invalid",
        "brightness_limits_invalid_and_source",
        "brightness_limits_legacy",
        "brightness_limits_legacy_and_source",
        "brightness_source_missing",
    }
    translations = (
        Path(__file__).resolve().parents[1]
        / "custom_components/adaptive_areas/translations"
    )
    for path in sorted(translations.glob("*.json")):
        issues = json.loads(path.read_text(encoding="utf-8"))["issues"]
        assert keys <= set(issues), path.name
        for key in keys:
            assert issues[key]["title"] and issues[key]["description"], (path.name, key)
            assert "{entry}" in issues[key]["title"], (path.name, key)


async def test_removing_the_entry_removes_its_brightness_issue(hass) -> None:
    """Deleting the Area's configuration entry removes its brightness repair."""
    from custom_components.adaptive_areas.repairs import (
        async_remove_config_entry_issues,
    )

    entry = _build(hass, _features(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, None))
    assert await _evaluate(hass, entry) == "brightness_limits_missing"
    await async_remove_config_entry_issues(hass, entry)
    assert _brightness_issues(hass, entry) == []


async def test_every_language_translates_the_brightness_issues() -> None:
    """Every language has its own brightness texts, with the same placeholders as English."""
    import re

    translations = (
        Path(__file__).resolve().parents[1]
        / "custom_components/adaptive_areas/translations"
    )
    english = json.loads((translations / "en.json").read_text(encoding="utf-8"))[
        "issues"
    ]
    keys = [key for key in english if key.startswith("brightness_")]
    assert len(keys) == 7
    for path in sorted(translations.glob("*.json")):
        issues = json.loads(path.read_text(encoding="utf-8"))["issues"]
        for key in keys:
            placeholders = set(
                re.findall(
                    r"{([^{}]+)}", issues[key]["title"] + issues[key]["description"]
                )
            )
            english_placeholders = set(
                re.findall(
                    r"{([^{}]+)}", english[key]["title"] + english[key]["description"]
                )
            )
            assert placeholders == english_placeholders, (path.name, key)
            if path.name not in ("en.json",):
                assert issues[key]["title"] != english[key]["title"], (path.name, key)
