/*
 * Frontend test harness: a simulated Home Assistant `hass` object for the
 * Adaptive Areas panel. Test-only; never shipped with the integration.
 *
 * Responses are the real backend DTOs exported by tests/test_frontend_fixtures.py.
 * Write commands mutate only this in-memory mock state.
 */
(function () {
  "use strict";
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function createHass(options) {
    const fixtures = options.fixtures;
    const state = {
      online: true,
      calls: [],
      subscriptions: [],
      unsubscribed: 0,
      global: clone(fixtures.global),
      config: clone(fixtures.config),
      overview: clone(fixtures.overview),
      area: clone(fixtures.area),
    };
    const latency = options.latency || {};
    const failures = options.failures || {};

    function respond(type, payload) {
      if (!state.online) {
        return Promise.reject(Object.assign(new Error("Connection lost"), { code: "connection_lost" }));
      }
      if (failures[type]) {
        return Promise.reject(Object.assign(new Error(failures[type]), { code: "failed" }));
      }
      return wait(latency[type] || 0).then(() => clone(payload));
    }

    const hass = {
      user: { is_admin: Boolean(options.admin), name: "harness" },
      language: options.language || "de",
      states: clone(options.states || {}),
      callWS(message) {
        state.calls.push(message.type);
        switch (message.type) {
          case "adaptive_areas/get_dashboard_texts": {
            // Same response shape as Home Assistant: flat keys, English merged as fallback (see translation.py)
            const language = message.language === "de" ? "de" : "en";
            const table = fixtures.translations;
            if (!table) return Promise.reject(Object.assign(new Error("translations unavailable"), { code: "not_found" }));
            const resources = language === "de" ? { ...table.en, ...table.de } : table.en;
            return respond(message.type, { resources });
          }
          case "adaptive_areas/get_overview":
            return respond(message.type, state.overview);
          case "adaptive_areas/get_area":
            return respond(message.type, state.area);
          case "adaptive_areas/get_area_configuration":
            return respond(message.type, state.config);
          case "adaptive_areas/get_global_configuration":
            return respond(message.type, state.global);
          case "adaptive_areas/get_light_runtime_status":
            return respond(message.type, fixtures.light);
          case "adaptive_areas/get_climate_runtime_status":
            return respond(message.type, fixtures.climate);
          case "adaptive_areas/get_decision_trace":
            return respond(message.type, fixtures.trace);
          case "adaptive_areas/get_diagnostics":
            return respond(message.type, fixtures.diagnostics);
          case "adaptive_areas/update_global_configuration": {
            state.lastGlobalUpdate = clone(message.options);
            const merged = { ...state.global.options, ...message.options };
            state.global = { ...state.global, options: merged };
            return respond(message.type, { ok: true, errors: {}, options: merged });
          }
          case "adaptive_areas/update_area":
            state.lastAreaUpdate = clone(message.options);
            return respond(message.type, { ok: true, errors: {} });
          case "adaptive_areas/create_area":
          case "adaptive_areas/delete_area":
            return respond(message.type, { ok: true, errors: {} });
          default:
            return Promise.reject(new Error("Unhandled command " + message.type));
        }
      },
      connection: {
        listeners: {},
        addEventListener(name, fn) {
          (this.listeners[name] = this.listeners[name] || []).push(fn);
        },
        removeEventListener(name, fn) {
          this.listeners[name] = (this.listeners[name] || []).filter((item) => item !== fn);
        },
        subscribeMessage(callback, message) {
          if (!state.online) {
            return Promise.reject(Object.assign(new Error("Connection lost"), { code: "connection_lost" }));
          }
          const entry = { callback, type: message.type };
          state.subscriptions.push(entry);
          return Promise.resolve(() => {
            state.subscriptions = state.subscriptions.filter((item) => item !== entry);
            state.unsubscribed += 1;
          });
        },
      },
    };
    hass.__state = state;
    hass.__connection = hass.connection;
    hass.__emitConnection = (name) => {
      (hass.connection.listeners[name] || []).slice().forEach((fn) => fn());
    };
    hass.__listenerCount = (name) => (hass.connection.listeners[name] || []).length;
    hass.__activeSubscriptions = () => state.subscriptions.length;
    hass.__emitArea = (summary) => {
      state.subscriptions.forEach((item) => item.callback({ area: clone(summary) }));
    };
    hass.__emitEvent = (payload) => {
      state.subscriptions.forEach((item) => item.callback(clone(payload)));
    };
    hass.__setOnline = (online) => {
      state.online = online;
    };
    return hass;
  }

  function mount(options) {
    const stage = document.getElementById("stage");
    stage.replaceChildren();
    const panel = document.createElement("adaptive-areas-panel");
    stage.append(panel);
    const hass = createHass(options);
    panel.hass = hass;
    return { panel, hass };
  }

  window.AAHarness = { createHass, mount, wait };
})();
