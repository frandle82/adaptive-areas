# Frontend browser harness (test-only)

Tests the shipped panel `custom_components/adaptive_areas/frontend/adaptive-areas-panel.js` in headless Chrome. The panel file is injected unchanged, so the tested code is the released code.

Nothing here is shipped with the integration. No npm packages are needed; the runner uses Node's built-in `WebSocket` and `fetch` (Node 22 or newer) and Chrome's DevTools protocol.

## Run

    # 1. Refresh fixtures from the real backend handlers (only when the WebSocket contract changes)
    ADAPTIVE_AREAS_WRITE_FIXTURES=1 .tox/ha-stable/bin/pytest -q tests/test_frontend_fixtures.py

    # 2. Regression checks (exit code 1 on failure)
    node tests/frontend/run.mjs

    # 3. Baseline measurements as JSON (written next to this file)
    node tests/frontend/run.mjs --measure

Set `CHROME_BIN` if Chrome is not at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`; Chromium works the same way (for example `CHROME_BIN=/usr/bin/chromium`).

The runner sets the markup of `harness/index.html` directly with `Page.setDocumentContent` instead of navigating to a `file://` URL, so the browser needs no file access (sandboxed Chromium packages often cannot read files outside their allowed folders). If the page is not ready, the runner stops with the page URL, ready state and body content instead of a bare timeout.

## Files

- `harness/harness.js` – simulated `hass` object: `callWS`, `connection.subscribeMessage`, `user.is_admin`, `language`, failure and latency injection, connection loss.
- `harness/index.html` – empty stage page.
- `fixtures/*.json` – backend responses written by `tests/test_frontend_fixtures.py`. Not hand-written.
- `run.mjs` – runner: regression checks (`R1` to `R7`, no JavaScript errors) and `--measure`.
- `baseline-before-modernisation.json` – measurements of the Phase E panel before the modernisation.
- `measure-after-step2.json` – measurements after the shell change (step 2). Focus is lost on subscription updates; this is the defect step 3 removes.

## Limits

- Only the harness is simulated. The real Home Assistant frontend, its theme engine and its translation loader are not part of this test.
- The backend fixtures come from a test instance; they are not captured from a live system.
- Fixtures contain one area (`kitchen`). Larger installations are not covered yet.

## Measurement comparison (step 3)

    node tests/frontend/run.mjs --measure --label=<name> --panel=<path-to-panel.js>

Seven repetitions per variant; results are written to `measure-<label>.json` with median, min and max. Variants used for the step-3 comparison: the original Phase E panel (`git show HEAD:custom_components/adaptive_areas/frontend/adaptive-areas-panel.js`), the panel after step 2, and the current panel.

Findings: focus survives a subscription update in 7 of 7 runs for the current panel and in 0 of 7 runs for the two earlier variants. Replaced DOM nodes per update drop from 2 to 1. Render time is below 1 ms in every variant and the spreads overlap; no render-time improvement is claimed.

Earlier navigation timings for the original panel were invalid (the test waited for the old tab label and timed out). Fixed by trying both labels.
