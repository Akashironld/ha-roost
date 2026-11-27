"""The weather, Home Assistant's side: fetch the forecast from Open-Meteo or a weather entity and convert its units.
What is kept and how is in core/weather.py."""
from __future__ import annotations

import time
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from aiohttp import ClientTimeout
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import weather as om
from .const import CONF_WEATHER, CONF_WEATHER_SOURCE, WEATHER_MINUTES
from .core import weather as cweather


@dataclass(frozen=True)
class Fetched:
    rows: dict[int, tuple]
    at: float               # time.time() when it came in
    merge: bool             # over the forecast there was (a weather entity) or in its place (Open-Meteo)


async def async_update(hass: Any, conf: dict, w: cweather.Weather,
                       sys_to_c: Callable[[float | None], float | None]) -> tuple[Fetched | None, str | None]:
    """The forecast when due (None: not due, or not available) and what to show as its source (None: nothing
    fetched). The caller puts it into the weather it has then (core/weather.with_forecast): w is only read before
    the first await here, so nothing that changed meanwhile (the history from learning) is lost."""
    if conf.get(CONF_WEATHER_SOURCE) == "entity" and conf.get(CONF_WEATHER):
        return await _async_entity(hass, conf[CONF_WEATHER], w, sys_to_c)
    if not cweather.due(w, time.time(), WEATHER_MINUTES * 60):
        return None, None
    url = om.FORECAST.format(lat=hass.config.latitude, lon=hass.config.longitude, past=92)
    try:
        async with async_get_clientsession(hass).get(url, timeout=ClientTimeout(total=30)) as r:
            r.raise_for_status()
            rows = om.parse(await r.json())
        return Fetched(rows, time.time(), merge=False), "Open-Meteo"
    except Exception as err:  # noqa: BLE001
        # not str(err): an HTTP error holds the request URL, and with it the home location
        return None, f"Open-Meteo unavailable: {f'HTTP {err.status}' if hasattr(err, 'status') else type(err).__name__}"


async def _async_entity(hass: Any, eid: str, w: cweather.Weather,
                        sys_to_c: Callable[[float | None], float | None]) -> tuple[Fetched | None, str | None]:
    if not cweather.due(w, time.time(), WEATHER_MINUTES * 60):
        return None, None
    try:
        resp = await hass.services.async_call("weather", "get_forecasts", {ATTR_ENTITY_ID: eid, "type": "hourly"},
                                              blocking=True, return_response=True)
        # the weather entity's own units (R12): a forecast in °F or a wind in m/s or mph is not in Home Assistant's units
        st = hass.states.get(eid)
        t_unit = st.attributes.get("temperature_unit") if st else None
        w_unit = st.attributes.get("wind_speed_unit") if st else None

        def to_c(v: float | None) -> float | None:
            return unit_to(v, t_unit, "temperature") if t_unit else sys_to_c(v)

        def to_ms(v: float | None) -> float | None:
            return unit_to(v, w_unit, "speed") if w_unit else ((v / 3.6) if v is not None else None)
        sky = partial(cweather.clear_sky, lat=hass.config.latitude, tz=dt_util.get_default_time_zone())
        rows = cweather.entity_rows((resp or {}).get(eid, {}).get("forecast", []), to_c, to_ms, sky)
        return Fetched(rows, time.time(), merge=True), eid
    except Exception as err:  # noqa: BLE001
        return None, f"{eid} unavailable: {err}"


def unit_to(v: float | None, unit: str, kind: str) -> float | None:
    """A value in a source's own unit to °C or m/s (Home Assistant's converters); an unknown unit: not used."""
    if v is None:
        return None
    from homeassistant.util.unit_conversion import (
        SpeedConverter,
        TemperatureConverter,
    )
    conv, to = (TemperatureConverter, "°C") if kind == "temperature" else (SpeedConverter, "m/s")
    try:
        return conv.convert(v, unit, to)
    except Exception:  # noqa: BLE001 - a unit Home Assistant does not know
        return None
