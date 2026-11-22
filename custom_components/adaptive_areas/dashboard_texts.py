"""Dashboard texts for the Adaptive Areas panel.

The texts live in `dashboard_texts/<language>.json`, outside `translations/`.
Home Assistant's translation schema (hassfest) accepts only its own top-level
categories, so the dashboard texts cannot live in `translations/*.json`.

The panel reads them through `adaptive_areas/get_dashboard_texts`. The response
keeps the flattened key format `component.adaptive_areas.dashboard.<path>` that
the panel already unpacks. English is the fallback for every missing key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DASHBOARD_TEXT_PREFIX = "component.adaptive_areas.dashboard."
DASHBOARD_TEXTS_DIR = Path(__file__).parent / "dashboard_texts"
FALLBACK_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "de")


def _flatten(node: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested text objects into dotted keys."""
    flat: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{path}."))
        else:
            flat[f"{DASHBOARD_TEXT_PREFIX}{path}"] = value
    return flat


def _read_language(language: str) -> dict[str, str]:
    """Read one language file; raise OSError, ValueError or TypeError when unusable."""
    content = json.loads(
        (DASHBOARD_TEXTS_DIR / f"{language}.json").read_text(encoding="utf-8")
    )
    if not isinstance(content, dict):
        raise TypeError(f"dashboard texts for {language} are not an object")
    return _flatten(content)


def load_dashboard_texts(language: str) -> dict[str, str]:
    """Return flattened dashboard texts for a language with English fallback."""
    resolved = language if language in SUPPORTED_LANGUAGES else FALLBACK_LANGUAGE
    resources = _read_language(FALLBACK_LANGUAGE)
    if resolved != FALLBACK_LANGUAGE:
        resources.update(_read_language(resolved))
    return resources
