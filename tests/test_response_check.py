"""Response to the thermostat, hot water profile, self-check and the correction from the last hours."""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

model = load("model")
heatpump = load("heatpump")
planner = load("planner")
response = load("response")
check = load("check")

DAY0 = 20_000
HOUSE = model.HouseModel(C=19.0, H=0.125, g=5.5, lag=1.0, internal=-0.05, Hw=0.007, source="learned")


def simulate(hp, days=30, seed=5, house=HOUSE):
    """Hourly rows of a house driven by a thermostat with the given response: day 20.5 °C, night 19 °C, and now and
    then a different setpoint, as someone (or a planner) would set. Rows hold hourly means, like the Weheat logs."""
    rnd = random.Random(seed)
    sim = planner.Simulator(house, hp, planner.Settings())
    rows, T, E, w = [], 20.0, 0.0, 1.0
    for d in range(days):
        for h in range(24):
            sp = 20.5 if 7 <= h < 22 else 19.0
            if rnd.random() < 0.15:
                sp += rnd.choice((-1.0, -0.5, 0.5, 1.0))
            t_out = 4 + 4 * math.sin((h - 9) / 24 * 2 * math.pi) + rnd.uniform(-1, 1)
            rad = max(0.0, 0.35 * math.sin((h - 7) / 11 * math.pi)) if 7 <= h <= 18 else 0.0
            wind = 3.5 + rnd.uniform(-2, 3)
            hin = planner.HourIn(t_out=t_out, wind=wind, rad=rad, p_grid=0.0, p_own=0.0)
            T1, E1, _c, e, q, _p = sim.hour(T, E, sp, hin, w)
            w = sim.w_end
            rows.append(model.HourRow(ts=(DAY0 + d) * 86400 + h * 3600, T=(T + T1) / 2, T_out=t_out, Q=q, rad=rad, wind=wind, E=e,
                                      T_out_sensor=t_out + 1.0, heating_s=3600.0 if q > 0.3 else 0.0, sp=sp,
                                      T_th=(T + T1) / 2 + hp.th_diff, room_sensor=True))
            T, E = T1, E1
    return rows


def true_pump():
    """Like the author's Lyric T6 (OpenTherm) on a Blackbird P80: modulating, about 1 kW per degree, slow."""
    hp = heatpump.HeatPumpModel()
    hp.a, hp.k, hp.offset, hp.follow, hp.th_diff = 0.9, 1.0, 0.4, 0.35, -0.8
    return hp


def test_response_learned_from_setpoints_and_heat():
    rows = simulate(true_pump())
    m, note = response.learn(rows, HOUSE, heatpump.HeatPumpModel())
    assert m.resp_source == "learned", note
    assert m.th_diff == -0.8, note
    assert abs(m.k - 1.0) <= 0.5 and abs(m.offset - 0.4) <= 0.3 and 0.25 <= m.follow <= 0.5 and abs(m.a - 0.9) <= 0.15, note
    assert m.resp_error is not None and m.resp_error < 0.1, m.resp_error


def test_response_leaves_the_cop_alone():
    hp = heatpump.HeatPumpModel()
    before = hp.cop(3.0, 2.0)
    m, _ = response.learn(simulate(true_pump()), HOUSE, hp)
    assert m.cop(3.0, 2.0) == before and m.alpha == hp.alpha          # alpha is the COP's, the delay is `follow`


def test_response_skips_days_without_heating():
    rows = simulate(true_pump(), days=20)
    for r in rows[-10 * 24:]:                    # heating switched off for the last ten days (summer)
        r.Q, r.E, r.heating_s = 0.0, 0.0, 0.0
    m, note = response.learn(rows, HOUSE, heatpump.HeatPumpModel())
    assert m.resp_source == "learned" and m.k >= 0.5, note


def test_a_heat_pump_on_its_own_curve_has_no_lever():
    hp = true_pump()
    hp.k = 0.0                                   # the setpoint does nothing (heating curve)
    m, note = response.learn(simulate(hp), HOUSE, heatpump.HeatPumpModel())
    assert m.resp_source == "learned" and m.k < 0.2, note
    assert check.readiness({"heating_hours": 100, "rmse_6h": 0.2, "heat_ratio": 1.0}, True, lever=False) == (False, ["lever"])


def test_response_needs_hours_with_a_setpoint():
    rows = simulate(true_pump(), days=2)
    for r in rows:
        r.sp = None
    m, note = response.learn(rows, HOUSE, heatpump.HeatPumpModel())
    assert m.resp_source == "default" and "usable windows" in note


def test_hot_water_blocks_space_heating():
    hp = heatpump.HeatPumpModel()
    sim = planner.Simulator(HOUSE, hp, planner.Settings())
    cold = dict(t_out=-5.0, wind=3.5, rad=0.0, p_grid=0.3, p_own=0.3)
    q_free = sim.hour(18.0, 0.0, 21.0, planner.HourIn(**cold))[4]
    q_dhw = sim.hour(18.0, 0.0, 21.0, planner.HourIn(**cold, dhw=0.75))[4]
    assert q_dhw < q_free * 0.4, (q_free, q_dhw)


def test_cycling_costs_more_per_kwh():
    hp = heatpump.HeatPumpModel()
    sim = planner.Simulator(HOUSE, hp, planner.Settings())
    mild = planner.HourIn(t_out=14.0, wind=3.5, rad=0.0, p_grid=0.3, p_own=0.3)
    _T, _E, c1, e1, q1, _ = sim.hour(20.4, 0.0, 20.5, mild)
    hp.q_min, hp.cyc = 4.0, 0.7
    _T, _E, c2, e2, q2, _ = sim.hour(20.4, 0.0, 20.5, mild)
    assert abs(q1 - q2) < 1e-9 and q1 > 0 and e2 > e1 * 1.3


def test_hot_water_profile():
    samples = []
    for week in range(4):
        for wd in range(7):
            for h in range(24):
                share = 0.75 if h == 13 else (1.0 if (wd == 6 and h == 12) else 0.0)
                samples.append((wd, h, share))
    prof = response.dhw_profile(samples)
    assert len(prof) == 168 and prof[13] == 0.75 and prof[6 * 24 + 12] == 1.0 and prof[12] == 0.0
    assert response.dhw_profile(samples[:100]) is None
    hp = heatpump.HeatPumpModel(dhw=prof)
    assert hp.dhw_share(6, 12) == 1.0 and hp.dhw_share(2, 3) == 0.0


def test_self_check_and_readiness():
    hp = true_pump()
    rows = simulate(hp, days=12)
    good = check.self_check(rows, HOUSE, hp)
    assert good["rmse_1h"] < 0.05 and good["rmse_6h"] < 0.1 and abs(good["heat_ratio"] - 1) < 0.05, good
    ready, missing = check.readiness(good, True)
    assert ready and not missing
    wrong = model.HouseModel.from_dict({**HOUSE.as_dict(), "H": 0.25})        # twice the heat loss
    bad = check.self_check(rows, wrong, hp)
    assert bad["rmse_6h"] > good["rmse_6h"] * 3 and bad["heat_ratio"] > 1.3, bad
    assert check.readiness(good, False) == (False, ["following"])
    assert "heat" in check.readiness(bad, True)[1]


def test_correction_from_the_last_hours():
    hp = heatpump.HeatPumpModel()
    sim = planner.Simulator(HOUSE, hp, planner.Settings())
    t0 = 1_800_000_000 - 1_800_000_000 % 3600
    entries, T, E = [], 21.0, 0.5
    for k in range(6):
        h = planner.HourIn(t_out=12.0, wind=3.5, rad=0.0, p_grid=0.0, p_own=0.0)
        T1, E1, *_ = sim.hour(T, E, 20.5, h)
        entries.append({"ts": t0 + k * 3600, "T": T, "E": E, "sp_t": 20.5, "t_out": 12.0, "wind": 3.5, "rad": 0.0, "dhw": 0.0})
        T, E = T1 + 0.02, E1                     # the room ends each hour 0.02 °C warmer than the model says
    entries.append({"ts": t0 + 6 * 3600, "T": T, "E": E, "sp_t": 20.5, "t_out": 12.0})
    kw, n = check.correction(entries, HOUSE, hp, t0 + 6 * 3600)
    assert n == 6 and 0.25 < kw < 0.4, (kw, n)  # 0.02 °C × 19 kWh/K = 0.38 kW, shrunk a little for 6 hours
    assert check.fade(kw, 6) == kw / 2
    for e in entries:
        e.pop("dhw", None)                       # hot water unknown: no correction
    assert check.correction(entries, HOUSE, hp, t0 + 6 * 3600) == (0.0, 0)



def test_slow_unit_plan_beats_a_steady_thermostat():
    """A modulating unit that follows slowly: the plan (search + polish with the real delay) costs less than holding the
    comfort temperature, keeps the room within comfort, and lowers the setpoint before the expensive evening."""
    hp = true_pump()
    s = planner.Settings(comfort=20.5, day_min=20.0, night_min=19.0, store_max=22.5)
    hours = []
    for i in range(36):
        hr = (13 + i) % 24
        price = 0.22 if 10 <= hr < 16 else (0.45 if 17 <= hr < 21 else (0.25 if hr >= 21 or hr < 7 else 0.30))
        hours.append(planner.HourIn(t_out=2 + 2 * math.sin((hr - 9) / 24 * 2 * math.pi), wind=4, rad=0.15 if 10 <= hr <= 15 else 0,
                                    p_grid=price, p_own=price, day=7 <= hr < 22, hour=hr))
    p = planner.plan(HOUSE, hp, s, hours, 20.6, 1.0, 20.0, w_now=2.0)
    assert p.saving > 0.05, p.saving
    assert all(x.t_end >= 20.1 for x, h in zip(p.hours, hours) if h.day), [round(x.t_end, 2) for x in p.hours]
    evening = [x.sp for x, h in zip(p.hours, hours) if 17 <= h.hour < 20]
    hold = planner.baseline_sp(s, hp, HOUSE, hours[4])
    assert max(evening) < hold, (evening, hold)


if __name__ == "__main__":
    run_all(dict(globals()))
