"""Prices per hour: what a price sensor, the built-in day-ahead prices or a fixed contract give for the hours ahead,
and the prices seen (kept for diagnostics and to tell what kind of sensor it is). Pure: the shell reads the sensors
and fetches the day-ahead prices; these functions work out the series and the new state."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable

from .. import epex, series, value
from ..const import (
    CONF_FIXED_EXPORT_PRICE,
    CONF_FIXED_LOW_PRICE,
    CONF_FIXED_PRICE,
    CONF_LOW_FROM,
    CONF_LOW_TO,
    CONF_LOW_WEEKEND,
)
from ..util import num as _f

SEEN_KEEP_S = 3 * 86400      # prices seen are kept this long


@dataclass(frozen=True)
class Prices:
    seen: dict[str, dict[int, float]] = field(default_factory=dict)   # price key -> {hour epoch: price per kWh}
    guess: dict[str, list[bool]] = field(default_factory=dict)        # price key -> per hour ahead: not published
    epex: list[tuple[float, float, float]] = field(default_factory=list)   # built-in day-ahead prices (epex.py)
    epex_at: float | None = None
    need_epex: bool = False         # a price sensor without a forecast: estimate from day-ahead prices
    tariff_now: float | None = None     # the import price this hour, from the last tick (cost without a plan)

    # ------------------------------------------------------------ kept over restarts (the main store's own key)
    def stored(self) -> dict:
        return {"price_seen": {e: {str(k): round(v, 5) for k, v in sorted(d.items())} for e, d in self.seen.items()}}

    @classmethod
    def restore(cls, data: dict) -> Prices:
        return cls(seen={e: {int(k): v for k, v in d.items()} for e, d in (data.get("price_seen") or {}).items()})


def prune_seen(p: Prices, now: float) -> Prices:
    cut = now - SEEN_KEEP_S
    return replace(p, seen={e: {k: v for k, v in d.items() if k >= cut} for e, d in p.seen.items()})


def _with_seen(p: Prices, key: str, seen: dict[int, float]) -> Prices:
    return replace(p, seen={**p.seen, key: seen})


def _with_guess(p: Prices, key: str, guess: list[bool]) -> Prices:
    return replace(p, guess={**p.guess, key: guess})


def seed(p: Prices, eid: str, h0: int, hourly: list[float | None], scale: float) -> Prices:
    """Known historical prices (from the recorder) into the prices seen; never used as future tariffs."""
    seen = dict(p.seen.get(eid, {}))
    for h, v in enumerate(hourly):
        if v is not None:
            seen.setdefault(h0 + h * 3600, v * scale)
    return _with_seen(p, eid, seen)


def published(p: Prices, key: str, raw: list[float | None], base: int, cur: float | None) -> tuple[Prices, list[float]]:
    """Keep known history for diagnostics; stop planning at the first unpublished price."""
    seen = dict(p.seen.get(key, {}))
    for h, v in enumerate(raw):
        if v is not None and h > 0:                     # hour 0 is only the rest of the hour: keep the full one
            seen[base + h * 3600] = v
        elif v is not None:
            seen.setdefault(base, v)
    # A sensor's current price is usable now, but it does not publish a future tariff.
    raw = list(raw)
    if raw and raw[0] is None:
        raw[0] = cur
    p = _with_guess(_with_seen(p, key, seen), key, [v is None for v in raw])
    return p, series.published_prefix(raw)


def epex_series(p: Prices, now: float, hours: int, mult: float, add: float, key: str) -> tuple[Prices, list[float] | None]:
    """The built-in day-ahead prices through the user's formula (day-ahead × multiplier + fixed amount)."""
    if not p.epex:
        return p, None
    raw = [None if v is None else epex.formula(v, mult, add) for v in series.hourly(p.epex, now, hours, fill_last=False, full=True)]
    cur = series.current_value(p.epex, now)
    return published(p, key, raw, int(now // 3600 * 3600), epex.formula(cur, mult, add) if cur is not None else None)


@dataclass(frozen=True)
class NoForecast:
    """A price sensor with only its current price: what its history says it is, and how the hours ahead were made."""
    kind: str               # series.classify_history: "flat", "tou", "dynamic", "unknown"
    how: str                # what the sources show: the kind, or for a dynamic one "estimated" / "flat"


def sensor_series(p: Prices, eid: str, attrs: dict, state: str, now: float, hours: int, mids: list[float],
                  local_hour: Callable[[int], int]) -> tuple[Prices, list[float] | None, NoForecast | None]:
    """A price sensor's hours ahead from its attributes (rates/forecast) and state. mids: the local midnights of today,
    tomorrow and the day after (epoch)."""
    slots = series.find_slots(dict(attrs), mids[0], mids)
    cur = _f(state)
    unit = attrs.get("unit_of_measurement")
    scale = series.price_scale(unit, [cur] if cur is not None else [v for _, _, v in slots])     # for the state
    if slots:
        fscale = series.slot_scale(slots, unit, cur * scale if cur is not None else None, now)
        raw = [None if v is None else v * fscale for v in series.hourly(slots, now, hours, fill_last=False, full=True)]
        p, out = published(p, eid, raw, int(now // 3600 * 3600), cur * scale if cur is not None else None)
        return p, out, None
    if cur is None:
        return p, None, None
    return without_forecast(p, eid, cur * scale, now, hours, local_hour)


def without_forecast(p: Prices, eid: str, cur: float, now: float, hours: int,
                     lh: Callable[[int], int]) -> tuple[Prices, list[float], NoForecast]:
    """A price sensor with only the current price. Its history tells what it is: one price or a fixed rate per hour
    of the day (a fixed contract: those prices are known ahead), or a price that changes every hour (a dynamic
    contract): then the hours ahead are estimated from the day-ahead prices, the way this sensor followed them
    (sensor ≈ a × day-ahead + b); one flat price when that does not fit."""
    base = int(now // 3600 * 3600)
    seen = dict(p.seen.get(eid, {}))
    seen[base] = cur
    p = _with_seen(p, eid, seen)
    kind = series.classify_history(seen, lh)
    out, how = [cur] * hours, kind
    if kind == "tou":
        rate = {lh(ts): v for ts, v in sorted(seen.items())}        # the latest price per hour of the day
        out = [cur] + [rate.get(lh(base + i * 3600), cur) for i in range(1, hours)]
    elif kind == "dynamic":
        p = replace(p, need_epex=True)
        how = "flat"
        if p.epex:
            pairs = []
            for ts, v in sorted(seen.items())[-48:]:
                x = series.hourly(p.epex, ts, 1, fill_last=False)[0]
                if x is not None:
                    pairs.append((x, v))
            fit = series.fit_line(pairs)
            if fit and fit[2] >= series.FIT_MIN_R2:
                a, b, _r2 = fit
                ahead = series.hourly(p.epex, base, hours, fill_last=False, full=True)
                out = series.published_prefix([cur, *(None if x is None else a * x + b for x in ahead[1:])])
                how = "estimated"
    p = _with_guess(p, eid, [kind in ("dynamic", "unknown") and i > 0 for i in range(len(out))])
    return p, out, NoForecast(kind, how if kind == "dynamic" else kind)


def fixed_series(conf: dict, local: list[tuple[int, int]], key: str) -> list[float] | None:
    """A fixed contract per hour ahead (normal / low rate), or the fixed export price. local: (weekday, hour) of each
    hour ahead."""
    hours = len(local)
    if key == CONF_FIXED_EXPORT_PRICE:
        v = _f(conf.get(CONF_FIXED_EXPORT_PRICE))
        return None if v is None else [v] * hours
    normal = _f(conf.get(CONF_FIXED_PRICE))
    if normal is None:
        return None
    return value.fixed_prices(local, normal, _f(conf.get(CONF_FIXED_LOW_PRICE)),
                              int(conf.get(CONF_LOW_FROM, 23)), int(conf.get(CONF_LOW_TO, 7)), bool(conf.get(CONF_LOW_WEEKEND, True)))


def pv_forecast(forecasts: list[dict], start: float, hours: int, pv_power: bool, pv_k: float | None,
                weather: Any) -> list[float] | None:
    """Own solar per hour ahead (kWh): from the forecast sensors' attributes (the first wins where both cover the same
    time: summing them counted that sun twice, R14), else the learned kW per kW/m² of sun with the weather forecast."""
    slots: list = []
    for attrs in forecasts:
        slots += [s for s in series.find_slots(dict(attrs))
                  if not any(min(s[1], k[1]) - max(s[0], k[0]) > 0 for k in slots)]
    if slots:
        return series.energy_per_hour(sorted(slots), start, hours, rate_first=True)
    if pv_power and pv_k:
        base = start - start % 3600
        return [pv_k * (weather.get(int(base + i * 3600)) or (0, 0, 0))[1] for i in range(hours)]
    return None


def flat(p: Prices, plan_tariff: list[float], hours: int = 24) -> tuple[value.EnergyInputs, value.EnergyValue]:
    """No price: one flat price for every hour (the last known import price), so Roost still plans for comfort and
    the weather, without moving heat to cheaper hours."""
    known = [v for d in p.seen.values() for _, v in sorted(d.items())[-1:]]
    price = plan_tariff[0] if plan_tariff else (known[0] if known else 0.25)
    inp = value.EnergyInputs(import_price=[price] * hours, export_price=[price] * hours)
    ev = value.EnergyValue(value=[price] * hours, source=[value.SOURCE_GRID] * hours, surplus_kwh=[0.0] * hours)
    return inp, ev
