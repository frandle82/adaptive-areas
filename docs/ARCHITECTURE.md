# Architecture

## Runtime

`custom_components/adaptive_areas/__init__.py` owns Config Entry setup and unload. It creates runtime areas, registers integration services and the custom panel, and forwards platforms to Home Assistant. `AdaptiveArea` and `AdaptiveMetaArea` in `base/adaptive.py` model physical and derived areas. Config Entry data and options are the persisted configuration boundary.

Platform modules create Home Assistant entities for binary sensors, sensors, switches, lights, covers, numbers, fans, and media players. Shared policy and runtime work belongs in `helpers/`; configuration validation and panel updates use `area_config.py` and `config_flow.py`.

## Data flow

```text
Home Assistant registries, entity states, Config Entry options
    -> AdaptiveArea / AdaptiveMetaArea and helper policies
    -> Home Assistant entities, services, diagnostics, repairs
    -> dashboard DTO builders
    -> WebSocket commands
    -> adaptive-areas-panel.js
```

The JavaScript panel is presentation and configuration UI. Python runtime objects remain the source of truth; `dashboard.py` constructs presentation data and `websocket.py` validates and exposes the WebSocket boundary.

## External interfaces

- Config Flow and Options Flow in `config_flow.py`.
- Integration services in `services.py`.
- Diagnostics, repairs, and system health in their respective modules.
- WebSocket commands registered by `websocket.py`, including overview/detail retrieval, runtime status, area/global configuration updates, area CRUD, and subscriptions. `subscribe_updates` pushes area summaries for tracked entities and rebuilds its entity index on the internal dispatcher signal `SIGNAL_AREAS_CHANGED`, which `__init__.py` sends after an entry is set up or unloaded; the client then receives a data-free `{"areas_changed": true}` event. The role (administrator or not) is read for every pushed event, because Home Assistant changes `connection.user` in place when groups change and keeps the connection open. In the panel, each subscription has its own generation: callbacks of a replaced, closed or role-changed subscription process nothing.
- The administrator-only custom panel is registered by `panel.py` and serves `frontend/adaptive-areas-panel.js`.

## Area identity and lifecycle (GlobalEntry)

- One GlobalEntry holds every logical Area in `options[areas]`; global settings live in `options[global_options]`. Area options such as `reload_on_registry_change` are local to the Area.
- An Area's identity is its stable ID (Home Assistant Area ID, floor ID or Meta type). Its Adaptive Areas device carries the identifier `(adaptive_areas, adaptive_area_device_<area_id>)` and owns the Area's generated entities (`helpers/entity_identity.py`, `helpers/area.py`). Name parts of unique IDs are never an identity. A device-less generated entity belongs to the Area of a legacy single-Area entry, and to no Area in a GlobalEntry.
- Generated entity IDs and unique IDs come from one rule (`generated_ids`). Internal consumers resolve the registered entity ID by unique ID (`resolve_generated_entity_id`), so renamed or suffixed IDs keep working. The light control switch registers itself on its Area while loaded (`area.light_control_switch`) and sends `SIGNAL_LIGHT_CONTROL_CHANGED`; light groups read that object.
- Setup: Areas whose Home Assistant Area or floor is gone are skipped (Repair `missing_area`); devices of Areas no longer configured are removed with their generated entities, unless a device also holds a foreign entity. Platforms clean up only entities the Area owns, compared by unique ID.
- Unload reports a failed platform unload as failed and then keeps the runtime. Area deletion updates the options once; the resulting reload performs the registry cleanup.
- Meta Areas of the GlobalEntry do not reload the entry when one of its Areas loads; children are resolved after all Areas exist and sources refresh on entity registration.

## Compatibility boundaries

Entity IDs, unique IDs, Config Entry options, translations, and user automations are compatibility-sensitive. Changes to persisted configuration require an explicit migration path and tests. Inputs from Home Assistant may be `None`, `unknown`, or `unavailable` and must remain safely handled.
