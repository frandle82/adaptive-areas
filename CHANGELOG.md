# Changelog

## 1.6.19-rc.12 - 2026-11-21

### Added

- Dashboard 2.0 Intelligence Center: the overview groups areas by floor, shows presence as occupied, not occupied or unknown, and marks technical issues, notices and unknown data separately. Meta-areas are aggregated and not counted in the physical figures.
- Native Home Assistant translations: all dashboard texts (English and German) are loaded through `frontend/get_translations` from `translations/en.json` and `translations/de.json`, with English as the fallback.
- Collapsible navigation on narrow containers, with keyboard and touch support.
- Central area editor with progressive disclosure: basic, function and advanced settings are grouped; validation errors open the section that contains the field.
- Decision trace and diagnostics with a clearer structure: each entry shows its decision, outcome and reason; diagnostics group technical issues, data availability and details.
- Backend diagnostics and overview data: explicit `presence.state` (`unknown` when no source is available), physical presence counts, floor metadata and Meta-area membership. Existing fields keep their meaning.

### Changed

- The area editor warns before a view switch or another area discards unsaved changes; a cancelled switch keeps the draft.
- Empty feature entries (a feature enabled without settings) count as changes of the editor draft.
- Language changes re-render the dashboard without losing an open draft, focus or section state.
- Area cards, trace entries and diagnostics wrap long values on small screens.

### Fixed

- Unsaved area changes were lost silently when the view was switched.
- A feature enabled without settings was not detected as a change.
- Areas without an available presence source were shown as not occupied; they are now shown as unknown.
- Environment values without notices were hidden on the dashboard.
- Area cards overflowed their track by a few pixels at 320 px width.
- Two text colours on the light theme did not reach the WCAG 2.2 AA contrast ratio of 4.5:1.

### Validation

- 635 Python tests passed (pytest-homeassistant-custom-component, Home Assistant 2026.10.4 test framework).
- 294 browser harness checks passed (Chromium with a simulated Home Assistant `hass` object and backend-generated fixtures).
- Repository pre-commit hooks passed.

### Known limitations

- Not yet run in a real Home Assistant installation: panel registration, the translation request in a live instance, language switching, WebSocket reconnect, real theme contrast and browser zoom at 200 %.
- Home Assistant 2026.8.0 compatibility is not verified at runtime.
- The three persisted fan lists stay excluded from the dashboard.
- Pre-release for testing and feedback.

## 1.6.19-rc.11 - 2026-11-19

### Added

- Dashboard 2.0: the area overview shows occupancy, configured light and climate activation, and sleep and extended state, using backend values only.
- Dashboard 2.0: light and climate runtime status, with dedicated light (policy and light groups) and climate configuration tabs. These tabs are administrator-only.

### Changed

- Dashboard 2.0: the thermostat selection shows friendly names; the entity id stays as fallback.
- Dashboard 2.0: visible panel texts are localized in English and German; empty states for light and climate control point to Areas → Features.
- Coalesce meta-area source refreshes to reduce repeated work.

### Fixed

- Dashboard 2.0: the global settings tab and the area editor were missing after an unreleased Dashboard 2.0 change. Both are restored.
- Saving an Area keeps its light, light group and climate configuration.
- Global settings: an unchanged, currently unavailable entity reference no longer blocks saving the other setting. Explicit removal still works.
- Avoid missing-name errors in config entry and registry listener logging.
- Refresh and remove meta-area sources after child entity registration and removal.
- Handle delayed area assignment during migration verification.
- Update device registry usage for Home Assistant 2026.10.
- Declare the `http` dependency for hassfest validation.

### Validation

- 563 tests passed against Home Assistant 2026.10.4.
- 562 tests passed and 1 skipped against Home Assistant 2026.8.1.
- Repository pre-commit hooks passed.

### Known limitations

- Visual acceptance in a real Home Assistant installation is pending.
- Dashboard localization currently supports English and German.
- Configuration tabs require administrator privileges.
- Pre-release for testing and feedback.

## 1.6.19-rc.6 - 2026-11-15

### Changed

- Redesign the Adaptive Areas panel with role-aware navigation, a whole-home
  summary, dense feature-aware Area cards, and responsive layouts.
- Move diagnostics into the admin settings view while keeping dashboard reads
  available to normal users.

### Validation

- 323 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository pre-commit hooks and the whitespace check passed.

## 1.6.19-rc.5 - 2026-11-15

### Added

- Add read-model controls for configured lights and Adaptive Areas switches to
  the dashboard, using Home Assistant's service and entity-permission model.

### Validation

- 323 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository pre-commit hooks and the whitespace check passed.

## 1.6.19-rc.4 - 2026-11-15

### Changed

- Enrich dashboard Area cards with existing presence coverage, light groups,
  public environment assessments, room usage, cleaning, and source coverage.
- Keep the presentation feature-aware and Home Assistant theme-native.

### Validation

- 322 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository pre-commit hooks and the whitespace check passed.

## 1.6.19-rc.3 - 2026-11-15

### Fixed

- Keep dashboard diagnostics available when an optional Area diagnostic cannot
  be mapped, while reporting a compact warning for the affected Area.
- Show unavailable sources and empty aggregates as compact dashboard issues.

### Changed

- Separate the dashboard overview, Area list, Area details, and Diagnostics
  into distinct, localized Home Assistant-native views.

### Validation

- 322 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository pre-commit hooks and the whitespace check passed.

## 1.6.19-rc.2 - 2026-11-15

### Fixed

- Restore the Adaptive Areas dashboard WebSocket command handlers by applying
  Home Assistant's required decorator order.
- Keep the overview visible when live-update subscription fails and show a
  controlled command/error-code message for dashboard requests.
- Use the installed integration version for the dashboard frontend asset URL.

### Validation

- 319 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository pre-commit hooks and the whitespace check passed.

## 1.6.15 - 2026-10-20

### Fixed

- Preserve the prioritized order of public environment notices without a
  second alphabetical sort or order-destroying deduplication.
- Keep coverage notices last and limit public notices to the three most useful
  messages.
- Use stable singular/plural pollutant wording and severity-aware wording for
  very high pollutant values.

### Validation

- 301 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository lint checks passed.

## 1.6.14 - 2026-10-20

### Added

- Add graduated environment assessment quality from basic climate sensing to
  comprehensive indoor/outdoor coverage.
- Keep temperature and humidity useful as the minimum environment assessment
  without presenting missing air-quality data as good.
- Add actionable humidity, mould-risk, and outdoor-air ventilation notices.

### Validation

- 297 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository lint checks passed.

## 1.6.13 - 2026-10-20

### Fixed

- Prefer real rolling pollutant averages while marking live-value fallbacks as
  `instant_indicative` instead of presenting them as official 8-/24-hour means.
- Expose deterministic indoor and outdoor sensor-source mappings, including
  configured sources that are temporarily unavailable.
- Recommend brief ventilation when elevated CO2 conflicts with unfavorable or
  hazardous outdoor air quality.

### Validation

- 292 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository lint checks passed.

## 1.6.9 - 2026-10-15

### Fixed

- Keep Adaptive Areas energy aggregates monotonic across unavailable sources,
  source resets, unit changes, and Home Assistant restarts.
- Persist per-source energy baselines and aggregate totals while preserving
  existing entity IDs and Energy Dashboard compatibility.

### Validation

- 291 tests passed against the configured Home Assistant stable environment;
  1 test skipped.
- Repository lint checks passed.

## 1.6.6 - 2026-09-21

### Fixed

- Limit automatic light control to lights explicitly assigned to Light Group
  categories.
- Keep unconfigured Area lights unchanged when an Area clears or its light
  policy is re-evaluated.
- Build the parent All Lights group from the deduplicated union of configured,
  valid category members while preserving activation, brightness, blocking,
  presence-activity, and manual-override behavior.

### Validation

- 276 tests passed against Home Assistant 2026.9.0, including configured scope,
  CLEAR, BRIGHT, blocking-state, presence-activity, empty configuration,
  duplicate membership, and removed-entity regressions.
- Repository-wide Ruff, Black, JSON, and whitespace checks passed.

## 1.6.5 - 2026-09-21

### Fixed

- Make `device_tracker` entities already discovered for an Area contribute to
  occupancy when their state is `home`.
- Preserve the 1.6.3 Area assignment and source discovery behavior while
  retaining domain-specific runtime evaluation.
- Keep presence-control entities as a separate confirmation mechanism and
  preserve the optional Area-ID and Area-name tracker states.

### Validation

- 274 tests passed against Home Assistant 2026.9.0, including tracker source
  counts, activity reports, presence control, Keep-Only, clear timeouts, and
  cross-Area discovery isolation.
- Repository-wide Ruff, Black, JSON, and whitespace checks passed.

## 1.6.4 - 2026-09-21

### Fixed

- Evaluate presence sources with domain-specific state semantics instead of a
  shared global active-state list.
- Resolve room-level `device_tracker` states deterministically against the
  configured Home Assistant Area ID or Area Registry name.
- Keep `home`, `not_home`, `work`, and `school` tracker states from occupying a
  room while retaining trackers as regular presence sources and optional
  presence-control entities.
- Keep source discovery, runtime activity, source counts, and configuration
  choices consistent without adding entities or heuristic person matching.

### Validation

- 269 tests passed against Home Assistant 2026.9.0, including tracker room
  states, global location states, source counts, presence control, Meta Areas,
  BLE tracking, Wasp in a Box, and existing presence behavior.
- Repository-wide Ruff, Black, JSON, and whitespace checks passed.

## 1.6.3 - 2026-09-12

### Fixed

- Apply the presence-control gate to source activity as well as occupancy.
- Ignore blocked active sensor reports, including unchanged reports, without
  updating activity timestamps or reasons or publishing presence activity.
- Preserve pending clear timeouts and prevent activity-driven light group
  reactivation while the presence-control gate is closed.
- Re-evaluate occupancy when the gate opens without generating artificial
  source activity; preserve the existing OR semantics for control entities.

### Validation

- 250 tests passed against Home Assistant 2026.9.0, including gate states,
  repeated reports, clear timeouts, Meta Areas, and light group regressions.
- Ruff, Black, and whitespace checks passed.

## 1.6.2 - 2026-09-08

### Fixed

- Re-evaluate real-area child light groups on presence activity, including
  unchanged active sensor reports, without artificial occupancy transitions or
  additional public area events.
- Turn on every target light when a group is only partially on, while skipping
  groups whose members are already on.
- Preserve activation conditions, brightness modes, blocking states, and manual
  overrides during activity-driven control.
- Suppress duplicate turn-on calls when occupancy transitions and presence
  activity occur together; expose activity decisions in the existing trace.

### Validation

- Regression coverage for repeated presence reports, partial groups, duplicate
  triggers, activation conditions, brightness modes, and manual overrides.

## 1.6.1 - 2026-09-06

### Fixed

- Applied the required source formatting to the Meta Area summary helper so the
  packaged release passes every repository quality gate.

## 1.6.0 - 2026-09-06

### Added

- Explainable Area presence state with source counts, timestamps, transition
  reasons, active states, and public `adaptive_areas_area_event` events.
- Meta Area status and cleaning summaries derived from existing child Areas.
- Deterministic environment recommendations and aggregate quality attributes.
- Capability counts in the configuration flow plus richer diagnostics and
  system health data.

### Changed

- Consolidated cleaning information into the canonical cleaning-due binary
  sensor, including state, elapsed and remaining minutes, and capped score.
- Updated English and German translations and feature documentation.

### Removed

- Removed the redundant room-usage score sensor. Existing entity-registry
  entries are cleaned up automatically; automations should use the cleaning-due
  binary sensor and its attributes instead.

### Validation

- Passed the complete test suite against Home Assistant 2026.9.0.
- Passed all repository lint checks.
