---
name: adaptive-areas-dashboard-context
description: >-
  Classify Adaptive Areas dashboard data before any UI decision or dashboard bugfix.
  Use to filter presentation DTOs into primary, detail, diagnostic, and internal information.
---

# Adaptive Areas Dashboard Context

Classify available data before designing or changing a dashboard. Runtime values must not become UI components without this filter.

## When to Trigger

Use for every dashboard task. For bugfixes, combine it with the affected feature and a UI/UX review; for a new phase, follow the full dashboard skill chain.

## Classification

For every candidate field ask: does a normal user need it now, during analysis, or only a developer? Classify it exactly once:

- `PRIMARY`: immediate area state — name/type, occupied or clear, dark or bright, current brightness, active lights, core environment state, warnings.
- `DETAIL`: feature context — presence sources, dark source, threshold, light groups, aggregates, environment details, room usage, cleaning.
- `DIAGNOSTIC`: unavailable/unknown/missing sources, empty aggregates, inconsistent brightness, invalid configuration, runtime warnings.
- `INTERNAL`: object representations, raw registry entries, listener/callback/debounce state, or IDs without diagnostic value. Do not transfer or render by default.

## Workflow

1. Inventory runtime values and classify each field.
2. Deduplicate equivalent domain facts: show one primary state and put its source or rationale in details.
3. Treat MetaAreas independently: show their aggregate domain state first; child-area sources are details.
4. Model feature absence explicitly. Areas with fewer features stay compact; never force empty placeholders.
5. Define filtered presentation DTOs in Python. Send only fields the frontend needs.

## Guardrails

- Frontend must not decide sensor relevance, aggregate meaning, or domain-state semantics.
- Entity IDs and source counts are secondary diagnostic data, never overview content.
- Missing data is a reported missing capability, not permission to invent runtime logic.
