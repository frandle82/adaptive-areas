---
name: grill-me
description: >-
  Intensive requirements elicitation and edge case analysis before writing any code.
  Use when planning new features, refactorings, architectural changes, or clarifying ambiguous requests.
---

# Requirements Elicitation & Clarification (Grill-Me)

Guidelines and questioning framework for thoroughly probing requirements, exposing edge cases, and aligning on design decisions *before* writing code.

## Purpose & Mindset

The goal of `grill-me` is to prevent speculative or misplaced code generation by intensely challenging assumptions, identifying hidden edge cases, and validating design constraints up front.

> **Principle:** Never write code on ambiguous, underspecified, or high-risk requirements. Grill the developer/user with sharp, structured questions first.

## When to Trigger

Activate `grill-me` whenever:
* A new feature or sub-platform is requested (e.g., adding a new sensor aggregate, new automation mode, new platform switch).
* The request is ambiguous, open-ended, or lacks concrete acceptance criteria.
* Changes affect core state machines, schema migrations, entity IDs, or breaking backwards compatibility.
* Multiple architectural trade-offs exist (e.g., where state should live, coordinator vs. event dispatcher, poll vs. push).

## Questioning Dimensions

Walk through the following 5 dimensions systematically:

### 1. Scope & Functional Boundaries
* **Exact Goal:** What is the precise user-facing outcome?
* **Non-Goals:** What is explicitly *out of scope* for this change?
* **Trigger Conditions:** Under which exact states, events, or transitions should the feature trigger or deactivate?

### 2. Home Assistant Architecture & Integration Model
* **Entity vs. Helper:** Should this be an entity (`sensor`, `binary_sensor`, `switch`, `number`), an options flow configuration, an internal helper, or a service?
* **State & Lifecycle:** How is state stored across HA restarts? Is it persisted in `ConfigEntry.options`, restored via `RestoreEntity`, or re-aggregated dynamically?
* **Hierarchy & Multi-Area:** How does this behave in nested/meta areas? Does it aggregate parent-to-child or child-to-parent?
* **Async Safety:** Are there blocking calls, third-party libraries, or high-frequency event loops involved?

### 3. Edge Cases & Resilience
* **Unavailable / Unknown States:** What happens if an input sensor is `STATE_UNAVAILABLE`, `STATE_UNKNOWN`, `None`, or sending malformed data?
* **Area Reload & Unload:** What happens when an area is reloaded while an automation/timer is active? Are listeners properly detached?
* **Concurrent Events:** Can race conditions occur between multiple state changes (e.g., presence detection vs. manual switch override)?
* **Boundary Values:** Zero values, negative values, extreme temperatures/lux levels, timeouts?

### 4. Data Storage, Backward Compatibility & Translations
* **Config/Options Flow Impact:** Does this require new fields in `config_flow.py`? If so, what are default values?
* **Schema Migration:** Does this change the structure of `entry.data` or `entry.options`? If yes, a migration in `custom_components/adaptive_areas/__init__.py` (see [`migrations`](.agents/skills/migrations/SKILL.md)) is strictly required.
* **Localization:** Are all UI strings, names, and option labels localized in `custom_components/adaptive_areas/translations/` (`en.json`, `de.json`, etc.)?

### 5. Testing & Verification Criteria
* **Test Matrix:** Which test files under `tests/` must be extended or created?
* **Regression Protection:** What existing behavior must definitely *not* change?
* **Acceptance Gates:** What exact pytest commands or integration scenarios determine that the change is finished?

## Execution Workflow

1. **Analyze Prompt & Context Retrieval:** Read the user request against the existing architecture and determine gaps or ambiguities. Retrieve and check existing specifications, architectural decisions, and notes stored in `.agents/knowledge/` (see [`knowledge`](.agents/skills/knowledge/SKILL.md)) to inform the analysis. Do not query external MCP tools.
2. **Formulate Focused Interview:** Use the `ask_question` tool (or structured conversational prompts) with:
   - Clear context of why the question matters.
   - Recommended option listed first with `(Recommended)`.
   - Concrete options rather than vague open questions where possible.
3. **Synthesize Specification:** Summarize the agreed specification and acceptance criteria.
4. **Approval Gate:** Only begin implementation after the user confirms the plan and requirements.
