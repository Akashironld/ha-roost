"""The weather Roost plans and learns with: the forecast (Open-Meteo or a weather entity) in Roost's units, the
history kept for learning, and the clear-sky radiation. Pure: the shell fetches, these functions keep."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, tzinfo
from typing import Callable

from .. import series
from ..util import num as _f


@dataclass(frozen=True)
class Weather:
    forecast: dict[int, tuple] = field(default_factory=dict)   # hour ts -> (°C, W/m² sun, wind m/s[, ..., humidity])
    at: float = 0.0                                             # when the forecast was last fetched (time.time())
    hist: dict[int, tuple] = field(default_factory=dict)       # hour ts -> the same, past hours (learning; history store)

    def get(self, ts: int) -> tuple | None:
        return self.forecast.get(ts)

    # ------------------------------------------------------------ kept over restarts (the history store's key)
    def stored(self) -> dict:
        return {"weather": {str(k): list(v) for k, v in self.hist.items()}}

    @classmethod
    def restore(cls, hist: dict) -> Weather:
        return cls(hist={int(k): tuple(v) for k, v in (hist.get("weather") or {}).items()})


def due(w: Weather, now: float, refresh_s: float) -> bool:
    """Whether to fetch the forecast: none yet, or older than refresh_s."""
    return not (w.forecast and now - w.at < refresh_s)


def fresh(w: Weather, t: float, max_age: float = 3 * 3600) -> bool:
    """A forecast fetched lately (the anomaly of the air at the unit is set against it)."""
    return bool(w.at) and t - float(w.at) < max_age


def with_forecast(w: Weather, rows: dict[int, tuple], at: float, merge: bool) -> Weather:
    """A new forecast: in place of the old one (Open-Meteo gives all hours), or over it (a weather entity)."""
    return replace(w, forecast={**w.forecast, **rows} if merge else dict(rows), at=at)


def with_history(w: Weather, rows: dict[int, tuple]) -> Weather:
    """Past hours (the archive) into the history kept for learning."""
    return replace(w, hist={**w.hist, **rows})


def prune_history(w: Weather, cut: float) -> Weather:
    return replace(w, hist={k: v for k, v in w.hist.items() if k >= cut})


def learning_rows(w: Weather) -> dict[int, tuple]:
    """Everything known, the forecast over the history (learning)."""
    return {**w.hist, **w.forecast}


def clear_sky(ts: float, lat: float, tz: tzinfo) -> float:
    """Radiation under a clear sky in the hour starting at ts (a rough model, fraction of 1 kW/m²)."""
    loc = datetime.fromtimestamp(ts + 1800, tz=tz)
    decl = 23.44 * math.sin(math.radians(360 / 365 * (loc.timetuple().tm_yday - 81)))
    la = math.radians(lat)
    ha = math.radians(15 * (loc.hour + loc.minute / 60 - 12.5))
    s = math.sin(la) * math.sin(math.radians(decl)) + math.cos(la) * math.cos(math.radians(decl)) * math.cos(ha)
    return max(0.0, 0.9 * s)


def entity_rows(forecast: list[dict], to_c: Callable[[float | None], float | None],
                to_ms: Callable[[float | None], float | None], sky: Callable[[int], float]) -> dict[int, tuple]:
    """A weather entity's hourly forecast (weather.get_forecasts) as Roost's rows. to_c / to_ms: the entity's own
    temperature and wind units to °C and m/s (R12); sky: the clear-sky radiation of an hour (cloud cover dims it)."""
    out: dict[int, tuple] = {}
    for x in forecast:
        ts = series.to_ts(x.get("datetime"))
        t = to_c(_f(x.get("temperature")))
        if ts is None or t is None:
            continue
        ts = int(ts - ts % 3600)
        cloud = _f(x.get("cloud_coverage"))
        wind = to_ms(_f(x.get("wind_speed")))
        row = (t, sky(ts) * (1 - 0.75 * ((cloud or 0) / 100) ** 3.4), wind)
        rh = _f(x.get("humidity"))
        out[ts] = row + (None, None, rh) if rh is not None else row      # om.humidity reads it (defrost)
    return out
