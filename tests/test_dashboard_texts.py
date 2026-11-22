"""Dashboard texts: Home Assistant schema, loading, fallback and the WebSocket contract.

The texts live in `dashboard_texts/`, outside `translations/`, because the
translation schema validated by hassfest does not allow a custom `dashboard`
category. These tests guard both sides of that split.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas import dashboard_texts
from custom_components.adaptive_areas.dashboard_texts import (
    DASHBOARD_TEXT_PREFIX,
    load_dashboard_texts,
)
from custom_components.adaptive_areas.websocket import async_register_websocket_commands

ROOT = Path(__file__).parents[1] / "custom_components" / "adaptive_areas"
TRANSLATIONS = ROOT / "translations"
TEXTS = ROOT / "dashboard_texts"
COMMAND = "adaptive_areas/get_dashboard_texts"
KEY = f"{DASHBOARD_TEXT_PREFIX}conflictTitle"

# Top-level categories that Home Assistant's translation schema accepts for an integration.
HA_TRANSLATION_CATEGORIES = {
    "title",
    "config",
    "options",
    "entity",
    "entity_component",
    "selector",
    "services",
    "issues",
    "device",
    "exceptions",
    "system_health",
}


def test_translation_files_contain_no_dashboard_category() -> None:
    """The integration translations use only Home Assistant's categories."""
    for lang in ("en", "de"):
        data = json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))
        assert "dashboard" not in data, lang
        unknown = set(data) - HA_TRANSLATION_CATEGORIES
        assert unknown == set(), (lang, unknown)


def test_dashboard_texts_are_complete_in_both_languages() -> None:
    """Every English dashboard text has a German counterpart and vice versa."""
    english = json.loads((TEXTS / "en.json").read_text(encoding="utf-8"))
    german = json.loads((TEXTS / "de.json").read_text(encoding="utf-8"))
    flat_en = dashboard_texts._flatten(english)
    flat_de = dashboard_texts._flatten(german)
    assert set(flat_en) == set(flat_de)
    assert len(flat_en) > 300


def test_german_request_returns_german_texts() -> None:
    """A German request returns German values for the flattened keys."""
    german = load_dashboard_texts("de")
    english = load_dashboard_texts("en")
    assert german[KEY] != english[KEY]
    assert all(key.startswith(DASHBOARD_TEXT_PREFIX) for key in german)


def test_unsupported_language_falls_back_to_english() -> None:
    """Languages without a text file receive the English texts."""
    assert load_dashboard_texts("fr") == load_dashboard_texts("en")


def test_missing_german_key_falls_back_to_english(monkeypatch) -> None:
    """A key missing in German shows the English text, never an empty value."""
    english = dashboard_texts._read_language("en")
    german = {k: v for k, v in dashboard_texts._read_language("de").items() if k != KEY}
    monkeypatch.setattr(
        dashboard_texts,
        "_read_language",
        lambda lang: english if lang == "en" else german,
    )
    resolved = load_dashboard_texts("de")
    assert resolved[KEY] == english[KEY]


def test_missing_text_file_raises(monkeypatch, tmp_path: Path) -> None:
    """An unreadable text file is an error, not a silent empty result."""
    monkeypatch.setattr(dashboard_texts, "DASHBOARD_TEXTS_DIR", tmp_path)
    with pytest.raises(OSError):
        load_dashboard_texts("de")


async def test_every_signed_in_user_receives_texts(
    hass: HomeAssistant,
    basic_config_entry,
    _setup_integration_basic,
    hass_ws_client,
    hass_read_only_access_token,
) -> None:
    """The read-only command answers a non-administrator through the real WebSocket."""
    async_register_websocket_commands(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": COMMAND, "language": "de"})
    reply = await client.receive_json()
    assert reply["success"] is True, reply
    assert reply["result"]["resources"][KEY] == load_dashboard_texts("de")[KEY]


async def test_missing_texts_report_an_error(
    hass: HomeAssistant,
    basic_config_entry,
    _setup_integration_basic,
    hass_ws_client,
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A failed load is reported as an error so the panel shows its unavailable state."""
    async_register_websocket_commands(hass)
    monkeypatch.setattr(dashboard_texts, "DASHBOARD_TEXTS_DIR", tmp_path)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": COMMAND, "language": "de"})
    reply = await client.receive_json()
    assert reply["success"] is False
    assert reply["error"]["code"] == "dashboard_texts_unavailable"
