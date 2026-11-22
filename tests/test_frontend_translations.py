"""Native translation source of the dashboard panel (E7).

The texts live in `custom_components/adaptive_areas/dashboard_texts/` (outside
`translations/`, because Home Assistant's translation schema does not allow a
custom `dashboard` category). The panel loads them through
`adaptive_areas/get_dashboard_texts`.
These tests check the files, not the panel's runtime; the runtime contract is
covered by the browser harness (tests/frontend/run.mjs, E7a-E7d).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
TRANSLATIONS = ROOT / "custom_components" / "adaptive_areas" / "translations"
PANEL = (
    ROOT
    / "custom_components"
    / "adaptive_areas"
    / "frontend"
    / "adaptive-areas-panel.js"
)

# Same in German and English by design (product names, units, brands, numbers).
IDENTICAL_BY_DESIGN = {
    "subtitle",
    "lux",
    "thermostat",
    "durationHM",
    "durationM",
    "diagVersion",
    "diagSevInfo",
    "diagGroupStatus",
    "diagGroupDetails",
}


TEXTS = ROOT / "custom_components" / "adaptive_areas" / "dashboard_texts"


def _texts(lang: str) -> dict:
    """Dashboard texts; they live outside translations/ (see dashboard_texts.py)."""
    return json.loads((TEXTS / f"{lang}.json").read_text(encoding="utf-8"))


def _load(lang: str) -> dict:
    return json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))


def _leaves(node, prefix: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix, node


def test_dashboard_texts_exist_in_both_languages() -> None:
    """The dashboard text files exist for English and German and are objects."""
    for lang in ("en", "de"):
        assert isinstance(_texts(lang), dict), lang


def test_every_english_key_has_its_own_german_value() -> None:
    """Every English key has its own German value (no silent fallback)."""
    english = dict(_leaves(_texts("en")))
    german = dict(_leaves(_texts("de")))
    assert sorted(set(english) - set(german)) == []
    identical = sorted(
        key
        for key, value in english.items()
        if german[key] == value and key.split(".")[0] not in IDENTICAL_BY_DESIGN
    )
    assert identical == [], f"German equals English without a reason: {identical}"


def test_placeholders_match_between_languages() -> None:
    """Placeholders such as {name} are the same in both languages."""
    english = dict(_leaves(_texts("en")))
    german = dict(_leaves(_texts("de")))
    mismatches = [
        key
        for key, value in english.items()
        if isinstance(value, str)
        and set(re.findall(r"\{(\w+)\}", value))
        != set(re.findall(r"\{(\w+)\}", german[key]))
    ]
    assert mismatches == []


def test_trace_labels_exist_in_both_languages() -> None:
    """The decision trace labels exist in English and German."""
    for lang in ("en", "de"):
        trace = _texts(lang)["trace_map"]
        assert set(trace) == {
            "decision",
            "outcome",
            "feature",
            "reason",
            "issue",
            "trigger",
            "state",
        }


def test_existing_backend_translations_are_preserved() -> None:
    """Backend translation categories remain in both files."""
    for lang in ("en", "de"):
        data = _load(lang)
        for key in (
            "title",
            "config",
            "options",
            "entity",
            "selector",
            "services",
            "issues",
            "device",
        ):
            assert key in data, (lang, key)


def test_panel_loads_texts_through_the_adaptive_areas_command() -> None:
    """The panel reads dashboard texts from the integration command, not frontend/get_translations."""
    source = PANEL.read_text(encoding="utf-8")
    assert 'type:"adaptive_areas/get_dashboard_texts"' in source
    assert "frontend/get_translations" not in source


def test_no_javascript_translation_tables_remain() -> None:
    """The panel no longer carries its own translation tables."""
    source = PANEL.read_text(encoding="utf-8")
    for marker in ("const EN=", "const DE=", "const TEXT=", "const TRACE_MAP="):
        assert marker not in source, marker
    assert "FEATURE_UI_REGISTRY" in source
    assert not re.search(
        r'label:"', source[source.index("const FEATURE_UI_REGISTRY=") :][:4000]
    )
