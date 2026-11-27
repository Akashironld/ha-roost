"""The meters: the heat in the floor, today's electricity and cost (the unit's and the indoor unit's own meters), the
unit's runs and the defrosts it is seen making. Pure: state in, new state out."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, tzinfo
from typing import Any


@dataclass(frozen=True)
class Meters:
    storage_e: float = 0.0                  # kWh of heat in the floor/water (Roost's estimate)
    cost_day: str | None = None             # the local day cost_today and kwh_today count
    cost_today: float = 0.0
    kwh_today: float = 0.0                  # heating electricity today (with the indoor unit's)
    unpriced_kwh: float = 0.0               # heating electricity today without any known price
    indoor_kwh_today: float = 0.0           # the indoor unit's electricity today (in kwh_today and cost_today too)
    last_elec: float | None = None          # the unit's meter reading at the last tick (sum of its meters)
    last_indoor: float | None = None        # the indoor unit's meter reading at the last tick
    runs: tuple[tuple[int, int | None], ...] = ()       # (start, end or None): space heating runs, the last days
    defrost_seen: dict[int, float] = field(default_factory=dict)   # hour ts -> seconds seen defrosting (last 48 h)
    defrost_tick: float | None = None

    # ------------------------------------------------------------ kept over restarts (the main store's own keys)
    def stored(self) -> dict:
        return {"storage_e": round(self.storage_e, 3),
                "defrost_seen": {str(k): round(v) for k, v in self.defrost_seen.items()},
                "runs": [list(r) for r in self.runs],
                "today": {"day": self.cost_day, "cost": round(self.cost_today, 4), "kwh": round(self.kwh_today, 3),
                          "indoor_kwh": round(self.indoor_kwh_today, 3)}}

    @classmethod
    def restore(cls, data: dict) -> Meters:
        today = data.get("today") or {}
        m = cls(storage_e=float(data.get("storage_e", 0.0)),
                defrost_seen={int(k): float(v) for k, v in (data.get("defrost_seen") or {}).items()},
                runs=tuple((r[0], r[1]) for r in (data.get("runs") or []) if isinstance(r, list) and len(r) == 2))
        if today.get("day"):                # another day: the first tick closes it and starts today at zero
            m = replace(m, cost_day=today["day"], cost_today=float(today.get("cost") or 0.0),
                        kwh_today=float(today.get("kwh") or 0.0), indoor_kwh_today=float(today.get("indoor_kwh") or 0.0))
        return m


def _keep(lag: float, hours: float) -> float:
    lag = max(0.0, lag)
    return (lag / (1 + lag)) ** hours if lag > 0 else 0.0


def age_storage(m: Meters, saved_at: float | None, t: float, lag: float) -> tuple[Meters, dict | None]:
    """Heat in the floor after Home Assistant was down (R19): it went on being released to the room meanwhile.
    Whether the unit heated is not known, so this is the lower estimate; a short restart changes nearly nothing.
    Gives the new meters and the event to log (storage_aged), if any."""
    if not saved_at or t <= saved_at:
        return m, None
    hours = min(12.0, (t - saved_at) / 3600)
    before = m.storage_e
    after = max(0.0, m.storage_e * _keep(lag, hours))
    ev = None
    if hours >= 0.25 and before - after >= 0.05:
        ev = {"hours": round(hours, 2), "before": round(before, 2), "after": round(after, 2)}
    return replace(m, storage_e=after), ev


def track_storage(m: Meters, last_tick: float | None, t: float, heating_kw: float | None, lag: float) -> Meters:
    """Heat in the floor/water: + heat the pump delivers for space heating (heating_kw: its output while it heats,
    None when it does not), − the learned release to the room."""
    if last_tick is None:
        return m
    dt_h = min(0.5, max(0.0, (t - last_tick) / 3600))
    q = max(0.0, heating_kw or 0.0) if heating_kw is not None else 0.0
    return replace(m, storage_e=max(0.0, min(20.0, (m.storage_e + q * dt_h) * _keep(lag, dt_h))))


@dataclass(frozen=True)
class Counted:
    """What one tick of the meters gave: the new meters, the day that ended (to close), and the unit's heating
    electricity and its cost in this tick (for the hour being logged; the indoor unit's is not in them)."""
    meters: Meters
    closed_day: str | None = None
    elec: float = 0.0
    cost: float = 0.0
    counted: bool = False           # the unit's meter moved and was counted (elec/cost to add to the hour)


def count_cost(m: Meters, day: str, unit_parts: list[float | None], indoor: float | None, price: float | None) -> Counted:
    """Today's electricity and cost from the meters. day: the local day now; unit_parts: the readings of each meter the
    unit has (an empty list: none configured); indoor: the indoor unit's meter (None: none or not read); price: this
    hour's import price (None: none known; then counted as energy without a price, not as free)."""
    closed = None
    if m.cost_day != day:
        closed = m.cost_day
        m = replace(m, cost_day=day, cost_today=0.0, kwh_today=0.0, unpriced_kwh=0.0, indoor_kwh_today=0.0)
    m = _count_indoor(m, indoor, price)
    # every meter the unit has must read: one missing would make the sum drop, and its return look like new use
    if not unit_parts or any(v is None for v in unit_parts):
        return Counted(m, closed)
    e = sum(v for v in unit_parts if v is not None)
    out = Counted(m, closed)
    if e and m.last_elec is not None and 0 <= e - m.last_elec < 5:
        d = e - m.last_elec
        kwh = m.kwh_today + d
        if price is None:
            m = replace(m, kwh_today=kwh, unpriced_kwh=m.unpriced_kwh + d)
            out = Counted(m, closed, d, 0.0, True)
        else:
            m = replace(m, kwh_today=kwh, cost_today=m.cost_today + d * price)
            out = Counted(m, closed, d, d * price, True)
    if e:
        out = replace(out, meters=replace(out.meters, last_elec=e))
    return out


def _count_indoor(m: Meters, v: float | None, price: float | None) -> Meters:
    """The indoor unit's own meter (pumps, control): outside the unit's total, so counted on its own, into today's
    electricity and cost only. The hour log keeps the unit's heating electricity, as the plan counts it."""
    if v is None:
        return m
    if m.last_indoor is not None and 0 <= v - m.last_indoor < 5:       # as the unit's own meter (cloud catch-ups)
        d = v - m.last_indoor
        m = replace(m, kwh_today=m.kwh_today + d, indoor_kwh_today=m.indoor_kwh_today + d)
        m = replace(m, unpriced_kwh=m.unpriced_kwh + d) if price is None else replace(m, cost_today=m.cost_today + d * price)
    if v:
        m = replace(m, last_indoor=v)
    return m


def track_runs(m: Meters, t: float, heating: bool) -> Meters:
    """The unit's space heating runs (start, end): how often it starts and how long it runs, for the card."""
    runs = list(m.runs)
    if heating and (not runs or runs[-1][1] is not None):
        runs.append((round(t), None))
    elif not heating and runs and runs[-1][1] is None:
        runs[-1] = (runs[-1][0], round(t))
    return replace(m, runs=tuple(r for r in runs if (r[1] or t) > t - 3 * 86400))


def run_stats(runs: tuple[tuple[int, int | None], ...], t: float, tz: tzinfo) -> dict:
    """Per local day (today, yesterday): runs started and their mean length in minutes (a run going on counts to now)."""
    today = datetime.fromtimestamp(t, tz=tz).date()
    out: dict[str, Any] = {}
    for key, day in (("today", today), ("yesterday", today - timedelta(days=1))):
        mine = [r for r in runs if datetime.fromtimestamp(r[0], tz=tz).date() == day]
        mins = [((r[1] or t) - r[0]) / 60 for r in mine]
        out[key] = {"starts": len(mine), "minutes": round(sum(mins) / len(mins)) if mins else None}
    out["heating"] = bool(runs and runs[-1][1] is None)
    return out


def track_defrost(m: Meters, t: float, defrosting: bool) -> Meters:
    """Seconds per hour the unit is seen defrosting, so the card can set what happened beside what was expected."""
    dt = t - m.defrost_tick if m.defrost_tick is not None else 0.0
    seen = dict(m.defrost_seen)
    if defrosting and 0 < dt < 600:
        h = int(t // 3600 * 3600)
        seen[h] = seen.get(h, 0.0) + dt
    cut = t - 48 * 3600
    for h in [h for h in seen if h < cut]:
        del seen[h]
    return replace(m, defrost_seen=seen, defrost_tick=t)
