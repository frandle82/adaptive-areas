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
- WebSocket commands registered by `websocket.py`, including overview/detail retrieval, runtime status, area/global configuration updates, area CRUD, and subscriptions.
- The administrator-only custom panel is registered by `panel.py` and serves `frontend/adaptive-areas-panel.js`.

## Compatibility boundaries

Entity IDs, unique IDs, Config Entry options, translations, and user automations are compatibility-sensitive. Changes to persisted configuration require an explicit migration path and tests. Inputs from Home Assistant may be `None`, `unknown`, or `unavailable` and must remain safely handled.
