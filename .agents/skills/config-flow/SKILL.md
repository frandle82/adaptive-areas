---
name: config-flow
description: >-
  Config Flow and Options Flow guidelines for Adaptive Areas UI configuration.
  Use when adding or updating setup steps, options flow, or user selectors.
---

# Config Flow & Options Flow Guidelines

Instructions for implementing UI configuration, options flows, and user inputs for `adaptive-areas`.

## Related Files & Structure

```text
custom_components/adaptive_areas/
├── config_flow.py        # ConfigFlow & OptionsFlowHandler implementations with category submenus
├── const.py              # Configuration option keys, default values, & vol.Schema definitions
└── translations/
    ├── en.json           # Master English UI labels, titles, descriptions & selectors
    ├── de.json           # German UI translations
    └── *.json            # Additional locale translations (es, fr, nl-NL, pl, pt-BR, sv, ta)
```

## Options Flow Submenu Structure

The options flow uses a modular category submenu pattern in `config_flow.py`:

* **`init`**: Category selection menu directing to specific configuration sections.
* **`general`**: Basic area settings, decision tracing toggle, diagnostic flags.
* **`presence`**: Motion/occupancy sensors, wasp-in-a-box contact/door sensors, BLE tracking entities, and presence hold duration.
* **`lighting`**: Light entities, adaptive brightness/CCT profile curves, illuminance sensor, transition duration, daylight elevation offsets.
* **`climate`**: Climate entity assignments, target heating/cooling setpoints, humidity thresholds.
* **`fan`**: Fan entities, air circulation triggers, humidity-based speed control.
* **`cover`**: Shading/cover entities, solar elevation & azimuth thresholds.
* **`media_player`**: Media player entity assignments and area presence auto-pause/resume.
* **`thresholds`**: Custom threshold entities and setpoint definitions.
* **`room_usage`**: Cleaning tracker thresholds, room utilization tracking options.

## Key Code References

* **UI Flow Handlers:** [`custom_components/adaptive_areas/config_flow.py`](custom_components/adaptive_areas/config_flow.py)
* **Option Keys & Schemas:** [`custom_components/adaptive_areas/const.py`](custom_components/adaptive_areas/const.py)
* **Master Translations:** [`custom_components/adaptive_areas/translations/en.json`](custom_components/adaptive_areas/translations/en.json)

## Best Practices & Implementation Rules

* **Schema Parity:** Maintain exact schema consistency between initial setup (`ConfigFlow`) and post-setup options adjustments (`OptionsFlow`).
* **Voluptuous Validation:** Use Home Assistant `voluptuous` schemas and standard HA selectors (`selector.EntitySelector`, `selector.SelectSelector`, `selector.NumberSelector`, etc.) defined in `const.py`.
* **Translation Keys:** Ensure every schema field, step title, section, and error string has corresponding translation keys in both [`en.json`](custom_components/adaptive_areas/translations/en.json) and [`de.json`](custom_components/adaptive_areas/translations/de.json).
* **Input Validation:** Validate user inputs strictly prior to saving to `config_entry.options`.
* **Safe Defaults:** Always provide safe default fallbacks from `const.py` when accessing options dictionary keys (`config_entry.options.get(CONF_KEY, DEFAULT_VALUE)`).
