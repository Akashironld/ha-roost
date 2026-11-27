"""The hourly log, Home Assistant's side: read the hour (the room, the thermostat, the unit, where its electricity
came from) and the plan in force into the core's views, replay a closed day in the executor, and give the card and
services their numbers. What goes into the log and how is in core/hourlog.py.

HourLog (held by RoostManager as `hl`) reaches the rest of Roost only through HourLogHost: the Logs and HourAcc
bundles (read and replaced, never held over an await), the plan in force, the readings, events, saving."""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from homeassistant.util import dt as dt_util

from . import lookback, planner, replan, schedule, value
from .const import (
    CONF_BATTERY_POWER,
    CONF_GRID_POWER,
    CONF_GRID_SIGN,
    CONF_HOUSE_POWER,
    CONF_PV_POWER,
)
from .core import hourlog as chl
from .core.hourlog import HourView, PlanView

_LOGGER = logging.getLogger(__name__)
from .mgr_common import DHW_STATES, DHW_WEEKS, _iso_ts


class HourLogHost(Protocol):
    """What the hour log needs of the manager: no more."""
    hass: Any
    log: chl.Logs                    # read and replaced
    acc: chl.HourAcc                 # read and replaced
    held: Any                        # the plan in force (core/plan.Held)
    corr_kw: Any
    corr_n: Any
    reason: Any
    mode: Any
    mem: Any
    otc: Any
    meters: Any
    weather: Any
    window: Any
    house: Any
    pump: Any
    rooms: list
    events: Any
    check: dict
    weheat: Any
    ent: dict[str, str]
    _last_tick: float | None

    read: Any                                # entity states as numbers, °C, kW (reader.Reader)

    @property
    def conf(self) -> dict: ...
    @property
    def ot(self) -> bool: ...
    def room(self) -> float | None: ...
    def thermostat_sp(self) -> float | None: ...
    def thermostat_reading(self) -> float | None: ...
    def pump_state(self) -> str | None: ...
    def planned_sp(self, t: float) -> float | None: ...
    def plan_hour(self, now: datetime) -> Any: ...
    def settings(self) -> planner.Settings: ...
    def is_away(self, ts: float | None = None) -> bool: ...
    def sun_on_house(self, ts: int, wx: tuple) -> float: ...
    def spawn(self, coro, name: str, background: bool = True) -> Any: ...
    async def async_save(self) -> None: ...
    def event(self, kind: str, **data: Any) -> None: ...


def _tz():
    return dt_util.get_default_time_zone()


class HourLog:
    def __init__(self, host: HourLogHost) -> None:
        self.host = host

    def view(self) -> PlanView:
        h = self.host
        return PlanView(h.held.plan, h.held.at, h.held.hours, h.held.guess, h.held.on_guess, h.held.w_now,
                        h.corr_kw, h.corr_n, h.reason.code, h.reason.args)

    # ------------------------------------------------------------ the hour in progress
    def _sources_kw(self) -> tuple[float, float, float] | None:
        """Where the heat pump's electricity comes from now (solar, battery, grid kW), while it heats the house."""
        h = self.host
        c = h.conf
        if not (c.get(CONF_PV_POWER) or c.get(CONF_BATTERY_POWER)):
            return None
        if h.pump_state() != "heating":
            return None             # hot water (and defrost of it) is not heating: only space heating is counted
        hp = h.read.kw(h.ent.get("power_in"))
        grid = h.read.kw(c.get(CONF_GRID_POWER))
        if hp is None or grid is None or hp <= 0:
            return None
        pv = h.read.kw(c.get(CONF_PV_POWER)) or 0.0
        bat = h.read.kw(c.get(CONF_BATTERY_POWER)) or 0.0
        house = h.read.kw(c.get(CONF_HOUSE_POWER))
        if house is None:
            house = value.house_use(grid, pv, bat, c.get(CONF_GRID_SIGN, "import_positive") == "import_positive")
        s = value.source_split(hp, house, pv, bat)
        return (s[0], s[1], s[2])

    def track(self, t: float) -> None:
        """Per hour: seconds on hot water (an hour on hot water is not a model error) and the heat delivered to the house
        (where the unit's output starts in the next hour), for the correction."""
        h = self.host
        hour = int(t // 3600 * 3600)
        if h.acc.hour != hour:
            if h.acc.hour is not None:
                self.close(h.acc.hour, h.room())
            h.acc = chl.new_hour(h.acc, hour)
        if h._last_tick is None:
            return
        dt = min(600.0, max(0.0, t - h._last_tick))
        src = self._sources_kw()
        sp, reading = h.thermostat_sp(), h.thermostat_reading()
        state = h.pump_state()
        heating_kw = (h.read.kw(h.ent.get("power_out")) or 0.0) if state == "heating" else None
        h.acc = chl.track(h.acc, dt, sp, reading, state in DHW_STATES, heating_kw, src)

    def close(self, hour: int, room: float | None, partial: bool = False) -> None:
        self.host.log = chl.close_hour(self.host.log, self.host.acc, hour, room, partial)

    def stored_acc(self) -> dict:
        h = self.host
        return h.acc.stored(h.meters.last_elec, h.meters.last_indoor, time.time())

    def restore(self, d: dict | None, t: float) -> tuple[float | None, float | None] | None:
        """Back after a restart (core/hourlog.restore_acc): the meter readings to go on counting from, if the same hour."""
        r = chl.restore_acc(d, t)
        if r is None:
            return None
        self.host.acc = r.acc
        if r.close_partial is not None:
            self.close(r.close_partial, None, partial=True)
            self.host.acc = replace(self.host.acc, hour=None)
        return r.meters

    # ------------------------------------------------------------ once an hour
    def _policy_changed(self, context: dict) -> bool:
        h = self.host
        return chl.policy_changed(context, vars(h.settings()), [vars(r) for r in h.rooms], schedule.context(h.conf))

    def log_hour(self, now: datetime) -> None:
        """Once per hour: what the thermostat had and the inputs, so the day can be replayed for the saving."""
        h = self.host
        hour = int(now.timestamp() // 3600 * 3600)
        day = dt_util.as_local(now).date().isoformat()
        context = h.log.day_contexts.get(day)
        # every tick, not once an hour: a change made and undone within an hour also makes the day's saving unsure
        if context is not None and not context.get("settings_changed") and self._policy_changed(context):
            h.log = chl.settings_changed(h.log, day)
        if h.log.hour_log and h.log.hour_log[-1]["ts"] == hour:
            return
        acc = h.otc.flow_acc
        if h.ot and h.log.hour_log and acc[2] and acc[0] == h.log.hour_log[-1]["ts"]:
            h.log = chl.flow_measured(h.log, acc)
        room = h.room()
        if h.ot:      # OpenTherm: the heat output steered (or, in shadow mode, that would be), kW
            sp = h.otc.mem.level if h.held.plan is not None or h.otc.mem.last_write else None
        elif h.mode == "shadow":
            # what Roost would have set: never the user's own thermostat, which is not Roost's doing (a day replayed
            # with it read as Roost's saving, e.g. -0.43 on 19-11-2026 for a thermostat simply set at 20 all day)
            sp = h.mem.virtual_sp if h.mem.virtual_sp is not None else h.planned_sp(now.timestamp())
        else:
            sp = h.thermostat_sp()
        wx = h.weather.get(hour)
        hin = h.plan_hour(now)
        if room is None or sp is None or wx is None or hin is None:
            return
        if day not in h.log.day_contexts:
            h.log = chl.with_day_context(h.log, day, chl.day_context(
                h.house.as_dict(), h.pump.as_dict(), vars(h.settings()), [vars(r).copy() for r in h.rooms],
                schedule.context(h.conf), hour))
        if self._policy_changed(h.log.day_contexts[day]):
            h.log = chl.settings_changed(h.log, day)
        v = HourView(
            ts=hour, local_hour=dt_util.as_local(now).hour, room=room, storage_e=h.meters.storage_e, sp=sp,
            sp_t=sp if h.ot else h.thermostat_sp(),
            ot={"flow": h.otc.mem.flow, "ot_state": h.otc.state(), "k_factor": h.otc.mem.k_factor} if h.ot else None,
            w=(h.read.kw(h.ent.get("power_out")) or 0.0) if h.pump_state() == "heating" else 0.0,
            away=h.is_away(now.timestamp()), wx=wx, rad=h.sun_on_house(hour, wx), h=hin, pred=h.log.pred.get(hour, {}),
            mode=h.mode, window=hour in h.window.hours,
            paused=bool(h.mem.pause_until and h.mem.pause_until > time.time()))
        entry = chl.hour_entry(v, self.view())
        h.log = chl.logged(h.log, hour, entry, self.plan_entry(hour, room))
        h.spawn(h.async_save(), "save the hour", background=False)   # a crash or power cut loses at most an hour

    def plan_entry(self, hour: int, room: float) -> dict:
        """Everything the plan in force sees now (core/hourlog.plan_entry), to replay a decision exactly."""
        h = self.host
        return chl.plan_entry(hour, room, h.meters.storage_e, h.thermostat_sp(), self.view(), schedule.context(h.conf))

    def remember_prediction(self, now: datetime, p) -> None:
        """The room the plan expects at the start of the coming hours, 1 and 6 hours ahead, to set beside what happened."""
        h = self.host
        h.log = replace(h.log, pred=chl.remember_prediction(h.log.pred, int(now.timestamp() // 3600 * 3600), p, self.view()))

    # ------------------------------------------------------------ the day
    async def async_close_day(self, day: str) -> None:
        """Replay yesterday with what Roost set and with a steady thermostat, from the same start (same model, same
        weather, same prices): the difference is the saving."""
        h = self.host
        entries = chl.entries_of_day(h.log.hour_log, day, _tz())
        if len(entries) < 20:
            return
        context = h.log.day_contexts.get(day)
        house, pump, settings = chl.replay_models(context, h.house, h.pump, h.settings())
        res = await h.hass.async_add_executor_job(planner.replay_day, house, pump, settings, entries)
        quality = None
        if res is not None:
            start = dt_util.start_of_local_day(datetime.fromisoformat(day))
            expected = round(((start + timedelta(days=1)).timestamp() - start.timestamp()) / 3600)
            quality = chl.day_quality(entries, res[2], expected, int(start.timestamp()), context, len(h.rooms))
        h.log = chl.day_closed(h.log, day, entries, res, quality, settings.comfort, chl.by_hand_on(h.events, day))
        # the comfort range: what eco a degree lower or higher and the top of the range lower would have cost
        ot = chl.day_steering(entries)
        if ot is not None:
            try:
                wi = await h.hass.async_add_executor_job(planner.what_if_day, house, pump, settings, entries, ot)
            except Exception as err:            # only the card's advice: never stop closing the day for it
                _LOGGER.debug("what-if of %s failed: %s", day, err)
                wi = None
            h.log = chl.with_what_if(h.log, day, wi)
        await h.async_save()

    def comfort_advice(self) -> dict | None:
        """The last week's what-ifs for the settings in force (core/hourlog.comfort_advice), for the card."""
        s = self.host.settings()
        return chl.comfort_advice(self.host.log.day_stats, s.comfort, s.night_min, s.store_max)

    async def async_replay_kept_days(self) -> None:
        """After an update that replays a day differently (planner.REPLAY_VERSION): every complete day still in the
        hourly log again, so the saving of the last week (and this month) is counted one way. Older days keep theirs."""
        h = self.host
        today = dt_util.now().date().isoformat()
        h.log = chl.drop_unchecked(h.log)
        days = chl.logged_days(h.log.hour_log, _tz())
        for day in days:
            if day < today:
                await self.async_close_day(day)
        h.log = replace(h.log, replayed_with=planner.REPLAY_VERSION)
        h.event("replayed", days=[d for d in days if d < today], version=planner.REPLAY_VERSION)
        await h.async_save()

    def dhw_samples(self, rows: list) -> list[tuple[int, int, float, int]]:
        """(local weekday, local hour, share on hot water, local day number) of the last weeks, Weheat logs first."""
        return chl.dhw_samples(self.host.weheat.hours, rows, time.time() - DHW_WEEKS * 7 * 86400,
                               lambda t: dt_util.as_local(datetime.fromtimestamp(t, tz=timezone.utc)))

    # ------------------------------------------------------------ for the card and the services
    def history_payload(self, days: int = 7) -> dict:
        """Everything the card's look back needs (websocket roost/history): the hours, the events that explain them,
        the days in numbers."""
        h = self.host
        cut = time.time() - days * 86400
        kinds = {"set", "by_hand", "pause", "resume", "mode", "learned", "set_failed", "login_needed", "window"}
        return {"hours": [e for e in h.log.hour_log if e["ts"] >= cut],
                "events": [e for e in h.events if e.get("kind") in kinds and _iso_ts(e.get("t")) >= cut],
                "days": dict(sorted(h.log.day_stats.items())[-62:]),
                "saving_detail": h.log.saving_detail, "next": self.next_breakdown(),
                "plan_changes": [c for c in h.log.plan_changes if c["ts"] >= cut],
                "comfort": h.settings().comfort, "currency": h.hass.config.currency or "EUR", "mode": h.mode}

    def next_breakdown(self) -> dict | None:
        """The saving per hour of the plan in force (planner.breakdown), with the time of each hour."""
        return chl.next_breakdown(self.view())

    def explain_saving(self, day: str = "yesterday") -> dict:
        """roost.explain_saving: where the saving of a day (replayed at the end of it) or of the next 24 hours (the plan
        in force) comes from, hour by hour against a steady thermostat at equal comfort, and how the plan changed."""
        h = self.host
        cur = h.hass.config.currency or "EUR"
        changes = replan.prune(h.log.plan_changes, time.time())
        if day == "next_24h":
            bd = self.next_breakdown()
            return {"day": day, "currency": cur, "available": bd is not None, **(bd or {}), "plan_changes": changes}
        if day == "yesterday":
            day = (dt_util.now().date() - timedelta(days=1)).isoformat()
        bd = h.log.saving_detail.get(day)
        on_day = [c for c in changes if chl.local_day(c["ts"], _tz()) == day]
        return {"day": day, "currency": cur, "available": bd is not None, **(bd or {}), "plan_changes": on_day}

    def measured_month(self) -> dict | None:
        """This month from the meters, no model (lookback.measured): timing, own solar, the battery."""
        return lookback.month_measured(self.host.log.day_stats, dt_util.now().date().isoformat()[:7])

    def model_band(self) -> float | None:
        return chl.model_band(self.host.check)

    def saving_month(self) -> float | None:
        return chl.saving_month(self.host.log.saving_days, dt_util.now().date().isoformat()[:7])
