// The card's own logic, without a browser: typed numbers, limits, reasons in every language, OpenTherm hours.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import test from "node:test";
import assert from "node:assert/strict";

const src = readFileSync(fileURLToPath(new URL("../custom_components/roost/frontend/roost-card.js", import.meta.url)), "utf8");
const elements = new Map();
const registry = { get: (name) => elements.get(name), define: (name, value) => elements.set(name, value) };
vm.runInNewContext(src, { HTMLElement: class {}, window: { customElements: registry }, console: { info() {} },
  setInterval() {}, clearInterval() {}, setTimeout() {}, clearTimeout() {}, Date, Intl });
const Card = elements.get("roost-card");

function card(lang = "nl", attrs = {}, states = {}) {
  const c = new Card();
  c._config = { language: lang, entity: "sensor.roost_planned_setpoint" };
  const all = Object.assign({ "sensor.roost_planned_setpoint": { state: "0", attributes: attrs } }, states);
  c._hass = { locale: { language: lang }, config: { currency: "EUR" }, states: all, callService: () => Promise.resolve() };
  c._render = () => {};
  return c;
}

test("every reason Roost gives has a text in all four languages", () => {
  const py = readFileSync(fileURLToPath(new URL("../custom_components/roost/reasons.py", import.meta.url)), "utf8");
  const codes = [...py.matchAll(/^\s+"([a-z][a-z0-9_]+)":\s*"/gm)].map((m) => m[1]);
  assert.ok(codes.length > 20);
  for (const lang of ["en", "nl", "de", "fr"]) {
    const c = card(lang);
    for (const code of codes) {
      const text = c._why(code, { kw: 1.3, q_min: 2.8, ct: 30, sp: 21, min: 20, at: 7, room: 20, state: "curve" }, "");
      assert.ok(text && !/\{\w+\}/.test(text), `${lang} ${code}: ${text}`);
    }
  }
  assert.match(card("nl")._why("ot_below_min", { kw: 1.3, q_min: 2.8 }, ""), /1,3 kW.*2,8 kW/);
  // the box's state in words, an unknown code as it is
  assert.match(card("nl")._why("ot_fallback", { state: "curve_ha_offline" }, ""), /\(Home Assistant is weg\)/);
  assert.match(card("nl")._why("ot_fallback", { state: "weird" }, ""), /\(weird\)/);
});

test("a typed setting snaps to its step and limits; garbage and an order the wrong way round are refused", () => {
  const c = card("nl", { comfort: 20.5, day_from: 7, day_to: 22 });
  const calls = [];
  c._hass.callService = (d, s, data) => { calls.push(data); return Promise.resolve(); };
  c._setTo("comfort", 21.3, true);
  assert.equal(c._pend.comfort.v, 21.5);
  c._setTo("comfort", 40, true);
  assert.equal(c._pend.comfort.v, 25);
  c._setTo("comfort", NaN, true);
  assert.ok(c._pend.comfort.err);
  c._setTo("day_from", 23, true);
  assert.ok(c._pend.day_from.err);
  c._setTo("day_to", 6, true);
  assert.ok(c._pend.day_to.err);
});

test("taps in a row add up from what is shown, not from the sensor", () => {
  const ot = { min_off_entity: "number.m_min_off_time", quiet_from: 22 };
  const c = card("nl", { opentherm: ot }, { "number.m_min_off_time": { state: "60.0", attributes: { min: 0, max: 120, step: 1 } } });
  for (let i = 0; i < 4; i++) c._step("ot_min_off", 1);
  assert.equal(c._pend.ot_min_off.v, 80);
  c._step("ot_min_off", -1);
  assert.equal(c._pend.ot_min_off.v, 75);
  for (let i = 0; i < 3; i++) c._step("ot_quiet_from", 1);
  assert.equal(c._pend.ot_quiet_from.v, 1);                  // 22 -> 23 -> 0 -> 1: hours go round
});

test("a value the sensor confirms is no longer pending", () => {
  const c = card("nl", { comfort: 21 });
  c._pend = { comfort: { v: 21, sent: true, at: Date.now() } };
  c._settle({ comfort: 21 });
  assert.equal(c._pend.comfort, undefined);
});

test("typed numbers: the comma, the point, spaces and units", () => {
  const c = card();
  const parse = (s) => { c._setTo("comfort", NaN); return s; };
  assert.ok(parse);
  const ctx = vm.createContext({});
  vm.runInContext(src.slice(src.indexOf("const parseNum"), src.indexOf("// Snaps a value")), ctx);
  const p = vm.runInContext("parseNum", ctx);
  assert.equal(p("20,5"), 20.5); assert.equal(p(" 20.5 "), 20.5); assert.equal(p("21 °C"), 21); assert.ok(isNaN(p("")));
  assert.ok(isNaN(p("abc")));
});

test("an OpenTherm hour shows its flow, never its heat output as a temperature", () => {
  const c = card();
  assert.equal(c._hset({ ot: true, sp_t: 2.8, flow: 34 }), 34);
  assert.equal(c._hsetTxt({ ot: true, sp_t: 0, flow: 0 }), "uit");
  assert.equal(c._hset({ sp_t: 20.5 }), 20.5);
  const ts = Math.floor(Date.now() / 3600000) * 3600 - 7200;
  c._range = 24;
  const s = { d: { comfort: 21, days: {} }, t0: ts - 3600 * 20, t1: ts + 7200, events: [],
    hours: [{ ts, T: 21, ot: true, sp_t: 2.8, sp_plan: 2.8, flow: 34, flow_meas: 31, q: 2.4, p_grid: 0.3, mode: "shadow" },
            { ts: ts + 3600, T: 21.2, ot: true, sp_t: 0, sp_plan: 0, flow: 0, q: 0, p_grid: 0.3, mode: "shadow" }] };
  const svg = c._histChart(s);
  assert.ok(!/>2°</.test(svg) && !/>3°</.test(svg), "no degree axis down at the heat output");
  assert.ok(svg.includes('class="offcol"') && svg.includes('class="hmeas"') && svg.includes('class="hwould"'));
  const items = c._histItems(s);
  assert.equal(items[0].what, "→ uit");
});

test("quiet hours switch off as well as on", () => {
  const sent = [];
  for (const on of [true, false]) {
    const c = card("nl", { opentherm: { quiet_on: on } });
    c._hass.callService = (d, s, data) => { sent.push(data); return Promise.resolve(); };
    const tap = c._taps().find((r) => r[0] === ".mini[data-otquiet]")[1];
    tap();
    assert.equal(c._pend.ot_quiet.v, !on);
    tap();                                         // a second tap before the sensor answered: back again
    assert.equal(c._pend.ot_quiet.v, on);
  }
});

test("the source is plain ASCII (wall tablets with an old browser or a wrong charset)", () => {
  assert.ok(!/[^\x00-\x7F]/.test(src));
});

test("shadow mode: the master's own curve next to what Roost asks; active mode: not", () => {
  const o = { flow_now: 28.9, curve_flow: 29.6, curve_flow_entity: "sensor.m_curve_flow" };
  const c = card("nl", { mode: "shadow", opentherm: o }, { "sensor.m_curve_flow": { state: "30.1", attributes: {} } });
  const txt = c._otNow(c._hass.states["sensor.roost_planned_setpoint"].attributes);
  assert.match(txt, /kastje 30,1°/);                // the live sensor before the attribute
  assert.match(txt, /28,9°/);
  assert.doesNotMatch(card("nl")._otNow({ mode: "active", opentherm: o }), /kastje/);
  assert.equal(card("nl")._otNow({ mode: "shadow", opentherm: { hot_water: true } }), "pomp maakt warm water");
});

test("learning shows how far it is", () => {
  const t = card("nl")._learnProgress({ learned: { steady: 18, starts: 1 }, learn_need: { steady: 72, starts: 3 } });
  assert.equal(t, "18 van 72 stabiele metingen · 1 van 3 starts");
});

test("the shadow summary counts what Roost would ask against what the unit did", () => {
  const c = card("nl"); c._range = 24;
  const h = (flow, sp_t, q) => ({ ot: true, mode: "shadow", flow, sp_t, q });
  const s = { hours: [h(34, 2.8, 2.4), h(0, 0, 2.5), h(30, 2.8, 0), h(0, 0, 0.1), { ot: false, mode: "shadow", sp_t: 20, q: 3 }] };
  assert.equal(c._shadowSum(s).replace(/<[^>]+>/g, ""),
    "Meekijken, laatste 24 h: Roost zou 2 u stoken (5,6 kWh warmte); de pomp stookte 2 u (5,0 kWh)");
  assert.equal(c._shadowSum({ hours: [{ ot: true, mode: "active", flow: 30, sp_t: 2.8, q: 2.8 }] }), "");
});

test("Roost asks other than the plan's flow: its correction within the hour is shown, in all four languages", () => {
  const a = { mode: "active", plan: [[30.0, 21.1, 0.59]], pump: { out_kw: 3.03 }, opentherm: { level: 3.33, flow_now: 29.3 } };
  const nl = card("nl")._otNow(a, 30.5);
  assert.match(nl, /plan 30,0°, \+0,5°: de pomp levert 3,0 van 3,3 kW/);
  for (const lang of ["en", "de", "fr"]) assert.match(card(lang)._otNow(a, 30.5), /3[.,]0.*3[.,]3 kW/);
  assert.doesNotMatch(card("nl")._otNow(a, 30.0), /plan/);                         // as planned: no line
  assert.doesNotMatch(card("nl")._otNow(Object.assign({}, a, { mode: "shadow" }), 30.5), /plan/);   // shadow: Roost asks nothing
  assert.match(card("nl")._otNow(Object.assign({}, a, { pump: { out_kw: 3.03, cop: 4.8 } }), 30.5), /pomp nu 29,3°, COP 4,8/);
  assert.doesNotMatch(nl, /COP/);                                                    // no COP (not heating): no COP
  assert.match(card("nl")._otNow(a, 29.5), /−0,5°/);                         // lower than the plan
});
