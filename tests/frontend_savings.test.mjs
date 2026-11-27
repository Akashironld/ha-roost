import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import test from "node:test";
import assert from "node:assert/strict";

const elements = new Map();
const registry = { get: (name) => elements.get(name), define: (name, value) => elements.set(name, value) };
vm.runInNewContext(readFileSync(fileURLToPath(new URL("../custom_components/roost/frontend/roost-card.js", import.meta.url)), "utf8"), {
  HTMLElement: class {}, window: { customElements: registry }, console: { info() {} },
  setInterval() {}, clearInterval() {}, Date, Intl,
});
const Card = elements.get("roost-card");

function card(language = "nl") {
  const c = new Card();
  c._config = { language };
  c._hass = { locale: { language }, config: { currency: "EUR" } };
  c._histAt = Date.now();
  return c;
}

test("all languages explain why the saving is unavailable", () => {
  for (const lang of ["en", "nl", "de", "fr"]) {
    const c = card(lang);
    const text = c._savingQuality({ valid: false, reasons: ["energy_mismatch", "missing_context"] });
    assert.ok(text.length > 50);
    assert.ok(!text.includes("energy_mismatch") && !text.includes("missing_context"));
  }
});

test("the missing 24-hour estimate is explained", () => {
  for (const lang of ["en", "nl", "de", "fr"]) {
    const c = card(lang);
    const reason = c._savingQuality({ valid: false, reasons: ["incomplete_forecast"] });
    assert.ok(reason.length > 40 && !reason.includes("incomplete_forecast"));
  }
});

test("storage labels are not presented as a causal finding of unnecessary hours", () => {
  const c = card();
  const ts = Math.floor(Date.now() / 3600000) * 3600 - 86400;
  const date = new Date(ts * 1000);
  const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  c._hist = { hours: [{ ts, T: 23, sp_t: 22.5, sp_plan: 22.5, reason: "store_cheap", e: 0.5 }],
    events: [], days: { [day]: { cost: 0.5, saving: -0.15 } } };
  const html = c._tableBack();
  assert.ok(html.includes("voorverwarmingslabel"));
  assert.ok(!html.includes("die niet nodig waren"));
});

test("invalid days show the validation reason instead of inventing a storage cause", () => {
  const c = card();
  const ts = Math.floor(Date.now() / 3600000) * 3600 - 86400;
  const date = new Date(ts * 1000);
  const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  c._hist = { hours: [{ ts, T: 20.5, sp_t: 20.5, sp_plan: 20.5, reason: "store_cheap" }], events: [],
    days: { [day]: { cost: 0.04, saving: null, quality: { valid: false, reasons: ["energy_mismatch"] } } } };
  const html = c._tableBack();
  assert.ok(html.includes("wijkt te veel af van de meter"));
  assert.ok(!html.includes("uur met een voorverwarmingslabel"));
  assert.equal(c._money(null), "\u2014");
});


test("weekly settings hide the legacy hour controls and remain available in every language", () => {
  const a = { comfort: 21, day_min: 20, night_min: 19, lowest_setpoint: 19,
    store_max: 23, day_from: 7, day_to: 22 };
  for (const lang of ["en", "nl", "de", "fr"]) {
    const c = card(lang);
    const weekly = c._settingsPanel({ ...a, weekly_comfort: true });
    const daily = c._settingsPanel(a);
    // v0.8.0: the weekly periods are edited in the card itself (no button to Configure)
    assert.ok(weekly.includes("data-wsave") && daily.includes('data-wmode="1"') && !daily.includes("data-wsave"));
    assert.ok(!weekly.includes('data-num="day_from"') && daily.includes('data-num="day_from"'));
    assert.ok(!weekly.includes("undefined") && !daily.includes("undefined"));
  }
});

test("partial comfort hours draw only the scheduled quarters", () => {
  const c = card();
  c._info = () => "";
  const a = { start: "2026-10-26T07:00:00+01:00", comfort: 21, day_min: 20, night_min: 19,
    store_max: 23, plan: [[21,20.5,.2,25,25,0],[21,20.6,.2,25,25,0]],
    day_hours: [1,0], comfort_masks: [[false,false,true,true],[false,false,false,false]] };
  const html = c._chart(a);
  assert.equal((html.match(/class="band"/g) || []).length, 2);
  assert.ok(!html.includes("NaN"));
});

const plan = [[20.5,21.2,0,25,25,0],[20.5,21.1,0,24,24,0],[21.5,21.0,.4,22,22,0],[21.5,21.3,.5,23,23,0]];

const why = [["holding", { sp: 20.5 }], ["holding", { sp: 20.5 }], ["store_cheap", { ct: 22 }], ["expensive", { ct: 23 }]];
const v09 = (over) => Object.assign({ plan, plan_why: why, start: new Date().toISOString(), room: 21.2, comfort: 21, thermostat: 20.5,
  storage_kwh: 1.7, room_recent: [[1, 20.8], [2, 21.0], [3, 21.1]], day_hours: [1, 1, 0, 0], kwh_24h: 9.7, mode: "shadow",
  day_from: 7, day_to: 20, day_min: 19, night_min: 19, lowest_setpoint: 19, store_max: 25,
  pump_runs: { today: { starts: 2, minutes: 160 }, yesterday: { starts: 7, minutes: 31 }, heating: true },
  control_method: "heating_curve", control_reported_at: new Date().toISOString(), control_detected: "heating_curve",
  control_check: { steps: 94, gain: 0.03, days: 7 },
  control_mismatch: false, ot_available: false,
  pump: { state: "heating", raw: "heating", requested: 26.4, supply: 29.7, return: 27.5, delta_t: 2.2, in_kw: 0.48, out_kw: 2.97, cop: 6.2 },
  status: [], saving_calc: { steady: 3.75, plan: 3.43, end_steady: 1, end_plan: 1.12, saving: 0.2, parts: {} } }, over || {});

test("v0.9 tiles, pills and panels in every language, without undefined or NaN", () => {
  for (const lang of ["en", "nl", "de", "fr"]) {
    const c = card(lang);
    c._siblings = () => ({});
    const a = v09();
    let html = c._tiles({ state: "20.5" }, a, "ok", "x") + c._pills(a, "shadow", false, false, { state: "on" }, true);
    for (const k of ["mode", "pump", "ctrl", "saving", "settings"]) { c._open = k; html += c._panel(a, "shadow", false, false, { state: "on" }, true); }
    c._sel = 2; html += c._hourPanel(a);
    assert.ok(html.includes("spark") && html.includes("29") && html.includes("✓") && html.includes("26"), html);
    // reported by the pump: shown, not chosen (only the Weheat app changes it)
    assert.ok(!html.includes("data-wc") && html.includes("steer") && html.includes("k-store"));
    assert.ok(!html.includes("undefined") && !html.includes("NaN"), html);
  }
});

test("v0.9 states: problems as a line, mismatch and unknowns in their pill, never 0 for an unknown saving", () => {
  const c = card("en");
  c._siblings = () => ({});
  const a = v09({ control_method: "opentherm", control_detected: "heating_curve", control_mismatch: true, saving_calc: null, pump: null,
    status: [{ code: "set_failed", level: "red", args: { retry_min: 5 } }, { code: "weheat_missing", level: "amber", args: { since: null } },
      { code: "weheat_login", level: "amber", args: { since: new Date().toISOString() } },
      { code: "control_mismatch", level: "amber", args: {} }, { code: "paused", level: "info", args: {} }],
    paused_until: new Date(Date.now() + 7.2e6).toISOString() });
  const alerts = c._alerts(a);
  assert.equal((alerts.match(/class="alert/g) || []).length, 3);         // the mismatch and the pause are pills, not lines
  assert.ok(alerts.includes("Weheat login has expired"));
  assert.ok(alerts.includes("alert red") && alerts.includes("5 min"));
  const pills = c._pills(a, "active", true, false, null, true);
  assert.ok(pills.includes("ctrl amber") && pills.includes("Pump —") && pills.includes("Saving not known yet") && !pills.includes("€0") && pills.includes("left"));
  c._open = "ctrl";
  const panel = c._panel(a, "active", true, false, null, true);
  assert.ok(panel.includes("did not follow") && panel.includes("Weheat app") && !panel.includes("data-wc"));
  assert.ok(!(pills + panel + alerts).includes("undefined") && !(pills + panel + alerts).includes("NaN"));
});

test("the weekly editor draws overnight periods on the next day and edits by the quarter", () => {
  const c = card("nl");
  const week = { monday: [[1320, 120]], tuesday: [], wednesday: [], thursday: [], friday: [], saturday: [], sunday: [[420, 1440]] };
  const a = { weekly_comfort: true, comfort_week: week, day_from: 7, day_to: 22 };
  c._wkDay = 0;
  const html = c._weekEditor(a);
  assert.equal((html.match(/class="blk over"/g) || []).length, 1);         // Monday 22:00 runs on to Tuesday 02:00
  assert.ok(html.includes("22:00") && html.includes("02:00"));
  const fresh = card("nl");
  const draft = fresh._weekDraft({ day_from: 7, day_to: 22 });               // not weekly yet: the daily hours every day
  assert.equal(JSON.stringify(draft.friday), "[[420,1320]]");
});

test("the savings calendar marks counted and excluded days", () => {
  const c = card("nl");
  const d = new Date(), key = (n) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(n).padStart(2, "0")}`;
  c._sib = () => ({ state: "1.2", attributes: { included_days: [key(1)], excluded_days: [key(2)], day_reasons: { [key(2)]: ["settings_changed"] } } });
  const html = c._calendar();
  assert.ok(html.includes('class="cd ok"') && html.includes('class="cd bad"') && !html.includes("undefined"));
});

test("the month's saving is a pill that opens the calendar", () => {
  const c = card("nl");
  c._sib = (k) => (k === "saving_month" ? { state: "1.5", attributes: { included_days: ["x"], days_expected: 12 } } : null);
  const closed = c._savingPanel({});
  assert.ok(closed.includes("calpill") && closed.includes("1/12"));
  c._calOpen = true;
  assert.ok(c._savingPanel({}).includes("calpill on"));
});

test("the plan graph is drawn in the card's pixels and empty bits stay hidden", () => {
  const c = card("nl");
  c._info = () => "";
  const a = { start: new Date().toISOString(), comfort: 21, day_min: 19, night_min: 19, store_max: 25, plan, day_hours: [1, 1, 1, 1] };
  c._chartW = 1032;
  assert.ok(c._chart(a).includes('viewBox="0 0 1000 172"'));
  c._chartW = undefined;
  assert.ok(c._chart(a).includes('viewBox="0 0 440 172"'));
  const quiet = [[20.5, 21, 0, 25, 25, 0]];
  assert.ok(!c._chart({ ...a, plan: quiet }).includes("l pump"));
});

test("the comfort range in one line, the box on fallback and the advice of the last days", () => {
  const a = { comfort: 20, store_max: 23, night_min: 18, day_from: 7, weekly_comfort: false,
    opentherm: { follow_curve: true },
    comfort_advice: { days: 5, comfort: 20, night_min: 18, store_max: 23, top_off: { week: 2.8, short: 0 },
      top_down: { week: 0.02, short: 0 }, eco_down: { week: -0.35, short: 0.7 } } };
  for (const lang of ["en", "nl", "de", "fr"]) {
    const html = card(lang)._rangeLine(a, "opentherm");
    assert.ok(html.includes("20,0–23,0") || html.includes("20.0–23.0"), html);
    assert.ok(html.includes("07:00") && html.includes("18") && /r_|undefined|NaN/.test(html) === false, html);
    assert.ok(html.includes("s-advice") && html.includes("2,80") || html.includes("2.80"), html);
  }
  const nl = card("nl")._rangeLine(a, "opentherm");
  assert.ok(nl.includes("kastje bij terugval 20,0") && nl.includes("tot 22,0") && nl.includes("maakt niets uit") && nl.includes("iets kouder"), nl);
  const th = card("nl")._rangeLine({ ...a, comfort_advice: null, weekly_comfort: true }, "thermostat");
  assert.ok(!th.includes("kastje") && !th.includes("s-advice") && th.includes("per weekdag"), th);
});
