---
name: information-architect
description: >-
  Define the user-task-oriented information hierarchy for a new Adaptive Areas dashboard phase or redesign.
  Use after data classification and before dashboard layout or frontend work.
---

# Dashboard Information Architecture

Organize domain information around user questions, never Python modules or registry types.

## Workflow

1. Start with `Overview`, `Areas`, `Area Detail`, and `Diagnostics`; Decision Trace and Configuration remain future optional destinations.
2. Make the overview answer within seconds: which rooms are occupied, dark, lit, or have a problem.
3. Group area details by Status, Presence, Brightness, Lights, Environment, Usage, Aggregates, and Sources, omitting empty sections.
4. Apply progressive disclosure: show domain status first, feature rationale next, technical sources last.
5. Record a structure overview before implementation, including KPIs, cards, detail sections, and diagnostics groups.

## Guardrails

- Primary navigation uses terms such as Status, Presence, Brightness, Lights, Climate, Usage, and Diagnostics.
- Do not expose Binary Sensor, Manager, Registry, or implementation module names as primary navigation.
- MetaArea details must not assume normal-area fields exist.
