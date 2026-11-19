---
name: dashboard-ui-structure
description: >-
  Design Adaptive Areas dashboard layout, information density, cards, sections, and responsive structure.
  Use after information architecture and before Home Assistant visual implementation.
---

# Dashboard UI Structure

Turn the agreed information hierarchy into a sparse, readable layout without changing domain meaning.

## Workflow

1. Establish visual priority: area name, domain state, important measurements, warnings, feature details, technical sources.
2. Use a compact grid of area cards and group related values; avoid nested container stacks and card-per-field layouts.
3. Keep one card per area concept where possible. Do not show threshold, aggregate, and area state as equal duplicate status cards.
4. Specify layouts for approximately 1440 px, 768 px, and 390 px without horizontal page scrolling.
5. Ensure labels, icons, and text communicate status; color is supplementary only.

## Guardrails

- Friendly names outrank entity IDs.
- Hide unavailable feature sections rather than reserving blank space.
- Preserve a compact representation for feature-light areas.
