# Real Home Assistant integration test plan (Phase 6)

Status: **not executed.** No running Home Assistant instance was available for the
review archive. Every item below is open until the steps are run and recorded here.
Harness results (tests/frontend/run.mjs) and pytest results do not count as proof of
runtime compatibility.

## Environment
- Home Assistant 2026.8.0 (minimum declared in hacs.json) and the current release.
- Install the integration as a custom component in a clean configuration directory.
- Record the exact versions in the results table below.

## Checks and expected results
| # | Check | Steps | Expected | Status |
|---|---|---|---|---|
| 1 | Panel registration | Start HA, open the sidebar entry | The panel loads without console errors | not run |
| 2 | Translation contract | Open DevTools, filter `adaptive_areas/get_dashboard_texts` | One request per language, response with `component.adaptive_areas.dashboard.*` keys | not run |
| 3 | English fallback | Switch a user profile to a language without a dashboard file | English texts are shown, no empty labels | not run |
| 4 | Language switch | Change the user language with an open, unsaved editor draft | Draft, focus and open section kept, no write request | not run |
| 5 | Subscriptions | Open and close the panel several times | One `adaptive_areas/subscribe_updates` per panel session, no duplicate subscriptions | not run |
| 6 | Reconnect | Restart HA while the panel is open | Panel shows the connection state, then recovers with fresh data | not run |
| 7 | Admin rights | Log in as admin, then as a non-admin | Admin sees Area management and Trace; non-admin sees the monitoring views only | not run |
| 8 | Direct WebSocket call | Non-admin calls an admin command from the browser console | Rejected with `unauthorized` | not run |
| 9 | Browser zoom 200 % | Set browser zoom to 200 % at 1280 px and 320 px | Editor usable, Save and Cancel reachable, no clipped labels | not run |
| 10 | Real theme contrast | Light and dark HA themes, measure text contrast of the main views | WCAG 2.2 AA (4.5:1 normal text) | not run |
| 11 | Beta suite | Run the integration's Beta test suite (if available for the version) | Pass; otherwise recorded as blocked with the reason | not run |
| 12 | Performance | Measure the initial load and request count with real HA | Recorded values only, no estimates | not run |

## Results (to be filled in)
| Version | Date | Checks run | Failures | Notes |
|---|---|---|---|---|
| 2026.8.0 | — | none | — | — |
| current | — | none | — | — |
