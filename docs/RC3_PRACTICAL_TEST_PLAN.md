# RC.3 practical acceptance plan (real Home Assistant OS)

Status: planned, not executed. No installation on the real system is part of this document.

Purpose: manual acceptance of `1.7.0-rc.3` before a pre-release is published. The automated suite
cannot prove the physical state of lamps, real sensor noise or the real HAOS configuration.

## Verbindliche Produktentscheidungen (abgeschlossen)

- **UNKNOWN:** `ignore` and `turn_off` switch on when occupied and a switch is needed. `require_dark` and `dark_on_bright_off` do not switch on from UNKNOWN. A sensor outage alone never sends a command. UNKNOWN is neither DARK nor BRIGHT.
- **Meta-Area:** DARK when any relevant child is DARK; BRIGHT only when all relevant children are BRIGHT; otherwise UNKNOWN. A child without a brightness source is UNKNOWN. Meta-Areas send no automatic light command.

## Recording per case

For each case, record: initial configuration, trigger, expected decision, expected Home Assistant service
call (`light.turn_on` / `light.turn_off`, target entity), expected light state, relevant diagnostics
(Light diagnosis in the dashboard, Repairs), and the pass or fail result.

Pass criterion: every case behaves as expected. A deviation blocks RC.3 unless it is an intended change named in the CHANGELOG.

## Cases

| # | Case | Initial configuration | Trigger | Expected decision | Expected service call | Expected light state |
|---|------|------------------------|---------|-------------------|-----------------------|----------------------|
| 1 | Study, accent group, `require_dark` | Lux limits set, numeric area illuminance sensor | Occupation while dark | ON once | `turn_on` on the group | on |
| 2 | Brightening while occupied, `require_dark` | as 1 | Lux rises above the upper limit | no command | none | unchanged |
| 3 | Darkening while occupied, `require_dark` | as 2 | Lux falls below the lower limit | ON only if not already on | `turn_on` if needed | on |
| 4 | Brightening while occupied, `dark_on_bright_off` | as 1, mode changed | Lux rises above the upper limit | OFF | `turn_off` | off |
| 5 | Brightening while occupied, `turn_off` | as 1, mode changed | Lux rises above the upper limit | OFF | `turn_off` | off |
| 6 | Sensor outage, occupation, `require_dark` | as 1 | Sensor `unavailable`, then occupation | no ON | none | off |
| 7 | Sensor outage, occupation, `turn_off` | as 5 | Sensor `unavailable`, then occupation | ON (decided) | `turn_on` | on |
| 8 | Sensor outage, occupation, `dark_on_bright_off` | as 4 | Sensor `unavailable`, then occupation | no ON | none | off |
| 9 | Sensor recovery | as 6 | Valid value in the band, no earlier DARK/BRIGHT | no decision from the band alone | none | unchanged |
| 10 | Exact lower limit | as 1 | Value equal to `turn_on_below` | DARK | per mode | per mode |
| 11 | Exact upper limit | as 1 | Value equal to `turn_off_above` | BRIGHT | per mode | per mode |
| 12 | Zero lux | as 1 | 0 lx | DARK (valid reading) | per mode | per mode |
| 13 | Manual override | group on | Physical switch off while occupied | override set, no automatic command until the next occupation | none | off |
| 14 | Physical switch on while occupied | override active | Switch on | no automatic OFF is derived | none | on |
| 15 | External automation | automation switches the group | External command | override, no counter-command | none | as set externally |
| 16 | Blocker (sleep) | blocker active | Occupation | no ON; blocker OFF per rule | `turn_off` if on | off |
| 17 | ALL-OFF on clear | area occupied, then clear | Vacancy | one OFF from the ALL group | `turn_off` on the ALL group | off |
| 18 | Shared lamp (two areas) | lamp in two area groups | Save or reload | rejected on save; on reload diagnosed, no command | none | unchanged |
| 19 | Ungrouped lamp | lamp in no group | Occupation | no automatic command | none | manual only |
| 20 | Migrated 1.6.18 configuration without Lux limits | legacy `dark_entity` | Start | repair shown, no invented limits | none | off |
| 21 | No brightness source | no sensor, no global lux | Occupation, `require_dark` | no ON, repair shown | none | off |
| 22 | Global sensor only | no area sensor, global lux | Occupation while dark | ON | `turn_on` | on |
| 23 | Configured area sensor unavailable | area sensor set, global present | Area sensor `unavailable` | UNKNOWN, no fallback to global | none | unchanged |
| 24 | Meta-Area brightness | children with a numeric source | One child dark | Meta-Area DARK in the dashboard | none (no Meta light command) | unchanged |
| 25 | Meta-Area with a child without source | one child without source | Others bright | Meta-Area UNKNOWN (intended), shown as unknown | none | unchanged |
| 26 | Meta-Area events | as 24 | Child transition | `dark_started` / `dark_ended` once per Meta-Area | none | unchanged |
| 27 | Restart and reload | all cases above | Reload integration | same classification, no duplicate commands | none | unchanged |
| 28 | Dashboard counts | as 24, 25 | – | DARK and BRIGHT as classified; UNKNOWN not counted as BRIGHT | none | – |
| 29 | Public threshold entity | aggregation threshold set | Crosses the threshold | entity reacts on its own; light control unaffected | none from it | unchanged |
| 30 | Retained features | Light feature disabled, limits kept | Feature re-enabled | limits restored unchanged | none | – |

## Environment to record

- Home Assistant version and HAOS version.
- Adaptive Areas version (`1.7.0-rc.3`), and the commit used.
- The area used for the accent group, its illuminance source, the Lux limits and the brightness mode.
- Whether an external automation or a physical switch is involved.

## Backup and rollback

- Take a full backup before the installation.
- Export the Adaptive Areas configuration (Diagnostics) before and after.
- Rollback: restore the backup, or install `1.7.0-rc.2` and restore the configuration. Do not edit stored configuration by hand.

## Not covered by this plan

- Native behaviour of third-party lamps beyond the service response.
- Real radio and sensor noise beyond the observed outages.
- Long-term stability over days.
