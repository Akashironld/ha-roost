/* Roost card - served by the roost integration. */
(() => {   // own scope: safe if the file is loaded twice as a classic script (legacy frontend + a manual resource)
const CARD_VERSION = "0.5.5";

// Plain ES2017 on purpose (no ?. / ??), ASCII only (\u escapes): wall tablets often run an older browser.
const nn = (a, b) => (a === null || a === undefined ? b : a);
const DEG = "\u00b0C";

const T = {
  en: { title: "Roost", room: "Room", thermostat: "Thermostat", planned: "Planned", next24: "Next 24 hours",
        setpoint: "setpoint", expected: "room expected", price: "tariff", guessed: "estimated", uses: "plan uses", comfort: "comfort hours", now: "now",
        night: "night", saving24: "expected saving", month: "this month", yesterday: "yesterday", vs: "vs steady", accuracy: "plan error 6 h", ready: "ready to steer", min: "min", steer: "Let Roost steer", sure: "Sure? Click again", importing: "Weheat import", months: "months", done_at: "done", eta: { import: "after the import", heating: "after more heating hours", heating_season: "in the heating season", check: "maybe at the next check", lever: "not yet (setpoint has no effect)", following: "not yet (heat pump not following)" },
        active: "ACTIVE", shadow: "SHADOW", off: "OFF", paused: "PAUSED", scrub: "slide over the graph",
        stored: "stored", unavailable: "Not available", pick: "Pick the 'Planned setpoint' sensor of the Roost integration.",
        noplan: "no plan yet", heating: "heat pump heating", e_entity: "Sensor", e_title: "Title", e_language: "Language",
        e_time_format: "Time format", e_auto: "Like Home Assistant", e_show_tiles: "Tiles", e_show_chart: "24-hour plan",
        e_show_footer: "Saving", e_compact: "Compact (e.g. a wall tablet)", e_history: "Look back (button)", e_view: "Opens in",
        v_plan: "Ahead (plan)", v_history: "Look back",
        ahead: "Ahead", back: "Look back", h_cost: "Cost", h_saving: "saving", h_pred: "Forecast 6 h", h_largest: "largest",
        h_below: "Below comfort", h_lowest: "lowest", h_changes: "Changes", h_byhand: "by hand", h_byroost: "Roost",
        h_log: "Log", h_report: "Report", h_loading: "Loading the last days\u2026",
        h_nodata: "No history yet: Roost keeps every hour from now on.", h_sp_t: "thermostat setpoint", h_sp_p: "planned",
        h_room: "room measured", h_pred6: "room predicted 6 h before", h_heat: "heat kWh", h_pause: "pause",
        h_expected: "expected", h_dev: "deviation", h_room_after: "room", h_set_hand: "by hand, Roost pauses {h} h",
        h_pause_ev: "paused {h} h", h_resume: "resumed", h_mode: "mode", h_learned: "learned the house again",
        h_window: "window open", h_window_end: "window closed, room back", h_win_mark: "W", h_period: "Period", h_day: "Day", h_kwh: "kWh", h_cop: "COP", h_deficit: "\u00b0C\u00b7h below" },
  nl: { title: "Roost", room: "Kamer", thermostat: "Thermostaat", planned: "Gepland", next24: "Komende 24 uur",
        setpoint: "setpoint", expected: "kamer verwacht", price: "tarief", guessed: "geschat", uses: "rekent met", comfort: "comforturen", now: "nu",
        night: "nacht", saving24: "verwachte besparing", month: "deze maand", yesterday: "gisteren", vs: "t.o.v. vast", accuracy: "planfout 6 u", ready: "klaar om te sturen", min: "min", steer: "Laat Roost sturen", sure: "Zeker? Klik nogmaals", importing: "Weheat-import", months: "maanden", done_at: "klaar", eta: { import: "na de import", heating: "na meer stookuren", heating_season: "in het stookseizoen", check: "mogelijk bij de volgende controle", lever: "nog niet (setpoint werkt niet)", following: "nog niet (warmtepomp volgt niet)" },
        active: "ACTIEF", shadow: "MEEKIJKEN", off: "UIT", paused: "GEPAUZEERD", scrub: "schuif over de grafiek",
        stored: "opgeslagen", unavailable: "Niet beschikbaar", pick: "Kies de sensor 'Gepland setpoint' van de integratie Roost.",
        noplan: "nog geen plan", heating: "warmtepomp stookt", e_entity: "Sensor", e_title: "Titel", e_language: "Taal",
        e_time_format: "Tijdnotatie", e_auto: "Zoals Home Assistant", e_show_tiles: "Tegels", e_show_chart: "24-uursplan",
        e_show_footer: "Besparing", e_compact: "Compact (bijv. een wandtablet)", e_history: "Terugblik (knop)", e_view: "Opent in",
        v_plan: "Vooruit (plan)", v_history: "Terugblik",
        ahead: "Vooruit", back: "Terugblik", h_cost: "Kosten", h_saving: "besparing", h_pred: "Voorspelling 6 u", h_largest: "grootst",
        h_below: "Onder comfort", h_lowest: "laagst", h_changes: "Wijzigingen", h_byhand: "met de hand", h_byroost: "Roost",
        h_log: "Logboek", h_report: "Rapport", h_loading: "De laatste dagen laden\u2026",
        h_nodata: "Nog geen geschiedenis: Roost bewaart vanaf nu elk uur.", h_sp_t: "setpoint thermostaat", h_sp_p: "gepland",
        h_room: "kamer gemeten", h_pred6: "kamer voorspeld 6 u eerder", h_heat: "warmte kWh", h_pause: "pauze",
        h_expected: "verw.", h_dev: "afwijking", h_room_after: "kamer", h_set_hand: "met de hand, Roost pauzeert {h} u",
        h_pause_ev: "gepauzeerd {h} u", h_resume: "hervat", h_mode: "modus", h_learned: "huis opnieuw geleerd",
        h_window: "raam open", h_window_end: "raam dicht, kamer terug", h_win_mark: "R", h_period: "Periode", h_day: "Dag", h_kwh: "kWh", h_cop: "COP", h_deficit: "\u00b0C\u00b7u onder" },
};

// Why Roost plans or does something: the integration sends a code with values (reason_code/_args,
// decision_code/_args); the card words it. Unknown codes fall back to the English text of the integration.
const WHY = {
  en: { starting: "starting", window_open: "window open: Roost waits until the room is back", no_price: "no price", no_room: "no room temperature",
        no_weather: "no weather forecast and no outdoor temperature", no_plan: "no plan", off: "Roost is off",
        store_solar: "charging the floor on own solar (up to {sp} \u00b0C)",
        store_cheap: "charging the floor now ({ct} ct) before more expensive hours",
        expensive: "expensive hour ({ct} ct): living off the heat in the floor",
        store_solar_house: "storing heat in the house on own solar (up to {sp} \u00b0C)",
        store_cheap_house: "storing heat in the house now ({ct} ct) before more expensive hours",
        expensive_house: "expensive hour ({ct} ct): living off the heat in the house",
        warm_enough: "warm enough ({room} \u00b0C): no heat needed", holding: "keeping the room at temperature",
        paused: "changed by hand: leaving the thermostat alone for {min} more min",
        already_right: "thermostat already right", wait: "next change allowed in {min} min",
        urgent: "room below the minimum: correcting now", following: "following the plan" },
  nl: { starting: "opstarten", window_open: "raam open: Roost wacht tot de kamer terug is", no_price: "geen prijs", no_room: "geen kamertemperatuur",
        no_weather: "geen weersverwachting en geen buitentemperatuur", no_plan: "geen plan", off: "Roost staat uit",
        store_solar: "vloer opladen met eigen zonnestroom (tot {sp} \u00b0C)",
        store_cheap: "vloer opladen ({ct} ct), straks wordt het duurder",
        expensive: "duur uur ({ct} ct): teert op de vloerbuffer",
        store_solar_house: "warmte opslaan in het huis met eigen zonnestroom (tot {sp} \u00b0C)",
        store_cheap_house: "warmte opslaan in het huis ({ct} ct), straks wordt het duurder",
        expensive_house: "duur uur ({ct} ct): teert op de warmte in het huis",
        warm_enough: "warm genoeg ({room} \u00b0C): geen warmte nodig", holding: "kamer op temperatuur houden",
        paused: "met de hand gewijzigd: thermostaat nog {min} min met rust gelaten",
        already_right: "thermostaat staat al goed", wait: "volgende wijziging over {min} min",
        urgent: "kamer onder het minimum: nu bijsturen", following: "volgt het plan" },
};
const WHY_DECIMALS = { sp: 1, room: 1, ct: 0, min: 0 };

// Parts of the card that can be hidden with show_<part>: false. "compact: true" hides the chart and the saving and
// keeps the header and the tiles; a show_<part> set explicitly always wins (e.g. compact with show_chart: true).
const PARTS = ["tiles", "chart", "footer"];
const COMPACT_HIDES = ["chart", "footer"];
const showDefault = (config, part) => !(config && config.compact && COMPACT_HIDES.indexOf(part) >= 0);
const shows = (config, part) => {
  const v = config ? config["show_" + part] : undefined;
  return v === undefined || v === null ? showDefault(config, part) : !!v;
};
const lang2 = (hass) => ((hass && ((hass.locale && hass.locale.language) || hass.language)) || "en").slice(0, 2);
const fmt = (v, d) => (v === null || v === undefined || isNaN(v)) ? "\u2014" : Number(v).toFixed(d === undefined ? 0 : d);

class RoostCard extends HTMLElement {
  static getConfigElement() { return document.createElement("roost-card-editor"); }

  static getStubConfig(hass) {
    const ent = Object.keys(hass.states).find((e) => e.startsWith("sensor.") && hass.states[e].attributes &&
      hass.states[e].attributes.plan !== undefined && hass.states[e].attributes.store_max !== undefined);
    return { entity: ent || "" };
  }

  setConfig(config) {
    if (!config.entity) throw new Error("entity is required (the 'Planned setpoint' sensor)");
    this._config = Object.assign({}, config);
    if (this._view === undefined) this._view = config.view === "history" ? "history" : "plan";
    if (this._range === undefined) this._range = 24;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = this._config && hass.states[this._config.entity];
    const sib = this._siblings();
    const parts = [st ? st.last_updated : "none", hass.locale && hass.locale.language];
    Object.keys(sib).forEach((k) => { const s = hass.states[sib[k]]; parts.push(s ? s.state : ""); });
    const key = parts.join("|");
    if (key !== this._key) { this._key = key; this._render(); }
  }

  getCardSize() { return 2 + (this._show("tiles") ? 1 : 0) + (this._show("chart") ? 3 : 0); }
  getGridOptions() { return { columns: 12, min_columns: 6 }; }

  _show(part) { return shows(this._config, part); }
  _lang() { const own = this._config && this._config.language; return own && T[own] ? own : lang2(this._hass); }
  _t(k) { return (T[this._lang()] || T.en)[k]; }
  _why(code, args, text) {
    const tpl = code && ((WHY[this._lang()] || WHY.en)[code] || WHY.en[code]);
    if (!tpl) return text || "";
    return tpl.replace(/\{(\w+)\}/g, (m, k) => (args && args[k] !== undefined ? this._num(args[k], nn(WHY_DECIMALS[k], 1)) : m));
  }
  _locale() {
    const user = (this._hass && ((this._hass.locale && this._hass.locale.language) || this._hass.language)) || undefined;
    const own = this._config && this._config.language;
    if (own && T[own]) return user && user.slice(0, 2) === own ? user : own;
    return user;
  }
  _hour(date) {
    const opts = { hour: "2-digit", minute: "2-digit" };
    const own = this._config && this._config.time_format;
    const profile = this._hass && this._hass.locale && this._hass.locale.time_format;
    const choice = own === "24" || own === "12" ? own : profile;
    if (choice === "24") opts.hour12 = false;
    if (choice === "12") opts.hour12 = true;
    return date.toLocaleTimeString(choice === "system" ? undefined : this._locale(), opts);
  }
  _num(v, d) { return v === null || v === undefined || isNaN(v) ? "\u2014" : Number(v).toLocaleString(this._locale(), { minimumFractionDigits: d, maximumFractionDigits: d }); }
  _money(v) {
    if (v === null || v === undefined || isNaN(v)) return "\u2014";
    const cur = (this._hass && this._hass.config && this._hass.config.currency) || "EUR";
    try { return Number(v).toLocaleString(this._locale(), { style: "currency", currency: cur }); } catch (e) { return fmt(v, 2); }
  }

  // The other Roost entities of the same entry, found through the entity registry by their translation key.
  _siblings() {
    const hass = this._hass, out = {};
    if (!hass || !hass.entities || !this._config) return out;
    const me = hass.entities[this._config.entity];
    if (!me || !me.device_id) return out;
    Object.keys(hass.entities).forEach((eid) => {
      const e = hass.entities[eid];
      if (e.device_id === me.device_id && e.platform === "roost" && e.translation_key) out[e.translation_key] = eid;
    });
    return out;
  }
  _hm(d) {   // a time, with the weekday when it is not today
    return (d.toDateString() === new Date().toDateString() ? "" : d.toLocaleDateString(this._lang(), { weekday: "short" }) + " ") +
      d.toLocaleTimeString(this._lang(), { hour: "2-digit", minute: "2-digit" });
  }
  _sib(key) { const s = this._siblings(); const st = s[key] && this._hass.states[s[key]]; return st ? st : null; }

  _shell() {
    if (this._card && this._card.parentNode === this.shadowRoot) return this._card;
    this.shadowRoot.innerHTML = `${this._style()}<ha-card></ha-card>`;
    this._card = this.shadowRoot.querySelector("ha-card");
    this._card.addEventListener("click", (ev) => {
      if (!this._clickable || (ev.target && ev.target.closest && ev.target.closest(".chart, .seg, .hlog, .rep, button"))) return;
      const e = new Event("hass-more-info", { bubbles: true, composed: true });
      e.detail = { entityId: this._config.entity };
      this.dispatchEvent(e);
    });
    return this._card;
  }

  _render() {
    if (!this.shadowRoot || !this._config || !this._hass) return;
    const st = this._hass.states[this._config.entity];
    if (!st || st.state === "unavailable" || st.state === "unknown") {
      this._clickable = false;
      this._shell().innerHTML = `<div class="na">${st ? this._t("unavailable") : this._t("pick")}</div>`;
      return;
    }
    const a = st.attributes;
    const mode = a.mode || "shadow";
    const paused = a.paused_until && new Date(a.paused_until) > new Date();
    const pill = paused ? `<span class="pill warn">${this._t("paused")}</span>`
      : `<span class="pill ${mode}">${this._t(mode)}</span>`;
    const title = this._config.title || this._t("title");
    const reason = this._why(a.reason_code, a.reason_args, a.reason) || this._t("noplan");
    const decision = this._why(a.decision_code, a.decision_args, a.decision);
    // the planned setpoint is a thermostat setting (a lever: a slow unit may be set well below the room), so show
    // where the room is expected to go with it
    const p0 = a.plan && a.plan.length ? a.plan[0] : null;
    const expect = p0 ? `${this._t("expected")} ${this._num(p0[1], 1)} ${DEG}` : reason;
    const hist = this._histOn();
    const seg = hist ? `<div class="seg"><span data-v="plan" class="${this._view === "plan" ? "on" : ""}">${this._t("ahead")}</span>` +
      `<span data-v="history" class="${this._view === "history" ? "on" : ""}">${this._t("back")}</span></div>` : "";
    let html = `<div class="head"><div class="ico"><ha-icon icon="mdi:bird"></ha-icon></div>
      <div class="ht"><div class="tt">${title}</div><div class="sub">${reason}</div></div>${seg}${pill}</div>`;
    if (hist && this._view === "history") {
      html += this._histBody();
      if (this._show("footer")) html += this._footer(a);
      this._clickable = true;
      this._shell().innerHTML = html;
      this._wire();
      return;
    }
    if (this._show("tiles")) {
      html += `<div class="tiles">
        ${this._tile("mdi:home-thermometer-outline", this._t("room"), a.room, true, `${this._t("stored")} ${fmt(a.storage_kwh, 1)} kWh`)}
        ${this._tile("mdi:thermostat", this._t("thermostat"), a.thermostat, false, decision)}
        ${this._tile("mdi:bird", this._t("planned"), parseFloat(st.state), false, expect, "plan")}
      </div>`;
    }
    if (a.rooms && a.rooms.length) html += this._rooms(a.rooms);
    // ready (nightly self-check) and still in shadow: one button to let Roost steer, clicked twice
    const ready = this._sib("ready");
    if (ready && ready.state === "on" && mode === "shadow" && this._siblings().mode) {
      html += `<button class="steer">${this._t("steer")}</button>`;
    }
    if (this._show("chart") && a.plan && a.plan.length) html += this._chart(a);
    if (this._show("footer")) html += this._footer(a);
    this._clickable = true;
    this._shell().innerHTML = html;
    this._wire();
  }

  // Extra rooms (radiators upstairs, a bedroom): temperature, minimum and its hours; orange when below it in its hours
  _rooms(list) {
    const chips = list.map((r) => {
      const cold = r.active_now && r.temperature < r.minimum;
      return `<span class="room${cold ? " cold" : ""}" title="${r.from}:00\u2013${r.to}:00"><b>${r.name}</b> ${this._num(r.temperature, 1)}${DEG}` +
        ` \u00b7 ${this._t("min")} ${this._num(r.minimum, 1)} <i>(${r.from}\u2013${r.to})</i></span>`;
    });
    return `<div class="rooms">${chips.join("")}</div>`;
  }

  _tile(icon, label, v, big, sub, cls) {
    return `<div class="tile ${cls || ""}"><div class="tl"><ha-icon icon="${icon}"></ha-icon>${label}</div>
      <div class="tv${big ? " big" : ""}">${this._num(v, 1)}<span>${DEG}</span></div><div class="ts">${sub}</div></div>`;
  }

  _chart(a) {
    const plan = a.plan, n = plan.length;
    // bars: the import tariff (p[4]; older versions only had the planner's price p[3]); p[5] = 1: not known yet, guessed
    const sp = plan.map((p) => p[0]), kt = plan.map((p) => p[1]), pr = plan.map((p) => nn(p[4], p[3]));
    const guess = plan.map((p) => !!p[5]);
    const day = a.day_hours || plan.map(() => 1);
    const start = a.start ? new Date(a.start) : new Date();
    const VW = 440, VH = 172, L = 28, R = 6, TOP = 8, B = 46, PB = 26, w = (VW - L - R) / n;
    const vals = sp.concat(kt).filter((v) => !isNaN(v));
    const lo = Math.min(nn(a.night_min, 19) - 0.5, Math.floor(Math.min.apply(null, vals) - 0.3));
    const hi = Math.max(nn(a.store_max, 22.5) + 0.3, Math.ceil(Math.max.apply(null, vals) + 0.3));
    const y = (v) => TOP + (hi - v) / (hi - lo) * (VH - TOP - B), x = (i) => L + i * w;
    const pmin = Math.min.apply(null, pr), pmax = Math.max.apply(null, pr), pb = VH - 18;
    const tone = (p) => { const r = (p - pmin) / Math.max(0.01, pmax - pmin); return r < 0.33 ? "var(--rc-cheap)" : (r < 0.66 ? "var(--rc-mid)" : "var(--rc-dear)"); };
    let g = "";
    const cl = nn(a.day_min, 20), ch = nn(a.comfort, 20.5);
    for (let i = 0; i < n; i++) if (day[i]) g += `<rect x="${x(i).toFixed(1)}" y="${y(ch).toFixed(1)}" width="${(w + 0.2).toFixed(1)}" height="${Math.max(1, y(cl) - y(ch)).toFixed(1)}" class="band"/>`;
    for (let v = Math.ceil(lo); v <= hi; v++) {
      g += `<line x1="${L}" x2="${VW - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="grid"/>` +
        `<text x="${L - 5}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end" class="axis">${v}\u00b0</text>`;
    }
    pr.forEach((p, i) => {
      const r = (p - pmin) / Math.max(0.01, pmax - pmin), hgt = 4 + r * (PB - 8);
      g += `<rect x="${(x(i) + 1).toFixed(1)}" y="${(pb - hgt).toFixed(1)}" width="${(w - 2).toFixed(1)}" height="${hgt.toFixed(1)}" rx="1.5" style="fill:${tone(p)}" class="price${guess[i] ? " guess" : ""}"/>`;
    });
    let d = `M${x(0).toFixed(1)} ${y(sp[0]).toFixed(1)}`;
    sp.forEach((v, i) => { d += ` L${x(i).toFixed(1)} ${y(v).toFixed(1)} L${x(i + 1).toFixed(1)} ${y(v).toFixed(1)}`; });
    let k = "";
    kt.forEach((v, i) => { k += `${i ? " L" : "M"}${(x(i) + w / 2).toFixed(1)} ${y(v).toFixed(1)}`; });
    const area = `${k} L${(x(n - 1) + w / 2).toFixed(1)} ${VH - B} L${(x(0) + w / 2).toFixed(1)} ${VH - B} Z`;
    g = `<path d="${area}" class="area"/>` + g + `<path d="${d}" class="sp"/><path d="${k}" class="room"/>` +
      `<line x1="${x(0).toFixed(1)}" x2="${x(0).toFixed(1)}" y1="${TOP}" y2="${pb}" class="nowl"/>`;
    for (let i = 0; i <= n; i += 6) {
      const t = new Date(start.getTime() + i * 3600000);
      g += `<text x="${x(i).toFixed(1)}" y="${VH - 4}" text-anchor="${i === 0 ? "start" : (i === n ? "end" : "middle")}" class="axis${i === 0 ? " nowt" : ""}">${i === 0 ? this._t("now") : this._hour(t)}</text>`;
    }
    g += `<line class="cur" x1="0" x2="0" y1="${TOP}" y2="${pb}"/><circle class="dot2" r="3.5"/><circle class="dot" r="4"/>` +
      `<rect class="hit" x="${L}" y="${TOP}" width="${VW - L - R}" height="${pb - TOP}"/>`;
    this._geo = { n, L, w, sp: sp.map((v) => y(v)), kt: kt.map((v) => y(v)), start: start.getTime(), plan, day };
    return `<div class="chart"><div class="ch"><span>${this._t("next24")}</span><span class="info">${this._info(0)} \u00b7 <i>${this._t("scrub")}</i></span></div>
      <svg viewBox="0 0 ${VW} ${VH}">${g}</svg>
      <div class="leg"><span><b class="l sp"></b>${this._t("setpoint")}</span><span><b class="l room"></b>${this._t("expected")}</span>
      <span><b class="l price"></b>${this._t("price")}</span>${guess.some((g) => g) ? `<span><b class="l price guess"></b>${this._t("guessed")}</span>` : ""}
      <span><b class="l band"></b>${this._t("comfort")}</span></div></div>`;
  }

  _info(i) {
    const p = this._geo && this._geo.plan[i];
    if (!p) return "";
    const t = i === 0 ? this._t("now") : this._hour(new Date(this._geo.start + i * 3600000));
    const tariff = nn(p[4], p[3]);
    // the planner may count another price: the battery's refill cost, or own solar
    const uses = Math.abs(p[3] - tariff) >= 0.5 ? ` (${this._t("uses")} ${this._num(p[3], 0)} ct)` : "";
    return `<b>${t}</b> \u00b7 ${this._t("setpoint")} <b class="o">${this._num(p[0], 1)}${DEG}</b> \u00b7 ${this._t("room")} <b>${this._num(p[1], 1)}${DEG}</b>` +
      ` \u00b7 <b>${this._num(tariff, 0)} ct</b>${p[5] ? " " + this._t("guessed") : ""}${uses}${this._geo.day[i] ? "" : " \u00b7 " + this._t("night")}`;
  }

  _wire() {
    const root = this.shadowRoot, hit = root.querySelector(".hit");
    root.querySelectorAll(".seg span").forEach((s) => s.addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._view = s.dataset.v;
      this._render();
    }));
    if (this._view === "history" && this._histOn()) { this._wireHist(); return; }
    const steer = root.querySelector(".steer");
    if (steer) {
      steer.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (!steer.dataset.armed) {
          steer.dataset.armed = "1";
          steer.textContent = this._t("sure");
          setTimeout(() => { if (steer.isConnected) { delete steer.dataset.armed; steer.textContent = this._t("steer"); } }, 5000);
          return;
        }
        this._hass.callService("select", "select_option", { entity_id: this._siblings().mode, option: "active" });
      });
    }
    if (!hit || !this._geo) return;
    const move = (ev) => {
      const r = hit.getBoundingClientRect();
      const cx = ev.touches && ev.touches.length ? ev.touches[0].clientX : ev.clientX;
      const i = Math.max(0, Math.min(this._geo.n - 1, Math.floor((cx - r.left) / r.width * this._geo.n)));
      const xx = this._geo.L + (i + 0.5) * this._geo.w;
      const cur = root.querySelector(".cur"), dot = root.querySelector(".dot"), dot2 = root.querySelector(".dot2");
      cur.setAttribute("x1", xx); cur.setAttribute("x2", xx);
      dot.setAttribute("cx", xx); dot.setAttribute("cy", this._geo.kt[i]);
      dot2.setAttribute("cx", xx); dot2.setAttribute("cy", this._geo.sp[i]);
      root.querySelector(".chart").classList.add("on");
      root.querySelector(".info").innerHTML = this._info(i);
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("touchmove", move, { passive: true });
  }

  _footer(a) {
    const s24 = this._sib("saving_next_24h"), sm = this._sib("saving_month"), sy = this._sib("saving_yesterday");
    const bits = [];
    if (s24) bits.push(`${this._t("saving24")} <b>${this._money(parseFloat(s24.state))}</b>`);
    if (sy && !isNaN(parseFloat(sy.state))) bits.push(`${this._t("yesterday")} <b>${this._money(parseFloat(sy.state))}</b>`);
    if (sm && !isNaN(parseFloat(sm.state))) bits.push(`${this._t("month")} <b>${this._money(parseFloat(sm.state))}</b>`);
    if (a.cost_24h !== undefined) bits.push(`24 h ${this._money(a.cost_24h)} (${this._t("vs")} ${this._money(a.steady_cost_24h)})`);
    const acc = this._sib("plan_accuracy");          // nightly self-check: the room 6 hours ahead
    if (acc && !isNaN(parseFloat(acc.state))) {
      bits.push(`${this._t("accuracy")} <b>\u00b1${this._num(parseFloat(acc.state), 2)} ${DEG}</b>` +
        (acc.attributes.ready_to_steer && a.mode === "shadow" ? ` \u00b7 <b class="ok">${this._t("ready")}</b>` : ""));
    }
    // the Weheat import while it runs: months in and the expected end
    const imp = this._sib("weheat_import"), prog = this._sib("import_progress");
    if (imp && imp.state === "importing" && prog) {
      const pa = prog.attributes, end = pa.expected_done ? new Date(pa.expected_done) : null;
      bits.push(`${this._t("importing")} <b>${pa.months_done}/${pa.months}</b> ${this._t("months")}` +
        (end && !isNaN(end) ? `, ${this._t("done_at")} ~${this._hm(end)}` : ""));
    }
    // not ready yet, still in shadow: when Roost expects to be (ready sensor, nightly self-check)
    const ready = this._sib("ready");
    const code = ready && ready.state !== "on" && a.mode === "shadow" ? ready.attributes.waiting_for : null;
    const eta = code ? this._t("eta")[code] : null;
    if (eta) {
      const when = ready.attributes.expected ? new Date(ready.attributes.expected) : null;
      const hm = when && !isNaN(when) ? ` ~${this._hm(when)}` : "";
      bits.push(`${this._t("ready")}: ${eta}${hm}`);
    }
    return bits.length ? `<div class="foot">${bits.join(" \u00b7 ")}</div>` : "";
  }

  // ---------------------------------------------------------------- look back (websocket roost/history)
  _histOn() { return this._config.history !== false && !this._config.compact; }

  _fetchHist() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    this._hass.callWS({ type: "roost/history", entity_id: this._config.entity, days: 7 }).then((d) => {
      this._hist = d; this._histAt = Date.now(); this._histErr = null; this._loading = false; this._render();
    }).catch((e) => { this._histErr = String((e && e.message) || e); this._loading = false; this._render(); });
  }

  _histSlice() {
    const d = this._hist || { hours: [], events: [], days: {} };
    const t1 = Math.floor(Date.now() / 3600000) * 3600 + 3600, t0 = t1 - this._range * 3600;
    const hours = d.hours.filter((h) => h.ts >= t0 && h.ts < t1);
    const evTs = (e) => new Date(e.t).getTime() / 1000;
    const events = d.events.filter((e) => evTs(e) >= t0 && evTs(e) < t1).map((e) => Object.assign({ ts: evTs(e) }, e));
    return { d, t0, t1, hours, events };
  }

  _histBody() {
    if (!this._hist || Date.now() - (this._histAt || 0) > 300000) this._fetchHist();
    if (!this._hist) return `<div class="na">${this._histErr || this._t("h_loading")}</div>`;
    const s = this._histSlice();
    if (!s.hours.length) return this._rangeBar() + `<div class="na">${this._t("h_nodata")}</div>`;
    return this._rangeBar() + this._histTiles(s) + this._histChart(s) + this._histLog(s);
  }

  _rangeBar() {
    const r = (v, l) => `<span data-r="${v}" class="${this._range === v ? "on" : ""}">${l}</span>`;
    return `<div class="hbar"><div class="seg rng">${r(24, "24 h")}${r(48, "48 h")}${r(168, "7 d")}</div>` +
      `<button class="rep"><ha-icon icon="mdi:file-download-outline"></ha-icon>${this._t("h_report")}</button></div>`;
  }

  _histStats(s) {
    const comfort = nn(s.d.comfort, 20.5);
    const costed = s.hours.filter((h) => h.cost !== undefined && h.cost !== null);
    const cost = costed.length ? costed.reduce((t, h) => t + h.cost, 0) : null;
    const days = Object.keys(s.d.days || {}).filter((k) => new Date(k + "T12:00:00").getTime() / 1000 >= s.t0);
    const sav = days.map((k) => s.d.days[k].saving).filter((v) => v !== undefined && v !== null);
    const errs = s.hours.filter((h) => h.p6 !== null && h.p6 !== undefined).map((h) => ({ ts: h.ts, e: h.T - h.p6 }));
    const mae = errs.length ? errs.reduce((t, x) => t + Math.abs(x.e), 0) / errs.length : null;
    const worst = errs.reduce((m, x) => (!m || Math.abs(x.e) > Math.abs(m.e) ? x : m), null);
    const dayH = s.hours.filter((h) => h.day);
    const below = dayH.filter((h) => h.T < comfort - 0.3).length * 60;
    const low = s.hours.length ? Math.min.apply(null, s.hours.map((h) => h.T)) : null;
    let roost = 0;
    for (let i = 1; i < s.hours.length; i++) {
      const a = s.hours[i - 1].sp_t, b = s.hours[i].sp_t;
      if (a !== null && b !== null && a !== undefined && b !== undefined && Math.abs(a - b) >= 0.25) roost++;
    }
    const hand = s.events.filter((e) => e.kind === "by_hand").length;
    return { cost, sav: sav.length ? sav.reduce((t, v) => t + v, 0) : null, mae, worst, below, low, roost: Math.max(0, roost - hand), hand };
  }

  _histTiles(s) {
    const st = this._histStats(s);
    const tile = (label, value, sub) => `<div class="tile htile"><div class="tl">${label}</div><div class="tv">${value}</div><div class="ts">${sub}</div></div>`;
    return `<div class="tiles four">` +
      tile(this._t("h_cost"), st.cost !== null ? this._money(st.cost) : "\u2014", st.sav !== null ? `${this._t("h_saving")} ${this._money(st.sav)}` : "&nbsp;") +
      tile(this._t("h_pred"), st.mae !== null ? `\u00b1 ${this._num(st.mae, 1)}<span>${DEG}</span>` : "\u2014",
        st.worst ? `${this._t("h_largest")} ${this._num(Math.abs(st.worst.e), 1)} (${this._hour(new Date(st.worst.ts * 1000))})` : "&nbsp;") +
      tile(this._t("h_below"), `${st.below}<span>min</span>`, st.low !== null ? `${this._t("h_lowest")} ${this._num(st.low, 1)} ${DEG}` : "&nbsp;") +
      tile(this._t("h_changes"), `${st.roost} + ${st.hand}`, `${this._t("h_byroost")} \u00b7 ${this._t("h_byhand")}`) + `</div>`;
  }

  _histChart(s) {
    const VW = 440, VH = 190, L = 28, R = 6, TOP = 14, B = 58, n = this._range;
    const w = (VW - L - R) / n, x = (ts) => L + (ts - s.t0) / 3600 * w;
    const by = {}; s.hours.forEach((h) => { by[h.ts] = h; });
    const vals = [];
    s.hours.forEach((h) => { [h.T, h.p6, h.sp_t, h.sp_plan].forEach((v) => { if (v !== null && v !== undefined && !isNaN(v)) vals.push(v); }); });
    const lo = Math.floor(Math.min.apply(null, vals) - 0.3), hi = Math.ceil(Math.max.apply(null, vals) + 0.3);
    const y = (v) => TOP + (hi - v) / Math.max(0.5, hi - lo) * (VH - TOP - B);
    const pb = VH - 18, ph = 30;
    const pmax = Math.max(0.01, Math.max.apply(null, s.hours.map((h) => h.p_grid || 0)));
    const qmax = Math.max(0.5, Math.max.apply(null, s.hours.map((h) => h.q || 0)));
    const pmin = Math.min.apply(null, s.hours.map((h) => h.p_grid || 0));
    const tone = (p) => { const r = (p - pmin) / Math.max(0.01, pmax - pmin); return r < 0.33 ? "var(--rc-cheap)" : (r < 0.66 ? "var(--rc-mid)" : "var(--rc-dear)"); };
    let g = "";
    for (let v = Math.ceil(lo); v <= hi; v++) {
      g += `<line x1="${L}" x2="${VW - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="grid"/>` +
        `<text x="${L - 5}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end" class="axis">${v}\u00b0</text>`;
    }
    s.hours.forEach((h) => {
      const x0 = x(h.ts);
      if (h.paused) g += `<rect x="${x0.toFixed(1)}" y="${TOP}" width="${(w + 0.2).toFixed(1)}" height="${(pb - TOP).toFixed(1)}" class="hpause"/>`;
      const p = h.p_grid || 0, q = h.q || 0, bw = Math.max(0.6, w / 2 - 0.6);
      const hp = 3 + p / pmax * (ph - 3), hq = q / qmax * (ph - 3);
      g += `<rect x="${(x0 + 0.3).toFixed(1)}" y="${(pb - hp).toFixed(1)}" width="${bw.toFixed(1)}" height="${hp.toFixed(1)}" style="fill:${tone(p)}" class="price"/>`;
      if (hq > 0.2) g += `<rect x="${(x0 + w / 2).toFixed(1)}" y="${(pb - hq).toFixed(1)}" width="${bw.toFixed(1)}" height="${hq.toFixed(1)}" class="hheat"/>`;
    });
    const step = (key) => {
      let d = "", pen = false;
      s.hours.forEach((h) => {
        const v = h[key];
        if (v === null || v === undefined) { pen = false; return; }
        d += `${pen ? " L" : " M"}${x(h.ts).toFixed(1)} ${y(v).toFixed(1)} L${(x(h.ts) + w).toFixed(1)} ${y(v).toFixed(1)}`;
        pen = !!by[h.ts + 3600];
      });
      return d;
    };
    const line = (key) => {
      let d = "", pen = false;
      s.hours.forEach((h) => {
        const v = h[key];
        if (v === null || v === undefined) { pen = false; return; }
        d += `${pen ? " L" : " M"}${(x(h.ts) + w / 2).toFixed(1)} ${y(v).toFixed(1)}`;
        pen = !!by[h.ts + 3600];
      });
      return d;
    };
    g += `<path d="${step("sp_plan")}" class="hplan"/><path d="${step("sp_t")}" class="sp"/>` +
      `<path d="${line("p6")}" class="hpred"/><path d="${line("T")}" class="hroom"/>`;
    s.events.forEach((e) => {
      const tag = e.kind === "by_hand" ? "H" : (e.kind === "mode" ? "M" : (e.kind === "window" && e.phase === "open" ? this._t("h_win_mark") : ""));
      if (!tag) return;
      const xx = Math.max(L + 6, Math.min(VW - R - 6, x(e.ts)));
      g += `<circle cx="${xx.toFixed(1)}" cy="${TOP - 5}" r="5.5" class="hmark"/><text x="${xx.toFixed(1)}" y="${TOP - 2}" text-anchor="middle" class="hmt">${tag}</text>`;
    });
    s.hours.forEach((h) => {
      if (h.p6 !== null && h.p6 !== undefined && Math.abs(h.T - h.p6) >= 0.5) {
        g += `<circle cx="${(x(h.ts) + w / 2).toFixed(1)}" cy="${y(h.T).toFixed(1)}" r="3" class="hdev"/>`;
      }
    });
    const every = n <= 24 ? 6 : (n <= 48 ? 12 : 24);
    for (let i = 0; i <= n; i += every) {
      const t = new Date((s.t0 + i * 3600) * 1000);
      const lab = n > 48 ? t.toLocaleDateString(this._lang(), { weekday: "short" }) : this._hour(t);
      g += `<text x="${(L + i * w).toFixed(1)}" y="${VH - 4}" text-anchor="${i === 0 ? "start" : (i === n ? "end" : "middle")}" class="axis">${lab}</text>`;
    }
    g += `<line class="cur" x1="0" x2="0" y1="${TOP}" y2="${pb}"/><rect class="hit" x="${L}" y="${TOP}" width="${VW - L - R}" height="${pb - TOP}"/>`;
    this._hgeo = { L, w, n, t0: s.t0, by };
    const last = s.hours[s.hours.length - 1];
    return `<div class="chart hchart"><div class="ch"><span>${this._t("back")}</span><span class="info">${this._hinfo(last)} \u00b7 <i>${this._t("scrub")}</i></span></div>
      <svg viewBox="0 0 ${VW} ${VH}">${g}</svg>
      <div class="leg"><span><b class="l sp"></b>${this._t("h_sp_t")}</span><span><b class="l hplan"></b>${this._t("h_sp_p")}</span>
      <span><b class="l hroom"></b>${this._t("h_room")}</span><span><b class="l hpred"></b>${this._t("h_pred6")}</span>
      <span><b class="l price"></b>${this._t("price")}</span><span><b class="l hheat"></b>${this._t("h_heat")}</span></div></div>`;
  }

  _hinfo(h) {
    if (!h) return "";
    const t = this._hour(new Date(h.ts * 1000));
    const why = h.reason ? this._why(h.reason, h.args || {}, "") : "";
    const pred = h.p6 !== null && h.p6 !== undefined ? ` (${this._t("h_expected")} ${this._num(h.p6, 1)})` : "";
    return `<b>${t}</b> \u00b7 ${this._t("h_sp_p")} <b class="o">${this._num(h.sp_plan, 1)}${DEG}</b> / ${this._num(h.sp_t, 1)}${DEG}` +
      ` \u00b7 ${this._t("room")} <b>${this._num(h.T, 1)}${DEG}</b>${pred} \u00b7 <b>${this._num((h.p_grid || 0) * 100, 0)} ct</b>` +
      ` \u00b7 ${this._num(h.q || 0, 1)} kWh${why ? " \u00b7 " + why : ""}`;
  }

  _histItems(s) {
    const items = [];
    const by = {}; s.hours.forEach((h) => { by[h.ts] = h; });
    // what happened next: the room an hour later against what the plan expected for it
    const outcome = (ts) => {
      const nx = by[Math.floor(ts / 3600) * 3600 + 3600];
      if (!nx || nx.p1 === null || nx.p1 === undefined) return { out: "", cls: "" };
      const ok = Math.abs(nx.T - nx.p1) <= 0.3;
      return { out: `${this._t("h_room_after")} ${this._num(nx.T, 1)} (${this._t("h_expected")} ${this._num(nx.p1, 1)}) ${ok ? "\u2713" : "\u00b7 " + this._t("h_dev")}`,
               cls: ok ? "ok" : "warn" };
    };
    // shadow mode: what Roost would have set (the plan changed); active mode: what it did set (below)
    for (let i = 1; i < s.hours.length; i++) {
      const a = s.hours[i - 1], h = s.hours[i];
      if (h.mode !== "shadow" || a.sp_plan === null || h.sp_plan === null || a.sp_plan === undefined || h.sp_plan === undefined ||
          Math.abs(a.sp_plan - h.sp_plan) < 0.25) continue;
      items.push(Object.assign({ ts: h.ts, what: `\u2192 ${this._num(h.sp_plan, 1)}${DEG}`, why: this._why(h.reason, h.args || {}, "") }, outcome(h.ts)));
    }
    s.events.forEach((e) => {
      if (e.kind === "set") {
        // older events have no values for the reason: leave the parts that need them out
        const why = e.args ? this._why(e.reason, e.args, "") : this._why(e.reason, {}, "").replace(/\s*\([^()]*\{\w+\}[^()]*\)|\s*\{\w+\}\S*/g, "");
        items.push(Object.assign({ ts: e.ts, what: `\u2192 ${this._num(e.new, 1)}${DEG}`, why }, outcome(e.ts)));
      }
      else if (e.kind === "by_hand") items.push({ ts: e.ts, what: `\u2192 ${this._num(e.new, 1)}${DEG}`, why: this._t("h_set_hand").replace("{h}", this._num(e.pause_h || 2, 0)), out: "", cls: "", hand: true });
      else if (e.kind === "pause") items.push({ ts: e.ts, what: "", why: this._t("h_pause_ev").replace("{h}", this._num(e.hours, 1)), out: "", cls: "", hand: true });
      else if (e.kind === "window") items.push({ ts: e.ts, what: "", why: this._t(e.phase === "open" ? "h_window" : "h_window_end") +
        (e.phase === "open" && e.before !== undefined && e.before !== null && e.room !== null && e.room !== undefined ?
          ` (${this._num(e.before, 1)} \u2192 ${this._num(e.room, 1)}${DEG})` : ""), out: "", cls: "", hand: e.phase === "open" });
      else if (e.kind === "resume") items.push({ ts: e.ts, what: "", why: this._t("h_resume"), out: "", cls: "" });
      else if (e.kind === "mode") items.push({ ts: e.ts, what: "", why: `${this._t("h_mode")}: ${this._t(e.new) || e.new}`, out: "", cls: "" });
      else if (e.kind === "learned" && String(e.house || "").indexOf("adopted") >= 0) items.push({ ts: e.ts, what: "", why: this._t("h_learned"), out: "", cls: "" });
    });
    return items.sort((a, b) => b.ts - a.ts);
  }

  _histLog(s) {
    const items = this._histItems(s);
    const when = (ts) => {
      const d = new Date(ts * 1000);
      return (this._range > 24 && d.toDateString() !== new Date().toDateString() ? d.toLocaleDateString(this._lang(), { weekday: "short" }) + " " : "") + this._hour(d);
    };
    const rows = this._logOpen ? items.slice(0, 60).map((it) => `<div class="lrow"><span>${when(it.ts)}</span><span>${it.what}</span>` +
      `<span class="${it.hand ? "warn" : "mut"}">${it.why}</span><span class="${it.cls}">${it.out}</span></div>`).join("") : "";
    return `<div class="hlog"><div class="lhead">${this._t("h_log")} (${items.length}) ${this._logOpen ? "\u25be" : "\u25b8"}</div>${rows}</div>`;
  }

  _wireHist() {
    const root = this.shadowRoot;
    root.querySelectorAll(".rng span").forEach((sp) => sp.addEventListener("click", (ev) => {
      ev.stopPropagation(); this._range = parseInt(sp.dataset.r, 10); this._render();
    }));
    const lh = root.querySelector(".lhead");
    if (lh) lh.addEventListener("click", (ev) => { ev.stopPropagation(); this._logOpen = !this._logOpen; this._render(); });
    const rep = root.querySelector(".rep");
    if (rep) rep.addEventListener("click", (ev) => { ev.stopPropagation(); this._report(); });
    const hit = root.querySelector(".hchart .hit");
    if (!hit || !this._hgeo) return;
    const move = (ev) => {
      const r = hit.getBoundingClientRect();
      const cx = ev.touches && ev.touches.length ? ev.touches[0].clientX : ev.clientX;
      const i = Math.max(0, Math.min(this._hgeo.n - 1, Math.floor((cx - r.left) / r.width * this._hgeo.n)));
      const h = this._hgeo.by[this._hgeo.t0 + i * 3600];
      const xx = this._hgeo.L + (i + 0.5) * this._hgeo.w;
      const cur = root.querySelector(".hchart .cur");
      cur.setAttribute("x1", xx); cur.setAttribute("x2", xx);
      root.querySelector(".hchart").classList.add("on");
      if (h) root.querySelector(".hchart .info").innerHTML = this._hinfo(h);
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("touchmove", move, { passive: true });
  }

  // A page to keep or share: the period's numbers, the graph, the log and the days (built here, nothing is sent)
  _report() {
    const html = this._reportHtml();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    a.download = `roost-${new Date().toISOString().slice(0, 10)}.html`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  }

  _reportHtml() {
    const s = this._histSlice(), st = this._histStats(s);
    const svg = this.shadowRoot.querySelector(".hchart svg");
    const esc = (v) => String(v === undefined || v === null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;");
    const strip = (h) => String(h).replace(/<[^>]+>/g, "");
    const fromTo = `${new Date(s.t0 * 1000).toLocaleString(this._locale())} \u2013 ${new Date(s.t1 * 1000).toLocaleString(this._locale())}`;
    const days = Object.keys(s.d.days || {}).sort().reverse().slice(0, 62);
    const dayRows = days.map((k) => {
      const v = s.d.days[k];
      return `<tr><td>${k}</td><td>${this._num(v.kwh, 1)}</td><td>${this._num(v.heat_kwh, 1)}</td><td>${v.cop ? this._num(v.cop, 1) : "\u2014"}</td>` +
        `<td>${this._money(v.cost)}</td><td>${v.saving !== undefined ? this._money(v.saving) : "\u2014"}</td><td>${this._num(v.deficit_ch, 1)}</td>` +
        `<td>${v.changes} + ${v.by_hand}</td><td>${v.pred_mae !== null && v.pred_mae !== undefined ? "\u00b1" + this._num(v.pred_mae, 2) : "\u2014"}</td></tr>`;
    }).join("");
    const logRows = this._histItems(s).map((it) => `<tr><td>${new Date(it.ts * 1000).toLocaleString(this._locale())}</td><td>${esc(strip(it.what))}</td>` +
      `<td>${esc(strip(it.why))}</td><td>${esc(strip(it.out))}</td></tr>`).join("");
    const css = `body{font-family:system-ui,sans-serif;margin:24px;color:#222}h1{font-size:20px}table{border-collapse:collapse;font-size:13px;margin:8px 0 20px}
      td,th{border-bottom:1px solid #ddd;padding:4px 8px;text-align:left}svg{max-width:760px;width:100%}
      .grid{stroke:#e5e5e5}.axis{fill:#777;font-size:10px}.sp{fill:none;stroke:#fb923c;stroke-width:2.2}.hplan{fill:none;stroke:#fb923c;stroke-width:1.5;stroke-dasharray:4 3}
      .hroom{fill:none;stroke:#222;stroke-width:2}.hpred{fill:none;stroke:#378add;stroke-width:1.5;stroke-dasharray:4 3}.price{opacity:.55}
      .hheat{fill:#f0997b;opacity:.8}.hpause{fill:#f5a524;opacity:.12}.hmark{fill:#fde7c2;stroke:#ba7517}.hmt{fill:#7a4a06;font-size:8px}.hdev{fill:#e5484d}
      .cur,.hit{display:none}:root{--rc-cheap:#30a46c;--rc-mid:#f5a524;--rc-dear:#e5484d}`;
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>Roost \u2013 ${esc(this._t("back"))}</title><style>${css}</style></head><body>
      <h1>Roost \u2013 ${esc(this._t("back"))}</h1><p>${esc(this._t("h_period"))}: ${esc(fromTo)}</p>
      <table><tr><th>${esc(this._t("h_cost"))}</th><th>${esc(this._t("h_saving"))}</th><th>${esc(this._t("h_pred"))}</th><th>${esc(this._t("h_below"))}</th><th>${esc(this._t("h_changes"))}</th></tr>
      <tr><td>${st.cost !== null ? this._money(st.cost) : "\u2014"}</td><td>${st.sav !== null ? this._money(st.sav) : "\u2014"}</td><td>${st.mae !== null ? "\u00b1" + this._num(st.mae, 2) + " \u00b0C" : "\u2014"}</td>
      <td>${st.below} min</td><td>${st.roost} + ${st.hand}</td></tr></table>
      ${svg ? svg.outerHTML : ""}
      <h2>${esc(this._t("h_log"))}</h2><table>${logRows}</table>
      <h2>${esc(this._t("h_day"))}</h2><table><tr><th>${esc(this._t("h_day"))}</th><th>${esc(this._t("h_kwh"))}</th><th>${esc(this._t("h_heat"))}</th><th>${esc(this._t("h_cop"))}</th>
      <th>${esc(this._t("h_cost"))}</th><th>${esc(this._t("h_saving"))}</th><th>${esc(this._t("h_deficit"))}</th><th>${esc(this._t("h_changes"))}</th><th>${esc(this._t("h_pred"))}</th></tr>${dayRows}</table>
      </body></html>`;
    return html;
  }

  _style() {
    return `<style>
      :host { --rc-sp: #fb923c; --rc-cheap: var(--success-color, #30a46c); --rc-mid: var(--warning-color, #f5a524); --rc-dear: var(--error-color, #e5484d);
              --rc-band: var(--success-color, #30a46c); --rc-room: var(--primary-text-color); }
      ha-card { padding: 16px; cursor: pointer; }
      .na { color: var(--secondary-text-color); padding: 8px 0; }
      .head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
      .ico { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex: none;
             background: color-mix(in srgb, var(--rc-sp) 18%, transparent); color: var(--rc-sp); }
      .ht { flex: 1; min-width: 0; } .tt { font-size: 16px; font-weight: 600; }
      .sub { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .pill { font-size: 11px; font-weight: 600; letter-spacing: .3px; padding: 3px 9px; border-radius: 999px; flex: none; }
      .pill.active { background: color-mix(in srgb, var(--success-color, #30a46c) 20%, transparent); color: var(--success-color, #30a46c); }
      .pill.shadow, .pill.off { background: color-mix(in srgb, var(--secondary-text-color) 18%, transparent); color: var(--secondary-text-color); }
      .pill.warn { background: color-mix(in srgb, var(--warning-color, #f5a524) 20%, transparent); color: var(--warning-color, #f5a524); }
      .tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
      .tile { border: 1px solid var(--divider-color); border-radius: 12px; padding: 9px 11px; min-width: 0; }
      .rooms { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
      .room { font-size: 11.5px; color: var(--secondary-text-color); border: 1px solid var(--divider-color); border-radius: 999px; padding: 3px 9px; }
      .room b { color: var(--primary-text-color); font-weight: 600; } .room i { font-style: normal; opacity: .75; }
      .room.cold { border-color: var(--warning-color, #f5a524); color: var(--warning-color, #f5a524); }
      .tl { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--secondary-text-color); }
      .tl ha-icon { --mdc-icon-size: 15px; }
      .tv { font-size: 21px; font-weight: 700; margin-top: 3px; white-space: nowrap; } .tv.big { font-size: 25px; }
      .tv span { font-size: .55em; font-weight: 500; color: var(--secondary-text-color); margin-left: 2px; }
      .tile.plan .tv { color: var(--rc-sp); }
      .ts { font-size: 11px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .chart { margin-top: 14px; cursor: default; touch-action: pan-y; user-select: none; -webkit-user-select: none; }
      .ch { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
      .info { font-weight: 400; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .info b.o { color: var(--rc-sp); } .info i { font-style: normal; opacity: .8; }
      .chart.on .info i { display: none; }
      svg { width: 100%; display: block; touch-action: pan-y; }
      .band { fill: var(--rc-band); opacity: .07; } .grid { stroke: var(--divider-color); stroke-width: 1; }
      .axis { fill: var(--secondary-text-color); font-size: 10px; } .nowt { fill: var(--rc-sp); }
      .price { opacity: .55; } .price.guess { opacity: .2; } .area { fill: var(--rc-room); opacity: .06; }
      .sp { fill: none; stroke: var(--rc-sp); stroke-width: 2.2; stroke-linejoin: round; }
      .room { fill: none; stroke: var(--rc-room); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
      .nowl { stroke: var(--rc-sp); stroke-width: 1.5; opacity: .6; }
      .cur { stroke: var(--secondary-text-color); stroke-dasharray: 2 2; opacity: 0; } .dot { fill: var(--rc-room); opacity: 0; }
      .dot2 { fill: var(--rc-sp); opacity: 0; } .chart.on .cur, .chart.on .dot, .chart.on .dot2 { opacity: 1; }
      .hit { fill: transparent; cursor: crosshair; }
      .leg { display: flex; flex-wrap: wrap; gap: 12px; font-size: 11px; color: var(--secondary-text-color); margin-top: 4px; }
      .leg span { display: inline-flex; align-items: center; gap: 5px; }
      .l { display: inline-block; width: 14px; height: 3px; border-radius: 2px; } .l.sp { background: var(--rc-sp); }
      .l.room { background: var(--rc-room); } .l.price { height: 8px; background: linear-gradient(90deg, var(--rc-cheap), var(--rc-mid), var(--rc-dear)); opacity: .6; }
      .l.price.guess { opacity: .2; }
      .l.band { height: 8px; background: var(--rc-band); opacity: .25; }
      .foot { font-size: 12px; color: var(--secondary-text-color); margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--divider-color); }
      .seg { display: flex; border: 1px solid var(--divider-color); border-radius: 8px; overflow: hidden; font-size: 11.5px; flex: none; cursor: pointer; }
      .seg span { padding: 3px 8px; color: var(--secondary-text-color); } .seg span.on { background: color-mix(in srgb, var(--rc-sp) 18%, transparent); color: var(--rc-sp); font-weight: 600; }
      .hbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
      .rep { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; padding: 3px 9px; border-radius: 8px; border: 1px solid var(--divider-color);
             background: none; color: var(--secondary-text-color); cursor: pointer; } .rep ha-icon { --mdc-icon-size: 15px; }
      .tiles.four { grid-template-columns: repeat(4, minmax(0, 1fr)); } .htile .tv { font-size: 18px; }
      .hplan { fill: none; stroke: var(--rc-sp); stroke-width: 1.5; stroke-dasharray: 4 3; }
      .hroom { fill: none; stroke: var(--rc-room); stroke-width: 2; stroke-linejoin: round; }
      .hpred { fill: none; stroke: var(--info-color, #378add); stroke-width: 1.5; stroke-dasharray: 4 3; }
      .hheat { fill: #f0997b; opacity: .8; } .hpause { fill: var(--warning-color, #f5a524); opacity: .12; }
      .hmark { fill: color-mix(in srgb, var(--warning-color, #f5a524) 25%, var(--card-background-color, #fff)); stroke: var(--warning-color, #f5a524); stroke-width: .7; }
      .hmt { fill: var(--primary-text-color); font-size: 8px; font-weight: 600; } .hdev { fill: var(--error-color, #e5484d); }
      .l.hplan { background: none; border-top: 2px dashed var(--rc-sp); height: 0; } .l.hroom { background: var(--rc-room); }
      .l.hpred { background: none; border-top: 2px dashed var(--info-color, #378add); height: 0; } .l.hheat { height: 8px; background: #f0997b; }
      .hlog { margin-top: 10px; font-size: 12px; } .lhead { cursor: pointer; color: var(--secondary-text-color); font-weight: 600; padding: 4px 0; }
      .lrow { display: grid; grid-template-columns: 70px 62px minmax(0, 1fr) auto; gap: 8px; padding: 5px 0; border-top: 1px solid var(--divider-color); }
      .lrow .mut { color: var(--secondary-text-color); } .lrow .warn { color: var(--warning-color, #f5a524); } .lrow .ok { color: var(--success-color, #30a46c); }
      .foot b { color: var(--primary-text-color); }
      .steer { margin-top: 10px; width: 100%; padding: 9px; border-radius: 10px; border: 1px solid var(--success-color, #30a46c);
               background: color-mix(in srgb, var(--success-color, #30a46c) 15%, transparent); color: var(--success-color, #30a46c);
               font-weight: 600; font-size: 13px; cursor: pointer; } .foot b.ok { color: var(--success-color, #30a46c); }
    </style>`;
  }
}

class RoostCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }

  // The toggles show what the card really shows. Switching "compact" resets the parts to its preset, and a part
  // that matches the preset is left out of the YAML, so the configuration stays short.
  _changed(value) {
    const prev = this._config || {};
    const v = Object.assign({}, value);
    if (!!v.compact !== !!prev.compact) PARTS.forEach((p) => { delete v["show_" + p]; });
    else PARTS.forEach((p) => { if (v["show_" + p] === showDefault(v, p)) delete v["show_" + p]; });
    if (!v.compact) delete v.compact;
    if (!v.title) delete v.title;
    if (!v.language || v.language === "auto") delete v.language;
    if (!v.time_format || v.time_format === "auto") delete v.time_format;
    if (v.history !== false) delete v.history;
    if (!v.view || v.view === "plan") delete v.view;
    this._config = v;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: v }, bubbles: true, composed: true }));
  }

  _render() {
    if (!this._hass || !this._config) return;
    const t = T[lang2(this._hass)] || T.en;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => t["e_" + s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => this._changed(ev.detail.value));
      this.appendChild(this._form);
    }
    const data = Object.assign({}, this._config, { compact: !!this._config.compact,
      language: this._config.language || "auto", time_format: this._config.time_format || "auto",
      history: this._config.history !== false, view: this._config.view || "plan" });
    PARTS.forEach((p) => { data["show_" + p] = shows(this._config, p); });
    this._form.hass = this._hass;
    this._form.data = data;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { filter: { integration: "roost", domain: "sensor" } } } },
      { name: "title", selector: { text: {} } },
      { name: "compact", selector: { boolean: {} } },
      { type: "grid", name: "", schema: [
        { name: "view", selector: { select: { mode: "dropdown", options: [
          { value: "plan", label: t.v_plan }, { value: "history", label: t.v_history }] } } },
        { name: "history", selector: { boolean: {} } }] },
      { type: "grid", name: "", schema: [
        { name: "language", selector: { select: { mode: "dropdown", options: [
          { value: "auto", label: t.e_auto }, { value: "en", label: "English" }, { value: "nl", label: "Nederlands" }] } } },
        { name: "time_format", selector: { select: { mode: "dropdown", options: [
          { value: "auto", label: t.e_auto }, { value: "24", label: "24h (13:45)" }, { value: "12", label: "12h (1:45 PM)" }] } } }] },
      { type: "grid", name: "", schema: PARTS.map((p) => ({ name: "show_" + p, selector: { boolean: {} } })) },
    ];
  }
}

// Home Assistant 2026.9+ swaps window.customElements for a scoped registry while it starts: define in the registry
// that is there now, and again in the new one as soon as it appears (lesson from the Shower Time card).
const ELEMENTS = [["roost-card", RoostCard], ["roost-card-editor", RoostCardEditor]];
const defineIn = (registry) => {
  for (const pair of ELEMENTS) {
    try { if (!registry.get(pair[0])) registry.define(pair[0], pair[1]); } catch (e) { /* defined meanwhile */ }
  }
};
let registry = window.customElements;
defineIn(registry);
const recheck = () => { if (window.customElements !== registry) { registry = window.customElements; defineIn(registry); } };
if (registry.whenDefined) registry.whenDefined("home-assistant").then(recheck);
let checks = 0;
const timer = setInterval(() => { recheck(); if (++checks >= 120) clearInterval(timer); }, 250);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "roost-card")) {
  window.customCards.push({ type: "roost-card", name: "Roost", preview: true,
    description: "The 24-hour heating plan of your Weheat heat pump." });
}
console.info(`%c ROOST-CARD %c ${CARD_VERSION} `, "background:#fb923c;color:#fff;border-radius:3px 0 0 3px",
  "background:#222;color:#fff;border-radius:0 3px 3px 0");
})();
