"""House model, heat pump model, history rows and weather parsing."""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

model = load("model")
heatpump = load("heatpump")
history = load("history")
weather = load("weather")
sun = load("sun")

DAY0 = 20_000


def simulate_house(p, days=40, seed=3, winter=True):
    """A house following the model exactly, heated by a thermostat on 20.5 °C, plus measurement noise."""
    rnd = random.Random(seed)
    rows, T, E = [], 20.5, 0.0
    lag = p["lag"]
    for d in range(days):
        base = 3.0 if winter else 13.0
        for h in range(24):
            t_out = base + 4 * math.sin((h - 9) / 24 * 2 * math.pi) + rnd.uniform(-1, 1)
            rad = max(0.0, 0.4 * math.sin((h - 7) / 11 * math.pi)) if 7 <= h <= 18 else 0.0
            wind = 3.5 + rnd.uniform(-2, 4)
            He = p["H"] + p["Hw"] * (wind - 3.5)
            q = max(0.0, min(6.0, He * (T - t_out) - p["g"] * rad - p["internal"] + (20.5 - T) * p["C"]))
            T0 = T
            E += q
            rel = E / (1 + lag)
            E -= rel
            T += (rel + p["g"] * rad + p["internal"] - He * (T - t_out)) / p["C"]
            cop = 3.04 + 0.19 * (t_out + 1.0) - 0.27 * max(0.0, q - 3.5)
            rows.append(model.HourRow(ts=(DAY0 + d) * 86400 + h * 3600, T=T0 + rnd.gauss(0, 0.03), T_out=t_out, Q=q, rad=rad, wind=wind,
                                      E=q / cop, T_out_sensor=t_out + 1.0, heating_s=3600.0 if q > 0.3 else 0.0))
    return rows


TRUE = {"C": 19.0, "H": 0.125, "g": 5.5, "lag": 1.0, "internal": -0.05, "Hw": 0.007}


def test_learning_recovers_a_winter_house():
    res = model.learn(simulate_house(TRUE), model.HouseModel())
    assert res.adopted, res.reason
    m = res.model
    assert abs(m.H - TRUE["H"]) / TRUE["H"] < 0.15, m
    assert abs(m.C - TRUE["C"]) / TRUE["C"] < 0.3, m
    assert m.error_t is not None and m.error_t < 0.3 and m.error_balance < 0.15, m


def test_learning_needs_enough_days():
    res = model.learn(simulate_house(TRUE, days=6), model.HouseModel(C=30.0))
    assert not res.adopted and "not enough" in res.reason and res.model.C == 30.0


def test_select_days_keeps_old_heating_days():
    rows = simulate_house(TRUE, days=30) + [model.HourRow(ts=(DAY0 + 200 + d) * 86400 + h * 3600, T=21, T_out=18, Q=0.0)
                                           for d in range(70) for h in range(24)]
    days = model.select_days(rows, recent_days=60, heating_days=120)
    assert any(d < DAY0 + 100 for d in days), "winter days dropped"
    assert sum(1 for d in days if d >= DAY0 + 200) == 60


def test_heat_pump_cop_and_bias():
    rows = simulate_house(TRUE)
    m, note = heatpump.learn(rows, heatpump.HeatPumpModel.for_profile("generic"))
    assert m.source == "learned", note
    assert abs(m.cop(5.0, 3.0) - (3.04 + 0.19 * 6.0)) < 0.25, (m, note)


def test_heat_pump_max_output_only_raised():
    rows = [model.HourRow(ts=i * 3600, T=20, T_out=8, Q=2.0, heating_s=3600, E=0.5) for i in range(200)]
    m, _ = heatpump.learn(rows, heatpump.HeatPumpModel.for_profile("p80"))
    assert m.pmax(8) == heatpump.HeatPumpModel.for_profile("p80").pmax(8)
    rows = [model.HourRow(ts=i * 3600, T=20, T_out=0, Q=7.5, heating_s=3600, E=2.5) for i in range(20)]
    m, note = heatpump.learn(rows, heatpump.HeatPumpModel.for_profile("p80"))
    assert m.pmax(0) > 7.0, note


def test_profiles():
    assert heatpump.profile_for("Blackbird P80 heat pump") == "p80"
    assert heatpump.profile_for("Blackbird P60") == "p60"
    assert heatpump.profile_for("Sparrow") == "generic"


def test_weheat_logs_and_precedence():
    logs = [{"timeBucket": "2026-01-15T10:00:00Z", "tRoomAverage": 20.4, "tAirInAverage": 3.1, "heatPumpStateHeating": 3000,
             "heatPumpStateDhw": 600, "heatPumpStateManualControl": 0},
            {"timeBucket": "2026-01-15T11:00:00Z", "tRoomAverage": -1, "tAirInAverage": -1, "heatPumpStateHeating": 3600},
            {"timeBucket": "2026-01-15T12:00:00Z", "tRoomAverage": 20.6, "heatPumpStateManualControl": 3600}]
    energy = [{"timeBucket": "2026-01-15T10:00:00Z", "totalEOutHeating": 4.0, "totalEOutHeatingDefrost": -0.3, "totalEInHeating": 1.1,
               "totalEInHeatingDefrost": 0.05},
              {"timeBucket": "2026-01-15T11:00:00Z", "totalEOutHeating": 4.2, "totalEInHeating": 1.2},
              {"timeBucket": "2026-01-15T12:00:00Z", "totalEOutHeating": 1.0, "totalEInHeating": 0.4}]
    w = history.weheat_hours(logs, energy)
    t10 = 1768471200
    assert abs(w[t10]["q"] - 3.7) < 1e-9 and abs(w[t10]["e"] - 1.15) < 1e-9 and w[t10]["dhw_s"] == 600
    assert w[t10 + 3600]["room"] is None and w[t10 + 3600]["sensor_out"] is None      # -1 °C = sensor fault
    wx = {t10: (2.0, 0.1, 4.0), t10 + 3600: (2.5, 0.2, 4.0), t10 + 7200: (3.0, 0.2, 4.0)}
    ha = {t10: {"room": 20.9, "q": 9.9}, t10 + 3600: {"thermostat_room": 20.7}}
    rows = history.build_rows(w, ha, wx)
    assert [r.ts for r in rows] == [t10, t10 + 3600]           # hour 12 was manual control: left out
    assert rows[0].T == 20.9 and abs(rows[0].Q - 3.7) < 1e-9   # HA's room sensor, Weheat's meter
    assert rows[1].T == 20.7 and rows[1].T_out_sensor is None


def test_open_meteo_radiation_shift():
    j = {"hourly": {"time": ["2026-01-15T10:00", "2026-01-15T11:00", "2026-01-15T12:00"],
                    "temperature_2m": [2.0, 3.0, 4.0], "shortwave_radiation": [100, 300, 200], "wind_speed_10m": [4, 6, 8]}}
    w = weather.parse(j)
    t10 = 1768471200
    assert w[t10] == (2.5, 0.3, 5.0)      # radiation of 10–11 is reported at 11:00
    assert w[t10 + 7200][1] == 0.2



LAT, LON = 51.9, 5.7


def clear_sky(ts):
    """A synthetic sunny hour: (t_out, global, wind, direct, diffuse) in kW/m²."""
    el, _az = sun.position(ts + 1800, LAT, LON)
    s_ = max(0.0, math.sin(math.radians(el)))
    return (5.0, 0.8 * s_ + 0.08 * (s_ > 0), 3.5, 0.8 * s_, 0.08 * (s_ > 0))


def test_sun_position_and_facade():
    from datetime import datetime, timezone
    noon_june = int(datetime(2026, 6, 21, 11, 10, tzinfo=timezone.utc).timestamp())   # ~solar noon at 5.7° E
    el, az = sun.position(noon_june + 1800, LAT, LON)
    assert 61 < el < 62 and 175 < az < 185, (el, az)
    morning = noon_june - 4 * 3600
    wx = clear_sky(morning)
    assert sun.effective(morning, wx, LAT, LON, 90.0, 1.0) > sun.effective(morning, wx, LAT, LON, 270.0, 1.0) * 3
    assert sun.effective(morning, wx, LAT, LON, 135.0, 0.0) == wx[1]                 # vertical 0: global radiation
    assert sun.effective(morning, wx[:3], LAT, LON, 135.0, 1.0) == wx[1]             # no direct/diffuse: global


def test_learning_finds_the_window_facade_and_hourly_gains():
    """A house with its windows to the south-east and cooking at 18 h: the model finds both."""
    rnd = random.Random(7)
    p = dict(TRUE, g=6.0)
    rows, T, E = [], 20.5, 0.0
    for d in range(30):
        for h in range(24):
            ts = (DAY0 + d) * 86400 + h * 3600
            wx = clear_sky(ts) if d % 3 else (5.0, 0.1, 3.5, 0.0, 0.1)        # every third day overcast
            t_out = 3 + 4 * math.sin((h - 9) / 24 * 2 * math.pi)
            sol = sun.effective(ts, wx, LAT, LON, 135.0, 1.0)
            cook = 0.8 if h == 18 else 0.0
            He = p["H"]
            q = max(0.0, min(6.0, He * (T - t_out) - p["g"] * sol - p["internal"] - cook + (20.5 - T) * p["C"]))
            T0 = T
            E += q
            rel = E / (1 + p["lag"])
            E -= rel
            T += (rel + p["g"] * sol + p["internal"] + cook - He * (T - t_out)) / p["C"]
            rows.append(model.HourRow(ts=ts, T=T0 + rnd.gauss(0, 0.02), T_out=t_out, Q=q, rad=wx[1], wind=3.5, E=q / 3.5))
    wxs = {}

    def eff(ts, facade, vertical):
        d = (ts // 86400) - DAY0
        wx = clear_sky(ts) if d % 3 else (5.0, 0.1, 3.5, 0.0, 0.1)
        return sun.effective(ts, wx, LAT, LON, facade, vertical)
    res = model.learn(rows, model.HouseModel(), eff, lambda ts: int(ts % 86400 // 3600))
    m = res.model
    assert res.adopted and m.sun_facade in (90.0, 135.0, 180.0) and m.sun_vertical >= 0.5, (m.sun_facade, m.sun_vertical, res.scores)
    assert m.profile and m.profile[18] == max(m.profile) and m.profile[18] > 0.2, m.profile



def test_starting_values_by_heat_emitter():
    floor = model.starting_values("floor", None)
    rad = model.starting_values("radiators", None)
    assert floor == {**model.PRIOR, "lag": 1.0, "C": 20.0}
    assert rad["lag"] < 0.3 and rad["C"] < floor["C"]
    bag = model.starting_values("radiators", {"H": 0.2, "C": 20.0})
    assert bag["H"] == 0.2 and bag["C"] == 14.0                       # storage per m² scaled for radiators
    assert model.starting_values("unknown", None)["lag"] == 1.0



def test_after_insulating_recent_heating_wins():
    """60 heating days of the old house (heat loss 0.20 kW/K), then 45 of the same house insulated (0.12): the model
    follows the insulated house, not the average of both."""
    old = simulate_house(dict(TRUE, H=0.20), days=60, seed=11)
    new = simulate_house(dict(TRUE, H=0.12), days=45, seed=12)
    shift = 60 * 86400
    rows = old + [model.HourRow(**{**r.__dict__, "ts": r.ts + shift}) for r in new]
    m = model.learn(rows, model.HouseModel()).model
    assert abs(m.H - 0.12) < abs(m.H - 0.16), m.H          # nearer the insulated house than the middle
    w = model.recency_weights({r.ts: r for r in rows}, model.select_days(rows))
    days = sorted(w)
    assert w[days[-1]] == 1.0 and w[days[0]] < 0.6, (w[days[0]], w[days[-1]])


if __name__ == "__main__":
    run_all(dict(globals()))
