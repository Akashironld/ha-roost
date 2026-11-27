"""Prices per hour, Home Assistant's side: read the price sensors and the solar forecast, fetch the built-in
day-ahead prices, seed the prices seen from the recorder. The series themselves are worked out in core/prices.py,
the value of energy in energy.py and value.py. Plain functions: they get what they need and give the new price
state back; sources (what Roost shows it used) and notices go to the sinks they are given."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any, Callable

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder import history as rh
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import energy, epex, series, value
from .const import (
    CONF_BATTERY_KWH,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_EPEX_ZONE,
    CONF_EXPORT_ADD,
    CONF_EXPORT_FORMULA,
    CONF_EXPORT_MULT,
    CONF_EXPORT_PRICE,
    CONF_FIXED_EXPORT_PRICE,
    CONF_FIXED_PRICE,
    CONF_GRID_POWER,
    CONF_GRID_PREFERENCE,
    CONF_GRID_SIGN,
    CONF_IMPORT_ADD,
    CONF_IMPORT_MULT,
    CONF_IMPORT_PRICE,
    CONF_PRICE_MODE,
    CONF_PV_FORECAST,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_POWER,
    CONF_SOLAR_FROM_SOC,
)
from .core import prices as cprices
from .reader import Reader
from .util import num as _f

_LOGGER = logging.getLogger(f"{__package__}.manager")   # the name it always had (log settings, bug reports)

Issue = Callable[..., None]          # the manager's _issue(key, active, placeholders=..., translation_key=...)


async def async_history(hass: Any, conf: dict, read: Reader) -> list[tuple[str, int, list[float | None], float]]:
    """Known historical prices from the recorder, per price sensor: (entity, first hour, price per hour, scale), for
    core/prices.seed (applied by the caller after this returns: nothing is held over the awaits here)."""
    now = dt_util.utcnow()
    start = now - timedelta(hours=49)
    out = []
    for key in (CONF_IMPORT_PRICE, CONF_EXPORT_PRICE):
        eid = conf.get(key) if conf.get(CONF_PRICE_MODE, "sensor") == "sensor" else None
        st = read.state(eid)
        if not eid or st is None:
            continue
        try:
            res = await get_instance(hass).async_add_executor_job(
                partial(rh.state_changes_during_period, hass, start, now, entity_id=eid, no_attributes=True,
                        include_start_time_state=True))
        except Exception as err:  # noqa: BLE001 - without the recorder the last known price is used, as before
            _LOGGER.debug("Roost could not read the price history of %s: %s", eid, err)
            continue
        changes = [(s.last_changed.timestamp(), v) for s in res.get(eid, []) if (v := _f(s.state)) is not None]
        if not changes:
            continue
        scale = series.price_scale(st.attributes.get(ATTR_UNIT_OF_MEASUREMENT), [v for _, v in changes])
        h0 = int(start.timestamp() // 3600 * 3600) + 3600
        n = int((now.timestamp() - h0) // 3600)                # complete hours only
        out.append((eid, h0, series.hourly(series.slots_from_changes(changes, now.timestamp()), h0, n, fill_last=False), scale))
    return out


def epex_due(p: cprices.Prices, now: datetime) -> bool:
    """Whether to fetch the built-in day-ahead prices now (Energy-Charts limits how often an address may ask)."""
    loc = dt_util.as_local(now)
    tomorrow_end = (dt_util.start_of_local_day(loc) + timedelta(days=2)).timestamp()
    return epex.needs_refresh(p.epex, p.epex_at, now.timestamp(), loc.hour, tomorrow_end)


async def async_epex(hass: Any, conf: dict, now: datetime, sources: dict,
                     event: Callable[..., None]) -> list[tuple[float, float, float]] | None:
    """Fetch the built-in day-ahead prices (None: none, or an error; what there is is kept, tried again later)."""
    loc = dt_util.as_local(now)
    zone = conf.get(CONF_EPEX_ZONE) or epex.zone_for(hass.config.country)
    try:
        slots = await epex.async_fetch(async_get_clientsession(hass), zone, loc.date())
    except Exception as err:  # noqa: BLE001 - keep what there is, try again later
        sources["epex"] = f"error: {err}"[:120]
        event("epex", zone=zone, error=str(err)[:200])
        return None
    if slots:
        sources["epex"] = "ok"
        event("epex", zone=zone, slots=len(slots), until=datetime.fromtimestamp(slots[-1][1], tz=timezone.utc).isoformat())
        return slots
    return None


def local_hour(ts: int) -> int:
    return dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc)).hour


def sensor_series(p: cprices.Prices, read: Reader, eid: str | None, now: datetime, hours: int, sources: dict,
                  issue: Issue) -> tuple[cprices.Prices, list[float] | None]:
    """A price sensor's hours ahead (core/prices.sensor_series), with the source and notices of a sensor that has
    only its current price."""
    if eid is None:
        return p, None
    st = read.state(eid)
    if st is None:
        return p, None
    today = dt_util.as_local(now).date()
    mids = [dt_util.start_of_local_day(today + timedelta(days=d)).timestamp() for d in range(3)]
    p, out, nf = cprices.sensor_series(p, eid, dict(st.attributes), st.state, now.timestamp(), hours, mids, local_hour)
    if nf is not None:
        sources[f"price_forecast {eid}"] = nf.how
        # one notice per sensor; its wording says whether Roost estimates the hours ahead or plans on one flat price
        for k in ("estimated", "flat"):
            issue(f"price_no_forecast_{k}_{eid}", nf.kind in ("dynamic", "unknown") and (nf.how == "estimated") == (k == "estimated"),
                  translation_key=f"price_no_forecast_{k}", placeholders={"entity": eid})
    return p, out


def pv_forecast(conf: dict, read: Reader, start: float, hours: int, pv_k: float | None, weather: Any) -> list[float] | None:
    fc = [dict(st.attributes) for key in (CONF_PV_FORECAST, CONF_PV_FORECAST_TOMORROW) if (st := read.state(conf.get(key))) is not None]
    return cprices.pv_forecast(fc, start, hours, bool(conf.get(CONF_PV_POWER)), pv_k, weather)


def _fixed(conf: dict, now: datetime, hours: int, key: str) -> list[float] | None:
    base = int(now.timestamp() // 3600 * 3600)
    loc = [dt_util.as_local(datetime.fromtimestamp(base + i * 3600, tz=timezone.utc)) for i in range(hours)]
    return cprices.fixed_series(conf, [(x.weekday(), x.hour) for x in loc], key)


def energy_ahead(conf: dict, p: cprices.Prices, read: Reader, now: datetime, hours: int, pv_k: float | None, weather: Any,
                 load_profile: list[float] | None, sources: dict,
                 issue: Issue) -> tuple[cprices.Prices, tuple[value.EnergyInputs, value.EnergyValue] | None]:
    """The prices and the value of energy for the hours ahead (None: no price), and the new price state."""
    c = conf
    if c.get(CONF_PRICE_MODE) == "fixed":
        imp = _fixed(c, now, hours, CONF_FIXED_PRICE)
        exp = _fixed(c, now, hours, CONF_FIXED_EXPORT_PRICE)
        p = replace(p, guess={**p.guess, CONF_FIXED_PRICE: [False] * hours})
        if not imp:
            sources["price"] = "missing"
            return p, None
        sources["price"] = "fixed"
    elif c.get(CONF_PRICE_MODE) == "epex":
        t = now.timestamp()
        p, imp = cprices.epex_series(p, t, hours, _f(c.get(CONF_IMPORT_MULT)) or 0.0, _f(c.get(CONF_IMPORT_ADD)) or 0.0, "epex_import")
        if not imp:
            sources["price"] = "missing"
            return p, None
        sources["price"] = "epex"
        exp = None
        if c.get(CONF_EXPORT_FORMULA):
            p, exp = cprices.epex_series(p, t, hours, _f(c.get(CONF_EXPORT_MULT)) or 0.0, _f(c.get(CONF_EXPORT_ADD)) or 0.0, "epex_export")
    else:
        p, imp = sensor_series(p, read, c.get(CONF_IMPORT_PRICE), now, hours, sources, issue)
        if not imp:
            sources["price"] = "missing"
            return p, None
        sources["price"] = "ok"
        exp = None
        if c.get(CONF_EXPORT_PRICE):
            p, exp = sensor_series(p, read, c.get(CONF_EXPORT_PRICE), now, hours, sources, issue)
    # Clip BEFORE the valuation: an unpublished refill/export price must not leak back into known hours.
    export_required = (bool(c.get(CONF_EXPORT_FORMULA)) if c.get(CONF_PRICE_MODE) == "epex"
                       else bool(c.get(CONF_EXPORT_PRICE)) if c.get(CONF_PRICE_MODE) != "fixed" else False)
    if export_required and exp is None:
        sources["price"] = "missing"
        return p, None
    hours = min(hours, len(imp), len(exp) if exp is not None else hours)
    if not hours:
        sources["price"] = "missing"
        return p, None
    imp = imp[:hours]
    exp = exp[:hours] if exp is not None else None
    now_read = energy.Readings(grid_kw=read.kw(c.get(CONF_GRID_POWER)), battery_kw=read.kw(c.get(CONF_BATTERY_POWER)),
                               pv_kw=read.kw(c.get(CONF_PV_POWER)), battery_soc=read.num(c.get(CONF_BATTERY_SOC)),
                               import_positive=c.get(CONF_GRID_SIGN, "import_positive") == "import_positive")
    sfs = _f(c.get(CONF_SOLAR_FROM_SOC))
    site = energy.Site(battery_kwh=_f(c.get(CONF_BATTERY_KWH)), grid_preference=_f(c.get(CONF_GRID_PREFERENCE)) or 0.0,
                       solar_from_soc=value.SOLAR_FROM_SOC if sfs is None else sfs)
    # the local hour of each hour ahead, from its own time: over a change of daylight saving time "now + i" is wrong (R15)
    base = int(now.timestamp() // 3600 * 3600)
    load = energy.load_ahead(load_profile, [local_hour(base + i * 3600) for i in range(hours)])
    return p, energy.hour_values(imp, exp, now_read, site, pv_forecast(c, read, now.timestamp(), hours, pv_k, weather), load)
