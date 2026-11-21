# Non-admin consumer review (step 3, corrected after reviews B01–B11 and R01–R05)

Scope: what a non-administrator can receive from the backend and what the panel does with it. Evidence: fixtures from the real backend handlers (`tests/frontend/fixtures`), backend tests (`tests/test_dashboard_permissions.py`) and browser checks (`tests/frontend/run.mjs`).

## 1. Backend responses for non-administrators

| Command | Access | Non-admin content | Redaction |
|---|---|---|---|
| `get_overview` | all users | area summary: id, name, type, occupied, active states, presence state, brightness state and illuminance, warning count and details, light counts (`on`, `total`), environment, room usage, cleaning, source counts, enabled feature names | no `controls`; sources as counts; light group names and counts removed; `warning_details` are counts only; `environment` carries the values only (`temperature`, `humidity`, `comfort`, `air_quality`, `mould_risk`, `notices`), not the generated entity's fields and not `used_sensors` (fixed 2026-11-20; before, both reached non-administrators); `floor_id`, `floor_name` and, for Meta-Areas, `members` (IDs of physical Areas, no entity IDs) are shared with all users; `cleaning` and `room_usage` values are shared with all users when the feature is enabled |
| `get_area` | all users | summary plus presence source counts, aggregates without entity IDs (counts of sources), environment, source counts, brightness state | no `controls`, no `light_groups`, no `dark_source`, no entity IDs; `environment` as in `get_overview` |
| `subscribe_updates` | all users | area summary events; data-free `{"areas_changed": true}` when the set of loaded Areas changes | same redaction as `get_overview`; the role is read from the connection for every pushed event, so a user who loses administrator rights on a live connection receives redacted summaries from the next event on; the structural event carries no data |
| `get_area_configuration`, `get_global_configuration`, `get_light_runtime_status`, `get_climate_runtime_status`, `get_diagnostics`, `get_decision_trace`, `create_area`, `update_area`, `delete_area`, `update_global_configuration` | administrator only (`require_admin`) | not returned | rejected by the backend |

Verified by fixtures: no entity-like string value (`binary_sensor.`, `light.`, `sensor.`, `weather.` and others) occurs in any non-admin response. The admin responses are the only ones that contain entity IDs.

Verified by tests: non-admin summaries and details carry no `controls`, no `light_groups`, no `dark_source`; light summaries carry `on` and `total` only; subscription events are redacted; `get_decision_trace`, `get_diagnostics` and the configuration commands reject non-admin connections.

## 2. Panel consumers for non-administrators

- Overview: name, occupied, active states, enabled features (activation text for light and climate), presence state, warning count and warning details, light counts, environment and room usage values, cleaning values, aggregated source counts. None of these carries an entity ID.
- Area cards and area detail: the same fields. The detail view reads only aggregated presence and source counts.
- Administrative views (areas, settings, light and climate configuration, trace, diagnostics, area editor) are not rendered for non-administrators. The navigation hides them, and the render path falls back to the dashboard if such a view is requested directly. Direct requests are rejected by the backend.

## 3. Error texts

- Non-administrators see only panel-level texts (`error`, `loading`, `connectionLost`, `offlineNotice`). The panel shows no backend message to them.
- Administrative error texts (validation messages from `update_area` and `update_global_configuration`, `error.message` of administrative calls) are shown only inside administrative forms.
- The backend message for an unknown area (`Adaptive Area not found`) contains no identifier.

## 4. Role and session changes

On a role change to non-administrator the panel discards: area configuration, global settings and their draft, global and Area conflict state, the Area draft, decision trace, diagnostics, light and climate runtime data, administrative error values, request flags and request ownership of administrative loads and saves, the light, climate and trace selections, and the open editor. In-flight responses are discarded by the shared guard (`_guard`/`_isCurrent`), which checks session and role after every `await` and in `catch`. Verified by browser checks S13, S14, S22, B02c, B02d and B03; the safety-relevant checks were also confirmed to fail against the pre-fix implementation (see `docs/HANDOVER.md`).

Subscription callbacks are bound to a subscription generation and to the role at subscription time. After a role change, a replaced subscription or the removal of the panel, an old callback processes nothing: no area summary, no `areas_changed` reload, no administrative request (browser checks R01a–d, called explicitly after the unsubscription). Late responses of the global settings load, of light and climate configuration saves and of Area saves after a role change restore nothing (R02a, R04b, R05c). Backend: `tests/test_dashboard_subscription.py::test_subscription_reads_the_role_for_every_event`.

## 5. Limits that remain

- The review covers the fields and commands listed above. It is not a formal audit of third-party integrations that read the same backend commands.
- The backend has no atomic conflict detection for configuration writes. The panel compares the current server state immediately before each write; a change between that check and the write is not detected (see `docs/HANDOVER.md`).
- Light group names and per-group counts are administrator detail. Light counts (`on`, `total`) remain visible to non-administrators, as before.
