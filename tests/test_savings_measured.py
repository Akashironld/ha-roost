"""The measured parts of the saving (no model) and the planned electricity for battery optimisers."""
import os
import sys
from datetime import timezone

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

lookback = load("lookback")
loadcast = load("loadcast")


def _day(cheap_kwh=1.0, dear_kwh=0.5, sun=0.0, bat=0.0, p_own=None, refill=None):
    """18 dear hours (40 ct) and 6 cheap ones (20 ct), the same outdoor temperature."""
    dear = [{"e": dear_kwh, "t_out": 5.0, "p_imp": 0.40, "p_grid": 0.40, "p_own": 0.40} for _ in range(18)]
    cheap = [{"e": cheap_kwh, "t_out": 5.0, "p_imp": 0.20, "p_grid": refill if refill is not None else 0.20,
              "p_own": p_own if p_own is not None else 0.20, "e_sun": sun, "e_bat": bat} for _ in range(6)]
    return dear + cheap


def test_timing_against_heating_spread_evenly():
    m = lookback.measured(_day(), 20.5)
    # paid 18*0.5*0.40 + 6*1*0.20 = 4.80; evenly 15 kWh over 24 equal hours: 15 * (18*0.4 + 6*0.2)/24 = 5.25
    assert abs(m["paid"] - 4.80) < 1e-6 and abs(m["flat"] - 5.25) < 1e-6 and abs(m["timing"] - 0.45) < 1e-6
    assert m["ct_paid"] == 32.0 and m["ct_flat"] == 35.0


def test_heating_in_dear_hours_shows_as_a_cost():
    m = lookback.measured(_day(cheap_kwh=0.2, dear_kwh=0.8), 20.5)
    assert m["timing"] < 0


def test_solar_with_net_metering_is_worth_nothing_extra_and_after_it_is():
    netm = lookback.measured(_day(sun=0.5), 20.5)
    after = lookback.measured(_day(sun=0.5, p_own=0.05), 20.5)
    assert netm["sun_kwh"] == 3.0 and netm["sun_value"] == 0.0
    assert abs(after["sun_value"] - 3.0 * 0.15) < 1e-6


def test_battery_counted_at_its_refill_cost():
    m = lookback.measured(_day(bat=0.5, refill=0.12), 20.5)
    assert m["bat_kwh"] == 3.0 and abs(m["bat_value"] - 3.0 * 0.08) < 1e-6


def test_no_heating_no_measurement_and_the_month_adds_up():
    assert lookback.measured([{"e": 0.0, "t_out": 5.0, "p_imp": 0.3}] * 24, 20.5) is None
    d = lookback.measured(_day(), 20.5)
    m = lookback.month_measured({"2026-11-01": {"measured": d}, "2026-11-02": {"measured": d}, "2026-10-31": {"measured": d}},
                                "2026-11")
    assert m["days"] == 2 and abs(m["timing"] - 0.9) < 1e-6 and m["ct_paid"] == 32.0


def test_planned_electricity_for_predbat_is_cumulative_from_midnight():
    tz = timezone.utc
    start = 1_795_000_000 // 86400 * 86400 + 10 * 3600          # 10:00 UTC
    hours, pb = loadcast.forecast(start, [0.5, 0.0, 1.0, 0.25], tz, start + 1800)
    assert [h["kwh"] for h in hours] == [0.5, 0.0, 1.0, 0.25]
    vals = list(pb.values())
    assert vals[0] == 0.0 and vals == sorted(vals) and vals[-1] == 1.75     # never decreasing, the total at the end
    hours2, _ = loadcast.forecast(start, [0.5, 0.0, 1.0], tz, start + 3 * 3600 - 10)
    assert len(hours2) == 1                                        # the hours already past are left out


def test_slow_correction_carries_half_of_yesterdays_miss():
    check = load("check")
    model = load("model")
    heatpump = load("heatpump")
    house = model.HouseModel(C=18.0, H=0.15, g=5.0, lag=1.0, internal=0.0, Hw=0.0)
    hp = heatpump.HeatPumpModel.for_profile("p80")
    now = 1_795_000_000 // 3600 * 3600
    start = now - 25 * 3600
    # the room drifts up 0.02 °C an hour more than the model says: by the end of the day 0.48 °C it missed
    planner = load("planner")
    sim = planner.Simulator(house, hp, planner.Settings(ot=True))
    entries, Tm, E = [], 20.5, 0.0
    for i in range(25):
        entries.append({"ts": start + 3600 * i, "T": round(Tm + 0.02 * i, 3), "E": 0.0, "q": 3.0, "t_out": 0.5, "rad": 0.0,
                        "wind": 3.5, "hour": i % 24})
        Tm, E, *_ = sim.hour(Tm, E, 3.0, planner.HourIn(t_out=0.5, wind=3.5, rad=0.0, p_grid=0, p_own=0, hour=i % 24), None)
    kw = check.slow_correction(entries, house, hp, now)
    assert 0.1 < kw < 0.25                                             # half of ~0.48 °C x C / 24 h
    sunny = [dict(e, rad=0.2) for e in entries]
    assert check.slow_correction(sunny, house, hp, now) == 0.0          # a sunny day says nothing about tomorrow
    assert check.slow_correction(entries[:20], house, hp, now) == 0.0   # no whole day


if __name__ == "__main__":
    run_all(globals())
