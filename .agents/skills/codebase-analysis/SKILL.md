---
name: codebase-analysis
description: >-
  Analyze the Adaptive Areas architecture before a new dashboard phase or major dashboard redesign.
  Use to establish runtime ownership, data flow, lifecycle, entities, and public versus internal data.
---

# Adaptive Areas Codebase Analysis

Establish the integration facts before making dashboard decisions. This skill produces analysis only; it does not add runtime capabilities.

## When to Trigger

Use first for a new dashboard phase, new main tab, or substantial redesign. For a narrow bugfix, inspect only the affected domain together with `adaptive-areas-dashboard-context`.

## Workflow

1. Read `custom_components/adaptive_areas/`, `tests/`, ConfigFlow and OptionsFlow entry points, and applicable `.agents/knowledge/` notes.
2. Map AdaptiveArea and MetaArea runtime objects, ConfigEntry ownership, setup/unload lifecycle, events, entities, registries, services, repairs, WebSocket commands, and the dashboard mapper.
3. Cover presence, thresholds, lights, aggregates, environment, room usage, and cleaning when available.
4. Report central runtime objects, data owners, data flow, lifecycle, public entities, internal data, MetaArea differences, and feature dependencies.
5. Separate confirmed facts from missing capabilities. Never infer a runtime field solely because the dashboard would benefit from it.

## Required Output

Create a concise data inventory: `Feature | Runtime source | Public entities | Important attributes | User relevance | Dashboard level`.
Flag runtime data not used by the dashboard and dashboard fields not supplied reliably by runtime data.

## Guardrails

- Python runtime remains the source of truth; WebSocket is transport; frontend is presentation.
- Do not create components directly from raw runtime objects.
- Do not implement a feature merely because the analysis reveals it is absent.
