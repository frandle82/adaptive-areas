# Changelog

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
