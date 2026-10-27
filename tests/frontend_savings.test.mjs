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

test("a limited tariff horizon is visible and the missing 24-hour estimate is explained", () => {
  for (const lang of ["en", "nl", "de", "fr"]) {
    const c = card(lang);
    assert.equal(c._priceHorizon({}), "");
    assert.equal(c._priceHorizon({ price_limited_until: "invalid" }), "");
    const msg = c._priceHorizon({ price_limited_until: "2026-10-27T00:00:00+01:00" });
    assert.ok(msg.length > 50 && !msg.includes("{time}"));
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
    assert.ok(weekly.includes("week-settings") && daily.includes("week-settings"));
    assert.ok(!weekly.includes('data-set="day_from"') && daily.includes('data-set="day_from"'));
    assert.ok(!weekly.includes("undefined") && !daily.includes("undefined"));
  }
});

test("partial comfort hours draw only the scheduled quarters", () => {
  const c = card();
  c._info = () => "";
  c._pwhy = () => "";
  const a = { start: "2026-10-26T07:00:00+01:00", comfort: 21, day_min: 20, night_min: 19,
    store_max: 23, plan: [[21,20.5,.2,25,25,0],[21,20.6,.2,25,25,0]],
    day_hours: [1,0], comfort_masks: [[false,false,true,true],[false,false,false,false]] };
  const html = c._chart(a);
  assert.equal((html.match(/class="band"/g) || []).length, 2);
  assert.ok(!html.includes("NaN"));
});
