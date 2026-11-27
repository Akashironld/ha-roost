"""energy.py: own energy for the heat pump put together from the meters, the settings and the forecasts."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

energy = load("energy")
value = load("value")

IMP, EXP = [0.30] * 6, [0.05] * 6
PV, LOAD = [0, 3, 3, 3, 3, 0], [0.5] * 6


def test_the_same_as_value_compute_with_everything_on():
    now = energy.Readings(grid_kw=-1.2, battery_kw=0.0, pv_kw=2.0, battery_soc=30.0)
    site = energy.Site(battery_kwh=10.0, solar_from_soc=50.0)
    inp, ev = energy.hour_values(IMP, EXP, now, site, PV, LOAD)
    want = value.compute(value.EnergyInputs(import_price=IMP, export_price=EXP, pv_kwh=PV, load_kwh=LOAD, surplus_now_kw=1.2,
                                            battery_soc=30.0, battery_kwh=10.0, solar_from_soc=50.0))
    assert ev.value == want.value and ev.surplus_kwh == want.surplus_kwh and inp.surplus_now_kw == 1.2


def test_a_source_can_be_left_out_to_measure_it():
    now = energy.Readings(grid_kw=-1.2, battery_kw=0.0, pv_kw=2.0, battery_soc=30.0)
    _, all_on = energy.hour_values(IMP, EXP, now, energy.Site(battery_kwh=10.0), PV, LOAD)
    _, no_bat = energy.hour_values(IMP, EXP, now, energy.Site(battery_kwh=10.0, use_battery=False), PV, LOAD)
    _, no_sun = energy.hour_values(IMP, EXP, now, energy.Site(battery_kwh=10.0, use_solar=False), PV, LOAD)
    assert all_on.value[1] == 0.30 and no_bat.value[1] == 0.05          # without the battery the first surplus is exported
    assert all(v == 0.30 for v in no_sun.value) and not any(no_sun.surplus_kwh)


def test_the_house_profile_by_local_hour():
    prof = [0.1 * h for h in range(24)]
    assert energy.load_ahead(prof, [23, 0, 1]) == [prof[23], 0.0, prof[1]]
    assert energy.load_ahead(None, [1]) is None and energy.load_ahead([1.0], [1]) is None


if __name__ == "__main__":
    run_all(globals())
