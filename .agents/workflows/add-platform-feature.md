# Workflow: Add or Extend Platform Feature

Step-by-step process for adding new platforms, entities, or capabilities to `adaptive-areas`.

## Steps

1. **Context & Specification Check (.agents/knowledge):**
   * Check existing project documentation, ADRs, and specifications in `.agents/knowledge/` (see [`knowledge`](.agents/skills/knowledge/SKILL.md)). Do not query external MCP tools.
   * Clarify ambiguous requirements via [`grill-me`](.agents/skills/grill-me/SKILL.md).

2. **Constants & Schema Definition:**
   * Define configuration keys, default options, and feature flags in [`custom_components/adaptive_areas/const.py`](custom_components/adaptive_areas/const.py).
   * Define schema validation rules and selector objects (`selector.EntitySelector`, etc.).

3. **Entity & Backend Implementation:**
   * Implement platform entities inheriting from base classes (`base/entities.py`, `sensor/base.py`, `binary_sensor/base.py`, `switch/base.py`).
   * Ensure `_attr_has_entity_name = True` and use `translation_key`.
   * Implement calculation logic in `base/adaptive.py` or dedicated helpers in `helpers/`.
   * Register platform in `custom_components/adaptive_areas/__init__.py` (`PLATFORMS`).

4. **Config Flow & Options Flow:**
   * Update [`custom_components/adaptive_areas/config_flow.py`](custom_components/adaptive_areas/config_flow.py) to expose settings in the appropriate category submenu (`general`, `presence`, `lighting`, `climate`, `fan`, `cover`, `media_player`, `thresholds`, `room_usage`).

5. **Translations (Localization):**
   * Add all new strings, step descriptions, and selector labels to [`custom_components/adaptive_areas/translations/en.json`](custom_components/adaptive_areas/translations/en.json) AND [`custom_components/adaptive_areas/translations/de.json`](custom_components/adaptive_areas/translations/de.json).
   * Validate JSON files via `python3 scripts/validate_json.py`.

6. **Unit & Integration Tests:**
   * Write targeted tests in `tests/test_<feature>.py`.
   * Validate config flow in `tests/test_config_flow.py`.
   * Verify schema migrations in `tests/test_init.py` if config schema was modified.

7. **Quality & Lint Verification:**
   * Run targeted pytest: `.tox/ha-stable/bin/pytest -q tests/test_<feature>.py`
   * Run linter: `scripts/lint`
