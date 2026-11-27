"""The heat pump's planned electricity per hour, for battery optimisers (Predbat, EMHASS, others). Pure Python.

Roost knows when the heat pump will run: an optimiser that plans the home battery can plan around it instead of
against it. Two forms in the sensor's attributes:
- `hours`: [{"start": ISO time, "kwh": electricity planned in that hour}], for any optimiser or template;
- `predbat`: {ISO time: kWh}, cumulative from local midnight today, the form Predbat reads for `load_forecast`
  (apps.yaml: `load_forecast: sensor.<name>$predbat`). Predbat ADDS this to its own load estimate: that estimate must
  then leave the heat pump out, or it is counted twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo


def forecast(start_ts: int, kwh: list[float], tz: tzinfo, now_ts: int) -> tuple[list[dict], dict[str, float]]:
    """start_ts: the start of the plan's first hour (UTC epoch); kwh: electricity per plan hour; now_ts: now."""
    hours: list[dict] = []
    ahead: list[tuple[datetime, float]] = []
    for i, e in enumerate(kwh):
        ts = start_ts + i * 3600
        if ts + 3600 <= now_ts:
            continue                                   # an hour already past
        at = datetime.fromtimestamp(ts, tz)
        ahead.append((at, round(max(0.0, e), 3)))
        hours.append({"start": at.isoformat(), "kwh": round(max(0.0, e), 3)})
    now = datetime.fromtimestamp(now_ts, tz)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    out: dict[str, float] = {midnight.isoformat(): 0.0}
    total = 0.0
    hour_now = now.replace(minute=0, second=0, microsecond=0)
    out[hour_now.isoformat()] = 0.0                     # nothing extra before now
    for at, e in ahead:
        if at < hour_now:
            continue
        total += e
        out[(at + timedelta(hours=1)).isoformat()] = round(total, 3)
    return hours, out
