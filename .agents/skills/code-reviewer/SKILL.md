---
name: code-reviewer
description: >-
  Automated code review and diff inspection for security, performance, HA standards, and code quality.
  Use before finalizing any change, creating a pull request, or proposing commits.
---

# Code Reviewer & Quality Inspection Guidelines

Automated quality review guidelines to inspect diffs, prevent regressions, enforce Home Assistant core standards, and ensure production-grade code.

## Purpose

The `code-reviewer` skill acts as an authoritative, thorough reviewer before code changes are committed or presented as complete. It spots regressions, resource leaks, breaking changes, and performance pitfalls early.

## When to Trigger

* Before reporting a task as complete.
* When evaluating `git diff` before submitting changes or proposing commits.
* During pull request review workflows.
* Whenever refactoring critical core logic in `custom_components/adaptive_areas/`.

## Review Checklist

Systematically inspect code diffs against these 7 critical review categories:

### 1. Home Assistant Core Standards
* [ ] **Entity Naming:** Base entities set `_attr_has_entity_name = True`.
* [ ] **Translation Keys:** Entities and config options use `translation_key` rather than hardcoded string names.
* [ ] **Entity Descriptions:** Prefer `EntityDescription` dataclasses (`SensorEntityDescription`, `BinarySensorEntityDescription`, etc.) for platform definitions.
* [ ] **Device Info:** Entities are correctly linked to device registry via `DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, ...)`.
* [ ] **Type Annotations:** Full type coverage adhering to `py.typed`; avoid raw untyped `Any` without reason.

### 2. Asynchronous Safety & Event Loop Hygiene
* [ ] **No Blocking Calls:** No sync I/O, disk writes, time.sleep, or blocking network requests inside the event loop. Use `hass.async_add_executor_job` if unavoidable.
* [ ] **Listener Cleanup:** All state listeners (`async_track_state_change_event`) and dispatcher connections (`async_dispatcher_connect`) registered in entities or coordinator must have cleanup hooks (`async_on_unload` or within `async_will_remove_from_hass`).
* [ ] **Timer Cleanup:** Internal timers and callbacks are cancelled on entity removal or area reload to prevent memory leaks and zombie execution.

### 3. State Handling & Edge Cases
* [ ] **State Resilience:** State conversions safely guard against `None`, `STATE_UNKNOWN`, and `STATE_UNAVAILABLE`.
* [ ] **Numeric Safety:** Uses safe conversion helpers (`try ... float(...) except (ValueError, TypeError): ...`) instead of raw float parsing.
* [ ] **State Machine Integrity:** Area operational state calculations remain deterministic under unexpected sensor flaps.

### 4. Backward Compatibility & Storage Schema
* [ ] **Unique IDs:** `unique_id` format is preserved. NEVER alter existing entity unique IDs without an explicit migration path.
* [ ] **Config/Options Flow Schema:** Modified options retain compatibility with existing user configs. Default fallbacks must exist for newly introduced keys.
* [ ] **Schema Versioning:** If `entry.data` or `entry.options` keys change or are renamed, bump `ConfigEntry.version` and implement `async_migrate_entry`.

### 5. Performance & Scalability
* [ ] **Minimal Listener Footprint:** Listeners should track only the specific entity IDs required, not global state changes.
* [ ] **Algorithm Complexity:** Avoid $O(N^2)$ loops across areas or all entities in the state machine.
* [ ] **Debouncing & Throttling:** Rapid sensor updates (e.g. illuminance, power) must not trigger expensive cascade calculations unnecessarily.

### 6. Security, Privacy & Diagnostics
* [ ] **Sensitive Data Scrubbing:** Area traces, diagnostics, and debug logs must sanitize private credentials, tokens, and identifying information.
* [ ] **No Speculative Debug Code:** Remove temporary `print()` statements, test monkey-patches, and unused imports before completion.

### 7. Test Verification & Code Style
* [ ] **Full Test Coverage:** Unit and integration tests cover both happy paths and edge cases (e.g. unavailable sensors, reloads).
* [ ] **Lint Clean:** Passes `scripts/lint` (`tox -e lint` with ruff, black, pylint, validate_json).
* [ ] **Regression Suite:** Passes `scripts/test stable`.

## Step-by-Step Review Workflow

1. **Inspect Git Diff:**
   ```bash
   git status --short --branch
   git diff
   ```
2. **Execute Static Analysis & Linter:**
   ```bash
   scripts/lint
   ```
3. **Execute Relevant Test Suites:**
   ```bash
   .tox/ha-stable/bin/pytest -q tests/test_<affected_module>.py
   ```
4. **Formulate Review Summary:**
   Provide a concise review report in German covering:
   - Evaluated changes and files
   - Potential risks or identified edge cases
   - Test results (passed/failed)
   - Quality verdict (Approved / Needs Attention)
