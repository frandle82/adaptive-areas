---
name: knowledge
description: >-
  Local knowledge retrieval, documentation management, and context integration strictly from the .agents folder (.agents/knowledge/).
  Use when analyzing requirements, planning features, researching architecture decisions, or checking project specifications without external MCP tools.
---

# Local Knowledge & Context Management

Guidelines for retrieving, referencing, and maintaining domain knowledge, architectural decisions, and specifications strictly within the `.agents/` folder.

## Purpose & Mindset

All project-specific knowledge, architectural decisions (ADRs), specifications, domain notes, and edge-case documentations are stored directly in `.agents/knowledge/`.
**No external tools, remote services, or MCP servers are queried.** The local files in `.agents/` are the authoritative knowledge base for coding agents.

> **Principle:** Always consult `.agents/knowledge/` before proposing new features, refactorings, or architectural changes. Keep the knowledge base updated when new decisions or patterns are established.

## Knowledge Repository Structure

The `.agents/knowledge/` directory is organized into focused domains:

```text
.agents/knowledge/
├── README.md               # Overview and index of project knowledge
├── architecture/           # System design, data flow, entity models, lifecycle
├── specs/                  # Feature specifications, option parameters, thresholds
├── adrs/                   # Architectural Decision Records (ADRs)
└── notes/                  # Domain notes, edge cases, known caveats, testing tips
```

## Retrieval Strategy

When tasked with feature implementation, bug fixing, or architectural analysis:

1. **Locate Relevant Documents:**
   - For architectural guidelines: inspect `.agents/knowledge/architecture/`
   - For feature definitions & options: inspect `.agents/knowledge/specs/`
   - For historical decisions and trade-offs: inspect `.agents/knowledge/adrs/`
   - For domain edge cases or testing insights: inspect `.agents/knowledge/notes/`

2. **Grep / Search Locally:**
   - Search across `.agents/knowledge/` using targeted domain terms (e.g., `presence`, `wasp_in_a_box`, `ble_tracker`, `lighting`, `aggregates`, `climate`).

3. **Grounding in Code:**
   - Treat `.agents/knowledge/` as the architectural intent and background context, cross-referenced with actual Python implementation (`custom_components/adaptive_areas/`) and unit tests (`tests/`).

## Maintaining & Extending Knowledge

When requirements are refined (e.g., via `grill-me`), new decisions are reached, or complex bug investigations yield new insights:

1. **Update Existing Specs:** Reflect agreed changes in `.agents/knowledge/specs/` or `.agents/knowledge/architecture/`.
2. **Record ADRs:** If an architectural choice is made (e.g. state management change, migration strategy, sensor priority), document it as an ADR under `.agents/knowledge/adrs/NNN-<title>.md`.
3. **No External Calls:** Never attempt to call external MCP tools or remote note servers. Everything stays self-contained in `.agents/`.
