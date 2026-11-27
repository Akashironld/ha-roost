"""Runtime of one Roost entry: read sources, keep track of stored heat, plan, steer the thermostat, learn.

Split by subject: prices (prices.py), the Weheat login and history (weheat_sync.py), the hourly log and the look back
(hourlog.py), notices and watching for a window open (health.py); shared imports and constants in mgr_common.py."""
from __future__ import annotations

from . import curve, prices, replan, savings, weatherfetch
from .cardstate import Card
from .care import Care
from .const import (
    CONF_CONTROL,
    CONF_OT_FLOW,
    CONF_OT_START_KWH,
    START_GRACE_S,
)
from .core import hourlog as chl
from .core import meters as cmeters
from .core import plan as cplan
from .core import prices as cprices
from .core import weather as cweather
from .core import weheat as cweheat
from .health import Notices
from .hourlog import HourLog
from .learner import Learner
from .mgr_common import (  # the shared imports and constants  # noqa: F401
    _LOGGER,
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    AWAY_MIN,
    CONF_BASELINE_NIGHT,
    CONF_COMFORT,
    CONF_DAY_FROM,
    CONF_DAY_MIN,
    CONF_DAY_TO,
    CONF_EMITTER,
    CONF_HEAT_PUMP,
    CONF_IMPORT_ON_SETUP,
    CONF_IMPORT_PRICE,
    CONF_MAX_ABOVE,
    CONF_MIN_INTERVAL,
    CONF_NIGHT_MIN,
    CONF_PAUSE_HOURS,
    CONF_PRICE_MODE,
    CONF_PV_FORECAST,
    CONF_PV_POWER,
    CONF_ROOM,
    CONF_SP_MIN,
    CONF_STORE_MAX,
    CONF_THERMOSTAT,
    CONF_USE_BAG,
    CONF_WEATHER,
    CONF_WEATHER_SOURCE,
    DEFAULTS,
    DHW_STATES,
    DHW_WEEKS,
    DOMAIN,
    EVENT_HOMEASSISTANT_STOP,
    EVENTS_KEPT,
    FALLBACK_MIN,
    FALLBACK_NOTICE_H,
    HISTORY_KEEP_DAYS,
    HOUR_LOG_KEPT,
    HYBRID_MAX_ABOVE,
    LEARN_HOUR,
    LEARN_MINUTE,
    MIN_RUN_MIN,
    NO_LEVER_KW,
    PLAN_LOG_KEPT,
    PLAN_MINUTES,
    SAVING_DETAIL_DAYS,
    SP_HIST_DAYS,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    STORAGE_VERSION,
    TICK_SECONDS,
    WEATHER_MINUTES,
    WEHEAT,
    WEHEAT_FIELDS,
    WEHEAT_IMPORT_DAYS,
    Any,
    Callable,
    ClientTimeout,
    ConfigEntry,
    Context,
    Event,
    EventStateChangedData,
    Health,
    HomeAssistant,
    Reason,
    State,
    Store,
    UnitOfTemperature,
    _f,
    _i,
    _iso_ts,
    async_get_clientsession,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
    asyncio,
    building,
    callback,
    check,
    comfort,
    control,
    datetime,
    deque,
    dt_util,
    er,
    heatpump,
    history,
    model,
    om,
    partial,
    planner,
    replace,
    response,
    rooms,
    schedule,
    series,
    stick,
    sun,
    time,
    timedelta,
    timezone,
    traceback,
    value,
    window,
)
from .otmgr import OpenTherm
from .reader import Reader
from .weheat_sync import WeheatSync

AIR_FRESH_S = 1800      # the unit's air sensor counts when it reported within this (defrost.anomaly_ahead)


class RoostManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.read = Reader(hass)                    # entity states as numbers, °C, kW (reader.py)
        self.conf_key: str | None = None            # the options that need a reload (set by __init__.py)
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._hist_store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.history")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._contexts: dict[str, float] = {}
        self.mode = "shadow"
        self.ent: dict[str, str] = {}               # weheat role -> entity_id
        self.pump_name: str | None = None
        self.house = model.HouseModel()
        self.pump = heatpump.HeatPumpModel()
        self.mem = control.ControlMemory()
        self.corr_slow = 0.0                        # kW: yesterday's missed heat carried into the plan (check.slow_correction)
        self.otc = OpenTherm(self)                  # OpenTherm steering and its state (otmgr.py, opentherm.py)
        self.held = cplan.Held()                    # the plan in force and what it was made with (core/plan.py)
        self.meters = cmeters.Meters()              # heat stored, today's electricity and cost, runs, defrosts (core/meters.py)
        self.weheat = cweheat.Weheat()              # the unit's hours, settings, data and import from Weheat (core/weheat.py)
        self.wh = WeheatSync(self)                  # talking to Weheat (weheat_sync.py)
        # prices seen (retained history, never a source of unpublished future tariffs), day-ahead prices (core/prices.py)
        self.prices = cprices.Prices()
        self.reason = Reason("starting")
        self.decision: control.Decision | None = None
        self.sources: dict[str, str] = {}
        self.learn_info: dict = {}
        self._watch = stick.Watch()
        self._heating_since: float | None = None    # the unit has been heating since (MIN_RUN_MIN)
        self._airing_from: float | None = None      # the setpoint before Roost lowered it for an open window (contact)
        self.window = window.WindowWatch()          # airing: Roost waits and does not learn from those hours
        self.curve_advice: curve.CurveAdvice | None = None     # the heating curve the house needs
        self.notices: Notices = Notices(self)              # repairs, ready to steer, a window open (health.py)
        self.care: Care = Care(self)                    # notifications, the thermostat, away, settings from the card (care.py)
        self.card: Card = Card(self)                    # what the card shows beside the plan (cardstate.py)
        self._started_at = 0.0          # time.time() of async_start
        self._last_tick: float | None = None
        self.pv_k: float | None = None              # kW of PV per kW/m² of radiation (learned)
        self.load_profile: list[float] | None = None
        self.health = Health()
        self.weather = cweather.Weather()           # the forecast and the weather history (core/weather.py)
        self._planning = False
        self.learner: Learner = Learner(self)       # learning the house, the unit and the rooms (learner.py)
        self.check: dict = {}                       # nightly self-check (check.self_check)
        self.changes: list[dict] = []               # changes by hand while active: {"ts", "from", "to", "room"}
        self.building: dict | None = None           # opt-in BAG data: {"lat", "lon", "year", "area_m2", "walls"} (no address)
        # extra rooms (subentries of type "room"): the heat pump heats them too, Roost keeps their minimums
        self.rooms: list[rooms.Room] = [
            rooms.Room(id=sid, name=sub.title, sensor=sub.data["sensor"], kind=sub.data.get("kind", "other"),
                       minimum=_f(sub.data.get("minimum")), hour_from=_i(sub.data.get("hour_from")), hour_to=_i(sub.data.get("hour_to")))
            for sid, sub in getattr(entry, "subentries", {}).items() if sub.subentry_type == "room" and sub.data.get("sensor")]
        self.room_models: dict[str, rooms.RoomModel] = {}
        self.suggestion: comfort.Suggestion | None = None
        # what Roost did and why, for a bug report (diagnostics): thermostat changes, changes by hand, mode, learning,
        # import, repairs, plans that could not be made, errors
        self.events: deque = deque(maxlen=EVENTS_KEPT)
        self._tasks: set[asyncio.Task] = set()
        self._stop_unsub: Callable[[], None] | None = None
        self._last_reason_code: str | None = None
        self.ready: bool = False
        self.ready_missing: list[str] = []
        self.ready_muted: bool = False                  # the user asked not to be told 'ready to steer' again
        self.corr_kw, self.corr_n = 0.0, 0   # correction from the last hours (check.correction)
        self.log = chl.Logs()                       # the hour log, plan log, predictions, day numbers (core/hourlog.py)
        self.acc = chl.HourAcc()                    # the hour in progress
        self.hl = HourLog(self)                     # the hour log's side in Home Assistant (hourlog.py)

    # ------------------------------------------------------------ config
    @property
    def conf(self) -> dict:
        return {**DEFAULTS, **self.entry.data, **self.entry.options}

    @property
    def hybrid(self) -> bool:
        """A gas boiler next to the heat pump (history.is_hybrid)."""
        return cweheat.hybrid(self.weheat)

    def settings(self) -> planner.Settings:
        c = self.conf
        night = _f(c.get(CONF_BASELINE_NIGHT)) or 0.0
        above = float(c[CONF_MAX_ABOVE])
        if self.hybrid:
            above = min(above, HYBRID_MAX_ABOVE)    # a hybrid: a setpoint far above the room calls the gas boiler
        ot: dict[str, Any] = {}
        if self.ot:
            # the settings are starting values: what the unit showed over OpenTherm replaces them (otlearn.py)
            L = self.otc.learned
            ot = dict(ot=True, ot_q_min=self.otc.q_min(),
                      ot_start_kwh=L.start_kwh if L.start_kwh is not None else float(c[CONF_OT_START_KWH]))
            # ot_cop_low: the planner's fixed value, not learned (22-11-2026: learning it from the measured output put that
            # output on both sides of the fit, and in the simulations it reached only half of what a fixed value gives)
            if self.pump.indoor_run_kw is not None:      # the indoor unit's pumps while it heats (outside the COP)
                ot["ot_run_kw"] = self.pump.indoor_run_kw
            ot["ot_max_starts"] = int(c.get("ot_max_starts", 0) or 0)
            ot["ot_quiet"] = self.otc.quiet()
        return planner.Settings(comfort=float(c[CONF_COMFORT]), day_min=float(c[CONF_DAY_MIN]), night_min=float(c[CONF_NIGHT_MIN]),
                                store_max=max(float(c[CONF_STORE_MAX]), float(c[CONF_COMFORT])), max_above_room=above,
                                sp_min=float(c.get(CONF_SP_MIN, c[CONF_NIGHT_MIN])),
                                baseline_night=night if night > 0 else None,
                                away_min=float(self.mem.away_min) if self.mem.away_min is not None else AWAY_MIN, **ot)

    def control_settings(self) -> control.ControlSettings:
        c = self.conf
        return control.ControlSettings(min_interval_min=float(c[CONF_MIN_INTERVAL]), pause_hours=float(c[CONF_PAUSE_HOURS]))

    def is_away(self, ts: float | None = None) -> bool:
        u = self.mem.away_until
        return bool(u and (ts if ts is not None else time.time()) < u)

    def is_day(self, local: datetime) -> bool:
        return schedule.is_comfort(self.conf, local)

    # ------------------------------------------------------------ OpenTherm or thermostat (the steering itself: otmgr.py)
    @property
    def ot(self) -> bool:
        """Roost steers the flow through an OpenTherm master (not a room setpoint on a thermostat)."""
        return self.conf.get(CONF_CONTROL) == "opentherm"


    def planned_level(self, t: float) -> float | None:
        return cplan.level(self.held.plan, self.held.at, t)

    def _own_context(self) -> Context:
        ctx = Context()
        self._contexts[ctx.id] = time.time()
        return ctx

    def is_own_context(self, context_id: str) -> bool:
        """A state change made by Roost itself (not by hand)."""
        return context_id in self._contexts

    # ------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        hist = await self._hist_store.async_load() or {}
        self._resolve_weheat()
        prof = heatpump.profile_for(self.pump_name)
        self.mode = data.get("mode", "shadow")
        self.house = model.HouseModel.from_dict(data.get("house"))
        if data.get("pump"):
            self.pump = heatpump.HeatPumpModel.from_dict(data.get("pump"), prof)
        else:
            self.pump = heatpump.HeatPumpModel.for_profile(prof)
            self.pump.alpha = round(self.pump.alpha + curve.emitter_profile(self.conf)[2], 3)
        self.mem = control.ControlMemory.from_dict(data.get("control"))
        self.otc.restore(data.get("ot") or {})
        self.meters = cmeters.Meters.restore(data)
        self._age_storage(data.get("storage_at"), time.time())
        self.learn_info = data.get("learn", {})
        self.log = chl.Logs.restore(data)
        self.held = cplan.Held.restore(data)
        # a plan held from before a restart was made by the code and settings then (21-11-2026: a new correction was not
        # used for hours): plan afresh once
        self._replan_on_start = self.held.commit is not None
        self._started_at = time.time()
        last = self.hl.restore(data.get("acc"), time.time())
        if last is not None:
            self.meters = replace(self.meters, last_elec=last[0], last_indoor=last[1])
        self.card.restore(data)
        if self.meters.runs and self.meters.runs[-1][1] is None:
            self._heating_since = self.meters.runs[-1][0]  # a run that went on over the restart
        self.window.hours = set(int(h) for h in (data.get("window_hours") or []))
        self.pv_k = data.get("pv_k")
        self.load_profile = data.get("load_profile")
        self.prices = cprices.Prices.restore(data)
        self.check = data.get("check") or {}
        self.changes = data.get("changes") or []
        self.room_models = {k: rooms.RoomModel.from_dict(v) for k, v in (data.get("room_models") or {}).items()}
        self.events.extend(data.get("events") or [])
        self.weheat = cweheat.Weheat.restore(data, hist, self.events)
        self.event("start", mode=self.mode)
        self.building = data.get("building") if self.conf.get(CONF_USE_BAG) else None
        self.curve_advice = curve.CurveAdvice.from_dict(data.get("curve"))
        if self.house.source != "learned":
            self.house = model.HouseModel(**self.learner.house_start(), source="building register" if building.prior(self.building) else "default")
        self.ready_muted = bool(data.get("ready_muted"))
        self.notices.update_ready(at_start=True)  # the same readiness as at night (issue #11: on restart it skipped lever and following)
        self.weather = cweather.Weather.restore(hist)
        self.otc.restore_samples(hist)     # OpenTherm: samples of the unit while it heats, in the history store
        self._unsubs.append(async_track_time_interval(self.hass, self._async_tick, timedelta(seconds=TICK_SECONDS)))
        self._unsubs.append(async_track_time_change(self.hass, self.learner.async_nightly, hour=LEARN_HOUR, minute=LEARN_MINUTE, second=0))
        self._unsubs.append(async_track_time_change(self.hass, self.care.async_weekly, hour=8, minute=0, second=0))
        if self.conf.get(CONF_THERMOSTAT):
            self._unsubs.append(async_track_state_change_event(self.hass, [self.conf[CONF_THERMOSTAT]], self._on_thermostat))
        if self.conf.get(CONF_OT_FLOW):
            self._unsubs.append(async_track_state_change_event(self.hass, [self.conf[CONF_OT_FLOW]], self.otc.on_flow))
        self._stop_unsub = self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._on_ha_stop)
        self.spawn(self._async_first_run(), "first run", background=False)
        if data.get("replayed_with") != planner.REPLAY_VERSION:
            self.spawn(self.hl.async_replay_kept_days(), "replay the days kept")

    async def _async_first_run(self) -> None:
        if not self.entry.data.get("token"):
            self.wh.ask_login("not logged in to Weheat yet")     # installed before 0.5.3, or setup without a login
        await self.learner.async_building()
        for eid, h0, hourly, scale in await prices.async_history(self.hass, self.conf, self.read):
            self.prices = cprices.seed(self.prices, eid, h0, hourly, scale)
        if not self.weheat.pump:
            await self.wh.async_pump_info()                  # whether a gas boiler is there, before the first plan
        await self._async_tick(None, force_plan=True)
        if not self.weheat.import_info.get("done") and self.weheat.import_info.get("oldest"):
            # an import in months was cut off by a restart: carry on with the older months
            self.spawn(self.wh.async_import(WEHEAT_IMPORT_DAYS), "weheat import (resumed)")
        elif self.weheat.import_info.get("done") and self.weheat.import_info.get("fields", 1) < WEHEAT_FIELDS:
            # imported by an older version: read the hourly logs again for the newer fields (setpoint, flow
            # temperature); the energy per hour is there already
            self.spawn(self.wh.async_import(WEHEAT_IMPORT_DAYS, logs_only=True), "weheat import (new fields)")
        elif self.conf.get(CONF_IMPORT_ON_SETUP) and not self.weheat.import_info.get("done"):
            self.spawn(self.wh.async_import(WEHEAT_IMPORT_DAYS), "weheat import")
        elif self.house.source != "learned":
            self.spawn(self.learner.async_learn(), "first learning")

    def spawn(self, coro, name: str, background: bool = True) -> asyncio.Task:
        """A job of Roost's own (import, learning; background=False: the first run, which startup waits for): tied to
        the config entry, and cancelled when Roost unloads or Home Assistant stops, so nothing asks the executor for
        work after it has shut down. The import carries on after a restart from the last month it finished."""
        task = (self.entry.async_create_background_task(self.hass, coro, f"{DOMAIN} {name}") if background
                else self.entry.async_create_task(self.hass, coro, f"{DOMAIN} {name}"))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _cancel_tasks(self) -> None:
        for task in list(self._tasks):
            task.cancel()

    @callback
    def _on_ha_stop(self, _event) -> None:
        self._stop_unsub = None                 # fired: nothing to remove any more
        self._cancel_tasks()
        self.hass.async_create_task(self.async_save(), f"{DOMAIN} save on stop")   # the last Weheat call times, events

    async def async_stop(self) -> None:
        self._cancel_tasks()
        if self._stop_unsub is not None:
            self._stop_unsub()
            self._stop_unsub = None
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
            "ot": self.otc.stored(),
            **self.meters.stored(), "learn": self.learn_info,
            **self.log.stored(time.time()),
            "window_hours": sorted(h for h in self.window.hours if h > time.time() - 400 * 86400),
            **self.held.stored(), "acc": self.hl.stored_acc(),
            "storage_at": time.time(),
            "pv_k": self.pv_k, "load_profile": self.load_profile, **self._prices_stored(),
            "check": self.check, "ready_muted": self.ready_muted, "changes": [c for c in self.changes if c["ts"] > time.time() - 30 * 86400],
            "building": self.building,
            "curve": self.curve_advice.as_dict() if self.curve_advice else None, **self.weheat.stored(),
            "room_models": {k: v.as_dict() for k, v in self.room_models.items() if any(r.id == k for r in self.rooms)},
            "events": list(self.events), **self.card.stored()})

    def _prices_stored(self) -> dict:
        self.prices = cprices.prune_seen(self.prices, time.time())
        return self.prices.stored()

    async def _async_save_history(self) -> None:
        cut = time.time() - HISTORY_KEEP_DAYS * 86400      # thirteen months: learning uses a year
        self.weheat = cweheat.prune(self.weheat, cut)
        self.weather = cweather.prune_history(self.weather, cut)
        await self._hist_store.async_save({**self.weheat.stored_history(),
                                           **self.weather.stored(),
                                           "ot_obs": self.otc.obs, "ot_stops": self.otc.stops})

    def event(self, kind: str, **data: Any) -> None:
        """Remember what happened (kept: the last EVENTS_KEPT, also over restarts)."""
        self.events.append({"t": dt_util.now().isoformat(timespec="seconds"), "kind": kind, **data})

    async def async_set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.event("mode", old=self.mode, new=mode)
        was_active = self.mode == "active"
        self.mode = mode
        if was_active and mode != "active" and not self.ot:
            await self.care.async_back_to_comfort(f"mode {mode}")
        self.mem.virtual_sp = None
        if mode == "active":
            self.ready_muted = False        # chosen by hand: a later 'ready' after going back to shadow is news again
        self.notices.issue_ready()
        await self.async_save()
        await self._async_tick(None, force_plan=True)

    # ------------------------------------------------------------ Weheat entities
    def _resolve_weheat(self) -> None:
        reg = er.async_get(self.hass)
        dev_id = self.conf.get(CONF_HEAT_PUMP)
        from homeassistant.helpers import device_registry as dr
        dev = dr.async_get(self.hass).async_get(dev_id) if dev_id else None
        # a child device (a sub-device of a device) has no model of its own: getattr gives what DeviceEntry would
        self.pump_name = getattr(dev, "model", None) or dev.name if dev else None
        by_key = {e.translation_key: e.entity_id for e in er.async_entries_for_device(reg, dev_id, include_disabled_entities=False)} if dev_id else {}
        self.ent = {role: by_key[key] for role, key in WEHEAT.items() if key in by_key}
        self.card.apply_pump_entities()

    # ------------------------------------------------------------ reading


    def unit_air_now(self) -> float | None:
        """The air at the unit now (°C) from its own sensor, only when that reading is live: the heat pump's entity when
        it reported in the last AIR_FRESH_S (a cloud that is away keeps its last value: 23-11-2026, 47 minutes),
        else the OpenTherm master's reading of the same sensor (THRM ONE), else None (the forecast is used as it is)."""
        now = dt_util.utcnow()
        for eid in (self.ent.get("outdoor"), self.otc.air_entity() if self.ot else None):
            st = self.read.state(eid)
            seen = getattr(st, "last_reported", None) or (st.last_updated if st is not None else None)
            if st is not None and seen is not None and (now - seen).total_seconds() < AIR_FRESH_S:
                v = self.read.temp(eid)
                if v is not None:
                    return v
        return None





    def room(self) -> float | None:
        r = self.read.temp(self.conf.get(CONF_ROOM))
        if r is None:
            st = self.read.state(self.conf.get(CONF_THERMOSTAT))
            r = self.read.sys_to_c(_f(st.attributes.get("current_temperature"))) if st else None
        if r is None:
            r = self.read.temp(self.ent.get("thermostat_room"))
        return r

    def thermostat_sp(self) -> float | None:
        st = self.read.state(self.conf.get(CONF_THERMOSTAT))
        return self.read.sys_to_c(_f(st.attributes.get("temperature"))) if st else None

    def thermostat_reading(self) -> float | None:
        st = self.read.state(self.conf.get(CONF_THERMOSTAT))
        return self.read.sys_to_c(_f(st.attributes.get("current_temperature"))) if st else None

    def pump_state(self) -> str | None:
        st = self.read.state(self.ent.get("state"))
        return st.state if st else None

    def _rooms_ahead(self, hours: list[planner.HourIn]) -> tuple[list[dict], list[dict]]:
        """The extra rooms for the planner and for the card (core/plan.rooms_ahead), with their temperature now."""
        temps = {}
        for r in self.rooms:
            st = self.read.state(r.sensor)
            temps[r.id] = self.read.sys_to_c(_f(st.state)) if st else None
        c = self.conf
        return cplan.rooms_ahead(self.rooms, temps, self.room_models, int(c[CONF_DAY_FROM]), int(c[CONF_DAY_TO]), hours)

    def _note_no_plan(self) -> None:
        if self.reason.code != self._last_reason_code:
            self._last_reason_code = self.reason.code
            self.event("no_plan", reason=self.reason.code, sources=dict(self.sources))

    def sun_on_house(self, ts: int, wx: tuple) -> float:
        """Radiation driving the solar gain in this hour, for the facade the house model learned (sun.effective)."""
        return sun.effective(ts, wx, self.hass.config.latitude, self.hass.config.longitude, self.house.sun_facade, self.house.sun_vertical)

    def local_hour(self, ts: int) -> int:
        return dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc)).hour

    # ------------------------------------------------------------ the weather (weatherfetch.py, core/weather.py)
    async def _async_weather(self) -> None:
        got, src = await weatherfetch.async_update(self.hass, self.conf, self.weather, self.read.sys_to_c)
        if got is not None:         # into the weather as it is now (learning may have added history meanwhile)
            self.weather = cweather.with_forecast(self.weather, got.rows, got.at, got.merge)
        if src is not None:
            self.sources["weather"] = src

    # ------------------------------------------------------------ the meters (core/meters.py)
    def _age_storage(self, saved_at: float | None, t: float) -> None:
        self.meters, ev = cmeters.age_storage(self.meters, saved_at, t, self.house.lag)
        if ev:
            self.event("storage_aged", **ev)

    def _track_storage(self, t: float) -> None:
        kw = (self.read.kw(self.ent.get("power_out")) or 0.0) if self.pump_state() == "heating" else None
        self.meters = cmeters.track_storage(self.meters, self._last_tick, t, kw, self.house.lag)

    def _count_cost(self, now: datetime) -> None:
        """Today's electricity and cost from the unit's and the indoor unit's meters; the unit's into the hour too."""
        h = self.plan_hour(now)
        # no plan: the published price of this hour; none known: counted as energy without a price, not as free
        price = h.p_grid if h is not None else self.prices.tariff_now
        indoor = self.read.num(self.ent.get("elec_indoor")) if self.ent.get("elec_indoor") else None
        parts = [self.read.num(self.ent.get(k)) for k in ("elec", "elec_defrost") if self.ent.get(k)]
        c = cmeters.count_cost(self.meters, dt_util.as_local(now).date().isoformat(), parts, indoor, price)
        if c.closed_day is not None:
            self.spawn(self.hl.async_close_day(c.closed_day), "close the day", background=False)
        self.meters = c.meters
        if c.counted:
            self.acc = chl.add_elec(self.acc, c.elec, c.cost if price is not None else None)

    def run_stats(self, t: float) -> dict:
        return cmeters.run_stats(self.meters.runs, t, dt_util.get_default_time_zone())



    # ------------------------------------------------------------ the run
    async def _async_tick(self, _now: datetime | None, force_plan: bool | str = False) -> None:
        now = dt_util.utcnow()
        t = now.timestamp()
        try:
            if not self.ent:
                self._resolve_weheat()
            await self._async_weather()
            if self.conf.get(CONF_PRICE_MODE) == "epex" or self.prices.need_epex:
                await self._async_epex(now)
            self.notices.watch_window(t)
            self._track_storage(t)
            self.hl.track(t)
            if not self.ot:
                self.care.watch_thermostat(t)
            self._count_cost(now)
            self.notices.check(t)
            heating = self.pump_state() == "heating"
            self.meters = cmeters.track_defrost(self.meters, t, self.pump_state() == "defrosting")
            self.meters = cmeters.track_runs(self.meters, t, heating)
            self.card.track(t)
            self._heating_since = (self._heating_since or t) if heating else None
            e = self._energy(now, stick.HORIZON_H)
            self.prices = replace(self.prices, tariff_now=e[0].import_price[0] if e else None)
            why = self._why_plan(now, e, "forced" if force_plan is True else (force_plan or None))
            # a plan made afresh only for a reason (stick.py); otherwise the plan held is worked out again for the new
            # hour; without a plan, try again every PLAN_MINUTES
            due = (why is not None or self.held.at is None or int(t // 3600) != int(self.held.at // 3600)
                   or (self.held.plan is None and t - self.held.at >= PLAN_MINUTES * 60))
            if due and not self._planning:
                await self._async_plan(now, why, e)
            self.hl.log_hour(now)
            await self._async_control(t)
        except Exception as err:  # noqa: BLE001 - one bad run must not stop the integration
            _LOGGER.exception("Roost run failed")
            self.event("error", where="run", error=repr(err)[:200], trace=traceback.format_exc(limit=4)[-800:])
        self._last_tick = t
        self._notify()

    def plan_hour(self, now: datetime):
        """Input for this UTC hour, including before a new plan is ready at the hour boundary."""
        return cplan.hour_in(self.held.at, self.held.hours, now.timestamp())

    def _local(self, ts: float) -> datetime:
        return dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc))

    def _hours_ahead(self, now: datetime, prices: list[value.HourPrices], tariff: list[float]) -> list[planner.HourIn]:
        """The planner's hours (core/plan.hours_ahead) from what Roost reads now."""
        return cplan.hours_ahead(
            int(now.timestamp() // 3600 * 3600), now.timestamp(), prices, tariff, self.weather, local=self._local,
            dhw_share=self.pump.dhw_share, dhw_top=self.read.temp(self.ent.get("dhw_top")),
            dhw_now=self.pump_state() in DHW_STATES, unit_air=self.unit_air_now(), bias=self.pump.bias,
            outdoor=lambda: self.read.num(self.ent.get("outdoor")), sun=self.sun_on_house, weekly=bool(self.conf.get(schedule.ENABLED)),
            is_day=self.is_day, corr_kw=self.corr_kw, corr_slow=self.corr_slow, away=self.is_away)

    def _why_plan(self, now: datetime, e, force: str | None) -> str | None:
        """Why to make the plan afresh now (stick.why_plan), from what Roost measures and the forecasts now."""
        t = now.timestamp()
        c = self.held.commit
        tariff = list(e[0].import_price) if e else None
        base = int(t // 3600 * 3600)
        t_out, rad = [], []
        for i in range(stick.WEATHER_H):
            wx = self.weather.get(base + i * 3600)
            if wx is None:
                break
            t_out.append(wx[0])
            rad.append(self.sun_on_house(base + i * 3600, wx))
        pv = self._pv_forecast(t, stick.WEATHER_H) if e and self.conf.get(CONF_PV_FORECAST) else None
        pv_now = self._watch.feed_pv(t, self.read.kw(self.conf.get(CONF_PV_POWER))) if self.conf.get(CONF_PV_FORECAST) else None
        coarse = window.reading_step(self.window.changes) >= 0.3
        if force is None and getattr(self, "_replan_on_start", False):
            force = "restart"                   # until a plan is made afresh (the first rounds may have no prices yet)
        why = stick.why_plan(c, t, room=self.room(), coarse=coarse, tariff=tariff, t_out=t_out, rad=rad, pv=pv,
                             pv_now_kw=pv_now, watch=self._watch, force=force)
        if why is None and c is not None and self.held.fallback == "no_price" and e:
            why = "prices"                                  # prices are back
        return why

    # ------------------------------------------------------------ prices (prices.py, core/prices.py)
    async def _async_epex(self, now: datetime) -> None:
        if not prices.epex_due(self.prices, now):
            return
        self.prices = replace(self.prices, epex_at=now.timestamp())       # before the fetch: one at a time
        slots = await prices.async_epex(self.hass, self.conf, now, self.sources, self.event)
        if slots:
            self.prices = replace(self.prices, epex=slots)

    def _energy(self, now: datetime, hours: int) -> tuple[value.EnergyInputs, value.EnergyValue] | None:
        self.prices, e = prices.energy_ahead(self.conf, self.prices, self.read, now, hours, self.pv_k, self.weather,
                                             self.load_profile, self.sources, self.notices.issue)
        return e

    def _pv_forecast(self, start: float, hours: int) -> list[float] | None:
        return prices.pv_forecast(self.conf, self.read, start, hours, self.pv_k, self.weather)

    def _plan_failed(self, code: str, t: float) -> None:
        """No plan could be made (core/plan.failed): the plan held for a while, then the comfort schedule."""
        self.held, f = cplan.failed(self.held, code, t, self._started_at, START_GRACE_S, FALLBACK_MIN * 60, FALLBACK_NOTICE_H * 3600)
        if f is None:
            return              # just started: the price sensor often comes back a minute after Roost (22-11-2026)
        self.reason = Reason(code)
        self._note_no_plan()
        if f.reason == "fallback_schedule":
            if f.to_schedule:
                self.event("fallback", to="schedule", why=code)
            self.reason = Reason("fallback_schedule")
        self.notices.issue("fallback", f.notice, placeholders={"why": code})

    def fallback_sp(self, t: float) -> float:
        """The comfort schedule: comfort in the comfort hours, the night minimum outside them, the away minimum away."""
        return cplan.fallback_sp(self.is_away(t), self.is_day(self._local(t)), self.settings().away_min,
                                 float(self.conf[CONF_COMFORT]), float(self.conf[CONF_NIGHT_MIN]))

    def planned_sp(self, t: float) -> float | None:
        """The setpoint for now: the plan's for this hour, or the fallback. OpenTherm: the flow asked now (0 = off)."""
        if self.ot:
            return self.otc.mem.flow if self.held.plan is not None or self.otc.mem.last_write else None
        sp = cplan.setpoint(self.held.plan, self.held.at, t)
        if sp is not None:
            return sp
        if self.held.fallback == "schedule":
            return self.fallback_sp(t)
        return None

    async def _async_plan(self, now: datetime, why: str | None = None, e=...) -> None:
        self._planning = True
        try:
            t = now.timestamp()
            if e is ...:
                e = self._energy(now, 36)             # up to 36 h, bounded by published tariffs
            room = self.room()
            fallback = None
            if e is None and room is not None and self.held.fail_since and t - self.held.fail_since >= FALLBACK_MIN * 60:
                e, fallback = cprices.flat(self.prices, self.held.tariff), "no_price"
                why = why or "fallback"
            if e is None or room is None:
                self._plan_failed("no_price" if e is None else "no_room", t)
                return
            inp, ev = e
            prices = value.planner_prices(inp, ev)
            self.corr_kw, self.corr_n = check.correction(self.log.hour_log, self.house, self.pump, now.timestamp())
            self.corr_slow = check.slow_correction(self.log.hour_log, self.house, self.pump, now.timestamp())
            hours = self._hours_ahead(now, prices, inp.import_price)
            if not hours:
                self._plan_failed("no_weather", t)
                return
            s = self.settings()
            w_now = self.read.kw(self.ent.get("power_out")) if self.pump_state() == "heating" else 0.0
            room_in, room_meta = self._rooms_ahead(hours)
            mode = self.conf.get(CONF_PRICE_MODE)
            price_key = "epex_import" if mode == "epex" else self.conf.get(CONF_IMPORT_PRICE)
            guess = [] if mode == "fixed" else list(
                (self.prices.guess.get(price_key) if price_key is not None else None) or [])[:len(hours)]
            sp_now = self.thermostat_sp() if self.thermostat_sp() is not None else self.mem.last_sp
            # the plan held: keep its setpoints and work out what they give now; a reason: plan afresh
            fixed = None
            kind = "level" if self.ot else None
            if why is None and self.held.commit is not None and (self.held.commit.fallback or None) == fallback and self.held.commit.kind == kind:
                fixed = self.held.commit.setpoints(t)
                if not fixed:
                    why = "horizon"
            elif why is None:
                why = "first"
            if self.ot:
                # the level the unit runs at now: what it makes (a start peak counts as its level planned)
                # hot water now counts as running: it heats the house again after it, a plan must not stop it for that
                lvl = self.otc.mem.level if self.otc.mem.level > 0 and (self.pump_state() == "heating" or self.otc.hot_water()) else (
                    w_now if w_now and w_now > 0.5 else 0.0)
                run = partial(planner.plan_ot, self.house, self.pump, s, hours, room, self.meters.storage_e, lvl, 24, room_in,
                              extra_rooms=len(self.rooms))
            else:
                run = partial(planner.plan, self.house, self.pump, s, hours, room, self.meters.storage_e, sp_now, 24, w_now, room_in,
                              extra_rooms=len(self.rooms))
            # the plan held is kept as it is: comparing it with a fresh plan every round gained nothing in the
            # simulations (22-11-2026 ablation: -0.27 % without), the reasons to plan again (stick.why_plan) do the work
            p = await self.hass.async_add_executor_job(partial(run, fixed=fixed or None))
            commit = None
            if not fixed:
                commit = stick.Commitment(at=t, hour0=int(t // 3600 * 3600), sp=[x.sp for x in p.hours], room0=room,
                                               t_end=[round(x.t_end, 3) for x in p.hours], t_out=[h.t_out for h in hours],
                                               rad=[h.rad for h in hours], tariff=list(inp.import_price),
                                               pv=list(inp.pv_kwh) if inp.pv_kwh and self.conf.get(CONF_PV_FORECAST) else None,
                                               fallback=fallback, kind=kind)
                self._watch.room_off = 0
                self._replan_on_start = False
                self.event("plan", why=why, sp=[x.sp for x in p.hours[:6]], fallback=fallback)
            if self.held.fallback != fallback and fallback:
                self.event("fallback", to=fallback, why="no_price")
            if not fallback:
                self.notices.issue("fallback", False)
            if len(p.hours) < 24:
                # A partial tariff horizon is usable for steering, not a complete next-24-hour saving estimate.
                quality = {**p.breakdown["quality"], "valid": False, "status": "incomplete_forecast",
                           "reasons": p.breakdown["quality"]["reasons"] + ["incomplete_forecast"]}
                p.breakdown = savings.publish(p.breakdown, quality)
            if fallback:
                quality = {**p.breakdown["quality"], "valid": False, "status": "fallback",
                           "reasons": p.breakdown["quality"]["reasons"] + ["no_price"]}
                p.breakdown = savings.publish(p.breakdown, quality)
            seen = [m for m in room_meta if m.get("available", True)]
            room_status = [{**meta, "expected": temps[:24]} for meta, temps in zip(seen, p.rooms, strict=False)] + \
                          [m for m in room_meta if not m.get("available", True)]
            # into the plan state as it is now (read again after the planner ran in the executor)
            self.held = cplan.adopted(self.held, p, hours, now.timestamp(), w_now, list(inp.import_price), guess, room_status,
                                      commit, why, fallback)
            self.hl.remember_prediction(now, p)
            try:
                snap = replan.snapshot(now.timestamp(), int(now.timestamp() // 3600 * 3600), p, hours, inp.import_price, guess, room,
                                       self.corr_kw, {**vars(s), "comfort_schedule": schedule.context(self.conf)}, self.held.on_guess)
                line = replan.compare(self.log.plan_snap, snap, room)
                if line:
                    self.log = replace(self.log, plan_changes=replan.prune(self.log.plan_changes + [line], now.timestamp()))
                self.log = replace(self.log, plan_snap=snap)
            except Exception as err:  # noqa: BLE001 - the change log must never stop planning and steering
                _LOGGER.debug("plan change log: %s", err)
                self.log = replace(self.log, plan_snap=None)
            if self.ot:
                self.reason = planner.explain_ot(p, hours, room, s, self.house, curve.emitter_profile(self.conf)[3])
            else:
                self.reason = planner.explain(p, hours, room, s, self.pump, self.house, curve.emitter_profile(self.conf)[3])
            if fallback:
                self.reason = Reason("fallback_no_price")
            self._last_reason_code = None
        finally:
            self._planning = False

    async def _async_write(self, sp: float) -> bool:
        """Set the thermostat (Roost's own context, so it is not taken for a change by hand)."""
        ctx = Context()
        self._contexts[ctx.id] = time.time()
        await self.hass.services.async_call("climate", "set_temperature",
                                            {ATTR_ENTITY_ID: self.conf[CONF_THERMOSTAT], "temperature": self.read.c_to_sys(sp)},
                                            blocking=True, context=ctx)
        return True

    async def _async_airing(self, t: float) -> None:
        """A window/door sensor says open: the thermostat to the lowest setpoint so the unit stops heating the outdoors
        (not for a fall of the room alone: that can be a false alarm). Back to the plan when it closes (_watch_window)."""
        self.reason = Reason("airing")
        cur = self.thermostat_sp()
        low = float(self.conf.get(CONF_SP_MIN, self.conf[CONF_NIGHT_MIN]))
        paused = bool(self.mem.pause_until and t < self.mem.pause_until)
        if (self.mode == "active" and not paused and self._airing_from is None and cur is not None and cur > low + 0.01
                and self.care.thermostat_reachable()):
            try:
                await self._async_write(low)
                self._airing_from = cur
                self.event("airing", old=cur, new=low)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Roost could not lower the thermostat for an open window: %s", err)
                self.event("set_failed", new=low, error=str(err)[:200])
        self.decision = control.Decision(None, Reason("airing"), self.thermostat_sp())

    async def _async_control(self, t: float) -> None:
        if self.ot:
            await self.otc.async_control(t)
            return
        if self.otc.steering:
            await self.otc.async_reconcile()       # steering changed back to the thermostat: the master on its own curve
        if self.window.active():
            if self.window.via == "contact":
                await self._async_airing(t)
                return
            # airing seen from the room alone: changing the thermostat now would heat the outdoors; wait until the room is back
            self.reason = Reason("window_open")
            self.decision = control.Decision(None, Reason("window_open"), self.thermostat_sp())
            return
        planned = self.planned_sp(t)
        if self.mode == "off" or planned is None:
            self.decision = control.Decision(None, Reason("off") if self.mode == "off" else self.reason, self.thermostat_sp())
            return
        if self.mode == "active" and not self.care.thermostat_reachable():
            self.decision = control.Decision(None, Reason("no_plan"), None)     # unreachable: leave it alone (a notice follows)
            return
        hard = (self.settings().away_min if self.is_away(t) else float(self.conf[CONF_DAY_MIN]) if self.is_day(dt_util.as_local(datetime.fromtimestamp(t, tz=timezone.utc)))
                else float(self.conf[CONF_NIGHT_MIN]))
        current = self.thermostat_sp() if self.mode == "active" or self.mem.virtual_sp is None else self.mem.virtual_sp
        room = self.room()
        if (self._heating_since is not None and t - self._heating_since < MIN_RUN_MIN * 60 and current is not None
                and planned < current - 0.01 and (room is None or room < self.settings().store_max)
                and not (self.mem.pause_until and t < self.mem.pause_until)):
            # the unit just started: a short run wears it and wastes the warm-up; lower once it has run a while
            mins = round(MIN_RUN_MIN - (t - self._heating_since) / 60)
            self.decision = control.Decision(None, Reason("min_run", {"min": mins}), current)
            return
        before = (self.mem.last_write, self.mem.last_sp)
        d = control.decide(t, planned, self.thermostat_sp(), room, hard,
                           self.mem, self.control_settings(), self.mode == "active")
        self.decision = d
        if d.setpoint is not None and self.mode == "active":
            old = self.thermostat_sp()
            try:
                await self._async_write(d.setpoint)
                self.event("set", old=old, new=d.setpoint, why=d.why.code, reason=self.reason.code, args=dict(self.reason.args),
                           room=room)
                self.care.set_result(True)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Roost could not set the thermostat: %s", err)
                self.event("set_failed", new=d.setpoint, error=str(err)[:200])
                self.care.set_result(False, str(err))
                # not applied: the change interval does not start; try again soon, later after each failure
                interval = self.control_settings().min_interval_min
                retry = min(interval, 5 * 2 ** max(0, self.care._set_fails - 1))
                self.mem.last_write = t - (interval - retry) * 60
                self.mem.last_sp = before[1]
                self.decision = control.Decision(None, Reason("set_failed", {"min": round(retry)}), old)
        if d.setpoint is not None:
            await self.async_save()

    @callback
    def _on_thermostat(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if old is None or new is None or event.context.id in self._contexts or self.mode != "active":
            return
        a, b = _f(old.attributes.get("temperature")), _f(new.attributes.get("temperature"))
        if a is None or b is None or abs(a - b) < 0.05:
            return
        # our own change coming back (a thermostat may report it without our context); a change that carries a user
        # is that user's, also right after ours (R20)
        if self.mem.last_write and time.time() - self.mem.last_write < 60 and not event.context.user_id:
            return
        self.mem.pause_until = time.time() + self.control_settings().pause_hours * 3600
        room = self.room()
        self.changes.append({"ts": round(time.time()), "from": a, "to": b, "room": round(room, 2) if room is not None else None})
        self.event("by_hand", old=a, new=b, room=room, pause_h=self.control_settings().pause_hours,
                   context_user=bool(event.context.user_id), context_parent=bool(event.context.parent_id))
        self.hass.async_create_task(self.async_save())
        self._notify()

    # ------------------------------------------------------------ health (repairs)

    # ------------------------------------------------------------ services
    async def async_pause(self, hours: float) -> None:
        self.event("pause", hours=hours)
        self.mem.pause_until = time.time() + hours * 3600
        await self.async_save()
        self._notify()

    async def async_resume(self) -> None:
        self.event("resume")
        self.mem.pause_until = None
        self.mem.last_write = None
        await self.async_save()
        await self._async_tick(None, force_plan=True)

    # ------------------------------------------------------------ learning