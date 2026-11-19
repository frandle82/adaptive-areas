---
name: testing
description: >-
  Testing procedures, linting, and test execution for Adaptive Areas.
  Use when running unit tests, linting, or verifying code quality.
---

# Testing & Verification Guidelines

Instructions for executing tests, linting, and code quality checks in `adaptive-areas`.

## Related Files & Structure

```text
adaptive-areas/
├── tests/                          # Pytest unit & integration test suites
│   ├── conftest.py                 # Core fixtures, event loop & mock setup
│   ├── const.py                    # Test constants and sample payloads
│   ├── helpers.py                  # Helper functions for setting up mock areas & entities
│   ├── mocks.py                    # Mock classes for HA registries and state machines
│   ├── test_init.py                # Entry setup, unload, reload & schema migration tests
│   ├── test_config_flow.py         # ConfigFlow & OptionsFlow UI handler tests
│   ├── test_environment.py         # Climate, WAQI, dew point & environment aggregator tests
│   ├── test_light.py               # Adaptive lighting control & profile interpolation tests
│   ├── test_light_group_migration.py # Migration tests for legacy light group structures
│   ├── test_climate_control.py     # Climate automation switch & logic tests
│   ├── test_fan.py                 # Fan automation switch & circulation tests
│   ├── test_media_player.py        # Area-aware media player entity tests
│   ├── test_cover.py               # Adaptive shading / cover platform tests
│   ├── test_wasp_in_a_box.py       # Wasp-in-a-box presence algorithm tests
│   ├── test_ble_tracker_monitor.py # BLE presence tracker monitor tests
│   ├── test_area_state.py          # Area operational state calculation tests
│   ├── test_area_reload.py         # Area reload & dynamic entity update tests
│   ├── test_aggregates.py          # Area sensor aggregation tests
│   ├── test_meta_aggregates.py     # Hierarchical meta-area aggregate sensor tests
│   ├── test_meta_area_state.py     # Meta-area operational state tests
│   ├── test_cleaning_tracker.py    # Room usage & cleaning tracker tests
│   ├── test_switch_groups.py       # Switch group control tests
│   ├── test_threshold.py           # Threshold sensor & binary helper tests
│   ├── test_timer.py               # Internal timer helper tests
│   ├── test_repairs.py             # Issue registry & diagnostic repair tests
│   └── test_system_health.py       # HA System Health info endpoint tests
├── scripts/
│   ├── lint                        # Runs tox -e lint (ruff, black, pylint, pre-commit, validate_json)
│   ├── test                        # Runs tox -e ha-stable / ha-beta
│   └── validate_json.py            # Validates JSON files (translations, manifests)
└── .tox/                           # Pre-configured virtualenvs (lint, ha-stable, ha-beta)
```

## Test Commands

* **Specific Test File:**
  ```bash
  .tox/ha-stable/bin/pytest -q tests/test_<bereich>.py
  # Or with active virtual environment:
  pytest -q tests/test_<bereich>.py
  ```

* **Specific Test Function:**
  ```bash
  .tox/ha-stable/bin/pytest -q tests/test_<bereich>.py -k "<test_name>"
  ```

* **Linting & Formatting:**
  ```bash
  scripts/lint
  # Or directly via tox:
  .tox/lint/bin/tox -e lint
  ```

* **Full Stable Test Suite:**
  ```bash
  scripts/test stable
  ```

* **JSON Translations / Manifest Validation:**
  ```bash
  python3 scripts/validate_json.py
  ```

## Best Practices & Rules

* **Environment Fallback:** If `pytest` or `tox` are not available in the global `PATH`, use the executables in `.tox/ha-stable/bin/pytest` or `.tox/lint/bin/tox`.
* **Assertion Integrity:** Tests are specifications; never weaken or remove assertions to mask a regression.
* **Mock Hygiene:** Use fixtures from `conftest.py` and helpers from `tests/helpers.py` / `tests/mocks.py` to maintain consistent HA state mocking.
* **Transparent Reporting:** Always report exact test results (passed / failed) and explicitly note any unexecuted checks in German.
