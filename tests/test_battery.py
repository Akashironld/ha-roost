"""The home battery's habits (battery.py) and what its energy costs (value.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

battery = load("battery")
value = load("value")


def _days(n, per_day):
    """n days of 5-minute samples; per_day(hour, minute) -> (battery_kw, grid_kw, pv_kw, soc)."""
    out = []
    for d in range(n):
        for h in range(24):
            for m in range(0, 60, 5):
                b, g, pv, soc = per_day(h, m)
                out.append(battery.Sample(d * 86400 + h * 3600 + m * 60, f"day{d}", h, b, g, pv, soc))
    return out


def _night_charger(h, m):
    """Charged from the grid 02-04 at 5 kW to 50 %, runs down to 10 % in the evening, a little sun at noon."""
    if 2 <= h < 4:
        return -5.0, 5.4, 0.0, 20 + (h - 2) * 15 + m / 4
    if 11 <= h < 14:
        return -1.0, 0.0, 1.5, 50.0         # solar charging: not from the grid
    return 0.4, 0.0, 0.0, 10.0 if h >= 20 else 50.0


def test_grid_charging_is_learned_with_its_hours_and_reserve():
    hab = battery.learn(_days(7, _night_charger))
    assert hab.charges_from_grid and hab.grid_days == 7
    assert hab.grid_hours == hab.charge_hours == [2, 3]        # not the solar hours
    assert 9.5 < hab.grid_kwh_day < 10.5
    assert hab.reserve == 10.0
    assert hab.top_soc["3"] < battery.FULL_SOC
    assert len(hab.soc_by_hour) == 24 and hab.soc_by_hour["4"] == 50.0 and hab.soc_by_hour["21"] == 10.0


def test_charging_beyond_the_solar_left_over_is_from_the_grid():
    """1 kW of sun, charging with 5 kW: 4 kW comes from the grid (with a grid meter: what it imports)."""
    assert battery.grid_charge_kw(5.0, None, 1.0) == 4.0
    assert battery.grid_charge_kw(5.0, 4.2, 1.0) == 4.2
    assert battery.grid_charge_kw(2.0, -1.0, 3.0) == 0.0          # exporting: all solar
    assert battery.grid_charge_kw(0.0, 3.0, 0.0) == 0.0


def test_only_the_state_of_charge_is_enough():
    """No battery power sensor: the rise of the charge × the capacity."""
    hab = battery.learn([battery.Sample(s.ts, s.day, s.hour, None, s.grid_kw, s.pv_kw, s.soc)
                         for s in _days(7, _night_charger)], capacity_kwh=14.0)
    assert hab.charges_from_grid and 2 in hab.charge_hours


def test_solar_only_and_full_charging_hours_do_not_count():
    def solar(h, m):
        return (-2.0, 0.0, 3.0, 60.0) if 10 <= h < 15 else (0.3, 0.0, 0.0, 40.0)
    assert not battery.learn(_days(7, solar)).charges_from_grid

    def to_full(h, m):
        return (-5.0, 5.0, 0.0, 96.0) if h == 3 else (0.3, 0.0, 0.0, 50.0)
    hab = battery.learn(_days(7, to_full))
    assert hab.grid_days == 7 and hab.grid_hours == [3] and hab.charge_hours == []         # full after it: no room
    assert hab.charges_from_grid


def test_habits_round_trip():
    hab = battery.learn(_days(5, _night_charger))
    back = battery.BatteryHabits.from_dict(hab.as_dict())
    assert back == hab and back.charges_from_grid
    old = {k: v for k, v in hab.as_dict().items() if k != "hold_hours"}      # stored by v0.7.5: none known yet
    assert battery.BatteryHabits.from_dict(old).hold_hours == []


def test_battery_energy_costs_the_cheapest_charging_hour_ahead():
    """The battery runs empty in the morning peak (40 ct); it is charged from the grid at night (24 ct): a kWh from it
    in the evening costs 24 / 0.9, not 40 / 0.9."""
    n = 12
    imp = [0.38] * 3 + [0.24] * 3 + [0.40] * 6
    base = dict(import_price=imp, export_price=imp, pv_kwh=[0.0] * n, load_kwh=[0.5] * n, battery_soc=50.0,
                battery_kwh=10.0, battery_reserve=10.0)
    old = value.compute(value.EnergyInputs(**base))
    assert old.source[0] == value.SOURCE_BATTERY and abs(old.value[0] - 0.40 / 0.9) < 1e-6
    new = value.compute(value.EnergyInputs(**base, grid_charge=[False] * 3 + [True] * 3 + [False] * 6))
    assert abs(new.value[0] - 0.24 / 0.9) < 1e-6
    # a charging hour dearer than running empty changes nothing
    dear = value.compute(value.EnergyInputs(**{**base, "import_price": [0.38] * 3 + [0.50] * 3 + [0.40] * 6},
                                            grid_charge=[False] * 3 + [True] * 3 + [False] * 6))
    assert abs(dear.value[0] - 0.40 / 0.9) < 1e-6



def test_an_hour_the_battery_charges_from_the_grid_costs_the_grid_price():
    """13:00 is the cheapest hour (23 ct) and the battery charges from the grid then: it supplies nothing, so extra use
    costs 23 ct — not the 43 ct of refilling the battery in the evening peak. The battery is simulated charging."""
    n = 8
    imp = [0.31, 0.23, 0.25, 0.43, 0.43, 0.43, 0.43, 0.43]
    base = dict(import_price=imp, export_price=imp, pv_kwh=[0.0] * n, load_kwh=[0.5] * n, battery_soc=30.0,
                battery_kwh=10.0, battery_reserve=10.0)
    old = value.compute(value.EnergyInputs(**base))
    assert old.source[1] == value.SOURCE_BATTERY and old.value[1] > 0.40
    new = value.compute(value.EnergyInputs(**base, grid_charge_to=[None, 60.0, 85.0] + [None] * 5))
    assert new.source[1] == value.SOURCE_GRID and abs(new.value[1] - 0.23) < 1e-9 and abs(new.value[2] - 0.25) < 1e-9
    assert new.battery_soc[2] == 85.0 and new.battery_soc[3] == 80.0          # charged, then supplying the house again
    assert new.source[3] == value.SOURCE_BATTERY



def test_a_steered_battery_follows_its_usual_charge():
    """Predbat sells the battery in the evening peak: it is empty at 20:00, though the house alone would leave it
    half full. Following its usual charge, energy from it after 20:00 is grid energy, and an hour in which the charge
    usually rises (charging) supplies nothing."""
    n = 6
    imp = [0.30, 0.40, 0.45, 0.30, 0.25, 0.25]
    base = dict(import_price=imp, export_price=imp, pv_kwh=[0.0] * n, load_kwh=[0.3] * n, battery_soc=80.0,
                battery_kwh=10.0, battery_reserve=10.0)
    sim = value.compute(value.EnergyInputs(**base))
    assert all(s == value.SOURCE_BATTERY for s in sim.source)                   # the house alone: never empty
    usual = value.compute(value.EnergyInputs(**base, soc_usual=[60.0, 30.0, 10.0, 10.0, 40.0, 40.0]))
    assert usual.source[:2] == [value.SOURCE_BATTERY] * 2 and abs(usual.value[0] - 0.45 / 0.9) < 1e-9
    assert usual.source[3] == value.SOURCE_GRID and usual.value[3] == 0.30
    assert usual.source[4] == value.SOURCE_GRID and usual.value[4] == 0.25      # charging: supplies nothing


def _evening_keeper(h, m):
    """Issue #5 (a Marstek): filled by solar 10-14, keeps its charge by day while the house draws from the grid, covers
    the house 17-23, empty at night (the house from the grid then, nothing to spare)."""
    if 10 <= h < 14:
        return -1.0, 0.0, 1.5, 40 + (h - 10) * 12
    if 14 <= h < 17:
        return 0.0, 0.5, 0.2, 88.0                 # the house imports, the battery waits
    if 17 <= h < 24:
        return 0.5, 0.0, 0.0, 88 - (h - 17) * 10
    return 0.0, 0.4, 0.0, 12.0                      # at its reserve


def test_hours_a_steered_battery_keeps_its_charge_are_learned():
    hab = battery.learn(_days(7, _evening_keeper))
    assert hab.hold_hours == [14, 15, 16], hab.hold_hours      # not the night: empty then, nothing to hold
    assert not hab.charges_from_grid

    def own_use(h, m):                              # an ordinary battery: covers every need while it has charge
        if 10 <= h < 14:
            return -1.0, 0.0, 1.5, 70.0
        return (0.4, 0.0, 0.0, 60.0) if h % 3 else (1.3, 1.7, 0.0, 60.0)    # at its power limit: still supplying
    assert battery.learn(_days(7, own_use)).hold_hours == []
    no_meter = [battery.Sample(x.ts, x.day, x.hour, x.battery_kw, None, x.pv_kw, x.soc) for x in _days(7, _evening_keeper)]
    assert battery.learn(no_meter).hold_hours == []                  # without a grid meter: not known
    assert battery.learn(_days(2, _evening_keeper)).hold_hours == []  # too few days


def test_an_hour_the_battery_keeps_its_charge_costs_the_grid_price():
    """Issue #5: the battery keeps its charge in the afternoon (cheap, 25 ct) for the evening peak (45 ct). Extra use in
    the afternoon comes from the grid at 25 ct, not at the 45 / 0.9 of refilling the battery; and the battery is not
    drained in the simulation, so it still has the evening's charge."""
    n = 8
    imp = [0.25, 0.25, 0.25, 0.45, 0.45, 0.45, 0.45, 0.30]
    base = dict(import_price=imp, export_price=imp, pv_kwh=[0.0] * n, load_kwh=[0.5] * n, battery_soc=60.0,
                battery_kwh=5.4, battery_reserve=12.0, battery_max_kw=1.3)
    old = value.compute(value.EnergyInputs(**base))
    assert old.source[0] == value.SOURCE_BATTERY and old.value[0] > 0.30
    new = value.compute(value.EnergyInputs(**base, battery_holds=[True] * 3 + [False] * 5))
    assert new.source[:3] == [value.SOURCE_GRID] * 3 and new.value[:3] == [0.25] * 3
    assert abs(new.battery_soc[2] - 60.0) < 1e-6 and new.battery_soc[3] < 59.0     # kept, then supplying the house
    assert new.source[3] == value.SOURCE_BATTERY

if __name__ == "__main__":
    run_all(dict(globals()))
