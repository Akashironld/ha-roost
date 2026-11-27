"""Own energy for the heat pump: from the tariffs and what the site has (solar, a home battery) to what a kWh costs in each
hour ahead. Pure Python: Home Assistant is read in prices.py, which hands the readings and the settings over.

The calculation itself is value.compute (where a kWh comes from, and what it is worth); this module puts its inputs
together, with a switch per source so its effect can be measured (a replay, the simulation): solar and the battery can
each be left out, and Roost then plans as if they were not there.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import value


@dataclass
class Readings:
    """What the meters say now (kW; None when there is no such sensor or it does not read)."""
    grid_kw: float | None = None
    battery_kw: float | None = None      # + = discharging
    pv_kw: float | None = None
    battery_soc: float | None = None     # %
    import_positive: bool = True         # the grid meter's sign


@dataclass
class Site:
    """The settings for own energy."""
    battery_kwh: float | None = None
    solar_from_soc: float = value.SOLAR_FROM_SOC
    grid_preference: float = 0.0
    use_solar: bool = True               # switches for measuring what each source is worth (not in the options)
    use_battery: bool = True


def load_ahead(profile: list[float] | None, local_hours: list[int]) -> list[float] | None:
    """The house's usual use (kWh) for each hour ahead from its profile by local hour of the day."""
    if not profile or len(profile) != 24:
        return None
    return [profile[h] for h in local_hours]


def hour_values(import_price: list[float], export_price: list[float] | None, now: Readings, site: Site,
                pv_kwh: list[float] | None, load_kwh: list[float] | None) -> tuple[value.EnergyInputs, value.EnergyValue]:
    """The value of a kWh per hour ahead (value.compute) from the tariffs, the meters now and the forecasts."""
    sun = site.use_solar
    bat = site.use_battery and now.battery_soc is not None
    surplus = value.solar_export_now(now.grid_kw, now.battery_kw, now.pv_kw, now.import_positive) if sun else 0.0
    inp = value.EnergyInputs(import_price=import_price, export_price=export_price, pv_kwh=pv_kwh if sun else None,
                             load_kwh=load_kwh, surplus_now_kw=surplus,
                             battery_soc=now.battery_soc if bat else None,
                             battery_kwh=site.battery_kwh if bat else None,
                             solar_from_soc=site.solar_from_soc, grid_preference=site.grid_preference)
    return inp, value.compute(inp)
