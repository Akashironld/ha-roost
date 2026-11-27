"""OpenTherm steering: the plan in heat levels (planner.plan_ot) and the flow asked (opentherm.py)."""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402
from test_planner_control import HOUSE, PUMP, hours  # noqa: E402

planner = load("planner")
ot = load("opentherm")

S = planner.Settings(comfort=20.5, day_min=20.0, night_min=19.0, store_max=22.5, sp_min=19.0)
CS = ot.OTSettings()
H0 = 1_700_000_000 // 3600 * 3600          # the start of an hour


# ---------------------------------------------------------------- plan
def test_levels_off_or_from_the_lowest_output():
    lv = S.levels(5.5)
    assert lv[0] == 0.0 and lv[1] == 2.8 and all(b - a == 0.5 for a, b in zip(lv[1:], lv[2:]))
    assert lv[-1] <= 5.5


def test_plan_never_between_off_and_the_lowest_output():
    for t_out in (10, 2, -6):
        p = planner.plan_ot(HOUSE, PUMP, S, hours(t_out), 20.4, 4.0, 0.0)
        assert all(x.level == 0 or x.level >= S.ot_q_min for x in p.hours), t_out
        assert all(x.level == x.sp for x in p.hours)       # the plan's value is the level (opentherm.py makes the flow)


def test_plan_keeps_the_room_and_runs_long():
    for t_out in (8, 2, -3):
        hs = hours(t_out) + hours(t_out)[:12]
        p = planner.plan_ot(HOUSE, PUMP, S, hs, 20.4, 4.0, 0.0)
        assert min(x.t_end for x in p.hours) >= S.day_min - 0.2, t_out
        lv = [x.level for x in p.hours]
        starts = sum(1 for a, b in zip([0.0] + lv, lv) if a == 0 and b > 0)
        assert starts <= 3, (t_out, lv)


def test_start_cost_makes_fewer_starts():
    hs = hours(5) + hours(5)[:12]
    cheap = planner.plan_ot(HOUSE, PUMP, replace(S, ot_start_kwh=0.0), hs, 20.4, 4.0, 0.0)
    dear = planner.plan_ot(HOUSE, PUMP, replace(S, ot_start_kwh=2.0), hs, 20.4, 4.0, 0.0)

    def starts(p):
        lv = [x.level for x in p.hours]
        return sum(1 for a, b in zip([0.0] + lv, lv) if a == 0 and b > 0)
    assert starts(dear) <= starts(cheap)


def test_start_is_counted_from_off_only():
    sim = planner.Simulator(HOUSE, PUMP, replace(S, ot=True))
    h = hours(5)[0]
    _, _, c_start, kwh_start, *_ = sim.hour(20.5, 4.0, 2.8, h, 0.0)
    _, _, c_run, kwh_run, *_ = sim.hour(20.5, 4.0, 2.8, h, 2.8)
    assert abs(kwh_start - kwh_run - S.ot_start_kwh) < 1e-9 and c_start > c_run


def test_plan_ot_compares_with_a_steady_thermostat():
    p = planner.plan_ot(HOUSE, PUMP, S, hours(2), 20.4, 4.0, 0.0)
    assert p.baseline_cost > 0 and "saving" in p.breakdown


def test_plan_ot_fixed_levels_are_worked_out():
    fixed = [2.8] * 6 + [0.0] * 18
    p = planner.plan_ot(HOUSE, PUMP, S, hours(2), 20.4, 4.0, 2.8, fixed=fixed)
    assert [x.level for x in p.hours] == fixed


def test_explain_ot_says_why():
    hs = hours(2) + hours(2)[:12]
    p = planner.plan_ot(HOUSE, PUMP, S, hs, 20.4, 4.0, 0.0)
    rs = planner.explain_hours(p, hs, 20.4, replace(S, ot=True), PUMP, HOUSE)
    assert rs and all(str(r) for r in rs)
    assert {r.code for r in rs} <= {"store_cheap", "store_ahead", "expensive", "warm_enough", "ot_below_min", "ot_low_long",
                                    "holding", "store_solar"}


def test_quiet_hours_cap_the_output():
    hs = hours(-6)
    quiet = replace(S, ot_quiet=(22, 7, 2.8))
    p = planner.plan_ot(HOUSE, PUMP, quiet, hs, 20.4, 4.0, 0.0)
    assert all(x.level <= 2.8 for x, h in zip(p.hours, hs) if h.hour >= 22 or h.hour < 7)


def test_a_limit_on_starts():
    hs = hours(6, prices=[0.10, 0.40] * 12) + hours(6)[:12]
    free = planner.plan_ot(HOUSE, PUMP, replace(S, ot_start_kwh=0.0), hs, 20.4, 4.0, 0.0)
    capped = planner.plan_ot(HOUSE, PUMP, replace(S, ot_start_kwh=0.0, ot_max_starts=2), hs, 20.4, 4.0, 0.0)
    n_free = planner.count_starts([x.level for x in free.hours])
    n_cap = planner.count_starts([x.level for x in capped.hours])
    assert n_cap <= max(2, n_free) and (n_free <= 2 or n_cap < n_free)


def test_min_run_from_the_master():
    m = ot.OTMemory()
    cs = replace(CS, min_run_s=600)
    ot.decide(H0, 3.0, 20.5, 20.0, m, cs, True)
    d = ot.decide(H0 + 700, 0.0, 20.5, 20.0, m, cs, True)
    assert d.why.code != "min_run"


def test_the_grid_search_gives_the_same_plan():
    """With numpy (Home Assistant) the search runs over the whole grid at once: the same plan, to the last digit."""
    if not planner.GRID:
        return                                   # pure Python only here: nothing to compare
    try:
        for t_out, st, ln in ((8, S, 0.0), (2, replace(S, ot_max_starts=1), 0.0), (-3, replace(S, ot_quiet=(22, 7, 2.8)), 3.3)):
            hs = hours(t_out) + hours(t_out)[:12]
            fast = planner.plan_ot(HOUSE, PUMP, st, hs, 20.4, 4.0, ln)
            planner.GRID = False
            slow = planner.plan_ot(HOUSE, PUMP, st, hs, 20.4, 4.0, ln)
            planner.GRID = True
            assert [x.level for x in fast.hours] == [x.level for x in slow.hours] and abs(fast.cost - slow.cost) < 1e-9
    finally:
        planner.GRID = True


# ---------------------------------------------------------------- flow
def test_flow_and_level_are_each_others_inverse():
    f = ot.flow_for(3.0, 20.5, 0.3, 1.1)
    assert abs(ot.level_for(f, 20.5, 0.3, 1.1) - 3.0) < 1e-9
    assert ot.flow_for(0.0, 20.5, 0.3, 1.1) == 0.0


def test_off_asks_zero_and_on_asks_a_flow_in_limits():
    m = ot.OTMemory()
    d = ot.decide(H0, 0.0, 20.5, 20.0, m, CS, True)
    assert d.flow == 0.0 and d.write                  # first write: the lease
    d = ot.decide(H0 + 3600, 4.0, 20.5, 20.0, m, CS, True)
    assert CS.min_flow <= d.flow <= CS.max_flow and d.flow > 20.5 and d.write and d.level == 4.0
    assert d.flow * 2 == int(d.flow * 2)               # steps of 0.5


def test_lease_written_again_after_four_minutes_also_when_equal():
    m = ot.OTMemory()
    d = ot.decide(H0, 3.0, 20.5, 20.0, m, CS, True)
    m.last_write = H0
    assert not ot.decide(H0 + 120, 3.0, 20.5, 20.0, m, CS, True).write
    assert ot.decide(H0 + ot.LEASE_S, 3.0, 20.5, 20.0, m, CS, True).write
    assert d.flow == m.flow


def test_shadow_never_writes_but_remembers():
    m = ot.OTMemory()
    d = ot.decide(H0, 3.0, 20.5, 20.0, m, CS, False)
    assert not d.write and d.flow > 0 and m.flow == d.flow


def test_on_and_off_at_the_turn_of_the_hour():
    m = ot.OTMemory()
    ot.decide(H0 + 60, 0.0, 20.5, 20.0, m, CS, True)          # off, going off counted in this hour? it was off already
    m.level_hour = H0 // 3600                                  # it stopped in this hour
    d = ot.decide(H0 + 600, 3.0, 20.5, 20.0, m, CS, True)
    assert d.level == 0.0 and d.why.code == "ot_wait_hour"
    d = ot.decide(H0 + 3600, 3.0, 20.5, 20.0, m, CS, True)
    assert d.level == 3.0
    # on since the turn of the hour: off waits for the minimum run, then for the next hour
    d = ot.decide(H0 + 3600 + 600, 0.0, 20.5, 20.0, m, CS, True)
    assert d.level == CS.q_min and d.why.code == "min_run"
    d = ot.decide(H0 + 3600 + 2400, 0.0, 20.5, 20.0, m, CS, True)
    assert d.level == CS.q_min and d.why.code == "ot_wait_hour"
    d = ot.decide(H0 + 7200, 0.0, 20.5, 20.0, m, CS, True)
    assert d.level == 0.0 and d.flow == 0.0


def test_urgent_start_within_the_hour():
    m = ot.OTMemory(level_hour=H0 // 3600)
    d = ot.decide(H0 + 600, 3.0, 19.5, 20.0, m, CS, True)
    assert d.level == 3.0 and d.why.code == "urgent"


def test_never_below_the_flow_of_the_lowest_output():
    m = ot.OTMemory()
    d = ot.decide(H0, 2.8, 20.5, 20.0, m, CS, True)
    low = ot.flow_for(CS.q_min, 20.5, CS.k, CS.n) + 1.0
    assert d.flow >= round(low * 2) / 2 - 0.25


def test_lowest_level_stays_with_the_flow_it_makes():
    m = ot.OTMemory()
    ot.decide(H0, 2.8, 20.5, 20.0, m, CS, True)
    for i in range(8):                                 # a round every 2 min, from 25 min after the start
        d = ot.decide(H0 + 1500 + i * 120, 2.8, 20.5, 20.0, m, CS, True, measured_kw=2.9, measured_flow=33.0, running=True)
    assert d.flow >= 32.5                              # the floor warmed: asking less would stop the unit


def test_lowest_level_does_not_follow_the_unit_speeding_up():
    # 21-11-2026 07:00: asked 33 at 30.7 made, the unit sped up on its own (to 9.7 kW) and the flow asked followed its
    # flow up to 38.5. Now: not up while it makes far more than the level
    m = ot.OTMemory()
    ot.decide(H0, 2.8, 20.9, 19.0, m, CS, True)
    m.flow = 33.0
    made = [(30.7, 3.9), (32.3, 5.0), (34.7, 8.9), (35.6, 9.5), (37.3, 9.9), (38.4, 9.7), (38.6, 9.6)]
    asked = []
    for i, (fl, kw) in enumerate(made):
        d = ot.decide(H0 + 1500 + i * 120, 2.8, 20.9, 19.0, m, CS, True, measured_kw=kw, measured_flow=fl, running=True)
        asked.append(d.flow)
    assert max(asked) <= 33.0, asked
    assert asked == sorted(asked, reverse=True), asked     # never up while it speeds up


def test_a_defrost_neither_trims_nor_learns_nor_walks_the_flow():
    # 21-11-2026 05:16: a defrost (no heat for 15 min, the flow falls to 21) on a 3.8 kW level: the trim and k pushed
    # the flow asked from 32 to 34.5. Now: held, and nothing learned until it has settled again
    m = ot.OTMemory()
    ot.decide(H0, 3.8, 20.9, 19.0, m, CS, True)
    for i in range(10):                                 # steady first: at the level
        ot.decide(H0 + 1300 + i * 120, 3.8, 20.9, 19.0, m, CS, True, measured_kw=3.8, measured_flow=m.flow, running=True)
    f0, k0, t0 = m.flow, m.k_factor, m.trim
    for i in range(8):
        d = ot.decide(H0 + 2600 + i * 120, 3.8, 20.9, 19.0, m, CS, True, measured_kw=0.0, measured_flow=27 - i, running=True)
        assert d.flow <= f0
    assert m.k_factor == k0 and m.trim == t0
    m2 = ot.OTMemory()
    ot.decide(H0, 2.8, 20.9, 19.0, m2, CS, True)
    m2.flow = 31.0
    for i in range(8):
        d = ot.decide(H0 + 2600 + i * 120, 2.8, 20.9, 19.0, m2, CS, True, measured_kw=0.0, measured_flow=27 - i, running=True)
        assert d.flow == 31.0, d.flow                   # the lowest level does not walk down with a defrost


def test_trim_does_not_wind_up_while_the_unit_lags():
    # the unit makes a bit less than the level but has not reached the flow asked: no further up
    m = ot.OTMemory()
    ot.decide(H0, 3.8, 20.9, 19.0, m, CS, True)
    f0 = m.flow
    for i in range(6):
        ot.decide(H0 + 1300 + i * 600, 3.8, 20.9, 19.0, m, CS, True, measured_kw=3.3, measured_flow=f0 - 1.5, running=True)
    assert m.trim == 0.0 and m.flow <= f0
    # once it has (the flow made at the flow asked) and still too little heat: up
    for i in range(3):
        ot.decide(H0 + 5000 + i * 600, 3.8, 20.9, 19.0, m, CS, True, measured_kw=3.3, measured_flow=m.flow, running=True)
    assert m.trim > 0.0


def test_max_flow_of_the_pump_holds():
    m = ot.OTMemory()
    d = ot.decide(H0, 9.0, 20.5, 20.0, m, replace(CS, max_flow=45.0), True, pump_max_flow=40.0)
    assert d.flow == 40.0


def test_heat_feedback_trims_and_learns_k():
    m = ot.OTMemory()
    ot.decide(H0, 4.0, 20.5, 20.0, m, CS, True)
    f0 = m.flow
    # too much heat after the start peak: the flow goes down by a step, at most every 10 min
    d = ot.decide(H0 + 1300, 4.0, 20.5, 20.0, m, CS, True, measured_kw=5.0, measured_flow=f0, running=True)
    assert m.trim == -0.5 and m.k_factor > 1.0
    ot.decide(H0 + 1400, 4.0, 20.5, 20.0, m, CS, True, measured_kw=5.0, measured_flow=f0, running=True)
    assert m.trim == -0.5
    for i in range(20):
        ot.decide(H0 + 2000 + i * 600, 4.0, 20.5, 20.0, m, CS, True, measured_kw=5.0, measured_flow=f0, running=True)
    assert m.trim >= -ot.TRIM_MAX and d.flow <= f0
    # within the start peak: nothing
    m2 = ot.OTMemory()
    ot.decide(H0, 4.0, 20.5, 20.0, m2, CS, True)
    ot.decide(H0 + 300, 4.0, 20.5, 20.0, m2, CS, True, measured_kw=6.0, measured_flow=f0, running=True)
    assert m2.trim == 0.0 and m2.k_factor == 1.0


def test_pause_writes_nothing():
    m = ot.OTMemory()
    d = ot.decide(H0, 3.0, 20.5, 20.0, m, CS, True, paused_min=90)
    assert not d.write and d.why.code == "paused"


def test_no_plan_keeps_the_lease_for_an_hour_then_lets_the_master_take_over():
    m = ot.OTMemory(level=3.0, flow=30.0, ok_at=H0)
    d = ot.decide(H0 + 600, None, 20.5, 20.0, m, CS, True)
    assert d.write and d.flow == 30.0
    m.last_write = H0 + 600
    assert not ot.decide(H0 + ot.NO_PLAN_S + 60, None, 20.5, 20.0, m, CS, True).write
    assert not ot.decide(H0 + ot.NO_PLAN_S + 60, 3.0, None, 20.0, m, CS, True).write


def test_below_the_hard_minimum_heats_whatever_the_plan_says():
    m = ot.OTMemory(level_hour=H0 // 3600)
    d = ot.decide(H0 + 600, 0.0, 19.5, 20.0, m, CS, True)
    assert d.level == CS.q_min and d.flow > 0 and d.why.code == "urgent"
    m2 = ot.OTMemory()
    assert ot.decide(H0 + 600, None, 19.5, 20.0, m2, CS, True).level == CS.q_min


def test_lowest_level_does_not_walk_down_with_its_reading():
    m = ot.OTMemory()
    ot.decide(H0, 2.8, 20.5, 20.0, m, CS, True)
    flows = []
    for i in range(30):                    # a reading that follows the request down, every 2 min for an hour
        t = H0 + 1300 + i * 120
        d = ot.decide(t, 2.8, 20.5, 20.0, m, CS, True, measured_kw=2.8, measured_flow=m.flow, running=True)
        flows.append(d.flow)
    low = ot.flow_for(ot.LOW_FLOOR * CS.q_min, 20.5, CS.k, CS.n)
    assert min(flows) >= round(low * 2) / 2 - 0.5
    drops = sum(1 for a, b in zip(flows, flows[1:]) if b < a)
    assert drops <= 6                      # one step per 10 min at most


def test_take_over_from_a_running_unit_keeps_it_running():
    # 21-11-2026 08:58: the shadow had the hour off while the curve ran the unit; Roost wrote 0 at once and the master
    # kept it off for an hour. Now: a running unit counts as just started, so the plan's "off" waits for the min run
    m = ot.OTMemory(level=0.0, flow=0.0, level_hour=H0 // 3600)
    ot.take_over(H0 + 3480, m, True, CS, flow_now=30.4)
    assert m.level == CS.q_min and m.on_since == H0 + 3480 and m.flow == 30.5
    d = ot.decide(H0 + 3480, 0.0, 21.0, 19.0, m, CS, True, measured_kw=2.5, measured_flow=30.4, running=True)
    assert d.flow > 0 and d.why.code in ("min_run", "ot_wait_hour")
    d = ot.decide(H0 + 3600 + 120, 2.4, 21.0, 19.0, m, CS, True, measured_kw=2.5, measured_flow=30.4, running=True)
    assert d.flow > 0                                   # the next hour heats: it never stopped
    m2 = ot.OTMemory(level=2.8, flow=30.0, on_since=H0)
    ot.take_over(H0 + 600, m2, False, CS)
    assert m2.level == 0.0 and m2.flow == 0.0 and m2.on_since is None


def test_hot_water_hour_costs_at_the_level_it_runs():
    # hot water takes 60 % of the hour: 6 kW in the rest is the same heat as 2.4 kW all hour, but at 6 kW's COP
    # (21-11-2026: the plan put 7.4 kW = 40 °C in the Saturday hot-water hour, costed as 2.7 kW at a low-speed COP)
    sim = planner.Simulator(HOUSE, PUMP, replace(S, ot=True))
    h = hours(3)[4]
    _, _, _, e_dhw, q_dhw, _ = sim.hour(20.5, 3.0, 6.0, replace(h, dhw=0.6), 6.0)
    _, _, _, e_low, q_low, _ = sim.hour(20.5, 3.0, 2.4, h, 2.4)
    assert abs(q_dhw - q_low) < 1e-6
    assert e_dhw > e_low * 1.2, (e_dhw, e_low)
    # the grid search (numpy) costs it the same way
    import numpy as np
    _, _, c_grid = planner.hour_grid(sim, np.array([20.5]), np.array([3.0]), 6.0, replace(h, dhw=0.6))
    c_one = sim.hour(20.5, 3.0, 6.0, replace(h, dhw=0.6), None)
    assert abs(float(c_grid[0]) - (c_one[2] + c_one[5])) < 1e-9


def test_no_stop_for_the_rest_of_an_hour_when_the_next_heats():
    # 21-11-2026 10:56: a new plan had the last minutes of the hour off and 3.4 kW the next; Roost wrote 0 at 10:58 and
    # the master's minimum off time kept it off till 11:59. Now it runs on at the lowest output
    m = ot.OTMemory(level=3.4, flow=31.5, level_hour=H0 // 3600 - 2, on_since=H0 - 7200)
    d = ot.decide(H0 + 3480, 0.0, 21.7, 19.0, m, CS, True, measured_kw=3.4, measured_flow=31.5, running=True, next_level=3.4)
    assert d.flow > 0 and d.level == CS.q_min and d.why.code == "ot_bridge"
    d = ot.decide(H0 + 3600 + 120, 3.4, 21.7, 19.0, m, CS, True, measured_kw=2.8, measured_flow=31.0, running=True,
                  next_level=3.4)
    assert d.flow > 0 and d.level == 3.4                 # and on with the next hour's level
    # off for the next hour too: a real stop, at once (no need to wait for the hour)
    m2 = ot.OTMemory(level=3.4, flow=31.5, level_hour=H0 // 3600 - 2, on_since=H0 - 7200)
    assert ot.decide(H0 + 1200, 0.0, 21.7, 19.0, m2, CS, True, measured_kw=3.4, measured_flow=31.5, running=True,
                     next_level=0.0).flow == 0.0
    # not known (a window open, or the plan ends): off as planned
    m3 = ot.OTMemory(level=3.4, flow=31.5, level_hour=H0 // 3600 - 2, on_since=H0 - 7200)
    assert ot.decide(H0 + 1200, 0.0, 21.7, 19.0, m3, CS, True, running=True, next_level=None).flow == 0.0


def test_watch_after_grace():
    m = ot.OTMemory()
    assert ot.watch(H0, "home_assistant", "home_assistant", True, m) is None
    assert ot.watch(H0, "curve_no_command", "home_assistant", True, m) is None
    assert ot.watch(H0 + 300, "curve_no_command", "home_assistant", True, m) == "curve_no_command"
    assert ot.watch(H0 + 400, None, "home_assistant", True, m) == "unavailable"
    assert ot.watch(H0 + 500, "curve", "home_assistant", False, m) is None and m.bad_since is None


def test_memory_round_trip():
    m = ot.OTMemory(level=2.8, flow=31.0, k_factor=1.1)
    assert ot.OTMemory.from_dict(m.as_dict()) == m


# ---------------------------------------------------------------- learned from the unit
otlearn = load("otlearn")
heatpump = load("heatpump")


def _runs(q=2.2, k=0.25, n=1.1, cop=5.0, start_extra=0.3, runs=4, hours_each=6, t_out=5.0, room=20.5):
    """Samples every 10 min of runs of a unit with these true properties."""
    obs, ts = [], H0
    for _r in range(runs):
        for i in range(hours_each * 6):
            run_min = i * 10.0
            p_in = q / cop + (start_extra / (2 * 10 / 60) if run_min < 20 else 0.0)
            flow = room + (q / k) ** (1 / n)
            obs.append(otlearn.sample(ts, q, p_in, flow, room, t_out, run_min, flow))
            ts += 600
        ts += 4 * 3600
    return obs


def test_learns_lowest_output_emitter_and_start_cost():
    hp = heatpump.HeatPumpModel.for_profile("p80")
    L = otlearn.learn(_runs(runs=8), [[H0, H0 + 3600, True]] * 3, hp, 1.1)
    assert abs(L.q_min - 2.2) < 0.01 and abs(L.k - 0.25) < 0.005
    assert abs(L.start_kwh - 0.3) < 0.05 and L.starts == 8 and L.rest_min == 60
    assert L.cop_low is None                  # no longer learned (selection bias): the planner keeps its fixed value
    # from 4 starts the start cost is not learned yet (the setting stays): a few starts swing too much
    L4 = otlearn.learn(_runs(runs=4), [[H0, H0 + 3600, True]] * 3, hp, 1.1)
    assert L4.start_kwh is None and L4.starts == 4 and L4.rest_min == 60


def test_too_little_data_keeps_the_settings():
    hp = heatpump.HeatPumpModel.for_profile("p80")
    L = otlearn.learn(_runs(runs=1, hours_each=2), [], hp, 1.1)
    assert L.q_min is None and L.k is None and L.start_kwh is None and L.rest_min is None


def test_sample_needs_heat_and_electricity():
    assert otlearn.sample(H0, 0.0, 0.5, 30, 20, 5, 30, 30) is None
    assert otlearn.sample(H0, 3.0, None, 30, 20, 5, 30, 30) is None
    assert otlearn.OTLearned.from_dict(otlearn.OTLearned(q_min=2.0).as_dict()).q_min == 2.0


def test_learns_the_emitter_exponent_when_the_flow_varies():
    hp = heatpump.HeatPumpModel.for_profile("p80")
    obs, ts = [], H0
    for i in range(200):                          # outputs from 2 to 5 kW on a fan coil (n 1.0, k 0.4)
        q = 2.0 + 3.0 * (i % 20) / 19
        flow = 20.5 + (q / 0.4) ** (1 / 1.0)
        obs.append(otlearn.sample(ts, q, q / 4.5, flow, 20.5, 5.0, 60.0, flow))
        ts += 600
    L = otlearn.learn(obs, [], hp, 1.3)           # ticked as radiators (1.3): corrects itself
    assert abs(L.n - 1.0) < 0.02 and abs(L.k - 0.4) < 0.01
    same = otlearn.learn(_runs(), [], hp, 1.1)    # one output only: n cannot be told, k with the n given
    assert same.n is None and abs(same.k - 0.25) < 0.005


def test_emitter_ticks():
    curve = load("curve")
    assert curve.emitter_profile({"emitter": "radiators"})[:2] == ("radiators", 1.3)
    assert curve.emitter_profile({"emitter": "both"})[0] == "both"
    start, n, cop, floor = curve.emitter_profile({"emitters": ["floor", "fan_coils"]})
    assert start == "both" and n == 1.05 and cop == -0.15 and floor
    assert curve.emitter_ticks({"emitter": "both"}) == ["floor", "radiators"] and curve.emitter_ticks({}) == ["floor"]



def test_indoor_unit_running_cost_counts_in_the_plan():
    # the indoor unit's pumps are outside the COP: each quarter the unit heats costs ot_run_kw more, in both searches
    import numpy as np
    h = replace(hours(3)[4], t_out=8.0)             # mild: the pump only runs when the unit heats
    base = planner.Simulator(HOUSE, PUMP, replace(S, ot=True))
    more = planner.Simulator(HOUSE, PUMP, replace(S, ot=True, ot_run_kw=0.06))
    _, _, c0, e0, q0, _ = base.hour(20.5, 3.0, 2.8, h, 2.8)
    _, _, c1, e1, q1, _ = more.hour(20.5, 3.0, 2.8, h, 2.8)
    assert abs(q0 - q1) < 1e-9 and abs((e1 - e0) - 0.06) < 1e-9 and c1 > c0
    _, _, _, e_off, _, _ = more.hour(20.5, 3.0, 0.0, h, 0.0)
    _, _, _, e_off0, _, _ = base.hour(20.5, 3.0, 0.0, h, 0.0)
    assert e_off == e_off0 == 0.0                # off: nothing extra
    cold = replace(h, t_out=1.0)                 # below 5 °C the pump runs against frost anyway: nothing extra either
    assert abs(base.hour(20.5, 3.0, 2.8, cold, 2.8)[3] - more.hour(20.5, 3.0, 2.8, cold, 2.8)[3]) < 1e-9
    hd = replace(h, dhw=0.5)
    _, _, c_grid = planner.hour_grid(more, np.array([20.5]), np.array([3.0]), 2.8, hd)
    c_one = more.hour(20.5, 3.0, 2.8, hd, None)
    assert abs(float(c_grid[0]) - (c_one[2] + c_one[5])) < 1e-9


def test_indoor_unit_idle_and_running_power_from_its_meter():
    model = load("model")
    rows = []
    for i in range(150):
        f = (i % 5) / 4                                     # 0, .25, .5, .75, 1 of the hour heating
        rows.append(model.HourRow(ts=H0 + i * 3600, T=20.5, T_out=8.0, Q=2.6 * f, E=0.5 * f, heating_s=3600 * f,
                                  Ei=0.055 + 0.057 * f))
    for i in range(30):                                     # cold idle hours: the pump runs against frost, left out
        rows.append(model.HourRow(ts=H0 + i * 3600, T=20.5, T_out=1.0, Q=0.0, E=0.0, Ei=0.108))
    rows.append(model.HourRow(ts=H0, T=20.5, T_out=5.0, Q=2.0, E=0.4, Ei=0.3))          # heat, seconds unknown: left out
    rows.append(model.HourRow(ts=H0, T=20.5, T_out=5.0, Q=0.0, E=0.0, dhw_s=1800, Ei=0.4))  # hot water: left out
    idle, run = heatpump.learn_indoor(rows)
    assert abs(idle - 0.055) < 0.002 and abs(run - 0.057) < 0.002
    assert heatpump.learn_indoor(rows[:40]) == (None, None)             # too few hours
    assert heatpump.learn_indoor([r for r in rows if r.T_out < 5]) == (None, None)
    # no sensor reading: the forecast plus the bias decides whether the pump ran against frost
    assert heatpump.learn_indoor(rows, bias=-3.0) == (None, None)            # 8 °C forecast = 5 °C at the unit: left out

if __name__ == "__main__":
    run_all(globals())
