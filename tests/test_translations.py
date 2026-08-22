"""Translation catalog contract tests."""

from collections.abc import Iterator
import json
from pathlib import Path
from string import Formatter
from typing import Any

TRANSLATIONS = Path("custom_components/adaptive_areas/translations")


def _translated_strings(
    value: Any, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], str]]:
    """Yield every translated string with its structural key path."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _translated_strings(child, (*path, key))
    elif isinstance(value, str):
        yield path, value


def _placeholders(value: str) -> set[str]:
    """Return format placeholders used by a translation string."""
    return {
        field_name
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(value)
        if field_name is not None
    }


def test_all_translation_catalogs_are_json_and_placeholder_compatible() -> None:
    """Every locale is serializable and shared keys preserve placeholders."""
    catalogs = sorted(TRANSLATIONS.glob("*.json"))
    assert {path.stem for path in catalogs} >= {"en", "de"}

    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    english_strings = dict(_translated_strings(english))
    assert english_strings

    for catalog in catalogs:
        content = json.loads(catalog.read_text(encoding="utf-8"))
        assert isinstance(content, dict), catalog
        json.dumps(content)
        translated = dict(_translated_strings(content))
        for path in set(translated) & set(english_strings):
            value = translated[path]
            assert _placeholders(value) == _placeholders(
                english_strings[path]
            ), f"{catalog.name}: incompatible placeholders at {'.'.join(path)}"
