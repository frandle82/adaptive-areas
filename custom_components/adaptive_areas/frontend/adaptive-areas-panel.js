const TEXT = {
  en: { overview: "Overview", areas: "Areas", diagnostics: "Diagnostics", loading: "Loading…", empty: "No Adaptive Areas configured.", error: "Adaptive Areas could not be loaded.", liveError: "Live updates are unavailable.", diagnosticsError: "Diagnostics could not be loaded.", detailError: "Area details could not be loaded.", occupied: "Occupied", clear: "Clear", bright: "Bright", dark: "Dark", unavailable: "Unavailable", areaCount: "Areas", metaAreas: "Meta areas", lightsOn: "Lights on", warnings: "Warnings", light: "Light", of: "of", on: "on", status: "Status", presence: "Presence", brightness: "Brightness", lightGroups: "Light groups", environment: "Environment", aggregates: "Aggregates", technicalDetails: "Technical details", sources: "Sources", back: "Back to overview", selectArea: "Open area details", noIssues: "No current issues.", adaptiveEntities: "Adaptive entities", unavailableSources: "Unavailable sources", emptyAggregates: "Empty aggregates", diagnosticsUnavailable: "Some diagnostics are unavailable.", unavailableSource: "A source is unavailable.", emptyAggregate: "An aggregate has no sources.", brightnessStateInconsistent: "Brightness state is inconsistent." },
  de: { overview: "Übersicht", areas: "Bereiche", diagnostics: "Diagnose", loading: "Laden…", empty: "Noch keine Adaptive Areas konfiguriert.", error: "Adaptive Areas konnte nicht geladen werden.", liveError: "Live-Aktualisierung derzeit nicht verfügbar.", diagnosticsError: "Diagnose konnte nicht geladen werden.", detailError: "Area-Details konnten nicht geladen werden.", occupied: "Belegt", clear: "Frei", bright: "Hell", dark: "Dunkel", unavailable: "Nicht verfügbar", areaCount: "Bereiche", metaAreas: "Meta-Bereiche", lightsOn: "Lichter an", warnings: "Warnungen", light: "Licht", of: "von", on: "an", status: "Status", presence: "Präsenz", brightness: "Helligkeit", lightGroups: "Lichtgruppen", environment: "Raumklima", aggregates: "Aggregate", technicalDetails: "Technische Details", sources: "Quellen", back: "Zurück zur Übersicht", selectArea: "Area-Details öffnen", noIssues: "Keine aktuellen Hinweise.", adaptiveEntities: "Adaptive Entities", unavailableSources: "Nicht verfügbare Quellen", emptyAggregates: "Leere Aggregate", diagnosticsUnavailable: "Einige Diagnosedaten sind nicht verfügbar.", unavailableSource: "Eine Quelle ist nicht verfügbar.", emptyAggregate: "Ein Aggregat hat keine Quellen.", brightnessStateInconsistent: "Helligkeitszustand widersprüchlich." },
};

const escape = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);

class AdaptiveAreasPanel extends HTMLElement {
  set hass(hass) { this._hass = hass; if (!this._loaded) this._load(); }
  connectedCallback() { this._render(); }
  disconnectedCallback() { this._unsubscribe?.(); }
  get _text() { return TEXT[this._hass?.language?.startsWith("de") ? "de" : "en"]; }

  async _load() {
    this._loaded = true; this._render();
    try { this._overview = await this._hass.callWS({ type: "adaptive_areas/get_overview" }); }
    catch (error) { this._error = this._commandError("adaptive_areas/get_overview", error); this._render(); return; }
    try { this._unsubscribe = await this._hass.connection.subscribeMessage((event) => this._updateArea(event.area), { type: "adaptive_areas/subscribe_updates" }); }
    catch (error) { this._liveError = this._commandError("adaptive_areas/subscribe_updates", error); }
    this._render();
  }

  _commandError(command, error) { return { command, code: error?.code || "unknown_error" }; }
  _updateArea(area) { if (!this._overview) return; this._overview.areas = this._overview.areas.map((item) => item.id === area.id ? area : item); this._render(); }
  async _select(area) { this._detailError = null; try { this._selected = await this._hass.callWS({ type: "adaptive_areas/get_area", area_id: area.id }); } catch (error) { this._detailError = this._commandError("adaptive_areas/get_area", error); } this._tab = "areas"; this._render(); }
  async _diagnostics() { this._diagnosticsError = null; try { this._diagnosticsData ??= await this._hass.callWS({ type: "adaptive_areas/get_diagnostics" }); } catch (error) { this._diagnosticsError = this._commandError("adaptive_areas/get_diagnostics", error); } this._tab = "diagnostics"; this._render(); }
  _setTab(tab) { this._tab = tab; if (tab === "areas") this._selected = null; this._render(); }
  _renderError(label, detail) { return `<ha-alert alert-type="error">${label}<br><small>${escape(detail.command)} · ${escape(detail.code)}</small></ha-alert>`; }

  _render() {
    if (!this.isConnected) return;
    const t = this._text, tab = this._tab || "overview";
    const body = this._error ? this._renderError(t.error, this._error) : !this._overview ? `<div class="center"><ha-spinner></ha-spinner>${t.loading}</div>` : `${this._liveError ? this._renderError(t.liveError, this._liveError) : ""}${this._content(tab, t)}`;
    this.innerHTML = `<style>
      :host { display:block; max-width:1200px; margin:auto; padding:16px; color:var(--primary-text-color); } header, nav, .stats { display:flex; flex-wrap:wrap; gap:12px; } nav { margin:16px 0; } button { color:inherit; font:inherit; } nav button, .area-card, .area-row, .back { border:0; border-radius:8px; background:var(--secondary-background-color); padding:10px 14px; cursor:pointer; } button:focus-visible { outline:2px solid var(--primary-color); outline-offset:2px; } nav button.active { background:var(--primary-color); color:var(--text-primary-color); } .stats > div, .area-card, .area-row, .detail-section { border-radius:12px; background:var(--card-background-color); box-shadow:var(--ha-card-box-shadow, none); } .stats > div { min-width:110px; padding:14px; } .stats strong, .area-card strong, .area-row strong { display:block; font-size:1.1rem; } .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(340px, 1fr)); gap:12px; } .area-card, .area-row { text-align:left; } .area-card { display:grid; gap:10px; } .feature { border-top:1px solid var(--divider-color); padding-top:8px; } .feature span, .feature small, .coverage { display:block; color:var(--secondary-text-color); } .feature strong { margin-top:2px; } .area-row { display:grid; grid-template-columns:minmax(12rem, 1fr) repeat(4, minmax(6rem, auto)); gap:12px; align-items:center; width:100%; margin:8px 0; } .section { margin:16px 0; } .detail-section { padding:16px; margin:12px 0; } .meta, small { color:var(--secondary-text-color); } .warning { color:var(--warning-color, var(--error-color)); } .center { display:grid; place-items:center; min-height:160px; gap:12px; } .sources { overflow-wrap:anywhere; } details summary { cursor:pointer; } ha-icon { vertical-align:middle; margin-inline-end:6px; } @media (max-width:768px) { .grid { grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); } .area-row { grid-template-columns:1fr 1fr; } } @media (max-width:600px) { :host { padding:12px; } .grid { grid-template-columns:1fr; } .stats { display:grid; grid-template-columns:repeat(2, 1fr); } .area-row { grid-template-columns:1fr; gap:5px; } }
    </style><header><h1>Adaptive Areas</h1></header><nav aria-label="Adaptive Areas"><button class="${tab === "overview" ? "active" : ""}" aria-pressed="${tab === "overview"}" data-tab="overview">${t.overview}</button><button class="${tab === "areas" ? "active" : ""}" aria-pressed="${tab === "areas"}" data-tab="areas">${t.areas}</button><button class="${tab === "diagnostics" ? "active" : ""}" aria-pressed="${tab === "diagnostics"}" data-tab="diagnostics">${t.diagnostics}</button></nav>${body}`;
    this.querySelectorAll("[data-tab]").forEach((button) => button.onclick = () => button.dataset.tab === "diagnostics" ? this._diagnostics() : this._setTab(button.dataset.tab));
    this.querySelectorAll("[data-area]").forEach((button) => button.onclick = () => this._select(this._overview.areas.find((area) => area.id === button.dataset.area)));
    this.querySelectorAll("[data-back]").forEach((button) => button.onclick = () => this._setTab("overview"));
  }

  _content(tab, t) { if (tab === "diagnostics") return this._diagnosticsError ? this._renderError(t.diagnosticsError, this._diagnosticsError) : this._diagnosticsData ? this._diagnosticsView(t) : `<div class="center"><ha-spinner></ha-spinner></div>`; if (tab === "areas") return this._detailError ? this._renderError(t.detailError, this._detailError) : this._selected ? this._detailView(this._selected, t) : this._areasView(t); return this._overviewView(t); }
  _stats(items) { return `<div class="stats">${items.map(([value, label]) => `<div><strong>${escape(value)}</strong>${label}</div>`).join("")}</div>`; }
  _state(area, t) { return area.occupied ? t.occupied : t.clear; }
  _brightness(area, t) { const value = area.brightness; return value?.state ? `${t[value.state] || escape(value.state)}${value.illuminance !== null ? ` · ${escape(value.illuminance)} ${escape(value.unit || "")}` : ""}` : t.unavailable; }
  _lights(area, t) { return area.lights ? `${area.lights.on} ${t.of} ${area.lights.total} ${t.lightsOn.toLowerCase()}` : t.unavailable; }
  _warning(area, t) { return area.warning_count ? `<span class="warning"><ha-icon icon="mdi:alert"></ha-icon>${area.warning_count} ${t.warnings.toLowerCase()}</span>` : ""; }
  _environment(area) { const value = area.environment; if (!value) return ""; return [value.temperature && `${escape(value.temperature)} °C`, value.humidity && `${escape(value.humidity)} %`, value.comfort].filter(Boolean).join(" · "); }
  _cardBlocks(area, t) {
    const presence = area.presence ? `${area.presence.available} ${t.of} ${area.presence.total} ${t.sources.toLowerCase()}` : "";
    const groups = area.lights?.groups?.map((group) => `${escape(group.name)} ${group.on}/${group.total}`).join(" · ") || "";
    const coverage = area.sources?.total ? `${area.sources.available} ${t.of} ${area.sources.total} ${t.sources.toLowerCase()}` : "";
    return `${area.presence ? `<div class="feature"><span>${t.presence}</span><strong>${this._state(area, t)}</strong><small>${presence}</small></div>` : ""}${area.brightness ? `<div class="feature"><span>${t.brightness}</span><strong>${this._brightness(area, t)}</strong></div>` : ""}${area.lights ? `<div class="feature"><span>${t.light}</span><strong>${this._lights(area, t)}</strong><small>${groups}</small></div>` : ""}${this._environment(area) ? `<div class="feature"><span>${t.environment}</span><strong>${this._environment(area)}</strong></div>` : ""}${coverage ? `<small class="coverage"><ha-icon icon="mdi:access-point"></ha-icon>${coverage}</small>` : ""}`;
  }

  _overviewView(t) {
    const counts = this._overview.counts, warnings = this._overview.areas.reduce((total, area) => total + (area.warning_count || 0), 0);
    const stats = [[counts.areas, t.areaCount], [counts.occupied, t.occupied], [counts.dark, t.dark], [counts.lights_on, t.lightsOn], [warnings, t.warnings]];
    if (counts.meta_areas) stats.push([counts.meta_areas, t.metaAreas]);
    const cards = this._overview.areas.map((area) => `<button class="area-card" data-area="${escape(area.id)}" aria-label="${escape(`${t.selectArea}: ${area.name}`)}"><strong>${escape(area.name)}</strong><p class="meta">${area.type === "meta" ? t.metaAreas : ""}</p>${this._cardBlocks(area, t)}${this._warning(area, t)}</button>`).join("");
    return `${this._stats(stats)}${cards ? `<div class="grid section">${cards}</div>` : `<ha-alert>${t.empty}</ha-alert>`}`;
  }

  _areasView(t) {
    const rows = this._overview.areas.map((area) => `<button class="area-row" data-area="${escape(area.id)}" aria-label="${escape(`${t.selectArea}: ${area.name}`)}"><span><strong>${escape(area.name)}</strong><span class="meta">${area.type === "meta" ? t.metaAreas : ""}</span></span><span>${this._state(area, t)}</span><span>${this._brightness(area, t)}</span><span>${this._lights(area, t)}</span><span>${this._warning(area, t)}</span></button>`).join("");
    return rows ? `<div class="section">${rows}</div>` : `<ha-alert>${t.empty}</ha-alert>`;
  }

  _list(items, t) { return items?.length ? `<ul class="sources">${items.map((item) => `<li>${escape(item.name || item.entity_id)}: ${escape(item.state ?? t.unavailable)}</li>`).join("")}</ul>` : ""; }
  _section(title, content) { return content ? `<section class="detail-section"><h3>${title}</h3>${content}</section>` : ""; }
  _detailView(area, t) {
    const brightness = area.brightness ? this._brightness(area, t) : "", presence = area.presence?.sources?.length ? `${this._state(area, t)}${this._list(area.presence.sources, t)}` : "";
    const brightnessDetail = area.brightness_detail?.dark_source ? `${brightness}<br><span class="meta">${escape(area.brightness_detail.dark_source.name || area.brightness_detail.dark_source.entity_id)}: ${escape(area.brightness_detail.dark_source.state ?? t.unavailable)}</span>` : brightness;
    const lights = area.light_groups?.length ? area.light_groups.map((group) => `<div>${escape(group.name)}: ${group.on} ${t.of} ${group.total} ${t.on}</div>`).join("") : "";
    const environment = area.environment ? ["temperature", "humidity", "comfort", "air_quality", "mould_risk", "notices"].filter((key) => area.environment[key] !== undefined).map((key) => `${escape(key)}: ${escape(Array.isArray(area.environment[key]) ? area.environment[key].join(", ") : area.environment[key])}`).join("<br>") : "";
    const aggregates = area.aggregates?.length ? area.aggregates.map((item) => `<div>${escape(item.device_class || item.name)}: ${escape(item.state ?? t.unavailable)} ${escape(item.unit || "")} <span class="meta">(${item.available_count}/${item.source_count})</span></div>`).join("") : "", sources = this._list(area.sources, t);
    return `<button class="back" data-back><ha-icon icon="mdi:arrow-left"></ha-icon>${t.back}</button><h2>${escape(area.name)}</h2><p class="meta">${area.type === "meta" ? t.metaAreas : ""}</p>${this._section(t.status, `${this._state(area, t)}${brightness ? ` · ${brightness}` : ""}`)}${this._section(t.presence, presence)}${this._section(t.brightness, brightnessDetail)}${this._section(t.lightGroups, lights)}${this._section(t.environment, environment)}${this._section(t.aggregates, aggregates)}${sources ? `<details class="detail-section"><summary>${t.technicalDetails}</summary><h3>${t.sources}</h3>${sources}</details>` : ""}`;
  }
  _diagnosticsView(t) {
    const data = this._diagnosticsData, labels = { diagnostics_unavailable: t.diagnosticsUnavailable, unavailable_source: t.unavailableSource, empty_aggregate: t.emptyAggregate, brightness_state_inconsistent: t.brightnessStateInconsistent };
    const stats = [[data.area_count, t.areaCount], [data.meta_area_count, t.metaAreas], [data.adaptive_entity_count, t.adaptiveEntities], [data.warning_count, t.warnings], [data.unavailable_source_count, t.unavailableSources], [data.empty_aggregate_count, t.emptyAggregates]];
    const issues = data.issues.length ? data.issues.map((issue) => `<ha-alert alert-type="warning">${escape(labels[issue.code] || issue.message)}<br><small>${escape(issue.code)}</small></ha-alert>`).join("") : `<ha-alert alert-type="success">${t.noIssues}</ha-alert>`;
    return `${this._stats(stats)}<div class="section">${issues}</div>`;
  }
}
customElements.define("adaptive-areas-panel", AdaptiveAreasPanel);
