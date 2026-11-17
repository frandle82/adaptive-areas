# Single-GlobalEntry migration: manual Home Assistant test matrix

## Legacy baseline

- Install the current legacy build and configure at least three regular Areas, one
  floor Meta Area, and the Global Meta Area.
- Configure light groups, Area Climate, climate control, fan groups, room usage,
  presence hold, BLE tracking, and aggregates across the regular Areas.
- Rename one generated entity, disable another, and record entity IDs, unique IDs,
  device IDs, device identifiers, and HA Area assignments.
- Produce Energy, Room Usage, and Cleaning Tracker state.

## Upgrade and Repair

- Install the migration build and restart Home Assistant.
- Confirm that exactly one migration Repair is shown and that opening Dashboard,
  diagnostics, panel reads, reload, and restart do not change ConfigEntries.
- Open the Repair, confirm the migration, and wait for completion.

## Verify migration result

- Confirm there is exactly one Adaptive Areas ConfigEntry and that all Areas are
  present in it.
- Compare every recorded entity and device identity, customization, disabled state,
  and HA Area assignment with the baseline.
- Confirm no generated entity gained a `_2` suffix and no duplicate device exists.
- Verify dashboards, diagnostics, aggregates, floor/global Meta Areas, controls,
  environment data, and persisted Energy/Room Usage/Cleaning state.

## Lifecycle regression

- Restart Home Assistant, reload the GlobalEntry, then make a relevant registry
  change and register an Area entity.
- After each step verify one runtime instance per Area, no duplicate listeners or
  generated entities, no migration Repair, and unchanged entity/device identities.

## Recovery exercises

- Interrupt after factory creation, prepared configuration, legacy unload,
  registry transfer, partial remove, and cleanup.  After a Home Assistant restart,
  verify that no migration resumes automatically.
- Use only the migration Repair confirmation to resume. Confirm that the existing
  GlobalEntry is reused, removed legacy entries are not recreated, and a partial
  remove handles only remaining entries.
- Exercise one failed entity/device transfer, one activation failure, and one
  verification failure. Before the first remove, verify legacy ownership is
  restored; after a partial remove, verify forward recovery is used instead.

## Meta and persistence

- Verify floor/global Meta aggregates before and after migration, then register a
  late child source and confirm it is discovered without cross-Area sources.
- Compare saved Energy, Room Usage, and Cleaning Tracker values before migration,
  after completion, and after restart.
