---
name: playwright-interactive
description: >-
  Interactive end-to-end browser testing, UI workflow verification, and visual regression inspection.
  Use when validating Home Assistant frontend flows, Config/Options Flow UI dialogs, or web views.
---

# Interactive Web & UI Testing (playwright-interactive)

Guidelines for driving interactive browser sessions, executing end-to-end UI verification, and conducting visual validation for Home Assistant interfaces and web components.

## Purpose

The `playwright-interactive` skill empowers the agent to interact directly with a real web browser to:
1. Walk through and validate multi-step setup wizards (Config Flow) and configuration menus (Options Flow).
2. Click through Lovelace dashboards, area cards, and control toggles.
3. Visually verify layout responsiveness, dark mode, icons, and state animations.
4. Catch frontend JavaScript errors, unrendered DOM elements, and broken navigation.

## When to Trigger

* After modifying Config Flow or Options Flow steps in [`custom_components/adaptive_areas/config_flow.py`](custom_components/adaptive_areas/config_flow.py).
* When verifying translation strings and layout formatting in actual Home Assistant dialogs.
* When testing custom Lovelace cards or UI integrations associated with Adaptive Areas.
* When verifying that UI controls trigger expected backend state changes without console errors.

## Interaction Tooling

Tool names differ per agent. Use the browser automation tool your agent provides. Antigravity uses `browser_subagent`; Claude Code uses its available browser tools (for example a Chrome or built-in browser integration). If no browser tool is available, state explicitly which checks were not run. Do not claim a UI check passed.

Antigravity (`browser_subagent`) works as follows:
* The subagent opens a live Chromium browser session.
* It navigates, clicks, types, inspects the DOM, and captures screenshots.
* All browser interactions are automatically recorded and saved as WebP video artifacts.

### Key Rules for Browser Subagents
1. **Concrete Scope:** Provide a tightly defined `Task` prompt with exact URLs, elements to click, and specific values to input.
2. **Explicit Stop Conditions:** Clearly define what signals completion (e.g. "Stop when the success dialog appears or an error message is rendered").
3. **Descriptive Names:** Set `TaskName` (e.g. `Test Config Flow Options`) and `RecordingName` (e.g. `config_flow_test`).
4. **Post-Execution Inspection:** Read the returned DOM summary or screenshot artifact to confirm UI state.

## Step-by-Step UI Verification Workflow

### Phase 1: Preparation
* Ensure local Home Assistant test instance or mock web server is running and reachable (e.g. `http://localhost:8123`).
* Identify the exact target selectors, button labels, and input fields to be exercised.

### Phase 2: Launching the Interactive Test Session
Invoke `browser_subagent` with targeted instructions:

```text
browser_subagent:
  TaskName: "Verify Adaptive Areas Options Flow"
  TaskSummary: "Navigate to Adaptive Areas integration settings and verify lighting options subpage"
  RecordingName: "options_flow_lighting"
  Task: |
    1. Navigate to http://localhost:8123/config/integrations.
    2. Find the 'Adaptive Areas' integration card and click 'Configure'.
    3. In the options menu, select 'Lighting Settings' and click Next.
    4. Verify that all selector fields (Light profiles, transition time, sleep brightness) render correctly.
    5. Take a screenshot of the form.
    6. Check the browser console for JavaScript errors.
    7. Click 'Cancel' or 'Submit' to exit gracefully.
    8. Return a report detailing rendered fields, errors found, and confirmation of visual integrity.
```

### Phase 3: Visual & DOM Verification Checklist
* [ ] **Field Labels:** Are all labels properly translated (no missing string placeholders like `component.adaptive_areas.options.step...`)?
* [ ] **Selectors & Inputs:** Do dropdowns, entity selectors, and number sliders display valid choices and bounds?
* [ ] **Form Validation:** Do required fields show appropriate error banners when submitted empty or with invalid data?
* [ ] **Console Hygiene:** No uncaught JavaScript exceptions or failed network requests in the console logs.
* [ ] **Responsive Rendering:** Elements do not overlap, text is not truncated awkwardly.

### Phase 4: Reporting
Present a structured report in German for Andreas:
* Executed browser workflow.
* Screenshots or artifact recording links.
* Any visual defects, missing translation keys, or console warnings detected.
