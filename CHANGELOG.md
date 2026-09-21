# Changelog

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
