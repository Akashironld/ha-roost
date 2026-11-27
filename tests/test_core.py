"""The functional core (custom_components/roost/core): pure functions on small state bundles, without Home Assistant.

  python3 tests/test_core.py
"""
import ast
import os
import sys
from dataclasses import replace
from datetime import timezone

sys.path.insert(0, os.path.dirname(__file__))
from core import _DIR, load, run_all  # noqa: E402

cm = load("core.meters")
cw = load("core.weather")
cp = load("core.prices")
cwh = load("core.weheat")
cpl = load("core.plan")
cc = load("core.card")
chl = load("core.hourlog")
planner = load("planner")
value = load("value")
CORE = os.path.join(_DIR, "core")


def test_the_core_never_imports_home_assistant():
    for name in sorted(os.listdir(CORE)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(CORE, name)).read())
        for node in ast.walk(tree):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(m.startswith("homeassistant") or m.startswith("aiohttp") for m in mods), (name, mods)
        # and not through the pure modules it uses either: run as `python3 tests/test_core.py` (no Home Assistant
        # installed) this import fails when anything on the way needs it
        load(f"core.{name[:-3]}")


# ------------------------------------------------------------ meters
def test_counting_never_changes_what_it_was_given():
    m = cm.Meters(cost_day="2026-11-24", last_elec=10.0)
    c = cm.count_cost(m, "2026-11-24", [10.5], None, 0.3)
    assert m.last_elec == 10.0 and m.kwh_today == 0.0                  # the old bundle is as it was
    assert c.meters.last_elec == 10.5 and abs(c.meters.kwh_today - 0.5) < 1e-12 and abs(c.cost - 0.15) < 1e-12
    assert c.counted and c.closed_day is None


def test_a_new_day_closes_the_old_one_and_starts_at_zero():
    m = cm.Meters(cost_day="2026-11-23", cost_today=1.2, kwh_today=4.0, last_elec=10.0)
    c = cm.count_cost(m, "2026-11-24", [10.2], None, 0.3)
    assert c.closed_day == "2026-11-23" and abs(c.meters.kwh_today - 0.2) < 1e-12 and abs(c.meters.cost_today - 0.06) < 1e-12


def test_a_meter_missing_counts_nothing_and_an_unknown_price_is_not_free():
    m = cm.Meters(cost_day="d", last_elec=10.0)
    assert not cm.count_cost(m, "d", [10.4, None], None, 0.3).counted
    c = cm.count_cost(m, "d", [10.4], None, None)
    assert c.meters.cost_today == 0.0 and abs(c.meters.unpriced_kwh - 0.4) < 1e-12 and c.cost == 0.0


def test_the_indoor_unit_counts_today_but_not_in_the_hour():
    m = cm.Meters(cost_day="d", last_indoor=5.0)
    c = cm.count_cost(m, "d", [], 5.1, 0.2)
    assert not c.counted and abs(c.meters.indoor_kwh_today - 0.1) < 1e-12 and abs(c.meters.cost_today - 0.02) < 1e-12


def test_stored_heat_ages_and_a_short_restart_is_no_event():
    m = cm.Meters(storage_e=4.0)
    short, ev = cm.age_storage(m, 1000.0, 1060.0, 1.0)
    assert ev is None and 3.9 < short.storage_e <= 4.0
    long, ev = cm.age_storage(m, 1000.0, 1000.0 + 3 * 3600, 1.0)
    assert abs(long.storage_e - 0.5) < 1e-12 and ev == {"hours": 3.0, "before": 4.0, "after": 0.5}


def test_storage_fills_while_heating():
    m = cm.track_storage(cm.Meters(), 0.0, 1800.0, 4.0, 0.0)
    assert m.storage_e == 0.0                   # no lag learned: released at once
    m = cm.track_storage(cm.Meters(), 0.0, 1800.0, 4.0, 3.0)
    assert abs(m.storage_e - 2.0 * (0.75 ** 0.5)) < 1e-12


def test_runs_and_defrosts():
    m = cm.Meters()
    t = 1_700_000_000
    for at, on in ((t - 3600, True), (t - 1800, False), (t - 600, True)):
        m = cm.track_runs(m, at, on)
    s = cm.run_stats(m.runs, t, timezone.utc)
    assert s["heating"] and s["today"]["starts"] in (1, 2)
    d = cm.track_defrost(cm.Meters(), t, True)
    d = cm.track_defrost(d, t + 60, True)
    assert d.defrost_seen == {int((t + 60) // 3600 * 3600): 60.0}


def test_the_meters_are_stored_under_their_old_keys():
    m = replace(cm.Meters(storage_e=1.23456, cost_day="d", cost_today=0.5), runs=((1, 2), (3, None)), defrost_seen={7200: 61.4})
    st = m.stored()
    assert st == {"storage_e": 1.235, "defrost_seen": {"7200": 61}, "runs": [[1, 2], [3, None]],
                  "today": {"day": "d", "cost": 0.5, "kwh": 0.0, "indoor_kwh": 0.0}}
    back = cm.Meters.restore(st)
    assert back.runs == ((1, 2), (3, None)) and back.cost_day == "d" and back.defrost_seen == {7200: 61.0}


# ------------------------------------------------------------ weather
def test_the_forecast_is_fetched_when_due_and_an_entity_adds_to_it():
    w = cw.Weather()
    assert cw.due(w, 1000.0, 1800)
    w = cw.with_forecast(w, {3600: (5.0, 0.0, 3.0)}, 1000.0, merge=False)
    assert not cw.due(w, 1000.0 + 1799, 1800) and cw.due(w, 1000.0 + 1800, 1800)
    w2 = cw.with_forecast(w, {7200: (6.0, 0.0, 3.0)}, 2000.0, merge=True)
    assert set(w2.forecast) == {3600, 7200} and set(w.forecast) == {3600}       # the old bundle unchanged
    assert set(cw.with_forecast(w2, {10800: (1, 0, 0)}, 3000.0, merge=False).forecast) == {10800}


def test_a_weather_entity_in_its_own_units():
    rows = cw.entity_rows([{"datetime": "2026-11-24T12:20:00+00:00", "temperature": 69.8, "wind_speed": 9.0,
                            "cloud_coverage": 100, "humidity": 80},
                           {"datetime": None, "temperature": 5}],
                          lambda v: None if v is None else (v - 32) * 5 / 9, lambda v: v, lambda ts: 0.8)
    (key, row), = rows.items()
    assert key % 3600 == 0 and abs(row[0] - 21.0) < 1e-9 and row[2] == 9.0 and abs(row[1] - 0.2) < 1e-9 and row[5] == 80


def test_history_is_kept_pruned_and_stored_under_its_old_key():
    w = cw.with_history(cw.Weather(), {3600: (1.0, 0.0, 2.0), 7200: (2.0, 0.0, 2.0)})
    w = cw.prune_history(w, 7200)
    assert w.stored() == {"weather": {"7200": [2.0, 0.0, 2.0]}}
    assert cw.Weather.restore(w.stored()).hist == {7200: (2.0, 0.0, 2.0)}
    w = cw.with_forecast(w, {7200: (3.0, 0.0, 2.0)}, 1.0, merge=True)
    assert cw.learning_rows(w)[7200][0] == 3.0                           # the forecast over the history


def test_clear_sky_is_zero_at_night_and_highest_at_noon():
    noon = 1_782_475_200 - 1800 + 3600 * 0     # 2026-06-26 11:30 UTC: the hour around solar noon at 0° E
    assert cw.clear_sky(noon - 12 * 3600, 52.0, timezone.utc) == 0.0
    assert cw.clear_sky(noon, 52.0, timezone.utc) > 0.75


# ------------------------------------------------------------ prices
def test_published_prices_stop_at_the_first_gap_and_keep_the_full_hour_seen():
    p0 = cp.Prices()
    p, out = cp.published(p0, "s", [None, 0.3, None, 0.5], 7200, 0.2)
    assert out == [0.2, 0.3] and p.guess["s"] == [False, False, True, False]
    assert p.seen["s"] == {10800: 0.3, 18000: 0.5} and p0.seen == {}


def test_a_flat_sensor_without_forecast_plans_on_its_price_and_a_dynamic_one_asks_for_day_ahead():
    lh = lambda ts: (ts // 3600) % 24       # noqa: E731
    p, out, nf = cp.without_forecast(cp.Prices(), "s", 0.25, 100 * 3600, 3, lh)
    assert out == [0.25] * 3 and nf.how == nf.kind
    seen = {h * 3600: 0.1 + 0.01 * (h % 13) for h in range(48, 100)}
    p, out, nf = cp.without_forecast(cp.Prices(seen={"s": seen}), "s", 0.3, 100 * 3600, 3, lh)
    if nf.kind == "dynamic":
        assert p.need_epex and nf.how == "flat" and out == [0.3] * 3


def test_seen_prices_are_pruned_and_stored_under_their_old_key():
    p = cp.seed(cp.Prices(), "s", 0, [0.1, None, 0.3], 1.0)
    assert p.seen == {"s": {0: 0.1, 7200: 0.3}}
    p = cp.prune_seen(p, 3 * 86400 + 3600)
    assert p.stored() == {"price_seen": {"s": {"7200": 0.3}}}
    assert cp.Prices.restore(p.stored()).seen == {"s": {7200: 0.3}}


def test_no_price_plans_on_the_last_one_known():
    inp, ev = cp.flat(cp.Prices(seen={"s": {0: 0.1, 3600: 0.2}}), [], 3)
    assert inp.import_price == [0.2] * 3
    assert cp.flat(cp.Prices(), [0.4], 2)[0].import_price == [0.4, 0.4]


# ------------------------------------------------------------ Weheat
def test_weheat_hours_merge_field_by_field_without_touching_the_old_bundle():
    w = cwh.Weheat(hours={1: {"q": 1.0}})
    w2 = cwh.merge(w, {1: {"sp": 20.0}, 2: {"q": 2.0}})
    assert w2.hours == {1: {"q": 1.0, "sp": 20.0}, 2: {"q": 2.0}} and w.hours == {1: {"q": 1.0}}


def test_an_import_cut_off_by_a_restart_carries_on():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 24, 10, tzinfo=timezone.utc)
    fresh = cwh.plan_import({}, {}, 60, False, now, 4)
    assert not fresh.resumed and fresh.end == now and fresh.info["months"] == 2
    cut = {"oldest": "2026-10-24T10:00:00+00:00", "from": "2026-09-25T10:00:00+00:00", "fields_reading": 4,
           "months_done": 1, "hours": 700, "to": now.isoformat()}
    on = cwh.plan_import(cut, {}, 60, False, now, 4)
    assert on.resumed and on.end.isoformat() == cut["oldest"] and on.info["months_done"] == 1
    assert not cwh.plan_import({**cut, "fields_reading": 3}, {}, 60, False, now, 4).resumed
    done = cwh.import_done(cwh.month_done(on.info, on.start, 300, "x"), 4, 4, "y", None)
    assert done["done"] and done["months"] == 2 and done["hours"] == 1000


# ------------------------------------------------------------ the plan
def test_the_plan_in_force_is_read_per_hour():
    hours = [planner.HourIn(5, 3.5, 0, 0.1, 0.1), planner.HourIn(6, 3.5, 0, 0.2, 0.2)]
    assert cpl.hour_in(7200.0, hours, 7200 + 3700) is hours[1] and cpl.hour_in(7200.0, hours, 7200 + 7300) is None
    assert cpl.hour_in(None, hours, 0) is None
    assert cpl.fallback_sp(True, True, 15.0, 20.5, 17.0) == 15.0 and cpl.fallback_sp(False, False, 15.0, 20.5, 17.0) == 17.0


def test_the_planners_hours_from_the_weather_or_the_outdoor_reading():
    from datetime import datetime, timezone
    prices = [value.HourPrices(0.3, 0.3, 0.0, "grid"), value.HourPrices(0.2, 0.2, 0.0, "grid")]
    common = dict(local=lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc), dhw_share=lambda wd, h: 0.0, dhw_top=None,
                  dhw_now=True, unit_air=None, bias=1.0, sun=lambda ts, wx: 0.0, weekly=False, is_day=lambda loc: True,
                  corr_kw=0.0, corr_slow=0.0, away=lambda ts: False)
    w = cw.with_forecast(cw.Weather(), {7200: (5.0, 0.0, 2.0)}, 7200.0, merge=False)
    hs = cpl.hours_ahead(7200, 7300.0, prices, [0.3], w, outdoor=lambda: None, **common)
    assert [h.t_out for h in hs] == [5.0, 5.0] and hs[0].dhw == 0.5 and hs[0].p_imp == 0.3 and hs[1].p_imp is None
    assert cpl.hours_ahead(7200, 7300.0, prices, [], cw.Weather(), outdoor=lambda: None, **common) == []
    assert cpl.hours_ahead(7200, 7300.0, prices, [], cw.Weather(), outdoor=lambda: 4.0, **common)[0].t_out == 3.0


# ------------------------------------------------------------ the hour log
def test_an_hour_is_counted_and_closed_into_its_entry():
    a = chl.new_hour(chl.HourAcc(), 3600)
    a = chl.track(a, 1800, 20.0, 19.5, False, 4.0, (1.0, 0.0, 0.5))
    a = chl.track(a, 1800, 21.0, None, True, None, None)
    a = chl.add_elec(a, 0.4, 0.12)
    logs = chl.Logs(hour_log=[{"ts": 3600, "T": 20.0}])
    out = chl.close_hour(logs, a, 3600, 20.3)
    e = out.hour_log[0]
    assert e["q"] == 2.0 and e["dhw"] == 0.5 and e["e"] == 0.4 and e["cost"] == 0.12 and e["obs"] == 3600 and e["sp_mean"] == 20.5
    assert (e["e_sun"], e["e_bat"], e["e_grid"]) == (0.5, 0.0, 0.25) and out.sp_hist == {3600: [20.5, 19.5]}
    assert logs.hour_log[0] == {"ts": 3600, "T": 20.0}                   # the old bundle as it was


def test_a_restart_in_a_later_hour_closes_the_old_one_as_partial():
    st = chl.HourAcc(hour=3600, elec=0.2, obs=900.0).stored(10.0, 5.0, 1.0)
    later = chl.restore_acc(st, 3 * 3600)
    assert later.close_partial == 3600 and later.meters is None
    same = chl.restore_acc(st, 3600 + 60)
    assert same.close_partial is None and same.meters == (10.0, 5.0) and same.acc.elec == 0.2


def test_comfort_advice_sums_the_last_week_with_the_settings_in_force():
    base = {"comfort": 20.0, "night_min": 18.0, "store_max": 23.0}
    wi = {"base": base, "eco_down": {"cost": -0.05, "short": 0.1}, "top_off": {"cost": 0.4, "short": 0.0}}
    stats = {f"2026-11-{d:02d}": {"what_if": wi} for d in (20, 21)}
    logs = chl.Logs(day_stats=stats)
    assert chl.comfort_advice(logs.day_stats, 20.0, 18.0, 23.0) is None          # two days: not yet
    logs = chl.with_what_if(chl.Logs(day_stats={**stats, "2026-11-22": {}}), "2026-11-22", wi)
    a = chl.comfort_advice(logs.day_stats, 20.0, 18.0, 23.0)
    assert a["days"] == 3 and a["eco_down"] == {"week": -0.35, "short": 0.7} and a["top_off"]["week"] == 2.8
    assert "eco_up" not in a                                                     # not on every day: left out
    assert chl.comfort_advice(logs.day_stats, 20.0, 17.0, 23.0) is None          # other settings now: not these days
    assert chl.with_what_if(logs, "2026-11-30", wi) is logs                      # a day without numbers: nothing


def test_the_steering_of_a_day_comes_from_its_own_hours():
    assert chl.day_steering([{"ot": {"flow": 30}}, {"ot": {"flow": 0}}]) is True
    assert chl.day_steering([{"ot": None}, {}]) is False
    assert chl.day_steering([{"ot": {"flow": 30}}, {"ot": None}]) is None      # switched during the day: no what-if


def test_a_failed_round_holds_the_plan_then_falls_back_to_the_comfort_schedule():
    h = cpl.Held(plan=object(), hours=[1], tariff=[0.3])
    h1, f = cpl.failed(h, "no_room", 1000.0, 0.0, 300, 3600, 3 * 3600)
    assert h1.fail_since == 1000.0 and h1.plan is h.plan and f.reason == "no_room" and not f.to_schedule and not f.notice
    h2, f = cpl.failed(h1, "no_room", 1000.0 + 3600, 0.0, 300, 3600, 3 * 3600)
    assert h2.plan is None and h2.hours == [] and h2.fallback == "schedule" and f.reason == "fallback_schedule" and f.to_schedule
    h3, f = cpl.failed(h2, "no_room", 1000.0 + 4 * 3600, 0.0, 300, 3600, 3 * 3600)
    assert not f.to_schedule and f.notice
    assert cpl.failed(cpl.Held(), "no_price", 100.0, 0.0, 300, 3600, 3 * 3600)[1] is None      # just started


def test_a_plan_adopted_clears_the_failure_unless_it_is_a_fallback():
    h = cpl.Held(fail_since=5.0, why="first", commit="held")
    a = cpl.adopted(h, "p", [1], 10.0, 0.0, [0.3], [], [], None, "x", None)
    assert a.plan == "p" and a.fail_since is None and a.commit == "held" and a.why == "first"
    b = cpl.adopted(h, "p", [1], 10.0, 0.0, [0.3], [], [], "new", "prices", "no_price")
    assert b.fail_since == 5.0 and b.commit == "new" and b.why == "prices" and b.fallback == "no_price"


# ------------------------------------------------------------ the card
def test_weheat_is_asked_for_the_control_method_within_its_limits():
    c = cc.CardState(method_at=1000.0, pump_st="heating")
    assert not cc.poll_due(c, 1000.0 + 200, "heating", 0.0, False, False, True)              # not yet
    assert cc.poll_due(c, 1000.0 + 200, "standby", 0.0, False, False, True)                  # the unit changed state
    assert not cc.poll_due(c, 1000.0 + 400, "heating", 1000.0 + 350, False, False, True)     # the log quota just used
    assert not cc.poll_due(c, 1000.0 + 400, "heating", 0.0, False, True, True)               # an import runs
    assert cc.poll_due(c, 1000.0 + 400, "heating", 0.0, False, False, True)


def test_the_cards_state_follows_the_unit_and_weheats_answers():
    c = cc.seen(cc.CardState(), 10.0, "heating", True)
    assert (c.pump_st, c.pump_since, c.weheat_seen) == ("heating", 10.0, 10.0)
    assert cc.seen(c, 20.0, "heating", False).pump_since == 10.0
    c = cc.login_refused(c, 30.0)
    assert cc.login_refused(c, 40.0).login_bad_since == 30.0
    assert cc.answered(c, None, "x") is c
    a = cc.answered(c, {"currentControlMethod": 4, "dhwControlMethod": 3}, "x")
    assert a.login_bad_since is None and a.weheat_now == {"method": 4, "dhw": 3, "at": "x"}


if __name__ == "__main__":
    run_all(globals())
