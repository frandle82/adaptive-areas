# Testing

## Commands

| Purpose | Command |
| --- | --- |
| Stable Home Assistant suite | `scripts/test stable` |
| Beta Home Assistant suite | `scripts/test beta` |
| Stable and beta suites | `scripts/test both` |
| Lint and pre-commit checks | `scripts/lint` |
| Targeted stable test | `.tox/ha-stable/bin/pytest -q tests/test_<area>.py` |
| JSON validation | `python3 scripts/validate_json.py` |

Tox environments use Python 3.14. `scripts/lint` needs `tox` only. `scripts/test beta` needs `curl` and `jq` to look up the newest beta release on PyPI; stable runs do not need network access.

## Home Assistant compatibility

- The supported stable target is Home Assistant 2026.10.4. It is the default of `HA_STABLE_VERSION` in `tox.ini` (`ha-stable`) and is pinned in the `test-stable` CI job. `pytest-homeassistant-custom-component` 0.13.375 pins that version exactly and resolves through it.
- The newest Home Assistant stable release (2026.11.x) has no matching test harness release yet. Do not run or pin it until a harness release supports it.
- Override the default only for experiments, for example `HA_STABLE_VERSION=2026.8.1 tox -e ha-stable`.
- Verified 2026-11-20 on the working tree (HEAD 3b1bd6a plus uncommitted Phase 5 changes): full suite with Home Assistant 2026.10.4 and harness 0.13.375 reports 594 passed. The 563 figure is the pre-change baseline; the new tests in `tests/test_dashboard_permissions.py`, `tests/test_frontend_fixtures.py` and `tests/test_dashboard_subscription.py` account for the difference. Earlier figures for 2026.8.1 (532 passed, 1 skipped) were not re-run.

## Beta test job status

- Job `test-beta` in `.github/workflows/pytest.yml` is blocking. `continue-on-error` was removed so a failure is reported as a failure.
- **BLOCKED – TEST INFRASTRUCTURE INCOMPATIBILITY.** Not passed. Verified 2026-11-22 from the CI log of commit `15ec8f4`:
  - Python 3.14.10 on the GitHub runner.
  - `homeassistant==2026.11.0b6` (value of `HA_BETA_VERSION`, selected by the workflow).
  - `pytest-homeassistant-custom-component` is installed without a version. No harness release supports Home Assistant 2026.11.x beta; pip therefore resolves the 2020 release `0.2.1`, which pins `pytest==6.2.2` and `pluggy==1.0.0.dev0`. pytest 6.2.2 fails on Python 3.14 during assertion rewriting (`TypeError: required field "lineno" missing from alias`) while loading `conftest.py`.
  - The same versions fail with a different message on a later run (`AttributeError: module 'ast' has no attribute 'Str'`, run 45015644626 on `e981ad1`). Both messages come from pytest 6.2.2 running on Python 3.14; the failing module varies with the import order.
  - The current harness `0.13.375` pins `homeassistant==2026.10.4`. Installed manually against Home Assistant `2026.11.0b6` it fails in two places: `respx` imports `httpx` before Home Assistant aliases it to `httpx2`, and `pytest_homeassistant_custom_component` imports the private `_clear_logger_overwrites` from `homeassistant.components.logger`, which the beta no longer provides.
- The job was not green before. Run `1bad0d0` reported success only because `continue-on-error` hid the failure (`ha-beta: exit 1`, no tests collected).
- Not allowed: a stable Home Assistant version as beta, an old pytest pin, test shims, skipping the job, or marking it non-blocking.
- Exit condition: a `pytest-homeassistant-custom-component` release that supports the beta version. Then the job must run tests and pass.

## Selection rules

- Behavior changes require affected tests and, for broad changes, `scripts/test stable`.
- Config Flow, persisted options, or migrations require config/migration regression coverage.
- Panel, frontend, or flow changes require interactive UI verification when a Home Assistant test instance is available.
- Documentation-only changes need link/path and diff review; they do not require Home Assistant integration tests.
- Report commands actually run and any checks skipped, including the reason.

## Frontend browser harness

Test-only harness for the shipped panel (`tests/frontend/`). See `tests/frontend/README.md`.

- Regression checks: `node tests/frontend/run.mjs` (exit code 1 on failure; 213 checks on 2026-11-20). `--panel=<path>` runs the checks against another panel file, for example a saved pre-fix copy in an isolated directory. The runner sets the harness markup directly (no `file://` navigation), so sandboxed Chromium builds work; set `CHROME_BIN` for Chromium.
- Baseline measurements: `node tests/frontend/run.mjs --measure`.
- Fixtures are generated from the real backend: `ADAPTIVE_AREAS_WRITE_FIXTURES=1 .tox/ha-stable/bin/pytest tests/test_frontend_fixtures.py`.
- Not covered: the real Home Assistant frontend, theme engine and translation loader; a live instance.

## Light regression mapping (RC.3)

Where each light requirement is checked. "Gap" names what is not covered by an automated test.

| Requirement | Test file | Test functions (examples) | Gap |
|---|---|---|---|
| Ownership: exclusive physical group assignment | `tests/test_light_ownership.py`, `tests/test_light_ownership_runtime.py` | `test_same_light_in_two_areas_is_a_conflict`, `test_no_area_switches_the_shared_lamp_automatically` | – |
| Cross-area group assignment | `tests/test_light_cross_area_policy.py`, `tests/test_light_multi_area_distinct.py` | `test_all_group_of_the_other_area_never_switches_the_owned_lamp`, `test_each_area_switches_only_its_own_lamp` | – |
| Nested groups | `tests/test_light_nested_groups.py`, `tests/test_light_ownership.py` | `test_nested_group_that_switches_an_excluded_lamp_is_not_controlled`, `test_cyclic_group_references_terminate` | – |
| Dynamic group membership at runtime (native group membership changed after setup, no configuration change) | `tests/test_light_dynamic_membership.py` | `test_membership_change_creates_a_conflict_and_is_blocked_at_runtime`, `test_removing_the_conflict_restores_regular_control`, `test_dashboard_marks_only_the_conflicted_group_as_ownership_blocked` | – |
| Invalid stored configuration | `tests/test_light_ownership_runtime.py`, `tests/test_light_ownership_options.py` | `test_stored_shared_lamp_is_detected_by_the_runtime_check`, `test_stored_shared_lamp_is_diagnosed_by_the_ownership_check` | – |
| ALL group is OFF only | `tests/test_light_unified_all.py`, `tests/test_light_clear_cutover.py` | `test_occupation_never_switches_the_all_group_on`, `test_occupied_to_clear_sends_exactly_one_automatic_off` | – |
| Override by external state change | `tests/test_light_manual_override_origin.py`, `tests/test_light_unified_secondary.py` | `test_user_action_is_manual`, `test_manual_full_off_holds_against_presence_activity` | – |
| Automatic calls are not overrides (own, forwarded, ALL-OFF, initial, reload) | `tests/test_light_manual_override_origin.py` | `test_automatic_group_on_and_off_are_not_manual`, `test_initial_occupied_evaluation_is_not_manual`, `test_reload_then_automatic_cycle_is_not_manual` | – |
| Foreign ON without user context: override, no OFF | `tests/test_light_coordination_regression.py` | `test_foreign_on_without_user_context_sets_the_override_but_no_off`, `test_unchanged_state_report_sets_no_override` | – |
| Native context propagation (registry of 256 IDs) | `tests/test_light_origin_registry.py` | `test_newest_group_contexts_stay_recognised_and_older_ones_are_dropped` | – |
| Direct native service calls, correct target | `tests/service_faults.py` users: `tests/test_light_clear_cutover.py`, `tests/test_light_presence_activity.py` | `test_group_forward_is_not_a_second_automatic_decision` | – |
| No redundant commands | `tests/test_light_pending_commands.py`, `tests/test_light_unified_secondary.py` | `test_identical_pending_commands_are_sent_once`, `test_repeated_identical_occupation_sends_no_second_on` | – |
| No stale commands after new occupation | `tests/test_light_pending_commands.py` | `test_superseded_pending_command_is_dropped` | – |
| No automatic retry of a failed command | `tests/test_light_clear_cutover.py`, `tests/test_light_unified_all.py` | `test_failed_automatic_off_is_not_retried`, `test_failed_all_off_is_not_retried_by_an_identical_event` | – |
| New relevant input allows a new decision | `tests/test_light_unified_secondary.py` | `test_failed_call_allows_new_action_after_relevant_input_change` | – |
| Setup, partial failure, rollback | `tests/test_setup_rollback.py` | `test_failed_platform_setup_releases_listeners_and_areas_then_retry_works` | – |
| Reload and unload | `tests/test_light_lifecycle_brightness.py`, `tests/test_light_multi_area_distinct.py`, `tests/test_meta_area_hierarchy_regression.py` | `test_reload_after_on_sends_no_second_on`, `test_unload_releases_integration_event_listeners`, `test_reload_does_not_duplicate_meta_entities_or_events` | – |
| Four brightness modes against the transition table | `tests/test_light_mode_matrix.py`, `tests/test_light_transition.py` | `test_mode_matches_transition_table`, `test_mode_transition_table` | – |
| UNKNOWN never switches a light by itself | `tests/test_light_sensor_recovery.py`, `tests/test_light_unified_secondary.py` | `test_unknown_band_without_previous_state_is_not_dark`, `test_unknown_brightness_blocks_on_for_require_dark` | – |
| Exact limits, zero lux, band initialisation | `tests/test_light_sensor_recovery.py`, `tests/test_brightness_threshold_comparison.py` | `test_exact_turn_on_boundary_is_dark`, `test_initial_band_reading_is_off_native_and_unknown_central` | – |
| Configured area sensor outage: no global fallback | `tests/test_light_sensor_recovery.py` | `test_configured_area_sensor_outage_does_not_fall_back_to_global` | – |
| Repairs for incomplete brightness configuration | `tests/test_repairs_brightness.py`, `tests/test_repairs_brightness_flow.py`, `tests/test_light_lifecycle_brightness.py` | `test_repair_is_created_at_setup_and_resolved_after_correction` | – |
| Meta-Area aggregation and events | `tests/test_meta_area_brightness.py`, `tests/test_meta_area_brightness_lifecycle.py`, `tests/test_meta_area_hierarchy_regression.py` | `test_meta_brightness_matrix`, `test_exactly_one_relevant_bright_child_is_bright`, `test_dark_child_propagates_to_every_meta_area_that_contains_it` | – |

## GlobalEntry lifecycle (after RC.3, Phase F)

`tests/test_global_entry_lifecycle.py` (57 tests) runs a real GlobalEntry with the real entity, device, area, floor and issue registries, the test light and binary sensor platforms and native `light`/`switch` service calls. Light assertions use the recorded `call_service` events: the call on the group entity and its native forwarding to the lamp. No internal decision function is called directly.

Results: RC.3 = `2298f59`, Phase E = `8009f9d`, now = branch head. F = fails, P = passes.

| Req. | Test (file `test_global_entry_lifecycle.py` unless named) | Asserts | RC.3 | E | Now | Coverage |
|---|---|---|---|---|---|---|
| R01 | `test_r01_cold_start_controls_lights_without_registry_change` | setup before HA runs, START/STARTED, no entry reload, exactly one ON and one OFF on the group plus forwarding | F | P | P | full |
| R02 | `test_r02_configured_members_outside_the_ha_area_create_groups` | groups live, one ON, forwarding to the lamp | F | P | P | full |
| R03 | `test_r03_renamed_control_switch_is_the_switch_that_counts` | renamed switch enables/disables, survives reload, `control_switch` DTO | F | P | P | full |
| R04 | `test_r04_suffixed_control_switch_never_reads_a_foreign_entity` | foreign ON entity at default ID ignored; real `_2` switch counts | F | P | P | full |
| R05 | `test_r05_switch_registered_after_the_groups_enables_control` | restored-ON switch registers after the groups (event gate), one ON | P | P | P | full |
| R06/R07 | R01, `test_dark_bright_dark_sequence_before_and_after_reload` | ON, OFF, ON with forwarding, twice around a reload | P | P | P | full |
| R08 | `test_r08_device_assignment_after_setup_needs_no_initialisation` | control before assignment; registry IDs unchanged after the reload | P | P | P | full |
| R09/R10/R24 | `test_r09_r10_r24_deleting_an_area_removes_only_its_generated_entities` | entities and device removed; lamps and other Area unchanged and working | F | P | P | full |
| R11/R12 | `test_r11_r12_delete_last_area_and_create_it_again` | migrated entry stays LOADED; re-created IDs identical, no suffix | F | P | P | full |
| R13 | `test_r13_bad_bad_og_and_floor_og_keep_their_entities` | three reload cycles, distinct ownership, control of "Bad OG" | F | P | P | full |
| R14 | `test_r14_renaming_areas_and_floors_keeps_every_identity` | Area and floor rename, reload, restart (unload/setup), delete: entity ID, unique ID, registry ID, device ID, entry ID unchanged | F | F | P | full |
| R15 | `test_r15_migration_of_bad_and_bad_og_keeps_identities`; `test_migration*.py` | migration COMPLETE, identical entity/unique IDs | P | P | P | full |
| R16/R17 | `test_r16_r17_orphaned_area_devices_are_removed_ambiguous_entities_stay` | orphan device and entity removed, device-less entity kept | F | P | P | full |
| R18 | `test_r18_repeated_reloads_send_one_command_per_event` | three reloads, one call per event, stable listener counts | P | P | P | full |
| R19 | `tests/test_setup_rollback.py` | rollback of a failed platform setup | P | P | P | existing test |
| R20 | `test_r20_failed_platform_unload_is_not_a_successful_unload` | FAILED_UNLOAD, runtime kept, deletion error, registry untouched | F | P | P | full |
| R21 | `test_r21_deleting_a_meta_child_updates_meta_sources` | child list, presence sources, floor state | P | P | P | full |
| R22 | `test_r22_reload_on_registry_change_is_a_local_area_option`, `test_registry_event_for_two_areas_reloads_once`, `test_global_light_sensor_comes_from_global_options` | local reload flag, one debounced reload, global light sensor from `global_options` | F | P | P | full |
| R23 | `test_r23_own_registry_changes_cause_no_reload_loop` | no reload from own writes; own rename reloads once | F | P | P | full |
| R24 | R09, `test_r24_orphaned_device_with_a_foreign_entity_is_left_alone` | foreign entity on an orphan device protects it | P | P | P | full |
| R25 | `tests/test_area_retained_features.py` | parked feature settings | P | P | P | existing test |
| R26 | `test_r26_native_group_membership_change_in_a_global_entry`; `tests/test_light_dynamic_membership.py` (legacy, state-attribute model) | real native group helper, membership changed through its options flow, no Adaptive Areas write or device assignment: affected groups blocked incl. ALL-OFF, unaffected Area works, manual call works, dashboard marks exactly the affected groups, control returns after removal | P | P | P | full |
| R27 | `test_r27_unavailable_configured_lamp_keeps_its_group` | same registry entry after reload | P | P | P | full |
| R28 | `test_r28_deleted_ha_area_keeps_other_areas_working` | entry LOADED, Area skipped with config and entities, Repair raised, other Area controls | F | P | P | full |
| Phase F | `test_area_and_floor_with_the_same_slug_exist_independently`, `test_existing_area_keeps_its_ids_and_only_the_newcomer_changes` | no duplicate unique IDs, existing IDs unchanged, newcomer controls | F | F | P | full |
| Phase F | `test_climate_*` (4) and `tests/test_environment.py::test_health_warning_has_highest_context_priority` | Health read, alert, rename, foreign default ID ignored, missing Health | F | F | P | full |
| Phase F | `test_no_cleanup_during_an_unfinished_migration`, `test_no_cleanup_with_an_inconsistent_area_configuration`, `test_disabled_generated_entity_survives_reload_and_cleanup` | cleanup guards, disabled entity kept | P/P/P | F/P/P | P | full |
| Phase F | `test_global_entry_offers_no_per_area_options_flow` | `supports_options` is False | F | F | P | full |
| Phase G | `test_meta_all_group_exists_on_the_first_setup`, `test_meta_without_lit_children_has_no_all_group` | first setup without registry entries: Meta ALL live with the children's groups as native members, never switched automatically, child ALL-OFF once, manual operation, reload without duplicates; no group without lit children | F | F | P (failed on `3acee62`) | full |
| Phase G | `test_disabled_presence_entity_keeps_identity_on_rename`, `test_removed_presence_entity_does_not_change_the_identity`, `test_fallback_id_part_that_is_taken_gets_a_unique_one` | identity edge cases | – | – | P (the removed-entity case failed on `3acee62`) | full |
| Phase G | `test_no_cleanup_without_global_options`, `test_no_cleanup_of_a_device_with_two_area_identifiers`, `test_area_with_the_id_of_a_configured_floor_is_refused` | cleanup guards, RC.4 key-space decision | – | – | P (all three failed on `3acee62`) | full |
| Section 10 | `test_outage_recovery_override_and_clear_in_a_global_entry`, `test_shared_lamp_in_a_global_entry_is_never_switched` (negative safety test) | outage and recovery send nothing, CLEAR one ALL-OFF, manual override holds, shared lamp never switched | P | P | P | full |

Not covered automatically: a real Home Assistant restart with persisted storage (simulated by cold start and unload/setup), Hassfest and HACS validation.

Most older light tests use legacy single-Area entries; new lifecycle tests should use a GlobalEntry.

Verified 2026-11-26 on the branch head: see the Phase F report in [HANDOVER.md](HANDOVER.md).

Parallel runs: `-n 4` with and without `--cov` pass in the repository and in a separate worktree (Phase G, 1039 tests, 92 % coverage). Two earlier hangs followed aborted runs with leftover worker processes and were not reproducible; no lifecycle leak was found (listener counts are asserted in R18).
On `3acee62` (end of Phase F) 7 of the 44 tests fail: the Meta ALL, removed-entity, two cleanup-guard and floor-ID tests, plus R14 and the slug-collision test, which compare identities from the first setup and therefore depend on the Meta ALL fix.

Stable CI stall (Phase H, 2026-11-27): the stable job stopped after `tests/test_frontend_translations.py` in 4 of 8 runs while every local run passed. Cause, reproduced locally with a live process and the stack of `asyncio.Runner.close()`: the former R05 gated the switch platform setup on an `asyncio.Event` set by a light group state change. Home Assistant runs platform setups shielded, so depending on timing that setup task outlived the test and the pytest-asyncio runner waited for it forever. Outside every per-test timeout, and the progress dots of the file were still buffered, so the log showed the stall before the file. R05 now removes and re-adds the switch through its real entity platform, without cross-task waiting. Production code was not involved. The temporary diagnostics (file-wide thread timeout, faulthandler watchdog, conftest task report) were removed again.

Phase J.3 (2026-11-28): `tests/test_light_lifecycle.py` covers L01–L36 with the template setup of Phase J.2: no restored override in both forced platform orders (the order is forced by waiting in `async_added_to_hass`, never by timing), reloads, the initial decision before and after Home Assistant has started, unknown presence and brightness, a failed call without retry, a reload before start, and Meta presence unload (Global and a floor), reloads while extended and the setup rollback. Time is moved with `freezer` and `async_fire_time_changed`; lingering timers and tasks fail the test through the harness. On Phase J.2 (`8c605f3`) 19 of the new and changed tests fail, on RC.4 29.

Phase J.2 (2026-11-27): `tests/test_light_template_helper.py` runs the exact HAOS test light: a template light helper created through the real template config flow (and the YAML equivalent) on a storage `input_boolean`, with a cold-started GlobalEntry ("Arbeitszimmer", Meta "global"). No mock or push light. By default the `binary_sensor` component is set up first, as on a real instance. On RC.4 (`7f9593f`) every switching test passes; 6 tests fail there only on diagnostics (origin classes, `group_unavailable`, per-group DTO) and on the event-loop check of the listeners.

Phase J (2026-11-27): `tests/test_light_manual_override_lifecycle.py` runs the real integration with `PushLight`, a push device that reports its state after the call (the Context is assigned by Home Assistant, never by the test). It covers J01–J28 where a deterministic test is possible, including a cold-started GlobalEntry with a Meta Area and a real nested native light group. On unchanged RC.4 code 3 of its 18 tests fail (panel trace reasons and the two override origin traces); every light switching test passes on RC.4. The restart cases "occupied before the restart" are not in the suite: their outcome depends on a thread race (about 1 in 5 runs keeps the stored override), see [DECISIONS.md](DECISIONS.md). Do not run that file with `-p no:logging`; other files then fail on `caplog`.
