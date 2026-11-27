"""The card's Energy tab: what the heat pump took and gave, per hour, day, week or month.

Built from Home Assistant's long-term statistics (kept for good, one row per hour), with Roost's own hour log for the
price, the sun and the reason where it still has them. Pure: the caller fetches the statistics (energy_ws.py) and
hands them in, so this is tested without Home Assistant.

Per period: outdoor (mean, lowest), flow while heating, room, heat (space heating, hot water, lost to defrosting),
electricity (heating, hot water, indoor unit, standby), COP (heating, hot water, all
in), cost, own sun, hours running, degree days, and the performance index: the heating COP against what Roost's
learned model of this heat pump expects at the same outdoor temperature and output (100 = as expected). Learned on
the same unit, so the index says when it does worse than it used to (a dirty evaporator, a pump turned up), not how
it compares with other heat pumps.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

PERIODS = {"hour": 48, "day": 31, "week": 13, "month": 12}    # how many periods the tab shows
DD_BASE = 18.0            # degree days: below this outdoor temperature (°C), the Dutch convention
INDEX_MAX_DHW = 0.05      # an hour counts for the index with next to no hot water (kWh electricity)
KWH_PER_DEFROST = 0.65    # heat one defrost takes back (kWh), until the unit's own counted defrosts say otherwise
CATCH_UP_KWH = 15.0       # more heat than this in one hour: the cloud caught up on hours it missed (not one hour)
INDEX_COP = (1.0, 10.0)   # an hour's own COP outside this: the meters caught up in another hour (cloud gaps)

# statistics per role: the Weheat meters (change)
ENERGY = ("heat", "heat_defrost", "heat_dhw", "elec", "elec_defrost", "elec_dhw", "elec_indoor", "elec_total")


def period_start(local: datetime, period: str) -> datetime:
    """The start of the period a local time falls in, as a wall-clock time without a zone (a month that starts in
    summer time and ends in winter time is one period; the caller turns it back into a moment)."""
    local = local.replace(tzinfo=None)
    if period == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return day
    if period == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def first_start(now_local: datetime, period: str) -> datetime:
    """The start of the oldest period the tab shows."""
    cur = period_start(now_local, period)        # wall clock, no zone
    n = PERIODS[period] - 1
    if period == "hour":
        return cur - timedelta(hours=n)
    if period == "day":
        return period_start(cur - timedelta(days=n), "day")
    if period == "week":
        return cur - timedelta(weeks=n)
    y, m = cur.year, cur.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return cur.replace(year=y, month=m)


def hour_row(v: dict) -> dict:
    """One hour of statistics (role -> value) as the tab counts it."""
    g = lambda k: v.get(k) or 0.0     # noqa: E731
    q_heat = max(0.0, g("heat"))
    q_def = max(0.0, -g("heat_defrost"))            # the defrost meter counts negative
    e_heat = max(0.0, g("elec") + g("elec_defrost"))
    e_dhw = max(0.0, g("elec_dhw"))
    e_ind = max(0.0, g("elec_indoor")) if "elec_indoor" in v else 0.0
    # the unit's own total holds standby and cooling as well
    e_rest = max(0.0, g("elec_total") - e_heat - e_dhw) if "elec_total" in v else 0.0
    return {"q_heat": q_heat, "q_def": q_def, "q_dhw": max(0.0, g("heat_dhw")), "e_heat": e_heat, "e_dhw": e_dhw,
            "e_ind": e_ind, "e_rest": e_rest, "t_out": v.get("outdoor"), "t_min": v.get("outdoor_min"),
            "flow": v.get("water_out"), "room": v.get("room"), "price": v.get("price"), "p_exp": v.get("price_export"),
            "pv": v.get("pv"), "battery": v.get("battery"), "house": v.get("house")}


def sources(e_all: float, h: dict) -> tuple[float, float, float]:
    """The heat pump's kWh in an hour by source (own sun, home battery, grid), in the same mix as the whole house:
    the sun the battery does not take first, then the battery discharging, the rest from the grid (kW means of the
    hour; battery + = discharging). Without solar and house readings: all from the grid."""
    pv, house = h.get("pv"), h.get("house")
    if e_all <= 0 or pv is None or house is None:
        return 0.0, 0.0, e_all
    bat = h.get("battery") or 0.0
    house = max(house, e_all)
    sun = min(max(0.0, pv - max(0.0, -bat)), house)
    from_bat = min(max(0.0, bat), house - sun)
    return e_all * sun / house, e_all * from_bat / house, e_all * (house - sun - from_bat) / house


def status(h: dict) -> str:
    """What the unit mostly did in an hour."""
    if h["e_dhw"] >= 0.05:
        return "dhw"
    if h["q_def"] >= 0.2:
        return "defrost"
    if h["e_heat"] >= 0.05:
        return "heating"
    return "idle"


def build(hours: dict[int, dict], period: str, local: Callable[[int], datetime],
          cop_expected: Callable[[float, float], float] | None = None, log: dict[int, dict] | None = None,
          fixed_price: float | None = None, fixed_export: float | None = None,
          moment: Callable[[datetime], int] | None = None, defrosts: dict[int, int] | None = None,
          counted_from: int | None = None) -> list[dict]:
    """Statistics per hour {ts: {role: value}} -> one row per period, oldest first.

    local: ts -> local datetime. cop_expected(t_out, q_kw): the learned model (None: no index). log: Roost's hour log
    by ts (price, reason). fixed_price / fixed_export: the contract's prices when there is no price per hour (no export
    price: net metering, the import price). moment: a period's local wall-clock start -> ts (default: this
    computer's zone). defrosts: the defrosts counted per hour from the unit's state history, which Home Assistant keeps
    for some days only (counted_from: its first hour); before that the number is estimated from the defrost meter, at
    the heat per defrost of the counted hours (rows say defrosts_est)."""
    log = log or {}
    defrosts = defrosts or {}
    per_defrost = KWH_PER_DEFROST
    if counted_from is not None:
        n = sum(c for t, c in defrosts.items() if t >= counted_from)
        q = sum(hour_row(v)["q_def"] for t, v in hours.items() if t >= counted_from)
        if n >= 3 and q > 0:
            per_defrost = q / n
    moment = moment or (lambda n: int(n.timestamp()))
    out: dict[datetime, dict] = {}
    for ts in sorted(hours):
        h = hour_row(hours[ts])
        key = period_start(local(ts), period)
        r = out.get(key)
        if r is None:
            r = out[key] = {"start": moment(key), "hours": 0, "defrosts": 0.0, "defrosts_est": False, "q_heat": 0.0, "q_def": 0.0, "q_dhw": 0.0,
                            "e_heat": 0.0, "e_dhw": 0.0, "e_ind": 0.0, "e_rest": 0.0, "cost": 0.0, "priced": 0.0,
                            "sun": 0.0, "bat": 0.0, "cost_heat": 0.0, "cost_dhw": 0.0, "cost_ind": 0.0, "cost_rest": 0.0,
                            "run_h": 0.0, "dd": 0.0, "_t": [], "_tmin": None, "_flow": [], "_room": [],
                            "_iq": 0.0, "_ie": 0.0, "_iexp": 0.0}
        r["hours"] += 1
        if counted_from is not None and ts >= counted_from:
            r["defrosts"] += defrosts.get(ts, 0)
        elif h["q_def"] > 0:
            r["defrosts"] += h["q_def"] / per_defrost
            r["defrosts_est"] = True
        for k in ("q_heat", "q_def", "q_dhw", "e_heat", "e_dhw", "e_ind", "e_rest"):
            r[k] += h[k]
        if h["t_out"] is not None:
            r["_t"].append(h["t_out"])
            r["dd"] += max(0.0, DD_BASE - h["t_out"]) / 24.0
            lo = h["t_min"] if h["t_min"] is not None else h["t_out"]
            r["_tmin"] = lo if r["_tmin"] is None else min(r["_tmin"], lo)
        if h["e_heat"] >= 0.05:
            r["run_h"] += 1
            if h["flow"] is not None:
                r["_flow"].append(h["flow"])
        if h["room"] is not None:
            r["_room"].append(h["room"])
        # the price: Roost's own (what the plan used), else the price sensor's mean, else the contract. Own sun costs
        # what it would have earned going to the grid (the export price; with net metering that is the import price),
        # the battery and the grid the import price
        e_all = h["e_heat"] + h["e_dhw"] + h["e_ind"] + h["e_rest"]
        lg = log.get(ts) or {}
        price = lg.get("p_grid") if lg.get("p_grid") is not None else h["price"] if h["price"] is not None else fixed_price
        sun, bat, _grid = sources(e_all, h)
        r["sun"] += sun
        r["bat"] += bat
        if price is not None:
            p_exp = h["p_exp"] if h["p_exp"] is not None else fixed_export if fixed_export is not None else price
            c = (e_all - sun) * price + sun * p_exp
            r["cost"] += c
            r["priced"] += e_all
            if e_all > 0:
                for k, e in (("cost_heat", h["e_heat"]), ("cost_dhw", h["e_dhw"]), ("cost_ind", h["e_ind"]), ("cost_rest", h["e_rest"])):
                    r[k] += c * e / e_all
        if period == "hour":
            r["status"] = status(h)
            if lg.get("reason"):
                r["reason"], r["args"] = lg["reason"], lg.get("args") or {}
        # the index: hours of space heating (no hot water), the model being that of the heat after defrosting. Over a
        # period the sums count (the cloud meters sometimes book heat and electricity in different hours; summed they
        # agree); a single hour only when its own COP is believable
        catch_up = h["q_heat"] + h["q_dhw"] > CATCH_UP_KWH
        if catch_up:
            r["catch_up"] = r.get("catch_up", 0) + 1
        if cop_expected is not None and h["e_dhw"] < INDEX_MAX_DHW and not catch_up:
            q_net = h["q_heat"] - h["q_def"]
            one = h["e_heat"] > 0 and INDEX_COP[0] <= q_net / h["e_heat"] <= INDEX_COP[1]
            if period != "hour" or one:
                r["_ie"] += h["e_heat"]
                if h["t_out"] is not None and q_net > 0:
                    exp = cop_expected(h["t_out"], max(0.1, q_net))
                    if exp > 0:
                        r["_iq"] += q_net
                        r["_iexp"] += q_net / exp
    rows = []
    for key in sorted(out):
        r = out.pop(key)
        t, fl, rm = r.pop("_t"), r.pop("_flow"), r.pop("_room")
        r["t_out"] = round(sum(t) / len(t), 1) if t else None
        tmin = r.pop("_tmin")
        r["t_min"] = round(tmin, 1) if tmin is not None else None
        r["flow"] = round(sum(fl) / len(fl), 1) if fl else None
        r["room"] = round(sum(rm) / len(rm), 1) if rm else None
        q_net = r["q_heat"] - r["q_def"]
        e_all = r["e_heat"] + r["e_dhw"] + r["e_ind"] + r["e_rest"]
        r["cop_heat"] = round(q_net / r["e_heat"], 2) if r["e_heat"] >= 0.05 and q_net > 0 else None
        r["cop_dhw"] = round(r["q_dhw"] / r["e_dhw"], 2) if r["e_dhw"] >= 0.05 else None
        # the heat pump's own COP (as Weheat and EN 14511 count it: without the indoor unit) and all in
        e_pump = r["e_heat"] + r["e_dhw"]
        r["cop_pump"] = round((q_net + r["q_dhw"]) / e_pump, 2) if e_pump >= 0.05 and q_net + r["q_dhw"] > 0 else None
        r["cop_all"] = round((q_net + r["q_dhw"]) / e_all, 2) if e_all >= 0.05 and q_net + r["q_dhw"] > 0 else None
        iq, ie, iexp = r.pop("_iq"), r.pop("_ie"), r.pop("_iexp")
        r["index"] = round(100.0 * (iq / ie) / (iq / iexp)) if ie > 0 and iexp > 0 and iq >= 1.0 else None
        for k in ("cost", "cost_heat", "cost_dhw", "cost_ind", "cost_rest"):
            r[k] = round(r[k], 3) if r["priced"] > 0 else None
        r["priced"] = round(r["priced"], 3)
        r["defrosts"] = round(r["defrosts"]) if not r["defrosts_est"] else round(r["defrosts"], 1)
        for k in ("q_heat", "q_def", "q_dhw", "e_heat", "e_dhw", "e_ind", "e_rest", "sun", "bat", "dd"):
            r[k] = round(r[k], 3)
        rows.append(r)
    return rows
