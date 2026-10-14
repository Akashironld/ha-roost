"""Runtime of one Roost entry: read sources, keep track of stored heat, plan, steer the thermostat, learn."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any, Callable

from homeassistant.components.recorder import get_instance, history as rh
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import Context, Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import building, check, comfort, control, heatpump, history, model, planner, response, series, sun, value, weather as om
from .const import (
    CONF_BASELINE_NIGHT, CONF_BATTERY_KW, CONF_BATTERY_KWH, CONF_BATTERY_POWER, CONF_BATTERY_RESERVE, CONF_BATTERY_SOC,
    CONF_COMFORT, CONF_DAY_FROM, CONF_DAY_MIN, CONF_DAY_TO, CONF_EXPORT_PRICE, CONF_GRID_POWER, CONF_GRID_PREFERENCE,
    CONF_GRID_SIGN, CONF_HEAT_PUMP, CONF_HOUSE_POWER, CONF_IMPORT_ON_SETUP, CONF_IMPORT_PRICE, CONF_MAX_ABOVE,
    CONF_MIN_INTERVAL, CONF_NIGHT_MIN, CONF_PAUSE_HOURS, CONF_PV_FORECAST, CONF_PV_FORECAST_TOMORROW, CONF_PV_POWER,
    CONF_ROOM, CONF_STORE_MAX, CONF_THERMOSTAT, CONF_WEATHER, CONF_WEATHER_SOURCE, DEFAULTS, DOMAIN, HISTORY_DAYS,
    CONF_FIXED_EXPORT_PRICE, CONF_FIXED_LOW_PRICE, CONF_FIXED_PRICE, CONF_LOW_FROM, CONF_LOW_TO, CONF_LOW_WEEKEND, CONF_PRICE_MODE,
    CONF_SP_MIN, CONF_USE_BAG,
    LEARN_HOUR, LEARN_MINUTE, PLAN_MINUTES, STORAGE_VERSION, TICK_SECONDS, WEATHER_MINUTES, WEHEAT, WEHEAT_IMPORT_DAYS,
)
from .reasons import Reason
from .weheat_api import WeheatUnavailable, async_fetch_history, heat_pump_id

_LOGGER = logging.getLogger(__name__)
DHW_STATES = ("dhw", "legionella_prevention")
DHW_WEEKS = 8                 # hot water profile from the last weeks
SP_HIST_DAYS = 120            # own record of the thermostat's setpoint per hour
NO_LEVER_KW = 0.2             # learned gain below this (kW per °C): the setpoint hardly moves the heat pump
WEHEAT_FIELDS = 2             # 2: the import includes the setpoint per hour
NOT_FOLLOWING_MIN = 45
ROOM_SILENT_MIN = 30


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


@dataclass
class Health:
    not_following_since: float | None = None
    room_missing_since: float | None = None
    issues: set = field(default_factory=set)


class RoostManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._hist_store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.history")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._contexts: dict[str, float] = {}
        self.mode = "shadow"
        self.ent: dict[str, str] = {}               # weheat role -> entity_id
        self.pump_name: str | None = None
        self.house = model.HouseModel()
        self.pump = heatpump.HeatPumpModel()
        self.mem = control.ControlMemory()
        self.storage_e = 0.0
        self.plan: planner.Plan | None = None
        self.plan_hours: list[planner.HourIn] = []
        self.plan_at: float | None = None
        self.plan_tariff: list[float] = []          # import price per plan hour (what the price sensor says, or a guess)
        self.plan_guess: list[bool] = []            # True: no price known yet for that hour, filled in
        # price entity -> {hour epoch: price per kWh}: known hourly prices of the last days, to fill hours the price
        # forecast does not reach yet with the same hour a day earlier
        self.price_seen: dict[str, dict[int, float]] = {}
        self._price_guess: dict[str, list[bool]] = {}
        self.reason = Reason("starting")
        self.decision: control.Decision | None = None
        self.sources: dict[str, str] = {}
        self.learn_info: dict = {}
        self.import_info: dict = {}
        self.hour_log: list[dict] = []              # last ~48 h: state and inputs per hour, for the daily saving
        self.saving_days: dict[str, float] = {}     # date -> saving (currency)
        self.cost_today = 0.0
        self.kwh_today = 0.0
        self._cost_day: str | None = None
        self._last_elec: float | None = None
        self._last_tick: float | None = None
        self.pv_k: float | None = None              # kW of PV per kW/m² of radiation (learned)
        self.load_profile: list[float] | None = None
        self.health = Health()
        self._weather: dict[int, tuple] = {}
        self._weather_at = 0.0
        self._weheat_hours: dict[int, dict] = {}
        self._weather_hist: dict[int, tuple] = {}
        self._planning = False
        self._learning = False
        self.importing = False
        self.check: dict = {}                       # nightly self-check (check.self_check)
        self.changes: list[dict] = []               # changes by hand while active: {"ts", "from", "to", "room"}
        self.building: dict | None = None           # opt-in BAG data: {"lat", "lon", "year", "area_m2", "walls"} (no address)
        self.suggestion: comfort.Suggestion | None = None
        self.ready: bool = False
        self.ready_missing: list[str] = []
        self.corr_kw, self.corr_n = 0.0, 0           # correction from the last hours (check.correction)
        self._acc_hour: int | None = None           # the current hour: seconds on hot water, heat for the house
        self._dhw_acc = 0.0
        self._heat_acc = 0.0
        # per hour: mean room setpoint and the thermostat's own reading, from the thermostat entity (an on/off thermostat
        # never tells the heat pump its setpoint, so the Weheat logs do not have it; HA statistics keep no attributes)
        self.sp_hist: dict[int, list] = {}
        self._sp_acc = [0.0, 0.0, 0.0, 0.0]      # setpoint × s, s, reading × s, s

    # ------------------------------------------------------------ config
    @property
    def conf(self) -> dict:
        return {**DEFAULTS, **self.entry.data, **self.entry.options}

    def settings(self) -> planner.Settings:
        c = self.conf
        night = _f(c.get(CONF_BASELINE_NIGHT)) or 0.0
        return planner.Settings(comfort=float(c[CONF_COMFORT]), day_min=float(c[CONF_DAY_MIN]), night_min=float(c[CONF_NIGHT_MIN]),
                                store_max=max(float(c[CONF_STORE_MAX]), float(c[CONF_COMFORT])), max_above_room=float(c[CONF_MAX_ABOVE]),
                                sp_min=float(c.get(CONF_SP_MIN, c[CONF_NIGHT_MIN])),
                                baseline_night=night if night > 0 else None)

    def control_settings(self) -> control.ControlSettings:
        c = self.conf
        return control.ControlSettings(min_interval_min=float(c[CONF_MIN_INTERVAL]), pause_hours=float(c[CONF_PAUSE_HOURS]))

    def is_day(self, local: datetime) -> bool:
        c = self.conf
        return int(c[CONF_DAY_FROM]) <= local.hour < int(c[CONF_DAY_TO])

    # ------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        hist = await self._hist_store.async_load() or {}
        self._resolve_weheat()
        prof = heatpump.profile_for(self.pump_name)
        self.mode = data.get("mode", "shadow")
        self.house = model.HouseModel.from_dict(data.get("house"))
        self.pump = heatpump.HeatPumpModel.from_dict(data.get("pump"), prof) if data.get("pump") else heatpump.HeatPumpModel.for_profile(prof)
        self.mem = control.ControlMemory.from_dict(data.get("control"))
        self.storage_e = float(data.get("storage_e", 0.0))
        self.learn_info = data.get("learn", {})
        self.import_info = data.get("import", {})
        self.hour_log = data.get("hour_log", [])
        self.saving_days = data.get("saving_days", {})
        self.pv_k = data.get("pv_k")
        self.load_profile = data.get("load_profile")
        self.price_seen = {e: {int(k): v for k, v in d.items()} for e, d in (data.get("price_seen") or {}).items()}
        self.check = data.get("check") or {}
        self.changes = data.get("changes") or []
        self.sp_hist = {int(k): v for k, v in (data.get("sp_hist") or {}).items()}
        self.building = data.get("building") if self.conf.get(CONF_USE_BAG) else None
        if self.house.source != "learned" and building.prior(self.building):
            self.house = model.HouseModel(**{**model.PRIOR, **building.prior(self.building)}, source="building register")
        self.ready, self.ready_missing = check.readiness(self.check, None) if self.check else (False, [])
        self._weheat_hours = {int(k): v for k, v in (hist.get("weheat") or {}).items()}
        self._weather_hist = {int(k): tuple(v) for k, v in (hist.get("weather") or {}).items()}
        self._unsubs.append(async_track_time_interval(self.hass, self._async_tick, timedelta(seconds=TICK_SECONDS)))
        self._unsubs.append(async_track_time_change(self.hass, self._async_nightly, hour=LEARN_HOUR, minute=LEARN_MINUTE, second=0))
        self._unsubs.append(async_track_state_change_event(self.hass, [self.conf[CONF_THERMOSTAT]], self._on_thermostat))
        self.hass.async_create_task(self._async_first_run())

    async def _async_building(self) -> None:
        """Opt-in: the building register (BAG via PDOK) around the home location, once (again when the home moves).
        Only the construction year, the floor area and the directions of the outside walls are kept."""
        if not self.conf.get(CONF_USE_BAG):
            return
        lat, lon = round(self.hass.config.latitude, 5), round(self.hass.config.longitude, 5)
        if self.building and abs(self.building.get("lat", 0) - lat) < 1e-4 and abs(self.building.get("lon", 0) - lon) < 1e-4:
            return
        bb = building.bbox(lat, lon)
        session = async_get_clientsession(self.hass)
        try:
            got = {}
            for kind in ("pand", "verblijfsobject"):
                async with session.get(building.WFS.format(kind=kind, **bb), timeout=30) as r:
                    r.raise_for_status()
                    got[kind] = await r.json(content_type=None)
            b = await self.hass.async_add_executor_job(building.parse, got["pand"], got["verblijfsobject"], lat, lon)
        except Exception as err:  # noqa: BLE001 - optional: without it Roost starts from a generic house
            _LOGGER.info("Roost: building register not available: %s", err)
            return
        self.building = {**b, "lat": lat, "lon": lon} if b else {"lat": lat, "lon": lon, "none": True}
        if b and self.house.source != "learned" and building.prior(b):
            self.house = model.HouseModel(**{**model.PRIOR, **building.prior(b)}, source="building register")
        await self.async_save()

    async def _async_first_run(self) -> None:
        await self._async_building()
        await self._async_seed_prices()
        await self._async_tick(None, force_plan=True)
        if self.import_info.get("done") and self.import_info.get("fields", 1) < WEHEAT_FIELDS:
            # imported by an older version: read again, now with the setpoint per hour (needed for the response)
            self.hass.async_create_background_task(self.async_import(WEHEAT_IMPORT_DAYS), f"{DOMAIN} weheat import")
        elif self.conf.get(CONF_IMPORT_ON_SETUP) and not self.import_info.get("done"):
            self.hass.async_create_background_task(self.async_import(WEHEAT_IMPORT_DAYS), f"{DOMAIN} weheat import")
        elif self.house.source != "learned":
            self.hass.async_create_background_task(self.async_learn(), f"{DOMAIN} first learning")

    async def async_stop(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()
        await self.async_save()

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    async def async_save(self) -> None:
        await self._store.async_save({
            "mode": self.mode, "house": self.house.as_dict(), "pump": self.pump.as_dict(), "control": self.mem.as_dict(),
            "storage_e": round(self.storage_e, 3), "learn": self.learn_info, "import": self.import_info,
            "hour_log": self.hour_log[-60:], "saving_days": dict(sorted(self.saving_days.items())[-62:]),
            "pv_k": self.pv_k, "load_profile": self.load_profile, "price_seen": self._price_seen_recent(),
            "check": self.check, "changes": [c for c in self.changes if c["ts"] > time.time() - 30 * 86400],
            "building": self.building,
            "sp_hist": {str(k): v for k, v in self.sp_hist.items() if k > time.time() - SP_HIST_DAYS * 86400}})

    def _price_seen_recent(self) -> dict[str, dict[str, float]]:
        cut = time.time() - 3 * 86400
        self.price_seen = {e: {k: v for k, v in d.items() if k >= cut} for e, d in self.price_seen.items()}
        return {e: {str(k): round(v, 5) for k, v in sorted(d.items())} for e, d in self.price_seen.items()}

    async def _async_seed_prices(self) -> None:
        """Hourly prices of the last two days from the recorder (the state of the price sensor), so hours without a
        forecast yet can be filled with the same hour a day earlier right after setup or a restart."""
        now = dt_util.utcnow()
        start = now - timedelta(hours=49)
        for key in (CONF_IMPORT_PRICE, CONF_EXPORT_PRICE):
            eid = self.conf.get(key) if self.conf.get(CONF_PRICE_MODE) != "fixed" else None
            st = self._state(eid)
            if not eid or st is None:
                continue
            try:
                res = await get_instance(self.hass).async_add_executor_job(
                    partial(rh.state_changes_during_period, self.hass, start, now, entity_id=eid, no_attributes=True,
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
            seen = self.price_seen.setdefault(eid, {})
            for h, v in enumerate(series.hourly(series.slots_from_changes(changes, now.timestamp()), h0, n, fill_last=False)):
                if v is not None:
                    seen.setdefault(h0 + h * 3600, v * scale)

    async def _async_save_history(self) -> None:
        await self._hist_store.async_save({"weheat": {str(k): v for k, v in self._weheat_hours.items()},
                                           "weather": {str(k): list(v) for k, v in self._weather_hist.items()}})

    async def async_set_mode(self, mode: str) -> None:
        self.mode = mode
        self.mem.virtual_sp = None
        self._issue_ready()
        await self.async_save()
        await self._async_tick(None, force_plan=True)

    # ------------------------------------------------------------ Weheat entities
    def _resolve_weheat(self) -> None:
        reg = er.async_get(self.hass)
        dev_id = self.conf.get(CONF_HEAT_PUMP)
        from homeassistant.helpers import device_registry as dr
        dev = dr.async_get(self.hass).async_get(dev_id) if dev_id else None
        self.pump_name = dev.model or dev.name if dev else None
        by_key = {e.translation_key: e.entity_id for e in er.async_entries_for_device(reg, dev_id, include_disabled_entities=False)} if dev_id else {}
        self.ent = {role: by_key[key] for role, key in WEHEAT.items() if key in by_key}

    # ------------------------------------------------------------ reading
    def _state(self, eid: str | None) -> State | None:
        if not eid:
            return None
        st = self.hass.states.get(eid)
        return None if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) else st

    def _num(self, eid: str | None) -> float | None:
        st = self._state(eid)
        return _f(st.state) if st else None

    def _temp(self, eid: str | None) -> float | None:
        st = self._state(eid)
        v = _f(st.state) if st else None
        if v is not None and st.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == UnitOfTemperature.FAHRENHEIT:
            v = (v - 32) * 5 / 9
        return v if v is not None and history.BAD_LOW < v < history.BAD_HIGH else None

    def _kw(self, eid: str | None) -> float | None:
        st = self._state(eid)
        v = _f(st.state) if st else None
        if v is None:
            return None
        u = (st.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or "").lower()
        return v / 1000 if u == "w" else v

    def _sys_to_c(self, v: float | None) -> float | None:
        if v is None:
            return None
        return (v - 32) * 5 / 9 if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else v

    def _c_to_sys(self, v: float) -> float:
        return round(v * 9 / 5 + 32) if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else v

    def room(self) -> float | None:
        r = self._temp(self.conf.get(CONF_ROOM))
        if r is None:
            st = self._state(self.conf[CONF_THERMOSTAT])
            r = self._sys_to_c(_f(st.attributes.get("current_temperature"))) if st else None
        if r is None:
            r = self._temp(self.ent.get("thermostat_room"))
        return r

    def thermostat_sp(self) -> float | None:
        st = self._state(self.conf[CONF_THERMOSTAT])
        return self._sys_to_c(_f(st.attributes.get("temperature"))) if st else None

    def thermostat_reading(self) -> float | None:
        st = self._state(self.conf[CONF_THERMOSTAT])
        return self._sys_to_c(_f(st.attributes.get("current_temperature"))) if st else None

    def pump_state(self) -> str | None:
        st = self._state(self.ent.get("state"))
        return st.state if st else None

    # ------------------------------------------------------------ weather
    async def _async_weather(self) -> None:
        if self.conf.get(CONF_WEATHER_SOURCE) == "entity" and self.conf.get(CONF_WEATHER):
            await self._async_weather_entity()
            return
        if self._weather and time.time() - self._weather_at < WEATHER_MINUTES * 60:
            return
        url = om.FORECAST.format(lat=self.hass.config.latitude, lon=self.hass.config.longitude, past=92)
        try:
            async with async_get_clientsession(self.hass).get(url, timeout=30) as r:
                r.raise_for_status()
                self._weather = om.parse(await r.json())
            self._weather_at = time.time()
            self.sources["weather"] = "Open-Meteo"
        except Exception as err:  # noqa: BLE001
            self.sources["weather"] = f"Open-Meteo unavailable: {err}"

    async def _async_weather_entity(self) -> None:
        eid = self.conf[CONF_WEATHER]
        if self._weather and time.time() - self._weather_at < WEATHER_MINUTES * 60:
            return
        try:
            resp = await self.hass.services.async_call("weather", "get_forecasts", {ATTR_ENTITY_ID: eid, "type": "hourly"},
                                                       blocking=True, return_response=True)
            out = {}
            for x in (resp or {}).get(eid, {}).get("forecast", []):
                ts = series.to_ts(x.get("datetime"))
                t = self._sys_to_c(_f(x.get("temperature")))
                if ts is None or t is None:
                    continue
                ts = int(ts - ts % 3600)
                cloud = _f(x.get("cloud_coverage"))
                wind = _f(x.get("wind_speed"))
                out[ts] = (t, self._clear_sky(ts) * (1 - 0.75 * ((cloud or 0) / 100) ** 3.4), (wind / 3.6) if wind is not None else None)
            self._weather.update(out)
            self._weather_at = time.time()
            self.sources["weather"] = eid
        except Exception as err:  # noqa: BLE001
            self.sources["weather"] = f"{eid} unavailable: {err}"

    def _clear_sky(self, ts: float) -> float:
        import math
        loc = dt_util.as_local(datetime.fromtimestamp(ts + 1800, tz=timezone.utc))
        decl = 23.44 * math.sin(math.radians(360 / 365 * (loc.timetuple().tm_yday - 81)))
        lat = math.radians(self.hass.config.latitude)
        ha = math.radians(15 * (loc.hour + loc.minute / 60 - 12.5))
        s = math.sin(lat) * math.sin(math.radians(decl)) + math.cos(lat) * math.cos(math.radians(decl)) * math.cos(ha)
        return max(0.0, 0.9 * s)

    # ------------------------------------------------------------ energy value
    def _price_series(self, eid: str | None, now: datetime, hours: int) -> list[float] | None:
        st = self._state(eid)
        if st is None:
            return None
        mid = dt_util.start_of_local_day(dt_util.as_local(now)).timestamp()
        slots = series.find_slots(dict(st.attributes), mid)
        cur = _f(st.state)
        scale = series.price_scale(st.attributes.get(ATTR_UNIT_OF_MEASUREMENT), [v for _, _, v in slots] or ([cur] if cur is not None else []))
        if slots:
            raw = [None if v is None else v * scale for v in series.hourly(slots, now.timestamp(), hours, fill_last=False)]
            seen = self.price_seen.setdefault(eid, {})
            base = int(now.timestamp() // 3600 * 3600)
            for h, v in enumerate(raw):
                if v is not None and h > 0:                     # hour 0 is only the rest of the hour: keep the full one
                    seen[base + h * 3600] = v
                elif v is not None:
                    seen.setdefault(base, v)
            vals, guess = series.fill_gaps(raw, now.timestamp(), seen, cur * scale if cur is not None else None)
            self._price_guess[eid] = guess
            return [v or 0.0 for v in vals]
        self._price_guess[eid] = [h > 0 for h in range(hours)]
        return [cur * scale] * hours if cur is not None else None

    def _pv_forecast(self, start: float, hours: int) -> list[float] | None:
        slots = []
        for key in (CONF_PV_FORECAST, CONF_PV_FORECAST_TOMORROW):
            st = self._state(self.conf.get(key))
            if st is not None:
                slots += series.find_slots(dict(st.attributes))
        if slots:
            return series.energy_per_hour(sorted(slots), start, hours)
        if self.conf.get(CONF_PV_POWER) and self.pv_k:
            base = start - start % 3600
            return [self.pv_k * (self._weather.get(int(base + i * 3600)) or (0, 0, 0))[1] for i in range(hours)]
        return None

    def sun_on_house(self, ts: int, wx: tuple) -> float:
        """Radiation driving the solar gain in this hour, for the facade the house model learned (sun.effective)."""
        return sun.effective(ts, wx, self.hass.config.latitude, self.hass.config.longitude, self.house.sun_facade, self.house.sun_vertical)

    def local_hour(self, ts: int) -> int:
        return dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc)).hour

    def _fixed_series(self, now: datetime, hours: int, key: str) -> list[float] | None:
        """A fixed contract per hour ahead (normal / low rate), or the fixed export price."""
        c = self.conf
        base = int(now.timestamp() // 3600 * 3600)
        loc = [dt_util.as_local(datetime.fromtimestamp(base + i * 3600, tz=timezone.utc)) for i in range(hours)]
        if key == CONF_FIXED_EXPORT_PRICE:
            v = _f(c.get(CONF_FIXED_EXPORT_PRICE))
            return None if v is None else [v] * hours
        normal = _f(c.get(CONF_FIXED_PRICE))
        if normal is None:
            return None
        return value.fixed_prices([(x.weekday(), x.hour) for x in loc], normal, _f(c.get(CONF_FIXED_LOW_PRICE)),
                                  int(c.get(CONF_LOW_FROM, 23)), int(c.get(CONF_LOW_TO, 7)), bool(c.get(CONF_LOW_WEEKEND, True)))

    def _energy(self, now: datetime, hours: int) -> tuple[value.EnergyInputs, value.EnergyValue] | None:
        c = self.conf
        if c.get(CONF_PRICE_MODE) == "fixed":
            imp = self._fixed_series(now, hours, CONF_FIXED_PRICE)
            exp = self._fixed_series(now, hours, CONF_FIXED_EXPORT_PRICE)
            self._price_guess[CONF_FIXED_PRICE] = [False] * hours
            if imp is None:
                self.sources["price"] = "missing"
                return None
            self.sources["price"] = "fixed"
        else:
            imp = self._price_series(c.get(CONF_IMPORT_PRICE), now, hours)
            if imp is None:
                self.sources["price"] = "missing"
                return None
            self.sources["price"] = "ok"
            exp = self._price_series(c.get(CONF_EXPORT_PRICE), now, hours) if c.get(CONF_EXPORT_PRICE) else None
        surplus = value.solar_export_now(self._kw(c.get(CONF_GRID_POWER)), self._kw(c.get(CONF_BATTERY_POWER)),
                                         self._kw(c.get(CONF_PV_POWER)), c.get(CONF_GRID_SIGN, "import_positive") == "import_positive")
        soc = self._num(c.get(CONF_BATTERY_SOC))
        load = None
        if self.load_profile and len(self.load_profile) == 24:
            h0 = dt_util.as_local(now).hour
            load = [self.load_profile[(h0 + i) % 24] for i in range(hours)]
        inp = value.EnergyInputs(import_price=imp, export_price=exp, pv_kwh=self._pv_forecast(now.timestamp(), hours), load_kwh=load,
                                 surplus_now_kw=surplus, battery_soc=soc,
                                 battery_kwh=_f(c.get(CONF_BATTERY_KWH)) if soc is not None else None,
                                 battery_reserve=_f(c.get(CONF_BATTERY_RESERVE)) or 10.0, battery_max_kw=_f(c.get(CONF_BATTERY_KW)) or 5.0,
                                 grid_preference=_f(c.get(CONF_GRID_PREFERENCE)) or 0.0)
        return inp, value.compute(inp)

    # ------------------------------------------------------------ the run
    async def _async_tick(self, _now: datetime | None, force_plan: bool = False) -> None:
        now = dt_util.utcnow()
        t = now.timestamp()
        try:
            if not self.ent:
                self._resolve_weheat()
            await self._async_weather()
            self._track_storage(t)
            self._track_hour(t)
            self._count_cost(now)
            self._log_hour(now)
            self._check_health(t)
            due = force_plan or self.plan_at is None or t - self.plan_at >= PLAN_MINUTES * 60
            if due and not self._planning:
                await self._async_plan(now)
            await self._async_control(t)
        except Exception:  # noqa: BLE001 - one bad run must not stop the integration
            _LOGGER.exception("Roost run failed")
        self._last_tick = t
        self._notify()

    def _track_storage(self, t: float) -> None:
        """Heat in the floor/water: + heat the pump delivers for space heating, − the learned release to the room."""
        if self._last_tick is None:
            return
        dt_h = min(0.5, max(0.0, (t - self._last_tick) / 3600))
        q = 0.0
        if self.pump_state() == "heating":
            q = max(0.0, (self._kw(self.ent.get("power_out")) or 0.0))
        lag = max(0.0, self.house.lag)
        keep = (lag / (1 + lag)) ** dt_h if lag > 0 else 0.0
        self.storage_e = max(0.0, min(20.0, (self.storage_e + q * dt_h) * keep))

    def _count_cost(self, now: datetime) -> None:
        day = dt_util.as_local(now).date().isoformat()
        if self._cost_day != day:
            if self._cost_day is not None:
                self.hass.async_create_task(self._async_close_day(self._cost_day))
            self._cost_day, self.cost_today, self.kwh_today = day, 0.0, 0.0
        e = (self._num(self.ent.get("elec")) or 0.0) + (self._num(self.ent.get("elec_defrost")) or 0.0)
        if e and self._last_elec is not None and 0 <= e - self._last_elec < 5:
            d = e - self._last_elec
            price = self.plan_hours[0].p_grid if self.plan_hours else 0.0
            self.kwh_today += d
            self.cost_today += d * price
        if e:
            self._last_elec = e

    def _log_hour(self, now: datetime) -> None:
        """Once per hour: what the thermostat had and the inputs, so the day can be replayed for the saving."""
        hour = int(now.timestamp() // 3600 * 3600)
        if self.hour_log and self.hour_log[-1]["ts"] == hour:
            return
        room = self.room()
        sp = self.thermostat_sp() if self.mode == "active" or self.mem.virtual_sp is None else self.mem.virtual_sp
        wx = self._weather.get(hour)
        if room is None or sp is None or wx is None or not self.plan_hours:
            return
        h = self.plan_hours[0]
        self.hour_log.append({"ts": hour, "T": round(room, 2), "E": round(self.storage_e, 2), "sp": sp, "sp_t": self.thermostat_sp(),
                              "t_out": wx[0], "rad": round(self.sun_on_house(hour, wx), 4), "hour": dt_util.as_local(now).hour,
                              "wind": wx[2] if wx[2] is not None else 3.5, "p_grid": h.p_grid, "p_own": h.p_own, "own": h.own_kw,
                              "day": self.is_day(dt_util.as_local(now))})
        self.hour_log = self.hour_log[-60:]

    async def _async_close_day(self, day: str) -> None:
        """Replay yesterday with what Roost set and with a steady thermostat, from the same start (same model, same
        weather, same prices): the difference is the saving."""
        entries = [e for e in self.hour_log if dt_util.as_local(datetime.fromtimestamp(e["ts"], tz=timezone.utc)).date().isoformat() == day]
        if len(entries) < 20:
            return
        res = await self.hass.async_add_executor_job(planner.replay_day, self.house, self.pump, self.settings(), entries)
        if res is not None:
            self.saving_days[day] = round(res[1] - res[0], 3)
            await self.async_save()

    def saving_month(self) -> float:
        month = dt_util.now().date().isoformat()[:7]
        return round(sum(v for k, v in self.saving_days.items() if k.startswith(month)), 2)

    def _hours_ahead(self, now: datetime, prices: list[value.HourPrices]) -> list[planner.HourIn]:
        base = int(now.timestamp() // 3600 * 3600)
        out = []
        last = None
        for i, p in enumerate(prices):
            wx = self._weather.get(base + i * 3600) or last
            if wx is None:
                t_out = self._num(self.ent.get("outdoor"))
                if t_out is None:
                    return []
                wx = (t_out - self.pump.bias, 0.0, 3.5)
            last = wx
            loc = dt_util.as_local(datetime.fromtimestamp(base + i * 3600, tz=timezone.utc))
            dhw = self.pump.dhw_share(loc.weekday(), loc.hour)
            if i == 0 and self.pump_state() in DHW_STATES:
                dhw = max(dhw, 0.5)                     # making hot water right now
            out.append(planner.HourIn(t_out=wx[0], wind=wx[2] if wx[2] is not None else 3.5, rad=self.sun_on_house(base + i * 3600, wx),
                                      p_grid=p.p_grid, p_own=p.p_own, own_kw=p.own_kw, day=self.is_day(loc), hour=loc.hour, dhw=dhw,
                                      extra_kw=check.fade(self.corr_kw, i)))
        return out

    async def _async_plan(self, now: datetime) -> None:
        self._planning = True
        try:
            e = self._energy(now, 36)                 # plan 36 h, show 24: the end of the horizon does not distort what is shown
            room = self.room()
            if e is None or room is None:
                self.reason = Reason("no_price" if e is None else "no_room")
                return
            inp, ev = e
            prices = value.planner_prices(inp, ev)
            self.corr_kw, self.corr_n = check.correction(self.hour_log, self.house, self.pump, now.timestamp())
            hours = self._hours_ahead(now, prices)
            if not hours:
                self.reason = Reason("no_weather")
                return
            s = self.settings()
            w_now = self._kw(self.ent.get("power_out")) if self.pump_state() == "heating" else 0.0
            p = await self.hass.async_add_executor_job(planner.plan, self.house, self.pump, s, hours, room, self.storage_e,
                                                       self.thermostat_sp(), 24, w_now)
            self.plan, self.plan_hours, self.plan_at = p, hours, now.timestamp()
            self.plan_tariff = list(inp.import_price)
            self.plan_guess = [] if self.conf.get(CONF_PRICE_MODE) == "fixed" else list(self._price_guess.get(self.conf.get(CONF_IMPORT_PRICE)) or [])
            self.reason = planner.explain(p, hours, room, s, self.pump, self.house)
        finally:
            self._planning = False

    async def _async_control(self, t: float) -> None:
        if self.mode == "off" or self.plan is None or self.plan.first is None:
            self.decision = control.Decision(None, Reason("off") if self.mode == "off" else self.reason, self.thermostat_sp())
            return
        d = control.decide(t, self.plan.first.sp, self.thermostat_sp(), self.room(), float(self.conf[CONF_DAY_MIN]) if self.plan_hours and self.plan_hours[0].day else float(self.conf[CONF_NIGHT_MIN]),
                           self.mem, self.control_settings(), self.mode == "active")
        self.decision = d
        if d.setpoint is not None and self.mode == "active":
            ctx = Context()
            self._contexts[ctx.id] = time.time()
            try:
                await self.hass.services.async_call("climate", "set_temperature",
                                                    {ATTR_ENTITY_ID: self.conf[CONF_THERMOSTAT], "temperature": self._c_to_sys(d.setpoint)},
                                                    blocking=True, context=ctx)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Roost could not set the thermostat: %s", err)
        if d.setpoint is not None:
            await self.async_save()

    @callback
    def _on_thermostat(self, event: Event) -> None:
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if old is None or new is None or event.context.id in self._contexts or self.mode != "active":
            return
        a, b = _f(old.attributes.get("temperature")), _f(new.attributes.get("temperature"))
        if a is None or b is None or abs(a - b) < 0.05:
            return
        if self.mem.last_write and time.time() - self.mem.last_write < 60:
            return                                   # our own change coming back
        self.mem.pause_until = time.time() + self.control_settings().pause_hours * 3600
        room = self.room()
        self.changes.append({"ts": round(time.time()), "from": a, "to": b, "room": round(room, 2) if room is not None else None})
        self.hass.async_create_task(self.async_save())
        self._notify()

    # ------------------------------------------------------------ health (repairs)
    def _issue(self, key: str, active: bool, fixable: bool = False, placeholders: dict | None = None,
               translation_key: str | None = None, data: dict | None = None) -> None:
        iid = f"{self.entry.entry_id}_{key}"
        if active and key not in self.health.issues:
            ir.async_create_issue(self.hass, DOMAIN, iid, is_fixable=fixable, severity=ir.IssueSeverity.WARNING,
                                  translation_key=translation_key or key,
                                  data={"entry_id": self.entry.entry_id, "issue": key, **(data or {})} if fixable else None,
                                  translation_placeholders={"name": self.entry.title, **(placeholders or {})})
            self.health.issues.add(key)
        elif not active and key in self.health.issues:
            ir.async_delete_issue(self.hass, DOMAIN, iid)
            self.health.issues.discard(key)

    def _issue_comfort(self) -> None:
        """A comfort setting suggested from the changes made by hand (comfort.suggest); the user accepts or ignores it."""
        c = self.conf

        def local(ts: float) -> tuple[str, int]:
            loc = dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc))
            return loc.date().isoformat(), loc.hour
        def local_minute(ts: float) -> tuple[str, int]:
            loc = dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc))
            return loc.date().isoformat(), loc.hour * 60 + loc.minute
        sched = comfort.scheduled(self.changes, local_minute, time.time())
        self._issue("thermostat_schedule", bool(sched), placeholders={
            "times": ", ".join(f"{s['minute'] // 60:02d}:{s['minute'] % 60:02d} → {s['to']:g} °C" for s in sched)})
        by_schedule = {t for s in sched for t in s["ts"]}
        own = [x for x in self.changes if x["ts"] not in by_schedule]
        sug = comfort.suggest(own, local, time.time(), int(c[CONF_DAY_FROM]), int(c[CONF_DAY_TO]),
                              float(c[CONF_COMFORT]), float(c[CONF_DAY_MIN]))
        if self.suggestion is not None and (sug is None or sug.as_dict() != self.suggestion.as_dict()):
            self._issue("comfort", False)
        self.suggestion = sug
        if sug is not None:
            cur = {"comfort": c[CONF_COMFORT], "day_from": c[CONF_DAY_FROM], "day_to": c[CONF_DAY_TO]}[sug.key]
            fmt = (lambda v: f"{float(v):g}") if sug.key == "comfort" else (lambda v: f"{int(v)}:00")
            self._issue("comfort", True, fixable=True, translation_key=f"suggest_{sug.kind}", data=sug.as_dict(),
                        placeholders={"current": fmt(cur), "value": fmt(sug.value), "days": str(sug.days), "count": str(sug.count)})

    async def async_accept_suggestion(self, key: str, value: float) -> None:
        """The user accepted a suggested comfort setting: store it (the entry reloads) and start counting afresh."""
        self.changes = []
        self.suggestion = None
        await self.async_save()
        v = int(value) if key in (CONF_DAY_FROM, CONF_DAY_TO) else float(value)
        self.hass.config_entries.async_update_entry(self.entry, options={**self.entry.options, key: v})

    def _issue_ready(self) -> None:
        """Tell the user once the self-check says Roost can steer (only while in shadow mode; the user decides)."""
        rmse = self.check.get("rmse_6h")
        self._issue("ready_for_active", self.mode == "shadow" and self.ready, fixable=True,
                    placeholders={"rmse": f"{rmse:.2f}" if rmse is not None else "?",
                                  "hours": str(self.check.get("heating_hours", 0)), "days": str(self.check.get("days", 0))})

    def _track_hour(self, t: float) -> None:
        """Per hour: seconds on hot water (an hour on hot water is not a model error) and the heat delivered to the house
        (where the unit's output starts in the next hour), for the correction."""
        hour = int(t // 3600 * 3600)
        if self._acc_hour != hour:
            if self._acc_hour is not None:
                for e in reversed(self.hour_log[-3:]):
                    if e["ts"] == self._acc_hour:
                        e["dhw"] = round(min(1.0, self._dhw_acc / 3600), 2)
                        e["q"] = round(self._heat_acc, 2)
                a = self._sp_acc
                if a[1] >= 1800:                      # at least half the hour seen
                    self.sp_hist[self._acc_hour] = [round(a[0] / a[1], 2), round(a[2] / a[3], 2) if a[3] >= 1800 else None]
            self._acc_hour, self._dhw_acc, self._heat_acc = hour, 0.0, 0.0
            self._sp_acc = [0.0, 0.0, 0.0, 0.0]
        if self._last_tick is None:
            return
        dt = min(600.0, max(0.0, t - self._last_tick))
        sp, reading = self.thermostat_sp(), self.thermostat_reading()
        if sp is not None:
            self._sp_acc[0] += sp * dt
            self._sp_acc[1] += dt
        if reading is not None:
            self._sp_acc[2] += reading * dt
            self._sp_acc[3] += dt
        state = self.pump_state()
        if state in DHW_STATES:
            self._dhw_acc += dt
        elif state == "heating":
            self._heat_acc += max(0.0, self._kw(self.ent.get("power_out")) or 0.0) * dt / 3600

    def _dhw_samples(self, rows: list[model.HourRow]) -> list[tuple[int, int, float]]:
        """(local weekday, local hour, share on hot water) of the last weeks, Weheat logs first."""
        since = time.time() - DHW_WEEKS * 7 * 86400
        src = {t: v["dhw_s"] for t, v in self._weheat_hours.items() if t >= since and "dhw_s" in v}
        if len(src) < 7 * 24:
            src = {r.ts: r.dhw_s for r in rows if r.ts >= since}
        out = []
        for t, secs in src.items():
            loc = dt_util.as_local(datetime.fromtimestamp(t, tz=timezone.utc))
            out.append((loc.weekday(), loc.hour, secs / 3600))
        return out

    def _check_health(self, t: float) -> None:
        # the heat pump heats while the thermostat asks for no heat: it is on its own heating curve
        demand = self._num(self.ent.get("water_setpoint"))
        heating = self.pump_state() == "heating" and (self._kw(self.ent.get("power_in")) or 0.0) > 0.4
        if heating and demand is not None and demand <= 15:
            self.health.not_following_since = self.health.not_following_since or t
        else:
            self.health.not_following_since = None
        self._issue("not_following", bool(self.health.not_following_since and t - self.health.not_following_since > NOT_FOLLOWING_MIN * 60))
        if self.room() is None:
            self.health.room_missing_since = self.health.room_missing_since or t
        else:
            self.health.room_missing_since = None
        self._issue("room_missing", bool(self.health.room_missing_since and t - self.health.room_missing_since > ROOM_SILENT_MIN * 60))
        self._issue("weheat_missing", not self.ent)

    @property
    def following(self) -> bool | None:
        if not self.ent.get("water_setpoint"):
            return None
        return not (self.health.not_following_since and time.time() - self.health.not_following_since > NOT_FOLLOWING_MIN * 60)

    # ------------------------------------------------------------ services
    async def async_pause(self, hours: float) -> None:
        self.mem.pause_until = time.time() + hours * 3600
        await self.async_save()
        self._notify()

    async def async_resume(self) -> None:
        self.mem.pause_until = None
        self.mem.last_write = None
        await self.async_save()
        await self._async_tick(None, force_plan=True)

    # ------------------------------------------------------------ learning
    async def _async_nightly(self, _now: datetime) -> None:
        await self._async_refresh_weheat()
        await self.async_learn()

    async def _async_refresh_weheat(self) -> None:
        """The hours since the last import, from Weheat (read-only), so learning and the self-check use the unit's own
        meters and states. Skipped quietly when the Weheat login is not available."""
        if not self.import_info.get("done") or not self._weheat_hours or self.importing:
            return
        pump, weheat_entry = heat_pump_id(self.hass, self.conf.get(CONF_HEAT_PUMP))
        if not pump or not weheat_entry:
            return
        end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        start = max(end - timedelta(days=30), datetime.fromtimestamp(max(self._weheat_hours) - 3 * 3600, tz=timezone.utc))
        try:
            logs, energy = await async_fetch_history(self.hass, weheat_entry, pump, start, end)
        except Exception as err:  # noqa: BLE001 - learn with what there is
            _LOGGER.debug("Roost: Weheat refresh skipped: %s", err)
            return
        self._weheat_hours.update(history.weheat_hours(logs, energy))
        await self._async_save_history()

    async def async_learn(self) -> None:
        if self._learning:
            return
        self._learning = True
        try:
            from .learning import async_rows
            rows, extra = await async_rows(self)
            # hours without the setpoint in the Weheat logs (an on/off thermostat): Roost's own record of the thermostat
            rows = [replace(r, sp=self.sp_hist[r.ts][0] if r.sp is None else r.sp,
                            T_th=self.sp_hist[r.ts][1] if r.T_th is None else r.T_th) if r.ts in self.sp_hist else r for r in rows]
            wx_all = {**self._weather_hist, **self._weather}
            lat, lon = self.hass.config.latitude, self.hass.config.longitude

            def eff(ts: int, facade: float, vertical: float) -> float:
                wx = wx_all.get(ts)
                return sun.effective(ts, wx, lat, lon, facade, vertical) if wx else 0.0
            hours = {r.ts: self.local_hour(r.ts) for r in rows}
            house = await self.hass.async_add_executor_job(model.learn, rows, self.house, eff, hours.__getitem__,
                                                           building.prior(self.building), building.facades(self.building, model.FACADES))
            # from here on the rows carry the sun on the learned facade and their local hour
            hm = house.model
            rows = [replace(r, rad=eff(r.ts, hm.sun_facade, hm.sun_vertical) if hm.sun_vertical > 0 else r.rad, hour=hours[r.ts]) for r in rows]
            pump, note = await self.hass.async_add_executor_job(heatpump.learn, rows, self.pump)
            pump, note_r = await self.hass.async_add_executor_job(response.learn, rows, house.model, pump)
            note = "; ".join(x for x in (note, note_r) if x)
            samples = self._dhw_samples(rows)
            prof = response.dhw_profile(samples)
            if prof:
                pump.dhw, pump.dhw_weeks = prof, round(len(samples) / 168, 1)
            self.house, self.pump = house.model, pump
            self.check = await self.hass.async_add_executor_job(check.self_check, rows, self.house, self.pump)
            self.check["at"] = dt_util.now().isoformat(timespec="seconds")
            lever = not (self.pump.resp_source == "learned" and self.pump.k is not None and self.pump.k < NO_LEVER_KW)
            self._issue("no_lever", not lever, placeholders={"k": f"{self.pump.k or 0:.2f}"})
            self.ready, self.ready_missing = check.readiness(self.check, self.following, lever)
            self._issue_ready()
            self._issue_comfort()
            if extra.get("pv_k"):
                self.pv_k = extra["pv_k"]
            if extra.get("load_profile"):
                self.load_profile = extra["load_profile"]
            self.learn_info = {"at": dt_util.now().isoformat(timespec="seconds"), "house": house.reason, "scores": house.scores,
                               "heat_pump": note, "rows": len(rows), "heating_hours": sum(1 for r in rows if r.Q > 0.3),
                               "rows_with_setpoint": sum(1 for r in rows if r.sp is not None),
                               "rows_with_room_sensor": sum(1 for r in rows if r.room_sensor),
                               "rows_with_thermostat_reading": sum(1 for r in rows if r.T_th is not None),
                               "last_row": datetime.fromtimestamp(max(r.ts for r in rows), tz=timezone.utc).isoformat() if rows else None,
                               "weheat_hours": sum(1 for r in rows if r.ts in self._weheat_hours)}
            self._issue("learning_failed", False)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Roost learning failed")
            self._issue("learning_failed", True)
        finally:
            self._learning = False
        await self.async_save()
        await self._async_tick(None, force_plan=True)

    async def async_import(self, days: int = WEHEAT_IMPORT_DAYS) -> None:
        """Read the heat pump's history from Weheat (read-only), then learn."""
        if self.importing:
            return
        pump, weheat_entry = heat_pump_id(self.hass, self.conf.get(CONF_HEAT_PUMP))
        if not pump or not weheat_entry:
            self.import_info = {"status": "no Weheat heat pump found"}
            return
        self.importing = True
        end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        self.import_info = {"status": "importing", "from": start.isoformat(), "to": end.isoformat()}
        self._notify()

        def progress(t: datetime) -> None:
            self.import_info["at"] = t.isoformat()
            self._notify()
        try:
            logs, energy = await async_fetch_history(self.hass, weheat_entry, pump, start, end, progress)
            rows = history.weheat_hours(logs, energy)
            self._weheat_hours.update(rows)
            await self._async_save_history()
            first = min(rows) if rows else None
            self.import_info = {"status": "done", "done": True, "fields": WEHEAT_FIELDS, "hours": len(rows),
                                "from": first and datetime.fromtimestamp(first, tz=timezone.utc).isoformat(),
                                "to": end.isoformat(), "at": dt_util.now().isoformat(timespec="seconds")}
        except WeheatUnavailable as err:
            self.import_info = {"status": f"waiting for the Weheat login ({err})"}
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Roost: Weheat import failed")
            self.import_info = {"status": f"failed: {err}"}
        finally:
            self.importing = False
        await self.async_save()
        if self.import_info.get("done"):
            await self.async_learn()
        self._notify()
