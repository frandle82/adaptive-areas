---
name: translations
description: >-
  Localization and translation management for Adaptive Areas.
  Use when adding new UI strings, entity names, or config flow options.
---

# Translations Guidelines

Instructions for managing UI localization and translation schemas in `adaptive-areas`.

## Related Files & Structure

```text
custom_components/adaptive_areas/translations/
├── en.json               # Master English translation file (semantic reference)
├── de.json               # German translation file (must maintain parity with en.json)
├── es.json               # Spanish translation file
├── fr.json               # French translation file
├── nl-NL.json            # Dutch translation file
├── pl.json               # Polish translation file
├── pt-BR.json            # Portuguese (Brazil) translation file
├── sv.json               # Swedish translation file
└── ta.json               # Tamil translation file
```

## Key Code References

* **Master English File:** [`custom_components/adaptive_areas/translations/en.json`](custom_components/adaptive_areas/translations/en.json)
* **German Translation File:** [`custom_components/adaptive_areas/translations/de.json`](custom_components/adaptive_areas/translations/de.json)
* **Config Flow Integration:** [`custom_components/adaptive_areas/config_flow.py`](custom_components/adaptive_areas/config_flow.py)
* **Validation Script:** [`scripts/validate_json.py`](scripts/validate_json.py)

## Best Practices & Rules

* **Master Reference:** English (`en.json`) is the primary source of truth for string keys, titles, descriptions, and formatting placeholders.
* **Dual Update Requirement:** Every addition or modification in `en.json` must be reflected with an equivalent German translation in `de.json`.
* **Config Flow Alignment:** Key paths in `translations/*.json` under `config.step`, `options.step`, `selector.*`, and `issues.*` must match the field keys used in [`custom_components/adaptive_areas/config_flow.py`](custom_components/adaptive_areas/config_flow.py) and [`custom_components/adaptive_areas/repairs.py`](custom_components/adaptive_areas/repairs.py).
* **Validation:** Run JSON validation (`python3 scripts/validate_json.py` or `scripts/lint`) and test coverage (`pytest tests/test_environment.py`) to ensure no missing translation keys, duplicate JSON keys, or invalid formatting syntax.
