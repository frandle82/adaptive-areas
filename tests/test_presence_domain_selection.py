"""Presence domain selection: allowed domains, lossless storage, and panel/backend agreement."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, STATE_OFF, STATE_ON
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.area_config import async_update_area
from custom_components.adaptive_areas.base.adaptive import AdaptiveArea
from custom_components.adaptive_areas.const import (
    ALL_PRESENCE_DEVICE_PLATFORMS,
    AREA_TYPE_INTERIOR,
    BINARY_SENSOR_DOMAIN,
    CONF_CLEAR_TIMEOUT,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_NAME,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    CONF_TYPE,
    DEFAULT_PRESENCE_DEVICE_PLATFORMS,
    DEVICE_TRACKER_DOMAIN,
    DOMAIN,
    CONF_GLOBAL_ENTRY,
    MEDIA_PLAYER_DOMAIN,
    REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA,
    REMOTE_DOMAIN,
)
from custom_components.adaptive_areas.helpers.sources import (
    SUPPORTED_PHYSICAL_PRESENCE_SOURCE_DOMAINS,
)

ROOT = Path(__file__).parents[1]
PANEL = (
    ROOT
    / "custom_components"
    / "adaptive_areas"
    / "frontend"
    / "adaptive-areas-panel.js"
)
TRANSLATIONS = ROOT / "custom_components" / "adaptive_areas" / "translations"
TEXTS = ROOT / "custom_components" / "adaptive_areas" / "dashboard_texts"

ALLOWED_PRESENCE_DOMAINS = {
    BINARY_SENSOR_DOMAIN,
    MEDIA_PLAYER_DOMAIN,
    REMOTE_DOMAIN,
    DEVICE_TRACKER_DOMAIN,
}


def test_backend_offers_exactly_the_four_presence_domains() -> None:
    """Only binary_sensor, media_player, remote and device_tracker are offered."""
    assert set(ALL_PRESENCE_DEVICE_PLATFORMS) == ALLOWED_PRESENCE_DOMAINS
    assert len(ALL_PRESENCE_DEVICE_PLATFORMS) == 4
    assert SUPPORTED_PHYSICAL_PRESENCE_SOURCE_DOMAINS == ALLOWED_PRESENCE_DOMAINS


def test_default_domains_are_unchanged() -> None:
    """Existing entries keep their stored default: media_player and binary_sensor."""
    assert DEFAULT_PRESENCE_DEVICE_PLATFORMS == [
        MEDIA_PLAYER_DOMAIN,
        BINARY_SENSOR_DOMAIN,
    ]


def test_panel_choices_match_backend_domains() -> None:
    """The panel's offered domains are the backend's allowed domains, in order."""
    source = PANEL.read_text(encoding="utf-8")
    match = re.search(r"const PRESENCE_DOMAIN_CHOICES=(\[[^\]]*\]);", source)
    assert match, "PRESENCE_DOMAIN_CHOICES constant missing from the panel"
    panel_choices = json.loads(match.group(1))
    assert set(panel_choices) == ALLOWED_PRESENCE_DOMAINS
    assert len(panel_choices) == len(ALLOWED_PRESENCE_DOMAINS)


def test_panel_presence_domains_use_the_checkbox_renderer() -> None:
    """The domain choice uses the four-domain checkbox renderer, not every state domain."""
    source = PANEL.read_text(encoding="utf-8")
    assert '_renderDomainCheckboxes("presence_device_platforms"' in source
    assert '_renderStringMultiSelect("presence_device_platforms"' not in source
    assert (
        'Object.keys(this._hass?.states||{}).map((id)=>id.split(".",1)[0])'
        not in source
    )


def test_stored_unsupported_domain_is_kept_by_the_options_schema() -> None:
    """Saving never rejects or drops a stored domain that is no longer offered."""
    stored = ["binary_sensor", "light"]
    validated = REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA(
        {CONF_PRESENCE_DEVICE_PLATFORMS: stored}
    )
    assert validated[CONF_PRESENCE_DEVICE_PLATFORMS] == stored


def test_empty_domain_choice_is_stored_as_empty_list() -> None:
    """An explicit empty selection is kept as a user choice, not replaced by the default."""
    validated = REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA(
        {CONF_PRESENCE_DEVICE_PLATFORMS: []}
    )
    assert validated[CONF_PRESENCE_DEVICE_PLATFORMS] == []


def _area(
    hass, name: str, platforms: list[str], include: list[str] | None = None
) -> AdaptiveArea:
    area_entry = async_get_area_registry(hass).async_create(name)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_GLOBAL_ENTRY: True}, options={})
    entry.add_to_hass(hass)
    config = {
        CONF_ID: area_entry.id,
        CONF_NAME: name,
        CONF_TYPE: AREA_TYPE_INTERIOR,
        CONF_PRESENCE_DEVICE_PLATFORMS: platforms,
        CONF_PRESENCE_SENSOR_DEVICE_CLASS: [BinarySensorDeviceClass.MOTION],
        CONF_INCLUDE_ENTITIES: include or [],
    }
    return AdaptiveArea(
        hass,
        SimpleNamespace(id=area_entry.id, name=name, icon=None, floor_id=None),
        entry,
        config,
    )


def test_unsupported_stored_domain_is_ignored_at_runtime(hass) -> None:
    """A stored but unsupported domain such as light is never a presence source."""
    hass.states.async_set("light.kitchen", STATE_ON)
    hass.states.async_set(
        "binary_sensor.kitchen_motion",
        STATE_OFF,
        {ATTR_DEVICE_CLASS: BinarySensorDeviceClass.MOTION},
    )
    # Explicit include: even a deliberately included light is not a presence source.
    area = _area(
        hass,
        "Kueche",
        ["light", BINARY_SENSOR_DOMAIN],
        include=["light.kitchen", "binary_sensor.kitchen_motion"],
    )

    sources = area.get_presence_sensors()

    assert "light.kitchen" not in sources
    assert "binary_sensor.kitchen_motion" in sources


def test_unsupported_stored_domain_survives_a_save_without_changes() -> None:
    """Validating an unchanged form keeps the unsupported value (no silent deletion)."""
    stored = [MEDIA_PLAYER_DOMAIN, "light"]
    validated = REGULAR_AREA_PRESENCE_TRACKING_OPTIONS_SCHEMA(
        {CONF_PRESENCE_DEVICE_PLATFORMS: list(stored)}
    )
    assert set(validated[CONF_PRESENCE_DEVICE_PLATFORMS]) == set(stored)


def test_translation_keys_for_domain_and_entity_list_controls() -> None:
    """New controls have English and German texts in the dashboard text files."""
    keys = [
        "domainMultiHint",
        "domainNone",
        "domainUnsupported",
        "entityListToggle",
    ]
    english = json.loads((TEXTS / "en.json").read_text(encoding="utf-8"))
    german = json.loads((TEXTS / "de.json").read_text(encoding="utf-8"))
    for key in keys:
        assert english.get(key), key
        assert german.get(key), key
        assert english[key] != german[key], key


async def test_new_unsupported_presence_domain_is_rejected_without_mutation(
    hass, basic_config_entry, _setup_integration_basic
) -> None:
    """A domain that is not stored yet cannot be added through the Area form."""
    original = dict(basic_config_entry.options)

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload:
        errors = await async_update_area(
            hass,
            basic_config_entry,
            {CONF_PRESENCE_DEVICE_PLATFORMS: [BINARY_SENSOR_DOMAIN, "light"]},
        )

    assert CONF_PRESENCE_DEVICE_PLATFORMS in errors
    assert dict(basic_config_entry.options) == original
    reload.assert_not_awaited()


async def test_stored_unsupported_domain_survives_unrelated_saves(
    hass, basic_config_entry, _setup_integration_basic
) -> None:
    """An already stored value stays accepted and other fields are not changed."""
    hass.config_entries.async_update_entry(
        basic_config_entry,
        options={
            **basic_config_entry.options,
            CONF_PRESENCE_DEVICE_PLATFORMS: [BINARY_SENSOR_DOMAIN, "light"],
        },
    )
    before = dict(basic_config_entry.options)

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload:
        errors = await async_update_area(
            hass,
            basic_config_entry,
            {
                CONF_PRESENCE_DEVICE_PLATFORMS: [BINARY_SENSOR_DOMAIN, "light"],
                CONF_CLEAR_TIMEOUT: 42,
            },
        )

    assert errors == {}
    assert basic_config_entry.options[CONF_PRESENCE_DEVICE_PLATFORMS] == [
        BINARY_SENSOR_DOMAIN,
        "light",
    ]
    assert basic_config_entry.options[CONF_CLEAR_TIMEOUT] == 42
    for key in before:
        if key not in (CONF_CLEAR_TIMEOUT, CONF_PRESENCE_DEVICE_PLATFORMS):
            assert basic_config_entry.options[key] == before[key], key
    reload.assert_awaited_once()


async def test_user_can_remove_stored_unsupported_domain(
    hass, basic_config_entry, _setup_integration_basic
) -> None:
    """Explicit removal is accepted and the value is not added back automatically."""
    hass.config_entries.async_update_entry(
        basic_config_entry,
        options={
            **basic_config_entry.options,
            CONF_PRESENCE_DEVICE_PLATFORMS: [BINARY_SENSOR_DOMAIN, "light"],
        },
    )

    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        errors = await async_update_area(
            hass,
            basic_config_entry,
            {CONF_PRESENCE_DEVICE_PLATFORMS: [BINARY_SENSOR_DOMAIN]},
        )
        assert errors == {}
        assert basic_config_entry.options[CONF_PRESENCE_DEVICE_PLATFORMS] == [
            BINARY_SENSOR_DOMAIN
        ]

        # Selecting the removed value again is a new addition and is rejected.
        errors = await async_update_area(
            hass,
            basic_config_entry,
            {CONF_PRESENCE_DEVICE_PLATFORMS: [BINARY_SENSOR_DOMAIN, "light"]},
        )

    assert CONF_PRESENCE_DEVICE_PLATFORMS in errors
    assert basic_config_entry.options[CONF_PRESENCE_DEVICE_PLATFORMS] == [
        BINARY_SENSOR_DOMAIN
    ]


async def test_empty_presence_domain_choice_is_accepted(
    hass, basic_config_entry, _setup_integration_basic
) -> None:
    """An empty selection is a valid user choice and is stored as empty."""
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        errors = await async_update_area(
            hass, basic_config_entry, {CONF_PRESENCE_DEVICE_PLATFORMS: []}
        )

    assert errors == {}
    assert basic_config_entry.options[CONF_PRESENCE_DEVICE_PLATFORMS] == []
