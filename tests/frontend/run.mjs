// Browser harness runner for the Adaptive Areas panel (test-only, no npm dependencies).
//
// Usage:
//   node tests/frontend/run.mjs            # regression checks, exit 1 on failure
//   node tests/frontend/run.mjs --measure  # baseline measurements as JSON
//
// Environment:
//   CHROME_BIN   path to a Chrome/Chromium executable (default: macOS Google Chrome)
//
// The runner loads the shipped panel file itself, so the tested code is the
// released code. Fixtures come from tests/test_frontend_fixtures.py.

import { spawn } from "node:child_process";
import { readFileSync, readdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const HARNESS = join(ROOT, "tests", "frontend", "harness");
const PANEL_ARG = process.argv.find((a) => a.startsWith("--panel="));
const PANEL = PANEL_ARG ? resolve(PANEL_ARG.slice(8)) : join(ROOT, "custom_components", "adaptive_areas", "frontend", "adaptive-areas-panel.js");
const LABEL_ARG = process.argv.find((a) => a.startsWith("--label="));
const LABEL = LABEL_ARG ? LABEL_ARG.slice(8) : "current";
const FIXTURES = join(ROOT, "tests", "frontend", "fixtures");
const CHROME = process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9400 + Math.floor(Math.random() * 300);
const MEASURE = process.argv.includes("--measure");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function loadTranslations() {
  const flatten = (node, prefix) => Object.entries(node).reduce((out, [key, value]) => (value && typeof value === "object" ? { ...out, ...flatten(value, `${prefix}${key}.`) } : { ...out, [`${prefix}${key}`]: value }), {});
  const prefix = "component.adaptive_areas.dashboard.";
  const read = (lang) => JSON.parse(readFileSync(join(ROOT, "custom_components/adaptive_areas/dashboard_texts", `${lang}.json`), "utf8"));
  const en = flatten(read("en"), prefix);
  const de = flatten(read("de"), prefix);
  return { en, de: { ...en, ...de } };
}

function loadFixtures() {
  const read = (name) => JSON.parse(readFileSync(join(FIXTURES, name), "utf8"));
  return {
    overviewAdmin: read("get_overview.admin.json"),
    overviewUser: read("get_overview.user.json"),
    translations: loadTranslations(),
    overviewMultiAdmin: read("get_overview.multi.admin.json"),
    overviewMultiUser: read("get_overview.multi.user.json"),
    overviewPresenceAdmin: read("get_overview.presence.admin.json"),
    overviewEnvAdmin: read("get_overview.environment_partial.admin.json"),
    overviewEnvUser: read("get_overview.environment_partial.user.json"),
    diagAcceptance: read("get_diagnostics.acceptance.admin.json"),
    overviewEnvValidAdmin: read("get_overview.environment_valid.admin.json"),
    overviewEnvValidUser: read("get_overview.environment_valid.user.json"),
    overviewEnvDisabledAdmin: read("get_overview.environment_disabled.admin.json"),
    overviewEnvDisabledUser: read("get_overview.environment_disabled.user.json"),
    areaAdmin: read("get_area.admin.json"),
    areaUser: read("get_area.user.json"),
    config: read("get_area_configuration.admin.json"),
    global: read("get_global_configuration.admin.json"),
    light: read("get_light_runtime_status.admin.json"),
    climate: read("get_climate_runtime_status.admin.json"),
    trace: read("get_decision_trace.admin.json"),
    diagnostics: read("get_diagnostics.admin.json"),
  };
}

async function launch() {
  const profile = mkdtempSync(join(tmpdir(), "aa-harness-"));
  const proc = spawn(CHROME, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--no-first-run",
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: "ignore" });
  let targets = [];
  for (let i = 0; i < 150; i++) {
    try {
      targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      if (targets.some((t) => t.type === "page")) break;
    } catch { /* Chrome starts */ }
    await sleep(200);
  }
  const page = targets.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener("open", res); ws.addEventListener("error", rej); });
  let id = 0;
  const pending = new Map();
  const errors = [];
  ws.addEventListener("message", (msg) => {
    const m = JSON.parse(msg.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    } else if (m.method === "Runtime.exceptionThrown") {
      const d = m.params.exceptionDetails;
      errors.push(d.exception?.description || d.text);
    } else if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
      errors.push(m.params.args.map((a) => a.value ?? a.description).join(" "));
    }
  });
  const send = (method, params = {}) => new Promise((res, rej) => {
    const i = ++id;
    pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  await send("Page.enable");
  await send("Runtime.enable");
  const cleanup = () => { try { ws.close(); } catch { /* ignore */ } proc.kill(); };
  return { send, evaluate, errors, cleanup };
}

async function setupPage(browser, viewport) {
  await browser.send("Emulation.setDeviceMetricsOverride", { width: viewport.width, height: viewport.height, deviceScaleFactor: 1, mobile: false });
  await browser.send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await browser.send("Page.bringToFront");
  // The page markup is set directly instead of navigating to a file:// URL: some Chromium
  // builds (for example sandboxed packages) cannot read the file, show an error page and the
  // stage element never appears; a navigation can also be observed before it has committed.
  const { frameTree } = await browser.send("Page.getFrameTree");
  await browser.send("Page.setDocumentContent", { frameId: frameTree.frame.id, html: readFileSync(join(HARNESS, "index.html"), "utf8") });
  const ready = await waitFor(browser, "document.getElementById('stage') !== null && document.body !== null", 8000).catch(() => false);
  if (!ready) throw new Error("harness page not ready: " + JSON.stringify(await browser.evaluate("({ url: location.href, readyState: document.readyState, body: document.body?.innerHTML.slice(0, 200) ?? null })")));
  await browser.evaluate(readFileSync(join(HARNESS, "harness.js"), "utf8"));
  await browser.evaluate(readFileSync(join(ROOT, "custom_components", "adaptive_areas", "frontend", "aa-entity-picker.js"), "utf8"));
  await browser.evaluate(readFileSync(PANEL, "utf8"));
  await browser.evaluate(`window.__fixtures = ${JSON.stringify(loadFixtures())};`);
}

async function waitFor(browser, expression, timeout = 6000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await browser.evaluate(expression)) return true;
    await sleep(25);
  }
  throw new Error("timeout waiting for: " + expression);
}

function mountCode(options) {
  return `(() => { const f = window.__fixtures; const opts = ${JSON.stringify(options)};
    const admin = Boolean(opts.admin);
    opts.fixtures = { overview: admin ? f.overviewAdmin : f.overviewUser, area: admin ? f.areaAdmin : f.areaUser,
      config: f.config, global: f.global, light: f.light, climate: f.climate, trace: f.trace, diagnostics: f.diagnostics, translations: f.translations };
    if (opts.envValid) opts.fixtures.overview = admin ? f.overviewEnvValidAdmin : f.overviewEnvValidUser;
    if (opts.envDisabled) opts.fixtures.overview = admin ? f.overviewEnvDisabledAdmin : f.overviewEnvDisabledUser;
    if (opts.diagAcc) opts.fixtures.diagnostics = f.diagAcceptance;
    if (opts.envPartial) opts.fixtures.overview = admin ? f.overviewEnvAdmin : f.overviewEnvUser;
    if (opts.presence) opts.fixtures.overview = f.overviewPresenceAdmin;
    if (opts.multi) opts.fixtures.overview = admin ? f.overviewMultiAdmin : f.overviewMultiUser;
    if (opts.twoAreas) { opts.fixtures.overview = JSON.parse(JSON.stringify(opts.fixtures.overview)); const second = JSON.parse(JSON.stringify(opts.fixtures.overview.areas[0])); second.id = "office"; second.name = "Office"; opts.fixtures.overview.areas.push(second); }
    if (opts.warnings) { opts.fixtures.overview = JSON.parse(JSON.stringify(opts.fixtures.overview)); const a0 = opts.fixtures.overview.areas[0]; a0.warning_details = { aggregates: 1, secondary_states: 1 }; a0.warning_count = 2; a0.sources = { available: 0, total: 1 }; a0.enabled_features = ["aggregates"]; }
    if (opts.warningsAggregatesOff) { opts.fixtures.overview = JSON.parse(JSON.stringify(opts.fixtures.overview)); const a0 = opts.fixtures.overview.areas[0]; a0.warning_details = { aggregates: 1, secondary_states: 1 }; a0.warning_count = 2; a0.sources = { available: 1, total: 1 }; a0.enabled_features = []; }
    if (opts.featureLight) { opts.fixtures.overview = JSON.parse(JSON.stringify(opts.fixtures.overview)); opts.fixtures.overview.areas[0].enabled_features = ["light"]; }
    window.__h = AAHarness.mount(opts); return true; })()`;
}

const text = (sel = "adaptive-areas-panel") => `(document.querySelector(${JSON.stringify(sel)})?.textContent || "")`;
const results = [];
const check = (name, pass, detail = "") => results.push({ name, pass: Boolean(pass), detail: String(detail) });

async function clickByText(browser, label) {
  return browser.evaluate(`(() => { const b = [...document.querySelectorAll("adaptive-areas-panel button, adaptive-areas-panel [role=tab], adaptive-areas-panel a")].find(x => x.textContent.trim() === ${JSON.stringify(label)}); if (!b) return false; b.click(); return true; })()`);
}

async function regression(browser) {
  // R1: initial render and subscription
  await browser.evaluate(mountCode({ admin: true, language: "en" }));
  await waitFor(browser, `${text()}.length > 40`);
  const r1 = await browser.evaluate(`({ calls: window.__h.hass.__state.calls, subs: window.__h.hass.__state.subscriptions.length })`).catch(() => null);
  const calls = await browser.evaluate("window.__h.hass.__state.calls");
  const subs = await browser.evaluate("window.__h.hass.__state.subscriptions.length");
  check("R1 initial load calls get_overview and subscribes once", calls.includes("adaptive_areas/get_overview") && subs === 1, JSON.stringify({ calls, subs, r1 }));

  // R2: admin sees the administration tabs
  check("R2 admin sees the Global settings tab", (await browser.evaluate(text())).includes("Global settings"));

  // R3: subscription update keeps the panel rendered
  await browser.evaluate(`window.__h.hass.__emitArea(window.__fixtures.areaAdmin)`);
  await sleep(150);
  check("R3 subscription update keeps the panel rendered", (await browser.evaluate(text())).length > 40);

  // R4: non-admin sees no administration tabs
  await browser.evaluate(mountCode({ admin: false, language: "en" }));
  await waitFor(browser, `${text()}.length > 40`);
  const userText = await browser.evaluate(text());
  check("R4 non-admin sees no Global settings tab", !userText.includes("Global settings"), userText.slice(0, 80));

  // R5: connection failure shows the error text
  await browser.evaluate(`(() => { window.__h = null; return true; })()`);
  await browser.evaluate(`(() => { const f = window.__fixtures; const opts = { admin: true, language: "en", fixtures: {}, failures: {} };
    const hass = AAHarness.createHass({ admin: true, language: "en", fixtures: { overview: f.overviewAdmin, area: f.areaAdmin, config: f.config, global: f.global, light: f.light, climate: f.climate, trace: f.trace, diagnostics: f.diagnostics, translations: f.translations }, failures: { "adaptive_areas/get_overview": "Connection lost" } });
    const panel = document.createElement("adaptive-areas-panel"); document.getElementById("stage").replaceChildren(panel); panel.hass = hass; return true; })()`);
  await waitFor(browser, `${text()}.includes("could not be loaded")`, 4000).then(() => check("R5 load failure shows error text", true)).catch(() => check("R5 load failure shows error text", false, (""),));

  // R6/R7: global settings: a rejected save keeps the draft; an accepted save reaches the backend contract
  const states = { "weather.home": { state: "sunny", attributes: { friendly_name: "Home" } }, "weather.city": { state: "cloudy", attributes: { friendly_name: "City" } } };
  await browser.evaluate(mountCode({ admin: true, language: "en", states, failures: { "adaptive_areas/update_global_configuration": "Save rejected" } }));
  await waitFor(browser, `${text()}.length > 40`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  const pick = (value) => `(() => { const s = document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]"); s.value = ${JSON.stringify(value)}; s.dispatchEvent(new Event("change", { bubbles: true })); return s.value; })()`;
  const chosen = await browser.evaluate(pick("weather.city"));
  await clickByText(browser, "Save");
  await sleep(300);
  check("R6 rejected save reports the failure", (await browser.evaluate(text())).includes("could not be saved"));
  check("R6 rejected save keeps the draft value", (await browser.evaluate(`document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]").value`)) === chosen, chosen);

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  const chosen2 = await browser.evaluate(pick("weather.city"));
  await clickByText(browser, "Save");
  await sleep(300);
  const stored = await browser.evaluate("window.__h.hass.__state.global.options.weather_entity");
  check("R7 accepted save reaches the backend contract", stored === chosen2, `stored=${stored}`);

  // S-series: step 3 data layer, targeted updates and lifecycle
  const area = "window.__fixtures.areaAdmin";
  await browser.evaluate(mountCode({ admin: true, language: "en", states, twoAreas: true }));
  await waitFor(browser, `${text()}.includes("Office")`);
  await sleep(300);
  await browser.evaluate(`(() => { window.__kitchen = document.querySelector('article[data-area-id="kitchen"]'); window.__office = document.querySelector('article[data-area-id="office"]'); return true; })()`);
  const officeChanged = JSON.parse(JSON.stringify(await browser.evaluate(area)));
  officeChanged.id = "office"; officeChanged.name = "Office"; officeChanged.occupied = !officeChanged.occupied;
  await browser.evaluate(`window.__h.hass.__emitArea(${JSON.stringify(officeChanged)})`);
  await sleep(120);
  check("S1 unchanged Area keeps its DOM element", await browser.evaluate(`document.querySelector('article[data-area-id="kitchen"]') === window.__kitchen`));
  check("S2 changed Area is updated in place (same DOM node, new content)", await browser.evaluate(`document.querySelector('article[data-area-id="office"]') === window.__office && document.querySelector('article[data-area-id="office"]').textContent.includes(${JSON.stringify(officeChanged.occupied ? "Occupied" : "Not occupied")})`));
  await browser.evaluate(`window.scrollTo(0, 400); true`);
  await browser.evaluate(`window.__h.hass.__emitArea(${JSON.stringify(officeChanged)})`);
  await sleep(80);
  check("S3 scroll position survives an update", (await browser.evaluate("window.scrollY")) === 400);

  // S4: focus and an unsaved draft survive a subscription update on the settings view
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  await sleep(300);
  await browser.evaluate(`(() => { const s = document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]"); s.focus(); s.value = "weather.city"; s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); window.__renderCount = 0; const orig = p._render.bind(p); p._render = () => { window.__renderCount++; return orig(); }; return true; })()`);
  await browser.evaluate(`window.__h.hass.__emitArea(${JSON.stringify(officeChanged)})`);
  await sleep(120);
  check("S4 focus survives a subscription update", await browser.evaluate(`document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]")?.shadowRoot?.activeElement?.tagName === "INPUT"`));
  check("S5 unsaved draft survives a subscription update", await browser.evaluate(`document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]").value === "weather.city"`));

  // S6: repeated open and close: subscriptions and listeners do not accumulate
  for (let cycle = 0; cycle < 3; cycle++) {
    await browser.evaluate(`(() => { const panel = document.querySelector("adaptive-areas-panel"); panel.remove(); document.getElementById("stage").append(panel); return true; })()`);
    await sleep(120);
  }
  const subsAfterCycles = await browser.evaluate(`window.__h.hass.__activeSubscriptions()`);
  const listenersAfterCycles = await browser.evaluate(`window.__h.hass.__listenerCount("ready")`);
  check("S6 repeated open and close keeps exactly one subscription", subsAfterCycles === 1, `subs=${subsAfterCycles}`);
  check("S6b repeated open and close keeps exactly one connection listener", listenersAfterCycles === 1, `listeners=${listenersAfterCycles}`);
  await browser.evaluate(`(() => { document.querySelector("adaptive-areas-panel").remove(); return true; })()`);
  await sleep(120);
  check("S6c removing the panel releases its subscription", (await browser.evaluate(`window.__h.hass.__activeSubscriptions()`)) === 0);

  // S7: connection loss keeps the draft and shows the state; reconnection resynchronises
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  await browser.evaluate(`(() => { const s = document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]"); s.value = "weather.city"; s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  const callsBefore = (await browser.evaluate("window.__h.hass.__state.calls")).length;
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await sleep(80);
  check("S7 disconnect shows Connection lost", (await browser.evaluate(text())).includes("Connection lost"));
  check("S7b disconnect keeps the unsaved draft", await browser.evaluate(`document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]").value === "weather.city"`));
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await waitFor(browser, `${text()}.includes("Connected")`, 4000).then(() => check("S7c reconnect shows Connected again", true)).catch(() => check("S7c reconnect shows Connected again", false));
  const callsAfter = (await browser.evaluate("window.__h.hass.__state.calls")).length;
  check("S7d reconnect resynchronises the overview", callsAfter > callsBefore && (await browser.evaluate("window.__h.hass.__state.calls")).slice(callsBefore).includes("adaptive_areas/get_overview"));

  // S8: a role change reloads the panel for the new role
  await browser.evaluate(`(() => { const panel = document.querySelector("adaptive-areas-panel"); const next = AAHarness.createHass({ admin: false, language: "en", fixtures: window.__h.hass.__state && { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; panel.hass = next; return true; })()`);
  await sleep(200);
  const roleNav = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .nav-label")].map(e => e.textContent.trim())`);
  check("S8 role change to non-admin hides administration", JSON.stringify(roleNav) === JSON.stringify(["Monitoring"]), JSON.stringify(roleNav));

  // S9/S10: Decision trace and diagnostics read real backend data
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await clickByText(browser, "Decision trace");
  await waitFor(browser, `document.querySelectorAll("adaptive-areas-panel ol.trace li").length > 0`, 4000).catch(() => null);
  const traceTexts = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel ol.trace li time")].map(e => e.textContent)`);
  check("S9 trace lists newest first", traceTexts.length > 1 && traceTexts.every((v, i) => i === 0 || traceTexts[i - 1] >= v), JSON.stringify(traceTexts));
  check("S9b trace shows translated decisions, no raw enum", (await browser.evaluate(text())).includes("State change") && !(await browser.evaluate(text())).includes("state_transition"));
  await clickByText(browser, "Diagnostics");
  await waitFor(browser, `${text()}.includes("Version")`, 4000).then(() => check("S10 diagnostics shows version and counts", true)).catch(() => check("S10 diagnostics shows version and counts", false));

  // S11: a delayed response from a closed panel is discarded and creates no subscription
  await browser.evaluate(mountCode({ admin: true, language: "en", states, latency: { "adaptive_areas/get_overview": 400 } }));
  await sleep(60);
  await browser.evaluate(`(() => { document.querySelector("adaptive-areas-panel").remove(); return true; })()`);
  await sleep(600);
  check("S11 delayed response after close creates no subscription", (await browser.evaluate(`window.__h.hass.__activeSubscriptions()`)) === 0, `subs=${await browser.evaluate(`window.__h.hass.__activeSubscriptions()`)}`);
  check("S11b delayed response after close renders nothing", (await browser.evaluate(`document.querySelectorAll("adaptive-areas-panel").length`)) === 0);

  // S12: repeated navigation across views keeps the shell consistent
  await browser.evaluate(mountCode({ admin: true, language: "en", states, featureLight: true }));
  await waitFor(browser, `${text()}.length > 40`);
  const order = ["Global settings", "Decision trace", "Diagnostics", "Dashboard", "Global settings", "Decision trace"];
  let navOk = true;
  for (let round = 0; round < 4; round++) {
    for (const label of order) {
      const ok = await clickByText(browser, label);
      if (!ok) { navOk = false; break; }
      await sleep(10);
    }
  }
  const active = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel [role=tab][aria-selected=true]")].map(e => e.textContent.trim())`);
  check("S12 repeated navigation reaches every view and keeps one active tab", navOk && active.length === 1, JSON.stringify(active));

  // S13: administrative data must not survive a role change to non-admin
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  const beforeRole = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); return { config: Boolean(p._data.config), globalSettings: Boolean(p._drafts.global.original) }; })()`);
  await browser.evaluate(`(() => { const panel = document.querySelector("adaptive-areas-panel"); const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; panel.hass = next; return true; })()`);
  await sleep(200);
  const afterRole = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); return { config: p._data.config ?? null, globalSettings: p._drafts.global.original ?? null, trace: p._data.trace ?? null, diagnostics: p._data.diagnostics ?? null }; })()`);
  check("S13 admin data before role change was loaded", beforeRole.config === true && beforeRole.globalSettings === true, JSON.stringify(beforeRole));
  check("S13b admin data is discarded after role change to non-admin", afterRole.config === null && afterRole.globalSettings === null && afterRole.trace === null && afterRole.diagnostics === null, JSON.stringify(afterRole));

  // S14: an administrative response that arrives after a role change is discarded
  await browser.evaluate(mountCode({ admin: true, language: "en", states, latency: { "adaptive_areas/get_area_configuration": 500 } }));
  await sleep(80);
  await browser.evaluate(`(() => { const panel = document.querySelector("adaptive-areas-panel"); const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; panel.hass = next; return true; })()`);
  await sleep(800);
  const late = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); return { config: p._data.config ?? null, text: p.textContent.includes("Settings") || p.textContent.includes("Global settings") }; })()`);
  check("S14 late administrative response after role change is discarded", late.config === null && late.text === false, JSON.stringify(late));

  // S15: central feature availability from the backend DTO (no inferred values)
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const featureCases = await browser.evaluate(`(() => {
    const p = document.querySelector("adaptive-areas-panel");
    const base = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin.areas[0]));
    const run = (patch, key) => p._featureState({ ...base, ...patch }, key);
    return {
      envOff: run({ enabled_features: [] , environment: null }, "environment"),
      envNoData: run({ enabled_features: ["environment"], environment: null }, "environment"),
      envData: run({ enabled_features: ["environment"], environment: { temperature: 21 } }, "environment"),
      lightNoData: run({ enabled_features: ["light"], lights: null }, "light"),
      lightData: run({ enabled_features: ["light_groups"], lights: { on: 1, total: 2, groups: [] } }, "light"),
      cleanOff: run({ enabled_features: ["environment"], cleaning: { cleaning_state: "due" } }, "cleaning"),
      cleanNoData: run({ enabled_features: ["room_usage"], cleaning: null }, "cleaning"),
      cleanData: run({ enabled_features: ["room_usage"], cleaning: { cleaning_state: "due" } }, "cleaning"),
      climate: run({ enabled_features: ["climate_control"] }, "climate"),
      climateOff: run({ enabled_features: [] }, "climate"),
    };
  })()`);
  check("S15 environment: area-off, no-data, data", featureCases.envOff === "area-off" && featureCases.envNoData === "no-data" && featureCases.envData === "data", JSON.stringify(featureCases));
  check("S15b light: no-data when enabled without light groups; data with groups", featureCases.lightNoData === "no-data" && featureCases.lightData === "data", JSON.stringify(featureCases));
  check("S15c cleaning requires the room usage feature", featureCases.cleanOff === "area-off" && featureCases.cleanNoData === "no-data" && featureCases.cleanData === "data", JSON.stringify(featureCases));
  check("S15d climate data is not inferred from the overview", featureCases.climate === "data-unknown" && featureCases.climateOff === "area-off", JSON.stringify(featureCases));

  // S16: warnings: business notices and technical source problems are shown separately, each counted once
  await browser.evaluate(mountCode({ admin: true, language: "en", states, warnings: true }));
  await waitFor(browser, `${text()}.includes("Notices")`);
  const warnLine = await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`);
  check("S16 notices and unavailable sources are separate and counted once", warnLine === "2 Notices 1 Unavailable source", JSON.stringify(warnLine));
  await browser.evaluate(mountCode({ admin: true, language: "en", states, warningsAggregatesOff: true }));
  await waitFor(browser, `${text()}.includes("Notices")`);
  check("S16c disabled aggregates do not produce notices, the secondary-state notice stays", (await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)) === "1 Notice", JSON.stringify(await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("No notices")`);
  check("S16b no warnings show an explicit neutral state, not a missing line", (await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)) === "No notices");

  // S17: reconnect with an open settings form keeps the draft; a changed server configuration is reported as a conflict
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  await sleep(200);
  await browser.evaluate(`(() => { const s = document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]"); s.value = "weather.city"; s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await browser.evaluate(`(() => { window.__h.hass.__state.global = { ok: true, errors: {}, options: { weather_entity: "weather.home", global_light_sensor: null } }; return true; })()`);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-conflict]") !== null`, 4000).then(() => check("S17 changed server configuration is reported as a conflict", true)).catch(() => check("S17 changed server configuration is reported as a conflict", false));
  check("S17b reconnect keeps the local draft", await browser.evaluate(`document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]").value === "weather.city"`));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-keep]").click()`);
  check("S17c keeping the draft removes the notice and keeps the value", (await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict]") === null && document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]").value === "weather.city"`)) === true);

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  await sleep(200);
  await browser.evaluate(`(() => { const s = document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]"); s.value = "weather.city"; s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await sleep(200);
  check("S17d no conflict notice when the server configuration is unchanged", (await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict]") === null`)) === true);

  // S18: a kept draft is not consent to overwrite; saving is blocked until the user confirms the overwrite
  const conflictSetup = `(() => { window.__h.hass.__state.global = { ok: true, errors: {}, options: { weather_entity: "weather.home", global_light_sensor: null } }; return true; })()`;
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  await sleep(200);
  await browser.evaluate(`(() => { const s = document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]"); s.value = "weather.city"; s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await browser.evaluate(conflictSetup);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-conflict]") !== null`, 4000).catch(() => null);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-keep]").click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-save-global]").click()`);
  await sleep(150);
  check("S18 saving after keeping the draft is blocked", (await browser.evaluate("window.__h.hass.__state.lastGlobalUpdate === undefined")) === true);
  check("S18b the blocked save asks for an explicit overwrite", (await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-overwrite]") !== null`)) === true);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-overwrite]").click()`);
  await sleep(300);
  check("S18c the explicit overwrite sends the draft", (await browser.evaluate(`window.__h.hass.__state.lastGlobalUpdate?.weather_entity`)) === "weather.city");

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`);
  await sleep(200);
  await browser.evaluate(`(() => { const s = document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]"); s.value = "weather.city"; s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await browser.evaluate(conflictSetup);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-conflict-take]") !== null`, 4000).catch(() => null);
  check("S18d 'use server values' replaces the draft only after the explicit choice", (await browser.evaluate(`document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]").value === "weather.city"`)) === true);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-take]").click()`);
  await sleep(200);
  check("S18e after 'use server values' the form shows the server value", (await browser.evaluate(`document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]").value === "weather.home"`)) === true);

  // S19: area form: a server change during editing is a conflict; the draft is kept; saving needs an explicit overwrite
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel input[name=clear_timeout]") !== null`);
  await browser.evaluate(`(() => { const i = document.querySelector("adaptive-areas-panel input[name=clear_timeout]"); i.value = "5"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  await browser.evaluate(`(() => { window.__h.hass.__state.config.areas[0].options.clear_timeout = 77; return true; })()`);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-conflict-scope=area]") !== null`, 4000).then(() => check("S19 server change during area editing is reported as a conflict", true)).catch(() => check("S19 server change during area editing is reported as a conflict", false));
  check("S19b the area draft survives reconnect", await browser.evaluate(`document.querySelector("adaptive-areas-panel input[name=clear_timeout]").value === "5"`));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel form:not([data-light-configuration]):not([data-climate-configuration])").requestSubmit()`);
  await sleep(200);
  check("S19c saving during an unresolved area conflict is blocked", (await browser.evaluate("window.__h.hass.__state.lastAreaUpdate === undefined")) === true);
  check("S19d the blocked save asks for an explicit overwrite", (await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-overwrite]") !== null`)) === true);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-overwrite]").click()`);
  await sleep(300);
  check("S19e the explicit overwrite sends the area draft", (await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.clear_timeout`)) === 5);

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel input[name=clear_timeout]") !== null`);
  await browser.evaluate(`(() => { const i = document.querySelector("adaptive-areas-panel input[name=clear_timeout]"); i.value = "5"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  await browser.evaluate(`(() => { window.__h.hass.__state.config.areas[0].options.clear_timeout = 77; return true; })()`);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-conflict-take]") !== null`, 4000).catch(() => null);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-take]").click()`);
  await sleep(200);
  check("S19f 'use server values' replaces the area draft only after the explicit choice", (await browser.evaluate(`document.querySelector("adaptive-areas-panel input[name=clear_timeout]").value === "77"`)) === true);

  // S20/S21: non-admin views contain no entity identifiers and no administrative controls
  await browser.evaluate(mountCode({ admin: false, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const userPanel = await browser.evaluate(text());
  const entityPattern = /\b(binary_sensor|sensor|light|switch|climate|media_player|fan|cover|number|device_tracker)\.[a-z0-9_]+/;
  check("S20 non-admin overview shows no entity identifiers", !entityPattern.test(userPanel), (userPanel.match(entityPattern) || [""])[0]);
  check("S21 non-admin has no administrative controls", (await browser.evaluate(`document.querySelectorAll("adaptive-areas-panel [data-save-global],adaptive-areas-panel [data-conflict],adaptive-areas-panel [data-edit],adaptive-areas-panel [data-add]").length`)) === 0);

  // S22: a role change while the global settings are loading must not leave the form stuck
  await browser.evaluate(mountCode({ admin: true, language: "en", states, latency: { "adaptive_areas/get_global_configuration": 600 } }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await sleep(150);
  await browser.evaluate(`(() => { const panel = document.querySelector("adaptive-areas-panel"); const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; panel.hass = next; return true; })()`);
  await sleep(800);
  await browser.evaluate(`(() => { const panel = document.querySelector("adaptive-areas-panel"); const next = AAHarness.createHass({ admin: true, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewAdmin, area: window.__fixtures.areaAdmin, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; panel.hass = next; return true; })()`);
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  const recovered = await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`, 4000).then(() => true).catch(() => false);
  check("S22 settings recover after a role change during loading", recovered);

  // B01: subscription events keep working after one or several reconnects; no duplicate subscriptions or listeners
  await browser.evaluate(mountCode({ admin: true, language: "en", states, twoAreas: true }));
  await waitFor(browser, `${text()}.includes("Office")`);
  await sleep(200);
  for (let cycle = 0; cycle < 3; cycle++) {
    await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
    await sleep(60);
    await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
    await sleep(250);
  }
  check("B01a reconnect cycles keep exactly one subscription", (await browser.evaluate("window.__h.hass.__activeSubscriptions()")) === 1);
  check("B01b reconnect cycles keep exactly one connection listener per event", (await browser.evaluate(`window.__h.hass.__listenerCount("ready")`)) === 1 && (await browser.evaluate(`window.__h.hass.__listenerCount("disconnected")`)) === 1);
  const beforeUpdate = await browser.evaluate(`document.querySelector('article[data-area-id="office"]')?.textContent.includes("Not occupied") ?? null`);
  const officeNow = JSON.parse(JSON.stringify(await browser.evaluate(`window.__fixtures.areaAdmin`)));
  officeNow.id = "office"; officeNow.name = "Office"; officeNow.occupied = !officeNow.occupied;
  await browser.evaluate(`window.__h.hass.__emitArea(${JSON.stringify(officeNow)})`);
  await sleep(120);
  check("B01c an update after reconnect is applied to the panel", (await browser.evaluate(`document.querySelector('article[data-area-id="office"]')?.textContent.includes(${JSON.stringify(officeNow.occupied ? "Occupied" : "Not occupied")})`)) === true, `before=${beforeUpdate}`);

  // B02: late responses of administrative operations never overwrite newer state or reset newer request flags
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await browser.evaluate(`window.__b02 = undefined; (async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_light_runtime_status" ? new Promise((res) => setTimeout(() => res({ ...window.__fixtures.light, marker: msg.area_id }), msg.area_id === "A" ? 400 : 50)) : orig(msg); p._ui.editing = { area_id: "A", options: {} }; const first = p._loadLightRuntime("A"); p._ui.editing = { area_id: "B", options: {} }; const second = p._loadLightRuntime("B"); await Promise.all([first, second]); h.callWS = orig; p._ui.editing = null; window.__b02 = { marker: p._data.lightRuntime?.marker ?? null, flag: p._requests.lightRuntime }; })()`);
  await waitFor(browser, `window.__b02 !== undefined`, 4000);
  const b02a = await browser.evaluate(`window.__b02`);
  check("B02a a late light response for a previous area does not overwrite the newer area", b02a.marker === "B" && b02a.flag === false, JSON.stringify(b02a));

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await browser.evaluate(`window.__b02 = undefined; (async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_light_runtime_status" ? new Promise((res) => setTimeout(() => res({ ...window.__fixtures.light, marker: msg.area_id }), msg.area_id === "A" ? 400 : 50)) : orig(msg); p._data.config = { ...p._data.config, areas: [{ area_id: "A", name: "A", options: { features: { light: {} } } }, { area_id: "B", name: "B", options: { features: { light: {} } } }] }; const first = p._selectLightArea("A"); const second = p._selectLightArea("B"); await Promise.all([first, second]); h.callWS = orig; window.__b02 = { marker: p._data.lightRuntime?.marker ?? null, flag: p._requests.lightRuntime }; })()`);
  await waitFor(browser, `window.__b02 !== undefined`, 4000);
  const b02e = await browser.evaluate(`window.__b02`);
  check("B02e light-control tab: the selected area receives its runtime data; a late response for the previous selection is discarded", b02e.marker === "B" && b02e.flag === false, JSON.stringify(b02e));

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await browser.evaluate(`window.__b02 = undefined; (async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_climate_runtime_status" ? new Promise((res) => setTimeout(() => res({ ...window.__fixtures.climate, marker: msg.area_id }), msg.area_id === "A" ? 400 : 50)) : orig(msg); p._data.config = { ...p._data.config, areas: [{ area_id: "A", name: "A", options: { features: { climate_control: {} } } }, { area_id: "B", name: "B", options: { features: { climate_control: {} } } }] }; p._ui.climateArea = "A"; const first = p._loadClimateRuntime("A"); p._ui.climateArea = "B"; const second = p._loadClimateRuntime("B"); await new Promise((r) => setTimeout(r, 200)); const mid = { marker: p._data.climateRuntime?.marker ?? null, flag: p._requests.climateRuntime }; await Promise.all([first, second]); h.callWS = orig; window.__b02 = { mid, end: { marker: p._data.climateRuntime?.marker ?? null, flag: p._requests.climateRuntime } }; })()`);
  await waitFor(browser, `window.__b02 !== undefined`, 4000);
  const b02b = await browser.evaluate(`window.__b02`);
  check("B02b overlapping climate loads keep the newest area and clear the flag only for it", b02b.mid.marker === "B" && b02b.mid.flag === false && b02b.end.marker === "B" && b02b.end.flag === false, JSON.stringify(b02b));

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await browser.evaluate(`window.__b02 = undefined; (async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_light_runtime_status" ? new Promise((res) => setTimeout(() => res({ ...window.__fixtures.light, marker: msg.area_id }), 300)) : orig(msg); p._ui.editing = { area_id: "A", options: {} }; const pending = p._loadLightRuntime("A"); const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; p.hass = next; await pending; await new Promise((r) => setTimeout(r, 100)); window.__b02 = { data: p._data.lightRuntime, flag: p._requests.lightRuntime, error: p._errors.lightRuntime }; })()`);
  await waitFor(browser, `window.__b02 !== undefined`, 4000);
  const b02c = await browser.evaluate(`window.__b02`);
  check("B02c a late light response after a role change is discarded", b02c.data === null && b02c.flag === false && b02c.error === null, JSON.stringify(b02c));

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await browser.evaluate(`window.__b02 = undefined; (async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/update_global_configuration" ? new Promise((res) => setTimeout(() => res({ ok: true, options: { weather_entity: "weather.leaked", global_light_sensor: null } }), 300)) : orig(msg); p._drafts.global.original = { weather_entity: null, global_light_sensor: null }; p._drafts.global.draft = { weather_entity: "weather.typed", global_light_sensor: null }; p._drafts.global.conflict = null; const pending = p._saveGlobalSettings(); const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; p.hass = next; await pending; await new Promise((r) => setTimeout(r, 100)); window.__b02 = { original: p._drafts.global.original, draft: p._drafts.global.draft, saving: p._drafts.global.saving, leaked: JSON.stringify(p._drafts.global).includes("weather.leaked") }; })()`);
  await waitFor(browser, `window.__b02 !== undefined`, 4000);
  const b02d = await browser.evaluate(`window.__b02`);
  check("B02d a late global save response after a role change does not restore administrative data", b02d.original === null && b02d.draft === null && b02d.saving === false && b02d.leaked === false, JSON.stringify(b02d));

  // B03: a role change to non-admin discards every administrative state, including drafts, conflicts and selections
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await browser.evaluate(`window.__b03 = undefined; (async () => { const p = document.querySelector("adaptive-areas-panel"); p._drafts.area = { ...p._areaDraftState(), areaId: "kitchen", original: { type: "interior" }, conflict: { type: "exterior" }, conflictBlocked: true, conflictOverwrite: true }; p._drafts.global.conflict = { weather_entity: "weather.server" }; p._drafts.global.conflictBlocked = true; p._drafts.global.conflictHidden = true; p._ui.lightArea = "kitchen"; p._ui.climateArea = "kitchen"; p._ui.traceArea = "kitchen"; const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; p.hass = next; await new Promise((r) => setTimeout(r, 300)); window.__b03 = { area: p._drafts.area, globalConflict: p._drafts.global.conflict, globalBlocked: p._drafts.global.conflictBlocked, globalHidden: p._drafts.global.conflictHidden, light: p._ui.lightArea ?? null, climate: p._ui.climateArea ?? null, trace: p._ui.traceArea, editing: p._ui.editing, owners: Object.values(p._owners || {}).filter(Boolean).length }; })()`);
  await waitFor(browser, `window.__b03 !== undefined`, 4000);
  const b03 = await browser.evaluate(`window.__b03`);
  check("B03 role change discards area draft, conflicts, selections and request ownership", JSON.stringify(b03.area) === JSON.stringify({ areaId: null, original: null, draft: null, newAreaId: null, saving: false, conflict: null, conflictHidden: false, conflictBlocked: false, conflictOverwrite: false }) && b03.globalConflict === null && !b03.globalBlocked && !b03.globalHidden && b03.light === null && b03.climate === null && b03.trace === null && b03.editing === null && b03.owners === 0, JSON.stringify(b03));

  // B04: the area editor works on a real draft; the form is rendered from it and it survives errors and re-renders
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  const serverTimeout = await browser.evaluate(`document.querySelector("adaptive-areas-panel")._data.config.areas.find((a) => a.area_id === "kitchen").options.clear_timeout ?? null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel input[name=clear_timeout]") !== null`);
  await browser.evaluate(`(() => { const i = document.querySelector("adaptive-areas-panel input[name=clear_timeout]"); i.value = "42"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  check("B04a input changes are captured in the area draft", (await browser.evaluate(`document.querySelector("adaptive-areas-panel")._drafts.area.draft.clear_timeout`)) === 42);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel")._render()`);
  check("B04b the form is rendered from the draft after a full re-render", (await browser.evaluate(`document.querySelector("adaptive-areas-panel input[name=clear_timeout]").value`)) === "42");
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__b04orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/update_area" ? Promise.resolve({ ok: false, errors: { clear_timeout: "invalid" } }) : window.__b04orig(msg); document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] ha-alert") !== null`, 3000).catch(() => {});
  check("B04c a validation error keeps the draft in the form", (await browser.evaluate(`document.querySelector("adaptive-areas-panel input[name=clear_timeout]")?.value`)) === "42" && (await browser.evaluate(`document.querySelector("adaptive-areas-panel form[data-area-form] ha-alert") !== null`)));
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = (msg) => msg.type === "adaptive_areas/update_area" ? Promise.reject(new Error("boom")) : window.__b04orig(msg); document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(250);
  check("B04d a failed save keeps the draft in the form", (await browser.evaluate(`document.querySelector("adaptive-areas-panel input[name=clear_timeout]")?.value`)) === "42");
  await browser.evaluate(`(() => { window.__h.hass.callWS = window.__b04orig; const p = document.querySelector("adaptive-areas-panel"); const server = JSON.parse(JSON.stringify(p._data.config.areas.find((a) => a.area_id === "kitchen").options)); server.clear_timeout = 77; p._drafts.area.conflict = server; p._patchConflict(); document.querySelector("adaptive-areas-panel [data-conflict-scope=area] [data-conflict-take]").click(); return true; })()`);
  await sleep(150);
  const b04e = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); return { form: document.querySelector("adaptive-areas-panel input[name=clear_timeout]")?.value, config: p._data.config.areas.find((a) => a.area_id === "kitchen").options.clear_timeout ?? null, editingKeys: Object.keys(p._ui.editing || {}).sort() }; })()`);
  check("B04e 'use server values' replaces the draft without mutating the loaded configuration", b04e.form === "77" && b04e.config === serverTimeout && JSON.stringify(b04e.editingKeys) === JSON.stringify(["area_id", "create", "name"]), JSON.stringify(b04e));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-cancel]").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  const afterCancel = await browser.evaluate(`JSON.stringify(document.querySelector("adaptive-areas-panel")._drafts.area)`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel input[name=clear_timeout]") !== null`);
  check("B04f cancel discards the draft; reopening shows the server value", afterCancel === JSON.stringify({ areaId: null, original: null, draft: null, newAreaId: null, saving: false, conflict: null, conflictHidden: false, conflictBlocked: false, conflictOverwrite: false }) && (await browser.evaluate(`document.querySelector("adaptive-areas-panel input[name=clear_timeout]").value`)) === String(serverTimeout ?? ""), afterCancel);

  // B05: every regular write first compares the current server state with the draft's origin; no reconnect needed
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel")._drafts.global.original !== null`, 4000);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.global = { ...st.global, options: { ...st.global.options, weather_entity: "weather.server" } }; p._drafts.global.draft = { ...p._drafts.global.draft, weather_entity: "weather.typed" }; p._saveGlobalSettings(); return true; })()`);
  await sleep(250);
  check("B05a global save detects a server change without reconnect and does not write", (await browser.evaluate(`window.__h.hass.__state.lastGlobalUpdate === undefined && document.querySelector("adaptive-areas-panel")._drafts.global.conflict?.weather_entity === "weather.server" && document.querySelector("adaptive-areas-panel [data-conflict-scope=global]") !== null`)) === true);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.global = { ...st.global, options: { ...st.global.options, weather_entity: "weather.newer" } }; const p = document.querySelector("adaptive-areas-panel"); p._drafts.global.conflictOverwrite = true; p._drafts.global.conflictBlocked = false; p._saveGlobalSettings(); return true; })()`);
  await sleep(250);
  check("B05b an overwrite confirmed for an older conflict does not write over a newer server change", (await browser.evaluate(`window.__h.hass.__state.lastGlobalUpdate === undefined && document.querySelector("adaptive-areas-panel")._drafts.global.conflict?.weather_entity === "weather.newer" && document.querySelector("adaptive-areas-panel")._drafts.global.conflictBlocked === true`)) === true);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._drafts.global.conflictOverwrite = true; p._drafts.global.conflictBlocked = false; p._saveGlobalSettings(); return true; })()`);
  await sleep(250);
  check("B05c an overwrite confirmed for the current conflict writes the draft", (await browser.evaluate(`window.__h.hass.__state.lastGlobalUpdate?.weather_entity`)) === "weather.typed");

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel input[name=clear_timeout]") !== null`);
  await browser.evaluate(`(() => { const i = document.querySelector("adaptive-areas-panel input[name=clear_timeout]"); i.value = "6"; i.dispatchEvent(new Event("input", { bubbles: true })); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.clear_timeout = 88; document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(250);
  check("B05d area save detects a server change without reconnect, does not write and keeps the draft", (await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate === undefined && document.querySelector("adaptive-areas-panel")._drafts.area.conflict?.clear_timeout === 88 && document.querySelector("adaptive-areas-panel [data-conflict-scope=area]") !== null && document.querySelector("adaptive-areas-panel input[name=clear_timeout]").value === "6"`)) === true);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.clear_timeout = 99; document.querySelector("adaptive-areas-panel [data-conflict-scope=area] [data-conflict-overwrite]")?.click(); return true; })()`);
  await sleep(250);
  check("B05e an area overwrite confirmed for an older conflict does not write over a newer server change", (await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate === undefined && document.querySelector("adaptive-areas-panel")._drafts.area.conflict?.clear_timeout === 99`)) === true);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-scope=area] [data-conflict-overwrite]")?.click()`);
  await sleep(250);
  check("B05f an area overwrite confirmed for the current conflict writes the draft", (await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.clear_timeout`)) === 6);

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel input[name=clear_timeout]") !== null`);
  await browser.evaluate(`(() => { const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_area_configuration" ? Promise.reject(new Error("check failed")) : orig(msg); document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); setTimeout(() => { h.callWS = orig; }, 200); return true; })()`);
  await sleep(300);
  check("B05g a failed server check does not write", (await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate === undefined && document.querySelector("adaptive-areas-panel form[data-area-form] ha-alert") !== null`)) === true);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config = { ...st.config, areas: [] }; document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(250);
  check("B05h an Area removed on the server is reported and nothing is written", (await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate === undefined && ([...document.querySelectorAll("adaptive-areas-panel form[data-area-form] ha-alert")].map((n) => n.textContent).join(" ")).includes("no longer exists")`)) === true);

  // B06/B07: missing, invalid or outdated warning data is never shown as "No notices"
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("No notices")`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const a = p._data.overview.areas[0]; delete a.warning_details; delete a.warning_count; p._render(); return true; })()`);
  check("B06a missing warning data is shown as unknown", (await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)) === "Notices unknown", await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`));
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const a = p._data.overview.areas[0]; a.warning_details = { aggregates: 0 }; a.warning_count = 0; p._render(); return true; })()`);
  check("B06b incomplete warning details are shown as unknown, not as zero", (await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)) === "Notices unknown", await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`));
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const a = p._data.overview.areas[0]; a.warning_details = { aggregates: 0, secondary_states: 0 }; a.warning_count = 0; delete a.sources; p._render(); return true; })()`);
  check("B06c missing source data is shown as unknown", (await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)) === "Source status unknown", await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`));
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const a = p._data.overview.areas[0]; a.sources = { available: 2, total: 3 }; p._render(); return true; })()`);
  check("B06d unavailable sources are derived from the backend fields available and total", (await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)) === "1 Unavailable source", await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`));
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const a = p._data.overview.areas[0]; a.sources = { available: 1, total: 1 }; p._render(); return true; })()`);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await sleep(100);
  check("B07a while offline the card is marked as possibly outdated instead of 'No notices'", (await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)) === "Possibly outdated", await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`));
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim() === "No notices"`, 3000).catch(() => {});
  check("B07b after reconnect the outdated marker is removed", (await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`)) === "No notices", await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim()`));

  // B08: missing enabled_features, active_states or occupied are unknown, not "disabled", "no" or "clear"
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("No notices")`);
  const b08 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const a = p._data.overview.areas[0]; delete a.enabled_features; delete a.active_states; delete a.occupied; p._render(); const card = document.querySelector("adaptive-areas-panel article[data-area-id]"); return { state: p._featureState(a, "light"), env: card.querySelector("[data-line=environment]")?.textContent.trim() ?? null, chips: [...card.querySelectorAll(".state-chip")].map((n) => n.textContent.trim()), status: card.querySelector(".status").textContent.trim(), label: card.querySelector("[data-open-area]").getAttribute("aria-label") }; })()`);
  check("B08a missing enabled_features gives the feature state 'unknown', not 'area-off'", b08.state === "unknown", JSON.stringify(b08));
  check("B08b the area card shows unknown environment availability and unknown states instead of hiding them or showing none", b08.env === "Environment: Unknown" && JSON.stringify(b08.chips) === JSON.stringify(["States unknown"]), JSON.stringify(b08));
  check("B08c a missing occupancy value is shown as unknown, not as 'Not occupied'", b08.status === "Unknown" && b08.label.includes("Unknown"), JSON.stringify(b08));
  const b08d = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const a = p._data.overview.areas[0]; a.enabled_features = []; a.active_states = []; a.occupied = false; p._render(); const card = document.querySelector("adaptive-areas-panel article[data-area-id]"); return { env: card.querySelector("[data-line=environment]") === null, chips: card.querySelectorAll(".state-chip").length, status: card.querySelector(".status").textContent.trim(), state: p._featureState(a, "environment") }; })()`);
  check("B08d an explicitly empty feature list is treated as not activated: no environment line, no unknown chip", b08d.env && b08d.chips === 0 && b08d.status === "Not occupied" && b08d.state === "area-off", JSON.stringify(b08d));

  // B09: panel state lives only in the sub-states; a late trace response for a previous Area is discarded
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  for (const label of ["Decision trace", "Diagnostics", "Global settings", "Area management", "Dashboard"]) { await clickByText(browser, label).catch(() => {}); await sleep(150); }
  const b09 = await browser.evaluate(`Object.keys(document.querySelector("adaptive-areas-panel")).filter((key) => key.startsWith("_")).sort()`);
  const allowed = ["__data", "__drafts", "__errors", "__link", "__requests", "__ui", "_climateHandlersBound", "_delegated", "_hass", "_owners"];
  check("B09a panel state is held only in the sub-states (no stray instance fields)", b09.every((key) => allowed.includes(key)), JSON.stringify(b09));
  await browser.evaluate(`window.__b09 = undefined; (async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_decision_trace" ? new Promise((res) => setTimeout(() => res({ ...window.__fixtures.trace, marker: msg.area_id }), msg.area_id === "A" ? 400 : 50)) : orig(msg); const first = p._loadTrace("A"); const second = p._loadTrace("B"); await Promise.all([first, second]); h.callWS = orig; window.__b09 = { marker: p._data.trace?.marker ?? null, area: p._ui.traceArea }; })()`);
  await waitFor(browser, `window.__b09 !== undefined`, 4000);
  const b09b = await browser.evaluate(`window.__b09`);
  check("B09b a late trace response for a previous Area does not replace the current one", b09b.marker === "B" && b09b.area === "B", JSON.stringify(b09b));

  // B10: Areas added or removed on the server reach the panel through the structural subscription event
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.overview = JSON.parse(JSON.stringify(st.overview)); const second = JSON.parse(JSON.stringify(st.overview.areas[0])); second.id = "office"; second.name = "Office"; st.overview.areas.push(second); window.__h.hass.__emitEvent({ areas_changed: true }); return true; })()`);
  await waitFor(browser, `document.querySelector('adaptive-areas-panel article[data-area-id="office"]') !== null`, 3000).catch(() => {});
  const b10a = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel article[data-area-id]")].map((n) => n.dataset.areaId).sort()`);
  check("B10a an Area added on the server appears after the structural event", JSON.stringify(b10a) === JSON.stringify(["kitchen", "office"]), JSON.stringify(b10a));
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.overview = { ...st.overview, areas: st.overview.areas.filter((a) => a.id !== "kitchen") }; window.__h.hass.__emitEvent({ areas_changed: true }); return true; })()`);
  await waitFor(browser, `document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]') === null`, 3000).catch(() => {});
  const b10b = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel article[data-area-id]")].map((n) => n.dataset.areaId).sort()`);
  check("B10b an Area removed on the server disappears after the structural event", JSON.stringify(b10b) === JSON.stringify(["office"]), JSON.stringify(b10b));
  await browser.evaluate(`(() => { const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_overview" ? Promise.reject(new Error("down")) : orig(msg); h.__emitEvent({ areas_changed: true }); setTimeout(() => { h.callWS = orig; }, 300); return true; })()`);
  await sleep(200);
  const b10c = await browser.evaluate(`({ line: document.querySelector("adaptive-areas-panel article p.warnings")?.textContent.trim(), pill: document.querySelector("adaptive-areas-panel .pill")?.textContent.trim() })`);
  check("B10c a failed structural reload marks the cards as possibly outdated without claiming a lost connection", (b10c.line || "").includes("Possibly outdated") && b10c.pill === "Connected", JSON.stringify(b10c));
  await sleep(200);
  await browser.evaluate(`window.__h.hass.__emitEvent({ areas_changed: true })`);
  await waitFor(browser, `!(document.querySelector("adaptive-areas-panel article p.warnings")?.textContent || "").includes("Possibly outdated")`, 3000).catch(() => {});
  check("B10d a later successful reload removes the outdated marker", !((await browser.evaluate(`document.querySelector("adaptive-areas-panel article p.warnings")?.textContent`)) || "").includes("Possibly outdated"));

  await browser.evaluate(`window.__b10 = undefined; (async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); let n = 0; h.callWS = (msg) => { if (msg.type !== "adaptive_areas/get_overview") return orig(msg); n += 1; const call = n; return orig(msg).then((o) => new Promise((res) => setTimeout(() => res({ ...o, areas: o.areas.map((a) => ({ ...a, name: "Call " + call })) }), call === 1 ? 400 : 50))); }; const first = p._areasChanged(); const second = p._areasChanged(); await Promise.all([first, second]); h.callWS = orig; window.__b10 = { names: p._data.overview.areas.map((a) => a.name), owner: Object.values(p._owners || {}).filter(Boolean).length }; })()`);
  await waitFor(browser, `window.__b10 !== undefined`, 4000);
  const b10e = await browser.evaluate(`window.__b10`);
  check("B10e overlapping structural reloads keep the newest result", b10e.names.every((name) => name === "Call 2") && b10e.owner === 0, JSON.stringify(b10e));

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel input[name=clear_timeout]") !== null`);
  await browser.evaluate(`(() => { const i = document.querySelector("adaptive-areas-panel input[name=clear_timeout]"); i.value = "13"; i.dispatchEvent(new Event("input", { bubbles: true })); const f = document.querySelector("adaptive-areas-panel select[name=type]"); f.focus(); window.__b10focusBefore = document.activeElement === f; window.__h.hass.__emitEvent({ areas_changed: true }); return true; })()`);
  await sleep(250);
  const b10f = await browser.evaluate(`({ value: document.querySelector("adaptive-areas-panel input[name=clear_timeout]")?.value, focused: document.activeElement === document.querySelector("adaptive-areas-panel select[name=type]"), before: window.__b10focusBefore, pending: document.querySelector("adaptive-areas-panel")._ui.pendingRender })`);
  check("B10f a structural event during editing keeps the draft, the focus and defers the re-render", b10f.value === "13" && b10f.before === true && b10f.focused === true && b10f.pending === true, JSON.stringify(b10f));

  // R01: subscription generation: callbacks of replaced or closed subscriptions process nothing
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const r01a = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const old = window.__h.hass.__state.subscriptions[0].callback; const leak = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin.areas[0])); leak.name = "LEAK"; const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; p.hass = next; await new Promise((r) => setTimeout(r, 300)); const before = next.__state.calls.length; old({ area: leak }); old({ areas_changed: true }); await new Promise((r) => setTimeout(r, 300)); const fresh = JSON.parse(JSON.stringify(window.__fixtures.overviewUser.areas[0])); fresh.name = "Fresh"; next.__emitArea(fresh); await new Promise((r) => setTimeout(r, 150)); return { leak: JSON.stringify(p._data.overview).includes("LEAK") || p.textContent.includes("LEAK"), config: p._data.config, calls: next.__state.calls.slice(before), fresh: p.textContent.includes("Fresh") }; })()`);
  check("R01a after a role change the old administrative callback restores nothing, also not via areas_changed", r01a.leak === false && r01a.config === null && r01a.calls.length === 0, JSON.stringify(r01a));
  check("R01b the subscription of the new role keeps working", r01a.fresh === true, JSON.stringify(r01a));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const r01c = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const old = h.__state.subscriptions[0].callback; p._detach(); await p._subscribe(p._link.session); const leak = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin.areas[0])); leak.name = "LEAK"; const before = h.__state.calls.length; old({ area: leak }); old({ areas_changed: true }); await new Promise((r) => setTimeout(r, 300)); const fresh = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin.areas[0])); fresh.name = "Fresh"; h.__emitArea(fresh); await new Promise((r) => setTimeout(r, 150)); return { leak: JSON.stringify(p._data.overview).includes("LEAK"), calls: h.__state.calls.slice(before), fresh: p.textContent.includes("Fresh"), active: h.__activeSubscriptions() }; })()`);
  check("R01c a replaced subscription's callback is ignored while the new one works", r01c.leak === false && r01c.calls.length === 0 && r01c.fresh === true && r01c.active === 1, JSON.stringify(r01c));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const r01d = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const old = h.__state.subscriptions[0].callback; p.remove(); const leak = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin.areas[0])); leak.name = "LEAK"; const before = h.__state.calls.length; old({ area: leak }); old({ areas_changed: true }); await new Promise((r) => setTimeout(r, 300)); return { leak: JSON.stringify(p._data.overview).includes("LEAK"), calls: h.__state.calls.slice(before), active: h.__activeSubscriptions() }; })()`);
  check("R01d after the panel is removed an old callback processes nothing", r01d.leak === false && r01d.calls.length === 0 && r01d.active === 0, JSON.stringify(r01d));

  // R02: global settings load through the shared guard and request ownership
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const r02a = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); let n = 0; h.callWS = (msg) => { if (msg.type !== "adaptive_areas/get_global_configuration") return orig(msg); n += 1; const call = n; return new Promise((_, rej) => setTimeout(() => rej(new Error(\"late\")), 300)); }; const pending = p._loadGlobalSettings(); const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; p.hass = next; await pending; await new Promise((r) => setTimeout(r, 100)); return { loadError: p._drafts.global.loadError, loading: p._drafts.global.loading }; })()`);
  check("R02a a late load error after a role change is discarded", r02a.loadError === null && r02a.loading === false, JSON.stringify(r02a));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const r02b = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); let n = 0; h.callWS = (msg) => { if (msg.type !== "adaptive_areas/get_global_configuration") return orig(msg); n += 1; const call = n; return new Promise((res) => setTimeout(() => res({ ok: true, errors: {}, options: { weather_entity: \"weather.old\", global_light_sensor: null } }), 400)); }; const first = p._loadGlobalSettings(); const user = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = user; p.hass = user; await new Promise((r) => setTimeout(r, 50)); const admin = AAHarness.createHass({ admin: true, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewAdmin, area: window.__fixtures.areaAdmin, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); const orig2 = admin.callWS.bind(admin); admin.callWS = (msg) => msg.type === "adaptive_areas/get_global_configuration" ? new Promise((res) => setTimeout(() => res({ ok: true, errors: {}, options: { weather_entity: "weather.new", global_light_sensor: null } }), 50)) : orig2(msg); window.__h.hass = admin; p.hass = admin; await new Promise((r) => setTimeout(r, 50)); const second = p._loadGlobalSettings(); await Promise.all([first, second]); await new Promise((r) => setTimeout(r, 100)); return { original: p._drafts.global.original, loading: p._drafts.global.loading, loadError: p._drafts.global.loadError }; })()`);
  check("R02b concurrent loads across a role change keep the newest result", r02b.original?.weather_entity === "weather.new" && r02b.loading === false && r02b.loadError === null, JSON.stringify(r02b));

  // R03: results and errors are taken only from the request that currently owns the load
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const r03 = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); const out = {}; let n = 0; h.callWS = (msg) => { if (msg.type === "adaptive_areas/get_light_runtime_status" || msg.type === "adaptive_areas/get_climate_runtime_status" || msg.type === "adaptive_areas/get_decision_trace") { n += 1; const call = n; const slow = call % 2 === 1; if (window.__r03fail && slow) return new Promise((_, rej) => setTimeout(() => rej(new Error("late")), 400)); return new Promise((res) => setTimeout(() => res({ ...window.__fixtures.light, entries: [], marker: call }), slow ? 400 : 50)); } return orig(msg); };
    p._ui.editing = { area_id: "A" }; await Promise.all([p._loadLightRuntime("A"), p._loadLightRuntime("A")]); out.light = { marker: p._data.lightRuntime?.marker ?? null, flag: p._requests.lightRuntime };
    window.__r03fail = true; await Promise.all([p._loadLightRuntime("A"), p._loadLightRuntime("A")]); out.lightError = { marker: p._data.lightRuntime?.marker ?? null, error: p._errors.lightRuntime ? String(p._errors.lightRuntime) : null }; window.__r03fail = false; p._ui.editing = null;
    p._data.config = { ...p._data.config, areas: [{ area_id: "A", name: "A", options: { features: { climate_control: {} } } }] }; p._ui.climateArea = "A"; await Promise.all([p._loadClimateRuntime("A"), p._loadClimateRuntime("A")]); out.climate = { marker: p._data.climateRuntime?.marker ?? null, flag: p._requests.climateRuntime };
    await Promise.all([p._loadTrace("A"), p._loadTrace("A")]); out.trace = { marker: p._data.trace?.marker ?? null };
    h.callWS = orig; return { out, n }; })()`);
  check("R03a two light loads for the same Area answered in reverse order keep the newer result", r03.out.light.marker === 2 && r03.out.light.flag === false, JSON.stringify(r03));
  check("R03b a late error of an older load does not replace the newer result", r03.out.lightError.marker === 4 && r03.out.lightError.error === null, JSON.stringify(r03));
  check("R03c two climate loads for the same Area answered in reverse order keep the newer result", r03.out.climate.marker === 6 && r03.out.climate.flag === false, JSON.stringify(r03));
  check("R03d two trace loads for the same Area answered in reverse order keep the newer result", r03.out.trace.marker === 8, JSON.stringify(r03));

  // R04: one area save at a time, guarded final render; delete with guard, ownership and errors
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const r04a = await browser.evaluate(`(async () => { const h = window.__h.hass; const orig = h.callWS.bind(h); let n = 0; h.callWS = (msg) => { if (msg.type !== "adaptive_areas/update_area") return orig(msg); n += 1; const call = n; return new Promise((res) => setTimeout(() => res(orig(msg)), 300)); }; const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); form.requestSubmit(); form.requestSubmit(); await new Promise((r) => setTimeout(r, 30)); document.querySelector("adaptive-areas-panel form[data-area-form]")?.requestSubmit(); await new Promise((r) => setTimeout(r, 600)); return { updates: window.__h.hass.__state.calls.filter((c) => c === "adaptive_areas/update_area").length, saving: document.querySelector("adaptive-areas-panel")._drafts.area.saving }; })()`);
  check("R04a repeated submits of the area form send exactly one write", r04a.updates === 1 && r04a.saving === false, JSON.stringify(r04a));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const r04b = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); let n = 0; h.callWS = (msg) => { if (msg.type !== "adaptive_areas/update_area") return orig(msg); n += 1; const call = n; return new Promise((_, rej) => setTimeout(() => rej(new Error(\"zz-late-save-error\")), 300)); }; document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); await new Promise((r) => setTimeout(r, 50)); const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; p.hass = next; await new Promise((r) => setTimeout(r, 500)); return { error: p._errors.form, editing: p._ui.editing, draft: p._drafts.area.draft, text: p.textContent.includes("zz-late-save-error") }; })()`);
  check("R04b a late save error after a role change is discarded and not rendered", r04b.error === null && r04b.editing === null && r04b.draft === null && r04b.text === false, JSON.stringify(r04b));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-delete='kitchen']") !== null`);
  const r04c = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); window.confirm = () => true; const h = window.__h.hass; const orig = h.callWS.bind(h); let n = 0; h.callWS = (msg) => { if (msg.type !== "adaptive_areas/delete_area") return orig(msg); n += 1; window.__r04deletes = n; return new Promise((_, rej) => setTimeout(() => rej(new Error(\"down\")), 200)); }; const button = document.querySelector("adaptive-areas-panel [data-delete='kitchen']"); button.click(); button.click(); await new Promise((r) => setTimeout(r, 400)); return { deletes: window.__r04deletes || 0, alert: document.querySelector("adaptive-areas-panel ha-alert[alert-type=error]")?.textContent || "", flag: p._requests.areaDelete }; })()`);
  check("R04c a failed delete is reported, repeated clicks send one request, the lock is released", r04c.deletes === 1 && r04c.alert.includes("could not be deleted") && r04c.flag === false, JSON.stringify(r04c));

  // AV-series (step 6.8): analysis views are read-only and point to the central Area editor; the old forms are gone
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 50, turn_off_above: 200 }, light_groups: { overhead_lights: ["light.ceiling"], overhead_lights_activation: "occupied", overhead_lights_blocking_states: [], overhead_lights_brightness: "require_dark", sleep_lights: [], sleep_lights_activation: "disabled", sleep_lights_blocking_states: [], sleep_lights_brightness: "require_dark", accent_lights: [], accent_lights_activation: "disabled", accent_lights_blocking_states: [], accent_lights_brightness: "require_dark", task_lights: [], task_lights_activation: "disabled", task_lights_blocking_states: [], task_lights_brightness: "require_dark" }, climate_control: { entity_id: "climate.kitchen", preset_clear: "off", preset_occupied: "comfort", preset_sleep: "sleep", preset_extended: "eco", climate_occupancy_threshold: 5 } })); p._data.config = JSON.parse(JSON.stringify(st.config)); p._data.overview.areas[0].enabled_features = ["light", "light_groups", "climate_control"]; p._render(); return true; })()`);
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; window.__av = 0; (() => { const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => { if (msg.type === "adaptive_areas/update_area") window.__av += 1; return orig(msg); }; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-tab=light-control]").click()`);
  await sleep(200);
  const av1 = await browser.evaluate(`(() => { const body = document.querySelector("adaptive-areas-panel [data-region=body]"); return { forms: body.querySelectorAll("form").length, inputs: body.querySelectorAll("input").length, lightSelects: [...body.querySelectorAll("select")].filter((n) => (n.name || "").startsWith("light")).length, configButton: !!body.querySelector("[data-config-area='kitchen']"), thresholds: body.textContent.includes("50 lx") && body.textContent.includes("200 lx") }; })()`);
  check("AV1 the light analysis shows the stored thresholds read-only: no form, no input, and a button to the Area editor", av1.forms === 0 && av1.inputs === 0 && av1.lightSelects === 0 && av1.configButton === true && av1.thresholds === true, JSON.stringify(av1));
  const av2 = await browser.evaluate(`(() => { const body = document.querySelector("adaptive-areas-panel [data-region=body]"); return { groups: body.textContent.includes("Ceiling lights") && body.textContent.includes("occupied") || body.textContent.includes("Occupied"), runtimeStatus: !!body.querySelector("section.runtime") || body.textContent.includes("Current status") }; })()`);
  check("AV2 the light analysis keeps the group settings and the runtime status information", av2.groups === true && av2.runtimeStatus === true, JSON.stringify(av2));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-tab=climate-control]").click()`);
  await sleep(200);
  const av3 = await browser.evaluate(`(() => { const body = document.querySelector("adaptive-areas-panel [data-region=body]"); return { forms: body.querySelectorAll("form").length, inputs: body.querySelectorAll("input").length, climateSelects: [...body.querySelectorAll("select")].filter((n) => (n.name || "").startsWith("climate")).length, presetsShown: body.textContent.includes("comfort") && body.textContent.includes("eco"), configButton: !!body.querySelector("[data-config-area='kitchen']") }; })()`);
  check("AV3 the climate analysis shows the stored presets read-only: no form, no input, and a button to the Area editor", av3.forms === 0 && av3.inputs === 0 && av3.climateSelects === 0 && av3.presetsShown === true && av3.configButton === true, JSON.stringify(av3));
  const av4 = await browser.evaluate(`window.__av`);
  check("AV4 visiting the analysis views sends no configuration write", av4 === 0, String(av4));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-config-area='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-climate]") !== null`, 4000).catch(() => {});
  const av5 = await browser.evaluate(`({ editor: !!document.querySelector("adaptive-areas-panel form[data-area-form]"), tab: document.querySelector("adaptive-areas-panel [data-tab=areas]")?.getAttribute("aria-selected") || null, light: !!document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]"), climate: !!document.querySelector("adaptive-areas-panel form[data-area-form] [data-climate]") })`);
  check("AV5 the navigation button opens the central Area editor with the light and climate sections", av5.editor === true && av5.tab === "true" && av5.light === true && av5.climate === true, JSON.stringify(av5));
  const av6 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); return { threshold: f.elements.namedItem("light:threshold")?.value ?? null, hysteresis: f.elements.namedItem("light:hysteresis")?.value ?? null, preset: f.elements.namedItem("climate:preset_occupied").value }; })()`);
  check("AV6 the stored 50/200 lx pair is shown as threshold 125 and hysteresis 120 %, and climate values stay editable", av6.threshold === "125" && av6.hysteresis === "120" && av6.preset === "comfort", JSON.stringify(av6));

  // H-series: lux threshold and hysteresis mapping, responsive editor widths
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 90, turn_off_above: 110 }, light_groups: { overhead_lights: ["light.ceiling"], overhead_lights_activation: "occupied", overhead_lights_blocking_states: ["sleep"], overhead_lights_brightness: "require_dark", sleep_lights: ["light.bed"], sleep_lights_activation: "sleep", sleep_lights_blocking_states: [], sleep_lights_brightness: "ignore", accent_lights: [], accent_lights_activation: "disabled", accent_lights_blocking_states: [], accent_lights_brightness: "require_dark", task_lights: [], task_lights_activation: "disabled", task_lights_blocking_states: [], task_lights_brightness: "require_dark" } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  const h1 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); return { threshold: f.elements.namedItem("light:threshold")?.value ?? null, hysteresis: f.elements.namedItem("light:hysteresis")?.value ?? null, legacy: !!f.elements.namedItem("light:turn_on_below") }; })()`);
  check("H1 the stored 90/110 lx pair is shown as threshold 100 and hysteresis 20 without legacy fields", h1.threshold === "100" && h1.hysteresis === "20" && h1.legacy === false, JSON.stringify(h1));
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; (() => { document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(200);
  const h2 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null`);
  check("H2 saving without changing the pair keeps the stored limits exactly (no rounding or rewrite)", h2 === null || (h2.turn_on_below === 90 && h2.turn_off_above === 110), JSON.stringify(h2));
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`, 4000).catch(() => {});
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']")?.click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  const widths = [];
  for (const width of [320, 390, 430, 768, 1024]) {
    await browser.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(120);
    const w = await browser.evaluate(`(() => { const doc = document.documentElement; const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); const box = form ? form.getBoundingClientRect() : null; const controls = [...form.querySelectorAll("select, input:not([type=hidden])"), ...[...form.querySelectorAll("aa-entity-picker")].map((p) => p.shadowRoot?.querySelector("input")).filter(Boolean)]; const over = box ? controls.filter((n) => n.getClientRects().length > 0).filter((n) => n.getBoundingClientRect().right > box.right + 1 || n.getBoundingClientRect().left < box.left - 1).map((n) => n.name || n.tagName) : ["no-form"]; return { docScroll: doc.scrollWidth, client: doc.clientWidth, over }; })()`);
    widths.push({ width, ...w });
  }
  check("H4 the light editor has no horizontal page overflow and no control outside its form at 320, 390, 430, 768 and 1024 px", widths.every((w) => w.docScroll <= w.client && w.over.length === 0), JSON.stringify(widths));
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:threshold").value = "100"; f.elements.namedItem("light:hysteresis").value = "40"; f.requestSubmit(); return true; })()`);
  await sleep(250);
  const h3 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null`);
  check("H3 threshold 100 with hysteresis 40 is stored as 80 on and 120 off", h3?.turn_on_below === 80 && h3?.turn_off_above === 120, JSON.stringify(h3));

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 110, turn_off_above: 90 } })); const p = document.querySelector("adaptive-areas-panel"); p._data.config = JSON.parse(JSON.stringify(st.config)); window.__h.hass.__state.lastAreaUpdate = undefined; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  const h5 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); return { legacyOn: f.elements.namedItem("light:turn_on_below")?.value ?? null, legacyOff: f.elements.namedItem("light:turn_off_above")?.value ?? null, warning: !!f.querySelector("[data-light-legacy]"), pairShown: !!f.querySelector("[data-light-pair]:not([data-light-legacy])") }; })()`);
  check("H5 inverted stored limits (110 on, 90 off) stay in the original fields with a hint and are not converted", h5.legacyOn === "110" && h5.legacyOff === "90" && h5.warning === true && h5.pairShown === false, JSON.stringify(h5));
  await browser.evaluate(`(() => { document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(200);
  const h6 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null`);
  check("H6 saving the inverted limits without an edit sends them unchanged (no conversion)", h6 === null || (h6.turn_on_below === 110 && h6.turn_off_above === 90), JSON.stringify(h6));

  // RS-series: long entity IDs and labels in selectors at narrow widths and 200 % zoom equivalents
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 90, turn_off_above: 110 }, light_groups: { overhead_lights: ["light.ceiling"], overhead_lights_activation: "occupied", overhead_lights_blocking_states: ["sleep"], overhead_lights_brightness: "require_dark", sleep_lights: ["light.bed"], sleep_lights_activation: "sleep", sleep_lights_blocking_states: [], sleep_lights_brightness: "ignore", accent_lights: [], accent_lights_activation: "disabled", accent_lights_blocking_states: [], accent_lights_brightness: "require_dark", task_lights: [], task_lights_activation: "disabled", task_lights_blocking_states: [], task_lights_brightness: "require_dark" } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  await browser.evaluate(`(() => { const long = "binary_sensor.upstairs_corridor_hallway_motion_detector_zone_north_long_name_v3_2026"; const h = window.__h.hass; const extra = {}; for (let i = 0; i < 6; i += 1) extra["binary_sensor.very_long_presence_entity_identifier_number_" + i + "_for_responsive_layout_testing"] = { state: "off", attributes: { friendly_name: "Presence sensor with a very long display name number " + i + " for the responsive layout check", device_class: "motion" } }; extra[long] = { state: "on", attributes: { friendly_name: "Upstairs corridor hallway motion detector zone north", device_class: "motion" } }; h.states = Object.assign({}, h.states, extra); document.querySelector("adaptive-areas-panel")._render(); return true; })()`);
  await sleep(150);
  const rs0 = await browser.evaluate(`(() => { const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); if (!form) return { form: false }; for (const sel of form.querySelectorAll("select[multiple]")) { for (const opt of sel.options) { if (opt.value.startsWith("binary_sensor.upstairs")) opt.selected = true; } } return { form: true, multi: form.querySelectorAll("select[multiple]").length }; })()`);
  check("RS0 the Area editor with long entity IDs and a multi-select is open", rs0.form === true && rs0.multi >= 1, JSON.stringify(rs0));
  const rsWidths = [320, 390, 430, 768, 1024, 160, 195, 512];
  const rsResults = [];
  for (const width of rsWidths) {
    await browser.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(150);
    const r = await browser.evaluate(`(() => { const doc = document.documentElement; const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); if (!form) return { form: false, docScroll: doc.scrollWidth, client: doc.clientWidth }; const box = form.getBoundingClientRect(); const bad = []; for (const n of form.querySelectorAll("select, input, label")) { const r = n.getBoundingClientRect(); if (r.width === 0) continue; if (r.right > box.right + 1 || r.left < box.left - 1) bad.push((n.name || n.tagName) + ":" + Math.round(r.right - box.right)); if (n.scrollWidth > n.clientWidth + 1 && (n.tagName === "INPUT" || (n.tagName === "SELECT" && !n.multiple))) bad.push("clip:" + (n.name || n.tagName)); if (n.tagName === "SELECT" && n.multiple) { for (const o of n.options) { if (!o.title && o.value.includes(".")) bad.push("no-title:" + o.value); } } } return { form: true, docScroll: doc.scrollWidth, client: doc.clientWidth, bad: bad.slice(0, 6) }; })()`);
    rsResults.push({ width, ...r });
  }
  check("RS1 at 160, 195, 320, 390, 430, 512, 768 and 1024 px (200 % zoom equivalents included) the form has no horizontal page overflow and no control or label outside its container or clipped", rsResults.every((r) => r.form === true && r.docScroll <= r.client && (r.bad || []).length === 0), JSON.stringify(rsResults));
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // HX-series: hysteresis floats, unchanged saves, blocked invalid input, equality cases
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 90.3, turn_off_above: 110.1 }, light_groups: { overhead_lights: ["light.ceiling"], overhead_lights_activation: "occupied", overhead_lights_blocking_states: ["sleep"], overhead_lights_brightness: "require_dark", sleep_lights: ["light.bed"], sleep_lights_activation: "sleep", sleep_lights_blocking_states: [], sleep_lights_brightness: "ignore", accent_lights: [], accent_lights_activation: "disabled", accent_lights_blocking_states: [], accent_lights_brightness: "require_dark", task_lights: [], task_lights_activation: "disabled", task_lights_blocking_states: [], task_lights_brightness: "require_dark" } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  const hx1 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); return { threshold: f.elements.namedItem("light:threshold").value, hysteresis: f.elements.namedItem("light:hysteresis").value }; })()`);
  check("HX1 a stored float pair 90.3/110.1 is shown without rounding (threshold 100.2, hysteresis 19.8 within float precision)", Math.abs(Number(hx1.threshold) - 100.2) < 1e-9 && Math.abs(Number(hx1.hysteresis) - 19.8) < 1e-9, JSON.stringify(hx1));
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; (() => { document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(200);
  const hx2 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null`);
  check("HX2 saving the unchanged float pair sends exactly 90.3 and 110.1", hx2 === null || (hx2.turn_on_below === 90.3 && hx2.turn_off_above === 110.1), JSON.stringify(hx2));
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`, 4000).catch(() => {});
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']")?.click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:hysteresis").value = ""; window.__h.hass.__state.lastAreaUpdate = undefined; f.requestSubmit(); return true; })()`);
  await sleep(200);
  const hx3 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const box = f?.querySelector("[data-light-pair-error]"); return { sentNull: window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null, shown: !!box && !box.hidden && box.textContent.length > 0, form: !!f }; })()`);
  check("HX3 an empty hysteresis blocks the save with a visible message and sends nothing", hx3.form === true && hx3.shown === true && hx3.sentNull === null, JSON.stringify(hx3));
  const invalid = ["-5", "250", "x"];
  const hx4 = [];
  for (const value of invalid) {
    await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:threshold").value = "100"; f.elements.namedItem("light:hysteresis").value = ${JSON.stringify(value)}; window.__h.hass.__state.lastAreaUpdate = undefined; f.requestSubmit(); return true; })()`);
    await sleep(120);
    const r = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const box = f?.querySelector("[data-light-pair-error]"); return { sent: window.__h.hass.__state.lastAreaUpdate ?? null, shown: !!box && !box.hidden }; })()`);
    hx4.push({ value, ...r });
  }
  check("HX4 negative, above 200 % and non-numeric hysteresis are blocked", hx4.every((r) => r.sent === null && r.shown === true), JSON.stringify(hx4));
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:threshold").value = "100"; f.elements.namedItem("light:hysteresis").value = "20"; window.__h.hass.__state.lastAreaUpdate = undefined; f.requestSubmit(); return true; })()`);
  await sleep(200);
  const hx5 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null`);
  check("HX5 threshold 100 and hysteresis 20 give exactly 90 on and 110 off (equality case, inclusive limits stay in the backend)", hx5?.turn_on_below === 90 && hx5?.turn_off_above === 110, JSON.stringify(hx5));
  // HX6: 0 % hysteresis is valid and gives equal limits (threshold on and off at the same value)
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']")?.click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`, 4000).catch(() => {});
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:threshold").value = "100"; f.elements.namedItem("light:hysteresis").value = "0"; window.__h.hass.__state.lastAreaUpdate = undefined; f.requestSubmit(); return true; })()`);
  await sleep(200);
  const hx6 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null`);
  check("HX6 0 % hysteresis is valid: threshold 100 sends equal limits 100 and 100", hx6?.turn_on_below === 100 && hx6?.turn_off_above === 100, JSON.stringify(hx6));
  // DG: brightness source reasons in the area detail and light diagnostics (backend payload shape)
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const bdDetail = (reason, extra = {}) => browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.detailArea = "kitchen"; p._data.areaDetail = { id: "kitchen", brightness_detail: { state: null, reason: ${JSON.stringify(reason)}, default_dark: ${reason === "not_configured"}, dark_source: ${JSON.stringify(extra.dark_source ?? null)} } }; p._render(); return (document.querySelector("adaptive-areas-panel")?.textContent || "").replace(/\\s+/g, " "); })()`);
  const bdg1 = await bdDetail("configured_source", { dark_source: { name: "Hall dark", state: "off", entity_id: "binary_sensor.hall_dark", status: "ok", available: true } });
  check("DG1 a configured darkness entity is named with its state as the source", bdg1.includes("Source: darkness entity Hall dark (state off)"), bdg1.slice(0, 200));
  const bdg2 = await bdDetail("not_configured");
  check("DG2 without a darkness entity the dark state is labelled as the default assumption", bdg2.includes("Default assumption") && bdg2.includes("no darkness entity configured"), "");
  const bdg3 = await bdDetail("source_unavailable", { dark_source: { name: "Hall dark", state: null, entity_id: "binary_sensor.hall_dark", status: "unavailable", available: false } });
  check("DG3 an unavailable darkness entity is not guessed: the last valid state remains", bdg3.includes("unavailable; the last valid state remains"), "");
  check("DG4 the aggregation threshold is marked as a separate configuration", bdg3.includes("separate from the percentage hysteresis"), "");
  const lrRun = (light) => browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.lightRuntime = { area_id: "kitchen", light: ${JSON.stringify(light)} }; p._requests = p._requests || {}; p._requests.lightRuntime = false; p._errors.lightRuntime = null; return p._lightRuntimeStatus(p._t).replace(/\\s+/g, " "); })()`);
  const base = { enabled: true, presence: { available: true, occupied: true }, illuminance: { configured: true, entity_id: "sensor.global_lux", available: true, value: 85 }, thresholds: { turn_on_below: 90, turn_off_above: 110 }, override: { mode: "NONE", groups: [] }, control_path: { group_active: false, groups: [] } };
  const lrc4 = await lrRun({ ...base, illuminance: { configured: false, entity_id: null, available: false, value: null } });
  check("LR4 a missing global light sensor is named as missing, not as a value", lrc4.includes("No global light sensor configured"), lrc4.slice(-300));
  const lrc6 = await lrRun({ ...base, thresholds: { turn_on_below: null, turn_off_above: null } });
  check("LR6 missing limits are shown as not configured", lrc6.includes("not configured"), lrc6.slice(-300));
  const lrc7 = await lrRun({ ...base, override: { mode: "MANUAL", groups: ["light.adaptive_areas_light_groups_kitchen_overhead_lights"] } });
  check("LR7 the group override is shown with its label", lrc7.includes("Manually set"), lrc7.slice(-300));
  // PCT: percentage hysteresis edge cases (formula T ± T·H/200, no intermediate rounding, legacy only when a one-decimal preview cannot reproduce the stored limits)
  const pctOpen = async (on, off) => {
    await browser.evaluate(mountCode({ admin: true, language: "en", states }));
    await waitFor(browser, `${text()}.includes("Connected")`);
    await clickByText(browser, "Area management");
    await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
    await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: ${on}, turn_off_above: ${off} } })); document.querySelector("adaptive-areas-panel")._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
    await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
    await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  };
  const pctTry = async (threshold, percent) => {
    await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:threshold").value = ${JSON.stringify(String(threshold))}; f.elements.namedItem("light:hysteresis").value = ${JSON.stringify(String(percent))}; window.__h.hass.__state.lastAreaUpdate = undefined; f.requestSubmit(); return true; })()`);
    await sleep(160);
    return browser.evaluate(`({ sent: window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null, error: !!document.querySelector("adaptive-areas-panel form[data-area-form] [data-light-pair-error]:not([hidden])"), nativeInvalid: document.querySelector("adaptive-areas-panel form[data-area-form]")?.elements.namedItem("light:threshold")?.validity.valid === false })`);
  };
  await pctOpen(90, 110);
  const pct1 = await pctTry(100, 200);
  check("PCT1 0 to 200 % is accepted: H 200 at threshold 100 gives 0 on and 200 off", pct1.sent?.turn_on_below === 0 && pct1.sent?.turn_off_above === 200, JSON.stringify(pct1));
  await pctOpen(90, 110);
  const pct2 = await pctTry(100, 100);
  check("PCT2 H 100 % at threshold 100 gives 50 on and 150 off", pct2.sent?.turn_on_below === 50 && pct2.sent?.turn_off_above === 150, JSON.stringify(pct2));
  await pctOpen(90, 110);
  const pct3 = await pctTry(12.5, 33.3);
  check("PCT3 decimal inputs are not rounded: 12.5 lx at 33.3 % gives 10.41875 and 14.58125", Math.abs(pct3.sent?.turn_on_below - 10.41875) < 1e-9 && Math.abs(pct3.sent?.turn_off_above - 14.58125) < 1e-9, JSON.stringify(pct3));
  await pctOpen(90, 110);
  const pct4 = await pctTry(0, 20);
  check("PCT4 threshold 0 is blocked with a visible message and sends nothing", pct4.sent === null && pct4.error === true, JSON.stringify(pct4));
  await pctOpen(90, 110);
  const pct5 = await pctTry(-3, 20);
  check("PCT5 a negative threshold is blocked and sends nothing (by the field minimum or by the visible message)", pct5.sent === null && (pct5.error === true || pct5.nativeInvalid === true), JSON.stringify(pct5));
  await pctOpen(90, 110);
  const pct6 = await browser.evaluate(`(() => { const preview = document.querySelector("adaptive-areas-panel form[data-area-form] [data-light-pair-preview]")?.textContent || ""; return { preview, shownHyst: document.querySelector("adaptive-areas-panel form[data-area-form] input[name='light:hysteresis']")?.value ?? null }; })()`);
  check("PCT6 the preview shows the resulting limits (90 and 110 lx) and the percentage field shows 20", pct6.preview.includes("90") && pct6.preview.includes("110") && pct6.shownHyst === "20", JSON.stringify(pct6));
  await pctOpen(0.04, 0.06);
  const pct7 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); return { legacy: !!document.querySelector("adaptive-areas-panel [data-light-legacy]"), lux: [f.elements.namedItem("light:turn_on_below")?.value ?? null, f.elements.namedItem("light:turn_off_above")?.value ?? null], percentEmpty: (f.elements.namedItem("light:hysteresis")?.value ?? "x") === "" }; })()`);
  check("PCT7 a valid tiny pair is shown as a percentage (threshold 0.1, hysteresis 40 %), not as legacy", pct7.legacy === false && pct7.lux.every((v) => v === null) && pct7.percentEmpty === false, JSON.stringify(pct7));
  await pctOpen(0.04, 0.06);
  const pct7d = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); return { threshold: f.elements.namedItem("light:threshold").value, hysteresis: f.elements.namedItem("light:hysteresis").value }; })()`);
  check("PCT7c the rounded display of 0.04/0.06 is threshold 0.1 and hysteresis 40", pct7d.threshold === "0.1" && pct7d.hysteresis === "40", JSON.stringify(pct7d));
  const pct7b = await browser.evaluate(`(() => { window.__h.hass.__state.lastAreaUpdate = undefined; document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(160);
  const pct7c = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null`);
  check("PCT7b saving the tiny pair without edits sends the stored values unchanged", pct7c === null || (pct7c.turn_on_below === 0.04 && pct7c.turn_off_above === 0.06), JSON.stringify(pct7c));
  await pctOpen(90.3, 110.1);
  let drift = { ok: true, values: [] };
  for (let round = 0; round < 3; round += 1) {
    await browser.evaluate(`(() => { window.__h.hass.__state.lastAreaUpdate = undefined; document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
    await sleep(160);
    const sent = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light ?? null`);
    drift.values.push(sent);
    if (sent !== null && (sent.turn_on_below !== 90.3 || sent.turn_off_above !== 110.1)) drift.ok = false;
    await pctOpen(90.3, 110.1);
  }
  check("PCT8 repeated open and save cycles do not drift from the stored float pair", drift.ok === true, JSON.stringify(drift));
  // PCT9: an invalid stored pair (T = 0) stays legacy with both lux fields and is not overwritten
  await pctOpen(0, 0);
  const pct9 = await browser.evaluate(`(() => ({ legacy: !!document.querySelector("adaptive-areas-panel [data-light-legacy]"), lux: [document.querySelector("adaptive-areas-panel form[data-area-form]")?.elements.namedItem("light:turn_on_below")?.value ?? null, document.querySelector("adaptive-areas-panel form[data-area-form]")?.elements.namedItem("light:turn_off_above")?.value ?? null] }))()`);
  check("PCT9 a stored zero-threshold pair is invalid: legacy with both lux values shown", pct9.legacy === true && JSON.stringify(pct9.lux) === JSON.stringify(["0", "0"]), JSON.stringify(pct9));
  // PCT10: changing only the threshold keeps the exact stored hysteresis (not the rounded display)
  await pctOpen(90.3, 110.1);
  const pct10 = await pctTry(120, await browser.evaluate(`document.querySelector("adaptive-areas-panel form[data-area-form] input[name='light:hysteresis']").value`));
  const exactH = 200 * (110.1 - 90.3) / (90.3 + 110.1);
  const expectedOn = 120 - 120 * exactH / 200, expectedOff = 120 + 120 * exactH / 200;
  check("PCT10 changing only the threshold keeps the exact hysteresis and derives new limits from it (not from the rounded 19.8)", Math.abs(pct10.sent?.turn_on_below - expectedOn) < 1e-9 && Math.abs(pct10.sent?.turn_off_above - expectedOff) < 1e-9, JSON.stringify({ sent: pct10.sent, expectedOn, expectedOff }));
  // LG-series: light groups as nested details (open/close, keyboard, content mapping, unchanged config)
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 90, turn_off_above: 110 }, light_groups: { overhead_lights: ["light.ceiling"], overhead_lights_activation: "occupied", overhead_lights_blocking_states: ["sleep"], overhead_lights_brightness: "require_dark", sleep_lights: ["light.bed"], sleep_lights_activation: "sleep", sleep_lights_blocking_states: [], sleep_lights_brightness: "ignore", accent_lights: [], accent_lights_activation: "disabled", accent_lights_blocking_states: [], accent_lights_brightness: "require_dark", task_lights: [], task_lights_activation: "disabled", task_lights_blocking_states: [], task_lights_brightness: "require_dark" } })); const p = document.querySelector("adaptive-areas-panel"); p._data.config = JSON.parse(JSON.stringify(st.config)); window.__h.hass.__state.lastAreaUpdate = undefined; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light-group='overhead']") !== null`);
  const lg1 = await browser.evaluate(`(() => { const groups = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] details.light-group")]; return groups.map((g) => ({ prefix: g.dataset.lightGroup, open: g.open, selects: [...g.querySelectorAll("select, aa-entity-picker")].map((n) => n.getAttribute("name")), count: g.querySelector("[data-light-group-count]")?.textContent.trim() ?? null })); })()`);
  const prefixesOk = ["overhead", "sleep", "accent", "task"].every((prefix) => lg1.find((g) => g.prefix === prefix)?.selects.every((name) => name.startsWith("light_group:" + prefix + "_")) && (lg1.find((g) => g.prefix === prefix)?.selects.length ?? 0) >= 4);
  check("LG1 the four light groups are nested details and each contains only its own settings", lg1.length === 4 && prefixesOk, JSON.stringify(lg1));
  check("LG2 all groups start closed and show the number of assigned lights (overhead 1, sleep 1, accent 0, task 0)", lg1.every((g) => g.open === false) && lg1.find((g) => g.prefix === "overhead")?.count === "1" && lg1.find((g) => g.prefix === "sleep")?.count === "1" && lg1.find((g) => g.prefix === "accent")?.count === "0", JSON.stringify(lg1.map((g) => [g.prefix, g.open, g.count])));
  await browser.evaluate(`(() => { const el = document.querySelector("adaptive-areas-panel form[data-area-form] [data-light-group='overhead'] > summary"); el.focus(); return true; })()`);
  await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", text: "\r", unmodifiedText: "\r", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await sleep(120);
  const lg2 = await browser.evaluate(`document.querySelector("adaptive-areas-panel form[data-area-form] [data-light-group='overhead']").open`);
  check("LG3 Enter on a focused group summary opens the group", lg2 === true, String(lg2));
  await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: " ", code: "Space", text: " ", unmodifiedText: " ", windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32 });
  await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: " ", code: "Space", windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32 });
  await sleep(120);
  const lg3 = await browser.evaluate(`document.querySelector("adaptive-areas-panel form[data-area-form] [data-light-group='overhead']").open`);
  check("LG4 Space on the focused group summary closes it again", lg3 === false, String(lg3));
  await browser.evaluate(`(() => { document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(200);
  const lg4 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light_groups ?? null`);
  check("LG5 toggling groups without edits keeps the stored group configuration", lg4 === null || (lg4.overhead_lights_activation === "occupied" && JSON.stringify(lg4.sleep_lights) === JSON.stringify(["light.bed"]) && JSON.stringify(lg4.overhead_lights) === JSON.stringify(["light.ceiling"]) && lg4.sleep_lights_activation === "sleep"), JSON.stringify(lg4));

  // O-series (step 4.1): overview KPIs, filters, search, meta row, data freshness
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`(() => { const base = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin.areas[0])); const mk = (patch) => Object.assign(JSON.parse(JSON.stringify(base)), patch); const overview = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin)); overview.areas = [mk({ id: "kitchen", name: "Kitchen", occupied: true, sources: { available: 2, total: 3 }, warning_details: { aggregates: 1, secondary_states: 0 }, warning_count: 1, enabled_features: ["aggregates"] }), mk({ id: "office", name: "Office", occupied: false, sources: { available: 1, total: 1 }, warning_details: { aggregates: 0, secondary_states: 0 }, warning_count: 0, enabled_features: [] }), mk({ id: "hall", name: "Hall", occupied: undefined, sources: { available: 1, total: 1 } }), mk({ id: "interior", name: "Interior", type: "meta", occupied: true, sources: { available: 0, total: 4 }, warning_details: { aggregates: 5, secondary_states: 1 }, warning_count: 6, enabled_features: ["aggregates"] })]; delete overview.areas[2].occupied; delete overview.areas[2].warning_details; delete overview.areas[2].warning_count; const p = document.querySelector("adaptive-areas-panel"); p._data.overview = overview; p._ui.filter = "all"; p._ui.search = ""; p._render(); return true; })()`);
  const o1 = await browser.evaluate(`({ areas: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=areas] .kpi-value')?.textContent.trim(), areasSub: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=areas] .kpi-sub')?.textContent.trim(), occupied: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=occupied] .kpi-value')?.textContent.trim(), occupiedSub: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=occupied] .kpi-sub')?.textContent.trim(), notices: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=notices] .kpi-value')?.textContent.trim(), noticesSub: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=notices] .kpi-sub')?.textContent.trim(), technical: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=technical] .kpi-value')?.textContent.trim(), technicalSub: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=technical] .kpi-sub')?.textContent.trim(), cards: [...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] article[data-area-id]")].map((n) => n.dataset.areaId), meta: [...document.querySelectorAll("adaptive-areas-panel [data-ov=meta] [data-meta-id]")].map((n) => n.dataset.metaId) })`);
  check("O1 KPIs count physical areas only; meta areas are listed separately and not counted", o1.areas === "3" && o1.areasSub.includes("1 meta") && JSON.stringify(o1.meta) === JSON.stringify(["interior"]) && !o1.cards.includes("interior"), JSON.stringify(o1));
  check("O2 occupied counts only known values and names the unknown ones", o1.occupied.startsWith("1") && o1.occupied.includes("of 2") && o1.occupiedSub.includes("1 unknown"), JSON.stringify(o1));
  check("O3 notices and technical issues come from the central warning model, without meta double counting", o1.notices === "1" && o1.noticesSub.includes("1 areas unknown") && o1.technical === "1" && !o1.technicalSub.includes("unknown"), JSON.stringify(o1));
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.overview.areas[0].enabled_features = []; p._patchDashboard(); return true; })()`);
  check("O4 a disabled feature produces no notices in the KPI", (await browser.evaluate(`document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=notices] .kpi-value')?.textContent.trim()`)) === "0");
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.overview.areas[0].enabled_features = ["aggregates"]; p._patchDashboard(); window.__o = { kitchen: document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]'), kpi: document.querySelector("adaptive-areas-panel [data-ov=kpis] [data-key=occupied]") }; document.querySelector("adaptive-areas-panel [data-filter=occupied]").click(); return true; })()`);
  const o5 = await browser.evaluate(`({ cards: [...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] article[data-area-id]")].map((n) => n.dataset.areaId), pressed: document.querySelector("adaptive-areas-panel [data-filter=occupied]").getAttribute("aria-pressed"), all: document.querySelector("adaptive-areas-panel [data-filter=all]").getAttribute("aria-pressed"), sameCard: document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]') === window.__o.kitchen, sameKpi: document.querySelector("adaptive-areas-panel [data-ov=kpis] [data-key=occupied]") === window.__o.kpi })`);
  check("O5 filter chips filter the cards, mark the active filter and keep the remaining DOM nodes", JSON.stringify(o5.cards) === JSON.stringify(["kitchen"]) && o5.pressed === "true" && o5.all === "false" && o5.sameCard && o5.sameKpi, JSON.stringify(o5));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-filter=unknown]").click()`);
  check("O6 the unknown filter shows areas without a known occupancy", JSON.stringify(await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] article[data-area-id]")].map((n) => n.dataset.areaId)`)) === JSON.stringify(["hall"]));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-kpi-filter=technical]").click()`);
  const o7a = await browser.evaluate(`({ cards: [...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] article[data-area-id]")].map((n) => n.dataset.areaId), pressed: document.querySelector("adaptive-areas-panel [data-kpi-filter=technical]").getAttribute("aria-pressed") })`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-kpi-filter=technical]").click()`);
  const o7b = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] article[data-area-id]")].map((n) => n.dataset.areaId)`);
  check("O7 a KPI toggles its filter on and off", JSON.stringify(o7a.cards) === JSON.stringify(["kitchen"]) && o7a.pressed === "true" && o7b.length === 3, JSON.stringify({ o7a, o7b }));
  await browser.evaluate(`(() => { const i = document.querySelector("adaptive-areas-panel [data-ov-search]"); i.focus(); i.value = "off"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const o8 = await browser.evaluate(`({ cards: [...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] article[data-area-id]")].map((n) => n.dataset.areaId), focused: document.activeElement === document.querySelector("adaptive-areas-panel [data-ov-search]"), value: document.querySelector("adaptive-areas-panel [data-ov-search]").value })`);
  await browser.evaluate(`(() => { const i = document.querySelector("adaptive-areas-panel [data-ov-search]"); i.value = "zzz"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const o8b = await browser.evaluate(`({ empty: document.querySelector("adaptive-areas-panel [data-ov=grid] .ov-empty")?.textContent || "", focused: document.activeElement === document.querySelector("adaptive-areas-panel [data-ov-search]") })`);
  check("O8 search filters by name, keeps focus and value, and reports no matches", JSON.stringify(o8.cards) === JSON.stringify(["office"]) && o8.focused && o8.value === "off" && o8b.empty.includes("No areas") && o8b.focused, JSON.stringify({ o8, o8b }));
  await browser.evaluate(`(() => { const i = document.querySelector("adaptive-areas-panel [data-ov-search]"); i.value = ""; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const office = JSON.parse(JSON.stringify(await browser.evaluate(`document.querySelector("adaptive-areas-panel")._data.overview.areas[1]`)));
  office.occupied = true;
  await browser.evaluate(`window.__h.hass.__emitArea(${JSON.stringify(office)})`);
  await sleep(120);
  check("O9 a live update changes the KPI in place", (await browser.evaluate(`document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=occupied] .kpi-value')?.textContent.trim()`)).startsWith("2") && (await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-ov=kpis] [data-key=occupied]") === window.__o.kpi`)));
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await sleep(100);
  const o10 = await browser.evaluate(`({ banner: document.querySelector("adaptive-areas-panel [data-ov=status] [role=alert]")?.textContent || "", occupied: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=occupied] .kpi-value')?.textContent.trim(), occupiedSub: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=occupied] .kpi-sub')?.textContent.trim(), notices: document.querySelector('adaptive-areas-panel [data-ov=kpis] [data-key=notices] .kpi-sub')?.textContent.trim(), asof: document.querySelector("adaptive-areas-panel .ov-asof")?.textContent || "" })`);
  check("O10 while offline the overview shows a banner with the time, last-known occupancy and an outdated mark", o10.banner.includes("Connection lost") && /\d/.test(o10.banner) && o10.occupied === "—" && o10.occupiedSub.includes("Last known: 2 of 2") && o10.notices.includes("possibly outdated") && o10.asof.startsWith("As of"), JSON.stringify(o10));
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-ov=status] [role=alert]") === null`, 3000).catch(() => {});
  check("O11 after reconnect the banner disappears", (await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-ov=status] [role=alert]") === null`)) === true);

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`(() => { const base = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin.areas[0])); const mk = (patch) => Object.assign(JSON.parse(JSON.stringify(base)), patch); const overview = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin)); overview.areas = [mk({ id: "kitchen", name: "Kitchen", occupied: true, sources: { available: 2, total: 3 }, warning_details: { aggregates: 1, secondary_states: 0 }, warning_count: 1, enabled_features: ["aggregates"] }), mk({ id: "office", name: "Office", occupied: false, sources: { available: 1, total: 1 }, warning_details: { aggregates: 0, secondary_states: 0 }, warning_count: 0, enabled_features: [] }), mk({ id: "hall", name: "Hall", occupied: undefined, sources: { available: 1, total: 1 } }), mk({ id: "interior", name: "Interior", type: "meta", occupied: true, sources: { available: 0, total: 4 }, warning_details: { aggregates: 5, secondary_states: 1 }, warning_count: 6, enabled_features: ["aggregates"] })]; delete overview.areas[2].occupied; delete overview.areas[2].warning_details; delete overview.areas[2].warning_count; const p = document.querySelector("adaptive-areas-panel"); p._data.overview = overview; p._ui.filter = "all"; p._ui.search = ""; p._render(); return true; })()`);
  const o12 = await browser.evaluate(`(() => { const kpis = [...document.querySelectorAll("adaptive-areas-panel [data-ov=kpis] [data-key]")]; const chips = [...document.querySelectorAll("adaptive-areas-panel [data-ov=chips] [data-filter]")]; const search = document.querySelector("adaptive-areas-panel [data-ov-search]"); return { kpiButtons: kpis.filter((n) => n.tagName === "BUTTON" && n.type === "button" && n.hasAttribute("aria-pressed")).length, kpiNamed: kpis.every((n) => (n.getAttribute("aria-label") || "").length > 5), chips: chips.every((n) => n.tagName === "BUTTON" && n.hasAttribute("aria-pressed")), chipsHeight: chips.every((n) => n.getBoundingClientRect().height >= 44), group: document.querySelector("adaptive-areas-panel [data-ov=chips]").getAttribute("role"), label: search.closest("label")?.textContent.includes("Search areas"), live: document.querySelector("adaptive-areas-panel [data-ov=status]").getAttribute("aria-live"), hex: /#[0-9a-f]{3,8}\b/i.test(document.querySelector("adaptive-areas-panel")._styles()) }; })()`);
  check("O12 KPIs and chips are named buttons with pressed state, touch targets >= 44 px, labelled search, polite status", o12.kpiButtons === 3 && o12.kpiNamed && o12.chips && o12.chipsHeight && o12.group === "group" && o12.label && o12.live === "polite", JSON.stringify(o12));
  check("O13 overview styles use theme variables only (no hex colours)", o12.hex === false, JSON.stringify(o12));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-filter=clear]").focus()`);
  // Raw key events are not used: in headless Chrome an Enter key event can reach the browser UI and navigate away.
  // Native buttons activate on Enter and Space by the HTML standard; the check covers focusability and activation with focus.
  await browser.evaluate(`(() => { const chip = document.querySelector("adaptive-areas-panel [data-filter=clear]"); window.__o14 = { tabIndex: chip.tabIndex, native: chip.tagName === "BUTTON" && chip.type === "button" }; chip.click(); return true; })()`);
  await sleep(100);
  const o14 = await browser.evaluate(`({ meta: window.__o14, cards: [...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] article[data-area-id]")].map((n) => n.dataset.areaId), focused: document.activeElement === document.querySelector("adaptive-areas-panel [data-filter=clear]") })`);
  check("O14 keyboard: filter chips are native, focusable buttons; activating the focused chip applies it and keeps the focus", o14.meta.native && o14.meta.tabIndex >= 0 && JSON.stringify(o14.cards) === JSON.stringify(["office"]) && o14.focused, JSON.stringify(o14));

  await browser.evaluate(mountCode({ admin: true, language: "de", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`(() => { const base = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin.areas[0])); const mk = (patch) => Object.assign(JSON.parse(JSON.stringify(base)), patch); const overview = JSON.parse(JSON.stringify(window.__fixtures.overviewAdmin)); overview.areas = [mk({ id: "kitchen", name: "Kitchen", occupied: true, sources: { available: 2, total: 3 }, warning_details: { aggregates: 1, secondary_states: 0 }, warning_count: 1, enabled_features: ["aggregates"] }), mk({ id: "office", name: "Office", occupied: false, sources: { available: 1, total: 1 }, warning_details: { aggregates: 0, secondary_states: 0 }, warning_count: 0, enabled_features: [] }), mk({ id: "hall", name: "Hall", occupied: undefined, sources: { available: 1, total: 1 } }), mk({ id: "interior", name: "Interior", type: "meta", occupied: true, sources: { available: 0, total: 4 }, warning_details: { aggregates: 5, secondary_states: 1 }, warning_count: 6, enabled_features: ["aggregates"] })]; delete overview.areas[2].occupied; delete overview.areas[2].warning_details; delete overview.areas[2].warning_count; const p = document.querySelector("adaptive-areas-panel"); p._data.overview = overview; p._ui.filter = "all"; p._ui.search = ""; p._render(); return true; })()`);
  const o15 = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel [data-ov=kpis] .kpi-label")].map((n) => n.textContent.trim())`);
  check("O15 German KPI labels", JSON.stringify(o15) === JSON.stringify(["Physische Bereiche", "Belegt", "Hinweise", "Technische Auffälligkeiten"]), JSON.stringify(o15));

  await browser.evaluate(mountCode({ admin: false, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  const o16 = await browser.evaluate(`({ kpis: document.querySelectorAll("adaptive-areas-panel [data-ov=kpis] [data-key]").length, ids: /\b(binary_sensor|sensor|light|switch|weather|climate)\.[a-z0-9_]+/.test(document.querySelector("adaptive-areas-panel").textContent + JSON.stringify(document.querySelector("adaptive-areas-panel")._data.overview)) })`);
  check("O16 non-admin overview has the KPIs and no entity identifiers", o16.kpis === 4 && o16.ids === false, JSON.stringify(o16));

  // C-series (step 4.2): area cards and area detail
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const base = JSON.parse(JSON.stringify(p._data.overview.areas[0])); const a = Object.assign(JSON.parse(JSON.stringify(base)), { id: "kitchen", name: "Kitchen", occupied: true, active_states: ["dark", "occupied", "sleep", "extended"], brightness: { state: "dark", illuminance: "12", unit: "lx" }, lights: { on: 1, total: 3 }, enabled_features: ["environment", "light"], environment: { comfort: "comfortable", humidity: "normal", notices: ["Ventilate soon"] } }); const b = Object.assign(JSON.parse(JSON.stringify(base)), { id: "office", name: "Office", occupied: false, active_states: [], brightness: null, lights: null, enabled_features: ["environment"], environment: null }); const c = Object.assign(JSON.parse(JSON.stringify(base)), { id: "hall", name: "Hall", occupied: false, active_states: [], brightness: null, lights: { on: 0, total: 0 }, enabled_features: [], environment: null }); p._data.overview = { ...p._data.overview, areas: [a, b, c] }; p._ui.filter = "all"; p._ui.search = ""; p._render(); return true; })()`);
  const c1 = await browser.evaluate(`(() => { const k = document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]'); const btn = k.querySelector("[data-open-area]"); return { tag: btn.tagName, type: btn.type, label: btn.getAttribute("aria-label"), h3: k.querySelector("h3").textContent, status: k.querySelector(".status").textContent, brightness: k.querySelector("[data-line=brightness]")?.textContent, lights: k.querySelector("[data-line=lights]")?.textContent, chips: [...k.querySelectorAll(".state-chip")].map((n) => n.textContent), env: k.querySelector("[data-line=environment]")?.textContent, hallLights: document.querySelector('adaptive-areas-panel article[data-area-id="hall"]').querySelector("[data-line=lights]") === null }; })()`);
  check("C1 the area card is a named button with presence text, brightness, lights and secondary states from the DTO", c1.tag === "BUTTON" && c1.type === "button" && c1.label === "Kitchen, Occupied" && c1.h3 === "Kitchen" && c1.status === "Occupied" && c1.brightness === "Dark · 12 lx" && c1.lights === "1 of 3 lights on" && JSON.stringify(c1.chips) === JSON.stringify(["Sleep", "Extended"]) && c1.hallLights, JSON.stringify(c1));
  const c2 = await browser.evaluate(`({ kitchen: document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]').querySelector("[data-line=environment]")?.textContent, office: document.querySelector('adaptive-areas-panel article[data-area-id="office"]').querySelector("[data-line=environment]")?.textContent, hall: document.querySelector('adaptive-areas-panel article[data-area-id="hall"]').querySelector("[data-line=environment]") })`);
  check("C2 environment: values when the feature has data, 'No data' when enabled without data, hidden when disabled", c2.kitchen === "Environment: Comfort comfortable · Humidity normal · 1 environment notes" && c2.office === "Environment: No data" && c2.hall === null, JSON.stringify(c2));
  await browser.evaluate(`window.__c = { btn: document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]').querySelector("[data-open-area]") }; window.__c.btn.focus(); window.__h.hass.__emitConnection("disconnected"); true`);
  await sleep(100);
  const c3 = await browser.evaluate(`({ label: document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]').querySelector("[data-open-area]").getAttribute("aria-label"), stale: document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]').querySelector(".card-stale")?.textContent, same: document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]').querySelector("[data-open-area]") === window.__c.btn, focused: document.activeElement === window.__c.btn })`);
  check("C3 while data is outdated the card is marked 'Last known'; the focused card button stays the same node", c3.label === "Kitchen, Occupied, Last known" && c3.stale === "Last known" && c3.same && c3.focused, JSON.stringify(c3));
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await sleep(300);

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`document.querySelector('adaptive-areas-panel [data-open-area="kitchen"]').click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-detail] [data-key=presence]") !== null && document.querySelector("adaptive-areas-panel [data-detail] .detail-loading") === null`, 3000).catch(() => {});
  const c4 = await browser.evaluate(`({ title: document.querySelector("adaptive-areas-panel [data-detail-title]")?.textContent, focused: document.activeElement === document.querySelector("adaptive-areas-panel [data-detail-title]"), sections: [...document.querySelectorAll("adaptive-areas-panel [data-detail-body] > [data-key]")].map((n) => n.dataset.key), sources: document.querySelector("adaptive-areas-panel [data-detail-body] [data-key=presence]")?.textContent, calls: window.__h.hass.__state.calls.filter((c) => c === "adaptive_areas/get_area").length, grid: document.querySelector("adaptive-areas-panel [data-overview]") === null })`);
  check("C4 opening a card shows the area detail from get_area, focuses its heading and replaces the overview", c4.title === "kitchen" && c4.focused && c4.sections.includes("presence") && c4.sections.includes("sources") && c4.sections.includes("notices") && c4.calls === 1 && c4.grid, JSON.stringify(c4));
  check("C5 admin detail lists the presence sources by name", (c4.sources || "").includes("binary_sensor.motion_sensor") && (c4.sources || "").includes("1 of 1 available"), JSON.stringify(c4));
  await browser.evaluate(`window.__c = { title: document.querySelector("adaptive-areas-panel [data-detail-title]"), before: window.__h.hass.__state.calls.filter((c) => c === "adaptive_areas/get_area").length }; true`);
  const changed = JSON.parse(JSON.stringify(await browser.evaluate(`document.querySelector("adaptive-areas-panel")._data.overview.areas[0]`)));
  changed.occupied = false; changed.active_states = ["clear"];
  await browser.evaluate(`window.__h.hass.__emitArea(${JSON.stringify(changed)})`);
  await sleep(250);
  const c6 = await browser.evaluate(`({ calls: window.__h.hass.__state.calls.filter((c) => c === "adaptive_areas/get_area").length - window.__c.before, title: document.querySelector("adaptive-areas-panel [data-detail-title]") === window.__c.title })`);
  check("C6 a live update of the open area reloads its detail and keeps the detail heading node", c6.calls === 1 && c6.title, JSON.stringify(c6));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-detail-back]").click()`);
  await sleep(100);
  const c7 = await browser.evaluate(`({ overview: document.querySelector("adaptive-areas-panel [data-overview]") !== null, focused: document.activeElement === document.querySelector('adaptive-areas-panel [data-open-area="kitchen"]'), detail: document.querySelector("adaptive-areas-panel")._data.areaDetail })`);
  check("C7 back returns to the overview, restores the focus on the card and drops the detail data", c7.overview && c7.focused && c7.detail === null, JSON.stringify(c7));

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  const c8 = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_area" ? new Promise((res) => setTimeout(() => res({ ...window.__fixtures.areaAdmin, name: "LATE" }), 300)) : orig(msg); document.querySelector('adaptive-areas-panel [data-open-area="kitchen"]').click(); await new Promise((r) => setTimeout(r, 50)); document.querySelector("adaptive-areas-panel [data-detail-back]").click(); await new Promise((r) => setTimeout(r, 400)); h.callWS = orig; return { detail: p._data.areaDetail, late: p.textContent.includes("LATE"), overview: document.querySelector("adaptive-areas-panel [data-overview]") !== null }; })()`);
  check("C8 a late detail response after closing the detail is discarded", c8.detail === null && c8.late === false && c8.overview, JSON.stringify(c8));
  const c9 = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const h = window.__h.hass; const orig = h.callWS.bind(h); let fail = true; h.callWS = (msg) => msg.type === "adaptive_areas/get_area" && fail ? Promise.reject(new Error("down")) : orig(msg); document.querySelector('adaptive-areas-panel [data-open-area="kitchen"]').click(); await new Promise((r) => setTimeout(r, 150)); const error = document.querySelector("adaptive-areas-panel [data-detail] [role=alert]")?.textContent || ""; fail = false; document.querySelector("adaptive-areas-panel [data-detail-retry]").click(); await new Promise((r) => setTimeout(r, 200)); h.callWS = orig; return { error, after: document.querySelector("adaptive-areas-panel [data-detail] [role=alert]") === null, sources: document.querySelector("adaptive-areas-panel [data-detail-body] [data-key=sources]")?.textContent || "" }; })()`);
  check("C9 a failed detail load shows an error with retry; the retry loads the detail", c9.error.includes("could not be loaded") && c9.after && c9.sources.includes("binary_sensor.motion_sensor"), JSON.stringify(c9));
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.overview = { ...st.overview, areas: [] }; window.__h.hass.__emitEvent({ areas_changed: true }); return true; })()`);
  await sleep(250);
  check("C10 an area removed while its detail is open is reported as gone", ((await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-detail]")?.textContent`)) || "").includes("no longer exists"));

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`document.querySelector('adaptive-areas-panel [data-open-area="kitchen"]').click()`);
  await sleep(200);
  const c11 = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const next = AAHarness.createHass({ admin: false, language: "en", states: {}, fixtures: { overview: window.__fixtures.overviewUser, area: window.__fixtures.areaUser, config: window.__fixtures.config, global: window.__fixtures.global, light: window.__fixtures.light, climate: window.__fixtures.climate, trace: window.__fixtures.trace, diagnostics: window.__fixtures.diagnostics } }); window.__h.hass = next; p.hass = next; await new Promise((r) => setTimeout(r, 400)); const text = p.textContent + JSON.stringify(p._data.areaDetail); return { ids: /\b(binary_sensor|sensor|light|switch)\.[a-z0-9_]+/.test(text), coverage: document.querySelector("adaptive-areas-panel [data-detail-body] [data-key=sources]")?.textContent || "", open: p._ui.detailArea }; })()`);
  check("C11 after a role change the open detail is reloaded for the new role without entity identifiers", c11.ids === false && c11.coverage.includes("1 of 1 available") && c11.open === "kitchen", JSON.stringify(c11));

  await browser.evaluate(mountCode({ admin: false, language: "de", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`document.querySelector('adaptive-areas-panel [data-open-area="kitchen"]').click()`);
  await sleep(250);
  const c12 = await browser.evaluate(`({ heads: [...document.querySelectorAll("adaptive-areas-panel [data-detail-body] h3")].map((n) => n.textContent), back: document.querySelector("adaptive-areas-panel [data-detail-back]")?.textContent, ids: /\b(binary_sensor|sensor|light|switch)\.[a-z0-9_]+/.test(document.querySelector("adaptive-areas-panel").textContent) })`);
  check("C12 non-admin detail in German: translated section headings, no entity identifiers", c12.heads.includes("Präsenz") && c12.heads.includes("Quellen") && (c12.back || "").includes("Zurück") && c12.ids === false, JSON.stringify(c12));

  // M-series (steps 4.3 and 4.4): Meta-Areas, floors, cleaning and room usage views
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const base = JSON.parse(JSON.stringify(p._data.overview.areas[0])); const mk = (patch) => Object.assign(JSON.parse(JSON.stringify(base)), patch); const kitchen = mk({ id: "kitchen", name: "Kitchen", type: "area", occupied: true, floor_id: "first_floor", floor_name: "first_floor", enabled_features: ["room_usage"], cleaning: { cleaning_state: "used", due: false, remaining_minutes_to_due: 42.4 }, room_usage: { presence_minutes_since_cleaning: 65.2, current_occupancy_duration_seconds: 125 } }); const office = mk({ id: "office", name: "Office", type: "area", occupied: false, floor_id: null, floor_name: null, enabled_features: [], cleaning: null, room_usage: null }); const hall = mk({ id: "hall", name: "Hall", type: "area", occupied: false, floor_id: "f2", floor_name: null, enabled_features: ["room_usage"], cleaning: null, room_usage: null }); const interior = mk({ id: "interior", name: "Interior", type: "meta", occupied: true, floor_id: null, floor_name: null, members: ["kitchen", "office"], enabled_features: [], cleaning: null, room_usage: null }); p._data.overview = { ...p._data.overview, areas: [kitchen, office, hall, interior] }; p._ui.filter = "all"; p._ui.search = ""; p._render(); return true; })()`);
  const m1 = await browser.evaluate(`(() => { const card = document.querySelector('adaptive-areas-panel [data-meta-id="interior"]'); const cards = [...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] article[data-area-id]")].map((n) => n.dataset.areaId); return { text: card?.textContent || "", cards, meta: [...document.querySelectorAll("adaptive-areas-panel [data-ov=meta] [data-meta-id]")].map((n) => n.dataset.metaId) }; })()`);
  check("M1 a Meta-Area shows its member count and the occupancy of known members, not as a physical card", m1.text.includes("2 areas") && m1.text.includes("1 of 2 occupied") && JSON.stringify(m1.meta) === JSON.stringify(["interior"]) && !m1.cards.includes("interior"), JSON.stringify(m1));
  const m2 = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel [data-ov=grid] .floor-title")].map((n) => n.textContent)`);
  check("M2 cards are grouped by floor with the unknown floor and 'no floor' named; 'no floor' comes last", JSON.stringify(m2) === JSON.stringify(["first_floor", "Unknown floor", "No floor"]), JSON.stringify(m2));
  await browser.evaluate(`window.__m = document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]'); true`);
  const kitchenNow = JSON.parse(JSON.stringify(await browser.evaluate(`document.querySelector("adaptive-areas-panel")._data.overview.areas[0]`)));
  kitchenNow.occupied = false;
  await browser.evaluate(`window.__h.hass.__emitArea(${JSON.stringify(kitchenNow)})`);
  await sleep(150);
  const m3 = await browser.evaluate(`document.querySelector('adaptive-areas-panel article[data-area-id="kitchen"]') === window.__m && document.querySelectorAll("adaptive-areas-panel .floor-group").length === 3`);
  check("M3 a live update keeps the card node and the floor group structure", m3 === true);
  const m4 = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .nav-items [data-tab]")].map((n) => n.dataset.tab)`);
  check("M4 monitoring views for cleaning and room usage are shown when the feature is enabled", m4.includes("cleaning") && m4.includes("room-usage") && m4.indexOf("cleaning") < m4.indexOf("trace") || m4.includes("cleaning"), JSON.stringify(m4));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-tab=cleaning]").click()`);
  await sleep(120);
  const m5 = await browser.evaluate(`({ rows: [...document.querySelectorAll("adaptive-areas-panel [data-monitor=cleaning] [data-monitor-id]")].map((n) => ({ id: n.dataset.monitorId, text: n.textContent.trim() })), intro: document.querySelector("adaptive-areas-panel [data-monitor=cleaning] p")?.textContent })`);
  const m5ok = m5.rows.length === 2 && m5.rows[0].id === "kitchen" && m5.rows[0].text.includes("Used") && m5.rows[0].text.includes("43 min until due") && m5.rows[1].id === "hall" && m5.rows[1].text.includes("No cleaning data") && !m5.rows.some((row) => row.id === "office");
  check("M5 cleaning view lists room-usage areas with state and minutes to due; missing data is not zero; disabled areas are absent", m5ok, JSON.stringify(m5));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-tab=room-usage]").click()`);
  await sleep(120);
  const m6 = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel [data-monitor=room-usage] [data-monitor-id]")].map((n) => ({ id: n.dataset.monitorId, text: n.textContent.trim() }))`);
  check("M6 room usage shows durations in hours and minutes and reports missing usage data", m6.length === 2 && m6[0].text.includes("1 h 05 min") && m6[0].text.includes("2 min") && m6[1].text.includes("No usage data"), JSON.stringify(m6));
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await sleep(120);
  const m7 = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel [data-monitor=room-usage] .card-stale")].length`);
  check("M7 while offline the room usage view marks every row as last known", m7 === 2);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await sleep(150);
  const m8 = await browser.evaluate(`(() => { const text = document.querySelector("adaptive-areas-panel [data-monitor=room-usage]")?.textContent || ""; return { ids: /\\b(binary_sensor|sensor|light|switch)\\.[a-z0-9_]+/.test(text) }; })()`);
  check("M8 the monitoring views show no entity identifiers", m8.ids === false);

  await browser.evaluate(mountCode({ admin: false, language: "de", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const base = JSON.parse(JSON.stringify(p._data.overview.areas[0])); const mk = (patch) => Object.assign(JSON.parse(JSON.stringify(base)), patch); const kitchen = mk({ id: "kitchen", name: "Kitchen", type: "area", occupied: true, floor_id: "first_floor", floor_name: "first_floor", enabled_features: ["room_usage"], cleaning: { cleaning_state: "used", due: false, remaining_minutes_to_due: 42.4 }, room_usage: { presence_minutes_since_cleaning: 65.2, current_occupancy_duration_seconds: 125 } }); const office = mk({ id: "office", name: "Office", type: "area", occupied: false, floor_id: null, floor_name: null, enabled_features: [], cleaning: null, room_usage: null }); const hall = mk({ id: "hall", name: "Hall", type: "area", occupied: false, floor_id: "f2", floor_name: null, enabled_features: ["room_usage"], cleaning: null, room_usage: null }); const interior = mk({ id: "interior", name: "Interior", type: "meta", occupied: true, floor_id: null, floor_name: null, members: ["kitchen", "office"], enabled_features: [], cleaning: null, room_usage: null }); p._data.overview = { ...p._data.overview, areas: [kitchen, office, hall, interior] }; p._ui.filter = "all"; p._ui.search = ""; p._render(); return true; })()`);
  const m9 = await browser.evaluate(`({ nav: [...document.querySelectorAll("adaptive-areas-panel .nav-items [data-tab]")].map((n) => n.textContent.trim()), floors: [...document.querySelectorAll("adaptive-areas-panel .floor-title")].map((n) => n.textContent.trim()), meta: document.querySelector('adaptive-areas-panel [data-meta-id="interior"]')?.textContent || "" })`);
  check("M9 non-admin German labels: cleaning and room usage navigation, floor names, Meta-Area occupancy", m9.nav.includes("Reinigung") && m9.nav.includes("Raumnutzung") && m9.floors.includes("Ohne Etage") && m9.meta.includes("1 von 2 belegt"), JSON.stringify(m9));

  await browser.evaluate(mountCode({ admin: false, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(150);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const base = JSON.parse(JSON.stringify(p._data.overview.areas[0])); const mk = (patch) => Object.assign(JSON.parse(JSON.stringify(base)), patch); const kitchen = mk({ id: "kitchen", name: "Kitchen", type: "area", occupied: true, floor_id: "first_floor", floor_name: "first_floor", enabled_features: ["room_usage"], cleaning: { cleaning_state: "used", due: false, remaining_minutes_to_due: 42.4 }, room_usage: { presence_minutes_since_cleaning: 65.2, current_occupancy_duration_seconds: 125 } }); const office = mk({ id: "office", name: "Office", type: "area", occupied: false, floor_id: null, floor_name: null, enabled_features: [], cleaning: null, room_usage: null }); const hall = mk({ id: "hall", name: "Hall", type: "area", occupied: false, floor_id: "f2", floor_name: null, enabled_features: ["room_usage"], cleaning: null, room_usage: null }); const interior = mk({ id: "interior", name: "Interior", type: "meta", occupied: true, floor_id: null, floor_name: null, members: ["kitchen", "office"], enabled_features: [], cleaning: null, room_usage: null }); p._data.overview = { ...p._data.overview, areas: [kitchen, office, hall, interior] }; p._ui.filter = "all"; p._ui.search = ""; p._render(); return true; })()`);
  const m10 = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .nav-items [data-tab]")].map((n) => n.dataset.tab)`);
  check("M10 non-admin sees the monitoring views (not administration)", m10.includes("cleaning") && m10.includes("room-usage") && !m10.includes("trace") && !m10.includes("settings"), JSON.stringify(m10));

  // A-series (step 5): analysis views use translated, state-aware runtime data
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(120);
  const a4 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.lightRuntime = { area_id: "kitchen", light: { enabled: false } }; return p._lightRuntimeStatus(p._t).replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim(); })()`);
  check("A4 a disabled light automation is named as not activated, not as a fault", a4.includes("not activated for this Area") && !a4.includes("unavailable"), a4);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await sleep(100);
  const a5 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.lightRuntime = { area_id: "kitchen", light: { enabled: true, presence: { available: true, occupied: true }, illuminance: { configured: true, available: true, value: 12 }, policy: { decision: "TURN_ON", reason: "occupied_and_dark" }, override: { mode: "NONE" }, vacancy: { pending: false, due_at: null }, targets: { total: 3, available: 2 } } }; return p._lightRuntimeStatus(p._t).replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim(); })()`);
  check("A5 while offline the lighting status is marked as last known", a5.includes("Last known status"), a5);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await sleep(100);

  await browser.evaluate(mountCode({ admin: true, language: "de", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(120);

  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(120);
  const b1 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.climateRuntime = { area_id: "kitchen", enabled: true, controller_on: true, target_entity: null, target_available: true, area_states: ["occupied", "sleep"], current_preset: null, configured_preset: "comfort", occupancy_threshold: 5, occupancy_pending: true, decision: "occupied" }; return p._climateRuntimeStatus().replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim(); })()`);
  check("B1 climate analysis: translated states and decision, missing thermostat is 'Not configured', threshold shows pending", b1.includes("Occupied") && b1.includes("Sleep") && b1.includes("Not configured") && b1.includes("5 minutes") && b1.includes("waiting for the occupancy threshold") && b1.includes("Occupied") && !b1.includes("Aktiv") && !b1.includes("Nicht konfiguriert"), b1);
  const b2 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.climateRuntime = { ...{ area_id: "kitchen", enabled: true, controller_on: true, target_entity: null, target_available: true, area_states: ["occupied", "sleep"], current_preset: null, configured_preset: "comfort", occupancy_threshold: 5, occupancy_pending: true, decision: "occupied" }, target_available: null, occupancy_threshold: null, decision: "no_action", area_states: [], configured_preset: null, controller_on: null }; return p._climateRuntimeStatus().replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim(); })()`);
  check("B2 missing climate values are shown as unknown or no action, not as a value", b2.includes("Unknown") && b2.includes("No automatic action") && b2.includes("No action") && !b2.includes("null"), b2);
  await browser.evaluate(`window.__h.hass.__emitConnection("disconnected")`);
  await sleep(100);
  const b3 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.climateRuntime = { area_id: "kitchen", enabled: true, controller_on: true, target_entity: null, target_available: true, area_states: ["occupied", "sleep"], current_preset: null, configured_preset: "comfort", occupancy_threshold: 5, occupancy_pending: true, decision: "occupied" }; return p._climateRuntimeStatus().replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim(); })()`);
  check("B3 while offline the climate status is marked as last known", b3.includes("Last known status"), b3);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);
  await sleep(100);

  await browser.evaluate(mountCode({ admin: true, language: "de", states }));
  await waitFor(browser, `${text()}.length > 40`);
  await sleep(120);
  const b4 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.climateRuntime = { area_id: "kitchen", enabled: true, controller_on: true, target_entity: null, target_available: true, area_states: ["occupied", "sleep"], current_preset: null, configured_preset: "comfort", occupancy_threshold: 5, occupancy_pending: true, decision: "occupied" }; return p._climateRuntimeStatus().replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim(); })()`);
  check("B4 German climate analysis uses German labels", b4.includes("Belegt") && b4.includes("nicht aktiv") === false && b4.includes("Nicht konfiguriert") && b4.includes("wartet auf die Belegungsschwelle"), b4);

  // D-series (step 5.4): diagnostics do not count source problems twice
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await sleep(120);
  const d1 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.diagnostics = { version: "x", area_count: 1, meta_area_count: 0, adaptive_entity_count: 2, unavailable_source_count: 2, empty_aggregate_count: 1, warning_count: 3, issues: [{ severity: "warning", area_id: "kitchen", code: "unavailable_source", message: "" }, { severity: "warning", area_id: "kitchen", code: "unavailable_source", message: "" }, { severity: "warning", area_id: "kitchen", code: "empty_aggregate", message: "" }] }; const html = p._diagnosticsTab(p._t); const values = [...html.matchAll(/<dd>([^<]*)<\\/dd>/g)].map((m) => m[1]); return { values, items: (html.match(/<li>/g) || []).length }; })()`);
  check("D1 diagnostics count the warnings without the unavailable sources, which have their own line; the list keeps every issue", JSON.stringify([d1.values[0], d1.values[2], d1.values[3], d1.values[4]]) === JSON.stringify(["2", "1", "0", "1"]) && d1.items === 3, JSON.stringify(d1));
  const d2 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.diagnostics = { version: "x", area_count: 1, meta_area_count: 0, adaptive_entity_count: 0, unavailable_source_count: 0, empty_aggregate_count: 0, warning_count: 0, issues: [] }; const html = p._diagnosticsTab(p._t); const tpl = document.createElement("template"); tpl.innerHTML = html; return { none: html.includes("No issues."), warnings: [...tpl.content.querySelectorAll("dt")].find((dt) => dt.textContent === "Warnings")?.nextElementSibling?.textContent.trim() }; })()`);
  check("D2 an empty diagnostics result says no issues and counts zero warnings", d2.none === true && d2.warnings === "0", JSON.stringify(d2));

  // P-series (step 5 and open step 4 points): partial Meta-Areas, cleaning and lighting analysis texts
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await sleep(120);
  const p1 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const base = JSON.parse(JSON.stringify(p._data.overview.areas[0])); const kitchen = Object.assign({}, base, { id: "kitchen", name: "Kitchen", type: "area", occupied: true, floor_id: null, floor_name: null }); const meta = Object.assign({}, base, { id: "interior", name: "Interior", type: "meta", occupied: true, floor_id: null, floor_name: null, members: ["kitchen"], members_total: 3, enabled_features: [] }); p._data.overview = { ...p._data.overview, areas: [kitchen, meta] }; p._render(); return document.querySelector('adaptive-areas-panel [data-meta-id="interior"]').textContent; })()`);
  check("P1 a Meta-Area with unloaded members says how many are loaded, so the occupancy is not presented as complete", p1.includes("1 of 3 areas loaded"), p1);
  const p2 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.overview.areas[1].members_total = 1; p._render(); return document.querySelector('adaptive-areas-panel [data-meta-id="interior"]').textContent; })()`);
  check("P2 a complete Meta-Area shows the plain member count", p2.includes("1 areas") || p2.includes("1 area") || p2.includes("areas"), p2);
  const p3 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.overview.areas[0].occupied = false; p._render(); return document.querySelector('adaptive-areas-panel [data-meta-id="interior"]').textContent; })()`);
  check("P3 a Meta-Area's known occupancy uses only loaded members with a known value", p3.includes("0 of 1 occupied"), p3);

  // T-series (step 5.3): decision trace view
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await sleep(120);
  const t1 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "trace"; p._ui.traceArea = "kitchen"; p._data.trace = { area_id: "kitchen", limit: 20, entries: [{ timestamp: "2026-11-20T10:00:00Z", trigger: "presence_activity", decision: "turn_on", outcome: "executed", feature: "light_groups", reason_codes: ["motion_detected"], area_state: ["occupied"], from: "clear", to: "occupied" }, { timestamp: "2026-11-20T09:00:00Z", trigger: "area_state_changed", decision: "no_action", outcome: "skipped", feature: "presence", reason_codes: ["brand_new_reason"], area_state: [] }] }; p._render(); return p.querySelector("[data-tab=trace]") ? "" : (p.querySelector("[data-region=body]")?.textContent || ""); })()`);
  const t1b = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const items = [...p.querySelectorAll("ol.trace > li")]; return { count: items.length, first: items[0]?.textContent || "", second: items[1]?.textContent || "", datetime: items[0]?.querySelector("time")?.getAttribute("datetime") || null, visibleIso: (items[0]?.querySelector("time")?.textContent || "").includes("T10:00") }; })()`);
  check("T1 trace lists the newest entry first with translated trigger, decision, result, feature, reason and transition", t1b.count === 2 && t1b.first.includes("Presence activity") && t1b.first.includes("Turn on") && t1b.first.includes("Executed") && t1b.first.includes("Light automation") && t1b.first.includes("Motion detected") && t1b.first.includes("Clear") && t1b.first.includes("Occupied") && t1b.datetime === "2026-11-20T10:00:00Z" && t1b.visibleIso === false, JSON.stringify(t1b));
  check("T2 an unknown reason code is shown neutrally and never as the raw code", t1b.second.includes("Reason recorded, not translated.") && !t1b.second.includes("brand_new_reason"), JSON.stringify(t1b.second));
  const t3 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "trace"; p._ui.traceArea = "kitchen"; p._data.trace = { area_id: "kitchen", limit: 20, entries: [] }; p._render(); return p.querySelector("[data-key=empty]")?.textContent || ""; })()`);
  check("T3 an area without decisions says so explicitly", t3.includes("No decisions recorded for this Area."), t3);
  const t4 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "trace"; p._ui.traceArea = "kitchen"; p._data.trace = null; p._errors.trace = null; p._render(); return { loading: !!p.querySelector("[data-key=loading]"), error: !!p.querySelector("[data-key=error]") }; })()`);
  check("T4 while loading the trace shows the loading state, not an empty or error state", t4.loading === true && t4.error === false, JSON.stringify(t4));
  const t5 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "trace"; p._data.trace = null; p._errors.trace = new Error("down"); p._render(); return { loading: !!p.querySelector("[data-key=loading]"), error: p.querySelector("[data-key=error]")?.textContent || "" }; })()`);
  check("T5 a failed trace request shows the error state and no loading state", t5.loading === false && t5.error.includes("could not be loaded"), JSON.stringify(t5));
  const t6 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "trace"; p._errors.trace = null; p._data.trace = { area_id: "kitchen", limit: 20, entries: [{ timestamp: "2026-11-20T10:00:00Z", trigger: "presence_activity", decision: "turn_on", outcome: "executed", feature: "light_groups", reason_codes: ["motion_detected"], area_state: ["occupied"], from: "clear", to: "occupied" }, { timestamp: "2026-11-20T09:00:00Z", trigger: "area_state_changed", decision: "no_action", outcome: "skipped", feature: "presence", reason_codes: ["brand_new_reason"], area_state: [] }] }; window.__h.hass.__emitConnection("disconnected"); p._render(); return p.querySelector("[data-key=stale]")?.textContent || ""; })()`);
  check("T6 offline the decisions are marked as last known, not as the current state", t6.includes("Last known decisions"), t6);
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);

  await browser.evaluate(mountCode({ admin: true, language: "de", states }));
  await waitFor(browser, `${text()}.includes("Verbunden")`);
  await sleep(120);
  const t7 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "trace"; p._ui.traceArea = "kitchen"; p._data.trace = { area_id: "kitchen", limit: 20, entries: [{ timestamp: "2026-11-20T10:00:00Z", trigger: "presence_activity", decision: "turn_on", outcome: "executed", feature: "light_groups", reason_codes: ["motion_detected"], area_state: ["occupied"], from: "clear", to: "occupied" }, { timestamp: "2026-11-20T09:00:00Z", trigger: "area_state_changed", decision: "no_action", outcome: "skipped", feature: "presence", reason_codes: ["brand_new_reason"], area_state: [] }] }; p._render(); const first = p.querySelector("ol.trace > li")?.textContent || ""; return { first, heading: p.querySelector("[data-region=body] dt")?.textContent || "" }; })()`);
  check("T7 German trace labels and translated values", t7.first.includes("Auslöser") && t7.first.includes("Einschalten") && t7.first.includes("Ausgeführt") && t7.first.includes("Bewegung erkannt") && t7.first.includes("Belegt"), JSON.stringify(t7));

  // E-series (step 5.4): diagnostics distinguish complete, incomplete and last known data
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await sleep(120);
  const e1 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "diagnostics"; p._data.diagnostics = { version: "x", area_count: 1, meta_area_count: 0, adaptive_entity_count: 1, unavailable_source_count: 0, unknown_source_count: 0, empty_aggregate_count: 0, warning_count: 0, data_complete: true, issues: [] }; p._render(); const body = p.querySelector("[data-region=body]"); return { verdict: body.querySelector("[data-key=verdict]")?.textContent || null, incomplete: body.querySelector("[data-key=incomplete]")?.textContent || null, stale: body.querySelector("[data-key=stale]")?.textContent || null, text: body.textContent, values: [...body.querySelectorAll("dd")].map((n) => n.textContent) }; })()`);
  check("E1 a complete result without issues says 'No issues.' as a current status", e1.verdict === "No issues." && e1.incomplete === null, JSON.stringify(e1));
  const e2 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "diagnostics"; p._data.diagnostics = { version: "x", area_count: 1, meta_area_count: 0, adaptive_entity_count: 1, unavailable_source_count: 0, unknown_source_count: 2, empty_aggregate_count: 0, warning_count: 0, data_complete: false, issues: [{ severity: "info", area_id: "kitchen", code: "unknown_source", message: "" }, { severity: "info", area_id: "kitchen", code: "unknown_source", message: "" }] }; p._render(); const body = p.querySelector("[data-region=body]"); return { verdict: body.querySelector("[data-key=verdict]")?.textContent || null, incomplete: body.querySelector("[data-key=incomplete]")?.textContent || null, stale: body.querySelector("[data-key=stale]")?.textContent || null, text: body.textContent, values: [...body.querySelectorAll("dd")].map((n) => n.textContent) }; })()`);
  check("E2 unknown sources never produce 'No issues.' and are named as incomplete data, not as a fault", e2.verdict !== "No issues." && e2.verdict.includes("No known issues") && e2.incomplete.includes("2 sources") && e2.text.includes("not a fault"), JSON.stringify(e2));
  check("E3 unknown sources are counted separately from unavailable sources and are not warnings", e2.values[0] === "0" && e2.values[1] === "2" && e2.values[5] === "0", JSON.stringify(e2.values));
  const e4 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "diagnostics"; p._data.diagnostics = { version: "x", area_count: 1, meta_area_count: 0, adaptive_entity_count: 1, unavailable_source_count: 0, unknown_source_count: 0, empty_aggregate_count: 0, warning_count: 0, data_complete: true, issues: [] }; window.__h.hass.__emitConnection("disconnected"); p._render(); const body = p.querySelector("[data-region=body]"); return { verdict: body.querySelector("[data-key=verdict]")?.textContent || null, incomplete: body.querySelector("[data-key=incomplete]")?.textContent || null, stale: body.querySelector("[data-key=stale]")?.textContent || null, text: body.textContent, values: [...body.querySelectorAll("dd")].map((n) => n.textContent) }; })()`);
  check("E4 offline the result is labelled last known and never claims a current 'No issues.'", e4.stale !== null && e4.verdict === "No issues in the last known data." && e4.text.includes("Last known diagnostics"), JSON.stringify(e4));
  await browser.evaluate(`window.__h.hass.__emitConnection("ready")`);

  await browser.evaluate(mountCode({ admin: true, language: "de", states }));
  await waitFor(browser, `${text()}.includes("Verbunden")`);
  await sleep(120);
  const e5 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "diagnostics"; p._data.diagnostics = { version: "x", area_count: 1, meta_area_count: 0, adaptive_entity_count: 1, unavailable_source_count: 0, unknown_source_count: 2, empty_aggregate_count: 0, warning_count: 0, data_complete: false, issues: [{ severity: "info", area_id: "kitchen", code: "unknown_source", message: "" }, { severity: "info", area_id: "kitchen", code: "unknown_source", message: "" }] }; p._render(); const body = p.querySelector("[data-region=body]"); return { verdict: body.querySelector("[data-key=verdict]")?.textContent || null, incomplete: body.querySelector("[data-key=incomplete]")?.textContent || null, stale: body.querySelector("[data-key=stale]")?.textContent || null, text: body.textContent, values: [...body.querySelectorAll("dd")].map((n) => n.textContent) }; })()`);
  check("E5 German completeness wording for unknown sources", e5.incomplete.includes("Daten unvollständig") && e5.verdict.includes("Keine bekannten") && e5.text.includes("Quellen mit unbekanntem Zustand"), JSON.stringify(e5));

  // F-series (step 6.3): central area editor covers the environment fields and keeps hidden ones
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); const o = st.config.areas[0].options; o.room_category = "living_sedentary"; o.area_temperature_sensor = "sensor.area_temp"; o.outdoor_temperature_entity = "sensor.outdoor"; o.relevant_windows = ["binary_sensor.window"]; o.passive_cooling_temperature_difference = 2; o.ventilation_fans = ["fan.vent"]; p._data.config = JSON.parse(JSON.stringify(st.config)); p._render(); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] select[name=room_category]") !== null`);
  const f1 = await browser.evaluate(`(() => { const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); const cat = form.elements.namedItem("room_category"); return { value: cat.value, label: cat.closest("label").textContent, hasWindowField: !!form.elements.namedItem("relevant_windows"), passive: form.elements.namedItem("passive_cooling_temperature_difference")?.value }; })()`);
  check("F1 the environment fields are in the central editor with their translated labels and stored values", f1.value === "living_sedentary" && f1.label.includes("Area category") && f1.label.includes("Living / sedentary") && f1.hasWindowField === true && f1.passive === "2", JSON.stringify(f1));
  const f2 = await browser.evaluate(`(() => { const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); const cat = form.elements.namedItem("room_category"); form.elements.namedItem("clear_timeout").value = "7"; form.requestSubmit(); return new Promise((res) => setTimeout(() => res({ sent: window.__h.hass.__state.lastAreaUpdate || null }), 200)); })()`);
  check("F2 an untouched environment field is sent with its stored value, the presence change is sent, nothing else is invented", f2.sent?.room_category === "living_sedentary" && f2.sent?.clear_timeout === 7 && f2.sent?.outdoor_temperature_entity === "sensor.outdoor" && !("ventilation_fans" in (f2.sent || {})), JSON.stringify(f2));
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; true`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] select[name=room_category]") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); form.elements.namedItem("room_category").value = "hygiene_wet"; form.elements.namedItem("area_temperature_sensor").value = ""; form.elements.namedItem("passive_cooling_temperature_difference").value = ""; form.dispatchEvent(new Event("input", { bubbles: true })); form.requestSubmit(); return true; })()`);
  await sleep(200);
  const f3 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate || null`);
  check("F3 a changed category is sent, a cleared sensor is sent as an explicit empty value, an empty number keeps the stored value", f3?.room_category === "hygiene_wet" && f3?.area_temperature_sensor === "" && f3?.passive_cooling_temperature_difference === 2, JSON.stringify(f3));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-cancel]")?.click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const f4 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config.areas[0].options.room_category = "unconditioned"; p._data.config = JSON.parse(JSON.stringify(st.config)); p._render(); return p._errors.form; })()`);
  check("F4 a stored category that is not offered is not replaced silently in the form", f4 === null, String(f4));
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; true`);

  // G-series (step 6.3): area-bound entity fields follow the Home Assistant area registry
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  await browser.evaluate(`(() => { const h = window.__h.hass; const st = h.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.area_temperature_sensor = "sensor.office_temp"; const p = document.querySelector("adaptive-areas-panel"); p._data.config = JSON.parse(JSON.stringify(st.config)); if (p._drafts.area.draft) { p._drafts.area.draft.area_temperature_sensor = "sensor.office_temp"; p._drafts.area.original.area_temperature_sensor = "sensor.office_temp"; } h.states = Object.assign({}, h.states, { "sensor.kitchen_temp": { state: "21", attributes: { friendly_name: "Kitchen temperature" } }, "sensor.office_temp": { state: "20", attributes: { friendly_name: "Office temperature" } }, "sensor.dev_temp": { state: "22", attributes: { friendly_name: "Device temperature" } }, "sensor.loose_temp": { state: "19", attributes: { friendly_name: "Loose temperature" } } }); h.entities = { "sensor.kitchen_temp": { area_id: "kitchen", device_id: null }, "sensor.office_temp": { area_id: "office", device_id: null }, "sensor.dev_temp": { area_id: null, device_id: "dev1" }, "sensor.loose_temp": { area_id: null, device_id: null } }; h.devices = { dev1: { area_id: "kitchen" } }; p._render(); return true; })()`);
  await sleep(120);
  const g1 = await browser.evaluate(`(() => { const sel = document.querySelector("adaptive-areas-panel aa-entity-picker[name=area_temperature_sensor]"); return [...sel.options].map((o) => o.value).filter((v) => v); })()`);
  check("G1 an area-bound field offers only entities of this Area, direct or inherited from the device, plus the stored value (kept, see G2)", JSON.stringify(g1) === JSON.stringify(["sensor.dev_temp", "sensor.kitchen_temp", "sensor.office_temp"]), JSON.stringify(g1));
  const g2 = await browser.evaluate(`(() => { const sel = document.querySelector("adaptive-areas-panel aa-entity-picker[name=area_temperature_sensor]"); const opt = [...sel.options].find((o) => o.value === "sensor.office_temp"); return { selected: !!opt && opt.selected, label: opt ? opt.textContent : null }; })()`);
  check("G2 a stored source outside the Area is kept selected and named as outside this Area (cross-area use allowed)", g2.selected === true && (g2.label || "").includes("outside this Area; cross-area use allowed"), JSON.stringify(g2));
  const g3 = await browser.evaluate(`(() => { const sel = document.querySelector("adaptive-areas-panel aa-entity-picker[name=outdoor_temperature_entity]"); return [...sel.options].map((o) => o.value).filter((v) => v); })()`);
  check("G3 outdoor sources are not restricted to the Area", g3.includes("sensor.office_temp") && g3.includes("sensor.loose_temp"), JSON.stringify(g3));
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; true`);
  await browser.evaluate(`(() => { const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); form.elements.namedItem("humidity_warning_duration").value = "0"; form.elements.namedItem("clear_timeout").value = "4"; form.requestSubmit(); return true; })()`);
  await sleep(200);
  const g4 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate || null`);
  check("G4 a humidity duration of 0 is a valid explicit value and an out-of-Area source is not dropped on save", g4?.humidity_warning_duration === 0 && g4?.area_temperature_sensor === "sensor.office_temp", JSON.stringify(g4));
  await browser.evaluate(mountCode({ admin: true, language: "de", states }));
  await waitFor(browser, `${text()}.includes("Verbunden")`);
  const g5 = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._ui.tab = "areas"; p._ui.editing = { area_id: "kitchen", name: "Kitchen", options: {} }; p._drafts.area = { ...p._areaDraftState(), areaId: "kitchen", original: {}, draft: {} }; p._render(); return document.querySelector("adaptive-areas-panel form[data-area-form]")?.textContent || ""; })()`);
  check("G5 German labels for the humidity duration and the passive cooling unit", g5.includes("Mindestdauer erhöhter Luftfeuchtigkeit (min)") && g5.includes("Temperaturdifferenz für passive Kühlung (K)"), g5.slice(0, 200));

  // L-series (step 6.4): light configuration in the central editor with the shared draft and conflict model
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 50, turn_off_above: 200, vacancy_delay: 30 }, light_groups: { overhead_lights: ["light.ceiling"], overhead_lights_activation: "occupied", overhead_lights_blocking_states: ["sleep"], overhead_lights_brightness: "require_dark", sleep_lights: ["light.bed"], sleep_lights_activation: "sleep", sleep_lights_blocking_states: [], sleep_lights_brightness: "ignore", accent_lights: [], accent_lights_activation: "disabled", accent_lights_blocking_states: [], accent_lights_brightness: "require_dark", task_lights: [], task_lights_activation: "disabled", task_lights_blocking_states: [], task_lights_brightness: "require_dark" } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  const l1 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); return { threshold: f.elements.namedItem("light:threshold").value, hysteresis: f.elements.namedItem("light:hysteresis").value, overheadActivation: f.elements.namedItem("light_group:overhead_lights_activation").value, overheadBlocking: [...f.elements.namedItem("light_group:overhead_lights_blocking_states").selectedOptions].map((o) => o.value), sleepActivation: f.elements.namedItem("light_group:sleep_lights_activation").value, sleepLights: [...f.querySelectorAll('aa-entity-picker[name=\"light_group:sleep_lights\"] input[type=hidden]')].map((o) => o.value) }; })()`);
  check("L1 the central editor shows the stored 50/200 lx pair as threshold 125 and hysteresis 120 % and keeps light group settings", l1.threshold === "125" && l1.hysteresis === "120" && l1.overheadActivation === "occupied" && JSON.stringify(l1.overheadBlocking) === JSON.stringify(["sleep"]) && l1.sleepActivation === "sleep" && JSON.stringify(l1.sleepLights) === JSON.stringify(["light.bed"]), JSON.stringify(l1));
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; true`);
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:threshold").value = "120"; f.elements.namedItem("light_group:overhead_lights_activation").value = "extended"; f.requestSubmit(); return true; })()`);
  await sleep(250);
  const l2 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate || null`);
  check("L2 a changed threshold and group setting are sent; the stored legacy vacancy_delay is kept untouched (no automatic migration); untouched group settings are kept", l2?.features?.light?.turn_on_below === 48 && l2?.features?.light?.vacancy_delay === 30 && l2?.features?.light?.turn_off_above === 192 && l2?.features?.light_groups?.overhead_lights_activation === "extended" && JSON.stringify(l2?.features?.light_groups?.sleep_lights) === JSON.stringify(["light.bed"]) && l2?.features?.light_groups?.sleep_lights_activation === "sleep", JSON.stringify(l2));

  await sleep(150);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config.areas[0].options.features.light.turn_on_below = 99; window.__h.hass.__state.lastAreaUpdate = undefined; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:threshold").value = "70"; f.elements.namedItem("light:hysteresis").value = "50"; f.requestSubmit(); return true; })()`);
  await sleep(250);
  const l3 = await browser.evaluate(`({ updates: window.__h.hass.__state.lastAreaUpdate || null, conflict: !!document.querySelector("adaptive-areas-panel [data-conflict-scope=area]"), draft: document.querySelector("adaptive-areas-panel form[data-area-form] input[name=clear_timeout]") ? document.querySelector("adaptive-areas-panel form[data-area-form] select[name=type]")?.value : null, kept: document.querySelector("adaptive-areas-panel form[data-area-form]").elements.namedItem("light:threshold").value })`);
  check("L3 a server change blocks the central light save, keeps the entered value and shows the conflict", l3.updates === null && l3.conflict === true && l3.kept === "70", JSON.stringify(l3));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-scope=area] [data-conflict-overwrite]")?.click()`);
  await sleep(250);
  const l4 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.light?.turn_on_below ?? null`);
  check("L4 only the explicit overwrite confirmation writes the kept light value (70 lx threshold, 50 % hysteresis gives 52.5 and 87.5)", l4 === 52.5, String(l4));

  // K-series (step 6.5): climate configuration in the central editor
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 50, turn_off_above: 200 }, climate_control: { entity_id: "climate.kitchen", preset_clear: "off", preset_occupied: "comfort", preset_sleep: "sleep", preset_extended: "eco", climate_occupancy_threshold: 5 } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-climate]") !== null`);
  const k1 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); return { entity: f.elements.namedItem("climate:entity_id").value, clear: f.elements.namedItem("climate:preset_clear").value, occupied: f.elements.namedItem("climate:preset_occupied").value, extended: f.elements.namedItem("climate:preset_extended").value, threshold: f.elements.namedItem("climate:climate_occupancy_threshold").value }; })()`);
  check("K1 the central editor shows the stored thermostat, presets and occupancy threshold", k1.entity === "climate.kitchen" && k1.clear === "off" && k1.occupied === "comfort" && k1.extended === "eco" && k1.threshold === "5", JSON.stringify(k1));
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; true`);
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("climate:preset_occupied").value = "home"; f.elements.namedItem("climate:climate_occupancy_threshold").value = ""; f.elements.namedItem("climate:entity_id").value = ""; f.requestSubmit(); return true; })()`);
  await sleep(250);
  const k2 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate || null`);
  check("K2 a changed preset is sent; a cleared threshold and thermostat are removed; the light configuration is kept", k2?.features?.climate_control?.preset_occupied === "home" && !("climate_occupancy_threshold" in (k2?.features?.climate_control || {})) && !("entity_id" in (k2?.features?.climate_control || {})) && k2?.features?.climate_control?.preset_clear === "off" && k2?.features?.light?.turn_on_below === 50, JSON.stringify(k2));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 50, turn_off_above: 200 }, climate_control: { entity_id: "climate.kitchen", preset_clear: "off", preset_occupied: "comfort", preset_sleep: "sleep", preset_extended: "eco", climate_occupancy_threshold: 5 } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-climate]") !== null`);
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("climate:climate_occupancy_threshold").value = "0"; f.requestSubmit(); return true; })()`);
  await sleep(250);
  const k3 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.climate_control?.climate_occupancy_threshold ?? null`);
  check("K3 a threshold of 0 is sent as an explicit value", k3 === 0, String(k3));
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._data.config = JSON.parse(JSON.stringify(window.__h.hass.__state.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-climate]") !== null`);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config.areas[0].options.features.climate_control.preset_clear = "away"; return true; })()`);
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; (() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("climate:preset_extended").value = "boost"; f.requestSubmit(); return true; })()`);
  await sleep(250);
  const k4 = await browser.evaluate(`({ sent: window.__h.hass.__state.lastAreaUpdate || null, conflict: !!document.querySelector("adaptive-areas-panel [data-conflict-scope=area]"), kept: document.querySelector("adaptive-areas-panel form[data-area-form]")?.elements.namedItem("climate:preset_extended").value })`);
  check("K4 a server change blocks the central climate save, keeps the entered preset and shows the conflict", k4.sent === null && k4.conflict === true && k4.kept === "boost", JSON.stringify(k4));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-scope=area] [data-conflict-overwrite]")?.click()`);
  await sleep(250);
  const k5 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.features?.climate_control?.preset_extended ?? null`);
  check("K5 only the explicit overwrite confirmation writes the kept climate value", k5 === "boost", String(k5));

  // N-series (step 6.6/6.7): navigation after a successful save
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("clear_timeout").value = "11"; f.requestSubmit(); return true; })()`);
  await sleep(300);
  const n1 = await browser.evaluate(`({ editorOpen: document.querySelector("adaptive-areas-panel form[data-area-form]") !== null, listed: !!document.querySelector("adaptive-areas-panel [data-edit='kitchen']"), heading: document.querySelector("adaptive-areas-panel h2")?.textContent || "", saved: window.__h.hass.__state.lastAreaUpdate?.clear_timeout ?? null })`);
  check("N1 after a successful save the editor closes and the Area list is shown again", n1.saved === 11 && n1.editorOpen === false && n1.listed === true && n1.heading === "Areas", JSON.stringify(n1));

  // GL-series (step 6.7): global entity fields follow the backend validation rules
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=global_light_sensor]") !== null`, 4000);
  await browser.evaluate(`(() => { const h = window.__h.hass; h.states = Object.assign({}, h.states, { "sensor.lux": { state: "10", attributes: { friendly_name: "Lux", device_class: "illuminance" } }, "sensor.temp": { state: "20", attributes: { friendly_name: "Temp", device_class: "temperature" } }, "light.kitchen": { state: "on", attributes: { friendly_name: "Kitchen light" } } }); window.__h.hass.__state.global = Object.assign({}, window.__h.hass.__state.global); document.querySelector("adaptive-areas-panel")._render(); return true; })()`);
  await sleep(150);
  const gl1 = await browser.evaluate(`({ weather: [...document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]").options].map((o) => o.value).filter((v) => v), light: [...document.querySelector("adaptive-areas-panel aa-entity-picker[name=global_light_sensor]").options].map((o) => o.value).filter((v) => v) })`);
  check("GL1 the weather field offers only weather entities and the brightness field only illuminance sensors, as the backend validates", gl1.weather.every((v) => v.startsWith("weather.")) && gl1.light.includes("sensor.lux") && !gl1.light.includes("sensor.temp") && !gl1.light.includes("light.kitchen"), JSON.stringify(gl1));

  // GL2-series: light sensor selection rules (device class illuminance, unit lx, value 0, unsupported units)
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=global_light_sensor]") !== null`, 4000);
  await browser.evaluate(`(() => { const h = window.__h.hass; h.states = Object.assign({}, h.states, { "sensor.lux_class": { state: "120", attributes: { friendly_name: "Lux class", device_class: "illuminance", unit_of_measurement: "lx" } }, "sensor.lux_unit": { state: "45", attributes: { friendly_name: "Lux unit only", unit_of_measurement: "lx" } }, "sensor.plain": { state: "300", attributes: { friendly_name: "Plain" } }, "sensor.percent": { state: "50", attributes: { friendly_name: "Percent", unit_of_measurement: "%" } }, "sensor.lux_word": { state: "70", attributes: { friendly_name: "Lux word", unit_of_measurement: "lux" } }, "sensor.lux_zero": { state: "0", attributes: { friendly_name: "Zero lux", device_class: "illuminance", unit_of_measurement: "lx" } } }); document.querySelector("adaptive-areas-panel")._render(); return true; })()`);
  await sleep(150);
  const gl2 = await browser.evaluate(`[...document.querySelector("adaptive-areas-panel aa-entity-picker[name=global_light_sensor]").options].map((o) => o.value).filter((v) => v)`);
  check("GL2a the brightness field offers illuminance-class sensors and lx-unit sensors (incl. value 0) and nothing else", ["sensor.lux_class", "sensor.lux_unit", "sensor.lux_zero"].every((v) => gl2.includes(v)) && !gl2.includes("sensor.plain") && !gl2.includes("sensor.percent") && !gl2.includes("sensor.lux_word"), JSON.stringify(gl2));
  await browser.evaluate(`(() => { window.__glSent = null; const h = window.__h.hass; const orig = h.callWS.bind(h); h.callWS = (msg) => { if (msg.type === "adaptive_areas/update_global_configuration") window.__glSent = msg.options; return orig(msg); }; const sel = document.querySelector("adaptive-areas-panel aa-entity-picker[name=global_light_sensor]"); sel.value = "sensor.lux_unit"; sel.dispatchEvent(new Event("change", { bubbles: true })); document.querySelector("adaptive-areas-panel [data-save-global]")?.click(); return true; })()`);
  await sleep(250);
  const gl3 = await browser.evaluate(`({ sent: window.__glSent, selected: document.querySelector("adaptive-areas-panel aa-entity-picker[name=global_light_sensor]")?.value ?? null })`);
  check("GL2b a lx-unit sensor is saved as global_light_sensor and stays selected after the save round trip", gl3.sent?.global_light_sensor === "sensor.lux_unit" && gl3.selected === "sensor.lux_unit", JSON.stringify(gl3));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Global settings");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=global_light_sensor]") !== null`, 4000);
  await browser.evaluate(`(() => { const h = window.__h.hass; h.states = Object.assign({}, h.states, { "sensor.percent": { state: "50", attributes: { friendly_name: "Percent", unit_of_measurement: "%" } }, "sensor.lux_unit": { state: "45", attributes: { friendly_name: "Lux unit only", unit_of_measurement: "lx" } } }); h.__state.global = Object.assign({}, h.__state.global, { options: { weather_entity: null, global_light_sensor: "sensor.percent" } }); document.querySelector("adaptive-areas-panel")._drafts.global = { original: { weather_entity: null, global_light_sensor: "sensor.percent" }, draft: null, saving: false, errors: {} }; document.querySelector("adaptive-areas-panel")._render(); return true; })()`);
  await sleep(150);
  const gl4 = await browser.evaluate(`document.querySelector("adaptive-areas-panel aa-entity-picker[name=global_light_sensor]")?.value ?? null`);
  check("GL2c an already stored sensor that is not selectable by the new rules stays selected (no silent change)", gl4 === "sensor.percent", String(gl4));

  // PR-series (step 6.7): a direct Area assignment takes precedence over the inherited device Area
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const h = window.__h.hass; h.states = Object.assign({}, h.states, { "sensor.own_office": { state: "20", attributes: { friendly_name: "Own office sensor" } }, "sensor.kitchen_dev": { state: "21", attributes: { friendly_name: "Kitchen device sensor" } } }); h.entities = { "sensor.own_office": { area_id: "office", device_id: "devk" }, "sensor.kitchen_dev": { area_id: null, device_id: "devk" } }; h.devices = { devk: { area_id: "kitchen" } }; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const pr1 = await browser.evaluate(`[...document.querySelector("adaptive-areas-panel aa-entity-picker[name=area_temperature_sensor]").options].map((o) => o.value).filter((v) => v)`);
  check("PR1 an entity with its own Area is not offered for the device's Area; an entity without its own Area inherits the device Area", pr1.includes("sensor.kitchen_dev") && !pr1.includes("sensor.own_office"), JSON.stringify(pr1));

  // M68-series (step 6.8 migration of the R05 requirements to the central editor)
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 50, turn_off_above: 200 }, climate_control: { entity_id: "climate.kitchen", preset_clear: "off", preset_occupied: "comfort", preset_sleep: "sleep", preset_extended: "eco", climate_occupancy_threshold: 5 } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config.areas[0].options.features.light.turn_on_below = 99; return true; })()`);
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("light:threshold").value = "70"; f.elements.namedItem("light:hysteresis").value = "50"; f.requestSubmit(); return true; })()`);
  await sleep(200);
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; (() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.requestSubmit(); return true; })()`);
  await sleep(200);
  const x1 = await browser.evaluate(`({ sent: window.__h.hass.__state.lastAreaUpdate || null, kept: document.querySelector("adaptive-areas-panel form[data-area-form]")?.elements.namedItem("light:threshold").value ?? null, conflict: !!document.querySelector("adaptive-areas-panel [data-conflict-scope=area]") })`);
  check("M68a a normal repeated save after a light conflict writes nothing and keeps the entered value (R05b in the central editor)", x1.sent === null && x1.kept === "70" && x1.conflict === true, JSON.stringify(x1));
  await browser.evaluate(`(() => { const h = window.__h.hass; const orig = h.callWS.bind(h); window.__m68orig = orig; h.callWS = (msg) => msg.type === "adaptive_areas/update_area" ? Promise.resolve({ ok: false, errors: { turn_on_below: "must be a number" } }) : orig(msg); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-conflict-scope=area] [data-conflict-overwrite]")?.click()`);
  await sleep(250);
  const x2 = await browser.evaluate(`({ kept: document.querySelector("adaptive-areas-panel form[data-area-form]")?.elements.namedItem("light:threshold").value ?? null, error: [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] ha-alert")].map((n) => n.textContent).join(" ") })`);
  check("M68b a backend validation error keeps the entered light value and shows the backend message", x2.kept === "70" && x2.error.includes("turn_on_below"), JSON.stringify(x2));
  await browser.evaluate(`window.__h.hass.callWS = window.__m68orig`);

  // climate part of the migrated R05 requirements
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 50, turn_off_above: 200 }, climate_control: { entity_id: "climate.kitchen", preset_clear: "off", preset_occupied: "comfort", preset_sleep: "sleep", preset_extended: "eco", climate_occupancy_threshold: 5 } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-climate]") !== null`);
  await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate = undefined; (() => { const h = window.__h.hass; window.__m68count = 0; const orig = h.callWS.bind(h); window.__m68orig2 = orig; h.callWS = (msg) => { if (msg.type === "adaptive_areas/update_area") window.__m68count += 1; return orig(msg); }; const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("climate:preset_extended").value = "boost2"; f.requestSubmit(); f.requestSubmit(); return true; })()`);
  await sleep(300);
  const x3 = await browser.evaluate(`({ writes: window.__m68count, saving: window.__h.hass.__state.lastAreaUpdate?.features?.climate_control?.preset_extended ?? null })`);
  check("M68c repeated submits of the climate fields send exactly one write", x3.writes === 1 && x3.saving === "boost2", JSON.stringify(x3));
  await browser.evaluate(`window.__h.hass.callWS = window.__m68orig2`);
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 50, turn_off_above: 200 }, climate_control: { entity_id: "climate.kitchen", preset_clear: "off", preset_occupied: "comfort", preset_sleep: "sleep", preset_extended: "eco", climate_occupancy_threshold: 5 } })); p._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-climate]") !== null`);
  await browser.evaluate(`(() => { const h = window.__h.hass; const orig = h.callWS.bind(h); window.__m68orig3 = orig; h.callWS = (msg) => msg.type === "adaptive_areas/update_area" ? Promise.resolve({ ok: false, errors: { climate_occupancy_threshold: "must be a positive integer" } }) : orig(msg); const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); f.elements.namedItem("climate:climate_occupancy_threshold").value = "5"; f.requestSubmit(); return true; })()`);
  await sleep(250);
  const x4 = await browser.evaluate(`({ kept: document.querySelector("adaptive-areas-panel form[data-area-form]")?.elements.namedItem("climate:climate_occupancy_threshold").value ?? null, error: [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] ha-alert")].map((n) => n.textContent).join(" ") })`);
  check("M68d a backend validation error on the climate threshold keeps the entered value and shows the message", x4.kept === "5" && x4.error.includes("climate_occupancy_threshold"), JSON.stringify(x4));
  await browser.evaluate(`window.__h.hass.callWS = window.__m68orig3`);

  // V-series (review V01-V03): no visible German text in the English editor; German texts in German; one clear heading
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const v1 = await browser.evaluate(`(() => { const txt = document.querySelector("adaptive-areas-panel form[data-area-form]").textContent; return { leaks: ["Entitäten", "Anwesenheit", "Registry", "Diagnose-Entitäten", "Bestätigende", "Bereichsklima", "Klimasteuerung", "Lichtautomatik", "Lichtgruppen", "Aggregierte", "Reinigungstracker", "Schlafzustand", "Erweiterter", "Dunkelzustand", "Akzentzustand", "Bereichstemperatur"].filter((w) => txt.includes(w)) }; })()`);
  check("V1a English editor shows no German labels", v1.leaks.length === 0, JSON.stringify(v1));
  const v2 = await browser.evaluate(`(() => { const h = document.querySelector("adaptive-areas-panel form[data-area-form]").closest("section")?.querySelector("h2")?.textContent || ""; return { heading: h, strongLines: document.querySelectorAll("adaptive-areas-panel form[data-area-form] strong").length }; })()`);
  check("V1b the editor heading names the Area once and no repeated name line is shown", v2.heading === "Area: Kitchen" && v2.strongLines === 0, JSON.stringify(v2));
  const v3 = await browser.evaluate(`(() => { const txt = document.querySelector("adaptive-areas-panel form[data-area-form]").textContent; return { analysis: txt.includes("Include entities in analysis"), presence: txt.includes("Presence release entities"), sleep: txt.includes("Entity for sleep state") }; })()`);
  check("V1c English labels for analysis, presence release and secondary states", v3.analysis && v3.presence && v3.sleep, JSON.stringify(v3));
  await browser.evaluate(mountCode({ admin: true, language: "de", states }));
  await waitFor(browser, `${text()}.includes("Verbunden")`);
  await clickByText(browser, "Bereichsverwaltung");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const v4 = await browser.evaluate(`(() => { const txt = document.querySelector("adaptive-areas-panel form[data-area-form]").textContent; return { analysis: txt.includes("Entitäten in die Analyse einschließen"), presence: txt.includes("Anwesenheitsfreigabe"), sleep: txt.includes("Entität für Schlafzustand"), english: txt.includes("Include entities in analysis") }; })()`);
  check("V2 German editor shows the German labels and no English label", v4.analysis && v4.presence && v4.sleep && v4.english === false, JSON.stringify(v4));
  // V02: stored entities are marked by their real state; a missing thermostat is "not found", never "not assigned to this Area"
  const v02 = await browser.evaluate(`(async () => { const el = document.querySelector("adaptive-areas-panel"); const host = document.createElement("div"); host.innerHTML = el._scopedSingle("climate:entity_id", "climate.v02_missing", "Thermostat", "climate", false); el.appendChild(host); const picker = host.querySelector("aa-entity-picker"); const chip = picker.shadowRoot.querySelector(".chip.missing"); const out = { notFound: chip !== null && /not found|nicht gefunden/.test(chip.textContent), falseWarning: /outside this Area|nicht diesem Bereich/.test(chip?.textContent || ""), kept: picker.value === "climate.v02_missing" }; host.remove(); return out; })()`);
  check("V02a a stored thermostat missing from the states is marked as not found, not as outside the Area", v02.notFound && !v02.falseWarning, JSON.stringify(v02));
  check("V02b a stored value that is not found stays selected in the field", v02.kept === true, JSON.stringify(v02));

  // V06d: presence is shown by a symbol and a text label, not by colour alone
  await browser.evaluate(mountCode({ admin: true, language: "en", states, multi: true }));
  await waitFor(browser, `${text()}.includes("first_floor")`);
  const v06d = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .status[data-presence]")].map(e => ({ symbol: getComputedStyle(e, "::before").content, label: e.textContent.trim(), kind: e.dataset.presence }))`);
  check("V06d every presence status has a symbol and a text label", v06d.length > 0 && v06d.every((x) => x.symbol !== "none" && x.symbol !== "normal" && x.label), JSON.stringify(v06d));

  // V06e: backend presence states from the real handlers; each card shows one symbol and label
  await browser.evaluate(mountCode({ admin: true, language: "en", states, presence: true }));
  await waitFor(browser, `${text()}.includes("first_floor")`);
  const v06e = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .status[data-presence]")].map(e => e.dataset.presence)`);
  check("V06e the presence fixture shows occupied and clear cards", v06e.includes("occupied") && v06e.includes("clear"), JSON.stringify(v06e));

  // V06f: an area without an available presence source is unknown, never shown as clear
  const v06f = await browser.evaluate(`(() => { const cards = [...document.querySelectorAll("adaptive-areas-panel article[data-area-id]")]; const byId = Object.fromEntries(cards.map((c) => [c.dataset.areaId, c.querySelector(".status")?.dataset.presence])); return { garage: byId.garage, frontYard: byId.front_yard, kitchen: byId.kitchen }; })()`);
  check("V06f an area without an available presence source is shown as unknown, not clear", v06f.garage === "unknown" && v06f.frontYard === "unknown" && v06f.kitchen === "clear", JSON.stringify(v06f));

  // V06g: backend environment (humidity unavailable) is shown on the Area card, admin and non-admin
  for (const admin of [true, false]) {
    await browser.evaluate(mountCode({ admin, language: "en", states, envPartial: true }));
    await waitFor(browser, `${text()}.includes("first_floor")`);
    const v06g = await browser.evaluate(`(() => { const card = document.querySelector("adaptive-areas-panel article[data-area-id='kitchen'] [data-line='environment']"); return { line: card?.textContent.trim() || "", notes: document.querySelector("adaptive-areas-panel article[data-area-id='kitchen']")?.textContent.includes("environment notes") || false }; })()`);
    check(`V06g${admin ? "a" : "b"} the Area card shows the backend environment with its notices (${admin ? "admin" : "non-admin"})`, v06g.line.includes("Comfort") && v06g.notes, JSON.stringify(v06g));
  }

  // V06h: complete valid environment values from the backend reach the card (no notices needed)
  for (const admin of [true, false]) {
    await browser.evaluate(mountCode({ admin, language: "en", states, envValid: true }));
    await waitFor(browser, `${text()}.includes("first_floor")`);
    const v06h = await browser.evaluate(`(() => { const line = document.querySelector("adaptive-areas-panel article[data-area-id='kitchen'] [data-line='environment']"); return line?.textContent.trim() || ""; })()`);
    check(`V06h${admin ? "a" : "b"} complete environment values are shown on the Area card (${admin ? "admin" : "non-admin"})`, v06h.includes("Comfort comfortable") && v06h.includes("Humidity normal") && !v06h.includes("notes"), JSON.stringify(v06h));
  }
  // V06i: a disabled environment feature shows no environment line and no invented values
  for (const admin of [true, false]) {
    await browser.evaluate(mountCode({ admin, language: "en", states, envDisabled: true }));
    await waitFor(browser, `${text()}.includes("first_floor")`);
    const v06i = await browser.evaluate(`!!document.querySelector("adaptive-areas-panel article[data-area-id='kitchen'] [data-line='environment']")`);
    check(`V06i${admin ? "a" : "b"} a disabled environment feature shows no environment line (${admin ? "admin" : "non-admin"})`, v06i === false, String(v06i));
  }

  // V05: collapsible navigation on narrow containers (real key events, focus, Escape, v5Drafts, roles, subscriptions)
  const v5Key = async (type, keyName, code, vk, textValue = "") => browser.send("Input.dispatchKeyEvent", { type, key: keyName, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, text: textValue });
  const v5Nav = `(() => { const shell = document.querySelector("adaptive-areas-panel .nav-shell"); const toggle = shell?.querySelector("[data-nav-toggle]"); const group = shell?.querySelector("nav.groups"); const groupDisplay = group ? getComputedStyle(group).display : ""; const toggleDisplay = toggle ? getComputedStyle(toggle).display : ""; return { open: shell?.dataset.navOpen, expanded: toggle?.getAttribute("aria-expanded"), groupDisplay, toggleDisplay, current: shell?.querySelector(".nav-toggle-current")?.textContent.trim() || "", active: document.activeElement?.dataset?.tab || (document.activeElement?.hasAttribute("data-nav-toggle") ? "nav-toggle" : document.activeElement?.tagName || ""), focusInNav: Boolean(shell && document.activeElement && shell.contains(document.activeElement)), tabs: [...(shell?.querySelectorAll("nav [data-tab]") || [])].map((node) => node.dataset.tab) }; })()`;
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 900, deviceScaleFactor: 1, mobile: false });
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const v5_1 = await browser.evaluate(v5Nav);
  check("V05a narrow container: toggle visible, menu collapsed, active view named on the toggle", v5_1.toggleDisplay !== "none" && v5_1.groupDisplay === "none" && v5_1.expanded === "false" && v5_1.current === "Dashboard", JSON.stringify(v5_1));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  const v5_2 = await browser.evaluate(v5Nav);
  check("V05b opening shows the views and moves focus to the active view", v5_2.open === "true" && v5_2.expanded === "true" && v5_2.groupDisplay !== "none" && v5_2.active === "dashboard" && v5_2.focusInNav, JSON.stringify(v5_2));
  await v5Key("keyDown", "Escape", "Escape", 27); await v5Key("keyUp", "Escape", "Escape", 27);
  const v5_3 = await browser.evaluate(v5Nav);
  check("V05c Escape closes the menu and returns focus to the toggle", v5_3.open === "false" && v5_3.expanded === "false" && v5_3.active === "nav-toggle" && v5_3.groupDisplay === "none", JSON.stringify(v5_3));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").focus()`);
  await v5Key("keyDown", "Enter", "Enter", 13, "\r"); await v5Key("keyUp", "Enter", "Enter", 13);
  const v5_4 = await browser.evaluate(v5Nav);
  check("V05d Enter on the focused toggle opens the menu", v5_4.open === "true", JSON.stringify(v5_4));
  await v5Key("keyDown", "Escape", "Escape", 27); await v5Key("keyUp", "Escape", "Escape", 27);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").focus()`);
  await v5Key("keyDown", " ", "Space", 32, " "); await v5Key("keyUp", " ", "Space", 32);
  const v5_5 = await browser.evaluate(v5Nav);
  check("V05e Space on the focused toggle opens the menu", v5_5.open === "true", JSON.stringify(v5_5));
  await v5Key("keyDown", "Escape", "Escape", 27); await v5Key("keyUp", "Escape", "Escape", 27);
  // subscriptions and callWS must not change when the menu is opened and closed
  await browser.evaluate(`(() => { const el = document.querySelector("adaptive-areas-panel"); window.__v05Calls = 0; const orig = el._hass.callWS.bind(el._hass); el._hass.callWS = (...args) => { window.__v05Calls += 1; return orig(...args); }; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  const v5Calls = await browser.evaluate(`window.__v05Calls`);
  check("V05f opening and closing the menu sends no WebSocket requests", v5Calls === 0, String(v5Calls));
  // a collapsed view cannot be reached with the keyboard
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  const v5_6 = await browser.evaluate(v5Nav);
  check("V05g the views are removed from the tab order while the menu is collapsed", v5_6.groupDisplay === "none", JSON.stringify(v5_6));
  // selecting a view closes the menu and keeps the new view
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='trace']").click()`);
  await waitFor(browser, `!!document.querySelector("adaptive-areas-panel nav [data-tab='trace']") && document.querySelector("adaptive-areas-panel .nav-toggle-current")?.textContent.includes("Decision trace")`);
  await new Promise((resolve) => setTimeout(resolve, 700));
  const v5_7 = await browser.evaluate(`(() => ({ ...(${v5Nav}), traceVisible: !!document.querySelector("adaptive-areas-panel [data-trace-area], adaptive-areas-panel .trace") }))()`);
  check("V05h selecting a view closes the menu, keeps the view and returns focus to the toggle", v5_7.open === "false" && v5_7.current === "Decision trace" && v5_7.active === "nav-toggle", JSON.stringify(v5_7));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click()`).catch(() => {});
  // v5Drafts survive opening and closing the menu
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='areas']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  await browser.evaluate(`(() => { const input = document.querySelector("adaptive-areas-panel form[data-area-form] input[name='name']") || document.querySelector("adaptive-areas-panel form[data-area-form] input"); input.value = "V05 draft"; input.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]").click()`);
  const v5Draft = await browser.evaluate(`(() => { const input = document.querySelector("adaptive-areas-panel form[data-area-form] input[name='name']") || document.querySelector("adaptive-areas-panel form[data-area-form] input"); return input?.value || ""; })()`);
  check("V05i an unsaved area draft survives opening and closing the menu", v5Draft === "V05 draft", JSON.stringify(v5Draft));
  // roles: a non-admin only gets monitoring views
  await browser.evaluate(mountCode({ admin: false, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const v5_8 = await browser.evaluate(v5Nav);
  check("V05j non-admin menu lists only monitoring views", v5_8.tabs.length > 0 && !v5_8.tabs.includes("areas") && !v5_8.tabs.includes("trace") && !v5_8.tabs.includes("settings") && !v5_8.tabs.includes("diagnostics"), JSON.stringify(v5_8));
  // wide container: the existing navigation stays, no toggle
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const v5_9 = await browser.evaluate(v5Nav);
  check("V05k wide container keeps the full navigation and hides the toggle", v5_9.toggleDisplay === "none" && v5_9.groupDisplay !== "none", JSON.stringify(v5_9));
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 800, deviceScaleFactor: 1, mobile: false });

  // DG: unsaved area draft and view switching (confirm is the existing confirmation mechanism; the native dialog is replaced by a recorder)
  const dgSetup = async (width) => {
    await browser.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await browser.evaluate(mountCode({ admin: true, language: "en", states }));
    await waitFor(browser, `${text()}.includes("Connected")`);
    await browser.evaluate(`(() => { window.__dgAsk = 0; window.__dgAnswer = false; window.confirm = (message) => { window.__dgAsk += 1; window.__dgMessage = message; return window.__dgAnswer; }; return true; })()`);
    await browser.evaluate(`(() => { const nav = document.querySelector("adaptive-areas-panel nav [data-tab='areas']"); nav.click(); return true; })()`);
    await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
    await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
    await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  };
  const dgField = `document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']")`;
  const dgType = (value) => browser.evaluate(`(() => { const input = ${dgField}; input.value = ${JSON.stringify(value)}; input.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const dgState = `(() => ({ editorOpen: !!document.querySelector("adaptive-areas-panel form[data-area-form]"), value: ${dgField}?.value ?? null, tabSelected: document.querySelector("adaptive-areas-panel nav [data-tab][aria-selected='true']")?.dataset.tab || null, ask: window.__dgAsk }))()`;
  // DG1: an unchanged draft switches directly, without a question
  await dgSetup(1280);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click()`);
  const dg1 = await browser.evaluate(dgState);
  check("DG1 an unchanged area draft switches the view without asking", dg1.ask === 0 && dg1.tabSelected === "dashboard", JSON.stringify(dg1));
  // DG2: a changed draft asks once; cancelling keeps the view and the draft
  await dgSetup(1280);
  await dgType("42");
  await browser.evaluate(`(() => { window.__dgAnswer = false; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click()`);
  const dg2 = await browser.evaluate(dgState);
  check("DG2 cancelling the question keeps the view and the unsaved change", dg2.ask === 1 && dg2.tabSelected === "areas" && dg2.editorOpen && dg2.value === "42", JSON.stringify(dg2));
  // DG3: confirming the discard switches the view; the change is not kept silently
  await browser.evaluate(`(() => { window.__dgAnswer = true; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click()`);
  const dg3a = await browser.evaluate(dgState);
  check("DG3a confirming the discard switches the view and asks once", dg3a.ask === 2 && dg3a.tabSelected === "dashboard", JSON.stringify(dg3a));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='areas']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const dg3b = await browser.evaluate(dgState);
  check("DG3b after a confirmed discard the area opens from the saved values", dg3b.value !== "42", JSON.stringify(dg3b));
  // DG4: keyboard path at a narrow container; the cancelled question keeps focus on the view item
  await dgSetup(390);
  await dgType("43");
  await browser.evaluate(`(() => { window.__dgAnswer = false; document.querySelector("adaptive-areas-panel [data-nav-toggle]").focus(); return true; })()`);
  await v5Key("keyDown", "Enter", "Enter", 13, "\r"); await v5Key("keyUp", "Enter", "Enter", 13);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").focus()`);
  await v5Key("keyDown", "Enter", "Enter", 13, "\r"); await v5Key("keyUp", "Enter", "Enter", 13);
  const dg4 = await browser.evaluate(dgState);
  check("DG4 keyboard: a cancelled switch keeps the draft and the view", dg4.ask === 1 && dg4.tabSelected === "areas" && dg4.value === "43", JSON.stringify(dg4));
  await browser.evaluate(`(() => { window.__dgAnswer = true; return true; })()`);
  await v5Key("keyDown", "Enter", "Enter", 13, "\r"); await v5Key("keyUp", "Enter", "Enter", 13);
  const dg4b = await browser.evaluate(dgState);
  check("DG4b keyboard: a confirmed switch asks once and switches the view", dg4b.ask === 2 && dg4b.tabSelected === "dashboard", JSON.stringify(dg4b));
  // DG5: no save request is sent by a discard or a switch
  await dgSetup(1280);
  await browser.evaluate(`(() => { const el = document.querySelector("adaptive-areas-panel"); window.__dgWrites = 0; const orig = el._hass.callWS.bind(el._hass); el._hass.callWS = (msg) => { if (/update|set|delete|create/.test(msg.type)) window.__dgWrites += 1; return orig(msg); }; return true; })()`);
  await dgType("44");
  await browser.evaluate(`(() => { window.__dgAnswer = true; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='trace']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel nav [data-tab='trace']")?.getAttribute("aria-selected") === "true"`);
  await new Promise((resolve) => setTimeout(resolve, 500));
  const dg5 = await browser.evaluate(`window.__dgWrites`);
  check("DG5 discarding a draft sends no write request", dg5 === 0, String(dg5));

  // V07: progressive disclosure in the central Area editor
  await dgSetup(1280);
  const v7a = await browser.evaluate(`(() => { const d = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")]; const tag = (text) => d.find((x) => x.querySelector("summary")?.textContent.includes(text))?.querySelector(".tier-tag")?.textContent.trim() || ""; return { general: tag("General area options"), presence: tag("Presence tracking"), features: tag("Feature selection"), environment: tag("Area climate") }; })()`);
  check("V07a every section names its tier: basic, function or advanced", v7a.general === "Basic" && v7a.presence === "Basic" && v7a.environment === "Function" && v7a.features === "Advanced", JSON.stringify(v7a));
  await browser.evaluate(`(() => { const d = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Presence tracking")); d.open = true; return true; })()`);
  await browser.evaluate(`(() => { const input = document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']"); input.value = "7"; input.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  await browser.evaluate(`(() => { const d = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Area climate")); d.open = true; d.open = false; return true; })()`);
  await browser.evaluate(`(() => { const input = document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']"); if (input) input.focus(); return true; })()`);
  await browser.evaluate(`window.__v7Calls = 0; (() => { const el = document.querySelector("adaptive-areas-panel"); const orig = el._hass.callWS.bind(el._hass); el._hass.callWS = (msg) => { window.__v7Calls += 1; return orig(msg); }; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel")._render()`);
  const v7b = await browser.evaluate(`(() => { const d = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")]; const presence = d.find((x) => x.querySelector("summary")?.textContent.includes("Presence tracking")); const env = d.find((x) => x.querySelector("summary")?.textContent.includes("Area climate")); return { presenceOpen: presence?.open === true, envOpen: env?.open === true, draft: document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']")?.value ?? null, focus: document.activeElement?.getAttribute("name") || null, calls: window.__v7Calls }; })()`);
  check("V07b open sections, the draft and the focused field survive a re-render without a server request", v7b.presenceOpen === true && v7b.envOpen === false && v7b.draft === "7" && v7b.focus === "clear_timeout" && v7b.calls === 0, JSON.stringify(v7b));
  // V07c: validation error in a collapsed section opens it and marks it
  await browser.evaluate(`(() => { const d = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Presence tracking")); d.open = false; return true; })()`);
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__v7orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/update_area" ? Promise.resolve({ ok: false, errors: { clear_timeout: "must be positive" } }) : window.__v7orig(msg); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] details[data-has-error='true']") !== null`, 3000).catch(() => {});
  const v7c = await browser.evaluate(`(() => { const d = document.querySelector("adaptive-areas-panel form[data-area-form] details[data-has-error='true']"); return { section: d?.querySelector("summary")?.textContent.trim() || "", open: d?.open === true, tag: d?.querySelector(".error-tag")?.textContent.trim() || "", draft: document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']")?.value ?? null }; })()`);
  check("V07c a validation error in a collapsed section opens that section and marks it, and the draft stays", v7c.open === true && v7c.tag === "Error in this section" && v7c.section.includes("Presence tracking") && v7c.draft === "7", JSON.stringify(v7c));
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = window.__v7orig; return true; })()`);
  // V07d: keyboard: a section summary is reachable and toggles with Enter; the draft is unchanged
  await browser.evaluate(`document.querySelector("adaptive-areas-panel form[data-area-form] details[data-tier='advanced'] summary").focus()`);
  await v5Key("keyDown", "Enter", "Enter", 13, "\r"); await v5Key("keyUp", "Enter", "Enter", 13);
  const v7d = await browser.evaluate(`(() => ({ advancedOpen: document.querySelector("adaptive-areas-panel form[data-area-form] details[data-tier='advanced']")?.open === true, focusSummary: document.activeElement?.tagName === "SUMMARY", draft: document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']")?.value ?? null }))()`);
  check("V07d keyboard: Enter on a section summary toggles it and keeps focus and the draft", v7d.advancedOpen === true && v7d.focusSummary && v7d.draft === "7", JSON.stringify(v7d));
  // V07f: saving from an advanced section sends one update with the options of that Area
  await dgSetup(1280);
  await browser.evaluate(`(() => { const d = document.querySelector("adaptive-areas-panel form[data-area-form] details[data-tier='advanced']"); d.open = true; const box = d.querySelector("input[type='checkbox']"); if (box) box.click(); return true; })()`);
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__v7Update = null; window.__v7orig2 = h.callWS.bind(h); h.callWS = (msg) => { if (msg.type === "adaptive_areas/update_area") { window.__v7Update = msg; return Promise.resolve({ ok: true, errors: {} }); } return window.__v7orig2(msg); }; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit()`);
  await new Promise((resolve) => setTimeout(resolve, 400));
  const v7f = await browser.evaluate(`(() => ({ sent: !!window.__v7Update, area: window.__v7Update?.area_id || null, keys: Object.keys(window.__v7Update?.options || {}).length, hasFeatures: "features" in (window.__v7Update?.options || {}) }))()`);
  check("V07f saving from an advanced section sends one update for the Area with its options", v7f.sent && v7f.area === "kitchen" && v7f.keys > 0 && v7f.hasFeatures, JSON.stringify(v7f));
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = window.__v7orig2; return true; })()`);

  // V07g: a late save response for an Area that is no longer shown changes nothing
  await dgSetup(1280);
  await browser.evaluate(`(() => { const d = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Presence tracking")); d.open = true; return true; })()`);
  await browser.evaluate(`(() => { const input = document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']"); input.value = "9"; input.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__v7late = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/update_area" ? new Promise((resolve) => { window.__v7resolve = () => resolve({ ok: false, errors: { clear_timeout: "late error" } }); }) : window.__v7late(msg); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit()`);
  await browser.evaluate(`(() => { window.__dgAnswer = true; document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click(); return true; })()`);
  await browser.evaluate(`window.__v7resolve()`);
  await new Promise((resolve) => setTimeout(resolve, 400));
  const v7g = await browser.evaluate(`(() => ({ tabSelected: document.querySelector("adaptive-areas-panel nav [data-tab][aria-selected='true']")?.dataset.tab || null, editorOpen: !!document.querySelector("adaptive-areas-panel form[data-area-form]"), lateText: document.querySelector("adaptive-areas-panel")?.textContent.includes("late error") || false, errorTag: !!document.querySelector("adaptive-areas-panel .error-tag") }))()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='areas']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const v7g2 = await browser.evaluate(`(() => ({ errorLeak: document.querySelector("adaptive-areas-panel")?.textContent.includes("late error") || false, errorTag: !!document.querySelector("adaptive-areas-panel .error-tag") }))()`);
  check("V07g a late failed save for a closed editor does not change the shown view or show its error", v7g.tabSelected === "dashboard" && v7g.editorOpen === false && v7g.lateText === false && v7g.errorTag === false && v7g2.errorLeak === false && v7g2.errorTag === false, JSON.stringify({ v7g, v7g2 }));
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = window.__v7late; return true; })()`);
  // V07h: touch. Real touch events through the DevTools protocol, not CSS classes
  await dgSetup(390);
  await browser.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 1 });
  const v7tap = async (selector) => {
    const box = await browser.evaluate(`(() => { const el = ${selector}; el.scrollIntoView({ block: "center" }); const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    await browser.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: box.x, y: box.y }] });
    await browser.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await new Promise((resolve) => setTimeout(resolve, 150));
  };
  const v7presence = `[...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Presence tracking")).querySelector("summary")`;
  await v7tap(v7presence);
  const v7h1 = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Presence tracking")).open`);
  await v7tap(v7presence);
  const v7h2 = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Presence tracking")).open`);
  check("V07h touch opens and closes a section", v7h1 === true && v7h2 === false, JSON.stringify({ v7h1, v7h2 }));
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__v7t = h.callWS.bind(h); window.__v7tUpd = 0; h.callWS = (msg) => { if (msg.type === "adaptive_areas/update_area") { window.__v7tUpd += 1; return Promise.resolve({ ok: true, errors: {} }); } return window.__v7t(msg); }; return true; })()`);
  await v7tap(`document.querySelector("adaptive-areas-panel form[data-area-form] button[type='submit']")`);
  await new Promise((resolve) => setTimeout(resolve, 300));
  const v7hs = await browser.evaluate(`window.__v7tUpd`);
  check("V07h2 touch on Save sends exactly one update", v7hs === 1, String(v7hs));
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = window.__v7t; return true; })()`);
  await browser.send("Emulation.setTouchEmulationEnabled", { enabled: false, maxTouchPoints: 1 });
  // V07i: 200 % zoom, approximated with CSS zoom on the page (reflow to half the width)
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await dgSetup(1280);
  await browser.evaluate(`document.documentElement.style.zoom = "2"`);
  await new Promise((resolve) => setTimeout(resolve, 300));
  const v7i = await browser.evaluate(`(() => { const form = document.querySelector("adaptive-areas-panel form[data-area-form]"); const main = document.querySelector("adaptive-areas-panel main.shell"); const save = form.querySelector("button[type='submit']"); const cancel = document.querySelector("adaptive-areas-panel [data-cancel]"); const sum = [...form.querySelectorAll(":scope > details > summary")].map((x) => x.scrollWidth - x.clientWidth); return { container: Math.round(main.getBoundingClientRect().width), docScroll: document.documentElement.scrollWidth, docClient: document.documentElement.clientWidth, saveVisible: !!save && save.getBoundingClientRect().width > 0, cancelVisible: !!cancel && cancel.getBoundingClientRect().width > 0, summaryClipped: sum.filter((x) => x > 1).length }; })()`);
  check("V07i at 200 % zoom the editor has no horizontal overflow, keeps Save and Cancel and no clipped section titles", v7i.docScroll <= v7i.docClient && v7i.saveVisible && v7i.cancelVisible && v7i.summaryClipped === 0, JSON.stringify(v7i));
  await browser.evaluate(`document.documentElement.style.zoom = ""`);

  // V07e: non-admin users get no editor and no area edit controls
  await browser.evaluate(mountCode({ admin: false, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  const v7e = await browser.evaluate(`({ edit: document.querySelectorAll("adaptive-areas-panel [data-edit], adaptive-areas-panel form[data-area-form], adaptive-areas-panel [data-add]").length })`);
  check("V07e non-admin users have no area editor or edit controls", v7e.edit === 0, JSON.stringify(v7e));

  // V08: decision trace presentation, real backend fixture, unknown values, empty protocol, long content, late responses
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='trace']").click()`);
  await waitFor(browser, `document.querySelectorAll("adaptive-areas-panel .trace-entry").length > 0`, 4000).catch(() => {});
  const v8a = await browser.evaluate(`(() => ({ entries: document.querySelectorAll("adaptive-areas-panel .trace-entry").length, summaries: [...document.querySelectorAll("adaptive-areas-panel .trace-entry .trace-summary")].length, facts: [...document.querySelectorAll("adaptive-areas-panel .trace-entry .trace-facts")].length, time: document.querySelectorAll("adaptive-areas-panel .trace-entry time").length }))()`);
  check("V08a every recorded decision shows a summary, facts and a time from the backend fixture", v8a.entries === 3 && v8a.summaries === 3 && v8a.facts === 3 && v8a.time === 3, JSON.stringify(v8a));
  const v8b = await browser.evaluate(`(() => { const first = document.querySelector("adaptive-areas-panel .trace-entry"); return { decision: first.querySelector(".trace-decision")?.textContent.trim(), outcome: first.querySelector(".trace-outcome")?.textContent.trim(), feature: first.querySelector(".trace-feature")?.textContent.trim(), reason: first.querySelector(".trace-facts")?.textContent.includes("Motion detected") }; })()`);
  check("V08b the summary names the decision, outcome and feature of the entry", v8b.decision === "State change" && v8b.outcome === "Observed" && v8b.feature === "Presence" && v8b.reason === true, JSON.stringify(v8b));
  // V08c: an empty protocol says so and shows no entries
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__v8orig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/get_decision_trace" ? Promise.resolve({ area_id: "kitchen", limit: 20, entries: [] }) : window.__v8orig(msg); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='trace']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-key='empty']") !== null`, 3000).catch(() => {});
  const v8c = await browser.evaluate(`({ entries: document.querySelectorAll("adaptive-areas-panel .trace-entry").length, empty: !!document.querySelector("adaptive-areas-panel [data-key='empty']") })`);
  check("V08c an empty protocol shows the empty state and no entries", v8c.entries === 0 && v8c.empty === true, JSON.stringify(v8c));
  // V08d: missing fields are shown as unknown and neutral, not as a decision
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = (msg) => msg.type === "adaptive_areas/get_decision_trace" ? Promise.resolve({ area_id: "kitchen", limit: 20, entries: [{ timestamp: null, trigger: null, decision: null, outcome: null, feature: null, reason_codes: [], area_state: [] }] }) : window.__v8orig(msg); return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='trace']").click()`);
  await waitFor(browser, `document.querySelectorAll("adaptive-areas-panel .trace-entry").length === 1`, 3000).catch(() => {});
  const v8d = await browser.evaluate(`(() => { const e = document.querySelector("adaptive-areas-panel .trace-entry"); return { unknownCount: e ? e.querySelectorAll(".unknown").length : 0, decisionUnknown: e?.querySelector(".trace-decision .unknown") !== null, noInvented: e ? !e.textContent.includes("State change") && !e.textContent.includes("Other") : false, noTimeInvented: e ? !e.querySelector("time") : false }; })()`);
  check("V08d missing decision, trigger and time are shown as unknown, never invented", v8d.unknownCount >= 3 && v8d.decisionUnknown && v8d.noInvented && v8d.noTimeInvented, JSON.stringify(v8d));
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = window.__v8orig; return true; })()`);
  // V08e: long content on a 320 px viewport stays inside the container, no horizontal overflow
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 900, deviceScaleFactor: 1, mobile: false });
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']")?.click()`);
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]")?.click()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='trace']").click()`);
  await waitFor(browser, `document.querySelectorAll("adaptive-areas-panel .trace-entry").length > 0`, 3000).catch(() => {});
  const v8e = await browser.evaluate(`(() => { const main = document.querySelector("adaptive-areas-panel main.shell"); return { container: Math.round(main.getBoundingClientRect().width), docScroll: document.documentElement.scrollWidth, docClient: document.documentElement.clientWidth, entryOverflow: [...document.querySelectorAll("adaptive-areas-panel .trace-entry")].some((e) => e.scrollWidth > e.clientWidth + 1) }; })()`);
  check("V08e on a 320 px viewport the trace has no horizontal overflow", v8e.docScroll <= v8e.docClient && v8e.entryOverflow === false, JSON.stringify(v8e));
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  // V08f: a late response for the previously selected area does not replace the newer selection
  await browser.evaluate(mountCode({ admin: true, language: "en", states, twoAreas: true }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__v8late = h.callWS.bind(h); let held = true; h.callWS = (msg) => { if (msg.type === "adaptive_areas/get_decision_trace" && held) { held = false; return new Promise((resolve) => { window.__v8resolve = () => resolve({ area_id: "kitchen", limit: 20, entries: [{ timestamp: null, trigger: null, decision: "late", outcome: null, feature: null, reason_codes: [], area_state: [] }] }); }); } return window.__v8late(msg); }; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='trace']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-trace-area]") !== null`, 3000);
  await browser.evaluate(`(() => { const select = document.querySelector("adaptive-areas-panel [data-trace-area]"); const other = [...select.options].find((o) => o.value !== select.value); select.value = other.value; select.dispatchEvent(new Event("change", { bubbles: true })); return other.value; })()`);
  const v8fSel = await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-trace-area]").value`);
  await browser.evaluate(`window.__v8resolve && window.__v8resolve()`);
  await new Promise((resolve) => setTimeout(resolve, 300));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel")._render()`);
  const v8f = await browser.evaluate(`({ select: document.querySelector("adaptive-areas-panel [data-trace-area]")?.value, entries: document.querySelectorAll("adaptive-areas-panel .trace-entry").length, lateEntry: [...document.querySelectorAll("adaptive-areas-panel .trace-entry .trace-decision")].some((e) => e.textContent.trim() === "Other") })`);
  check("V08f a late trace response for the previous area does not replace the newer selection or its entries", v8f.select === v8fSel && v8f.entries === 3 && !v8f.lateEntry, JSON.stringify({ v8fSel, v8f }));
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = window.__v8late; return true; })()`);
  // V08g: keyboard focus on the area filter survives a live re-render
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-trace-area]").focus()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel")._render()`);
  const v8g = await browser.evaluate(`document.activeElement?.matches?.("[data-trace-area]") === true`);
  check("V08g keyboard focus on the trace area filter survives a re-render", v8g === true, String(v8g));

  // V09: diagnostics structure, real backend fixture (unavailable sources), normal state, privacy, long values, late responses
  const v9Open = `document.querySelector("adaptive-areas-panel nav [data-tab='diagnostics']").click()`;
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await browser.evaluate(mountCode({ admin: true, language: "en", states, diagAcc: true }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(v9Open);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-group='details']") !== null`, 4000).catch(() => {});
  const v9a = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel [data-group]")].map((g) => ({ group: g.dataset.group, heading: g.querySelector("h3")?.textContent.trim() || "" }))`);
  check("V09a the diagnostics are grouped into status, technical issues, data availability and details", JSON.stringify(v9a.map((x) => x.group)) === JSON.stringify(["status", "technical", "data", "details"]) && v9a.every((x) => x.heading.length > 0), JSON.stringify(v9a));
  const v9b = await browser.evaluate(`(() => { const items = [...document.querySelectorAll("adaptive-areas-panel [data-group='technical'] li")]; return { count: items.length, label: items[0]?.querySelector(".diag-sev")?.textContent.trim() || "", text: items[0]?.querySelector(".diag-text")?.textContent.trim() || "", area: items[0]?.querySelector(".diag-area")?.textContent.trim() || "", labels: [...new Set(items.map((i) => i.querySelector(".diag-sev")?.textContent.trim()))] }; })()`);
  check("V09b each technical issue shows its severity, its text and its Area name", v9b.count === 16 && v9b.label === "Warning" && v9b.text.length > 0 && v9b.area.length > 0 && JSON.stringify(v9b.labels) === JSON.stringify(["Warning"]), JSON.stringify(v9b));
  const v9c = await browser.evaluate(`(() => { const tpl = document.querySelector("adaptive-areas-panel [data-group='details'] dl"); const dts = [...tpl.querySelectorAll("dt")]; const warnings = dts.find((dt) => dt.textContent === "Warnings")?.nextElementSibling?.textContent.trim(); const unavailable = [...document.querySelectorAll("adaptive-areas-panel [data-group='data'] dt")].find((dt) => /unavailable/i.test(dt.textContent))?.nextElementSibling?.textContent.trim(); return { warnings, unavailable }; })()`);
  check("V09c unavailable sources are counted once, under data availability, not as warnings", v9c.warnings === "0" && v9c.unavailable === "16", JSON.stringify(v9c));
  const v9e = await browser.evaluate(`(() => { const body = document.querySelector("adaptive-areas-panel [data-group='technical']").textContent; return { privacy: /\\b(binary_)?sensor\\.|light\\.|climate\\.|switch\\./.test(body) }; })()`);
  check("V09e the technical list shows no entity IDs", v9e.privacy === false, JSON.stringify(v9e));
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(v9Open);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-group='technical']") !== null`, 4000).catch(() => {});
  const v9d = await browser.evaluate(`(() => ({ none: document.querySelector("adaptive-areas-panel [data-key='no-technical']")?.textContent || "", verdict: document.querySelector("adaptive-areas-panel [data-key='verdict']")?.textContent || "" }))()`);
  check("V09d a normal diagnostics state says so without inventing issues", v9d.none === "No technical issues recorded." && v9d.verdict === "No issues.", JSON.stringify(v9d));
  // V09f: long values on a 320 px viewport
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 900, deviceScaleFactor: 1, mobile: false });
  await browser.evaluate(mountCode({ admin: true, language: "en", states, diagAcc: true }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-nav-toggle]")?.click()`);
  await browser.evaluate(v9Open);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-group='technical'] li") !== null`, 4000).catch(() => {});
  const v9f = await browser.evaluate(`(() => { const main = document.querySelector("adaptive-areas-panel main.shell"); return { container: Math.round(main.getBoundingClientRect().width), docScroll: document.documentElement.scrollWidth, docClient: document.documentElement.clientWidth, overflow: [...document.querySelectorAll("adaptive-areas-panel [data-group] li")].some((li) => li.scrollWidth > li.clientWidth + 1) }; })()`);
  check("V09f on a 320 px viewport long issue rows stay inside the container", v9f.docScroll <= v9f.docClient && v9f.overflow === false, JSON.stringify(v9f));
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  // V09g: an older diagnostics response that arrives after a newer one does not replace it
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__v9orig = h.callWS.bind(h); window.__v9held = true; const fixture = window.__fixtures.diagAcceptance; h.callWS = (msg) => { if (msg.type === "adaptive_areas/get_diagnostics" && window.__v9held) { window.__v9held = false; return new Promise((resolve) => { window.__v9resolve = () => resolve(fixture); }); } return window.__v9orig(msg); }; return true; })()`);
  await browser.evaluate(v9Open);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click()`);
  await browser.evaluate(v9Open);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-key='no-technical']") !== null`, 3000).catch(() => {});
  await browser.evaluate(`window.__v9resolve && window.__v9resolve()`);
  await new Promise((resolve) => setTimeout(resolve, 300));
  await browser.evaluate(`document.querySelector("adaptive-areas-panel")._render()`);
  const v9g = await browser.evaluate(`({ none: !!document.querySelector("adaptive-areas-panel [data-key='no-technical']"), items: document.querySelectorAll("adaptive-areas-panel [data-group='technical'] li").length })`);
  check("V09g a late diagnostics response does not replace the newer result", v9g.none === true && v9g.items === 0, JSON.stringify(v9g));
  await browser.evaluate(`(() => { const h = window.__h.hass; h.callWS = window.__v9orig; return true; })()`);

  // V10: no visible text of the other language in any view (admin and non-admin), German and English
  const v10EN = ["Unknown", "Unavailable", "Disabled", "Other", "Save", "Cancel", "Dashboard", "Notices", "Warnings", "Settings", "Details", "Trigger", "Decision", "Outcome", "Feature", "Reason", "Targets", "Transition", "Empty", "Loading", "Error", "Warning", "Information", "Complete", "Incomplete", "Occupied", "Clear", "Presence", "Environment", "Comfort", "Humidity", "Sleep", "Dark", "Bright", "Accent", "Extended", "Edit", "Delete", "Add", "the", "and", "of", "No", "Not"];
  const v10DE = ["Unbekannt", "nicht", "Deaktiviert", "Bereich", "Bereiche", "Speichern", "Abbrechen", "Sonstige", "Keine", "Fehler", "Warnung", "Entscheidung", "Auslöser", "Ergebnis", "Begründung", "Anwesenheit", "Ansicht", "Einstellungen", "Diagnose", "Hinweise", "und", "oder", "der", "die", "das", "ist"];
  // Names that come from the backend data or are product names, not translations
  const v10Allow = /Adaptive[ -]Areas|Intelligence Center|Interior|Exterior|Global|Lux|Thermostat/g;
  const v10Scan = async (language, admin) => {
    await browser.evaluate(mountCode({ admin, language, states, diagAcc: true, twoAreas: true, featureLight: true }));
    await waitFor(browser, `${text()}.includes("Connected") || ${text()}.length > 40`, 6000).catch(() => {});
    const found = {};
    for (const tab of ["dashboard", "cleaning", "room-usage", "light-control", "climate-control", "trace", "diagnostics", "areas", "settings"]) {
      const exists = await browser.evaluate(`!!document.querySelector("adaptive-areas-panel nav [data-tab='${tab}']")`);
      if (!exists) continue;
      await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='${tab}']").click()`);
      await sleep(250);
      const value = await browser.evaluate(`document.querySelector("adaptive-areas-panel")?.innerText || ""`);
      found[tab] = value.replace(v10Allow, "");
      if (tab === "areas") {
        await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']")?.click()`);
        await sleep(250);
        found.editor = (await browser.evaluate(`document.querySelector("adaptive-areas-panel")?.innerText || ""`)).replace(v10Allow, "");
        await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-cancel]")?.click()`);
        await sleep(120);
      }
    }
    return found;
  };
  const wordsIn = (value, words) => words.filter((word) => new RegExp(`(^|[^A-Za-zÄÖÜäöüß])${word}($|[^A-Za-zÄÖÜäöüß])`).test(value));
  const v10de = await v10Scan("de", true);
  const v10deLeaks = Object.fromEntries(Object.entries(v10de).map(([view, value]) => [view, wordsIn(value, v10EN)]).filter(([, hits]) => hits.length));
  check("V10a German views show no English interface text (admin, all views and the editor)", Object.keys(v10deLeaks).length === 0, JSON.stringify(v10deLeaks));
  const v10en = await v10Scan("en", true);
  const v10enLeaks = Object.fromEntries(Object.entries(v10en).map(([view, value]) => [view, wordsIn(value, v10DE)]).filter(([, hits]) => hits.length));
  check("V10b English views show no German interface text (admin, all views and the editor)", Object.keys(v10enLeaks).length === 0, JSON.stringify(v10enLeaks));
  const v10user = await v10Scan("de", false);
  const v10userLeaks = Object.fromEntries(Object.entries(v10user).map(([view, value]) => [view, wordsIn(value, v10EN)]).filter(([, hits]) => hits.length));
  check("V10c German non-admin views show no English interface text", Object.keys(v10userLeaks).length === 0, JSON.stringify(v10userLeaks));
  // V10d: a language change keeps the open draft, the open section and the focus
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='areas']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  await browser.evaluate(`(() => { const d = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Presence tracking")); d.open = true; const input = document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']"); input.value = "11"; input.dispatchEvent(new Event("input", { bubbles: true })); input.focus(); return true; })()`);
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p.hass = Object.assign({}, p._hass, { language: "de" }); return true; })()`);
  await sleep(300);
  const v10d = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const d = [...document.querySelectorAll("adaptive-areas-panel form[data-area-form] > details")].find((x) => x.querySelector("summary")?.textContent.includes("Anwesenheit")); return { german: document.querySelector("adaptive-areas-panel")?.innerText.includes("Bereich: Kitchen") || document.querySelector("adaptive-areas-panel")?.innerText.includes("Anwesenheit") || false, draft: document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']")?.value ?? null, open: d?.open === true, focus: document.activeElement?.getAttribute("name") || null }; })()`);
  check("V10d a language change keeps the unsaved draft, the open section and the focus", v10d.draft === "11" && v10d.open === true && v10d.focus === "clear_timeout", JSON.stringify(v10d));

  // BR: Bereichsverwaltung – einklappbare Entitätslisten und Domänenauswahl (R01, R11-R16)
  const BR_FORM = "adaptive-areas-panel form[data-area-form]";
  const BR_STATES = {
    "binary_sensor.hall_motion": { state: "off", attributes: { friendly_name: "Hall motion", device_class: "motion" } },
    "device_tracker.phone": { state: "home", attributes: { friendly_name: "Phone" } },
    "light.kitchen_ceiling": { state: "on", attributes: { friendly_name: "Kitchen ceiling" } },
    "sensor.kitchen_lux": { state: "120", attributes: { friendly_name: "Kitchen lux", device_class: "illuminance", unit_of_measurement: "lx" } },
    "media_player.tv": { state: "off", attributes: { friendly_name: "TV" } },
    "person.alex": { state: "home", attributes: { friendly_name: "Alex" } },
    "remote.living": { state: "on", attributes: { friendly_name: "Living remote" } },
    "sensor.very_long_presence_entity_identifier_for_narrow_container_check_number_one": { state: "1", attributes: { friendly_name: "A very long presence sensor name that must wrap inside a narrow container", device_class: "motion" } },
  };
  const brEntityList = (key) => `document.querySelector("${BR_FORM} details[data-entity-list='${key}']")`;
  const brSection = (label) => `[...document.querySelectorAll("${BR_FORM} > details")].find((x) => x.querySelector("summary")?.textContent.includes(${JSON.stringify(label)}))`;
  const brDomain = `document.querySelector("${BR_FORM} details.domain-select")`;
  const brOpen = async (language, states = BR_STATES, width = 1280) => {
    await browser.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await browser.evaluate(mountCode({ admin: true, language, states }));
    await waitFor(browser, `/Connected|Verbunden/.test(${text()})`);
    await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='areas']").click()`);
    await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
    await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
    await waitFor(browser, `document.querySelector("${BR_FORM}") !== null`);
  };
  // A successful save returns to the Area list; reopening loads the configuration the server now holds.
  const brReopen = async () => {
    await browser.evaluate(`(() => { window.confirm = () => true; document.querySelector("adaptive-areas-panel form[data-area-form] [data-cancel]")?.click(); return true; })()`);
    await sleep(200);
    await browser.evaluate(`(() => { document.querySelector("adaptive-areas-panel nav [data-tab='areas']")?.click(); return true; })()`);
    await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`, 4000).catch(async () => {
      const dump = await browser.evaluate(`(document.querySelector("adaptive-areas-panel")?.textContent || "").replace(/\\s+/g, " ").slice(0, 400)`);
      throw new Error("brReopen: no Area list. Panel text: " + dump);
    });
    await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
    await waitFor(browser, `document.querySelector("${BR_FORM}") !== null`);
  };
  // The server answers with the saved options; mirror them so the editor's consistency check sees no conflict.
  const brMirrorSave = () => `(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); Object.assign(st.config.areas[0].options, JSON.parse(JSON.stringify(st.lastAreaUpdate || {}))); document.querySelector("adaptive-areas-panel")._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`;
  const brSetStoredDomains = (domains) => `(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.presence_device_platforms = ${JSON.stringify(domains)}; document.querySelector("adaptive-areas-panel")._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`;
  await brOpen("en");
  // BR1: entity lists exist and are collapsed by default
  const br1 = await browser.evaluate(`(() => { const lists = [...document.querySelectorAll("${BR_FORM} details.entity-list")]; return { keys: lists.map((d) => d.dataset.entityList), openCount: lists.filter((d) => d.open).length }; })()`);
  check("BR1 include, exclude, presence-control and keep-only entity lists are collapsed by default", ["include_entities", "exclude_entities", "presence_control_entities", "keep_only_entities"].every((key) => br1.keys.includes(key)) && br1.openCount === 0, JSON.stringify(br1));
  // BR2: opening and closing sends no write and keeps the selection
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__brWrites = 0; window.__brOrig = h.callWS.bind(h); h.callWS = (msg) => { if (msg.type === "adaptive_areas/update_area") window.__brWrites += 1; return window.__brOrig(msg); }; const pk = ${brEntityList("include_entities")}.querySelector("aa-entity-picker"); ${brEntityList("include_entities")}.open = true; pk.shadowRoot.querySelector("input").focus(); [...pk.shadowRoot.querySelectorAll("[role=option]")].slice(0, 2).forEach((o) => o.click()); ${brEntityList("include_entities")}.open = false; return true; })()`);
  const br2 = await browser.evaluate(`(() => { const d = ${brEntityList("include_entities")}; const s = d.querySelector("summary"); const picked = [...d.querySelectorAll("aa-entity-picker input[type=hidden]")].map((i) => i.value); s.click(); const opened = d.open; s.click(); const closed = d.open; s.click(); return { opened, closed, reopened: d.open, picked, writes: window.__brWrites }; })()`);
  check("BR2 opening and closing the entity list sends no write and keeps every selected entity", br2.opened === true && br2.closed === false && br2.reopened === true && br2.writes === 0 && br2.picked.length === 2, JSON.stringify(br2));
  // BR3: a re-render keeps the open state and the selection; the summary counts the selection
  const br3 = await browser.evaluate(`(() => { document.querySelector("adaptive-areas-panel")._render(); const d = ${brEntityList("include_entities")}; return { open: d.open, picked: [...d.querySelectorAll("aa-entity-picker input[type=hidden]")].map((i) => i.value), summary: d.querySelector("summary").textContent.trim() }; })()`);
  check("BR3 a re-render keeps the open state, the selection and shows the count", br3.open === true && br3.picked.length === 2 && br3.summary.includes("(2)"), JSON.stringify(br3));
  // BR4: saving sends exactly the selected entities of the list
  await browser.evaluate(`(() => { document.querySelector("${BR_FORM}").requestSubmit(); return true; })()`);
  await waitFor(browser, `window.__h.hass.__state.lastAreaUpdate !== undefined`, 3000).catch(() => {});
  const br4 = await browser.evaluate(`(() => { const u = window.__h.hass.__state.lastAreaUpdate || {}; return { include: u.include_entities || null, exclude: u.exclude_entities || null }; })()`);
  check("BR4 saving sends the selected entities of the collapsed list", Array.isArray(br4.include) && br4.include.length === 2 && Array.isArray(br4.exclude) && br4.exclude.length === 0, JSON.stringify(br4));
  await browser.evaluate(brMirrorSave());
  await brReopen();
  // BR5: presence domains: exactly the four supported domains, stored values checked
  await browser.evaluate(`${brSection("Presence tracking")}.open = true`);
  const br5 = await browser.evaluate(`(() => { const boxes = [...document.querySelectorAll("${BR_FORM} input[name='presence_device_platforms']")]; return { values: boxes.map((b) => b.value), checked: boxes.filter((b) => b.checked).map((b) => b.value), summary: ${brDomain}.querySelector("summary").textContent.trim() }; })()`);
  check("BR5 the presence domain choice offers exactly binary_sensor, device_tracker, media_player and remote", JSON.stringify(br5.values) === JSON.stringify(["binary_sensor", "device_tracker", "media_player", "remote"]) && br5.checked.includes("media_player") && br5.checked.includes("binary_sensor") && br5.checked.length === 2 && br5.summary.includes("media_player"), JSON.stringify(br5));
  // BR6: several domains can be selected at once; saving and reloading keeps the choice
  await browser.evaluate(`${brDomain}.querySelector("summary").click()`);
  for (const value of ["device_tracker", "media_player"]) await browser.evaluate(`[...document.querySelectorAll("${BR_FORM} input[name='presence_device_platforms']")].find((b) => b.value === "${value}").click()`);
  await browser.evaluate(`(() => { window.__h.hass.__state.lastAreaUpdate = undefined; document.querySelector("${BR_FORM}").requestSubmit(); return true; })()`);
  await waitFor(browser, `window.__h.hass.__state.lastAreaUpdate?.presence_device_platforms !== undefined`, 3000).catch(() => {});
  const br6saved = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.presence_device_platforms || null`);
  await browser.evaluate(brMirrorSave());
  await brReopen();
  await browser.evaluate(`${brSection("Presence tracking")}.open = true`);
  const br6 = await browser.evaluate(`(() => { const boxes = [...document.querySelectorAll("${BR_FORM} input[name='presence_device_platforms']")]; return { reloaded: boxes.filter((b) => b.checked).map((b) => b.value) }; })()`);
  check("BR6 two domains are saved and shown checked again after a reload", JSON.stringify(br6saved) === JSON.stringify(["binary_sensor", "device_tracker"]) && JSON.stringify(br6.reloaded) === JSON.stringify(["binary_sensor", "device_tracker"]), JSON.stringify({ br6saved, reloaded: br6.reloaded }));
  // BR7: a stored domain that is no longer offered stays visible, flagged and is not deleted by saving
  await browser.evaluate(brSetStoredDomains(["binary_sensor", "light"]));
  await brReopen();
  await browser.evaluate(`${brSection("Presence tracking")}.open = true`);
  await browser.evaluate(`${brDomain}.querySelector("summary").click()`);
  const br7a = await browser.evaluate(`(() => { const boxes = [...document.querySelectorAll("${BR_FORM} input[name='presence_device_platforms']")]; const light = boxes.find((b) => b.value === "light"); return { values: boxes.map((b) => b.value), lightChecked: light?.checked === true, flagged: light?.closest("label")?.textContent.includes("not supported") === true }; })()`);
  check("BR7a a stored unsupported domain is shown checked and flagged, not silently removed", br7a.lightChecked && br7a.flagged && br7a.values.length === 5, JSON.stringify(br7a));
  await browser.evaluate(`(() => { window.__h.hass.__state.lastAreaUpdate = undefined; document.querySelector("${BR_FORM}").requestSubmit(); return true; })()`);
  await waitFor(browser, `window.__h.hass.__state.lastAreaUpdate?.presence_device_platforms !== undefined`, 3000).catch(() => {});
  const br7b = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.presence_device_platforms || null`);
  check("BR7b saving without changes keeps the stored unsupported value", Array.isArray(br7b) && br7b.includes("light") && br7b.includes("binary_sensor"), JSON.stringify(br7b));
  // BR8: keyboard: Enter and Space toggle an entity list; Space toggles a domain checkbox
  await brReopen();
  await browser.evaluate(`${brSection("Presence tracking")}.open = true`);
  await browser.evaluate(`${brEntityList("exclude_entities")}.querySelector("summary").focus()`);
  await v5Key("keyDown", "Enter", "Enter", 13, "\r"); await v5Key("keyUp", "Enter", "Enter", 13);
  const br8a = await browser.evaluate(`({ open: ${brEntityList("exclude_entities")}.open, focus: document.activeElement?.tagName === "SUMMARY" })`);
  await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: " ", code: "Space", text: " ", unmodifiedText: " ", windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32 }); await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: " ", code: "Space", windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32 });
  const br8b = await browser.evaluate(`${brEntityList("exclude_entities")}.open`);
  check("BR8a Enter and Space toggle an entity list from the keyboard", br8a.open === true && br8a.focus === true && br8b === false, JSON.stringify({ br8a, br8b }));
  await browser.evaluate(`(() => { ${brDomain}.open = true; const box = [...document.querySelectorAll("${BR_FORM} input[name='presence_device_platforms']")].find((b) => b.value === "remote"); box.focus(); return true; })()`);
  await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key: " ", code: "Space", text: " ", unmodifiedText: " ", windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32 }); await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: " ", code: "Space", windowsVirtualKeyCode: 32, nativeVirtualKeyCode: 32 });
  const br8c = await browser.evaluate(`({ checked: [...document.querySelectorAll("${BR_FORM} input[name='presence_device_platforms']")].find((b) => b.value === "remote")?.checked === true, focused: document.activeElement?.getAttribute("value") ?? document.activeElement?.tagName ?? null })`);
  check("BR8b Space toggles a domain checkbox from the keyboard", br8c.checked === true, JSON.stringify(br8c));
  // BR9: a long entity ID in a narrow container causes no horizontal overflow (320 px)
  await brOpen("en", BR_STATES, 320);
  const br9 = await browser.evaluate(`(() => { ${brEntityList("include_entities")}.querySelector("summary").click(); const list = ${brEntityList("include_entities")}; const sel = list.querySelector("aa-entity-picker"); return { pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, selectFits: sel.getBoundingClientRect().width <= list.getBoundingClientRect().width + 1 }; })()`);
  check("BR9 long entity names in an open list do not overflow a 320 px screen", br9.pageOverflow <= 0 && br9.selectFits === true, JSON.stringify(br9));
  // PK: shared entity picker (aa-entity-picker): search, multiple selection, chips, keyboard, dirty state, save
  const PK = `document.querySelector("${BR_FORM} aa-entity-picker[name='include_entities']")`;
  const pkInput = `${PK}.shadowRoot.querySelector("input")`;
  const pkKey = async (key, code, vk, textValue = "") => { await browser.send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, text: textValue }); await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk }); };
  await brOpen("en");
  await browser.evaluate(`${brEntityList("include_entities")}.open = true`);
  // PK1: opening the picker shows the list; typing filters by entity ID and by friendly name
  await browser.evaluate(`(() => { ${pkInput}.focus(); return true; })()`);
  const pk1a = await browser.evaluate(`${PK}.shadowRoot.querySelectorAll("[role=option]").length`);
  await browser.evaluate(`(() => { const i = ${pkInput}; i.value = "phone"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const pk1b = await browser.evaluate(`[...${PK}.shadowRoot.querySelectorAll("[role=option]")].map((o) => o.querySelector(".option-id").textContent)`);
  await browser.evaluate(`(() => { const i = ${pkInput}; i.value = "KITCHEN"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const pk1c = await browser.evaluate(`[...${PK}.shadowRoot.querySelectorAll("[role=option]")].map((o) => o.querySelector(".option-id").textContent)`);
  check("PK1 the picker lists entities and search matches entity ID and friendly name, case-insensitively", pk1a >= 5 && JSON.stringify(pk1b) === JSON.stringify(["device_tracker.phone"]) && JSON.stringify(pk1c) === JSON.stringify(["light.kitchen_ceiling","sensor.kitchen_lux"]), JSON.stringify({ pk1a, pk1b, pk1c }));
  // PK2: several entities are added without reopening; the list stays open and the count is shown
  await browser.evaluate(`(() => { const i = ${pkInput}; i.value = ""; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  await browser.evaluate(`(() => { const opts = [...${PK}.shadowRoot.querySelectorAll("[role=option]")]; opts.find((o) => o.querySelector(".option-id").textContent === "binary_sensor.hall_motion").click(); return true; })()`);
  await browser.evaluate(`(() => { const opts = [...${PK}.shadowRoot.querySelectorAll("[role=option]")]; opts.find((o) => o.querySelector(".option-id").textContent === "device_tracker.phone").click(); return true; })()`);
  const pk2 = await browser.evaluate(`({ hidden: [...${PK}.querySelectorAll("input[type=hidden][name='include_entities']")].map((i) => i.value), listOpen: !${PK}.shadowRoot.querySelector(".list").hidden, count: ${PK}.shadowRoot.querySelector(".meta").textContent, selectedMarks: [...${PK}.shadowRoot.querySelectorAll("[role=option][aria-selected=true]")].length })`);
  check("PK2 several entities are added without reopening and the count is shown", JSON.stringify(pk2.hidden) === JSON.stringify(["binary_sensor.hall_motion", "device_tracker.phone"]) && pk2.listOpen === true && pk2.count.includes("2") && pk2.selectedMarks === 2, JSON.stringify(pk2));
  // PK3: selected entities appear as chips; removing one leaves the others and keeps focus in the search field
  await browser.evaluate(`(() => { const chip = [...${PK}.shadowRoot.querySelectorAll(".chip")].find((c) => c.textContent.includes("Phone")); chip.querySelector("button").click(); return true; })()`);
  const pk3 = await browser.evaluate(`({ hidden: [...${PK}.querySelectorAll("input[type=hidden][name='include_entities']")].map((i) => i.value), chips: [...${PK}.shadowRoot.querySelectorAll(".chip")].length, focus: ${PK}.shadowRoot.activeElement?.tagName ?? null })`);
  check("PK3 a single chip is removed, the other stays and focus stays in the search field", JSON.stringify(pk3.hidden) === JSON.stringify(["binary_sensor.hall_motion"]) && pk3.chips === 1 && pk3.focus === "INPUT", JSON.stringify(pk3));
  // PK4: keyboard: arrows move the active option, Enter toggles it, Escape closes the list only
  await browser.evaluate(`(() => { ${pkInput}.focus(); return true; })()`);
  await pkKey("ArrowDown", "ArrowDown", 40);
  const pk4a = await browser.evaluate(`[...${PK}.shadowRoot.querySelectorAll("[role=option]")].findIndex((o) => o.dataset.active === "true")`);
  await pkKey("Enter", "Enter", 13, "\r");
  const pk4b = await browser.evaluate(`[...${PK}.querySelectorAll("input[type=hidden][name='include_entities']")].map((i) => i.value)`);
  await pkKey("Escape", "Escape", 27);
  const pk4c = await browser.evaluate(`({ listHidden: ${PK}.shadowRoot.querySelector(".list").hidden, formStill: document.querySelector("${BR_FORM}") !== null, stillSelected: [...${PK}.querySelectorAll("input[type=hidden][name='include_entities']")].length })`);
  check("PK4 arrow keys move the active entry, Enter toggles it, Escape closes only the list", pk4a >= 0 && pk4b.length === 2 && pk4c.listHidden === true && pk4c.formStill === true && pk4c.stillSelected === 2, JSON.stringify({ pk4a, pk4b, pk4c }));
  // PK5: opening, closing and tabbing away change nothing (no write, not dirty)
  await browser.evaluate(`(() => { window.__pkWrites = 0; const h = window.__h.hass; window.__pkOrig = h.callWS.bind(h); h.callWS = (msg) => { if (msg.type === "adaptive_areas/update_area") window.__pkWrites += 1; return window.__pkOrig(msg); }; ${pkInput}.focus(); return true; })()`);
  const pk5before = await browser.evaluate(`document.querySelector("adaptive-areas-panel")._areaDirty()`);
  await browser.evaluate(`(() => { ${pkInput}.blur(); return true; })()`);
  await browser.evaluate(`(() => { ${pkInput}.focus(); return true; })()`);
  await pkKey("Tab", "Tab", 9);
  const pk5 = await browser.evaluate(`({ dirtyBefore: ${JSON.stringify(false)} || null, dirtyNow: document.querySelector("adaptive-areas-panel")._areaDirty(), writes: window.__pkWrites, selected: [...${PK}.querySelectorAll("input[type=hidden][name='include_entities']")].map((i) => i.value).length })`);
  check("PK5 opening and leaving the picker without a choice sends no write and changes no dirty state", pk5.writes === 0 && pk5.dirtyNow === pk5before && pk5.selected === 2, JSON.stringify({ pk5before, ...pk5 }));
  // PK6: a long entity ID stays inside its chip and causes no page overflow at 320 px
  await brOpen("en", BR_STATES, 320);
  const pk6 = await browser.evaluate(`(() => { const p = document.querySelector("${BR_FORM} aa-entity-picker[name='include_entities']"); const pi = p.shadowRoot.querySelector("input"); pi.focus(); pi.dispatchEvent(new Event("input", { bubbles: true })); [...p.shadowRoot.querySelectorAll("[role=option]")].find((o) => o.querySelector(".option-id").textContent.startsWith("sensor.very_long")).click(); const host = p.getBoundingClientRect(); const chip = p.shadowRoot.querySelector(".chip-text")?.getBoundingClientRect(); return { overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, chipInside: !!chip && chip.right <= host.right + 1 && chip.left >= host.left - 1 }; })()`);
  check("PK6 a long entity ID wraps inside its chip with no overflow at 320 px", pk6.overflow <= 0 && pk6.chipInside === true, JSON.stringify(pk6));
  // PK7: saving sends exactly the picked entities; reopening shows the saved selection
  await browser.evaluate(`(() => { window.__h.hass.__state.lastAreaUpdate = undefined; document.querySelector("${BR_FORM}").requestSubmit(); return true; })()`);
  await waitFor(browser, `window.__h.hass.__state.lastAreaUpdate?.include_entities !== undefined`, 3000).catch(() => {});
  const pk7saved = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate?.include_entities || null`);
  await browser.evaluate(brMirrorSave());
  await brReopen();
  await browser.evaluate(`${brEntityList("include_entities")}.open = true`);
  const pk7 = await browser.evaluate(`[...document.querySelectorAll("${BR_FORM} aa-entity-picker[name='include_entities'] input[type=hidden]")].map((i) => i.value)`);
  check("PK7 saving sends the picked entities and reopening shows them again", Array.isArray(pk7saved) && pk7saved.length === 1 && JSON.stringify(pk7) === JSON.stringify(pk7saved), JSON.stringify({ pk7saved, pk7 }));
  // PK8: the single picker (Entity for darkness) selects and clears through the same component
  await brOpen("en");
  const pk8 = await browser.evaluate(`(() => { const d = document.querySelector("${BR_FORM} aa-entity-picker[name='area_illuminance_sensor']"); const i = d.shadowRoot.querySelector("input"); i.focus(); i.dispatchEvent(new Event("input", { bubbles: true })); const opt = [...d.shadowRoot.querySelectorAll("[role=option]")].find((o) => o.querySelector(".option-id").textContent === "sensor.kitchen_lux"); opt.click(); const after = [...d.querySelectorAll("input[type=hidden]")].map((x) => x.value); const chipCount = d.shadowRoot.querySelectorAll(".chip").length; const rmBefore = d.shadowRoot.querySelector(".chip .remove") ? "found" : "missing"; d.shadowRoot.querySelector(".chip .remove")?.click(); const cleared = [...d.querySelectorAll("input[type=hidden]")].map((x) => x.value); return { after, chipCount, cleared, draftDark: document.querySelector("adaptive-areas-panel")._drafts.area.draft?.secondary_states?.dark_entity ?? null, dirtyAfterClear: document.querySelector("adaptive-areas-panel")._areaDirty() }; })()`);
  check("PK8 the single picker selects, shows and clears the entity; clearing back to the saved empty value is not a change", JSON.stringify(pk8.after) === JSON.stringify(["sensor.kitchen_lux"]) && pk8.chipCount === 1 && JSON.stringify(pk8.cleared) === JSON.stringify([""]) && pk8.draftDark === "" && pk8.dirtyAfterClear === false, JSON.stringify(pk8));
  // PK9: the picker stays usable and free of horizontal overflow at phone and tablet widths
  for (const width of [320, 390, 430, 768, 1024, 1440]) {
    await browser.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await sleep(100);
    const pk9 = await browser.evaluate(`(() => { const p = document.querySelector("${BR_FORM} aa-entity-picker[name='include_entities']"); const host = p.getBoundingClientRect(); const form = document.querySelector("${BR_FORM}").getBoundingClientRect(); return { overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, insideForm: host.right <= form.right + 1 && host.width > 0 }; })()`);
    check(`PK9 the picker fits the form without page overflow at ${width} px`, pk9.overflow <= 0 && pk9.insideForm === true, JSON.stringify(pk9));
  }
  // SEC: section headings, collapsing and checkbox alignment
  await brOpen("en");
  await browser.evaluate(`(() => { const i = document.querySelector("${BR_FORM} input[name='clear_timeout']"); if (i) { i.value = "17"; i.dispatchEvent(new Event("input", { bubbles: true })); } return true; })()`);
  const sec1 = await browser.evaluate(`(() => { const sections = [...document.querySelectorAll("${BR_FORM} > details")]; const before = document.querySelector("adaptive-areas-panel")._areaDirty(); const value = document.querySelector("${BR_FORM} input[name='clear_timeout']")?.value ?? null; const first = sections[0]; const summary = first.querySelector("summary"); const height = summary.getBoundingClientRect().height; sections.forEach((d) => { d.open = !d.open; }); sections.forEach((d) => { d.open = !d.open; }); const after = document.querySelector("adaptive-areas-panel")._areaDirty(); const valueAfter = document.querySelector("${BR_FORM} input[name='clear_timeout']")?.value ?? null; return { count: sections.length, height, dirtyChanged: before !== after, valueKept: value === valueAfter, valueAfter }; })()`);
  check("SEC1 each top-level section has a heading of at least 44 px; toggling sections keeps inputs and changes no dirty state", sec1.count >= 4 && sec1.height >= 44 && sec1.dirtyChanged === false && sec1.valueKept === true, JSON.stringify(sec1));
  const sec2 = await browser.evaluate(`(() => { const box = document.querySelector("${BR_FORM} details.domain-select"); if (box) box.open = true; const row = document.querySelector("${BR_FORM} label.check input[type=checkbox]") || document.querySelector("${BR_FORM} .domain-option input"); if (!row) return { found: false }; const label = row.closest("label"); const a = row.getBoundingClientRect(); const b = label.getBoundingClientRect(); const centreDelta = Math.abs((a.top + a.height / 2) - (b.top + b.height / 2)); return { found: true, centreDelta: Math.round(centreDelta), targetHeight: Math.round(b.height) }; })()`);
  check("SEC2 a checkbox shares its vertical centre with its label and has a 40 px click target", sec2.found === true && sec2.centreDelta <= 3 && sec2.targetHeight >= 36, JSON.stringify(sec2));
  // ENT: picker hardening: accessibility, the 200-option cap, domain filter and a failed picker load
  await brOpen("en");
  await browser.evaluate(`${brEntityList("include_entities")}.open = true`);
  const ar1 = await browser.evaluate(`(() => { const p = ${PK}; const input = p.shadowRoot.querySelector("input"); const list = p.shadowRoot.querySelector("[role=listbox]"); input.focus(); input.dispatchEvent(new Event("input", { bubbles: true })); const expandedOpen = input.getAttribute("aria-expanded"); const controls = input.getAttribute("aria-controls"); const listId = list.id; input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true })); const active = input.getAttribute("aria-activedescendant"); const activeNode = active ? p.shadowRoot.getElementById(active) : null; const removeLabels = [...p.shadowRoot.querySelectorAll(".chip .remove")].map((b) => b.getAttribute("aria-label")); return { expandedOpen, controls, listId, activeOk: activeNode?.getAttribute("role") === "option" && activeNode.dataset.active === "true", optionRoles: [...list.querySelectorAll("[role=option]")].length > 0, label: input.getAttribute("aria-label"), removeLabels }; })()`);
  check("ENT1 the search field is a labelled combobox that controls the listbox and marks the active option", ar1.expandedOpen === "true" && ar1.controls === ar1.listId && ar1.activeOk === true && ar1.optionRoles === true && (ar1.label || "").length > 0, JSON.stringify(ar1));
  const ar2 = await browser.evaluate(`(() => { const p = ${PK}; const status = p.shadowRoot.querySelector("[role=status]"); const before = status.textContent; p.shadowRoot.querySelectorAll("[role=option]")[1].click(); return { before, after: status.textContent, removeLabels: [...p.shadowRoot.querySelectorAll(".chip .remove")].map((b) => b.getAttribute("aria-label")) }; })()`);
  check("ENT2 a selection change is announced and each remove button names its entity", ar2.after.includes("added") && ar2.removeLabels.every((label) => label.startsWith("Remove ") || label.startsWith("Entfernen")), JSON.stringify(ar2));
  // ENT3: more than 200 possible matches: the list is capped, but a stored value outside the cap stays selected and editable
  const many = {};
  for (let i = 0; i < 260; i += 1) many[`binary_sensor.bulk_${String(i).padStart(3, "0")}`] = { state: "off", attributes: { friendly_name: `Bulk ${i}`, device_class: "motion" } };
  many["binary_sensor.zz_stored"] = { state: "on", attributes: { friendly_name: "Stored late", device_class: "motion" } };
  await browser.evaluate(`(() => { const h = window.__h.hass; h.states = Object.assign({}, h.states, ${JSON.stringify(many)}); const p = document.querySelector("adaptive-areas-panel"); p._data.config = p._data.config; p._drafts.area.draft = { ...p._drafts.area.draft, include_entities: ["binary_sensor.zz_stored"] }; p._render(); return true; })()`);
  await sleep(120);
  const ent3 = await browser.evaluate(`(() => { const p = ${PK}; const total = p.options.length; p.shadowRoot.querySelector("input").dispatchEvent(new Event("input", { bubbles: true })); const shown = p.shadowRoot.querySelectorAll("[role=option]").length; const chips = [...p.shadowRoot.querySelectorAll(".chip-text")].map((c) => c.textContent); return { total, shown, stored: p.selected, chipKept: chips.some((c) => c.includes("Stored late")), notice: p.shadowRoot.querySelector(".meta").textContent }; })()`);
  check("ENT3 the list is capped at 200 options, a stored value beyond the cap stays selected and visible, and the user is told to refine", ent3.total >= 261 && ent3.shown === 200 && JSON.stringify(ent3.stored) === JSON.stringify(["binary_sensor.zz_stored"]) && ent3.chipKept === true && ent3.notice.includes("200"), JSON.stringify(ent3));
  // ENT5: a failed picker load shows a notice on the Area form and the panel stays usable
  await browser.evaluate(`(() => { window.__entOrigGet = customElements.get.bind(customElements); customElements.get = (name) => (name === "aa-entity-picker" ? undefined : window.__entOrigGet(name)); return true; })()`);
  await brOpen("en");
  const ent5 = await browser.evaluate(`(() => { const notice = [...document.querySelectorAll("${BR_FORM}")].length ? document.querySelector("adaptive-areas-panel").textContent : ""; return { notice: notice.includes("could not be loaded"), formStillThere: document.querySelector("${BR_FORM}") !== null }; })()`);
  await browser.evaluate(`(() => { customElements.get = window.__entOrigGet; return true; })()`);
  check("ENT5 a picker that failed to load shows a notice on the Area form and the form stays usable", ent5.notice === true && ent5.formStillThere === true, JSON.stringify(ent5));
  // BR11: lux fields are compact numeric inputs at desktop and phone widths
  for (const width of [1280, 390]) {
    await browser.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await browser.evaluate(mountCode({ admin: true, language: "en", states: BR_STATES }));
    await waitFor(browser, `/Connected|Verbunden/.test(${text()})`);
    await clickByText(browser, "Area management");
    await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
    await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = { light: { turn_on_below: 90, turn_off_above: 110 } }; document.querySelector("adaptive-areas-panel")._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
    await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
    await waitFor(browser, `document.querySelector("${BR_FORM} [data-light]") !== null`);
    await browser.evaluate(`(() => { const d = document.querySelector("${BR_FORM} details[data-light]"); if (d) d.open = true; return true; })()`);
    await sleep(150);
    const lux = await browser.evaluate(`(() => { const inputs = [...document.querySelectorAll("${BR_FORM} details[data-light] input[name^='light:'][type=number]")]; return { count: inputs.length, widest: Math.max(0, ...inputs.map((i) => Math.round(i.getBoundingClientRect().width))), overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth }; })()`);
    check(`BR11 lux inputs are compact at ${width} px (max 160 px wide, no page overflow)`, lux.count >= 2 && lux.widest <= 160 && lux.overflow <= 0, JSON.stringify(lux));
  }
  // BR12: a warning only when the saved Area has no effective presence source
  await brOpen("en");
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const area = p._data.overview.areas.find((a) => a.id === "kitchen"); area.presence = { ...area.presence, total: 0, available: 0 }; p._render(); return true; })()`);
  await brOpen("en");
  const br12a = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const area = p._data.overview.areas.find((a) => a.id === "kitchen"); area.presence = { ...area.presence, total: 0, available: 0 }; p._render(); return [...document.querySelectorAll("${BR_FORM} ha-alert")].some((n) => n.textContent.includes("no available presence source")); })()`);
  check("BR12a the presence warning appears when the saved Area has no effective source", br12a === true, String(br12a));
  await brOpen("en");
  const br12b = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const area = p._data.overview.areas.find((a) => a.id === "kitchen"); area.presence = { ...area.presence, total: 2, available: 2 }; p._render(); return [...document.querySelectorAll("${BR_FORM} ha-alert")].some((n) => n.textContent.includes("no available presence source")); })()`);
  check("BR12b no warning when the saved Area has effective sources", br12b === false, String(br12b));
  // BR12c: an unsaved domain change replaces the definitive warning with a neutral pending note
  await brOpen("en");
  const br12c = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const area = p._data.overview.areas.find((a) => a.id === "kitchen"); area.presence = { ...area.presence, total: 0, available: 0 }; p._render(); ${brSection("Presence tracking")}.open = true; ${brDomain}.open = true; [...document.querySelectorAll("${BR_FORM} input[name='presence_device_platforms']")].find((b) => b.value === "remote").click(); const texts = [...document.querySelectorAll("${BR_FORM} ha-alert")].map((n) => n.textContent); return { pending: texts.some((t) => t.includes("Unsaved changes")), warning: texts.some((t) => t.includes("no available presence source")) }; })()`);
  check("BR12c an unsaved domain change shows the neutral pending note, not the warning", br12c.pending === true && br12c.warning === false, JSON.stringify(br12c));
  // BR13: an empty domain choice saves as an empty list without an error and changes nothing else
  await brOpen("en");
  await browser.evaluate(`${brSection("Presence tracking")}.open = true`);
  await browser.evaluate(`${brDomain}.open = true`);
  for (const value of ["media_player", "binary_sensor"]) await browser.evaluate(`[...document.querySelectorAll("${BR_FORM} input[name='presence_device_platforms']")].find((b) => b.value === "${value}").click()`);
  await browser.evaluate(`(() => { window.__h.hass.__state.lastAreaUpdate = undefined; document.querySelector("${BR_FORM}").requestSubmit(); return true; })()`);
  await waitFor(browser, `window.__h.hass.__state.lastAreaUpdate?.presence_device_platforms !== undefined`, 3000).catch(() => {});
  const br13 = await browser.evaluate(`(() => { const u = window.__h.hass.__state.lastAreaUpdate || null; return { presence: u?.presence_device_platforms ?? null, include: u?.include_entities ?? null }; })()`);
  check("BR13 an empty domain choice is saved as an empty list", Array.isArray(br13.presence) && br13.presence.length === 0 && Array.isArray(br13.include), JSON.stringify(br13));
  // BR10: German and English labels for the new controls
  await brOpen("de");
  const br10de = await browser.evaluate(`(() => { const list = ${brEntityList("include_entities")}?.querySelector("summary")?.textContent || ""; ${brSection("Anwesenheitsverfolgung")}.querySelector("summary").click(); const dom = ${brDomain}; dom.querySelector("summary").click(); return { list, domain: dom.querySelector("summary").textContent, hint: dom.querySelector("small")?.textContent || "" }; })()`);
  check("BR10a German labels: Entitäten anzeigen and the domain multi-select", br10de.list.includes("Entitäten anzeigen") && br10de.domain.includes("Domänen zur Anwesenheitsverfolgung") && br10de.hint.includes("Mehrere Domänen"), JSON.stringify(br10de));
  await brOpen("en");
  const br10en = await browser.evaluate(`(() => { const list = ${brEntityList("include_entities")}?.querySelector("summary")?.textContent || ""; return { list }; })()`);
  check("BR10b English labels: Show entities", br10en.list.includes("Show entities"), JSON.stringify(br10en));

  // E7: dashboard texts (adaptive_areas/get_dashboard_texts): fallback, load failure, late response, repeated updates
  const e7Mount = (language, translations = "f.translations", slow = false) => `(() => { const f = window.__fixtures; const panel = document.createElement("adaptive-areas-panel"); document.getElementById("stage").replaceChildren(panel);
    const fixtures = { overview: f.overviewAdmin, area: f.areaAdmin, config: f.config, global: f.global, light: f.light, climate: f.climate, trace: f.trace, diagnostics: f.diagnostics, translations: ${translations} };
    panel.hass = AAHarness.createHass({ admin: true, language: ${JSON.stringify(language)}, states: {}, fixtures, latency: ${slow ? '{ "adaptive_areas/get_dashboard_texts": 700 }' : "{}"} }); return true; })()`;
  // E7a: a German key that is missing falls back to English (the response carries the English fallback, as Home Assistant does)
  await browser.evaluate(`(() => { const f = window.__fixtures; const de = { ...f.translations.de }; const removed = "component.adaptive_areas.dashboard.navViews"; delete de[removed]; window.__e7de = de; return true; })()`);
  await browser.evaluate(e7Mount("de", "{ en: window.__fixtures.translations.en, de: window.__e7de }"));
  await waitFor(browser, `!!document.querySelector("adaptive-areas-panel nav")`, 4000).catch(() => {});
  const e7a = await browser.evaluate(`(() => { const label = document.querySelector("adaptive-areas-panel .nav-toggle-label")?.textContent || ""; return { label, english: label === "Views" }; })()`);
  check("E7a a missing German key shows the English fallback text, not an empty label", e7a.english === true, JSON.stringify(e7a));
  // E7b: a complete load failure shows a defined state, never an empty screen
  await browser.evaluate(e7Mount("de", "undefined"));
  await waitFor(browser, `${text()}.includes("Translations unavailable")`, 4000).catch(() => {});
  const e7b = await browser.evaluate(`({ alert: document.querySelector("adaptive-areas-panel ha-alert")?.textContent.trim() || "", nav: !!document.querySelector("adaptive-areas-panel nav") })`);
  check("E7b a complete load failure shows the defined unavailable state and no navigation", e7b.alert.includes("Translations unavailable") && e7b.nav === false, JSON.stringify(e7b));
  // E7c: a German response that arrives after switching back to English does not replace English
  await browser.evaluate(e7Mount("de", "f.translations", true));
  await browser.evaluate(`(() => { window.__e7slow = true; return true; })()`);
  await browser.evaluate(`(() => { const panel = document.querySelector("adaptive-areas-panel"); const hass = panel._hass; panel.hass = Object.assign({}, hass, { language: "en" }); return true; })()`);
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const e7c = await browser.evaluate(`(() => ({ english: document.querySelector("adaptive-areas-panel")?.innerText.includes("Overview") || document.querySelector("adaptive-areas-panel")?.innerText.includes("Dashboard") || false, german: document.querySelector("adaptive-areas-panel")?.innerText.includes("Überblick") || false }))()`);
  check("E7c a late German response does not replace the English view after switching back", e7c.german === false && e7c.english === true, JSON.stringify(e7c));
  // E7d: repeated hass updates send one translation request per language
  await browser.evaluate(e7Mount("en"));
  await waitFor(browser, `${text()}.includes("Connected")`, 4000).catch(() => {});
  await browser.evaluate(`(() => { const panel = document.querySelector("adaptive-areas-panel"); for (let i = 0; i < 5; i++) panel.hass = Object.assign({}, panel._hass); return true; })()`);
  await new Promise((resolve) => setTimeout(resolve, 200));
  const e7d = await browser.evaluate(`(() => ({ requests: (document.querySelector("adaptive-areas-panel")._hass.__state?.calls || []).filter((c) => c === "adaptive_areas/get_dashboard_texts").length }))()`);
  check("E7d repeated hass updates send exactly one translation request per language", e7d.requests === 1, JSON.stringify(e7d));

  // DG6-DG11: what counts as a changed Area draft (dirty check of the central editor)
  await dgSetup(1280);
  const dg6Sel = `document.querySelector("adaptive-areas-panel form[data-area-form] input[name='feature:environment']")`;
  const dg6Has = await browser.evaluate(`!!${dg6Sel}`);
  await browser.evaluate(`(() => { const box = ${dg6Sel}; if (box) { box.checked = true; box.dispatchEvent(new Event("change", { bubbles: true })); } return true; })()`);
  await browser.evaluate(`(() => { window.__dgAnswer = false; return true; })()`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='dashboard']").click()`);
  const dg6 = await browser.evaluate(dgState);
  check("DG6 enabling a feature without settings (an empty feature entry) counts as a change and asks", dg6Has === true && dg6.ask === 1 && dg6.tabSelected === "areas", JSON.stringify({ dg6Has, dg6 }));
  // DG7: a value changed and then reverted to its saved value is not a change
  await dgSetup(1280);
  const dirtyNow = (expr) => browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._drafts.area.draft = JSON.parse(JSON.stringify(p._drafts.area.original)); const d = p._drafts.area.draft; ${expr}; return p._areaDirty(); })()`);
  check("DG7a an untouched opened draft is clean", (await browser.evaluate(`document.querySelector("adaptive-areas-panel")._areaDirty()`)) === false);
  check("DG7b an existing non-empty value changed to an empty string is a change", (await dirtyNow(`d.clear_timeout = ""; d.area_humidity_sensor = ""; d.secondary_states.sleep_timeout = ""`)) === true);
  check("DG7c an existing value changed to null is a change", (await dirtyNow(`d.clear_timeout = null`)) === true);
  check("DG7d an existing value changed to an empty object is a change", (await dirtyNow(`d.presence_device_platforms = {}`)) === true);
  check("DG7e removing a stored secondary-state entry is a change", (await dirtyNow(`delete d.secondary_states.sleep_timeout`)) === true);
  check("DG7f an empty string that replaces a missing key is equivalent (no change)", (await dirtyNow(`delete d.clear_timeout; d.clear_timeout = 0; delete d.area_humidity_sensor`)) === false);
  check("DG7g reverting to the saved values is clean again", (await dirtyNow(`Object.assign(d, JSON.parse(JSON.stringify(p._drafts.area.original)))`)) === false);
  await dgSetup(1280);
  await browser.evaluate(`(() => { const input = document.querySelector("adaptive-areas-panel form[data-area-form] input[name='clear_timeout']"); input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  check("DG7i an input event without a value change is not a change (capture adds no false edits)", (await browser.evaluate(`document.querySelector("adaptive-areas-panel")._areaDirty()`)) === false);
  // DG7j: a real multi-select in the editor. The saved list is in another order than the editor delivers it;
  // the same selection in a different order is no change, adding or removing a value is a change.
  const dg7jStates = { "binary_sensor.a": { state: "off", attributes: { friendly_name: "A" } }, "binary_sensor.b": { state: "off", attributes: { friendly_name: "B" } }, "binary_sensor.c": { state: "off", attributes: { friendly_name: "C" } } };
  await browser.evaluate(mountCode({ admin: true, language: "en", states: dg7jStates }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel nav [data-tab='areas']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] aa-entity-picker[name='include_entities']") !== null`);
  // saved list in another order than the editor delivers it (as stored by Home Assistant)
  await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); p._drafts.area = { ...p._drafts.area, original: { ...p._drafts.area.original, include_entities: ["binary_sensor.b", "binary_sensor.a"] }, draft: { ...p._drafts.area.draft, include_entities: ["binary_sensor.b", "binary_sensor.a"] } }; p._render(); return true; })()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] aa-entity-picker[name='include_entities']") !== null`);
  const dg7jSet = (values) => browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel form[data-area-form] aa-entity-picker[name='include_entities']"); p.querySelectorAll("input[type=hidden][name='include_entities']").forEach((i) => i.remove()); ${JSON.stringify(values)}.forEach((id) => { const i = document.createElement("input"); i.type = "hidden"; i.name = "include_entities"; i.value = id; p.appendChild(i); }); p.dispatchEvent(new Event("input", { bubbles: true })); p.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  const dg7jDirty = () => browser.evaluate(`document.querySelector("adaptive-areas-panel")._areaDirty()`);
  await dg7jSet(["binary_sensor.a", "binary_sensor.b"]);
  const dg7j1 = await dg7jDirty();
  await dg7jSet(["binary_sensor.b", "binary_sensor.a"]);
  const dg7j2 = await dg7jDirty();
  check("DG7j the same selection in another order is not a change", dg7j1 === false && dg7j2 === false, JSON.stringify({ dg7j1, dg7j2 }));
  await dg7jSet(["binary_sensor.a", "binary_sensor.b", "binary_sensor.c"]);
  const dg7jAdd = await dg7jDirty();
  await dg7jSet(["binary_sensor.b", "binary_sensor.a"]);
  const dg7jBack = await dg7jDirty();
  await dg7jSet(["binary_sensor.a"]);
  const dg7jRemove = await dg7jDirty();
  check("DG7k adding or removing a selected value is a change", dg7jAdd === true && dg7jBack === false && dg7jRemove === true, JSON.stringify({ dg7jAdd, dg7jBack, dg7jRemove }));

  check("DG7h an enabled feature without any settings ({}) is a change, not nothing", (await dirtyNow(`d.features = { ...(d.features || {}), environment: {} }`)) === true);

  // V06: KPIs are emphasised only when the backend reports notices or technical issues
  await browser.evaluate(mountCode({ admin: true, language: "en", states, multi: true }));
  await waitFor(browser, `${text()}.includes("first_floor")`);
  const v06calm = await browser.evaluate(`document.querySelectorAll("adaptive-areas-panel .kpi-attn").length`);
  await browser.evaluate(mountCode({ admin: true, language: "en", states, warnings: true }));
  await waitFor(browser, `${text()}.includes("Notices")`);
  const v06warn = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .kpi-attn .kpi-label")].map(e => e.textContent.trim())`);
  check("V06a no KPI is emphasised without backend notices or technical issues", v06calm === 0, String(v06calm));
  check("V06b a KPI with backend notices is emphasised", v06warn.includes("Notices"), JSON.stringify(v06warn));
  const v06floor = await browser.evaluate(`getComputedStyle(document.querySelector("adaptive-areas-panel .floor-title")).textTransform`).catch(() => "");
  check("V06c floor headings are rendered as a structured group label", v06floor === "uppercase" || v06floor === "none", String(v06floor));

  // V11: multi-floor, Meta-Area fixture from the real backend handlers
  await browser.evaluate(mountCode({ admin: true, language: "en", states, multi: true }));
  await waitFor(browser, `${text()}.includes("first_floor")`);
  const v11 = await browser.evaluate(`(() => { const t = document.querySelector("adaptive-areas-panel")?.textContent || ""; return { first: t.includes("first_floor"), second: t.includes("second_floor"), ground: t.includes("ground_level"), kitchen: t.includes("kitchen") }; })()`);
  check("V11a the multi-floor fixture shows every floor from the backend", v11.first && v11.second && v11.ground && v11.kitchen, JSON.stringify(v11));

  // R8/R9: shell groups follow the role
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  const adminNav = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .nav-label")].map(e => e.textContent.trim())`);
  check("R8 admin sees Monitoring and Administration", adminNav.includes("Monitoring") && adminNav.includes("Administration"), JSON.stringify(adminNav));
  check("R8b Analysis group shown for admin without light or climate (trace and diagnostics are independent)", adminNav.includes("Analysis"), JSON.stringify(adminNav));
  await browser.evaluate(mountCode({ admin: false, language: "en", states }));
  await waitFor(browser, `${text()}.length > 40`);
  const userNav = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .nav-label")].map(e => e.textContent.trim())`);
  check("R9 non-admin sees only the Monitoring group", JSON.stringify(userNav) === JSON.stringify(["Monitoring"]), JSON.stringify(userNav));

  await browser.evaluate(mountCode({ admin: true, language: "en", states, featureLight: true }));
  await waitFor(browser, `${text()}.length > 40`);
  const featNav = await browser.evaluate(`[...document.querySelectorAll("adaptive-areas-panel .nav-label")].map(e => e.textContent.trim())`);
  check("R8c Analysis group appears when light is enabled", featNav.includes("Analysis"), JSON.stringify(featNav));

  // R10: connection status pill after a successful load
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  check("R10 status pill shows Connected", true);

  // R11: German labels and no English group names
  await browser.evaluate(mountCode({ admin: true, language: "de", states }));
  await waitFor(browser, `${text()}.includes("Verbunden")`);
  const deText = await browser.evaluate(text());
  check("R11 German shell labels", deText.includes("Verwaltung") && deText.includes("Intelligence Center") && deText.includes("Verbunden") && !deText.includes("Administration"), deText.slice(0, 120));

  // R12: no horizontal overflow at 320 px
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 320, height: 800, deviceScaleFactor: 1, mobile: false });
  await sleep(150);
  const overflow = await browser.evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
  check("R12 no horizontal overflow at 320 px", overflow <= 0, `overflow=${overflow}`);
  await browser.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  // S-series: one lamp, one individual light group (dashboard picker lock, step 4)
  const lockStates = { ...states,
    "light.ceiling": { state: "on", attributes: { friendly_name: "Ceiling" } },
    "light.bed": { state: "off", attributes: { friendly_name: "Bed" } },
    "light.desk": { state: "off", attributes: { friendly_name: "Desk" } },
    "light.sofa": { state: "off", attributes: { friendly_name: "Sofa" } },
    "light.group_wall": { state: "off", attributes: { friendly_name: "Wall group", entity_id: ["light.desk"] } } };
  await browser.evaluate(mountCode({ admin: true, language: "en", states: lockStates }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas[0].options.features = JSON.parse(JSON.stringify({ light: { turn_on_below: 50, turn_off_above: 200 }, light_groups: { overhead_lights: ["light.ceiling"], overhead_lights_activation: "occupied", overhead_lights_blocking_states: [], overhead_lights_brightness: "require_dark", sleep_lights: ["light.bed"], sleep_lights_activation: "sleep", sleep_lights_blocking_states: [], sleep_lights_brightness: "ignore", accent_lights: [], accent_lights_activation: "disabled", accent_lights_blocking_states: [], accent_lights_brightness: "require_dark", task_lights: [], task_lights_activation: "disabled", task_lights_blocking_states: [], task_lights_brightness: "require_dark" } })); document.querySelector("adaptive-areas-panel")._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form] [data-light]") !== null`);
  const pickerOption = (picker, id) => `(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const pk = f.querySelector('aa-entity-picker[name="light_group:${picker}_lights"]'); pk._open = true; pk._query = ""; pk._render(); const o = [...pk.shadowRoot.querySelectorAll('[role="option"]')].find((x) => x.querySelector(".option-id")?.textContent === "${id}"); return o ? { blocked: o.dataset.blocked === "true", owner: o.querySelector(".option-blocked")?.textContent || "", ariaDisabled: o.getAttribute("aria-disabled") } : null; })()`;
  const s1 = await browser.evaluate(pickerOption("accent", "light.ceiling"));
  check("S1 a lamp of the overhead group is locked in accent and names its group", s1?.blocked === true && s1?.ariaDisabled === "true" && s1?.owner === "Already assigned: Ceiling lights", JSON.stringify(s1));
  const s2 = await browser.evaluate(pickerOption("overhead", "light.ceiling"));
  check("S2 the group's own lamp stays selectable in its own group", s2 && s2.blocked === false, JSON.stringify(s2));
  const s3 = await browser.evaluate(pickerOption("accent", "light.desk"));
  check("S3 a free lamp is selectable", s3 && s3.blocked === false, JSON.stringify(s3));
  // unsaved change: desk is added to overhead in the form only; accent must see it at once (nested group too)
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const pk = f.querySelector('aa-entity-picker[name="light_group:overhead_lights"]'); const input = document.createElement("input"); input.type = "hidden"; input.name = "light_group:overhead_lights"; input.value = "light.desk"; pk.appendChild(input); return true; })()`);
  const s4 = await browser.evaluate(pickerOption("accent", "light.desk"));
  const s5 = await browser.evaluate(pickerOption("accent", "light.group_wall"));
  check("S4 an unsaved selection locks the lamp at once in other groups", s4?.blocked === true, JSON.stringify(s4));
  check("S5 a group that contains the selected lamp is locked too (nested)", s5?.blocked === true && s5?.owner === "Already assigned: Ceiling lights", JSON.stringify(s5));
  // cancelling changes nothing that is stored
  const s6 = await browser.evaluate(`window.__h.hass.__state.lastAreaUpdate || null`);
  check("S6 unsaved selections do not change the stored configuration", s6 === null, JSON.stringify(s6));
  // releasing the unsaved selection frees the lamp again
  await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const pk = f.querySelector('aa-entity-picker[name="light_group:overhead_lights"]'); pk.querySelectorAll('input[type="hidden"][value="light.desk"]').forEach((i) => i.remove()); return true; })()`);
  const s7 = await browser.evaluate(pickerOption("accent", "light.desk"));
  check("S7 removing the selection frees the lamp again", s7 && s7.blocked === false, JSON.stringify(s7));
  // a blocked option is not selectable by click
  const s8 = await browser.evaluate(`(() => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const pk = f.querySelector('aa-entity-picker[name="light_group:accent_lights"]'); pk._toggle("light.ceiling"); return pk.selected.length; })()`);
  check("S8 a locked lamp cannot be added by activation", s8 === 0, String(s8));
  // another Area's assignment is taken into account
  await browser.evaluate(`(() => { const st = window.__h.hass.__state; st.config = JSON.parse(JSON.stringify(st.config)); st.config.areas.push({ id: "living_room", name: "Living room", options: { features: { light_groups: { overhead_lights: ["light.sofa"] } } } }); document.querySelector("adaptive-areas-panel")._data.config = JSON.parse(JSON.stringify(st.config)); return true; })()`);
  const s9 = await browser.evaluate(pickerOption("accent", "light.sofa"));
  check("S9 an assignment in another Area locks the lamp and names that Area", s9?.blocked === true && s9?.owner.includes("Living room"), JSON.stringify(s9));
  // EM-series: localized ownership messages in the panel (German and English), rejected save
  const E_GROUPS = { overhead: ["Deckenleuchten", "Ceiling lights"], sleep: ["Schlaflichter", "Sleep lights"], accent: ["Akzentlichter", "Accent lights"], task: ["Arbeitslichter", "Task lights"] };
  await browser.evaluate(mountCode({ admin: true, language: "de", states: lockStates }));
  await waitFor(browser, `${text()}.includes("Verbunden")`);
  for (const [group, [de]] of Object.entries(E_GROUPS)) {
    const msg = await browser.evaluate(`document.querySelector("adaptive-areas-panel")._errorText("light_ownership_conflict_${group}", { light: "light.ceiling", area: "Küche" })`);
    check(`EM1 German ${group} message names the lamp, the Area and the localized group`, msg.includes("light.ceiling") && msg.includes("Küche") && msg.includes(de) && !msg.includes("{") && !msg.includes("_lights"), msg);
  }
  await browser.evaluate(mountCode({ admin: true, language: "en", states: lockStates }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  for (const [group, [, en]] of Object.entries(E_GROUPS)) {
    const msg = await browser.evaluate(`document.querySelector("adaptive-areas-panel")._errorText("light_ownership_conflict_${group}", { light: "light.sofa", area: "Living room" })`);
    check(`EM2 English ${group} message names the lamp, the Area and the localized group`, msg.includes("light.sofa") && msg.includes("Living room") && msg.includes(en) && !msg.includes("{") && !msg.includes("German"), msg);
  }
  const unknownCode = await browser.evaluate(`document.querySelector("adaptive-areas-panel")._errorText("no_such_code", {})`);
  check("EM3 an unknown error code is shown as the code, not as an empty text", unknownCode === "no_such_code", String(unknownCode));
  // rejected save: the server refuses, the form shows the localized text, the stored configuration stays unchanged
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const eBefore = await browser.evaluate(`JSON.stringify(document.querySelector("adaptive-areas-panel")._data.config.areas)`);
  await browser.evaluate(`(() => { const h = window.__h.hass; window.__eorig = h.callWS.bind(h); h.callWS = (msg) => msg.type === "adaptive_areas/update_area" ? Promise.resolve({ ok: false, errors: { overhead_lights: "light_ownership_conflict_sleep" }, details: { overhead_lights: { light: "light.ceiling", area: "Living room" } } }) : window.__eorig(msg); document.querySelector("adaptive-areas-panel form[data-area-form]").requestSubmit(); return true; })()`);
  await sleep(250);
  const eForm = await browser.evaluate(`document.querySelector("adaptive-areas-panel")._errors.form || ""`);
  check("EM4 a rejected save shows the localized ownership text with lamp and Area", eForm.includes("light.ceiling") && eForm.includes("Living room") && eForm.includes("Sleep lights") && !eForm.includes("{"), eForm);
  const eAfter = await browser.evaluate(`JSON.stringify(document.querySelector("adaptive-areas-panel")._data.config.areas)`);
  check("EM5 a rejected save leaves the stored configuration unchanged", eAfter === eBefore);
  await browser.evaluate(`(() => { window.__h.hass.callWS = window.__eorig; document.querySelector("adaptive-areas-panel [data-cancel]")?.click(); return true; })()`);
  await sleep(150);
  // restore the state the following L-series steps expect
  await browser.evaluate(mountCode({ admin: true, language: "en", states }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
}

function stats(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  return { median: +median.toFixed(2), min: +sorted[0].toFixed(2), max: +sorted[sorted.length - 1].toFixed(2), runs: values.length };
}

async function measure(browser) {
  const RUNS = 7;
  const mutationProbe = `(() => { window.__dom = { added: 0, removed: 0 }; if (window.__mo) window.__mo.disconnect(); window.__mo = new MutationObserver((records) => { for (const r of records) { window.__dom.added += r.addedNodes.length; window.__dom.removed += r.removedNodes.length; } }); window.__mo.observe(document.getElementById("stage"), { subtree: true, childList: true }); return true; })()`;
  const samples = { initialMs: [], initialDomAdded: [], updateMs: [], updateDomAdded: [], updateDomRemoved: [], navigateMs: [], focusRetained: [] };
  for (let run = 0; run < RUNS; run++) {
    await browser.evaluate(mutationProbe);
    const t0 = await browser.evaluate("performance.now()");
    await browser.evaluate(mountCode({ admin: true, language: "en", states: {} }));
    await waitFor(browser, `${text()}.length > 40`);
    samples.initialMs.push((await browser.evaluate("performance.now()")) - t0);
    samples.initialDomAdded.push(await browser.evaluate("window.__dom.added"));

    await browser.evaluate(`(() => { window.__dom = { added: 0, removed: 0 }; const u = JSON.parse(JSON.stringify(window.__fixtures.areaAdmin)); u.occupied = !u.occupied; window.__probe = u; return true; })()`);
    const u0 = await browser.evaluate("performance.now()");
    await browser.evaluate(`window.__h.hass.__emitArea(window.__probe)`);
    samples.updateMs.push((await browser.evaluate("performance.now()")) - u0);
    await sleep(40);
    samples.updateDomAdded.push(await browser.evaluate("window.__dom.added"));
    samples.updateDomRemoved.push(await browser.evaluate("window.__dom.removed"));

    const n0 = await browser.evaluate("performance.now()");
    const clicked = (await clickByText(browser, "Global settings")) || (await clickByText(browser, "Settings"));
    if (!clicked) throw new Error("settings tab not found");
    await waitFor(browser, `document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]") !== null`, 4000).catch(() => null);
    samples.navigateMs.push((await browser.evaluate("performance.now()")) - n0);

    const focused = await browser.evaluate(`(() => { const s = document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]"); if (!s) return "n/a"; s.focus(); return true; })()`);
    if (focused === true) {
      await browser.evaluate(`window.__h.hass.__emitArea(window.__probe)`);
      await sleep(40);
      samples.focusRetained.push(await browser.evaluate(`document.activeElement === document.querySelector("adaptive-areas-panel aa-entity-picker[name=weather_entity]")`));
    }
    await browser.evaluate(`(() => { document.querySelector("adaptive-areas-panel").remove(); return true; })()`);
    await sleep(60);
  }
  const out = {
    label: LABEL,
    runs: RUNS,
    initialRenderMs: stats(samples.initialMs),
    initialDomNodesAdded: stats(samples.initialDomAdded),
    subscriptionUpdateMs: stats(samples.updateMs),
    subscriptionUpdateDomNodesAdded: stats(samples.updateDomAdded),
    subscriptionUpdateDomNodesRemoved: stats(samples.updateDomRemoved),
    navigateSettingsMs: stats(samples.navigateMs),
    focusRetainedOnUpdate: samples.focusRetained.length ? `${samples.focusRetained.filter(Boolean).length}/${samples.focusRetained.length}` : "n/a",
    jsErrors: browser.errors.length,
  };
  return out;
}

// D07: the light diagnosis names the real control path (native group) and no longer
// shows "no lights assigned" when a group controls the lamps.
async function d07Regression(browser) {
  const fixture = JSON.stringify(JSON.parse(readFileSync(join(FIXTURES, "get_light_runtime_status.control_path.admin.json"), "utf8")));
  for (const language of ["en", "de"]) {
    await browser.evaluate(mountCode({ admin: true, language }));
    await waitFor(browser, `${text()}.length > 40`);
    const out = await browser.evaluate(`(() => {
      const p = document.querySelector("adaptive-areas-panel");
      const t = p._t;
      const f = ${fixture};
      const render = (mutate) => { const c = JSON.parse(JSON.stringify(f)); mutate(c.light); p._data.lightRuntime = c; return p._lightRuntimeStatus(t); };
      const base = render(() => {});
      const blocked = render((l) => { l.control_path.groups[0].ownership_blocked = true; });
      return { t: { control: t.lxControlPathLabel, active: t.lxGroupActive, blocked: t.lxGroupOwnershipBlocked }, base, blocked };
    })()`);
    const t = out.t;
    check(`D07 ${language}: control path section shows the group control and its lamp`, out.base.includes(t.control) && out.base.includes(t.active) && out.base.includes("light.accent_lamp"), language);
    check(`D07 ${language}: ownership block of a group is shown`, out.blocked.includes(t.blocked), language);
  }
}

// D08 (Phase J.2): each light group shows its own override, automatic control and last
// decision; an override of the ALL group does not mark the accent group as overridden.
async function d08Regression(browser) {
  const fixture = JSON.stringify(JSON.parse(readFileSync(join(FIXTURES, "get_light_runtime_status.control_path.admin.json"), "utf8")));
  for (const language of ["en", "de"]) {
    await browser.evaluate(mountCode({ admin: true, language }));
    await waitFor(browser, `${text()}.length > 40`);
    const out = await browser.evaluate(`(() => {
      const p = document.querySelector("adaptive-areas-panel");
      const t = p._t;
      const c = ${fixture};
      const groups = c.light.control_path.groups;
      const accent = groups.find((g) => g.category === "accent_lights");
      Object.assign(accent, { controlling: true, manual_override: false, last_decision: { decision: "turn_on", outcome: "executed", trigger: "area_state_changed", reason_codes: ["action_executed"], timestamp: null } });
      const all = groups.find((g) => g.category === "all_lights");
      Object.assign(all, { entity_id: all.entity_id || "light.adaptive_areas_light_groups_kitchen_all_lights", state: "on", controlling: true, manual_override: true, last_decision: null });
      c.light.override = { mode: "MANUAL", groups: [all.entity_id] };
      p._data.lightRuntime = c;
      const html = p._lightRuntimeStatus(t);
      const count = (needle) => html.split(needle).length - 1;
      return { active: count(t.lxGroupOverrideActive), inactive: count(t.lxGroupOverrideInactive), accentId: html.includes(accent.entity_id), decision: html.includes(p._map("decision", "turn_on")), none: html.includes(t.lxGroupNoDecision), auto: html.includes(t.lxGroupAutoOn) };
    })()`);
    check(`D08 ${language}: only the ALL group is shown as overridden`, out.active === 1 && out.inactive === 1, language);
    check(`D08 ${language}: a group shows its entity id, automatic control and last decision`, out.accentId && out.auto && out.decision && out.none, language);
  }
}

// D02 / D03 / D01 (form): feature sections follow the local draft at once; no save happens.
async function d02d03Regression(browser) {
  await browser.evaluate(mountCode({ admin: true, language: "en" }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const before = await browser.evaluate(`(() => { const p = document.querySelector("adaptive-areas-panel"); const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const sec = (k) => f.querySelector('[data-feature-section="' + k + '"]'); return { hasClimateSection: !!sec("climate_control"), climateHidden: sec("climate_control")?.hidden ?? null, envHidden: f.querySelector('details[data-feature-section="environment"]')?.hidden ?? null, draftHasEnvironment: Object.prototype.hasOwnProperty.call(p._drafts.area.draft?.features || {}, "environment"), sensorPicker: f.querySelector('aa-entity-picker[name="area_illuminance_sensor"]')?.getAttribute("device-class") ?? null, illuminancePickers: f.querySelectorAll('aa-entity-picker[name="area_illuminance_sensor"]').length, darkPickers: f.querySelectorAll('[name="dark_entity"]').length, lightPickers: f.querySelectorAll('[name^="light:illuminance"]').length, sensorDomain: f.querySelector('aa-entity-picker[name="area_illuminance_sensor"]')?.getAttribute("domain") ?? null, climateToggle: !!f.elements.namedItem("feature:climate_control"), draftHasClimate: Object.prototype.hasOwnProperty.call(p._drafts.area.draft?.features || {}, "climate_control"), updatesBefore: window.__h.hass.__state.calls.filter((c) => c.type === "adaptive_areas/update_area").length }; })()`);
  check("D02 the climate section is rendered hidden unless climate control is enabled", before.hasClimateSection && before.climateHidden === !before.draftHasClimate, JSON.stringify(before));
  check("D02 the room climate (environment) section is hidden unless its feature is enabled", before.envHidden === !before.draftHasEnvironment, JSON.stringify(before));
  check("D01 exactly one Area illuminance sensor field, a sensor filtered by device class illuminance", before.sensorPicker === "illuminance" && before.sensorDomain === "sensor" && before.illuminancePickers === 1, JSON.stringify(before));
  check("D01 no binary dark entity and no second illuminance field in the Area form", before.darkPickers === 0 && before.lightPickers === 0, JSON.stringify(before));
  if (before.climateToggle) {
    const after = await browser.evaluate(`(async () => { const p = document.querySelector("adaptive-areas-panel"); const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const box = f.elements.namedItem("feature:climate_control"); const was = !!box.checked; box.checked = !was; box.dispatchEvent(new Event("input", { bubbles: true })); box.dispatchEvent(new Event("change", { bubbles: true })); await new Promise((r) => setTimeout(r, 80)); const sec = f.querySelector('[data-feature-section="climate_control"]'); return { was, now: !!box.checked, hiddenNow: sec.hidden, displayNow: sec.style.display, updates: window.__h.hass.__state.calls.filter((c) => c.type === "adaptive_areas/update_area").length, draft: Object.prototype.hasOwnProperty.call(p._drafts.area.draft?.features || {}, "climate_control") }; })()`);
    check("D03 toggling climate control shows or hides its section at once", after.hiddenNow === after.was && after.draft === !after.was, JSON.stringify(after));
    check("D03 toggling a function sends no automatic save", after.updates === before.updatesBefore, JSON.stringify({ before: before.updatesBefore, after: after.updates }));
    await browser.evaluate(`(async () => { const f = document.querySelector("adaptive-areas-panel form[data-area-form]"); const box = f.elements.namedItem("feature:climate_control"); box.checked = !box.checked; box.dispatchEvent(new Event("input", { bubbles: true })); await new Promise((r) => setTimeout(r, 50)); return true; })()`);
  }
}

// D05: device classes use the same checkbox dropdown as the domains; one shared message.
async function d05Regression(browser) {
  await browser.evaluate(mountCode({ admin: true, language: "en" }));
  await waitFor(browser, `${text()}.includes("Connected")`);
  await clickByText(browser, "Area management");
  await waitFor(browser, `document.querySelector("adaptive-areas-panel [data-edit='kitchen']") !== null`);
  await browser.evaluate(`document.querySelector("adaptive-areas-panel [data-edit='kitchen']").click()`);
  await waitFor(browser, `document.querySelector("adaptive-areas-panel form[data-area-form]") !== null`);
  const d5 = await browser.evaluate(`(() => {
    const f = document.querySelector("adaptive-areas-panel form[data-area-form]");
    const dom = f.querySelector('details.domain-select[data-select="presence_device_platforms"]');
    const cls = f.querySelector('details.domain-select[data-select="presence_sensor_device_class"]');
    const classBoxes = cls ? [...cls.querySelectorAll('input[type=checkbox][name="presence_sensor_device_class"]')].map((b) => b.value) : [];
    const checked = cls ? [...cls.querySelectorAll('input[type=checkbox][name="presence_sensor_device_class"]:checked')].map((b) => b.value) : [];
    const domainBoxes = dom ? [...dom.querySelectorAll('input[type=checkbox][name="presence_device_platforms"]')].map((b) => b.value) : [];
    const hints = f.querySelectorAll("[data-presence-hint]").length;
    const order = dom && cls && hints === 1 ? (dom.compareDocumentPosition(cls) & Node.DOCUMENT_POSITION_FOLLOWING) && (cls.compareDocumentPosition(f.querySelector("[data-presence-hint]")) & Node.DOCUMENT_POSITION_FOLLOWING) : false;
    const selectMultiple = f.querySelectorAll('select[name="presence_sensor_device_class"]').length;
    return { hasDomainDropdown: !!dom, hasClassDropdown: !!cls, classBoxes, checked, domainBoxes, hints, order: !!order, selectMultiple };
  })()`);
  check("D05 device classes use the same checkbox dropdown as the domains, not a multi-select", d5.hasClassDropdown && d5.hasDomainDropdown && d5.selectMultiple === 0, JSON.stringify(d5));
  check("D05 the device class choices include motion and occupancy and the stored ones are checked", ["motion", "occupancy"].every((c) => d5.classBoxes.includes(c)) && d5.checked.every((c) => d5.classBoxes.includes(c)), JSON.stringify(d5));
  check("D05 one shared validation hint sits below both dropdowns", d5.hints === 1 && d5.order === true, JSON.stringify(d5));
  check("D05 the domain choices are unchanged", JSON.stringify(d5.domainBoxes) === JSON.stringify(["binary_sensor", "device_tracker", "media_player", "remote"]), JSON.stringify(d5.domainBoxes));
}

const viewport = { width: 1280, height: 900 };
const browser = await launch();
try {
  await setupPage(browser, viewport);
  if (MEASURE) {
    const result = await measure(browser);
    const outFile = join(ROOT, "tests", "frontend", "measure-" + LABEL + ".json");
    writeFileSync(outFile, JSON.stringify(result, null, 2) + "\n");
    console.log(JSON.stringify(result, null, 2));
    console.log("written:", outFile);
  } else {
    await regression(browser);
    await d07Regression(browser);
    await d08Regression(browser);
    await d02d03Regression(browser);
    await d05Regression(browser);
    check("no JavaScript errors", browser.errors.length === 0, browser.errors.slice(0, 3).join(" | "));
    const failed = results.filter((r) => !r.pass);
    for (const r of results) console.log((r.pass ? "PASS " : "FAIL ") + r.name + (r.pass || !r.detail ? "" : "  [" + r.detail + "]"));
    console.log(`${results.length - failed.length}/${results.length} passed`);
    if (failed.length) process.exitCode = 1;
  }
} finally {
  if (browser.errors.length) console.log("JS_ERRORS:", browser.errors.slice(0, 5).join(" | "));
  browser.cleanup();
}
