---
name: frontend-design
description: >-
  Refine Adaptive Areas dashboard presentation after analysis, data filtering, information architecture, and layout are settled.
  Use for typography, spacing, icons, visual weight, and presentational state handling only.
---

# Dashboard Frontend Design

Polish presentation without expanding domain scope or moving business decisions into the browser.

## Preconditions

Use only after `codebase-analysis`, `adaptive-areas-dashboard-context`, `information-architect`, `dashboard-ui-structure`, and `homeassistant-dashboard-designer` have established the design input.

## Workflow

1. Refine typography, spacing, icon usage, cards, detail affordances, and status emphasis using the approved hierarchy.
2. Keep error output controlled: identify the failing UI action and safe error code, never expose internal objects or sensitive values.
3. Verify long friendly names, long entity IDs in secondary views, empty states, loading states, and error states.
4. Do not alter DTO meaning or add frontend interpretations of Adaptive Areas runtime data.
