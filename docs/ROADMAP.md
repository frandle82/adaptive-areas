# Roadmap

Only approved work is listed here. Add an item only after it has an owner, scope, acceptance criteria, compatibility impact, and intended verification. Link accepted architecture choices from [DECISIONS.md](DECISIONS.md).

## Dashboard 2.0 – Phase E: Ist-/Soll-Abgleich und Korrekturen

Status: approved and functionally complete on `main`. Pending: visual review in a real Home Assistant instance (not done).

Owner: maintainer (Andreas Grundke).

Reference: the Dashboard 2.0 target design is the binding specification for panel behaviour. Backend fields, WebSocket endpoints and runtime semantics come from the code, not from the UI.

### Scope

| ID | Item | Priority |
| --- | --- | --- |
| F1 | Restore the global Settings renderer (weather entity, global brightness sensor). The renderer was lost in commit `50062ae`. | Critical |
| F1b | Restore the Area editor and light-group helpers that were lost in the same commit. Area saves must not overwrite Light, Light-group or Climate configuration. | Critical |
| F2 | Show friendly names for the thermostat selection; keep the entity id as fallback and keep unavailable stored ids. | High |
| M1/M2 | Overview per Area: occupancy, configured light and climate activation, sleep and extended state. Only backend values; no runtime status in the overview. | High |
| U2 | Remove hard-coded visible texts from the panel and route them through the existing translation object. | Medium |
| M3 | Empty states for light and climate control point to Areas → Features. | Medium |

### Acceptance criteria

- Settings tab renders, loads and saves global options through the existing WebSocket commands; other global options are preserved; admin permissions are unchanged.
- Panel regression tests: every `this._method(` call in the panel has a definition; settings renderer and save path exist; thermostat friendly names; area save keeps light, light-group and climate configuration.
- No raw backend keys or enums in visible text; no `undefined` in visible text in German or English.
- Empty states and dynamic tab visibility keep working; fallback to Overview when a dynamic tab disappears.
- Global options: an unchanged, unavailable stored entity id does not block saving the other field (regression test with red-to-green evidence).
- Save round trips through the real WebSocket handlers keep light, light-group, climate and presence configuration, other Areas and other global options.
- Full test suites pass on Home Assistant 2026.10.4 and 2026.8.1; pre-commit and `git diff --check` pass.
- Browser review covers all tabs, desktop/tablet/mobile widths, light and dark scheme, admin and non-admin users, friendly and stale entity ids, and saving without loss of other configuration.

### Non-goals

- New tabs or new light or climate features.
- Backend changes beyond what the existing endpoints already provide.
- Dirty-state or confirmation infrastructure for unsaved form values.
- Full frontend refactoring.
- Migration of the panel translation mechanism (see open decision below).

### Decisions

- Light, Climate and Settings tabs stay administrator-only. Permissions are not relaxed.
- The panel keeps its English/German dictionary. A migration to Home Assistant translations is out of scope.
- The overview shows configured activation ("Aktiviert"), not runtime status. Runtime status needs one read per Area and is not added to the overview.
- Save rule for global options (binding): unchanged stored entity ids are accepted even when unavailable. New or changed ids are fully validated. Explicit `null` removes a field. Unsent fields are kept. A rejected update persists nothing.

### Open decisions

- Non-administrators see no Light or Climate tab. The target design does not state an admin rule; this follows the current permission model.

### Compatibility

No storage, entity id or config entry changes. No backend migration.
