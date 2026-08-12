"""Tests for Adaptive Areas Repair issue lifecycle."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
import re

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.area_registry import async_get as async_get_area_registry

from custom_components.adaptive_areas.const import (
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_INCLUDE_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_FEATURE_ENVIRONMENT,
    CONF_NAME,
    DOMAIN,
)
from custom_components.adaptive_areas.repairs import (
    ISSUE_MISSING_AREA,
    ISSUE_MISSING_ENTITIES,
    async_evaluate_config_entry,
)

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import get_basic_config_entry_data


def _issue(registry: ir.IssueRegistry, category: str, entry: MockConfigEntry):
    return registry.async_get_issue(DOMAIN, f"{category}_{entry.entry_id}")


async def test_missing_area_issue_created_and_removed(hass: HomeAssistant) -> None:
    """A deleted backing Area creates one deterministic error issue."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    registry = ir.async_get(hass)

    await async_evaluate_config_entry(hass, entry)
    issue = _issue(registry, ISSUE_MISSING_AREA, entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    await async_evaluate_config_entry(hass, entry)
    assert len(registry.issues) == 1

    area = async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    assert area.id == data["id"]
    await async_evaluate_config_entry(hass, entry)
    assert _issue(registry, ISSUE_MISSING_AREA, entry) is None


async def test_missing_entity_issue_ignores_unavailable_and_cleans_up(
    hass: HomeAssistant,
) -> None:
    """Unavailable states exist; only absent explicit references are missing."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_INCLUDE_ENTITIES] = ["binary_sensor.configured_motion"]
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    area = async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    assert area.id == data["id"]
    registry = ir.async_get(hass)

    await async_evaluate_config_entry(hass, entry)
    issue = _issue(registry, ISSUE_MISSING_ENTITIES, entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING

    hass.states.async_set("binary_sensor.configured_motion", STATE_UNAVAILABLE)
    await async_evaluate_config_entry(hass, entry)
    assert _issue(registry, ISSUE_MISSING_ENTITIES, entry) is None


async def test_missing_explicit_environment_reference_is_repaired(
    hass: HomeAssistant,
) -> None:
    """Deleted explicit environmental sources are reported by category."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_ENVIRONMENT: {
            CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE: "sensor.deleted_outdoor"
        }
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    area = async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    assert area.id == data["id"]

    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["category_counts"] == {"area_evaluation": 1}


async def test_deleted_primary_area_sensor_is_repaired(hass: HomeAssistant) -> None:
    """Missing primary source creates a Repair only while evaluation is enabled."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data[CONF_AREA_TEMPERATURE_SENSOR] = "sensor.deleted_room_temperature"
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    area = async_get_area_registry(hass).async_create(name=data[CONF_NAME])
    assert area.id == data["id"]

    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["count"] == 0

    data[CONF_ENABLED_FEATURES] = {CONF_FEATURE_ENVIRONMENT: {}}
    entry = MockConfigEntry(domain=DOMAIN, title="Safe entry", data=data)
    summary = await async_evaluate_config_entry(hass, entry)
    assert summary["missing_entities"]["category_counts"] == {"area_climate": 1}


def test_repair_translation_keys_exist() -> None:
    """English and German issue keys and placeholders remain aligned."""
    import json
    from pathlib import Path

    translations = Path("custom_components/adaptive_areas/translations")
    english = json.loads((translations / "en.json").read_text())
    german = json.loads((translations / "de.json").read_text())
    assert english["issues"].keys() == german["issues"].keys()
    assert set(english["issues"]) == {ISSUE_MISSING_AREA, ISSUE_MISSING_ENTITIES}
    for issue_id in english["issues"]:
        english_placeholders = set(
            re.findall(r"{([^{}]+)}", english["issues"][issue_id]["description"])
        )
        german_placeholders = set(
            re.findall(r"{([^{}]+)}", german["issues"][issue_id]["description"])
        )
        assert english_placeholders == german_placeholders
