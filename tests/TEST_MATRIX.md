# Adaptive Areas test matrix

The stable Home Assistant suite (`tox -e ha-stable`) is the authoritative release
gate. It always discovers the complete `tests/` tree and enforces at least 80%
global branch coverage. HA beta is informative.

This matrix maps every current integration component and public behavior to its
regression tests. A platform or module added to the integration must be added here
with its tests in the same change.

| Scope | Implementation | Test coverage |
| --- | --- | --- |
| Config-entry setup, unload, reload, multiple Areas and listener cleanup | `__init__.py`, `base/adaptive.py` | `test_init.py`, `test_area_reload.py`, `test_decision_trace.py`, `test_cleaning_tracker.py` |
| Config flow, defaults, feature selection, options and duplicate/legacy import handling | `config_flow.py`, `const.py` | `test_config_flow.py` |
| Supported config-entry migrations and post-migration loading | `__init__.py`, `helpers/light_groups.py` | `test_init.py`, `test_light_group_migration.py`, `test_environment.py`, `test_config_flow.py` |
| Area/device/entity discovery, include/exclude rules and missing registries | `base/adaptive.py`, `helpers/area.py`, `repairs.py` | `test_area_state.py`, `test_area_reload.py`, `test_environment.py`, `test_repairs.py` |
| Sensor aggregates, minimum source count, units and meta aggregates | `sensor/`, `helpers/area.py` | `test_aggregates.py`, `test_meta_aggregates.py` |
| Area state and presence binary sensors | `binary_sensor/presence.py` | `test_area_state.py`, `test_meta_area_state.py`, `test_area_reload.py` |
| BLE presence | `binary_sensor/ble_tracker.py` | `test_ble_tracker_monitor.py` |
| Wasp-in-a-box presence | `binary_sensor/wasp_in_a_box.py` | `test_wasp_in_a_box.py` |
| Cleaning due binary sensor and room-usage sensor | `binary_sensor/__init__.py`, `sensor/__init__.py`, `helpers/room_usage.py` | `test_cleaning_tracker.py`, `test_environment.py` |
| Environment entity, public attributes and deprecated aliases | `sensor/__init__.py`, `helpers/environment.py` | `test_environment.py` |
| Temperature, humidity, comfort, mould, pollutants, rolling windows and provisional alerts | `helpers/environment.py` | `test_environment.py` |
| Indoor/outdoor isolation and mitigation outputs | `helpers/environment.py` | `test_environment.py` (`test_particle_mitigation_changes_without_changing_indoor_state` and outdoor-air scenarios) |
| Ventilation demand/strategy, windows, air cleaning and cooling | `helpers/environment.py`, `switch/fan_control.py` | `test_environment.py`, `test_fan.py` |
| Light groups and adaptive profiles | `light.py`, `helpers/light_groups.py` | `test_light.py`, `test_light_group_migration.py` |
| Fan groups | `fan.py`, `switch/fan_control.py` | `test_fan.py` |
| Cover groups | `cover.py` | `test_cover.py` |
| Switch groups and controls | `switch/` | `test_switch_groups.py`, `test_climate_control.py`, `test_fan.py`, `test_media_player.py` |
| Reference-temperature number | `number.py` | `test_environment.py` |
| Threshold entities | `threshold.py` | `test_threshold.py` |
| Area-aware media player and media-player groups | `media_player/` | `test_media_player.py` |
| Services, validation, multi-Area targeting and unload | `services.py`, `services.yaml` | `test_cleaning_tracker.py` |
| Diagnostics, JSON serialization, redaction and decision traces | `diagnostics.py`, `helpers/diagnostics.py`, `helpers/decision_trace.py` | `test_diagnostics.py`, `test_decision_trace.py` |
| Repairs for deleted Areas/entities and unavailable inputs | `repairs.py` | `test_repairs.py` |
| System health privacy and registration | `system_health.py` | `test_system_health.py` |
| Timers and cancellation without real sleeps | `helpers/timer.py` | `test_timer.py`, `test_wasp_in_a_box.py` |
| Translation and enum/value consistency | `translations/*.json`, `const.py` | `test_translations.py`, `test_environment.py`, `test_repairs.py`, `scripts/validate_json.py` |
| Release integrity and complete stable gate | `.github/workflows/`, `tox.ini`, `setup.cfg` | GitHub Actions: stable tests, lint, Hassfest, HACS, CodeQL and release-integrity jobs |

There are currently no `button` or `select` platforms and no reconfigure step;
post-setup changes use the options flow. If any of these are introduced, their
lifecycle, entity contract, translations, validation and regression cases become
mandatory matrix entries.

For numeric decision boundaries, tests must include the exact boundary and both
sides (for integral thresholds typically `n-1`, `n`, `n+1`). Time-dependent tests
must use Home Assistant time helpers, `freezer`, or the repository virtual clock;
tests must never wait using real `sleep()` calls.
