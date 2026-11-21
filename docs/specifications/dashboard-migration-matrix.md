# Dashboard migration matrix (function and interface inventory)

Purpose: regression safety while the existing panel is modernised in steps. This file lists what the current panel (`custom_components/adaptive_areas/frontend/adaptive-areas-panel.js`, Phase E) does, where each function goes in the modernised panel, and what still has to be verified. It is not a new design concept; the normative specification is [dashboard.md](dashboard.md).

Status legend: **verified** = found in the panel source or backend schema; **to verify** = must be checked in the source before the matching step is implemented.

## 1. WebSocket commands

| Command | Used by current panel | Access | Writes | Target location in new panel | Status |
|---|---|---|---|---|---|
| `adaptive_areas/get_overview` | yes | all users | no | Monitoring › Überblick | verified |
| `adaptive_areas/get_area` | no | all users | no | Monitoring › Bereichsdetail (new use) | verified (backend) |
| `adaptive_areas/get_area_configuration` | yes | admin | no | Verwaltung › Bereichskonfiguration | verified |
| `adaptive_areas/get_light_runtime_status` | yes | admin | no | Analyse › Lichtautomatik | verified |
| `adaptive_areas/get_climate_runtime_status` | yes | admin | no | Analyse › Klimaautomatik | verified |
| `adaptive_areas/get_global_configuration` | yes | admin | no | Verwaltung › Globale Einstellungen | verified |
| `adaptive_areas/update_global_configuration` | yes | admin | yes | Verwaltung › Globale Einstellungen | verified |
| `adaptive_areas/create_area` | yes | admin | yes | Verwaltung › Bereichsverwaltung | verified |
| `adaptive_areas/update_area` | yes | admin | yes | Verwaltung › Bereichskonfiguration | verified |
| `adaptive_areas/delete_area` | yes | admin | yes | Verwaltung › Bereichsverwaltung (confirm dialog) | verified |
| `adaptive_areas/get_diagnostics` | yes (new use) | admin | no | Analyse › Diagnose | verified (backend, browser harness) |
| `adaptive_areas/subscribe_updates` | yes | all users | no | Datenschicht (push of area summaries; data-free `areas_changed` event when the set of loaded Areas changes) | verified (backend tests, browser harness) |
| `adaptive_areas/get_decision_trace` | yes (new) | admin | no | Analyse › Decision Trace | verified (backend, tests, browser harness) |

## 2. Global settings (admin)

| Function | Source | Target | Status |
|---|---|---|---|
| Weather entity (`weather_entity`) | panel field, `update_global_configuration` | Globale Einstellungen | verified |
| Global brightness sensor (`global_light_sensor`) | panel field, same command | Globale Einstellungen | verified |
| Rule: unchanged stored entity IDs accepted even when unavailable; explicit `null` removes; unsent fields kept; rejected update persists nothing | Phase E decision | unchanged | verified (ROADMAP, CURRENT_STATE) |

## 3. Area list and lifecycle (admin)

| Function | Source | Target | Status |
|---|---|---|---|
| List of Areas with floor/type | `get_overview` | Bereichsverwaltung and Bereiche | verified |
| Add Area from unused Home Assistant Areas (`available_areas`) | `create_area`, backend `available_areas` | Bereichsverwaltung › Erstellen | verified (label `add`, `haArea`) |
| Delete Area with confirmation (`confirmDelete`) | `delete_area` | Bereichsverwaltung › Löschen | verified (label `confirmDelete`) |
| Meta-Areas (floor, interior, exterior, global) shown separately | `get_overview` (`meta_areas`) | Überblick (aggregates, not counted) | verified (backend), to verify (panel) |

## 4. Area configuration (admin, `update_area`)

Sections as labelled in the current panel: general options, presence tracking, advanced state tracking, feature selection.

| Section | Function | Backend field group | Target sub-page | Status |
|---|---|---|---|---|
| Allgemein | Area type (interior/exterior) | `CONF_TYPE` | Allgemein | verified (labels `interior`, `exterior`) |
| Allgemein | Home Assistant area mapping | `CONF_ID`, `haArea` | Allgemein | verified (label) |
| Allgemein | Further general fields (room category, outdoor sensors, passive cooling, humidity duration, reload on registry change, ignore diagnostic entities, keep-only entities) | `REGULAR_AREA_SCHEMA` | Allgemein / Raumklima | to verify: which of these the current panel edits |
| Präsenz | Presence sources (include/exclude), presence release entities | `CONF_INCLUDE_ENTITIES`, `CONF_EXCLUDE_ENTITIES`, `CONF_PRESENCE_CONTROL_ENTITIES` | Präsenz & Timeouts | verified (labels `presence`, `presenceReleaseHint`, `keepOnlyHint`) |
| Präsenz | Clear timeout | `CONF_CLEAR_TIMEOUT` | Präsenz & Timeouts | verified (label `vacancyDelaySeconds` for lights; to verify for presence) |
| Präsenz | Presence device platforms, sensor device classes | `CONF_PRESENCE_DEVICE_PLATFORMS`, `CONF_PRESENCE_SENSOR_DEVICE_CLASS` | Präsenz & Timeouts | to verify |
| Erweiterte Zustände | Secondary states: sleep, extended, accented, dark/bright, occupancy delay and "occupied after" | `CONF_SECONDARY_STATES` (`SECONDARY_STATES_SCHEMA`) | Erweiterte Zustände | verified (labels `states`, `occupancyDelay`, `occupancyAfter`, `activationSleep`, `activationExtended`, `activationAccented`); threshold validated (`thresholdInvalid`) |
| Funktionen | Enabled features | `CONF_ENABLED_FEATURES` (`FEATURES_SCHEMA`) | Funktionen | verified (label `features`) |
| Funktionen | Feature list: light, light_groups, aggregates, environment, room_usage, climate_control, fan_groups, cover_groups, media_player_groups, area_aware_media_player, presence_hold, ble_trackers, wasp_in_a_box, health | `CONF_FEATURE_LIST*` | Funktionen | verified (labels) |
| Validation | Backend validation with field errors (`validate_area_options`, `validation_errors`) | backend | all sections | verified (backend); panel display of field errors to verify |
| Validation | Name, duplicate/empty name rules | backend schema | Allgemein | to verify |

## 5. Lichtautomatik (admin)

| Function | Target | Status |
|---|---|---|
| Light policy: turn on at or below (lx) (`turn_on_below`) | Lichtautomatik › Automatik | verified (`lightOn`) |
| Light policy: turn off at or above (lx) (`turn_off_above`) | Lichtautomatik › Automatik | verified (`lightOff`) |
| Vacancy delay in seconds (`vacancy_delay`) | Lichtautomatik › Automatik | verified (`vacancyDelaySeconds`) |
| Brightness behaviour: ignore, require dark, turn off when bright, dark on / bright off | Lichtautomatik › Automatik | verified (`brightIgnore`, `brightRequireDark`, `brightTurnOff`, `brightDarkOnBrightOff`) |
| Activation: when occupied, accented, sleeping, extended | Lichtautomatik › Automatik | verified (`activationOccupied`, `activationAccented`, `activationSleep`, `activationExtended`) |
| Light groups: overhead, task, accent, sleep; per group activation, blocking states, brightness behaviour | Lichtgruppen | verified (`lightGroups`, `light_groups`, `lightEmptyHint`) |
| Light runtime: decision (turn on / turn off / hold / no action), manual override (none / forced on / forced off), presence, vacancy timer, targets available | Analyse › Lichtautomatik | verified (`policyLabel`, `overrideLabel`, `vacancyLabel`, `targetsLabel`) |
| Empty state: no Area with light automation | Lichtautomatik | verified (`noLightAreas`, `lightEmptyHint`) |

Rule to keep: the light decision is taken from the backend runtime status. It is never derived from occupancy in the panel.

## 6. Klimaautomatik (admin)

| Function | Target | Status |
|---|---|---|
| Thermostat (entity, friendly name, entity ID as fallback) | Klimaautomatik › Konfiguration | verified (`climateControl`, `thermostat`, F2 decision) |
| Presets: occupied, clear, sleep, extended (exact names as provided by the thermostat) | Klimaautomatik › Konfiguration | verified (`presetOccupied`, `presetClear`, `presetSleep`, `presetExtended`, `presetHint`) |
| Occupancy threshold in minutes (`climate_occupancy_threshold`), validated as positive whole number | Klimaautomatik › Konfiguration | verified (`occupancyHint`, `thresholdInvalid`) |
| Feature toggle `climate_control` | Funktionen | verified |
| Runtime: automatic active / inactive, availability, area state, decision, current and selected preset (separate), waiting for threshold | Analyse › Klimaautomatik | verified (`currentPreset`, `chosenPreset`, `statusUnavailable`) |
| Empty states: no Area with climate control; enabled but incomplete; not enabled | Klimaautomatik | verified (`noClimateAreas`, `climateIncomplete`, `climateNotActivated`) |
| Rule: selected and current presets come only from runtime data, never from occupancy alone | backend | verified (ROADMAP/Soll-Bild) |

## 7. Overview and status

| Function | Target | Status |
|---|---|---|
| Overview per Area: occupancy, configured light and climate activation, sleep and extended state (configured, not runtime) | Überblick | verified (ROADMAP M1/M2) |
| Overview hint: "Status of your Adaptive Areas" | Überblick | verified (`overviewHint`) |
| Current area status (runtime) | Bereichsdetail | verified (`currentStatus`) |
| Dynamic tabs: light tab when `light` or `light_groups` enabled; climate tab when `climate_control` enabled; fallback to Overview when a tab disappears | Navigation | verified (`_getDynamicTabs`, Soll-Bild) |
| Non-admins see Overview only in the current panel | Navigation | verified; **approved change**: Overview, Areas and area details are readable for non-admins (Freigabe 2) |

## 8. Diagnostics and information

| Function | Target | Status |
|---|---|---|
| Hint to native integration diagnostics ("remain available through HA's integration diagnostics") | Analyse › Diagnose (with link, no duplication) | verified (`diagnosticsHint`) |
| `get_diagnostics` data (runtime issues, aggregation, sources) | Analyse › Diagnose | verified (backend); not shown by current panel |

## 9. States and feedback

| State | Current label | Target | Status |
|---|---|---|---|
| Loading | `loading`, `statusLoading` | Schritt 2 shell and status system | verified |
| Error (panel) | `error` | shell error state | verified |
| Error (global settings) | `loadFailed`, `saveFailed` | global settings | verified |
| Current status unavailable | `statusUnavailable` | area and runtime views | verified |
| Empty (no Areas) | `empty` | Überblick | verified |
| Unsaved changes | `unsavedChanges` | all forms | verified |
| Saving | `saving` | all forms | verified |
| Confirm delete | `confirmDelete` | Bereichsverwaltung | verified |
| Unavailable value | `unavailable` | all views (never 0/false/clear) | verified |

## 10. Interface rules that must not change

- No new configuration options; no changes to config entries, entity IDs, unique IDs or stored schemas (`docs/specifications/dashboard.md` §18).
- Admin-only write paths stay server-side (`require_admin`). The panel only hides controls.
- Save rules of Phase E stay binding (see section 2 and `ROADMAP.md`).
- Light and climate decisions come from runtime status commands; the panel does not infer them.

## 11. Resolved verifications

1. **Panel fields (general and presence).** The panel edits: include and exclude entities, presence release entities, presence device platforms and sensor device classes, keep-only entities, clear timeout (presence), secondary states, enabled features, light policy, light groups, climate configuration. The panel does **not** edit: room category, outdoor and surface temperature sensors, area temperature and humidity sensors, environment windows and fans, passive cooling delta, humidity duration, reload-on-registry-change, ignore-diagnostic-entities. The backend merges partial updates with the stored configuration (`validate_area_options(current, updates)`), so these fields are preserved on save and must stay preserved in the new panel (no configuration option is removed).
2. **Field errors.** The panel displays backend validation errors per input (`errors[input.name]`). Preserve this in the new panel.
3. **Meta-Areas in the panel.** The panel does not render Meta-Areas as a separate group (no dedicated logic in the source). Meta-Areas are new in the Überblick according to the specification.
4. **Translation keys.** The EN and DE dictionaries have identical key sets (127 and 128 entries; the count differs by one duplicate key). Migration to `translations/*.json` must keep both sets complete.

## 12. Command count

- Registered WebSocket commands: 13.
- Overview DTO additions (step 4.3, additive): `floor_id`, `floor_name` for every Area; `members` for Meta-Areas (IDs of loaded physical Areas). No storage or configuration change; existing fields unchanged. Non-administrators receive the same fields (identifiers, no entity IDs).
- Used by the current panel (verified in the panel source, 2026-11-20): 12 (`create_area`, `delete_area`, `get_area_configuration`, `get_climate_runtime_status`, `get_decision_trace`, `get_diagnostics`, `get_global_configuration`, `get_light_runtime_status`, `get_overview`, `subscribe_updates`, `update_area`, `update_global_configuration`). `get_global_configuration` and `get_area_configuration` are also read immediately before each regular write (conflict check, B05).
- Not used by the current panel: 1 (`get_area`). The earlier statements "9 used, 4 unused" and "10 used, 3 unused" were wrong or outdated; the trace and diagnostics views added the two analysis commands.

## 13. Audit of area options (Schritt 6.1, 2026-11-20)

Source: `REGULAR_AREA_SCHEMA` in `const.py` compared with the keys the panel sends in `_save` (general and presence fields, secondary states, feature selection). The save merges the stored options with the update in `validate_area_options` before writing, so a field the panel does not send is kept (test `tests/test_area_options_migration.py`).

| Schema field | Meaning | Panel today | Stored by | Notes |
|---|---|---|---|---|
| `type` | interior or exterior | edited | update_area | |
| `include_entities`, `exclude_entities` | analysis scope | edited | update_area | |
| `presence_control_entities` | presence release | edited | update_area | |
| `reload_on_registry_change`, `ignore_diagnostic_entities` | behaviour flags | edited | update_area | |
| `presence_device_platforms`, `presence_sensor_device_class` | presence tracking | edited | update_area | |
| `keep_only_entities` | confirming entities | edited | update_area | |
| `clear_timeout` | presence release delay | edited | update_area | |
| `secondary_states` (dark, accent, sleep, extended, timeouts) | secondary states | edited | update_area | |
| `enabled_features` | feature selection | edited | update_area | |
| `area_temperature_sensor`, `area_humidity_sensor` | Area climate sensors | **not edited** | preserved | Missing in the panel |
| `room_category` | purpose category (6 values) | **not edited** | preserved | Missing in the panel |
| `outdoor_temperature_entity`, `outdoor_humidity_entity`, `surface_temperature_entity` | environment sources | **not edited** | preserved | Missing in the panel |
| `relevant_windows` | environment windows | **not edited** | preserved | Missing in the panel |
| `passive_cooling_delta`, `humidity_duration` | environment parameters | **not edited** | preserved | Missing in the panel |
| `ventilation_fans`, `circulation_fans`, `disabled_fans` | environment fans | **not edited** | preserved | Missing in the panel |

Result: 12 of 24 schema fields cannot be changed in the panel today; none is lost by a save. Adding them to the central editor is part of 6.3/6.6 and needs the environment and room-category vocabulary from the specification (§ environment). Light and climate options are stored in the feature configuration (`light`, `light_groups`, `climate_control`) and are covered by the Schritt-6.4/6.5 work.

### Consumers of the diagnostics count fields (Schritt 6.8 / section 11, 2026-11-20)

- `unavailable_source_count` and `unknown_source_count` are read only by `websocket.py` (`get_diagnostics`) and the Diagnose view of the panel.
- No other consumer: System Health, Repairs, sensors, the config-entry diagnostics (`diagnostics.py`) and services do not call `build_diagnostics` or `_state_data`.
- The additive source field `status` does not change `available`, `state` or `name`; the Area summary counts (`_source_coverage`) keep their values.
- The only intended change is that unknown sources are no longer part of `unavailable_source_count`.

## 14. Field semantics for the environment fields (Schritt 6.3, 2026-11-20)

Verified against the consuming code, not only against labels.

| Field (backend key) | Consumer in code | Unit and comparison | Editor label (EN / DE) | Status |
|---|---|---|---|---|
| `humidity_warning_duration` (default 15, range 0 to 1440) | `helpers/environment.py`: `humidity_duration_minutes * 60` compared with the seconds a humidity warning has lasted | minutes | Minimum duration of elevated humidity (min) / Mindestdauer erhöhter Luftfeuchtigkeit (min) | integrated; 0 is valid |
| `passive_cooling_temperature_difference` (default 2.0, range 0 to 20) | `helpers/environment.py`: passive cooling is suitable when `outdoor <= temperature - cooling_delta` | same unit as the temperature, i.e. kelvin for differences | Temperature difference for passive cooling (K) / Temperaturdifferenz für passive Kühlung (K) | integrated; no change of control logic |
| `ventilation_fans`, `circulation_fans`, `disabled_fans` | No runtime consumer in this repository. Validated as entities of domain `fan` (`repairs.py`); kept in the migration key list (`__init__.py`). Fan control (`switch/fan_control.py`) works from the computed requests, not from these lists. | not determinable | none | **not integrated (blocker)** |

### Blocker for the three fan fields

- Checked sources: `const.py` (schema and constants), `repairs.py`, `__init__.py`, `helpers/environment.py`, `switch/fan_control.py`, both translation files.
- Missing information: whether ventilation and circulation lists are used by any runtime path, and whether excluded fans are only left out of automation or are switched off. The code shows neither.
- Required decision: the owner must confirm the intended function of these lists. Until then no label is added, because the terms "ventilation fan", "circulation fan" and "excluded fan" would promise behaviour the code does not implement.
- The fields are preserved on save (test `tests/test_area_options_migration.py`).

### Entity scope rules (Schritt 6.3)

Uses the Home Assistant registries that the frontend already holds (`hass.entities`, `hass.devices`). No new registry, no new endpoint, no storage change. An entity belongs to an Area when its own `area_id` matches the Area, or when it has no own area and its device's `area_id` matches. The Area key equals the Home Assistant area ID (`available_areas` in `area_config.py`).

| Field | Scope | Domain |
|---|---|---|
| Area temperature sensor, Area humidity sensor, cool surface temperature | this Area | `sensor` |
| Relevant windows | this Area | `binary_sensor` |
| Outdoor temperature, outdoor humidity | all entities | `sensor` |

- Device class is not a filter: the configuration flow states that the device class is only an automatic suggestion; every sensor of the Area is selectable.
- A stored value outside the filter is kept selected, labelled as outside this Area (cross-area use allowed) when the entity exists, or as not found when it is missing from the states; both are saved unchanged unless the user changes the field (tests G2, G4).
- If the registry is not available, all entities of the domain are offered and the field says so.
- Entities without any area are not offered for Area-bound fields.
- Fields not yet covered: the global weather entity and the global brightness sensor (global settings, Schritt 6.2) are still offered without a domain filter.

## 15. Light and climate in the central editor (Schritte 6.4 and 6.5, 2026-11-20)

Backend keys, verified against `const.py` and `helpers/light_policy.py`:

| Area | Backend key | Editor | Rule |
|---|---|---|---|
| Light automation (`features.light`) | `turn_on_below`, `turn_off_above`, `vacancy_delay` | integrated (number, empty removes the key) | the backend accepts no other key in `light` |
| Light groups (`features.light_groups`), per group overhead, sleep, accent, task | `<g>_lights` (list), `<g>_lights_activation`, `<g>_lights_blocking_states` (list), `<g>_lights_brightness` | integrated; stored value selected; a missing value shows a neutral placeholder that is not written | brightness and activation belong to the group, not to the light automation |
| Climate control (`features.climate_control`) | `entity_id` (thermostat), `preset_clear`, `preset_occupied`, `preset_sleep`, `preset_extended`, `climate_occupancy_threshold` (positive integer, 0 valid) | integrated; empty thermostat and empty threshold remove the key | presets are free text, taken as the thermostat provides them |

Rules in the central editor: the light and climate inputs are read into the Area draft (`_lightFromForm`, `_climateFromForm`); the save uses the Area conflict model (server check before writing, explicit overwrite confirmation, re-check before a confirmed overwrite). Thermostat selection is not restricted to the Area: climate entities are offered by domain only.

Existing light and climate forms (still present until 6.8): they use the same reader and the same save path. After a conflict they no longer replace the configuration being edited; they show that the Area editor must be used. A normal repeated save writes nothing in this case.

## 16. Functional migration check (Schritte 6.6 and 6.7, 2026-11-20)

### 6.6 Further feature configuration

The feature list (`FEATURES_SCHEMA`, section 4) is a set of enable switches. Their options are either the feature's own configuration (light, climate, environment, presence) or nothing. The features light, light groups, climate control and environment are covered in sections 4, 14 and 15. The other features (aggregates, room usage, fan groups, cover groups, media player groups, area-aware media player, presence hold, BLE trackers, wasp in a box, health) have no dashboard configuration in the specification; the dashboard only switches them on and off. Nothing further is added. Their stored options are preserved (a feature that is switched on keeps its stored configuration; switching a feature off is the only change the editor makes to it).

### 6.7 Configuration completeness

| Area | Editable in the central editor | Not editable (reason) |
|---|---|---|
| Global settings | weather entity (domain `weather`), brightness sensor (domain `sensor`, device class `illuminance`, as validated by `websocket.py`) | none |
| Area general fields | type, include and exclude entities, presence release entities, reload on registry change, ignore diagnostic entities, keep-only entities, presence device platforms, presence sensor device classes | room category and the Area sensors are editable (section 14); the three fan lists are excluded by owner decision (ROADMAP) |
| Presence and timeouts | clear timeout, secondary states and their timeouts | none |
| Environment | Area temperature and humidity sensors, room category, outdoor temperature and humidity, cool surface temperature, relevant windows, passive cooling difference, humidity duration | ventilation, circulation and excluded fan lists: excluded, owner decision |
| Light automation | turn on below, turn off above, vacancy delay | none |
| Light groups (four groups) | lights, activation, blocking states, brightness | none |
| Climate control | thermostat, four presets, occupancy threshold | none |

### Save semantics (verified against the merge in `validate_area_options`)

- A feature dictionary is sent whole and replaces the stored one; keys removed in the editor stay removed (test `test_removed_optional_keys_are_not_restored_by_the_merge`).
- Keys that the editor does not send are kept by the merge (test `test_partial_save_keeps_every_field_the_panel_does_not_edit`).
- A cleared optional threshold (climate occupancy threshold) is removed and the schema default applies (10). Stored value is not restored. The editor therefore does not offer an "empty" threshold as a way to switch the rule off: the backend has no such state.
- A cleared vacancy delay (light) is removed; the backend has no default for it and the runtime uses its own behaviour.
- 0 is valid for thresholds and humidity duration (test `test_zero_thresholds_and_empty_sensor_are_explicit_values`).
- A cleared sensor is sent as an explicit empty value.
- An empty number input for the passive cooling difference keeps the stored value (it is not sent as null, which the schema rejects).

### Terminology

- The light thresholds are illuminance thresholds in lux: a light turns on when the measured value is at or below `turn_on_below` and off when it is at or above `turn_off_above` (`helpers/light_policy.py`). The labels "Einschalten bei höchstens (lx)" and "Ausschalten bei mindestens (lx)" match that logic. The term "Thermistor-Schwellen" used earlier in a status report was incorrect and does not appear in the code or in the translations.

### Entity filter rules

- Global fields: the weather field offers domain `weather`; the brightness field offers domain `sensor` with device class `illuminance` (test GL1). These are the rules the backend validates.
- Area-bound fields: entities of the Area, direct or inherited from the device (test G1). A direct area assignment takes precedence over the device: an entity with its own `area_id` is judged by that value only (`_entityArea`).
- Area-crossing fields (outdoor, thermostat): not restricted to the Area.
- Stored values outside a filter are kept and marked (test G2); a save without changing the field sends the stored value (test G4).
- No registry available: all entities of the domain are offered and the field says so.

### Open at the end of 6.7

- Negative counter-checks for the new administrative regressions: planned for the archive step; not run in this turn.
- The old light and climate forms (section 4 of the status) still exist; they are removed in 6.8 only after the counter-checks pass.
- Known gap (unchanged): no atomic compare-and-write in the backend.

## 17. Step 6.7 counter-checks and step 6.8 removal (2026-11-20)

### Counter-checks (isolated copy; the working tree was not changed)

The runs use one block per requirement. Each mutation is a single change to a copy of the production panel. The runner is fault tolerant, so a failing check is recorded as FAIL; an abort without result is not counted.

| # | Requirement | Faulty state or mutation | Expected failure | Result | Current code |
|---|---|---|---|---|---|
| M1 | Repeated save after a conflict writes nothing (old form, now R05 → M68a) | panel before the light/climate change of step 6.4 | R05b writes | R05b FAIL (7 of 8) | R05 block passes (8 of 8) |
| M2 | Stored light group activation shown as stored | `selected` removed from the activation options | L1, L2 | L1 and L2 FAIL (3 of 5) | 5 of 5 |
| M3 | Editor closes and list is shown after a successful save | re-render after save removed | N1 | N1 FAIL (1 of 2) | 2 of 2 |
| M4 | Old light and climate forms check the server before writing | server check removed from the old save path | R05a, R05b, R05g | 5 of 8; the three named checks FAIL | obsolete: the old path is removed in 6.8; the requirement is covered by M68a–d and L3/L4, K4/K5 |
| M5 | A direct Area assignment beats the inherited device Area | device Area checked first | PR1 | PR1 FAIL (1 of 2) | 2 of 2 |
| M6 | Cleared thermostat is removed | thermostat kept on empty input | K2 | K2 FAIL (5 of 6) | 6 of 6 |
| M7 | Central editor checks the server before writing | central server check disabled | L3 | L3 FAIL (4 of 5) | 5 of 5 |

Baseline runs of the same blocks against the current code: R05 8/8, L 5/5, K 6/6, N 2/2, PR 2/2, GL 2/2 (before 6.8; the R05 block was then replaced by AV and M68 checks, which pass, see below).

### Migration of the R05 requirements to the central editor

| Former check | Requirement | Now covered by |
|---|---|---|
| R05a | server change blocks the light write, input kept | L3 |
| R05b | normal repeated save after a conflict writes nothing | M68a |
| R05c | late response after a role change restores nothing | B02c (general guard) |
| R05d | validation error keeps the input and shows the message | M68b |
| R05e | climate submits write exactly once | M68c |
| R05f | invalid climate threshold keeps the input and shows the message | M68d (valid value sent; the browser blocks negative values through `min="0"` before submit) |
| R05g | server change blocks the climate write | K4, overwrite K5 |

### Step 6.8 removal

- Removed: the editable light form and the editable climate form in the analysis views, `_saveLightConfiguration`, `_saveClimateConfiguration`, `_saveFeatures`, `_patchFormError`, the light automation form helper, the climate submit listener and the submit binding for the light form.
- Analysis views now show the stored values read-only (light: thresholds, vacancy delay, group settings, runtime status; climate: thermostat, presets, occupancy threshold, runtime status). Each view has a button `data-config-area` that opens the central Area editor for that Area. Opening the light analysis loads its runtime status.
- Verified by checks AV1–AV6: no form and no input in the analysis views, no write when the views are visited, navigation to the editor opens the light and climate sections, the migrated values are editable there.
- Single write path: the central Area editor (`update_area` through `_save`) is the only administrative write path for light and climate values. Conflict handling is the central one (server check before write, explicit overwrite confirmation, check again before a confirmed overwrite).
- Not removed: the generic light and climate reader functions (`_lightFromForm`, `_climateFromForm`) and the group field renderer, because the central editor uses them.

### Open after step 6

- Step 6.8 is complete for the analysis views. The general cleanup of remaining frontend parts belongs to step 7.
- The non-atomic gap between server check and write remains documented; no atomic backend interface was added.
- The three fan lists stay excluded (owner decision, ROADMAP).
- The review archive `adaptive-areas-step6-review.zip` with screenshots of the production interface is not yet created.
