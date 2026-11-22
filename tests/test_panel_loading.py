"""Loading path of the Adaptive Areas panel and the shared entity picker."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "adaptive_areas"
FRONTEND = INTEGRATION / "frontend"
LOADER = FRONTEND / "adaptive-areas-loader.js"
PICKER = FRONTEND / "aa-entity-picker.js"
PANEL = FRONTEND / "adaptive-areas-panel.js"
PANEL_PY = INTEGRATION / "panel.py"
TEXTS = INTEGRATION / "dashboard_texts"


def test_panel_module_url_points_to_the_loader() -> None:
    """The panel is registered through the loader, not through a global extra module."""
    source = PANEL_PY.read_text(encoding="utf-8")
    assert "adaptive-areas-loader.js" in source
    assert "add_extra_js_url" not in source


def test_loader_imports_the_picker_before_the_panel() -> None:
    """The custom element exists before the panel renders; the loader is the only entry."""
    source = LOADER.read_text(encoding="utf-8")
    picker_at = source.index("import(`./aa-entity-picker.js${query}`)")
    panel_at = source.index("import(`./adaptive-areas-panel.js${query}`)")
    assert picker_at < panel_at


def test_loader_keeps_the_panel_usable_when_the_picker_fails() -> None:
    """A failing picker import is caught and the panel import still runs."""
    source = LOADER.read_text(encoding="utf-8")
    assert "catch" in source
    assert "import(`./adaptive-areas-panel.js${query}`)" in source.split("catch", 1)[1]


def test_loader_passes_the_integration_version_to_its_modules() -> None:
    """Cache: the loader reads its own ?v= and gives the same version to every module it imports."""
    source = LOADER.read_text(encoding="utf-8")
    assert 'new URL(import.meta.url).searchParams.get("v")' in source
    assert "const query = version" in source
    assert "${query}" in source


def test_panel_module_url_carries_the_manifest_version() -> None:
    """The loader URL is versioned with the installed integration version (manifest)."""
    source = PANEL_PY.read_text(encoding="utf-8")
    assert "adaptive-areas-loader.js?v={integration.version}" in source


def test_picker_registers_once() -> None:
    """Re-opening the panel or re-importing the picker must not define the element twice."""
    source = PICKER.read_text(encoding="utf-8")
    assert 'if (!customElements.get("aa-entity-picker"))' in source
    assert source.count('customElements.define("aa-entity-picker"') == 1


def test_panel_does_not_import_modules_itself() -> None:
    """The panel is evaluated as a classic script in the harness; it must not use import syntax."""
    source = PANEL.read_text(encoding="utf-8")
    assert not re.search(r"^\s*import\s", source, re.MULTILINE)


def test_every_picker_text_exists_in_both_languages() -> None:
    """Texts used by the picker and the notice live in dashboard_texts in DE and EN."""
    keys = {
        "pickerSearch",
        "pickerNone",
        "pickerCount",
        "pickerRemove",
        "pickerNoMatches",
        "pickerNotFound",
        "pickerLimit",
        "pickerStatusAdded",
        "pickerStatusRemoved",
        "pickerUnavailable",
        "fxMarkNotFound",
        "fxOutOfScope",
        "fxMarkUnavailable",
    }
    for language in ("de", "en"):
        data = json.loads((TEXTS / f"{language}.json").read_text(encoding="utf-8"))
        missing = sorted(key for key in keys if key not in data)
        assert not missing, f"{language}: {missing}"
