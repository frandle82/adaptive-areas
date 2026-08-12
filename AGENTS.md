# Adaptive Areas Engineering Guide

This file is the authoritative repository-specific guide for coding agents working on Adaptive Areas. Read it before changing the integration. The implementation is the primary source of truth; when sources disagree, use this order: runtime implementation, constants and registration, config flow and schemas, tests, migrations and compatibility code, translations, feature documentation, then the README.

## Project Identity and Compatibility Boundary

- Project: Adaptive Areas
- Repository: `frandle82/adaptive-areas`
- Product: Home Assistant custom integration distributed through HACS
- Integration domain: `adaptive_areas`
- Manifest version: `1.3.0-rc.1`
- Main language: Python
- License: MIT
- Minimum Home Assistant version declared by HACS: `2026.8.0`

Treat `adaptive_areas` as a stable compatibility boundary. Do not rename the domain, config keys, feature IDs, stored config-entry structures, entity unique-ID prefixes, device identifiers, state values, or event names unless the user explicitly requests a breaking change and a tested migration is supplied. In particular, preserve the `adaptive_areas` entity/unique-ID prefix, `adaptive_area_device_` device prefix, and the historical event strings that omit the underscore between the words: `adaptiveareas_area_loaded` and `adaptiveareas_area_state_changed`.

The integration can import existing `magic_areas` config entries through the add-integration flow. This compatibility path copies data/options, rewrites generated `magic_areas_` entity references to `adaptive_areas_`, applies light-group migration, rejects duplicates by area ID, and leaves the original entry intact. Preserve attribution and import compatibility unless an explicit, tested migration replaces them.

## Functional Baseline

The following behavior already exists and must not be silently removed or degraded.

### Area model and entity discovery

Adaptive Areas wraps Home Assistant Areas in `AdaptiveArea` objects. Normal areas can be classified as `interior` or `exterior`. `AdaptiveMetaArea` represents the global, interior, exterior, and floor groupings; global includes all normal areas, interior/exterior include matching normal areas, and floor meta areas include areas with the same floor ID. Meta areas derive presence and secondary state from their child area-state entities rather than from independent room hardware.

For a normal area, entity discovery includes registry entities attached directly to the HA Area and entities belonging to devices in the Area. Explicit include entries are added; explicit excludes, disabled entities, the integration's own entities, and (by default) diagnostic/config entities are filtered out. `keep_only` narrows presence inputs without removing entities from other feature discovery. Entity and device registry changes relevant to the area trigger a coalesced config-entry update/reload when auto-reload is enabled. Listeners, scheduled callbacks, platforms, and area-owned resources must be released on unload.

### State and presence model

- Primary states are `clear` and `occupied`.
- `extended` is a built-in timed occupancy state.
- `dark`/`bright`, `sleep`, and `accented` are configurable secondary states. Dark is the inverse presentation of the configured light/brightness input; sleep and accented come from configured state entities. Secondary state calculation supports `any`, `all`, and `majority` where the schema exposes it.
- Sleep and accented are priority states in dependent control logic. State semantics and priority must be checked in `binary_sensor/presence.py` and every consumer before modification.

Normal-area presence can use configured platform domains (`media_player` and `binary_sensor` by default; `remote` and `device_tracker` are also allowed). Binary sensors are filtered by configured motion, occupancy, or presence device classes. Explicit presence-control entities may come from `person`, `device_tracker`, or `binary_sensor` and gate tracking using their valid active states. Presence supports include/exclude discovery, keep-only sensors, active/last-active metadata, and a clear timeout. Presence Hold, BLE Monitor, and Wasp in a Box can contribute secondary presence inputs when enabled.

The main area-state binary sensor restores state and publishes state/metadata updates. State changes are sent through the dispatcher event `adaptiveareas_area_state_changed`; area initialization is announced with `adaptiveareas_area_loaded`. These are dispatcher signals, not arbitrary renaming opportunities.

### Presence Hold, BLE, and Wasp in a Box

- Presence Hold creates a restorable config switch that keeps the area occupied while on. Its optional timeout uses the reusable/resettable switch timer and turns the switch off automatically; zero disables the timeout.
- BLE tracking does not perform Bluetooth scanning. It watches configured text/state sensor entities (for example sensors produced by ESPresense, Bermuda, or room-assistant) and turns its occupancy binary sensor on when a tracker reports the area's name or ID.
- Wasp in a Box is available only for normal areas and requires Aggregates. Motion/occupancy/presence classes act as the “wasp”; door and garage-door classes define the “box”. Its state machine retains inferred occupancy across door/motion transitions using the configured delay and timeout. Preserve its listeners, restoration, and retained-occupancy rules.

### Light groups

Light Groups creates `overhead`, `task`, `accent`, and `sleep` groups from explicit per-category selections plus an all-lights group. Meta areas create a passive all-lights group from collected child entities. A normal area's Light Control config switch enables automatic control.

Each category has a single current activation condition (`disabled`, `occupied`, `extended`, `sleep`, or `accented`), blocking states, and a brightness policy (`ignore`, `require_dark`, `turn_off`, or `dark_on_bright_off`). Automatic control reacts to primary and secondary area-state changes, turns groups off when required, respects dark/bright policy, and tracks manual group changes so user action can suppress automation until control is reset. Plain group `turn_on` targets all members; attribute-only updates target already active members where possible.

Legacy light configuration is intentional. Old multi-state, ANY/ALL state-rule, `act_on`, `require_dark`, and `turn_off_when_bright` values are migrated by `helpers/light_groups.py` and config-entry migration version 2.2. Do not delete old constants or reinterpret stored values without migration tests.

### Switch groups

The repository contains a functional, tested switch-group runtime for `task` and `sleep` groups, an aggregate all-switches group, configurable on/off actions, area-state triggers, and a Switch Group Control switch. It currently has a deliberately restricted product status: the options UI hides the feature and removes switch-group values stored in options; setup also sanitizes persisted option values. A legacy/imported configuration present in config-entry `data` can still activate the runtime implementation because setup does not remove data values. Do not describe Switch Groups as generally UI-enableable, remove the dormant compatibility implementation, or re-enable it without an explicit product decision, migration analysis, UI/translations/docs review, and tests.

### Climate, fan, cover, and media features

- Climate Control creates a restorable config switch for one selected climate entity. It maps `clear`, `occupied`, `extended`, and `sleep` to available presets; blank mappings do nothing. Clear wins immediately, then priority is sleep, extended, occupied. The occupied preset can be delayed by the configured occupancy threshold. Timers and dispatcher subscriptions must be cleaned up.
- Fan Groups creates one passive HA fan group for the normal area's fans. Fan Control is a separate config switch. While enabled it observes an aggregate sensor for the selected supported device class, requires the configured area state (extended by default), turns on at or above the setpoint, turns off below it if already on, and always turns off when clear. Supported tracked classes are defined in `FAN_GROUPS_ALLOWED_TRACKED_DEVICE_CLASS` and include temperature, humidity, CO/CO2, air-quality/VOC/gas/ozone/particulate/nitrogen/sulfur classes. It does not implement custom fan percentage or speed logic; group services are used.
- Cover Groups passively group area covers by Home Assistant cover device class, including a separate classless group. They do not implement area-state automation.
- Media Player Groups passively group area media players. Their separate control switch turns the group off when the area clears.
- The Area-Aware Media Player is created only by the Global meta area, using normal areas that enabled the feature and selected notification devices. Its `play_media`/announce proxy forwards the request to configured players in every currently occupied area whose configured notification-state filter matches. It does nothing when no eligible area/player is active; multiple eligible areas are all targeted. Do not claim support for unrelated media-player operations.

### Aggregates, threshold, and health

Aggregates group eligible entities by device class after the configured minimum count. Sensor aggregates also require a unit of measurement, choose the most common observed unit, normalize to the HA unit-system attribute when available, ignore nonnumeric states, and use mean by default. Power, current, and energy classes use sums; configured total and total-increasing device classes receive the corresponding HA state class. Binary aggregates use HA group semantics; connectivity and plug classes use all-members mode, while other supported classes use any-member mode. Supported classes and defaults live in `const.py`; do not infer support from prose alone.

The illuminance threshold is part of Aggregates, not an independently selectable feature. If aggregation includes illuminance and the threshold is nonzero, a binary sensor of device class `light` tracks the generated illuminance aggregate using an upper threshold and percentage-derived hysteresis. It is omitted when prerequisites are absent. Preserve unknown/unavailable behavior supplied by HA's threshold entity.

Health creates one problem-class binary group over selected hazard device classes (currently problem, smoke, moisture, safety, and gas defaults/support). Its group semantics expose whether any tracked distress entity is active. Keep the actual group implementation and supported classes synchronized with UI text and docs.

### Environment Engine

The Environment Engine evaluates available environmental inputs and exposes assessment, window advice, and ventilation/circulation fan requests; it never controls devices directly. Existing Fan Control consumes requests only while enabled, so the engine reuses existing control infrastructure instead of duplicating device control. Partial sensor availability is required: missing information remains unknown and must never be interpreted as healthy. Air-quality/ventilation needs outrank thermal efficiency, and ventilation-fan semantics must remain distinct from circulation-fan semantics. Environment decisions must remain privacy-safe and traceable.

### Generated platforms

Normal areas forward `binary_sensor`, `media_player`, `cover`, `switch`, `sensor`, `light`, and `fan`. Meta areas forward the implemented subset in `ADAPTIVE_AREAS_COMPONENTS_META`; the Global list is separately defined. A platform-list change requires matching setup/unload handling, area/meta-area analysis, cleanup behavior, translations, docs, and tests.

## Architecture and Repository Map

- `custom_components/adaptive_areas/__init__.py`: config-entry setup, option sanitization, registry-triggered reloads, platform forwarding/unloading, and config-entry migration.
- `const.py`: stable IDs, schemas, defaults, selectors, supported device classes, feature descriptors, states, platform lists, and event names. Search all consumers before changing a constant.
- `config_flow.py`: area/meta-area creation, legacy Magic Areas import, Options UI, selectors, validation, and stored feature configuration. Every field needs a complete UI → storage → runtime → observable-behavior path.
- `base/adaptive.py`: entity discovery, area/meta-area model, child collection, initialization, reload filters, and shared area state/config access.
- `base/entities.py`: generated IDs, unique IDs, device association, translation keys, and state restoration. Naming changes here are migrations, not cosmetic edits.
- `binary_sensor/presence.py`: primary/secondary state engine, timeouts, metadata, state sensors, and dispatcher signals. `binary_sensor/ble_tracker.py` and `wasp_in_a_box.py` implement their own listeners and state logic; `binary_sensor/__init__.py` creates aggregates, health, BLE, Wasp, and threshold entities.
- `light.py` and `helpers/light_groups.py`: light grouping/control/manual override and legacy config migration.
- `switch/`: feature-control switches, Presence Hold, fan/climate/media control, and the currently hidden legacy Switch Groups implementation.
- `fan.py`, `cover.py`, `media_player/`, `sensor/`, and `threshold.py`: platform-specific grouping, routing, aggregates, and threshold behavior.
- `helpers/area.py`, `helpers/timer.py`, and `util.py`: config-entry-to-area construction, reusable timers, and registry cleanup.
- `diagnostics.py`, `repairs.py`, and `system_health.py`: privacy-safe native Home Assistant support artifacts, actionable configuration issue lifecycle, and integration-wide count-only health reporting. `helpers/diagnostics.py` contains reusable redaction helpers.
- `helpers/decision_trace.py`: bounded per-area Decision Trace storage. It is in-memory only, holds at most 20 oldest-to-newest exported entries, and is cleared on unload; trace failures must never alter or interrupt runtime behavior.
- `translations/`: HA config/options/entity/device/selector UI strings. English is the semantic reference; German receives special quality attention. Missing locale strings may use HA fallback rather than invented translations.
- `tests/`: behavioral contracts and HA test fixtures. Do not change expectations simply to conceal a regression.
- `docs/source/`, `README.md`, and `info.md`: user-facing documentation/HACS rendering. Implementation wins when they disagree, but verified doc defects should be corrected.
- `config/configuration.yaml`, `.devcontainer.json`, `.vscode/`, `scripts/develop`, and `scripts/setup`: local HA development environment.
- `custom_components/adaptive_areas/brand/` and `design/adaptive_areas/`: 256/512 PNG assets and editable SVG sources. Preserve transparent, trimmed light/dark assets and Adaptive Areas identity unless branding is explicitly requested.
- `.github/workflows/`, `.github/release-drafter.yml`, `scripts/commit`, and `scripts/set_version.py`: CI, Conventional Commits, draft/release automation, and version synchronization. Do not alter release machinery as incidental cleanup.

## Mandatory Change-Impact Analysis

Before a functional edit, inspect all applicable layers:

1. runtime implementation and directly interacting features;
2. constants, IDs, defaults, schemas, and config keys;
3. config/options flow and selectors;
4. entity creation, IDs, device association, and cleanup;
5. state listeners, dispatcher subscriptions, callbacks, and timers;
6. normal-area, meta-area, Global, interior/exterior, and floor behavior;
7. stored data/options, migration, legacy import, and fallback handling;
8. English/German and other translations;
9. targeted and cross-feature tests;
10. README, HACS info, feature docs, examples, and troubleshooting.

Inspect both sides of a feature interaction. Presence/state edits require review of lights, climate, fans, media routing, and meta areas. Config-flow edits require storage-consumer tracing, migrations, translations, and existing entries. Naming edits require unique IDs, registry cleanup, translations, docs, and tests. Aggregate edits require thresholds, fan control, health/binary grouping, units, and state classes.

## Backwards Compatibility Rules

Preserve existing behavior by default. Never silently rename keys, states, feature IDs, event strings, entity/unique IDs, or stored structures; remove options or compatibility paths; reinterpret stored values; change behavior-changing defaults; or alter generated entity semantics. Existing compatibility comments are intentional until repository-wide evidence proves otherwise.

When a compatibility-breaking change is explicitly required:

1. identify installed-system impact;
2. implement a versioned config-entry migration;
3. retain safe fallback reads where practical;
4. add migration and downgrade/legacy tests;
5. update UI, translations, and documentation;
6. call out the breaking change in release-facing material.

## Home Assistant UI, Translation, and Rendering Quality

Treat config/options flows and entity presentation as product code. For every relevant edit, audit labels, descriptions, selectors, options, defaults, units, required/optional behavior, filters, menus, back/finish behavior, feature visibility, and runtime application. Flag duplicate fields, empty selectors, internal enum values shown without translated labels, saved-but-unused options, applied-but-inaccessible options, disabled-feature settings, and mismatched reconfigure/options paths.

Compare `translations/en.json` keys with runtime translation keys and inspect German wording/key coverage. Check other locale files for malformed JSON, placeholders, missing/obsolete keys, stale `Magic Areas`/`magic_areas` user-facing text, obsolete links, and placeholder mismatches. Do not fabricate translations; report fallback coverage when a competent translation is unavailable.

For visible changes, inspect entity/device names, icons, state/attribute labels, selector labels, config forms, HACS/Markdown rendering, images, and light/dark brand variants. Look for raw keys, duplicate labels, truncation, malformed Markdown, broken links/images, outdated screenshots, bad Unicode, and misleading wording. Use a running HA development UI when practical. If no browser rendering was performed, say that only a structured static UI audit was completed.

Brand assets must retain the expected `icon.png`/`dark_icon.png` at 256×256 and `@2x` variants at 512×512, RGBA transparency, low padding, and readability on both themes. Do not substitute Magic Areas or Home Assistant marks.

## Proactive Regression and Bug Audit

Every substantial change includes a scoped audit of the changed and directly connected subsystems. Trace or reproduce suspected issues before editing; add a regression test where feasible; use the smallest robust fix; rerun related tests. Do not make speculative behavioral changes.

Check for exceptions and None handling; unavailable/unknown/non-numeric states; incorrect awaits or async service usage; listener/timer leaks, duplicate subscriptions, stale callbacks, and races; reload loops and stale area/entity/device references; improper unload/registry cleanup; duplicate or invalid IDs; restoration errors; deprecated or invalid HA APIs; meta-area inconsistencies; contradictory feature actions; unexpected services; and automation that continues while its control switch or feature is disabled.

Before replacing an apparently old Home Assistant API, verify deprecation against the repository's supported HA version. Keep HA interactions async-safe and introduce no unnecessary external dependencies.

Diagnostics must remain safe to share: never export raw personal names, entity object IDs, device-tracker or BLE identifiers, hardware unique IDs, exact locations, media content, credentials, tokens, or unsanitized exceptions. New stored entity-reference fields must be included in Repair validation when their disappearance can break current behavior. Future automatic-control features should record bounded, privacy-safe executed, skipped, and failed decisions at existing decision points without reshaping their control logic.

## Tests and Validation

Tests are specifications. Map work to these suites:

- setup, migration, and reload lifecycle: `test_init.py`, `test_area_reload.py`, `test_config_flow.py`, `test_light_group_migration.py`;
- presence and state/meta-area behavior: `test_area_state.py`, `test_meta_area_state.py`, `test_timer.py`;
- BLE and Wasp: `test_ble_tracker_monitor.py`, `test_wasp_in_a_box.py`;
- aggregates, health-adjacent grouping, and thresholds: `test_aggregates.py`, `test_meta_aggregates.py`, `test_threshold.py`;
- groups and control: `test_light.py`, `test_switch_groups.py`, `test_fan.py`, `test_cover.py`, `test_media_player.py`, `test_climate_control.py`.

Use targeted tests while iterating, for example:

```bash
pytest -q tests/test_fan.py
```

Repository-level checks are:

```bash
scripts/lint
scripts/test stable
```

`scripts/lint` resolves the latest stable Home Assistant package and runs the `tox -e lint` environment. `scripts/test stable` runs the stable HA test matrix; `scripts/test beta` and `scripts/test both` exist for compatibility probing. CI also enforces Ruff/Black/import formatting, pytest/tox, Hassfest, HACS validation, duplicate JSON-key validation, and Conventional Commit messages. If network, Python, HA dependencies, or environment limitations prevent a check, run the strongest local alternative and report the exact omission; never claim an unrun check passed.

## Documentation and Repository Discipline

After behavior changes inspect the README, `docs/source/`, `info.md`, `hacs.json`, manifest links, examples, troubleshooting, and feature navigation. Find implemented-but-undocumented or documented-but-unavailable features, stale naming/domains/URLs, bad relative links, duplicated material, and screenshots or examples that no longer match the UI. Correct proven defects, but do not turn ambiguous dormant behavior into a public promise.

Follow existing Ruff, Black, isort, typing, HA, and naming conventions. Keep central behavior centralized and reuse constants. Prefer root-cause fixes over broad rewrites. Do not remove apparently unused compatibility code without repository-wide search, migration analysis, and tests. Preserve unrelated user work in a dirty tree.

Commits follow Conventional Commits. Stage only intended files and use `scripts/commit "type(scope): description"` when asked to commit. Do not casually change release/version automation. Never commit caches, local HA runtime state, generated junk, editor state, or temporary visual assets.

## Completion Checklist

Before declaring a task complete:

- [ ] Requested behavior is implemented and the complete diff was reviewed.
- [ ] Existing behavior and directly connected features were checked for regressions.
- [ ] Normal, meta, Global, interior/exterior, and floor behavior was considered where relevant.
- [ ] Backwards compatibility, stored config, imports, and migrations were considered.
- [ ] Config flow, constants, storage, and runtime consumers remain consistent.
- [ ] Entity IDs, unique IDs, event names, and state values remain stable unless intentionally migrated.
- [ ] Listener, timer, registry, reload, restoration, and unavailable-state behavior was audited.
- [ ] English/German and translation key/placeholder coverage was checked.
- [ ] User-visible rendering was inspected when relevant, with live versus static inspection reported accurately.
- [ ] README, HACS info, docs, examples, and links were updated when behavior changed.
- [ ] Relevant regression tests were added or updated without weakening unrelated contracts.
- [ ] Targeted tests and applicable `scripts/test stable` checks pass.
- [ ] `scripts/lint` and applicable CI-equivalent validation pass.
- [ ] No obvious exception, dead path, raw UI key, stale reference, or unrelated modification was introduced.
- [ ] No new user-facing Magic Areas name remains except import labeling, compatibility, attribution, or history.
- [ ] Every check that could not run is reported explicitly.
