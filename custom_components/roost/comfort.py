"""Learn comfort from the changes people make by hand: a suggestion, never a change by itself. Pure Python.

Roost records every change of the thermostat that it did not make itself while it steers (in shadow mode another
controller may be steering, so those changes say nothing about comfort). When the same kind of change keeps coming
back on different days, it suggests a setting:

- turned up during the comfort hours        -> a higher comfort temperature
- turned down during the comfort hours      -> a lower comfort temperature (not below the day minimum)
- turned up shortly before the comfort hours -> start them earlier
- turned up shortly after the comfort hours  -> end them later
- turned down near the end of the comfort hours -> end them earlier
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

WINDOW_DAYS = 14
MIN_DAYS = 3            # the same kind of change on at least this many different days
MIN_STEP = 0.4          # °C: smaller changes are fiddling
EDGE_HOURS = 3          # "shortly before/after" the comfort hours


@dataclass
class Suggestion:
    kind: str           # raise_comfort | lower_comfort | earlier_day | later_day | earlier_night
    key: str            # the setting to change
    value: float        # its new value
    days: int           # different days with such a change
    count: int          # changes

    def as_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key, "value": self.value, "days": self.days, "count": self.count}


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def suggest(changes: list[dict], local: Callable[[float], tuple[str, int]], now_ts: float, day_from: int, day_to: int,
            comfort: float, day_min: float) -> Suggestion | None:
    """changes: [{"ts", "from", "to"}]; local(ts) -> (local date, local hour). The pattern seen on the most days wins."""
    groups: dict[str, list[tuple[str, int, float]]] = {k: [] for k in ("raise_comfort", "lower_comfort", "earlier_day", "later_day", "earlier_night")}
    for c in changes:
        if now_ts - c["ts"] > WINDOW_DAYS * 86400:
            continue
        delta = c["to"] - c["from"]
        if abs(delta) < MIN_STEP:
            continue
        date, h = local(c["ts"])
        day = day_from <= h < day_to
        if delta > 0 and day_from - EDGE_HOURS <= h < day_from:
            groups["earlier_day"].append((date, h, delta))
        elif delta > 0 and day_to <= h < day_to + EDGE_HOURS:
            groups["later_day"].append((date, h, delta))
        elif delta < 0 and day and h >= day_to - 2:
            groups["earlier_night"].append((date, h, delta))
        elif delta > 0 and day:
            groups["raise_comfort"].append((date, h, delta))
        elif delta < 0 and day:
            groups["lower_comfort"].append((date, h, delta))
    best: Suggestion | None = None
    for kind, xs in groups.items():
        days = len({d for d, _h, _x in xs})
        if days < MIN_DAYS:
            continue
        step = round(_median([abs(x) for _d, _h, x in xs]) * 2) / 2 or 0.5
        hour = int(_median([h for _d, h, _x in xs]))
        if kind == "raise_comfort":
            s = Suggestion(kind, "comfort", min(24.0, comfort + step), days, len(xs))
        elif kind == "lower_comfort":
            s = Suggestion(kind, "comfort", max(day_min, comfort - step), days, len(xs))
        elif kind == "earlier_day":
            s = Suggestion(kind, "day_from", min(h for _d, h, _x in xs), days, len(xs))
        elif kind == "later_day":
            s = Suggestion(kind, "day_to", min(24, max(h for _d, h, _x in xs) + 1), days, len(xs))
        else:
            s = Suggestion(kind, "day_to", max(day_from + 1, hour), days, len(xs))
        current = {"comfort": comfort, "day_from": day_from, "day_to": day_to}[s.key]
        if s.value == current:
            continue
        if best is None or s.days > best.days:
            best = s
    return best
