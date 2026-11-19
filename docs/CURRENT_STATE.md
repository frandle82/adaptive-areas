# Current state

## Stable facts

- Integration version: read `custom_components/adaptive_areas/manifest.json`; do not copy it here.
- Test baseline: the full suite passes with Home Assistant 2026.8.1 and with the CI-pinned Home Assistant 2026.10.4 (see [TESTING.md](TESTING.md)).

## Implementation direction

The Dashboard 2.0 panel covers area configuration, light control (policy and runtime status, light groups) and climate control (feature toggle, climate configuration, runtime status). The panel has read endpoints and administrator-gated configuration mutation endpoints.

Dashboard 2.0 Phase E (see [ROADMAP.md](ROADMAP.md)) is implemented in the panel:

- Settings tab renders and saves the two global options (weather entity, global brightness sensor) through the existing WebSocket commands.
- The Area editor and light-group helpers are restored; saving an Area keeps light, light-group and climate configuration.
- The overview shows occupancy, configured light and climate activation, and sleep and extended state, from backend values only.
- Thermostat selection shows friendly names with the entity id as fallback.
- Visible panel texts use the existing English/German panel dictionary.
- Save rule for global options: unchanged stored entity ids are accepted even when unavailable; new or changed ids are fully validated; explicit `null` removes a field; unsent fields are kept; a rejected update persists nothing.
- Light and Climate tabs and the Settings tab are administrator-only, as before.

## Known risks

- Home Assistant 2026.11.x has no matching test harness release. Without a compatible harness, pip falls back to an outdated harness, and test collection fails. CI therefore pins 2026.10.4 until a harness supports 2026.11.x.
- Browser review was run only against a local harness that loads the real panel script with mocked WebSocket responses. It is not a visual review in a real Home Assistant instance; that review is still pending. The harness does not run backend validation.
- Unsaved climate drafts are discarded when the selected area changes (accepted).

## Known documentation discrepancy

The README describes the dashboard as read-only, but the current WebSocket API includes administrator-gated updates for global and area configuration plus area creation and deletion. This document records the discrepancy; it does not change user-facing documentation or runtime behavior.

## Unverified items

A failing Hassfest validation run on an unrecognised commit SHA (`d3ee6a4`, not present locally) has not been analysed. No deployed Home Assistant instance was inspected.
