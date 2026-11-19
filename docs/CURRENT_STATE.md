# Current state

## Stable facts

- Integration version: read `custom_components/adaptive_areas/manifest.json`; do not copy it here.
- Test baseline: the full suite in the project's `ha-stable` tox environment passes with Home Assistant 2026.8.1 (see [TESTING.md](TESTING.md)).

## Implementation direction

The Dashboard 2.0 panel covers area configuration, light control (policy and runtime status, light groups) and climate control (feature toggle, climate configuration, runtime status). The panel has read endpoints and administrator-gated configuration mutation endpoints.

## Known risks

- Installing the latest Home Assistant stable release (2026.11.2 on 2026-11-19) breaks test collection in the tox environment through the `pytest-timeout` plugin (`ast.Str`, `distutils`). CI has no fixed Home Assistant pin, so this may affect CI as well. Status unverified.
- Browser-based visual review of the dashboard has not been run as part of the automated suite.
- Unsaved climate drafts are discarded when the selected area changes (accepted).

## Known documentation discrepancy

The README describes the dashboard as read-only, but the current WebSocket API includes administrator-gated updates for global and area configuration plus area creation and deletion. This document records the discrepancy; it does not change user-facing documentation or runtime behavior.

## Unverified items

A failing Hassfest validation run on an unrecognised commit SHA (`d3ee6a4`, not present locally) has not been analysed. No deployed Home Assistant instance was inspected.
