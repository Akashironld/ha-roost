"""defrost.py: the share of the heat defrosting takes back, by outdoor temperature and humidity (22-11-2026)."""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402
from test_planner_control import HOUSE, PUMP, hours  # noqa: E402

defrost = load("defrost")
model = load("model")
heatpump = load("heatpump")
planner = load("planner")


def test_no_defrost_when_mild_or_dry():
    assert defrost.share(6.0, 99.0) == 0.0 and defrost.share(2.0, 70.0) == 0.0
    s = defrost.share(2.0, 97.0)
    assert 0.04 < s < 0.06                                    # ~5 % at 2 °C in damp air, as measured on the P80
    assert defrost.share(2.0, None) < s and defrost.share(-10.0, 99.0) == defrost.CAP
    assert 0 < defrost.minutes(2.0, 97.0, 2.5) < 10           # one 17-min defrost per ~6 hours of 2.5 kW


def test_the_strength_is_learned_from_the_defrost_meter():
    rows = []
    for i in range(400):
        t, rh = (0.5 + (i % 5), 80.0 + (i % 4) * 6)
        x = (defrost.T0 - t) * defrost.ramp(rh)
        q_gross = 2.5
        qd = 0.03 * x * q_gross
        rows.append(model.HourRow(ts=i * 3600, T=20.0, T_out=t, Q=q_gross - qd, Qd=qd, rh=rh))
    a, n = defrost.learn(rows)
    assert n == 400 and abs(a - 0.03) < 0.003
    assert defrost.learn(rows[:10]) == (defrost.A_PRIOR, 10)  # too few hours: the prior stays


def test_the_strength_is_learned_on_the_air_at_the_unit():
    # 23-11-2026: the forecast 2 K colder than the air at the unit (beyond its usual bias of 1 K): learned on the
    # forecast alone, the strength comes out wrong; on the unit's sensor less its bias it is right
    rows = []
    for i in range(400):
        t_air, rh = (0.5 + (i % 5), 80.0 + (i % 4) * 6)
        qd = 0.03 * (defrost.T0 - t_air) * defrost.ramp(rh) * 2.5
        rows.append(model.HourRow(ts=i * 3600, T=20.0, T_out=t_air - 2.0, T_out_sensor=t_air + 1.0, Q=2.5 - qd, Qd=qd, rh=rh))
    a, _ = defrost.learn(rows, bias=1.0)
    assert abs(a - 0.03) < 0.003 and abs(defrost.learn(rows)[0] - 0.03) > 0.005     # on the forecast: off
    assert defrost.anomaly_ahead(99.0, 2.0, 1.0, 2) == [0.0, 0.0]          # a broken sensor: no correction


def test_the_cop_follows_the_hours_humidity():
    hp = heatpump.HeatPumpModel.for_profile("p80")
    # the learned COP holds a typical hour's defrosting: damp air below it, dry air above it, no forecast = the same
    assert hp.cop_net(8.0, 2.5, 99.0) == hp.cop(8.0, 2.5) and hp.cop_net(2.0, 2.5, None) == hp.cop(2.0, 2.5)
    assert hp.cop_net(2.0, 2.5, 97.0) < hp.cop(2.0, 2.5) < hp.cop_net(2.0, 2.5, 70.0)


def test_the_same_hour_costs_more_in_fog():
    # the planner prices defrosting per hour: the same output costs the share defrosting takes back more in damp air
    S = planner.Settings(comfort=20.0, day_min=19.0, night_min=19.0, store_max=21.5, sp_min=19.0, ot=True, ot_q_min=2.4)
    h = replace(hours(2)[4], t_out=2.0, p_grid=0.30, p_own=0.30)
    sim = planner.Simulator(HOUSE, PUMP, S)
    sim.ot = True
    _, _, c_dry, e_dry, q_dry, _ = sim.hour(20.3, 3.0, 2.4, replace(h, rh=60.0), 2.4)
    _, _, c_fog, e_fog, q_fog, _ = sim.hour(20.3, 3.0, 2.4, replace(h, rh=99.0), 2.4)
    assert q_dry == q_fog and e_fog > e_dry
    assert abs(e_dry / e_fog - PUMP.defrost_factor(2.0, 99.0) / PUMP.defrost_factor(2.0, 60.0)) < 0.02
    import numpy as np
    _, _, c_grid = planner.hour_grid(sim, np.array([20.3]), np.array([3.0]), 2.4, replace(h, rh=99.0))
    one = sim.hour(20.3, 3.0, 2.4, replace(h, rh=99.0), None)
    assert abs(float(c_grid[0]) - (one[2] + one[5])) < 1e-9          # the grid search costs it the same way


def test_todays_departure_of_the_unit_sensor_fades_over_the_hours():
    # 23-11-2026: a clear calm night, the weather service 4.5 K colder than the air at the unit (bias +1.15): two
    # defrosts expected, one happened. Today's extra 3.35 K counts now and fades by 15 % an hour
    adj = defrost.anomaly_ahead(-0.8, -5.3 + 0.0, 1.15, 7)
    assert adj[0] == 3.35 and abs(adj[3] - 3.35 * 0.85 ** 3) < 0.01 and adj[6] < 1.3
    assert defrost.anomaly_ahead(None, 2.0, 1.15, 3) == [0.0, 0.0, 0.0]
    assert defrost.anomaly_ahead(20.0, 0.0, 1.0, 1) == [defrost.ANOMALY_MAX]        # a sensor in the sun: capped
    m = heatpump.HeatPumpModel.for_profile("p80")
    assert m.cop_net(-5.3, 2.5, 95, adj[0]) > m.cop_net(-5.3, 2.5, 95)            # warmer air at the unit: less defrost
    assert defrost.air(-5.3, -0.8, 1.15) == -1.95 and defrost.air(2.0, None, 1.15) == 2.0
    assert defrost.air(0.0, 10.5, 1.15, rad=0.3) == 0.0                       # sun on the sensor: the forecast


def test_below_five_degrees_the_pump_runs_anyway():
    # Weheat manual 6.3 and the P80's indoor meter (23-11-2026): below 5 °C at the unit the circulation pump runs on
    # its own, so heating adds no indoor-unit electricity then
    m = heatpump.HeatPumpModel.for_profile("p80")
    m.bias = 1.15
    assert m.pumps_anyway(3.0) and not m.pumps_anyway(4.5)
    assert not m.pumps_anyway(3.0, 1.5)              # the air at the unit warmer than forecast today


if __name__ == "__main__":
    run_all(globals())
