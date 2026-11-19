---
name: home-assistant
description: >-
  Home Assistant Integration patterns, async practices, and component architecture for Adaptive Areas.
  Use when modifying core setup, base entity handling, or integration logic.
---

# Home Assistant Integration Guidelines

Instructions and guidelines for developing within the Home Assistant architecture in `adaptive-areas`.

## Repository Structure Overview

```text
adaptive-areas/
├── custom_components/adaptive_areas/
│   ├── __init__.py           # Integration entry point & lifecycle (setup, unload, reload, migrate)
│   ├── const.py              # Central constants, domain keys, options, defaults & schemas
│   ├── config_flow.py        # Config flow & Options flow UI handlers and category submenus
│   ├── diagnostics.py        # Redacted diagnostics exporter
│   ├── repairs.py            # Issue registry & diagnostic repair flows
│   ├── system_health.py      # HA System Health integration hooks
│   ├── services.py           # Custom service definitions & handlers (e.g. apply_light_profile)
│   ├── services.yaml         # Service metadata & UI descriptions
│   ├── util.py               # Shared utility functions
│   ├── light.py              # Adaptive lighting control platform & profile interpolation
│   ├── number.py             # Number platform implementations (thresholds & setpoints)
│   ├── cover.py              # Shading / cover platform implementations
│   ├── fan.py                # Ventilation & circulation fan control platform
│   ├── threshold.py          # Threshold helper entities & threshold logic
│   ├── base/                 # Core domain engines, aggregators & base entity classes
│   │   ├── adaptive.py       # Core adaptive engine logic & calculation routines
│   │   └── entities.py       # Core base entity abstractions
│   ├── helpers/              # Domain calculation, state tracking & diagnostics helpers
│   │   ├── area.py           # Area state management & entity tracking
│   │   ├── decision_trace.py # Tracing & debug context for decision auditability
│   │   ├── diagnostics.py    # Helper diagnostics & telemetry summaries
│   │   ├── environment.py    # Climate, WAQI, dew point & environment sensor aggregation
│   │   ├── light_groups.py   # Light group calculation & profile helpers
│   │   ├── room_usage.py     # Room utilization & cleaning tracker helpers
│   │   └── timer.py          # Timer & delay management
│   ├── sensor/               # Sensor platform implementations
│   │   ├── __init__.py       # Aggregates, Meta-Aggregates, Room Usage, Diagnostics sensors
│   │   └── base.py           # Base sensor entity class
│   ├── binary_sensor/        # Binary sensor platform implementations
│   │   ├── __init__.py       # Platform setup & registration
│   │   ├── base.py           # Base binary sensor class
│   │   ├── ble_tracker.py    # BLE presence tracker monitor entity
│   │   ├── presence.py       # Area presence sensing & combined occupancy
│   │   └── wasp_in_a_box.py  # Wasp-in-a-box algorithm entity
│   ├── switch/               # Area feature control switches
│   │   ├── __init__.py       # Platform setup & switch group entities
│   │   ├── base.py           # Base switch entity class
│   │   ├── climate_control.py# Climate automation toggle switch
│   │   ├── fan_control.py    # Fan automation toggle switch
│   │   ├── media_player_control.py # Media player automation toggle switch
│   │   └── presence_hold.py # Presence hold toggle switch
│   ├── media_player/         # Area media player management
│   │   └── area_aware_media_player.py # Area-aware media player entity
│   ├── brand/                # Integration branding assets
│   └── translations/         # Localization files (en, de, es, fr, nl-NL, pl, pt-BR, sv, ta)
├── tests/                    # Pytest test suite covering all domains and features
└── docs/                     # Documentation source
```

## Architecture & Core Entry Points

* **Setup & Entry Lifecycle:** [`custom_components/adaptive_areas/__init__.py`](custom_components/adaptive_areas/__init__.py)
* **Constants & Domain Schema:** [`custom_components/adaptive_areas/const.py`](custom_components/adaptive_areas/const.py)
* **Base Domain Engines & Aggregators:** [`custom_components/adaptive_areas/base/`](custom_components/adaptive_areas/base/)
* **Domain Calculation Helpers:** [`custom_components/adaptive_areas/helpers/`](custom_components/adaptive_areas/helpers/)

## Asynchronous Practices & Resource Safety

* **Async Conventions:** Strictly follow HA `async` conventions (`async_setup_entry`, `async_unload_entry`, `async_add_entities`).
* **Cleanup:** Ensure proper listener removal (`async_on_unload`, `async_dispatcher_connect`) and timer cancellation during unload/reload to prevent memory or state listener leaks.
* **State handling:** Gracefully handle `None`, `STATE_UNKNOWN`, and `STATE_UNAVAILABLE` states for all entity inputs. Avoid assuming numerical values without safe conversion functions.
* **Privacy Safety:** Diagnostics and trace exports must redact personal identifiers, hardware IDs, tokens, and sensitive data.

## Modern Home Assistant Core Standards

* **Modern Naming & Localizations:** Always set `_attr_has_entity_name = True` on base entities and rely on `translation_key` for UI naming instead of hardcoding name strings.
* **Typed Data & Entry Lifecycle:** Use typed `ConfigEntry` storage (or `runtime_data`) for runtime state and entry management.
* **Entity Descriptions:** Prefer `EntityDescription` dataclasses (`SensorEntityDescription`, `BinarySensorEntityDescription`, `NumberEntityDescription`, etc.) for platform entity definitions.
* **Device Registry:** Associate entities with proper `DeviceInfo` (`identifiers={(DOMAIN, entry.entry_id)}`, `name`, `manufacturer`, `model`).
* **Issue Registry & Repairs:** Use `async_create_issue` / `async_delete_issue` in [`repairs.py`](custom_components/adaptive_areas/repairs.py) to inform users of deprecations or misconfigurations gracefully.
* **Strict Type Annotations:** Maintain strict Python type hints (`py.typed` compliance) across all modules in `custom_components/adaptive_areas/`.
