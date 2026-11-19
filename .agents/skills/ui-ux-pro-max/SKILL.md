---
name: ui-ux-pro-max
description: >-
  Perform the final responsive, accessibility, and usability review of an Adaptive Areas dashboard change.
  Use after frontend implementation and for the UI/UX portion of dashboard bugfixes.
---

# Adaptive Areas UI/UX Review

Review the delivered dashboard as users encounter it across supported viewport and theme conditions.

## Checklist

- Desktop (~1440 px), tablet (~768 px), and mobile (~390 px) avoid forced horizontal scrolling.
- Light mode, dark mode, and custom themes retain contrast and readable hierarchy.
- Keyboard navigation and focus are usable; status is communicated by text/icons as well as color.
- Long friendly names, long technical identifiers, empty states, error states, and loading states remain legible.
- A user can understand an area’s state within five seconds; technical details are subordinate and duplicate facts are absent.

## Verification

Use `playwright-interactive` against a suitable Home Assistant instance when available. Otherwise state explicitly which visual checks could not be exercised.
