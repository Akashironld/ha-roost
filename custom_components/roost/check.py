"""Does the plan come true? Self-check of the models, and a correction from the last hours. Pure Python.

Self-check (every night): the last days replayed with the planner's own simulator and the setpoints that were really
on the thermostat (so it also works in shadow mode, while something else steers): from every hour, 1, 6 and 24 hours
ahead, the predicted room temperature against the measured one, and over 24 hours the heat and electricity against
the meters. That tests the whole chain the planner relies on: house model, response to the thermostat, hot water and
COP. Roost is ready to steer when it predicts well over enough heating hours and the unit follows the thermostat.

Correction (every plan): when the room was warmer or colder than predicted in the last hours (sun, visitors, a window
open, cooking), the planner gets that as extra heat in kW, fading out over the coming hours. The nightly learning
takes over what lasts.
"""
from __future__ import annotations

from .heatpump import HeatPumpModel
from .model import HouseModel, HourRow
from .planner import HourIn, Settings, Simulator

HORIZONS = (1, 6, 24)
CHECK_DAYS = 7
WARMUP = 6
# ready to steer
READY_HEATING_HOURS = 30
READY_RMSE_6H = 0.5        # °C
READY_HEAT_RATIO = 0.3     # predicted heat within ±30 % of the meters
# correction
CORR_HOURS = 8             # residuals of the last hours
CORR_HALF_LIFE = 3.0       # hours: weight of older residuals
CORR_FADE = 6.0            # hours: half-life of the correction in the plan
CORR_MAX = 1.0             # kW


def _hourin(r: HourRow) -> HourIn:
    return HourIn(t_out=r.T_out, wind=r.wind, rad=r.rad, p_grid=0.0, p_own=0.0, dhw=min(1.0, r.dhw_s / 3600), hour=r.hour)


def self_check(rows: list[HourRow], house: HouseModel, hp: HeatPumpModel, days: int = CHECK_DAYS) -> dict:
    idx = {r.ts: r for r in rows}
    if not idx:
        return {"hours": 0}
    last = max(idx)
    first = last - days * 86400
    keep = max(0.0, house.lag) / (1 + max(0.0, house.lag))
    sim = Simulator(house, hp, Settings())
    err: dict[int, list[float]] = {h: [] for h in HORIZONS}
    heat_p = heat_m = elec_p = elec_m = 0.0
    for t in sorted(x for x in idx if x >= first):
        r0, prev = idx[t], idx.get(t - 3600)
        if prev is None or r0.sp is None:
            continue
        E = 0.0                                   # storage at the start, from the heat of the hours before
        if any(t - 3600 * k not in idx for k in range(1, WARMUP + 1)):
            continue
        for k in range(WARMUP, 0, -1):
            E = (E + idx[t - 3600 * k].Q) * keep
        T = (prev.T + r0.T) / 2
        w = prev.Q                                # the output follows the demand with a delay, from what it gave before
        hq = he = mq = me = 0.0
        for k in range(max(HORIZONS)):
            r = idx.get(t + 3600 * k)
            if r is None or r.sp is None:
                break
            T, E, _c, e, q, _p = sim.hour(T, E, r.sp, _hourin(r), w)
            w = sim.w_end
            hq, he, mq, me = hq + q, he + e, mq + r.Q, me + r.E
            nxt = idx.get(t + 3600 * (k + 1))
            measured = (r.T + nxt.T) / 2 if nxt else None    # hourly means: the end of hour k lies between them
            if k + 1 in err and measured is not None:
                err[k + 1].append(T - measured)
            if k + 1 == max(HORIZONS):
                heat_p, heat_m, elec_p, elec_m = heat_p + hq, heat_m + mq, elec_p + he, elec_m + me
    out: dict = {"hours": len(err[1]), "heating_hours": sum(1 for x in idx.values() if x.ts >= first and x.Q > 0.3),
                 "days": days}
    for h, xs in err.items():
        if xs:
            out[f"rmse_{h}h"] = round((sum(x * x for x in xs) / len(xs)) ** 0.5, 3)
            out[f"bias_{h}h"] = round(sum(xs) / len(xs), 3)
            out[f"n_{h}h"] = len(xs)
    if heat_m > 1.0:
        out["heat_ratio"] = round(heat_p / heat_m, 3)
    if elec_m > 0.3:
        out["elec_ratio"] = round(elec_p / elec_m, 3)
    return out


def readiness(chk: dict, following: bool | None, lever: bool = True) -> tuple[bool, list[str]]:
    """Ready to steer? -> (ready, what is still missing as short codes). lever: the setpoint moves the heat pump."""
    missing = [] if lever else ["lever"]
    if chk.get("heating_hours", 0) < READY_HEATING_HOURS:
        missing.append("heating_hours")
    rmse = chk.get("rmse_6h")
    if rmse is None or rmse > READY_RMSE_6H:
        missing.append("temperature")
    ratio = chk.get("heat_ratio")
    if ratio is None or abs(ratio - 1) > READY_HEAT_RATIO:
        missing.append("heat")
    if following is False:
        missing.append("following")
    return not missing, missing


def correction(entries: list[dict], house: HouseModel, hp: HeatPumpModel, now_ts: float) -> tuple[float, int]:
    """Heat the model missed in the last hours (kW, + = the room got warmer than predicted), from the hourly log:
    each hour replayed from its measured start with the setpoint that was on the thermostat."""
    sim = Simulator(house, hp, Settings())
    by_ts = {e["ts"]: e for e in entries}
    tot = wsum = 0.0
    n = 0
    for e in entries:
        if now_ts - e["ts"] > (CORR_HOURS + 1) * 3600:
            continue
        nxt = by_ts.get(e["ts"] + 3600)
        sp = e.get("sp_t")
        if nxt is None or sp is None or "dhw" not in e:
            continue
        h = HourIn(t_out=e["t_out"], wind=e.get("wind", 3.5), rad=e.get("rad", 0.0), p_grid=0.0, p_own=0.0, dhw=e["dhw"],
                   hour=e.get("hour", -1))
        w0 = (by_ts.get(e["ts"] - 3600) or {}).get("q")      # heat the hour before: where the output starts
        T1 = sim.hour(e["T"], e.get("E", 0.0), float(sp), h, w0)[0]
        kw = (nxt["T"] - T1) * house.C              # °C over one hour × kWh/K = kW
        w = 0.5 ** ((now_ts - nxt["ts"]) / 3600 / CORR_HALF_LIFE)
        tot, wsum, n = tot + kw * w, wsum + w, n + 1
    if n < 2:
        return 0.0, n
    kw = tot / wsum * n / (n + 1)                   # shrink while there are few hours
    return round(max(-CORR_MAX, min(CORR_MAX, kw)), 3), n


def fade(kw: float, hours_ahead: int) -> float:
    return kw * 0.5 ** (hours_ahead / CORR_FADE)
