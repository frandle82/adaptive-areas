# Current state

## Stable facts

- Integration version: read `custom_components/adaptive_areas/manifest.json`; do not copy it here.
- Test baseline: the full suite passes with Home Assistant 2026.8.1 and with the CI-pinned Home Assistant 2026.10.4 (see [TESTING.md](TESTING.md)).

## Implementation direction

The Dashboard 2.0 panel covers area configuration, light control (policy and runtime status, light groups) and climate control (feature toggle, climate configuration, runtime status). The panel has read endpoints and administrator-gated configuration mutation endpoints.

Dashboard 2.0 Phase E (see [ROADMAP.md](ROADMAP.md)) is implemented in the panel:

- Settings tab renders and saves the two global options (weather entity, global brightness sensor) through the existing WebSocket commands.
- The Area editor and light-group helpers are restored; saving an Area keeps light, light-group and climate configuration.
- The overview shows occupancy, configured light and climate activation, and sleep and extended state, from backend values only.
- Thermostat selection shows friendly names with the entity id as fallback.
- Visible panel texts use the existing English/German panel dictionary.
- Save rule for global options: unchanged stored entity ids are accepted even when unavailable; new or changed ids are fully validated; explicit `null` removes a field; unsent fields are kept; a rejected update persists nothing.
- Light and Climate tabs and the Settings tab are administrator-only, as before.

## Dashboard redesign status

- Approved specification: [specifications/dashboard.md](specifications/dashboard.md). Approval Gates 1 and 2 are granted; Approval Gate 3 is closed.
- Step 3 is **technically accepted** (independent check of review archive v3, 2026-11-20; findings B01–B11 and R01–R05 closed, see [HANDOVER.md](HANDOVER.md)). Step 4 (monitoring) is in progress: 4.1 (overview) is implemented.
- Implemented (step 4.1, overview): KPI row over physical Areas only (physical Areas, occupied, notices, technical issues); meta Areas in a separate row and not counted; unknown values named separately; notices from the central warning model, so disabled features add none; filter chips and KPI toggles with `aria-pressed`; name search that keeps focus; data timestamp and a banner when the connection is lost or a reload failed; the occupied KPI shows the last known value while data is outdated. Keyed patching keeps existing DOM nodes. Floor grouping is not implemented: the overview DTO has no floor or meta membership, and the specification allows no new DTO fields.
- Implemented (steps 4.3 and 4.4): floor grouping of the overview from the additive DTO fields `floor_id` and `floor_name`; Meta-Area cards with member counts from `members`; cleaning and room usage views (feature `room_usage`) using the existing assessment values; missing values are shown as missing, never as zero. Step 5 (analysis) is implemented except the open points listed in [HANDOVER.md](HANDOVER.md); the decision trace view is complete (5.3). Diagnostics report source status (`status`), unknown sources separately (`unknown_source_count`) and data completeness (`data_complete`); the unavailable count no longer includes unknown sources (5.4). Earlier note on step 5: lighting and climate runtime texts are translated and state-aware (5.1, 5.2), the diagnostics warning count no longer counts source problems twice (5.4 partly). The decision trace (5.3) is unchanged. Step 6 (administration) has not started; steps 7 and Phase 6 are open; the continuation point is in [HANDOVER.md](HANDOVER.md).
- Implemented (light and presence follow-up): explicit `include_entities` for presence now accepts entities without a registry entry and bypasses the `binary_sensor` device-class filter; `exclude_entities` still wins; unknown and unavailable states are never active (`helpers/sources.py`; tests `test_presence_selection_regression.py`). The global light sensor accepts `illuminance` device class or the exact unit `lx` in backend and panel alike (`websocket.py`; tests GL2a–GL2c, `test_light_lux_regression.py`). Light thresholds are edited as threshold and hysteresis in the Area editor and stored unchanged as `turn_on_below`/`turn_off_above` (see `docs/specifications/dashboard-migration-matrix.md`, section Terminology). Light groups are nested native `<details>` with item counts and keyboard tests (LG1–LG5). Entity option titles show the full entity ID.
- Presence diagnostics (2026-11-22, release candidate 1.6.19-rc.14): native Home Assistant diagnostics of an Area include `presence.evaluation` (configured domains, device-class filter, manual include and exclude counts, per source domain, device class, status, origin, evaluated and raw signal; presence control gate; raw signal versus confirmed occupancy; dashboard state; reason code). Entity IDs are not exported. Presence logic unchanged. Gate semantics DECIDED / CLOSED (see [DECISIONS.md](DECISIONS.md)): a closed gate does not confirm occupancy; `clear` stays possible. Root cause of the status error on the test instance: UNRESOLVED until the diagnostics of the affected Area are read. Tests: `tests/test_presence_evaluation_diagnostics.py`, `tests/test_presence_gate_semantics.py`, `tests/test_dashboard_explicit_presence_sources.py`.
- Area management (2026-11-22, release candidate 1.6.19-rc.13): entity lists (include, exclude, presence release, keep-only) are collapsed by default and show their selection count; presence domains are checkboxes in a dropdown offering exactly `binary_sensor`, `device_tracker`, `media_player`, `remote`. Stored values outside these four stay visible, flagged and are never removed silently. The backend rejects a domain only when a save would newly add it; stored values are kept, explicit removal is allowed and a removed value cannot be re-added without a new save decision (`area_config.py`; tests in `tests/test_presence_domain_selection.py`). An empty domain choice is accepted; the editor warns only when the saved Area has no effective presence source (overview `presence.total` is 0). Lux fields are compact numeric inputs (at most 9 rem wide, tests BR11).
- Verification status (2026-11-22): Python suite 660 passed; browser harness 333/333 passed (headless Chrome, simulated `hass`). Ruff 0.16.2 and Black 26.5.1 passed (run in the isolated `.tox/lint` environment). JSON validation and `git diff --check` passed. The project pre-commit hooks were not run (they need network access to install). Not verified: a real Home Assistant instance (open items below), the 200 % browser zoom (approximated by halved viewport widths), and open multi-select dropdowns (not reachable in headless Chrome).
- Open for real-instance testing: the user's own lux sensor (entity ID and attributes needed), long entity IDs in native multi-select lists (their text is truncated by the browser; the full ID is in the tooltip), and light group behaviour with real lights.
- Implemented (step 5, partly): translated lighting and climate runtime status; swapped EN and DE labels for the lighting status corrected; Meta-Area DTO carries `members_total` so partial Meta-Areas are named; diagnostics warning count excludes unavailable-source entries.
- Fixed (privacy, backend): the environment summary carried the generated entity's fields and `used_sensors` (entity IDs) to non-administrators. Non-administrators now receive the values only; administrators are unchanged.
- Implemented (Phase 5, backend): role-aware DTOs. Non-administrators receive aggregated source and presence counts and no control entries in overview, area detail and update events. Administrators keep the full detail.
- Implemented (Phase 5, backend): `adaptive_areas/get_decision_trace` (administrator-only, `area_id` required, `limit` 1 to 20) with a field and value allowlist. Unknown values become `other`; invalid timestamps and exception names become `null`.
- Implemented (Phase 5, trace only): presence transitions record the source reason already computed for `last_reason`. The public `last_reason` attribute is unchanged.
- Implemented (Phase 5, step 2, frontend shell): header with status pill and brand mark, navigation grouped into Monitoring, Analysis and Administration, group visibility by role and by enabled analysis features, German and English labels, no horizontal overflow at 320 px. Configuration forms are unchanged.
- Implemented (step 3, corrected after review): lifecycle with session guard; subscription updates keep working after reconnects (B01); connection listeners; targeted dashboard updates by Area; decision trace and diagnostics views (read-only, administrator only); analysis group visibility by availability.
- State model: panel state lives in the sub-states `_link`, `_data`, `_ui`, `_drafts`, `_requests`, `_errors` (B09). Asynchronous operations use one guard mechanism (`_guard`, `_isCurrent`, `_begin`, `_end`): a response is applied only while session, role and the operation's own condition (edited Area, selected light, climate or trace Area) are unchanged, and only the newest request clears its loading flag (B02). Results, errors and final renders are taken only from the request that currently owns the operation (`_live`), also for two requests for the same Area (R03). The guard covers the global settings load (R02), the trace and diagnostics loads, `_refresh`, Area save and delete, and the light and climate configuration saves.
- Subscriptions: each panel subscription has its own generation, independent of the session number; callbacks of a replaced, closed or role-changed subscription, including the data-free `areas_changed` event, process nothing. The backend reads the role for every pushed event, because Home Assistant updates `connection.user` in place when groups change and keeps the connection open (R01).
- Writes: the Area form has one save at a time (`_drafts.area.saving`); repeated submits send one write; delete has a lock, the guard and a translated error (R04). Light and climate configuration saves read the current server state of the Area's features before writing; on a difference they write nothing, keep the input and report the conflict, and a second save applies the input to the current server state; they have a save lock and keep the input on errors (R05). The climate save failed with a `TypeError` since Phase E (the submit handler passed the panel instead of the form); this is fixed.
- Area editor: a real draft (`_drafts.area.draft`); the form is rendered from it and input is captured into it, so the draft survives validation errors, save errors, re-renders and structural updates. `_ui.editing` holds only the identity of the edited Area (B04).
- Conflicts: every regular write of global settings or an Area first reads the current server state and writes only if it equals the draft's origin; an overwrite confirmation applies only to the conflict that was shown (B05). Remaining limit: there is still no atomic compare-and-write in the backend, so a change between this check and the write is not detected.
- Role change to non-administrator discards all administrative data, including the Area draft, conflicts, selections and request ownership (B03).
- Warnings: missing or invalid warning data is shown as unknown, never as "No notices"; offline or failed reloads mark cards as possibly outdated (B06/B07). Unavailable sources are derived from the backend fields `sources.available` and `sources.total`.
- Feature availability (`_featureState`): area-off, no-data, data, data-unknown, and unknown when `enabled_features` is missing; missing `active_states` or `occupied` are shown as unknown (B08). The backend has no global feature state; none is derived.
- Area set changes: the integration sends an internal dispatcher signal after an entry is set up or unloaded; `subscribe_updates` then rebuilds its entity index and pushes a data-free `{"areas_changed": true}` event; the panel reloads overview (and configuration for administrators). An entity shared by several Areas updates each of them (B10).
- Still open: step 4 (monitoring), step 5 (analysis views), step 6 (administration migration), step 7 (cleanup). Translations still use the EN/DE object in the panel.
- Browser harness: `node tests/frontend/run.mjs` runs 213 checks against the shipped panel (all pass). It sets the harness markup directly instead of navigating to a `file://` URL.
- Non-admin consumer review: [specifications/dashboard-nonadmin-review.md](specifications/dashboard-nonadmin-review.md).
- Verified: 594 tests pass with Home Assistant 2026.10.4 (2026-11-20, working tree including the changes above); check-only lint (ruff, black, JSON validation, `git diff --check`) is clean.
- Not verified: the beta suite (local environment outdated), `pre-commit` itself (its hooks modify files), a browser run under Chromium (only Chrome is available locally), a browser or visual review in a real Home Assistant instance.

## Known risks

- Home Assistant 2026.11.x has no matching test harness release. Without a compatible harness, pip falls back to an outdated harness, and test collection fails. CI therefore pins 2026.10.4 until a harness supports 2026.11.x.
- Browser review was run only against a local harness that loads the real panel script with mocked WebSocket responses. It is not a visual review in a real Home Assistant instance; that review is still pending. The harness does not run backend validation.
- Unsaved climate drafts are discarded when the selected area changes (accepted).

## Known documentation discrepancy

The README describes the dashboard as read-only, but the current WebSocket API includes administrator-gated updates for global and area configuration plus area creation and deletion. This document records the discrepancy; it does not change user-facing documentation or runtime behavior.

## Unverified items

A failing Hassfest validation run on an unrecognised commit SHA (`d3ee6a4`, not present locally) has not been analysed. No deployed Home Assistant instance was inspected.

## Anwesenheitsquellen (Teilkorrektur, 2026-11-22)

- Automatische Quellenerkennung: Geräteklassen-Default für fehlende Konfiguration, Ausschluss vor Einschluss (`helpers/sources.py`). Tests: `tests/test_presence_source_detection.py`.
- „Entitäten in die Analyse einschließen“ ist optional; die automatische Erkennung arbeitet unabhängig davon.
- Warnung der Bereichsbearbeitung: neutraler Hinweis bei ungespeicherten Domänenänderungen, definitive Warnung nur bei gespeichertem Stand ohne wirksame Quelle.
- Noch offen: Zustandsmodell für `remote` und `media_player` (`on` ist unscharf), Entitätsauswahl-Vereinheitlichung, Formularlayout, reale HA-Prüfung. Details: `docs/HANDOVER.md`.

## Bereichseinstellungen: Entitätsauswahl und Abschnitte (2026-11-22)

- Gemeinsame Komponente `aa-entity-picker` für Einzel- und Mehrfachauswahl der Bereichseinstellungen (Einschluss, Ausschluss, Anwesenheits-Kontrolle, Behalten, Dunkelheit, Akzent, Schlaf). Details: `docs/HANDOVER.md`.
- Noch native Auswahl: Umgebungsfelder, `relevant_windows` und die globalen Quellen.
- Tests: 350/350 Browser-Checks, 701 Python-Tests. Echter 200-%-Zoom und reale HA-Oberfläche sind nicht geprüft.

## Entity-Picker: Ladeweg und Vereinheitlichung (2026-11-22)

- Ladeweg: Lader `adaptive-areas-loader.js` (Panel-Modul), nur im Adaptive-Areas-Panel. Keine globale Einbindung. Details: `docs/HANDOVER.md`.
- Alle Entitätsauswahlen außer Bereichs-, Aufzählungs- und Zeichenkettenfeldern nutzen `<aa-entity-picker>`.
- Tests: Browser 354/354, Python 707 bestanden. Echter 200-%-Zoom, Screenreader und reale HA-Oberfläche sind nicht geprüft.
