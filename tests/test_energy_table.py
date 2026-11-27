"""energy_table.py: the card's Energy tab per hour, day, week and month (23-11-2026)."""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

et = load("energy_table")
AMS = ZoneInfo("Europe/Amsterdam")


def local(ts):
    return datetime.fromtimestamp(ts, tz=AMS)


def moment(n):
    return int(n.replace(tzinfo=AMS).timestamp())


def hour(**kw):
    v = {"heat": 2.8, "heat_defrost": 0.0, "elec": 0.6, "elec_defrost": 0.0, "elec_dhw": 0.0, "elec_indoor": 0.11,
         "elec_total": 0.6, "outdoor": 2.0, "outdoor_min": 1.5, "water_out": 29.0}
    v.update(kw)
    return v


def test_hours_add_up_to_a_day_with_cop_cost_and_the_indoor_unit():
    t0 = moment(datetime(2026, 11, 22, 0))
    hours = {t0 + i * 3600: hour() for i in range(24)}
    rows = et.build(hours, "day", local, fixed_price=0.30, moment=moment)
    assert len(rows) == 1
    r = rows[0]
    assert r["hours"] == 24 and r["run_h"] == 24 and abs(r["q_heat"] - 67.2) < 1e-6
    assert abs(r["e_ind"] - 24 * 0.11) < 1e-6                     # the indoor unit's own meter, as it is
    assert r["cop_heat"] == round(2.8 / 0.6, 2) and r["cop_all"] == round(2.8 / 0.71, 2)
    assert r["cop_pump"] == round(2.8 / 0.6, 2)                    # as Weheat counts it: without the indoor unit
    assert abs(r["cost"] - 24 * 0.71 * 0.30) < 1e-6 and abs(r["dd"] - 16.0) < 1e-6
    assert r["t_out"] == 2.0 and r["t_min"] == 1.5 and r["flow"] == 29.0


def test_a_month_across_the_change_to_winter_time_is_one_period():
    hours = {}
    t = moment(datetime(2026, 10, 20, 0))
    while t < moment(datetime(2026, 11, 3, 0)):
        hours[t] = hour()
        t += 3600
    rows = et.build(hours, "month", local, moment=moment)
    assert [local(r["start"]).strftime("%m-%d %H") for r in rows] == ["10-01 00", "11-01 00"]
    assert rows[0]["hours"] == (12 * 24 + 1)                        # 20-31 October and the extra hour of 25 October


def test_weeks_start_on_monday_and_the_status_per_hour():
    assert et.period_start(datetime(2026, 11, 22, 15), "week") == datetime(2026, 11, 16)
    assert et.first_start(datetime(2026, 11, 23, 6, 30), "hour") == datetime(2026, 11, 21, 7)
    assert et.first_start(datetime(2026, 11, 23), "month") == datetime(2025, 12, 1)
    t0 = moment(datetime(2026, 11, 23, 3))
    hours = {t0: hour(heat_defrost=-0.5), t0 + 3600: hour(elec_dhw=0.8, heat_dhw=2.4), t0 + 7200: hour(heat=0, elec=0)}
    log = {t0 + 7200: {"p_grid": 0.4, "own": 0.0, "reason": "warm_enough", "args": {"room": 20.8}}}
    rows = et.build(hours, "hour", local, log=log, moment=moment)
    assert [r["status"] for r in rows] == ["defrost", "dhw", "idle"]
    assert rows[2]["reason"] == "warm_enough" and rows[0]["q_def"] == 0.5 and rows[1]["cop_dhw"] == 3.0


def test_the_index_against_the_model_and_cloud_catch_ups_left_out():
    t0 = moment(datetime(2026, 11, 22, 0))
    hours = {t0 + i * 3600: hour() for i in range(10)}
    expect = lambda t, q: 2.8 / 0.6 / 0.9    # noqa: E731 - the model expects 10 % better than measured
    r = et.build(hours, "day", local, cop_expected=expect, moment=moment)[0]
    assert r["index"] == 90
    hours[t0 + 10 * 3600] = hour(heat=45.0, elec=9.5)               # one 'hour' with what the cloud missed
    r = et.build(hours, "day", local, cop_expected=expect, moment=moment)[0]
    assert r["index"] == 90 and r["catch_up"] == 1


def test_defrosts_counted_where_the_states_are_kept_and_estimated_before():
    # 23-11-2026, the author: people want to see how many times it defrosted, not kWh
    t0 = moment(datetime(2026, 11, 21, 0))
    hours = {t0 + i * 3600: hour(heat_defrost=(-0.8 if i in (3, 27, 28, 30) else 0.0)) for i in range(48)}
    counted = t0 + 24 * 3600                          # the unit's states only from the second day
    defrosts = {t0 + 27 * 3600: 1, t0 + 28 * 3600: 1, t0 + 30 * 3600: 1}
    rows = et.build(hours, "day", local, moment=moment, defrosts=defrosts, counted_from=counted)
    assert rows[1]["defrosts"] == 3 and not rows[1]["defrosts_est"]
    assert rows[0]["defrosts_est"] and rows[0]["defrosts"] == 1.0     # 0.8 kWh at the 0.8 kWh the counted ones took
    rows = et.build(hours, "day", local, moment=moment)                # no state history at all: the default heat
    assert rows[1]["defrosts_est"] and rows[1]["defrosts"] == round(3 * 0.8 / et.KWH_PER_DEFROST, 1)


def test_own_sun_is_counted_from_the_meters_and_costs_the_export_price():
    # 23-11-2026, the author: more sun went into the heat pump than shown, and is it in the cost? Own sun costs what it
    # would have earned going to the grid: with net metering the import price, after 2026 the (lower) export price
    t0 = moment(datetime(2026, 11, 22, 12))
    sunny = hour(elec=1.2, elec_total=1.2, elec_indoor=0.1, pv=2.9, battery=-0.7, house=2.8, price=0.35, price_export=0.35)
    r = et.build({t0: sunny}, "day", local, moment=moment)[0]
    assert abs(r["sun"] - 1.3 * 2.2 / 2.8) < 1e-3 and r["bat"] == 0.0          # the sun the battery took is not for the house
    assert abs(r["cost"] - 1.3 * 0.35) < 1e-6                                   # net metering: the same as from the grid
    later = dict(sunny, price_export=0.05)
    r = et.build({t0: later}, "day", local, moment=moment)[0]
    sun = 1.3 * 2.2 / 2.8
    assert abs(r["cost"] - ((1.3 - sun) * 0.35 + sun * 0.05)) < 1e-3
    assert abs(r["cost_heat"] + r["cost_ind"] - r["cost"]) < 1e-3 and r["cost_heat"] > r["cost_ind"]
    night = hour(pv=0.0, battery=0.5, house=1.0, price=0.30, price_export=0.30)
    r = et.build({t0: night}, "day", local, moment=moment)[0]
    assert r["sun"] == 0.0 and abs(r["bat"] - 0.71 * 0.5) < 1e-3              # half the house from the battery


if __name__ == "__main__":
    run_all(globals())
