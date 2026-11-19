---
name: homeassistant-dashboard-designer
description: >-
  Apply Home Assistant-native visual and panel conventions to an Adaptive Areas dashboard.
  Use after layout design when implementing or reviewing dashboard presentation.
---

# Home Assistant Dashboard Designer

Make the custom panel feel native to Home Assistant while preserving the established runtime and WebSocket boundaries.

## Workflow

1. Prefer HA CSS variables, typography, spacing, theme colors, `ha-card`, `ha-alert`, and `ha-icon`.
2. Verify light mode, dark mode, and custom themes without hard-coded primary colors where a HA variable exists.
3. Use theme-aware states and explicit text/icon labels for occupied, clear, bright, dark, unavailable, and warning.
4. Preserve the architecture: runtime → presentation mapper/DTO → WebSocket → panel.

## Guardrails

- Do not create an unrelated design system.
- Do not encode Adaptive Areas business rules in JavaScript.
- Keep error, loading, and empty states controlled and safe to render.
