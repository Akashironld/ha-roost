"""Planner, control and the energy value for the planner."""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

model = load("model")
heatpump = load("heatpump")
planner = load("planner")
control = load("control")
value = load("value")
series = load("series")

HOUSE = model.HouseModel(C=19.1, H=0.122, g=5.8, lag=0.98, internal=-0.02, Hw=0.0073, source="learned")
PUMP = heatpump.HeatPumpModel.for_profile("p80")
PRICES = [0.30, 0.27, 0.25, 0.24, 0.25, 0.28, 0.33, 0.38, 0.45, 0.49, 0.46, 0.40, 0.36, 0.33, 0.30, 0.28, 0.27, 0.27, 0.28, 0.30,
          0.31, 0.33, 0.35, 0.33]                     # from 08:00: cheap midday, expensive 16–19 h


def hours(t_out, prices=PRICES, start=8, own=None):
    out = []
    for i, p in enumerate(prices):
        h = (start + i) % 24
        rad = max(0.0, 0.5 * math.sin((h - 7) / 11 * math.pi)) if 7 <= h <= 18 else 0.0
        out.append(planner.HourIn(t_out=t_out, wind=4, rad=rad, p_grid=p, p_own=0.05, own_kw=(own[i] if own else 0.0),
                                  day=7 <= h < 22, hour=h))
    return out


def test_cold_day_stores_heat_before_expensive_evening():
    s = planner.Settings()
    p = planner.plan(HOUSE, PUMP, s, hours(0), t_now=20.6, e_now=2.0, sp_now=20.5)
    midday = [h.sp for h in p.hours[2:8]]          # 10–16 h
    assert max(midday) > s.comfort, [h.sp for h in p.hours]
    assert p.cost < p.baseline_cost and p.saving > 0.2, (p.cost, p.baseline_cost, p.saving)
    assert p.min_day >= s.day_min - 0.05


def test_mild_day_does_nothing_special():
    p = planner.plan(HOUSE, PUMP, planner.Settings(), hours(12), t_now=21.0, e_now=0.0, sp_now=20.5)
    assert abs(p.cost - p.baseline_cost) < 0.15 and p.kwh < 4


def test_never_far_above_the_room_and_never_too_cold():
    s = planner.Settings()
    T = 19.6
    p = planner.plan(HOUSE, PUMP, s, hours(-3), t_now=T, e_now=0.0, sp_now=19.5)
    assert p.first.sp <= T + s.max_above_room + 1e-9 or p.first.sp <= s.day_min
    later = [h.t_end for h, x in zip(p.hours[3:], hours(-3)[3:]) if x.day]       # the floor needs an hour or two to respond
    assert min(later) >= s.day_min - 0.1, [round(h.t_end, 1) for h in p.hours]


def test_own_solar_is_used_for_storing():
    s = planner.Settings()
    own = [0, 0, 3, 3, 3, 3, 0, 0] + [0] * 16
    flat = [0.30] * 24
    p_sun = planner.plan(HOUSE, PUMP, s, hours(5, flat, own=own), t_now=20.6, e_now=1.0, sp_now=20.5)
    p_none = planner.plan(HOUSE, PUMP, s, hours(5, flat), t_now=20.6, e_now=1.0, sp_now=20.5)
    assert sum(h.kwh for h in p_sun.hours[2:6]) > sum(h.kwh for h in p_none.hours[2:6]) + 0.3


def test_store_max_equal_to_comfort_switches_storing_off():
    s = planner.Settings(store_max=20.5)
    p = planner.plan(HOUSE, PUMP, s, hours(0), t_now=20.6, e_now=2.0, sp_now=20.5)
    assert max(h.sp for h in p.hours) <= 20.5


def test_planner_is_fast_enough():
    t0 = time.time()
    planner.plan(HOUSE, PUMP, planner.Settings(), hours(0), t_now=20.6, e_now=2.0, sp_now=20.5)
    dt = time.time() - t0
    assert dt < 5.0, dt
    print(f"      (24 h plan in {dt:.2f} s)")


def test_replay_day_saving():
    s = planner.Settings()
    hs = hours(0)
    p = planner.plan(HOUSE, PUMP, s, hs, t_now=20.6, e_now=2.0, sp_now=20.5)
    entries = [{"T": 20.6 if i == 0 else 0, "E": 2.0, "sp": h.sp, "t_out": x.t_out, "rad": x.rad, "wind": x.wind, "p_grid": x.p_grid,
                "p_own": x.p_own, "own": x.own_kw, "day": x.day} for i, (h, x) in enumerate(zip(p.hours, hs))]
    roost, steady = planner.replay_day(HOUSE, PUMP, s, entries)
    assert steady - roost > 0.2, (roost, steady)


# ---------------------------------------------------------------- control

CS = control.ControlSettings()
NOW = 1_800_000_000.0


def test_control_sends_once_and_waits():
    mem = control.ControlMemory()
    d = control.decide(NOW, 21.0, 20.5, 20.6, 20.0, mem, CS, True)
    assert d.setpoint == 21.0
    d = control.decide(NOW + 600, 20.0, 21.0, 20.8, 20.0, mem, CS, True)
    assert d.setpoint is None and "next change" in d.reason
    assert d.why.code == "wait" and d.why.args == {"min": 50}       # code + values for the card's own language
    d = control.decide(NOW + 3700, 20.0, 21.0, 20.8, 20.0, mem, CS, True)
    assert d.setpoint == 20.0


def test_control_tolerance_pause_and_urgent():
    mem = control.ControlMemory()
    assert control.decide(NOW, 20.6, 20.5, 20.6, 20.0, mem, CS, True).setpoint is None
    mem.pause_until = NOW + 3600
    assert control.decide(NOW, 22.0, 20.5, 20.6, 20.0, mem, CS, True).setpoint is None
    mem = control.ControlMemory(last_write=NOW - 60)
    d = control.decide(NOW, 20.5, 19.5, 19.4, 20.0, mem, CS, True)
    assert d.setpoint == 20.5 and "minimum" in d.reason and d.why.code == "urgent"


def test_control_shadow_keeps_virtual_setpoint():
    mem = control.ControlMemory()
    d = control.decide(NOW, 21.0, 20.5, 20.6, 20.0, mem, CS, False)
    assert d.setpoint == 21.0 and mem.virtual_sp == 21.0
    d = control.decide(NOW + 4000, 21.0, 20.5, 20.6, 20.0, mem, CS, False)
    assert d.setpoint is None                      # virtually already on 21


# ---------------------------------------------------------------- energy value for the planner

def test_battery_selling_is_not_solar():
    assert value.solar_export_now(grid_kw=-7.9, battery_kw=10.1, pv_kw=0.23) == 0.0
    assert abs(value.solar_export_now(grid_kw=-2.0, battery_kw=0.0, pv_kw=3.0) - 2.0) < 1e-9
    assert abs(value.solar_export_now(grid_kw=-2.0, battery_kw=0.5, pv_kw=3.0) - 1.5) < 1e-9
    assert abs(value.solar_export_now(grid_kw=2.0, battery_kw=None, pv_kw=None, import_positive=False) - 2.0) < 1e-9


def test_planner_prices_split():
    inp = value.EnergyInputs(import_price=[0.30] * 4, export_price=[0.05] * 4, pv_kwh=[0, 3, 0, 0], load_kwh=[0.4] * 4)
    ev = value.compute(inp)
    pr = value.planner_prices(inp, ev)
    assert pr[1].own_kw > 2 and pr[1].p_own == 0.05 and pr[1].p_grid == 0.30
    assert pr[0].own_kw == 0 and pr[0].p_grid == 0.30



def test_price_gaps_filled_with_the_day_before():
    # forecast until midnight (3 hours known), tomorrow's prices not published yet
    start = 1_800_000_000 - 1_800_000_000 % 3600
    vals = [0.25, 0.46, 0.37, None, None, None]
    seen = {start + 3 * 3600 - 86400: 0.22, start + 5 * 3600 - 2 * 86400: 0.20}
    out, guess = series.fill_gaps(vals, start, seen)
    assert out == [0.25, 0.46, 0.37, 0.22, 0.37, 0.20]   # a day earlier, nothing known (last value), two days earlier
    assert guess == [False, False, False, True, True, True]


def test_slots_from_state_changes():
    sl = series.slots_from_changes([(7200, 0.3), (0, 0.2)], 10800)
    assert sl == [(0, 7200, 0.2), (7200, 10800, 0.3)]
    assert series.hourly(sl, 0, 3, fill_last=False) == [0.2, 0.2, 0.3]



def test_fixed_contract_prices():
    hours = [(0, 22), (0, 23), (1, 3), (1, 7), (5, 12), (6, 18)]       # Monday 22/23 h, Tuesday 3/7 h, Saturday, Sunday
    assert value.fixed_prices(hours, 0.30, 0.25) == [0.30, 0.25, 0.25, 0.30, 0.25, 0.25]
    assert value.fixed_prices(hours, 0.30, 0.25, low_weekend=False) == [0.30, 0.25, 0.25, 0.30, 0.30, 0.30]
    assert value.fixed_prices(hours, 0.30, 0.25, low_from=1, low_to=6, low_weekend=False) == [0.30, 0.30, 0.25, 0.30, 0.30, 0.30]
    assert value.fixed_prices(hours, 0.28) == [0.28] * 6               # single rate



def test_reasons_follow_the_heat_emitter():
    s = planner.Settings(comfort=20.5)
    hours = [planner.HourIn(t_out=2.0, wind=3.5, rad=0.0, p_grid=0.50 if i < 3 else 0.25, p_own=0.25) for i in range(12)]
    p = planner.Plan([planner.HourPlan(19.0, 20.6, 0.1, 0.4, 0.05, 0.5)], 0, 0, 0, 0, 0, None)
    assert planner.explain(p, hours, 20.8, s).code == "expensive"
    assert planner.explain(p, hours, 20.8, s, floor=False).code == "expensive_house"



def test_a_warm_room_is_not_storing():
    """Evening, battery power counts as own, the room at 24.3 °C and the thermostat at 21: no heat goes in, so the
    reason is 'warm enough', not 'charging the floor'."""
    s = planner.Settings(comfort=20.5)
    hours = [planner.HourIn(t_out=14.0, wind=3.5, rad=0.0, p_grid=0.34, p_own=0.30, own_kw=2.0) for _ in range(12)]
    p = planner.Plan([planner.HourPlan(21.0, 23.5, 0.0, 0.0, 0.0, 0.34)], 0, 0, 0, 0, 0, None)
    r = planner.explain(p, hours, 24.3, s)
    assert r.code == "warm_enough" and r.args["room"] == 24.3, r
    p = planner.Plan([planner.HourPlan(21.0, 20.9, 0.6, 2.4, 0.1, 0.34)], 0, 0, 0, 0, 0, None)
    assert planner.explain(p, hours, 20.4, s).code == "store_solar"          # heat going in: it is storing

if __name__ == "__main__":
    run_all(dict(globals()))
