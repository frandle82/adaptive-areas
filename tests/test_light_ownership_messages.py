"""Localized ownership messages: every conflict key exists in every language, no internal keys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.adaptive_areas.helpers.light_ownership import (
    GROUP_MEMBER_KEYS,
    OWNERSHIP_CONFLICT_ERRORS,
    ownership_conflict_error,
)

BASE = Path("custom_components/adaptive_areas")
FILES = {
    "strings": BASE / "strings.json",
    "en": BASE / "translations/en.json",
    "de": BASE / "translations/de.json",
}
# Localized group names, taken from the dashboard texts (single source of user-facing names).
GROUP_NAMES = {
    "en": {
        "overhead": "Ceiling lights",
        "sleep": "Sleep lights",
        "accent": "Accent lights",
        "task": "Task lights",
    },
    "de": {
        "overhead": "Deckenleuchten",
        "sleep": "Schlaflichter",
        "accent": "Akzentlichter",
        "task": "Arbeitslichter",
    },
}
INTERNAL = ("overhead_lights", "sleep_lights", "accent_lights", "task_lights")


def _errors(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["options"]["error"]


def test_conflict_keys_are_derived_from_the_group_keys() -> None:
    """Each individual group has exactly one conflict key, derived from its config key."""
    assert set(OWNERSHIP_CONFLICT_ERRORS) == {
        "light_ownership_conflict_overhead",
        "light_ownership_conflict_sleep",
        "light_ownership_conflict_accent",
        "light_ownership_conflict_task",
    }
    assert {
        ownership_conflict_error(k) for k in GROUP_MEMBER_KEYS
    } == OWNERSHIP_CONFLICT_ERRORS


@pytest.mark.parametrize("name", list(FILES))
def test_every_conflict_key_exists_in_every_language(name: str) -> None:
    """Every conflict key is present in strings.json, en.json and de.json."""
    errors = _errors(FILES[name])
    for key in OWNERSHIP_CONFLICT_ERRORS:
        assert key in errors, f"{key} missing in {name}"


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("group", ["overhead", "sleep", "accent", "task"])
def test_message_names_the_localized_group_and_placeholders(
    lang: str, group: str
) -> None:
    """The message names the localized group, keeps the placeholders and no internal key."""
    text = _errors(FILES[lang])[f"light_ownership_conflict_{group}"]
    assert GROUP_NAMES[lang][group] in text
    assert "{light}" in text and "{area}" in text
    assert "{group}" not in text
    for other_lang, names in GROUP_NAMES.items():
        if other_lang != lang:
            for name in names.values():
                assert name not in text
    for internal in INTERNAL:
        assert internal not in text
    assert ("Nothing was saved." in text) or ("Nichts wurde gespeichert." in text)


def test_german_messages_contain_no_english_group_key_or_name() -> None:
    """German texts never show an English group key or an English group name."""
    errors = _errors(FILES["de"])
    for key in OWNERSHIP_CONFLICT_ERRORS:
        text = errors[key]
        for word in (
            "overhead",
            "sleep",
            "accent",
            "task",
            "Ceiling",
            "Sleep",
            "Accent",
            "Task",
        ):
            assert word not in text, f"{word!r} leaked into {key}"


DASHBOARD = {
    "en": BASE / "dashboard_texts/en.json",
    "de": BASE / "dashboard_texts/de.json",
}


@pytest.mark.parametrize("lang", ["en", "de"])
def test_dashboard_carries_the_same_localized_conflict_messages(lang: str) -> None:
    """The panel shows the same localized texts as the Home Assistant translations."""
    texts = json.loads(DASHBOARD[lang].read_text(encoding="utf-8"))
    for key in OWNERSHIP_CONFLICT_ERRORS:
        assert texts[key] == _errors(FILES[lang])[key], key
        assert "{light}" in texts[key] and "{area}" in texts[key]
