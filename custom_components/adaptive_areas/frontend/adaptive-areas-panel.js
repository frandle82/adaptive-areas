const TEXT = {
  en: { overview: "Overview", areas: "Areas", diagnostics: "Diagnostics", loading: "Loading…", empty: "No Adaptive Areas configured.", error: "Adaptive Areas could not be loaded.", occupied: "Occupied", clear: "Clear", unavailable: "Unavailable" },
  de: { overview: "Übersicht", areas: "Areas", diagnostics: "Diagnose", loading: "Laden…", empty: "Noch keine Adaptive Areas konfiguriert.", error: "Adaptive Areas konnte nicht geladen werden.", occupied: "Belegt", clear: "Frei", unavailable: "Nicht verfügbar" },
};

const escape = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);

class AdaptiveAreasPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) this._load();
  }

  connectedCallback() { this._render(); }
  disconnectedCallback() { this._unsubscribe?.(); }
  get _text() { return TEXT[this._hass?.language?.startsWith("de") ? "de" : "en"]; }

  async _load() {
    this._loaded = true;
    this._render();
    try {
      this._overview = await this._hass.callWS({ type: "adaptive_areas/get_overview" });
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (event) => this._updateArea(event.area),
        { type: "adaptive_areas/subscribe_updates" },
      );
    } catch (_error) { this._error = true; }
    this._render();
  }

  _updateArea(area) {
    if (!this._overview) return;
    this._overview.areas = this._overview.areas.map((item) => item.id === area.id ? area : item);
    this._render();
  }

  async _select(area) {
    this._selected = await this._hass.callWS({ type: "adaptive_areas/get_area", area_id: area.id });
    this._tab = "areas";
    this._render();
  }

  async _diagnostics() {
    this._diagnosticsData ??= await this._hass.callWS({ type: "adaptive_areas/get_diagnostics" });
    this._tab = "diagnostics";
    this._render();
  }

  _render() {
    if (!this.isConnected) return;
    const t = this._text;
    const tab = this._tab || "overview";
    const body = this._error ? `<ha-alert alert-type="error">${t.error}</ha-alert>` : !this._overview ? `<div class="center"><ha-spinner></ha-spinner>${t.loading}</div>` : this._content(tab, t);
    this.innerHTML = `<style>
      :host { display:block; padding:16px; max-width:1200px; margin:auto; color:var(--primary-text-color); }
      header, nav, .stats, .grid { display:flex; gap:12px; flex-wrap:wrap; } header { align-items:center; justify-content:space-between; } nav { margin:16px 0; } button { background:var(--secondary-background-color); color:inherit; border:0; border-radius:8px; padding:9px 13px; cursor:pointer; } button.active { background:var(--primary-color); color:var(--text-primary-color); } .stats > div, .card { padding:14px; border-radius:12px; background:var(--card-background-color); box-shadow:var(--ha-card-box-shadow, none); } .stats > div { min-width:110px; } .stats strong { display:block; font-size:1.4rem; } .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); } .card { text-align:left; color:inherit; } .meta { opacity:.7; } .center { display:grid; place-items:center; min-height:160px; gap:12px; } .section { margin:16px 0; } .sources { font-family:var(--code-font-family, monospace); font-size:.9em; } @media (max-width:600px) { :host { padding:12px; } .stats { display:grid; grid-template-columns:repeat(2, 1fr); } }
    </style><header><h1>Adaptive Areas</h1></header><nav><button class="${tab === "overview" ? "active" : ""}" data-tab="overview">${t.overview}</button><button class="${tab === "areas" ? "active" : ""}" data-tab="areas">${t.areas}</button><button class="${tab === "diagnostics" ? "active" : ""}" data-tab="diagnostics">${t.diagnostics}</button></nav>${body}`;
    this.querySelectorAll("[data-tab]").forEach((button) => button.onclick = () => button.dataset.tab === "diagnostics" ? this._diagnostics() : (this._tab = button.dataset.tab, this._render()));
    this.querySelectorAll("[data-area]").forEach((button) => button.onclick = () => this._select(this._overview.areas.find((area) => area.id === button.dataset.area)));
  }

  _content(tab, t) {
    if (tab === "diagnostics") return this._diagnosticsData ? this._diagnosticsView() : `<div class="center"><ha-spinner></ha-spinner></div>`;
    if (tab === "areas" && this._selected) return this._detailView(this._selected, t);
    const counts = this._overview.counts;
    const cards = this._overview.areas.map((area) => this._card(area, t)).join("");
    return `<div class="stats"><div><strong>${counts.areas}</strong>Areas</div><div><strong>${counts.occupied}</strong>${t.occupied}</div><div><strong>${counts.dark}</strong>Dark</div><div><strong>${counts.lights_on}</strong>Lights on</div></div>${cards ? `<div class="grid section">${cards}</div>` : `<ha-alert>${t.empty}</ha-alert>`}`;
  }

  _card(area, t) {
    const brightness = area.brightness?.state ? `${escape(area.brightness.state)}${area.brightness.illuminance !== null ? ` · ${escape(area.brightness.illuminance)} ${escape(area.brightness.unit || "")}` : ""}` : t.unavailable;
    const lights = area.lights ? `${area.lights.on} / ${area.lights.total} 💡` : "";
    return `<button class="card" data-area="${escape(area.id)}"><strong>${escape(area.name)}</strong><p>${area.type === "meta" ? "Meta Area · " : ""}${area.occupied ? t.occupied : t.clear}</p><p>${brightness}</p><p>${lights}</p></button>`;
  }

  _detailView(area, t) {
    const list = (items) => items?.length ? `<ul class="sources">${items.map((item) => `<li>${escape(item.name || item.entity_id)}: ${escape(item.state ?? t.unavailable)}</li>`).join("")}</ul>` : "";
    const aggregates = area.aggregates.map((item) => `<div class="section"><strong>${escape(item.device_class || item.entity_id)}</strong><br>${escape(item.state ?? t.unavailable)} ${escape(item.unit || "")} (${item.available_count}/${item.source_count})${list(item.sources)}</div>`).join("");
    const environment = area.environment ? Object.entries(area.environment).filter(([key]) => ["temperature", "humidity", "comfort", "air_quality", "mould_risk", "notices", "used_sensors"].includes(key)).map(([key, value]) => `${escape(key)}: ${escape(Array.isArray(value) ? value.join(", ") : value)}`).join("<br>") : t.unavailable;
    return `<button data-tab="overview">← ${t.overview}</button><h2>${escape(area.name)}</h2><ha-card class="section"><div class="card"><h3>Status</h3>${escape(area.active_states.join(", ") || t.unavailable)}<h3>Presence</h3>${area.presence.occupied ? t.occupied : t.clear}${list(area.presence.sources)}<h3>Brightness</h3>${escape(area.brightness?.state || t.unavailable)}<h3>Light groups</h3>${area.light_groups.map((group) => `${escape(group.name)}: ${group.on}/${group.total}`).join("<br>") || t.unavailable}<h3>Aggregates</h3>${aggregates || t.unavailable}<h3>Environment</h3>${environment}<h3>Sources</h3>${list(area.sources)}</div></ha-card>`;
  }

  _diagnosticsView() {
    const data = this._diagnosticsData;
    return `<div class="stats"><div><strong>${data.area_count}</strong>Areas</div><div><strong>${data.meta_area_count}</strong>Meta Areas</div><div><strong>${data.adaptive_entity_count}</strong>Entities</div><div><strong>${data.warning_count}</strong>Warnings</div></div>${data.issues.map((issue) => `<ha-alert alert-type="warning">${escape(issue.message)}</ha-alert>`).join("")}`;
  }
}
customElements.define("adaptive-areas-panel", AdaptiveAreasPanel);
