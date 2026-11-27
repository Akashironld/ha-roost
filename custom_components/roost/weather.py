"""Open-Meteo responses -> {hour start ts: (outdoor °C, radiation kW/m², wind m/s)}. Pure Python.

Open-Meteo's radiation at time T is the mean of the hour BEFORE T; temperature and wind are instantaneous at T.
Roost's rows are keyed by the start of the hour, so radiation is taken from T + 1 h and temperature/wind are averaged
over the hour's start and end. Per hour: (outdoor °C, global radiation, wind m/s, direct radiation on the horizontal,
diffuse radiation, relative humidity %) — radiation in kW/m²; the direct and diffuse parts let sun.py work out the sun on
a facade; the humidity (averaged like the temperature) tells when the outdoor unit will defrost (defrost.py). Rows
stored before 22-11-2026 have three or five values: `humidity(row)` is None for them."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FORECAST = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,shortwave_radiation,"
            "wind_speed_10m,direct_radiation,diffuse_radiation,relative_humidity_2m&wind_speed_unit=ms&past_days={past}&forecast_days=2&timezone=UTC")
ARCHIVE = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
           "&hourly=temperature_2m,shortwave_radiation,wind_speed_10m,direct_radiation,diffuse_radiation,relative_humidity_2m"
           "&wind_speed_unit=ms&timezone=UTC")


def parse(j: dict) -> dict[int, tuple]:
    h = (j or {}).get("hourly") or {}
    times = h.get("time") or []
    raw = {}
    for i, t in enumerate(times):
        ts = int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp())
        raw[ts] = (h["temperature_2m"][i], h["shortwave_radiation"][i], h["wind_speed_10m"][i],
                   (h.get("direct_radiation") or [None] * len(times))[i], (h.get("diffuse_radiation") or [None] * len(times))[i],
                   (h.get("relative_humidity_2m") or [None] * len(times))[i])
    out = {}
    for ts, (temp, _rad, wind, _dir, _dif, rh) in raw.items():
        nxt = raw.get(ts + 3600)
        if temp is None:
            continue
        t2 = nxt[0] if nxt and nxt[0] is not None else temp
        w2 = nxt[2] if nxt and nxt[2] is not None else wind
        rad = nxt[1] if nxt and nxt[1] is not None else (_rad or 0.0)
        row: tuple[Any, ...] = ((temp + t2) / 2, max(0.0, (rad or 0.0) / 1000),
                                ((wind or 0.0) + (w2 or 0.0)) / 2 if wind is not None else None)
        d, f = (nxt[3], nxt[4]) if nxt else (_dir, _dif)
        if d is not None and f is not None:
            row += (max(0.0, d / 1000), max(0.0, f / 1000))
        if rh is not None:
            r2 = nxt[5] if nxt and nxt[5] is not None else rh
            if len(row) == 3:
                row += (None, None)
            row += ((rh + r2) / 2,)
        out[ts] = row
    return out


def humidity(row: tuple | list | None) -> float | None:
    """Relative humidity (%) of a weather row, None when it has none (older rows, or the service gave none)."""
    return row[5] if row is not None and len(row) > 5 and row[5] is not None else None
