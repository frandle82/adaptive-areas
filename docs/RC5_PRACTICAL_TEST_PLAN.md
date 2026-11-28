# RC.5 practical acceptance plan (real Home Assistant OS)

Status: planned, not executed. Installation needs a separate release and installation approval.

Purpose: check on a real installation whether the RC.4 field fault ("Arbeitszimmer" did not switch on at DARK, the panel showed a manual override) still occurs. The automated suite reproduces the exact template test light (`light.test_leuchte` on `input_boolean.licht`) and passes already on RC.4; the HAOS cause is not proven. RC.5 contains proven lifecycle fixes and better diagnosis only.

If a fault occurs: first save the diagnostics export, the Area's decision trace (panel) and the logbook. No manual registry cleanup and no device assignment before that.

## Preparation

1. Full HAOS backup.
2. Diagnostics export of the GlobalEntry with RC.4.
3. Save states and attributes (`manual_override`, `controlling`) of the accent group, the ALL group, Meta ALL and `light.test_leuchte`.
4. Record any active override (screenshot of the light diagnosis).
5. Save entity IDs and unique IDs of the Adaptive Areas entities.
6. Install RC.5 (only after approval).

## Original fault

7. Check "Arbeitszimmer" with `light.test_leuchte`.
8. Confirm `input_boolean.licht` as the state source of the template light.
9. Confirm light control switch and light group settings (accent group, `dark_on_bright_off`, 117/123 lx, activation on occupancy).
10. Occupy the Area.
11. Brightness above 123 lx.
12. Brightness below 117 lx.
13. Automatic ON (light diagnosis: accent group, last decision "Turn on", reason "Service call sent").
14. Brightness above 123 lx.
15. Automatic OFF.
16. Brightness below 117 lx again.
17. Automatic ON.
18. Do not assign a device as a workaround.

## Manual override

19. Switch the lamp by hand.
20. Light diagnosis: override only on the groups actually affected; origin class in the decision trace.
21. Change the brightness.
22. The override stays; no automatic command.
23. Reload the integration.
24. The override has ended (rule since RC.5: an override lasts for the current setup only).
25. The regular initial decision applies (dark and occupied: the lamp switches on).
26. Full Home Assistant restart.
27. No old override is restored.

## Initialization and lifecycle

28. Light control right after the start: at most "Initial decision still open" until Home Assistant has started, then one initial decision per group.
29. Several reloads.
30. Meta Areas in the extended state.
31. No events of old setup generations (decision trace, logbook).
32. No new or suffixed entity IDs.
33. Compare the per-group light diagnosis with the real states.

## Closing

34. Save the RC.5 diagnostics export.
35. Compare decision trace and logbook.
36. 48–72 hours of everyday use.
