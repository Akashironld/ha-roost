/* Roost card - served by the roost integration. */
(() => {   // own scope: safe if the file is loaded twice as a classic script (legacy frontend + a manual resource)
const CARD_VERSION = "0.5.1";

// Plain ES2017 on purpose (no ?. / ??), ASCII only (\u escapes): wall tablets often run an older browser.
const nn = (a, b) => (a === null || a === undefined ? b : a);
const DEG = "\u00b0C";

const T = {
  en: { title: "Roost", room: "Room", thermostat: "Thermostat", planned: "Planned", next24: "Next 24 hours",
        setpoint: "setpoint", expected: "room expected", price: "tariff", guessed: "estimated", uses: "plan uses", comfort: "comfort hours", now: "now",
        night: "night", saving24: "expected saving", month: "this month", yesterday: "yesterday", vs: "vs steady", accuracy: "plan error 6 h", ready: "ready to steer", min: "min", steer: "Let Roost steer", sure: "Sure? Click again",
        active: "ACTIVE", shadow: "SHADOW", off: "OFF", paused: "PAUSED", scrub: "slide over the graph",
        stored: "stored", unavailable: "Not available", pick: "Pick the 'Planned setpoint' sensor of the Roost integration.",
        noplan: "no plan yet", heating: "heat pump heating", e_entity: "Sensor", e_title: "Title", e_language: "Language",
        e_time_format: "Time format", e_auto: "Like Home Assistant", e_show_tiles: "Tiles", e_show_chart: "24-hour plan",
        e_show_footer: "Saving", e_compact: "Compact (e.g. a wall tablet)" },
  nl: { title: "Roost", room: "Kamer", thermostat: "Thermostaat", planned: "Gepland", next24: "Komende 24 uur",
        setpoint: "setpoint", expected: "kamer verwacht", price: "tarief", guessed: "geschat", uses: "rekent met", comfort: "comforturen", now: "nu",
        night: "nacht", saving24: "verwachte besparing", month: "deze maand", yesterday: "gisteren", vs: "t.o.v. vast", accuracy: "planfout 6 u", ready: "klaar om te sturen", min: "min", steer: "Laat Roost sturen", sure: "Zeker? Klik nogmaals",
        active: "ACTIEF", shadow: "MEEKIJKEN", off: "UIT", paused: "GEPAUZEERD", scrub: "schuif over de grafiek",
        stored: "opgeslagen", unavailable: "Niet beschikbaar", pick: "Kies de sensor 'Gepland setpoint' van de integratie Roost.",
        noplan: "nog geen plan", heating: "warmtepomp stookt", e_entity: "Sensor", e_title: "Titel", e_language: "Taal",
        e_time_format: "Tijdnotatie", e_auto: "Zoals Home Assistant", e_show_tiles: "Tegels", e_show_chart: "24-uursplan",
        e_show_footer: "Besparing", e_compact: "Compact (bijv. een wandtablet)" },
};

// Why Roost plans or does something: the integration sends a code with values (reason_code/_args,
// decision_code/_args); the card words it. Unknown codes fall back to the English text of the integration.
const WHY = {
  en: { starting: "starting", no_price: "no price", no_room: "no room temperature",
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
  nl: { starting: "opstarten", no_price: "geen prijs", no_room: "geen kamertemperatuur",
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
  _sib(key) { const s = this._siblings(); const st = s[key] && this._hass.states[s[key]]; return st ? st : null; }

  _shell() {
    if (this._card && this._card.parentNode === this.shadowRoot) return this._card;
    this.shadowRoot.innerHTML = `${this._style()}<ha-card></ha-card>`;
    this._card = this.shadowRoot.querySelector("ha-card");
    this._card.addEventListener("click", (ev) => {
      if (!this._clickable || (ev.target && ev.target.closest && ev.target.closest(".chart"))) return;
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
    let html = `<div class="head"><div class="ico"><ha-icon icon="mdi:bird"></ha-icon></div>
      <div class="ht"><div class="tt">${title}</div><div class="sub">${reason}</div></div>${pill}</div>`;
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
    return bits.length ? `<div class="foot">${bits.join(" \u00b7 ")}</div>` : "";
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
      language: this._config.language || "auto", time_format: this._config.time_format || "auto" });
    PARTS.forEach((p) => { data["show_" + p] = shows(this._config, p); });
    this._form.hass = this._hass;
    this._form.data = data;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { filter: { integration: "roost", domain: "sensor" } } } },
      { name: "title", selector: { text: {} } },
      { name: "compact", selector: { boolean: {} } },
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
