# Changelog

## 1.7.0-rc.3 - 2026-11-25

Pre-release for practical validation. This is not a stable release. Practical validation on a Home Assistant instance is still pending.

Changes compared with 1.7.0-rc.2.

### Changed

- Automatic light control runs only through explicitly configured individual light groups (overhead, sleep, accent or task lights). The former policy-only control path is removed.
- Lamps that are in no light group are never switched automatically by Adaptive Areas, even when Lux limits are set. Manual operation of these lamps is unchanged. To keep automatic control, add the lamp to an individual light group of its Area. No default group is created.
- Automatic group commands are direct native Home Assistant light service calls with the group entity as target. The origin registry for automatic group calls is limited to the newest 256 context IDs.
- A physical light belongs to at most one individual light group. Shared lamps are refused on save; a stored or runtime conflict blocks automatic control and is diagnosed, never repaired automatically. ALL groups stay OFF-only.
- The dashboard light diagnosis shows the automatic control path (`control_path`) and the override state. The policy-only lamp list, the policy decision and the dispatch fields are removed from the status payload.
- Brightness has one classification (DARK, BRIGHT, UNKNOWN) from the Lux limits and the numeric Area illuminance sensor, or the global lux sensor. UNKNOWN is neither DARK nor BRIGHT. The four brightness modes keep their tasks: `ignore`, `require_dark`, `turn_off`, `dark_on_bright_off`.
- Decided: with `turn_off`, an occupied Area whose brightness is `unknown` switches its group on, as `ignore` does. `require_dark` and `dark_on_bright_off` do not switch on from `unknown`. A sensor outage alone never sends a command. 1.6.18 switched a `turn_off` group off in this case; the difference is intended.
- Without any brightness source, `require_dark` and `dark_on_bright_off` do not switch lights on. A repair reports the missing configuration.
- Meta-Areas: DARK when any relevant child is DARK; BRIGHT only when all relevant children are BRIGHT; otherwise UNKNOWN. A relevant child without a brightness source is UNKNOWN. Meta-Areas send no automatic light command.
- Meta-Areas publish `dark_started` and `dark_ended` on the `adaptive_areas_area_event` bus event when their derived brightness changes. Automations that listen to this event for Meta-Areas will see these events for the first time. No new event types.
- The public illuminance threshold entity is unchanged and informational. Area brightness and light control do not read it.
- A group already off no longer receives a redundant `turn_off` when the Area becomes occupied while bright.

### Fixed

- Meta-Area brightness no longer reports BRIGHT regardless of its children. A child with unknown brightness, or a missing child state, no longer makes the Meta-Area BRIGHT.
- Native repairs report incomplete brightness configuration (missing Lux limits, invalid limits, missing source, legacy `dark_entity` without limits). A repair disappears after the correction.
- Dead translation keys for `dark_entity` were removed. The stored key is still accepted; no stored configuration changes.

### Upgrade notes

- Check the Light diagnosis and the repairs after the upgrade.
- Lamps that were controlled through the former policy-only path must be added to an individual light group to stay under automatic control.
- Check automations that read Meta-Area `dark` or `bright` states or listen to `adaptive_areas_area_event`.
- Check `turn_off` groups in an Area with a sensor outage: they now switch on when occupied.
- Backup before upgrading; rollback means restoring the backup or installing 1.7.0-rc.2 with its configuration.

### Known limitations

- A native light group whose members change at runtime is checked on every automatic command. The check is covered by an automated test with a modelled native group; the behaviour with a real `light.group` configuration entry is not covered.
- The root cause of the original 1.6.18 report on a real Home Assistant OS installation is not proven.
- Meta-Area brightness stays UNKNOWN while any relevant child has no brightness source (intended).
- The practical acceptance on Home Assistant OS (30 cases, `docs/RC3_PRACTICAL_TEST_PLAN.md`) is pending.

## 1.7.0-rc.2 - 2026-11-24

Pre-release for practical validation. This is not a stable release. Practical validation on a Home Assistant instance is still pending.

Changes compared with 1.7.0-rc.1.

### Fixed

- Light control: explicitly configured light group members are honored, also when they are outside their Home Assistant area.
- Light ownership: a physical light is controlled by one Area only, across Areas.
- Light groups: an excluded lamp inside a nested Home Assistant light group is never switched through the group; such a configuration is refused on save.
- Automatic light commands no longer trigger a manual override. A real manual action still does.
- ALL group: its automatic OFF at final CLEAR is correct and never switches on.
- Light diagnostics show the actual control path: group control, ALL, policy-only lamps and blocked configurations.

### Added

- Area illuminance sensor: one optional numeric sensor per Area (domain `sensor`, device class `illuminance` or unit `lx`). Dashboard, Options Flow and the save validation use the same rules.
- The Area brightness classification is central: DARK and BRIGHT come from the Area sensor (or the global light sensor) and the configured light limits, with hysteresis. Without a configured limit the state is UNKNOWN; UNKNOWN is never read as dark or bright.

### Changed

- Feature visibility in the Area editor follows the local draft immediately. Nothing is saved until the regular save.
- Disabling a feature keeps its configuration (inactive). Enabling it again restores the settings.
- Presence domains: `binary_sensor` and `media_player` are the defaults. Device classes use the same selection as the domains; the default device classes are `motion` and `occupancy`.
- Default vacancy delay (presence release) is one minute.

### Compatibility

- `area_illuminance_sensor` and `retained_features` are additive optional configuration keys.
- No schema version increase and no migration is required.
- Legacy `dark_entity` values remain stored but are no longer evaluated. Binary darkness sources must be replaced by a numeric illuminance sensor where the Dark state is needed.
- Without configured brightness limits the brightness classification remains UNKNOWN.
- A configured but unavailable Area illuminance sensor does not fall back to the global sensor.
- Policy-only lamp control remains supported.

## 1.7.0-rc.1 - 2026-11-24

Pre-release for practical validation. This is not a stable release. Practical validation on a Home Assistant instance is still pending.

### Added

- Exclusive light group ownership: a physical light may belong to one individual light group only (ceiling, sleep, accent or task lights). The rule applies across Areas, including the global entry. Nested Home Assistant light groups are resolved to their physical members. The ALL group is excluded from this rule.
- Dashboard: lights that are already assigned to another individual light group are locked and name the owning group and Area.
- Server-side validation in the Options Flow and on dashboard save rejects conflicting assignments. Error messages are localised (English and German). A rejected save leaves the previous valid configuration unchanged.

### Changed

- Light control uses one event-driven decision path for automatic light groups: transition decision, dispatch, group command, execution.
- Transitions are decided explicitly, and redundant automatic switching commands are avoided.
- No automatic retries when the decision basis is unchanged. There are no additional timers, deferred queues or periodic reconciliation.
- Manual overrides and blockers are handled as separate states.
- ALL switches off automatically only. It never switches on automatically.
- Group control and policy-only control are separated. Lights of automatic groups are never policy targets.
- Brightness classification and UNKNOWN states are handled consistently. Missing sensor data is not guessed.

### Removed

- The retired option `vacancy_delay` (vacancy timer) has no effect any more. Existing stored values are tolerated and ignored.
- The internal vacancy helper module was removed. The vacancy OFF now follows the common decision path.

### Compatibility

- No schema change and no migration.
- Existing configurations with a light in more than one individual light group are **not** changed automatically. The affected groups are excluded from automatic actions as a whole. Conflict-free groups keep working. The conflict is reported as a runtime diagnosis.
- To resolve a conflict, remove the duplicate assignment in the dashboard or in the Options Flow. Manual control of the lights in Home Assistant remains possible.
- Later registry or membership changes are reported as runtime deviations. They are not repaired automatically.

### Known issues

- Home Assistant beta tests are blocked. The beta job fails with `ResolutionImpossible`, because the test harness `pytest-homeassistant-custom-component` 0.13.375 pins Home Assistant 2026.10.4. No beta compatibility is claimed.
- Home Assistant 2026.11.x has not been validated in practice. The automated stable target is Home Assistant 2026.10.4.
- The vacancy delay value is still shown read-only in the light control tab of the dashboard. It has no effect.
- The original field reports (an Area stays dark although the brightness is exceeded; lights do not switch on at a change from bright to dark) are not confirmed as resolved on a real instance.

### Tests

- Stable test suite (Home Assistant 2026.10.4, pytest-homeassistant-custom-component 0.13.375, Python 3.14): 957 passed.
- Browser harness: 398 of 398 checks passed.
- Coverage: 91 %.
- Lint: ruff, black and pre-commit passed.

## 1.6.19-rc.17 - 2026-11-22

### Added

- Brightness diagnostics in the dashboard, for test and diagnosis in a real Home Assistant instance:
  - Area detail shows the actual darkness source: the configured darkness entity with its state, the derived area status, and a note when no darkness entity is configured (the default assumption "dark" is labelled as such), when the entity is not found, or when it is unavailable (the last valid state remains).
  - Light automation shows the global light sensor with its entity ID, the current lux value, the stored on and off limits, the policy decision and reason code, presence, the light targets with their availability, and the active manual override mode.
  - Policy wish, override block and duplicate suppression are reported separately.
  - The dispatched action is labelled as a service call that was issued. It is not presented as a confirmed light switch. If no runtime record exists, it is shown as "not recorded".
  - The aggregation threshold sensor is shown as a separate configuration, with its own threshold and hysteresis, not mixed with the percentage hysteresis of the light automation.

### Fixed

- The dashboard consistency check read the darkness entity from the wrong configuration path and could never report a contradiction. It now reads the same path as the area logic (`secondary_states.dark_entity`).

### Compatibility

- No change to light switching, presence, dedupe or override rules. No schema change, no migration, no new persistence.
- The light runtime status now also contains entity IDs and stored limits. It is available to administrators only.

### Known issues

- The original field reports are not yet fixed or finally explained: the area stays dark although the expected brightness is exceeded, and the lights do not switch on at a change from bright to dark. This release is for targeted diagnosis in a real Home Assistant instance.
- Home Assistant stable tests passed. The Home Assistant beta test is BLOCKED by a test-infrastructure incompatibility and was not completed successfully. No beta compatibility is claimed.
- Real-world acceptance of the diagnosis is still pending.

## 1.6.19-rc.16 - 2026-11-22

### Added

- Percentage-based hysteresis for the light automation in the dashboard. The Area editor takes a threshold T in lx and a hysteresis H in percent. Stored limits: `on = T × (1 − H / 200)` (turn on below) and `off = T × (1 + H / 200)` (turn off above). Example: T = 100 lx, H = 20 % gives turn on below 90 lx and turn off above 110 lx. The display shows at most one decimal place; the calculation uses full precision without intermediate rounding.

### Compatibility

- Stored lux limits stay stored in `turn_on_below` and `turn_off_above`. No schema change and no automatic migration.
- Saving without changes leaves the stored limits unchanged.
- Changing only the threshold keeps the exact stored hysteresis; changing only the percentage recalculates from the exact threshold.
- Every valid stored pair (threshold greater than 0, 0 ≤ on ≤ off) is shown as a percentage. Invalid stored values are shown with both lux limits and are not overwritten silently; they are replaced only after an explicit user action.
- The backend accepts equal limits (0 % hysteresis).

### Limits

- H = 0 % is allowed: the light follows the threshold without a hold band.
- H = 200 % is allowed (turn on below 0 lx).
- T = 0 is not allowed; the backend rejects a stored threshold of 0.
- The aggregate threshold sensor is unchanged and keeps its own percentage hysteresis, which uses a different formula.

### Known issues

- Home Assistant beta tests are blocked by an incompatibility of the test harness (BLOCKED – TEST INFRASTRUCTURE INCOMPATIBILITY). The stable tests passed. No beta compatibility is claimed.
- The real-world acceptance of the percentage hysteresis in a Home Assistant instance is still pending.

## 1.6.19-rc.15 - 2026-11-22

### Fixed

- Automatic detection of suitable presence sensors: `binary_sensor` entities are discovered for the device classes `motion`, `occupancy` and `presence` without a manual include list. A missing device-class setting now falls back to these defaults instead of detecting nothing.
- Exclusion rules: `exclude_entities` always wins over `include_entities`, also for entities that are known only from loaded Area entities.
- Misleading presence hint when changing the domain selection: unsaved changes show a neutral note; the definitive warning appears only for the saved configuration without an effective presence source.

### Changed

- Entity selection is unified in one component (`aa-entity-picker`): searchable, single and multiple selection with chips, keyboard operation (arrow keys, Enter, Escape, Tab) and a stored-value safe 200-option limit. It is used for include, exclude, presence control, keep-only, darkness, accent and sleep entities, the Area temperature and humidity sensors, outdoor and surface sensors, relevant windows, the weather entity, the global light sensor, the climate entity and the lights of light groups.
- Form layout: consistent field heights, labels above fields, checkboxes aligned with their labels, and clearly separated section headings.
- The panel loads its JavaScript through a versioned loader. Updates load the JavaScript that belongs to the installed integration.
- Keyboard and basic accessibility: combobox roles, labelled remove buttons, status messages for selection changes.

### Compatibility

- `media_player`: only `playing` counts as a presence activity indicator. A media player that is `on` but idle is no longer presence. Existing configurations are kept; there is no data migration.
- `remote`: never discovered automatically. A remote counts only when it is explicitly included in the Area.
- Stored configuration values, including unsupported presence domains and values outside the current filters, are kept.

### Known issues

- Home Assistant stable was tested successfully. The automated Home Assistant beta test could not run successfully because of an incompatibility of the test harness with the beta release; it is blocked and not passed. No beta compatibility is claimed.
- Not yet verified: the real Home Assistant interface, a true 200 % browser zoom, a screen reader, and behaviour with real presence sensors.
- The status error observed on the test instance (a configured source shown as `unknown`) was not explained by this release.

## 1.6.19-rc.14 - 2026-11-22

### Added

- The native Home Assistant diagnostics of an Area include `presence.evaluation`: configured domains, device-class filter, manual include and exclude counts, each presence source with domain, device class, status, origin (manual or automatic), evaluation and raw signal, the presence control gate, the raw signal, the confirmed occupancy, the dashboard state and a reason code. Entity IDs are not exported.

### Compatibility

- The presence logic is unchanged. Existing diagnostic keys are unchanged; `presence.evaluation` is additional.
- A closed presence control gate does not confirm occupancy. The dashboard may still show `clear` when the Area is reliably not occupied; `unknown` only when no source is evaluable.

### Known issues

- The status error observed on the test instance (a configured source shown as `unknown`) is not yet explained. Use the new diagnostics to identify the cause.

## 1.6.19-rc.13 - 2026-11-22

### Added

- Presence domains in the Area editor are a checkbox dropdown offering exactly `binary_sensor`, `device_tracker`, `media_player` and `remote`. Several domains can be selected at once; the closed dropdown lists the selection.
- Entity lists (include, exclude, presence release, keep-only) are collapsed by default and show the number of selected entities.
- The Area editor shows a factual hint when the saved Area has no effective presence source.

### Changed

- Light limits are edited as threshold and hysteresis and stored unchanged as `turn_on_below` and `turn_off_above`.
- The global light sensor accepts sensors with device class `illuminance` or the exact unit `lx`.
- Lux inputs are compact numeric fields.
- Light groups are nested, keyboard-operable sections with item counts.

### Fixed

- Explicitly included presence entities without a registry entry are used as presence sources.
- Explicitly included presence sources bypass the `binary_sensor` device-class filter; exclusions still win.
- Explicitly included light entities without a registry entry are light targets.
- Entity selectors and lux inputs no longer overflow narrow containers.
- Integration translation files passed Home Assistant's hassfest validation again: the dashboard texts moved from the custom `dashboard` category in `translations/*.json` to `dashboard_texts/*.json`, loaded through `adaptive_areas/get_dashboard_texts`. The texts are unchanged.

### Compatibility

- Stored presence domains outside the four offered domains are kept and flagged. They are not deleted or migrated, and they are ignored by presence evaluation.
- The backend rejects a presence domain only when a save newly adds it. Explicit removal is allowed.
- An empty presence domain selection is allowed.
- Stored light limits are unchanged.

### Validation

- 660 Python tests passed (pytest-homeassistant-custom-component, Home Assistant 2026.10.4 test framework).
- 333 browser harness checks passed (headless Chrome with a simulated Home Assistant `hass` object and backend-generated fixtures).
- Ruff, Black, JSON validation and `git diff --check` passed. The repository pre-commit hooks passed on the staged files.

### Known limitations

- Not yet run in a real Home Assistant installation: presence domain dropdown, collapsed entity lists, saving with a real presence sensor, the configured lux sensor on the test instance, and browser zoom at 200 %.
- Opening the presence domain dropdown with very long entity IDs is not covered by the browser harness.
- The presence hint reflects the saved configuration, not unsaved form changes.

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
