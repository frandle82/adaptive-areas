# Current state

## Stable facts

- Integration version: read `custom_components/adaptive_areas/manifest.json`; do not copy it here.
- Test baseline: the full suite passes with Home Assistant 2026.8.1 and with the CI-pinned Home Assistant 2026.10.4 (see [TESTING.md](TESTING.md)).

## Implementation direction

The Dashboard 2.0 panel covers area configuration, light control (runtime status, light groups; policy-only control was removed in Phase 2, see below) and climate control (feature toggle, climate configuration, runtime status). The panel has read endpoints and administrator-gated configuration mutation endpoints.

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

## Praxisabnahme 1.6.19-rc.15 (2026-11-22)

- Benutzer-Praxistests (acht Szenarien, bestanden): Präsenzquellenerkennung und Bereichsstatus frei/belegt für die geprüften Szenarien, Fensterkontakt-Ausschluss, Entity-Picker, Formularlayout, Speichern und Neuladen. Das ist Benutzerfeedback, keine automatisierten Testergebnisse, und gilt nicht pauschal für alle Geräte oder Home-Assistant-Versionen.
- Automatisierte Prüfungen des veröffentlichten Stands: Python 709 bestanden, Browser 354 bestanden, Home Assistant stable erfolgreich.
- Beta-Prüfung: BLOCKED – TEST INFRASTRUCTURE INCOMPATIBILITY, nicht bestanden. Details in `docs/TESTING.md`.
- Offen: echter 200-%-Browserzoom, Screenreader, weitere Sensortypen, weitere Home-Assistant-Versionen.

## Prozent-Hysterese (Entscheidung 2026-11-22)

- Entscheidung DECIDED / CLOSED: Lichtschwelle T in lx, Hysterese H in Prozent (0 bis 200). Speicherung unverändert über `turn_on_below` und `turn_off_above`. Ersetzt die frühere absolute Festlegung in lx.
- Finalisiert (lokal, 2026-11-22, noch nicht committet): gültige Paare immer als Prozent; Legacy nur für ungültige Paare; exakte Werte bei unveränderten Feldern; Gleichheitssemantik an der Schwelle dokumentiert; ungenutzte Übersetzungsschlüssel entfernt. Prüfungen: Python 717 bestanden, Browser 367/367 bestanden.
- Vorher (überholt): Panel-Eingabe in Prozent mit Vorschau, Backend akzeptiert gleiche Grenzen (H = 0), Legacy-Anzeige für Paare, die eine Nachkommastelle nicht reproduziert. Prüfungen: Python 709 bestanden, Browser 364/364 bestanden.
- Für die Prozentdefinition gilt: jedes Paar mit T > 0 ist exakt als T und H darstellbar. Legacy-Anzeige greift deshalb nur bei Rundungsabweichung der Einnachkommastellen-Anzeige, nicht bei einer strengen Asymmetrie.

## Helligkeitsdiagnose (lokal, 2026-11-22, nicht committet)

- Drei getrennte Helligkeitsmechanismen: (1) Bereichsstatus hell/dunkel über `secondary_states.dark_entity`; ohne Entität gilt der Standard „dunkel“. (2) Automatischer Schwellensensor mit eigener Aggregationsschwelle und Hysterese. (3) Lichtautomatik mit globalem Helligkeitssensor und `turn_on_below` / `turn_off_above`. Die Mechanismen sind nicht verbunden.
- Korrigiert: Die Konsistenzprüfung in `dashboard.py` las `dark_entity` auf oberster Ebene und konnte nie auslösen. Jetzt derselbe Pfad wie die Bereichslogik (`secondary_states`).
- Diagnose im Dashboard: Bereichsdetail zeigt den Grund des Bereichsstatus (konfigurierte Entität, Standardannahme, Entität nicht gefunden, nicht verfügbar). Lichtdiagnose zeigt Präsenz, Helligkeitsquelle, Grenzen, den Übersteuerungszustand je Gruppe und die Gruppen des Steuerpfads mit Aktivierung und aufgelösten Mitgliedern.
- Schaltlogik, Präsenzlogik, Dedupe- und Übersteuerungsregeln sind unverändert.
- Die ursprünglichen Praxisprobleme (Bereich bleibt dunkel; Licht schaltet bei hell→dunkel nicht ein) sind **ungeklärt**. Ohne reale Diagnosedaten (siehe Konzept) ist die Ursache nicht bestätigt.
- Prüfungen: Python 738 bestanden; Browser 378/378 bestanden.

## Lichtsteuerung und eindeutige Gruppenzuordnung (Commit 76bd329, Release 1.7.0-rc.1 vorbereitet, 2026-11-24)

Commit `76bd329` enthält die Änderungen. Der Pre-Release `1.7.0-rc.1` ist vorbereitet (siehe CHANGELOG). Nicht in einer Home-Assistant-Instanz geprüft.

**Regeln**

- Eine physische Lampe gehört höchstens einer individuellen Lichtgruppe an (Deckenleuchten, Schlaflichter, Akzentlichter, Arbeitslichter).
- Eindeutig innerhalb einer Area und zwischen Areas, auch im GlobalEntry.
- Verschachtelte HA-Lichtgruppen werden zu ihren physischen Mitgliedern aufgelöst.
- Die ALL-Gruppe ist ausgenommen, sperrt nichts und schaltet nie automatisch EIN (nur CLEAR-AUS).
- Betroffene Gruppen werden bei einem Konflikt als Ganzes von automatischen Aktionen ausgenommen.

**Dashboard**

- Bereits einer anderen individuellen Gruppe zugeordnete Lampen sind nicht wählbar und nennen Gruppe und ggf. Area des Besitzers.
- Noch nicht gespeicherte Änderungen zählen sofort. Abbrechen ändert nichts.

**Serverseitige Validierung (verbindlich)**

- Options-Flow und Dashboard-Speichern (`adaptive_areas/update_area`) nutzen dieselbe Prüfung `light_group_ownership_problem` (`helpers/light_ownership_runtime.py`).
- Die Prüfung läuft nur, wenn Lichtgruppen gespeichert werden. Unbezogene Änderungen scheitern nicht an einer inzwischen unbekannten Lampe.
- Eine abgelehnte Speicherung lässt die bisherige gültige Konfiguration unverändert.
- Fehlerschlüssel sind je Besitzer-Gruppe (`light_ownership_conflict_overhead|sleep|accent|task`), zusätzlich `light_entity_unknown` und `light_group_unresolved`. Die Texte stehen in `strings.json`, `translations/{en,de}.json` (Options-Flow) und `dashboard_texts/{en,de}.json` (Panel) und nennen Lampe und Area über Platzhalter. Gruppennamen sind lokalisiert (Deutsch: Deckenleuchten, Schlaflichter, Akzentlichter, Arbeitslichter).
- Korrigiert in dieser Runde: Die Prüfung las GlobalEntry-Areas nicht (`light_group_configs_of_entry` übersprang den GlobalEntry). Dadurch wären Konflikte zwischen gespeicherten Areas weder beim Speichern noch zur Laufzeit gesehen worden.
- Ungültige Bestandskonfigurationen werden nicht automatisch umgeschrieben. Die Laufzeit blockiert betroffene Gruppen und meldet die Diagnose.

**Lichtsteuerung (Architektur)**

- Einheitlicher automatischer Gruppen-Entscheidungsweg: `transition_decision` bzw. `initial_decision` (`helpers/light_transition.py`) → Dispatch → `_async_group_command` → Ausführung.
- Policy-only-Pfad entfernt (Variante B, Phase 2): nur konfigurierte individuelle Lichtgruppen werden automatisch gesteuert. Ungruppierte Lampen werden nicht automatisch geschaltet.
- Eigenerkennung über Kontext ist Area-weit (`_light_group_own_contexts`), weil die ALL-Weiterleitung Untergruppen verändert.
- Keine Shadow-Simulation. Keine zusätzlichen Timer. Keine Retries (ein fehlgeschlagener Versuch wird für unveränderte Basis nicht wiederholt). Keine Deferred-Queue. Keine periodische Reconciliation. Keine Golden-Referenz.

**Prüfungen (lokal, 2026-11-24)**

- Python: 957 Tests bestanden, 0 fehlgeschlagen, 0 xfail, 0 Sammlungsfehler, keine Ausschlüsse.
- Browser-Harness `tests/frontend/run.mjs`: 387/387 bestanden, Exit 0.
- Ruff, Black und `git diff --check` ohne Befund. Frontend-Syntaxprüfung (`node --check`) bestanden.

**Offen**

- Reale Home-Assistant-Prüfung (Oberfläche, Fehlertexte im Options-Flow, Reload) ist nicht durchgeführt. Der Browser-Harness prüft das Panel gegen Fixtures, nicht gegen eine laufende Instanz.
- Die Darstellung der Platzhalter im Home-Assistant-Options-Flow ist nicht in einer Instanz verifiziert.
- Das Panel übersetzt Fehlercodes über `_errorText`; diese Übersetzung ist nicht im Browser-Harness abgedeckt.
- Konfigurationen mit Doppelzuordnung aus früheren Ständen werden nicht bereinigt; sie werden nur als Laufzeit-Diagnose gemeldet.
- Graphify-Graph ist aktualisiert (Working Tree, nur Code). Dokumentation und Bilder sind nicht semantisch erfasst.

## Light control and correction block (release candidate 1.7.0-rc.1, working tree)

- Native group path: the Area decides when a configured light group switches (ON, OFF, NO_ACTION). Each automatic decision sends at most one service call to the group entity; Home Assistant forwards it to the lamps. The 1.6.18 time-based grace period is not restored; own calls are recognised by request context (`light_origin`).
- Explicit group membership (B01): a configured, existing light is a group member even when the HA-Area lookup does not find it (`_configured_group_lights` in `light.py`). An explicit exclusion (`exclude_entities`) still wins. Ownership is exclusive across Areas.
- Exclusive ownership is Area-wide (B01): a lamp that an active automatic group of any Area owns is controlled only by that group (`light_ownership_runtime.py`).
- Manual override (B02): a change caused by the Area's own automation (group call, registered in `light_origin`) is not manual. A real user action still sets the override (`test_light_manual_override_origin.py`).
- Light diagnosis (D07): the runtime status has a `control_path` block (group entities with activation, configured and resolved members, ownership block). The panel shows it. Ungrouped lamps are not listed as a control path.
- Area brightness sensor (D01): the Area property `area_illuminance_sensor` (numeric lux sensor, device class illuminance or unit lx, domain sensor) is the first source of the Area brightness and of the Light decision. Priority: the Area sensor, then the global light sensor, then UNKNOWN. A configured but unavailable Area sensor is UNKNOWN and never falls back to the global sensor. The Dark state is derived from the numeric value and the Light limits (`helpers/brightness.py`). The binary secondary entity `dark_entity` is no longer a source: it is accepted and ignored, never converted to a lux sensor. Schema: one optional additive key; no schema version change, no migration. Validation on save refuses binary and non-illuminance entities.
- Area form (D02, D03): the room-climate (`environment`) and climate-control sections are rendered always and shown or hidden from the local draft at once. No automatic save. Entries are kept in the DOM while a section is hidden.
- Defaults (D04 to D06): presence domains `binary_sensor` and `media_player`; device classes `motion` and `occupancy` (the former default also included `presence`); release time 1 minute (stored in minutes).
- Known open items: the device-class selector does not yet use the same component as the domain selector and has no shared error message below both (D05 UI). A feature that is disabled and then saved loses its stored configuration, as before; keeping it needs a storage decision (D02). Nested HA light groups and ownership conflicts between Areas are covered by existing tests but not by new ones. The Area brightness sensor is not in the Options Flow (the dashboard edits it); the Options Flow secondary-states step no longer offers the dark entity.
- Verification (earlier state): backend 980 passed, coverage 91 % (8701 statements); browser harness 411/411; ruff, black, `git diff --check` and pre-commit passed.
- Policy-only: removed in Phase 2 (Variante B). No automatic default group exists. Ungrouped lamps are never switched automatically; manual operation is unchanged.

## Final state of the correction block (1.7.0-rc.1, working tree, not committed)

- D01 (final): the Area property `area_illuminance_sensor` is the only configuration of the Area brightness sensor. Dashboard, Options Flow and the save validation use the same check (`area_config.illuminance_sensor_error`): domain sensor, device class illuminance or unit lx; binary entities are refused; only a changed value is checked, so a stored sensor that is temporarily unavailable never blocks other saves. Repairs use the category `area_illuminance`; the ignored legacy `dark_entity` is never reported. The Dark state and the Light decision read the same source. Without a configured Area sensor the global light sensor is used; without any sensor the state is UNKNOWN.
- Brightness limits (2.4): the Dark and Bright classification uses the Light limits also while the Light feature is disabled: the enabled configuration, otherwise the parked one (D02). A missing limit configuration stays UNKNOWN. This is a decision to review: the limits are an Area brightness input, not light control.
- D02 (storage decision, approved): `retained_features` holds the configuration of disabled features. Disabling moves the configuration there; enabling again with an empty configuration restores it; a submitted configuration replaces it. Enabled features stay in `features` and runtime consumers are unchanged. Additive key, no schema version change, no migration. Tests: `test_area_retained_features.py`.
- D05: the device-class selector uses the same checkbox dropdown as the presence domains, with its own choices (motion, occupancy, presence, moving). One shared hint sits below both dropdowns. Defaults: domains binary_sensor and media_player; device classes motion and occupancy.
- B01: a nested native light group that would switch an excluded lamp is not controlled as a whole and is refused at save (`excluded_members_by_group`). Tests: `test_light_nested_groups.py`. Cross-Area ALL: the ALL group of an Area never contains a lamp that another Area's group owns, also through a full occupation and CLEAR cycle (`test_light_cross_area_policy.py`).
- B02: the origin of an automatic call is its registration in the request registry; a user context is never registered. A user switching the member lamp is a manual override; the ALL group's automatic OFF at CLEAR is not (`test_light_manual_override_origin.py`).
- Verification: backend 996 passed (last full run, before the final frontend run), coverage 91 % (8787 statements). Ruff, Black, `git diff --check` and pre-commit passed. The browser harness last passed 416/416 after the D05 change. A later attempt to re-run it hung in the local headless Chrome and could not be completed in this session; a re-run is required before commit.
- Open: the Options Flow does not offer the D02 retained configuration of disabled features in a separate view; the dashboard is the editor. The D02 browser persistence check (save, reopen, reload) is not yet in the harness; the backend checks cover it.
- Policy-only: removed in Phase 2 (Variante B). Open architecture point: the context simplification (Phase 3).

- Brightness classification (final decision): see `docs/DECISIONS.md`, section "Brightness classification (final)". No default limits exist; without configured limits the state is UNKNOWN.
