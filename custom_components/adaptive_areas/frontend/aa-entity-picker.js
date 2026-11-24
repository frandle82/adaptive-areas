/*
 * <aa-entity-picker>: the one entity selection component of the Adaptive Areas panel.
 *
 * Attributes
 *   name            form field name
 *   multiple        several entities; otherwise a single entity
 *   label           accessible name of the search field
 *   domain          comma list of allowed entity domains (optional)
 *   device-class    allowed device class; "illuminance" also accepts unit "lx"
 *   scope           Area ID: only entities registered to this Area are offered
 *   disabled        read-only while the panel saves
 *
 * Values are kept as hidden <input name="..."> children in the light DOM, so the
 * surrounding <form> reads them like any other field and `input`/`change` events
 * bubble to the panel. Selected entities are always shown, even when they do not
 * match the current filters. Nothing changes unless the user acts.
 *
 * Texts come from the panel (`closest("adaptive-areas-panel")._t`); English
 * fallbacks are kept here. Entities come from the panel's `_hass`.
 */

const MAX_OPTIONS = 200;
const FALLBACK = {
  pickerSearch: "Search entities",
  pickerNone: "No entity selected",
  pickerCount: "{n} selected",
  pickerRemove: "Remove {entity}",
  pickerNoMatches: "No matching entities",
  pickerNotFound: "Not found in Home Assistant",
  pickerLimit: "Showing the first {n} matches. Refine the search.",
  pickerStatusAdded: "{entity} added",
  pickerStatusRemoved: "{entity} removed",
};

const STYLE = `
:host { display: block; width: 100%; min-width: 0; max-width: 100%; }
* { box-sizing: border-box; }
.box { min-width: 0; border: 1px solid var(--divider-color, #c8c8c8); border-radius: 8px; padding: 8px; background: var(--card-background-color, #fff); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.chips:empty { display: none; }
.chip { display: inline-flex; align-items: center; gap: 2px; min-width: 0; max-width: 100%; padding: 2px 2px 2px 10px; border-radius: 999px; background: var(--secondary-background-color, #eee); font-size: 0.9em; }
.chip-text { min-width: 0; overflow-wrap: anywhere; }
.chip.missing .chip-text { font-style: italic; color: var(--error-color, #b00020); }
button { font: inherit; color: inherit; background: transparent; border: 0; cursor: pointer; }
.remove { flex: none; min-width: 32px; min-height: 32px; border-radius: 50%; }
.remove:hover { background: rgba(127, 127, 127, 0.2); }
input[type="search"] { width: 100%; min-height: 40px; padding: 8px 10px; border: 1px solid var(--divider-color, #c8c8c8); border-radius: 6px; background: transparent; color: inherit; font: inherit; }
button:focus-visible, input:focus-visible, [role="option"]:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
.meta { margin: 6px 0 0; font-size: 0.85em; color: var(--secondary-text-color, #666); }
.list { margin-top: 6px; max-height: 240px; overflow: auto; border: 1px solid var(--divider-color, #c8c8c8); border-radius: 6px; }
.list[hidden] { display: none; }
[role="option"] { display: flex; align-items: center; gap: 8px; min-width: 0; min-height: 40px; padding: 6px 10px; cursor: pointer; }
[role="option"][aria-selected="true"] { background: rgba(3, 169, 244, 0.14); }
[role="option"][data-blocked="true"] { opacity: 0.65; cursor: not-allowed; }
.option-blocked { display: block; font-size: 0.85em; color: var(--error-color, #b00020); }
[role="option"][data-active="true"] { box-shadow: inset 3px 0 0 var(--primary-color, #03a9f4); }
.mark { flex: none; width: 18px; text-align: center; }
.option-text { min-width: 0; display: flex; flex-direction: column; }
.option-name { overflow-wrap: anywhere; }
.option-id { font-size: 0.85em; color: var(--secondary-text-color, #666); overflow-wrap: anywhere; }
.empty { padding: 10px; color: var(--secondary-text-color, #666); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
:host([disabled]) .box { opacity: 0.6; pointer-events: none; }
`;

const text = (t, key, values = {}) => {
  let value = t?.[key] || FALLBACK[key] || key;
  for (const [name, replacement] of Object.entries(values)) {
    value = value.replace(`{${name}}`, String(replacement));
  }
  return value;
};

const commaList = (value) =>
  String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

class AaEntityPicker extends HTMLElement {
  static get observedAttributes() {
    return ["disabled", "domain", "device-class", "scope", "multiple", "label"];
  }

  constructor() {
    super();
    this._query = "";
    this._open = false;
    this._active = 0;
    this._options = [];
    this._uid = Math.random().toString(36).slice(2, 8);
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <div class="box">
        <div class="chips"></div>
        <input type="search" autocomplete="off" spellcheck="false" role="combobox"
          aria-autocomplete="list" aria-expanded="false" aria-haspopup="listbox">
        <p class="meta" aria-live="polite"></p>
        <p class="sr-only" role="status" aria-live="polite"></p>
        <div class="list" role="listbox" hidden></div>
      </div>`;
    this._input = this.shadowRoot.querySelector("input");
    this._list = this.shadowRoot.querySelector(".list");
    this._list.id = `list-${this._uid}`;
    this._input.setAttribute("aria-controls", this._list.id);
    this._input.addEventListener("input", () => {
      this._query = this._input.value;
      this._active = 0;
      this._open = true;
      this._render();
    });
    this._input.addEventListener("focus", () => {
      this._open = true;
      this._render();
    });
    this._input.addEventListener("blur", () => {
      // Close when focus leaves the component; chips and options stay inside it.
      setTimeout(() => {
        if (!this.shadowRoot.activeElement) {
          this._open = false;
          this._render();
        }
      }, 0);
    });
    this._input.addEventListener("keydown", (event) => this._onKey(event));
    this._list.addEventListener("mousedown", (event) => {
      // Keep focus in the search field while an option is clicked.
      event.preventDefault();
    });
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    this._render();
  }

  get multiple() {
    return this.hasAttribute("multiple");
  }

  get name() {
    return this.getAttribute("name") || "";
  }

  get selected() {
    return [...this.querySelectorAll(`input[type="hidden"][name="${this.name}"]`)]
      .map((input) => input.value)
      .filter(Boolean);
  }

  /** Single value for single pickers (what the panel's draft handling reads). */
  get value() {
    return this.multiple ? this.selected : this.selected[0] || "";
  }

  set value(next) {
    this._setSelected(Array.isArray(next) ? next.filter(Boolean) : next ? [next] : []);
  }

  /** Candidates after all filters, for read-only inspection (not capped). */
  get options() {
    return this._filtered().map((entityId) => ({
      value: entityId,
      label: this._entityLabel(entityId),
      textContent: this._described(entityId),
      selected: this.selected.includes(entityId),
    }));
  }

  focus(options) {
    this._input.focus(options);
  }

  /** Mark for a stored value that is missing, outside the Area or unavailable. */
  _mark(entityId) {
    const t = this._panel()?._t || {};
    const state = this._panel()?._hass?.states?.[entityId];
    const scope = this.getAttribute("scope");
    let key = null;
    if (!state) key = "fxMarkNotFound";
    else if (scope && this._registryKnown() && this._panel()?._entityArea?.(entityId) !== scope) key = "fxOutOfScope";
    else if (state.state === "unavailable") key = "fxMarkUnavailable";
    return key && t[key] ? t[key].replace("{entity}", this._entityLabel(entityId)) : null;
  }

  _described(entityId) {
    return this._mark(entityId) || this._entityLabel(entityId);
  }

  _panel() {
    return this.closest("adaptive-areas-panel");
  }

  _entityLabel(entityId) {
    const state = this._panel()?._hass?.states?.[entityId];
    return state?.attributes?.friendly_name || entityId;
  }

  _registryKnown() {
    return this._panel()?._hass?.entities !== undefined;
  }

  _matchesFilters(entityId) {
    const panel = this._panel();
    const state = panel?._hass?.states?.[entityId];
    const domains = commaList(this.getAttribute("domain"));
    if (domains.length && !domains.includes(entityId.split(".")[0])) return false;
    const deviceClass = this.getAttribute("device-class");
    if (deviceClass) {
      const attributes = state?.attributes || {};
      const accepted =
        deviceClass === "illuminance"
          ? attributes.device_class === "illuminance" || attributes.unit_of_measurement === "lx"
          : attributes.device_class === deviceClass;
      if (!accepted) return false;
    }
    const scope = this.getAttribute("scope");
    if (scope && this._registryKnown() && panel?._entityArea?.(entityId) !== scope) return false;
    return true;
  }

  _filtered() {
    const query = this._query.trim().toLocaleLowerCase();
    const states = this._panel()?._hass?.states || {};
    const stored = this.selected;
    // Stored values stay offered (and marked) even when they no longer match the filters.
    const known = [...new Set([...Object.keys(states), ...stored])];
    return known
      .filter((id) => this._matchesFilters(id) || stored.includes(id))
      .filter((id) => {
        if (!query) return true;
        const name = String(states[id]?.attributes?.friendly_name || "");
        return id.toLocaleLowerCase().includes(query) || name.toLocaleLowerCase().includes(query);
      })
      .sort((a, b) => a.localeCompare(b));
  }

  _setSelected(ids, announcement = null) {
    this.querySelectorAll(`input[type="hidden"][name="${this.name}"]`).forEach((input) => input.remove());
    // A cleared single selection keeps its empty field, so the draft sees the change.
    const values = !this.multiple && ids.length === 0 ? [""] : ids;
    for (const id of values) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = this.name;
      input.value = id;
      this.appendChild(input);
    }
    if (announcement) this.shadowRoot.querySelector(".sr-only").textContent = announcement;
    this.dispatchEvent(new Event("input", { bubbles: true }));
    this.dispatchEvent(new Event("change", { bubbles: true }));
    this._render();
  }

  /** Owner text when the candidate belongs to another individual group (else null). */
  _blockedBy(entityId) {
    const panel = this._panel();
    return typeof panel?._lightGroupBlockedBy === "function"
      ? panel._lightGroupBlockedBy(this, entityId)
      : null;
  }

  _toggle(entityId) {
    if (this._blockedBy(entityId)) return;
    const t = this._panel()?._t || {};
    const label = this._entityLabel(entityId);
    const current = this.selected;
    if (!this.multiple) {
      this._open = false;
      this._setSelected([entityId], text(t, "pickerStatusAdded", { entity: label }));
      this._input.focus();
      return;
    }
    const added = !current.includes(entityId);
    const next = added ? [...current, entityId] : current.filter((id) => id !== entityId);
    this._setSelected(next, text(t, added ? "pickerStatusAdded" : "pickerStatusRemoved", { entity: label }));
  }

  _remove(entityId) {
    const t = this._panel()?._t || {};
    const label = this._entityLabel(entityId);
    this._setSelected(this.selected.filter((id) => id !== entityId), text(t, "pickerStatusRemoved", { entity: label }));
    this._input.focus();
  }

  _onKey(event) {
    const options = this._options;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      this._open = true;
      if (options.length) {
        const step = event.key === "ArrowDown" ? 1 : -1;
        this._active = (this._active + step + options.length) % options.length;
      }
      this._render();
    } else if (event.key === "Enter") {
      // Enter selects inside the component; it must never submit the form.
      event.preventDefault();
      if (this._open && options[this._active]) this._toggle(options[this._active]);
    } else if (event.key === "Escape") {
      if (this._open) {
        event.preventDefault();
        event.stopPropagation();
        this._open = false;
        this._render();
      }
    } else if (event.key === "Tab") {
      this._open = false;
      this._render();
    }
  }

  _render() {
    if (!this.shadowRoot) return;
    const t = this._panel()?._t || {};
    const selected = this.selected;
    const disabled = this.hasAttribute("disabled");
    this.shadowRoot.querySelector(".chips").replaceChildren(
      ...selected.map((id) => {
        const known = Boolean(this._panel()?._hass?.states?.[id]);
        const chip = document.createElement("span");
        chip.className = known ? "chip" : "chip missing";
        const label = document.createElement("span");
        label.className = "chip-text";
        label.textContent = this._described(id);
        label.title = known ? id : `${id} · ${text(t, "pickerNotFound")}`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove";
        remove.textContent = "×";
        remove.disabled = disabled;
        const removeLabel = text(t, "pickerRemove", { entity: this._entityLabel(id) });
        remove.setAttribute("aria-label", removeLabel);
        remove.title = removeLabel;
        remove.addEventListener("click", () => this._remove(id));
        chip.append(label, remove);
        return chip;
      })
    );

    const placeholder = text(t, "pickerSearch");
    this._input.placeholder = placeholder;
    this._input.disabled = disabled;
    this._input.setAttribute("aria-label", this.getAttribute("label") || placeholder);
    this._input.setAttribute("aria-expanded", String(this._open));
    const candidates = this._filtered();
    this._options = candidates.slice(0, MAX_OPTIONS);
    if (this._active >= this._options.length) this._active = 0;

    const countText = this.multiple
      ? text(t, "pickerCount", { n: selected.length })
      : selected.length
      ? ""
      : text(t, "pickerNone");
    this.shadowRoot.querySelector(".meta").textContent =
      candidates.length > MAX_OPTIONS
        ? `${countText} ${text(t, "pickerLimit", { n: MAX_OPTIONS })}`.trim()
        : countText;

    this._list.hidden = !this._open;
    this._list.setAttribute("aria-multiselectable", String(this.multiple));
    this._list.replaceChildren();
    this._input.removeAttribute("aria-activedescendant");
    if (!this._open) return;
    if (!this._options.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = text(t, "pickerNoMatches");
      this._list.append(empty);
      return;
    }
    this._options.forEach((entityId, index) => {
      const isSelected = selected.includes(entityId);
      const option = document.createElement("div");
      option.id = `opt-${this._uid}-${index}`;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(isSelected));
      option.dataset.active = String(index === this._active);
      option.tabIndex = -1;
      const mark = document.createElement("span");
      mark.className = "mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = isSelected ? "✓" : "";
      const textBox = document.createElement("span");
      textBox.className = "option-text";
      const name = document.createElement("span");
      name.className = "option-name";
      name.textContent = this._entityLabel(entityId);
      const id = document.createElement("span");
      id.className = "option-id";
      id.textContent = entityId;
      textBox.append(name, id);
      option.append(mark, textBox);
      const blocked = this._blockedBy(entityId);
      if (blocked) {
        option.dataset.blocked = "true";
        option.setAttribute("aria-disabled", "true");
        const owner = document.createElement("span");
        owner.className = "option-blocked";
        owner.textContent = blocked;
        textBox.append(owner);
      }
      option.addEventListener("click", () => this._toggle(entityId));
      this._list.append(option);
      if (index === this._active) this._input.setAttribute("aria-activedescendant", option.id);
    });
  }
}

if (!customElements.get("aa-entity-picker")) {
  customElements.define("aa-entity-picker", AaEntityPicker);
}
