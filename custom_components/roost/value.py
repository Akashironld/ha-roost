"""What does one extra kWh cost in each of the coming hours?

Pure Python. The answer depends on where that kWh would come from:

- solar that would otherwise be exported  -> the export price (it is "free" apart from lost feed-in);
- with a home battery: solar surplus while the battery is at or above `solar_from_soc` (%) -> the export price too.
  Below that the surplus goes into the battery first and counts as grid energy for the heat pump (it is missed later);
- everything else, the battery supplying the house included -> the import price of that hour, plus a small preference
  for own energy (configurable). Whoever steers the battery (Predbat, evcc, its own app) decides when it delivers:
  Roost does not guess its habits (22-11-2026: replaying two weeks, a learned battery model changed plans by ~1 %
  either way, while its choices confused people).

The battery's charge is followed hour by hour from the expected solar and house use, so a battery at 30 % in the
morning counts as at 50 % once the forecast surplus has filled it that far.

Only real solar counts as own solar: export minus battery discharge, never more than the PV power (a battery
that is selling to the grid is not solar; learned on 14-10-2026 in the author's Node-RED controller).

With a Predbat marginal-cost table available, that table can replace the estimate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SOURCE_SOLAR = "solar"
SOURCE_BATTERY = "battery"           # kept for stored hours; no longer produced
SOURCE_GRID = "grid"
SOURCE_PREDBAT = "predbat"
RESERVE = 10.0                       # % the battery keeps (no setting: it only shapes the charge followed)
SOLAR_FROM_SOC = 50.0                # default: solar for the heat pump once the battery is at least this full


@dataclass
class EnergyInputs:
    import_price: list[float]                     # per hour, currency/kWh (hour 0 = now)
    export_price: list[float] | None = None       # None: same as import (net metering)
    pv_kwh: list[float] | None = None             # expected solar per hour
    load_kwh: list[float] | None = None           # expected house use per hour without the heat pump
    surplus_now_kw: float = 0.0                   # measured, sustained export right now
    battery_soc: float | None = None              # %
    battery_kwh: float | None = None              # usable capacity
    solar_from_soc: float = SOLAR_FROM_SOC        # % from which solar surplus is free for the heat pump
    grid_preference: float = 0.0                  # added to grid hours (prefer own energy)
    predbat: list[float | None] | None = None     # optional marginal costs per hour


@dataclass
class EnergyValue:
    value: list[float]                            # currency per kWh per hour
    source: list[str]
    surplus_kwh: list[float] = field(default_factory=list)   # own solar free for the heat pump per hour
    battery_soc: list[float | None] = field(default_factory=list)   # the charge followed, at the start of each hour


def compute(inp: EnergyInputs) -> EnergyValue:
    n = len(inp.import_price)
    imp = list(inp.import_price)
    exp = list(inp.export_price) if inp.export_price else list(imp)
    exp = (exp + [exp[-1] if exp else 0.0] * n)[:n]
    pv = (list(inp.pv_kwh or []) + [0.0] * n)[:n]
    load = (list(inp.load_kwh or []) + [0.4] * n)[:n]
    has_bat = inp.battery_soc is not None and bool(inp.battery_kwh)
    cap = float(inp.battery_kwh or 0.0)
    e_res = cap * RESERVE / 100
    e = cap * min(100.0, max(0.0, inp.battery_soc or 0.0)) / 100 if has_bat else 0.0
    val: list[float] = []
    src: list[str] = []
    free_kwh: list[float] = []
    soc_path: list[float | None] = []
    for h in range(n):
        net = pv[h] - load[h]          # >0: surplus, <0: shortage
        if h == 0 and inp.surplus_now_kw > 0:
            net = max(net, inp.surplus_now_kw)
        surplus = max(0.0, net)
        soc_start = 100 * e / cap if has_bat else None
        soc_path.append(soc_start)
        if has_bat:
            if net > 0:
                take = min(net, cap - e)
                e += take
                spill = net - take
            else:
                e -= min(-net, max(0.0, e - e_res))
                spill = 0.0
            free = surplus if soc_start is not None and soc_start >= inp.solar_from_soc else spill
        else:
            free = spill = surplus
        if free >= 1.0 or (h == 0 and inp.surplus_now_kw >= 1.0 and free > 0):
            v, s = exp[h], SOURCE_SOLAR
        elif free > 0:
            f = min(1.0, free)                                # part of the extra kWh is surplus, the rest grid
            v, s = f * exp[h] + (1 - f) * (imp[h] + inp.grid_preference), SOURCE_SOLAR
        else:
            v, s = imp[h] + inp.grid_preference, SOURCE_GRID
        if inp.predbat and h < len(inp.predbat) and (pb_h := inp.predbat[h]) is not None:
            v, s = float(pb_h), SOURCE_PREDBAT
        val.append(v)
        src.append(s)
        free_kwh.append(free)
    return EnergyValue(val, src, free_kwh, battery_soc=soc_path)


@dataclass
class HourPrices:
    p_grid: float          # currency per kWh beyond own solar (grid, or battery at its refill cost)
    p_own: float           # currency per kWh of own solar (what exporting it would earn)
    own_kw: float          # own solar available for extra use this hour (kW)
    source: str


def fixed_prices(hours: list[tuple[int, int]], normal: float, low: float | None = None, low_from: int = 23, low_to: int = 7,
                 low_weekend: bool = True) -> list[float]:
    """A fixed contract per local hour ((weekday 0 = Monday, hour)): the low rate in the low hours (low_from until
    low_to, through midnight when low_from > low_to) and, if chosen, all weekend; else the normal rate."""
    out = []
    for wd, h in hours:
        if low is None:
            out.append(normal)
            continue
        night = (low_from <= h or h < low_to) if low_from > low_to else (low_from <= h < low_to)
        out.append(low if night or (low_weekend and wd >= 5) else normal)
    return out


def planner_prices(inp: EnergyInputs, ev: EnergyValue) -> list[HourPrices]:
    """Split each hour for the heat-pump planner: up to `own_kw` at the solar value, the rest at the grid value."""
    n = len(ev.value)
    exp = list(inp.export_price) if inp.export_price else list(inp.import_price)
    exp = (exp + [exp[-1] if exp else 0.0] * n)[:n]
    out = []
    for h in range(n):
        own = ev.surplus_kwh[h] if h < len(ev.surplus_kwh) else 0.0
        if h == 0:
            own = max(own, inp.surplus_now_kw)
        grid = ev.value[h] if ev.source[h] in (SOURCE_BATTERY, SOURCE_GRID, SOURCE_PREDBAT) else inp.import_price[h] + inp.grid_preference
        out.append(HourPrices(grid, exp[h], own, ev.source[h]))
    return out


def house_use(grid_kw: float, pv_kw: float | None, battery_kw: float | None, import_positive: bool = True) -> float:
    """What the house uses (kW, the heat pump included) from the grid meter, solar and battery (+ discharging): for
    the usage profile when there is no sensor for the house itself."""
    imp = grid_kw if import_positive else -grid_kw
    return max(0.0, imp + (pv_kw or 0.0) + (battery_kw or 0.0))


def source_split(hp_kw: float, house_kw: float, pv_kw: float, battery_kw: float) -> tuple[float, float, float]:
    """Where the heat pump's power comes from now (kW from own solar, the battery, the grid), in the same mix as the
    whole house: solar first, then the battery discharging, the rest from the grid."""
    if hp_kw <= 0:
        return 0.0, 0.0, 0.0
    house = max(house_kw, hp_kw)
    sun = min(max(0.0, pv_kw), house)
    bat = min(max(0.0, battery_kw), house - sun)
    return hp_kw * sun / house, hp_kw * bat / house, hp_kw * (house - sun - bat) / house


def solar_export_now(grid_kw: float | None, battery_kw: float | None, pv_kw: float | None, import_positive: bool = True) -> float:
    """Solar going to the grid right now (kW): export minus battery discharge, at most the PV power."""
    if grid_kw is None:
        return 0.0
    export = -grid_kw if import_positive else grid_kw
    export -= max(0.0, battery_kw or 0.0)
    if pv_kw is not None:
        export = min(export, pv_kw)
    return max(0.0, export)
