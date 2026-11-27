"""OpenTherm steering in the runtime: write the flow to the master, watch its state, switch its control mode.

OpenTherm (held by RoostManager as `otc`) owns the steering state: the memory of what was written (ot_mem), the
samples and stops it learns from (ot_obs, ot_stops, ot_learned), whether Roost switched the master to Home Assistant
(steering) and the fallback seen. It reaches the rest of Roost only through OTHost: the options, Home Assistant reads
and writes, the plan's level per hour, the pump state, the room, events. The decisions themselves are in opentherm.py.
Callers use it as m.otc (m.otc.settings(), m.otc.info(), ...)."""
from __future__ import annotations

import asyncio
from typing import Any, Protocol

from . import curve, opentherm, otlearn, planner
from .const import (
    CONF_OT_CH_ACTIVE,
    CONF_OT_COMM,
    CONF_OT_DHW_ACTIVE,
    CONF_OT_FLOW,
    CONF_OT_FLOW_TEMP,
    CONF_OT_FOLLOW,
    CONF_OT_MAX,
    CONF_OT_MAX_FLOW,
    CONF_OT_MAX_FLOW_NUM,
    CONF_OT_MAX_STARTS,
    CONF_OT_MIN_FLOW,
    CONF_OT_MIN_FLOW_NUM,
    CONF_OT_MIN_OFF,
    CONF_OT_MIN_RUN,
    CONF_OT_MODE,
    CONF_OT_MODE_CURVE,
    CONF_OT_MODE_HA,
    CONF_OT_Q_MIN,
    CONF_OT_QUIET,
    CONF_OT_QUIET_FROM,
    CONF_OT_QUIET_MAX,
    CONF_OT_QUIET_TO,
    CONF_OT_START_KWH,
    CONF_OT_STATE,
    CONF_OT_STATE_OK,
    OT_ENTITY_SUFFIX,
)
from .core import plan as cplan
from .mgr_common import (  # the shared imports and constants  # noqa: F401
    _LOGGER,
    ATTR_ENTITY_ID,
    CONF_DAY_MIN,
    CONF_EMITTER,
    CONF_NIGHT_MIN,
    CONF_ROOM,
    CONF_THERMOSTAT,
    DHW_STATES,
    Context,
    Event,
    EventStateChangedData,
    Reason,
    State,
    _f,
    callback,
    control,
    datetime,
    dt_util,
    time,
    timezone,
)

DHW_SETTLE_S = 900          # after hot water: its heat still in the pipes this long


class OTHost(Protocol):
    """What OpenTherm needs of the manager: no more."""
    hass: Any
    decision: control.Decision | None        # written: what the steering does now
    reason: Any                              # written: airing (a window open)
    notices: Any                             # notices.issue
    care: Any                                # care.set_result

    read: Any                                # entity states as numbers, °C, kW (reader.Reader)

    @property
    def conf(self) -> dict: ...
    @property
    def ot(self) -> bool: ...
    @property
    def ent(self) -> dict[str, str]: ...
    @property
    def mode(self) -> Any: ...
    @property
    def mem(self) -> Any: ...
    @property
    def window(self) -> Any: ...
    held: Any                                # the plan in force (core/plan.Held)
    @property
    def pump(self) -> Any: ...
    @property
    def curve_advice(self) -> Any: ...
    @property
    def changes(self) -> list[dict]: ...
    @property
    def weather(self) -> Any: ...
    @property
    def _heating_since(self) -> float | None: ...
    def pump_state(self) -> str | None: ...
    def room(self) -> float | None: ...
    def settings(self) -> planner.Settings: ...
    def control_settings(self) -> control.ControlSettings: ...
    def is_away(self, ts: float | None = None) -> bool: ...
    def is_day(self, local: datetime) -> bool: ...
    def planned_level(self, t: float) -> float | None: ...
    def is_own_context(self, context_id: str) -> bool: ...
    def _own_context(self) -> Context: ...
    def event(self, kind: str, **data: Any) -> None: ...
    def spawn(self, coro, name: str, background: bool = True) -> Any: ...
    async def _async_save_history(self) -> None: ...
    async def async_save(self) -> None: ...
    def _notify(self) -> None: ...


PLAN_BOX_HOURS = 36   # hours of the plan the box takes (THRM ONE: std::array<float, 36>)
PLAN_SEND_TIMEOUT_S = 5
PLAN_RETRY_S = 600      # after a failed send: again after this (26-11: the box was away at the hour, the new plan waited an hour)
PLAN_ARRIVE_S = 120     # the box shows the plan's hours within this after a send; 0 later means it lost it


class OpenTherm:
    """The OpenTherm steering of one Roost entry, with its own state."""

    def __init__(self, host: OTHost) -> None:
        self.host = host
        self.mem = opentherm.OTMemory()         # OpenTherm steering (opentherm.py)
        self.steering = False                   # the master's control mode set to Home Assistant by Roost
        self.fallback: str | None = None        # the master's state while it should be steered and is not
        self.obs: list[list] = []               # samples while the unit heats (otlearn.sample)
        self.stops: list[list] = []             # [stop, next start, heat still asked]
        self.learned = otlearn.OTLearned()
        self.obs_at = 0.0
        self.was_heating: bool | None = None
        self.learned_hour: int | None = None
        self.dhw_at: float | None = None
        self.flow_acc: list[float] = [0.0, 0.0, 0.0]   # this hour's measured flow while heating: [hour, sum, n]
        self.plan_sent: dict | None = None      # the plan last sent to the box for when Roost is gone: {plan_at, t, hours}
        self.plan_cleared = False               # an empty plan sent since Roost stopped steering (or since the start)
        self.clear_failed_at: float | None = None   # the empty plan could not be sent then (the box away): again later

    # ------------------------------------------------------------ kept over restarts
    def stored(self) -> dict:
        """For the main store."""
        return {"mem": self.mem.as_dict(), "steering": self.steering, "learned": self.learned.as_dict()}

    def restore(self, ot: dict) -> None:
        self.mem = opentherm.OTMemory.from_dict(ot.get("mem"))
        self.steering = bool(ot.get("steering"))
        self.learned = otlearn.OTLearned.from_dict(ot.get("learned"))

    def restore_samples(self, hist: dict) -> None:
        """The samples of the unit while it heats, from the history store (written less often than the main one)."""
        self.obs = [o for o in (hist.get("ot_obs") or []) if isinstance(o, list) and len(o) == 8]
        self.stops = [s for s in (hist.get("ot_stops") or []) if isinstance(s, list) and len(s) == 3]

    def relearn(self) -> None:
        """Forget what Roost learned of the heat pump."""
        self.obs, self.stops, self.learned = [], [], otlearn.OTLearned()
        self.mem.k_factor = 1.0

    # ------------------------------------------------------------ settings
    def settings(self) -> opentherm.OTSettings:
        c = self.host.conf
        a = self.host.curve_advice
        n = curve.emitter_profile(c)[1]
        k = a.k_kw if a is not None and a.k_kw and a.k_kw > 0 else opentherm.DEFAULT_K
        if a is not None and a.n:
            n = a.n
        L = self.learned
        if L.k:                         # measured over OpenTherm: newer and closer than the history's steady hours
            k = L.k
            if L.n:
                n = L.n                 # learned with it: a wrong tick in the options corrects itself
        run = self.host.read.num(c.get(CONF_OT_MIN_RUN))
        lo, hi = self.flow_limits()
        return opentherm.OTSettings(q_min=self.q_min(), min_run_s=run * 60 if run is not None else opentherm.MIN_RUN_S,
                                    min_flow=lo, max_flow=hi, k=k, n=n)

    def box_entity(self, key: str) -> str | None:
        """An entity on the OpenTherm box: as set in the options, else found next to its flow setpoint (same device
        prefix, as detect_opentherm), so an install from before the option has it too."""
        conf = self.host.conf
        eid = conf.get(key)
        if eid:
            return eid
        flow, (domain, suffix) = conf.get(CONF_OT_FLOW), OT_ENTITY_SUFFIX[key]
        base = OT_ENTITY_SUFFIX[CONF_OT_FLOW][1]
        if not flow or not str(flow).endswith(base):
            return None
        guess = f"{domain}.{str(flow).split('.', 1)[1][: -len(base)]}{suffix}"
        return guess if self.host.hass.states.get(guess) is not None else None

    def flow_limits(self) -> tuple[float, float]:
        """Lowest and highest flow: the box's own when it has them (it guards the unit also without Roost), else
        Roost's settings (another OpenTherm gateway)."""
        conf = self.host.conf
        lo, hi = float(conf[CONF_OT_MIN_FLOW]), float(conf[CONF_OT_MAX_FLOW])
        blo = self.host.read.num(self.box_entity(CONF_OT_MIN_FLOW_NUM))
        bhi = self.host.read.num(self.box_entity(CONF_OT_MAX_FLOW_NUM))
        if blo is not None and bhi is not None and 5 <= blo < bhi <= 80:
            return blo, bhi
        return lo, hi

    def q_min(self) -> float:
        """The lowest output planned with: learned, but never below Q_MIN_SHARE of the setting (samples of defrost or
        of the master's own curve could pull it too low, and a level the unit cannot make stops it)."""
        setting = float(self.host.conf[CONF_OT_Q_MIN])
        L = self.learned.q_min
        return round(max(setting * otlearn.Q_MIN_SHARE, L), 2) if L else setting

    def quiet(self) -> list | None:
        """Quiet hours (from, to, kW) when set: not above that output then."""
        c = self.host.conf
        q = float(c[CONF_OT_QUIET_MAX])
        on = bool(c.get(CONF_OT_QUIET)) and q > 0
        return [int(c[CONF_OT_QUIET_FROM]), int(c[CONF_OT_QUIET_TO]), q] if on and int(c[CONF_OT_QUIET_FROM]) != int(c[CONF_OT_QUIET_TO]) else None

    # ------------------------------------------------------------ what the unit and the master do now
    def level_now(self) -> float:
        """The heat the unit makes now for space heating (kW; 0 when it does not heat)."""
        if self.host.pump_state() != "heating":
            return 0.0
        return self.host.read.kw(self.host.ent.get("power_out")) or 0.0

    def _fresh_temp(self, eid: str | None, t: float, max_age: float = 900) -> float | None:
        """A temperature only when the sensor reported within max_age (a frozen flow reading must not steer)."""
        st = self.host.read.state(eid)
        if st is None:
            return None
        seen = getattr(st, "last_reported", None) or st.last_updated
        if seen is not None and t - seen.timestamp() > max_age:
            return None
        return self.host.read.temp(eid)

    def state(self) -> str | None:
        st = self.host.read.state(self.host.conf.get(CONF_OT_STATE))
        return st.state if st else None

    def flows(self) -> list[float]:
        """The flow each hour of the plan asks (0 = off), from the room the plan expects at the start of the hour."""
        plan = self.host.held.plan
        if not plan:
            return []
        cs, room = self.settings(), self.host.room()
        k = cs.k * self.mem.k_factor
        out, T = [], room if room is not None else self.host.settings().comfort
        for h in plan.hours:
            lvl = h.level if h.level is not None else h.sp
            if lvl > 0:
                f = max(opentherm.flow_for(lvl, T, k, cs.n), opentherm.flow_for(cs.q_min, T, k, cs.n) + 1.0)
                out.append(round(round(max(cs.min_flow, min(cs.max_flow, f)) * 2) / 2, 1))
            else:
                out.append(0.0)
            T = h.t_end
        return out

    def curve_entity(self) -> str | None:
        """The master's own heating-curve flow (what it asks on its curve now), next to its flow setpoint: the THRM ONE
        names it <device>_curve_flow. None when the master has no such sensor."""
        flow = str(self.host.conf.get(CONF_OT_FLOW) or "")
        if not flow.startswith("number.") or not flow.endswith("_flow_setpoint"):
            return None
        eid = "sensor." + flow[len("number."):-len("_flow_setpoint")] + "_curve_flow"
        return eid if self.host.read.state(eid) is not None else None

    def air_entity(self) -> str | None:
        """The unit's own air-inlet temperature as the master reads it over OpenTherm, next to its flow setpoint (the
        THRM ONE: <device>_air_inlet_temperature): the same sensor the Weheat cloud calls its outside temperature, live
        also when the cloud is away. None when the master has no such sensor."""
        flow = str(self.host.conf.get(CONF_OT_FLOW) or "")
        if not flow.startswith("number.") or not flow.endswith("_flow_setpoint"):
            return None
        eid = "sensor." + flow[len("number."):-len("_flow_setpoint")] + "_air_inlet_temperature"
        return eid if self.host.read.state(eid) is not None else None

    def box_sensor(self, suffix: str) -> str | None:
        """A sensor of the box next to its flow setpoint (THRM ONE: sensor.<device><suffix>), None when it has none."""
        flow = str(self.host.conf.get(CONF_OT_FLOW) or "")
        if not flow.startswith("number.") or not flow.endswith("_flow_setpoint"):
            return None
        eid = "sensor." + flow[len("number."):-len("_flow_setpoint")] + suffix
        return eid if self.host.read.state(eid) is not None else None

    def plan_service(self) -> str | None:
        """The box's action that takes Roost's plan for when Roost or HA is gone (THRM ONE 1.9.0: esphome.<device>_set_plan,
        the device named as in its flow setpoint). None when the box has no such action: older firmware works on."""
        flow = str(self.host.conf.get(CONF_OT_FLOW) or "")
        if not flow.startswith("number.") or not flow.endswith("_flow_setpoint"):
            return None
        name = flow[len("number."):-len("_flow_setpoint")] + "_set_plan"
        return name if self.host.hass.services.has_service("esphome", name) else None

    def plan_for_box(self, t: float) -> tuple[list[float], list[float]] | None:
        """From the hour of t on: the flow per hour (0 = off) and the outdoor temperature as the unit's own sensor would
        read it (the forecast plus the learned bias), at most PLAN_BOX_HOURS. None without a plan for this hour."""
        h = self.host
        i0 = cplan.index(h.held.at, t)
        flows = self.flows()
        if i0 is None or not 0 <= i0 < len(flows):
            return None
        flows = flows[i0:i0 + PLAN_BOX_HOURS]
        ins = h.held.hours[i0:i0 + len(flows)]
        if len(ins) < len(flows):
            flows = flows[:len(ins)]
        outs = [round(x.t_out + h.pump.bias + x.t_adj, 1) for x in ins]
        return (flows, outs) if flows else None

    async def async_send_plan(self, t: float) -> None:
        """Send the plan to the box for when Roost or HA is gone: when a new plan is held, else every hour. Only while
        Roost steers the box (active). Not steering (shadow, off, back to the thermostat): an empty plan once, so a box
        set back to Home Assistant by hand does not run an old plan for up to 36 hours."""
        h = self.host
        if h.mode != "active" or not self.steering:
            # only once it went through: a box away now would otherwise keep the old plan (review 27-11)
            if not self.plan_cleared and (self.clear_failed_at is None or t - self.clear_failed_at >= PLAN_RETRY_S) \
                    and (svc := self.plan_service()):
                self.plan_sent = None
                err = await self._async_call_plan(svc, [], [], 0)
                self.plan_cleared, self.clear_failed_at = err is None, (t if err else None)
            return
        sent = self.plan_sent or {}
        # the box lost the plan (it restarted: the plan is not kept in its flash): again at once, not after the hour
        lost = (sent.get("hours", 0) > 0 and t - sent.get("t", t) > PLAN_ARRIVE_S
                and h.read.num(self.box_sensor("_plan_hours_left")) == 0)
        wait = PLAN_RETRY_S if sent.get("error") else 3600      # after a failure (the box away) sooner again
        if sent.get("plan_at") == h.held.at and t - sent.get("t", 0.0) < wait and not lost:
            return
        svc = self.plan_service()
        got = self.plan_for_box(t) if svc else None
        if svc is None or got is None:
            return
        flows, outs = got
        self.plan_cleared, self.clear_failed_at = False, None
        err = await self._async_call_plan(svc, flows, outs, int(t % 3600))
        # after a failure not again before PLAN_RETRY_S, also for this plan
        self.plan_sent = ({"plan_at": h.held.at, "t": t, "hours": 0, "error": err} if err else
                          {"plan_at": h.held.at, "t": t, "hours": len(flows)})

    async def _async_call_plan(self, svc: str, flows: list[float], outs: list[float], sec: int) -> str | None:
        """Call the box's set_plan; the error as text, None when it went through."""
        h = self.host
        try:
            async with asyncio.timeout(PLAN_SEND_TIMEOUT_S):     # a box that hangs must not hold up the control tick
                await h.hass.services.async_call("esphome", svc, {"flows": flows, "outside": outs, "sec_into_hour": sec},
                                                 blocking=True, context=h._own_context())
        except Exception as err:  # noqa: BLE001 - the plan on the box is a spare; steering goes on
            _LOGGER.debug("Roost could not send its plan to the box: %s", err)
            return str(err)[:120] or type(err).__name__
        return None

    def info(self) -> dict:
        """For the setpoint sensor's attributes and diagnostics."""
        h, conf, plan = self.host, self.host.conf, self.host.held.plan
        m, cs = self.mem, self.settings()
        curve_eid = self.curve_entity()
        follow = h.read.state(conf.get(CONF_OT_FOLLOW))
        return {"control": "opentherm", "flow": m.flow, "level": m.level, "state": self.state(),
                "flow_now": self.flow_now(time.time()), "hot_water": self.hot_water(),
                "live_from_master": bool(conf.get(CONF_OT_FLOW_TEMP) or conf.get(CONF_OT_CH_ACTIVE)),
                "steering": bool(self.steering), "fallback": self.fallback, "k": round(cs.k, 3), "n": cs.n,
                "k_factor": m.k_factor, "trim": m.trim, "q_min": cs.q_min,
                "levels": [x.level for x in plan.hours] if plan else [], "flows": self.flows(),
                "learned": self.learned.as_dict(), "samples": len(self.obs),
                "learn_need": {"steady": otlearn.MIN_STEADY, "starts": otlearn.MIN_STARTS_KWH},
                # in shadow mode the master heats on its own curve: what that curve asks now, to set against Roost
                "curve_flow": h.read.num(curve_eid), "curve_flow_entity": curve_eid,
                "q_min_setting": float(conf[CONF_OT_Q_MIN]), "indoor_kw": {"idle": h.pump.indoor_idle_kw, "run": h.pump.indoor_run_kw}, "start_kwh_setting": float(conf[CONF_OT_START_KWH]),
                "min_flow": self.flow_limits()[0], "max_flow": self.flow_limits()[1],
                "min_flow_entity": self.box_entity(CONF_OT_MIN_FLOW_NUM), "max_flow_entity": self.box_entity(CONF_OT_MAX_FLOW_NUM),
                "max_starts": int(conf[CONF_OT_MAX_STARTS]), "quiet": self.quiet(), "quiet_on": bool(conf.get(CONF_OT_QUIET)),
                "quiet_from": int(conf[CONF_OT_QUIET_FROM]), "quiet_to": int(conf[CONF_OT_QUIET_TO]),
                "quiet_max": float(conf[CONF_OT_QUIET_MAX]),
                "min_run": h.read.num(conf.get(CONF_OT_MIN_RUN)), "min_run_entity": conf.get(CONF_OT_MIN_RUN),
                "min_off": h.read.num(conf.get(CONF_OT_MIN_OFF)), "min_off_entity": conf.get(CONF_OT_MIN_OFF),
                "follow_curve": (follow.state == "on") if follow else None,
                "plan_service": self.plan_service(),
                "plan_sent": {**self.plan_sent, "t": datetime.fromtimestamp(self.plan_sent["t"], tz=timezone.utc).isoformat(timespec="seconds")}
                if self.plan_sent else None,
                "starts_planned": planner.count_starts([x.level or 0.0 for x in plan.hours[:24]], self.mem.level) if plan else None,
                "last_write": datetime.fromtimestamp(m.last_write, tz=timezone.utc).isoformat(timespec="seconds") if m.last_write else None}

    # ------------------------------------------------------------ the master's control mode
    async def async_reconcile(self) -> None:
        """The master's control mode follows Roost: Home Assistant while Roost steers it (OpenTherm, active), else its
        own heating curve — only when that changes (not at every restart: the master keeps the last request for its
        command timeout and Roost writes again at once)."""
        h = self.host
        want = h.ot and h.mode == "active"
        if want == bool(self.steering):
            return
        eid = h.conf.get(CONF_OT_MODE)
        option = h.conf[CONF_OT_MODE_HA] if want else h.conf[CONF_OT_MODE_CURVE]
        if eid and h.read.state(eid) is not None:
            try:
                await h.hass.services.async_call("select", "select_option", {ATTR_ENTITY_ID: eid, "option": option},
                                                 blocking=True, context=h._own_context())
                h.event("ot_mode", option=option)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Roost could not set the OpenTherm master's control mode to %s: %s", option, err)
                h.event("ot_mode_failed", option=option, error=str(err)[:200])
                return
        elif want:
            return                       # the master is not there yet: try again next round
        self.steering = want
        if want:
            t = time.time()
            heating = self.heating() and not self.after_dhw(t)
            opentherm.take_over(t, self.mem, heating, self.settings(), self.flow_now(t) if heating else None)
            h.event("ot_take_over", running=heating)
        if not want:
            self.mem.bad_since = None
            self.fallback = None
            h.notices.issue("opentherm_fallback", False)
        await h.async_save()

    # ------------------------------------------------------------ steering
    def _bit(self, key: str) -> bool | None:
        """A status bit the master reads from the unit (OpenTherm ID 0) when its entity is chosen and there: at once,
        where the Weheat cloud lags a minute or two. None: not known, use the Weheat state."""
        st = self.host.read.state(self.host.conf.get(key))
        return None if st is None else st.state == "on"

    def heating(self) -> bool:
        """The unit heats the house now: the master's CH bit, else the Weheat state."""
        ch, dhw = self._bit(CONF_OT_CH_ACTIVE), self._bit(CONF_OT_DHW_ACTIVE)
        if ch is not None:
            return ch and not dhw
        return self.host.pump_state() == "heating"

    def hot_water(self) -> bool:
        dhw = self._bit(CONF_OT_DHW_ACTIVE)
        return dhw if dhw is not None else self.host.pump_state() in DHW_STATES

    def flow_now(self, t: float) -> float | None:
        """The flow now: what the master reads (OpenTherm ID 25, live) while the unit heats the house, else the Weheat
        cloud's. Only while heating: a Weheat reports its central-heating side there, which stands still during hot
        water."""
        conf = self.host.conf
        if conf.get(CONF_OT_FLOW_TEMP) and self.heating():
            v = self._fresh_temp(conf.get(CONF_OT_FLOW_TEMP), t, max_age=300)
            if v is not None:
                return v
        return self._fresh_temp(self.host.ent.get("water_out"), t)

    def after_dhw(self, t: float) -> bool:
        """Hot water now or within DHW_SETTLE_S: the pipes still hold hot water, the flow and heat say nothing about
        space heating (no learning, no correcting on them)."""
        if self.hot_water():
            self.dhw_at = t
        return self.dhw_at is not None and t - self.dhw_at < DHW_SETTLE_S

    def observe(self, t: float, heating: bool) -> None:
        """Samples of what the unit does while it heats (whoever steers it), and its stops and starts, to learn its
        lowest output, emitter, start cost, COP at a low speed and rest after a stop (otlearn.py)."""
        h = self.host
        was = self.was_heating
        self.was_heating = heating
        if was and not heating:
            self.stops.append([round(t), None, self.mem.flow > 0])     # a stop while heat was still asked
        elif heating and was is False and self.stops and self.stops[-1][1] is None:
            self.stops[-1][1] = round(t)
        since = h._heating_since
        if heating and since is not None and t - self.obs_at >= otlearn.OBS_S and not self.after_dhw(t):
            wx = h.weather.get(int(t // 3600 * 3600))
            o = otlearn.sample(t, h.read.kw(h.ent.get("power_out")), h.read.kw(h.ent.get("power_in")),
                               self.flow_now(t), h.room(), wx[0] if wx else None,
                               (t - since) / 60, self.mem.flow)
            if o:
                self.obs.append(o)
                self.obs_at = t
        cut = t - otlearn.KEEP_S
        self.obs = [o for o in self.obs if o[0] >= cut]
        self.stops = [s for s in self.stops if s[0] >= cut][-200:]
        if int(t // 3600) != self.learned_hour:
            self.learned_hour = int(t // 3600)
            n = curve.emitter_profile(h.conf)[1]
            new = otlearn.learn(self.obs, self.stops, h.pump, n)
            if new != self.learned:
                h.event("ot_learned", **{k: v for k, v in new.as_dict().items() if v is not None})
            self.learned = new
            if self.obs:
                h.spawn(h._async_save_history(), "save the OpenTherm samples")

    async def async_control(self, t: float) -> None:
        h = self.host
        self.after_dhw(t)
        self.observe(t, self.heating())
        await self.async_reconcile()
        active = h.mode == "active"
        if h.mode == "off":
            h.decision = control.Decision(None, Reason("off"), None)
            await self.async_send_plan(t)        # not steering: the box's plan is cleared
            return
        planned = h.planned_level(t)
        next_level = h.planned_level(t + 3600)
        if h.window.active() and h.window.via == "contact":
            planned, h.reason = 0.0, Reason("airing")            # a window open: no heat for the outdoors
            next_level = None                                    # ... now, not after the hour
        room = h.room()
        local = dt_util.as_local(datetime.fromtimestamp(t, tz=timezone.utc))
        hard = (h.settings().away_min if h.is_away(t) else float(h.conf[CONF_DAY_MIN]) if h.is_day(local)
                else float(h.conf[CONF_NIGHT_MIN]))
        paused = (h.mem.pause_until - t) / 60 if h.mem.pause_until and t < h.mem.pause_until else None
        heating = self.heating()
        flow_now = self.flow_now(t)
        if self.after_dhw(t):
            heating, flow_now = False, None          # hot water (or just after): its flow is not the heating's
        if heating and flow_now is not None:          # the hour's measured flow, for the card's look back
            hour = t // 3600 * 3600
            if self.flow_acc[0] != hour:
                self.flow_acc = [hour, 0.0, 0.0]
            self.flow_acc[1] += flow_now
            self.flow_acc[2] += 1
        d = opentherm.decide(t, planned, room, hard, self.mem, self.settings(), active,
                             measured_kw=self.level_now() if heating else None, measured_flow=flow_now, running=heating,
                             pump_max_flow=h.read.num(h.conf.get(CONF_OT_MAX)), paused_min=paused, next_level=next_level)
        h.decision = control.Decision(d.flow if d.write else None, d.why, d.flow)
        if d.write:
            await self.async_write(t, d)
        # the master's state while Roost steers it
        bad = opentherm.watch(t, self.state(), h.conf[CONF_OT_STATE_OK], active and bool(self.steering) and paused is None,
                              self.mem)
        comm = h.read.state(h.conf.get(CONF_OT_COMM))
        if bad is None and active and comm is not None and comm.state == "on":
            bad = "communication_error"
        if bad != self.fallback:
            h.event("ot_fallback" if bad else "ot_back", state=bad)
            self.fallback = bad
        h.notices.issue("opentherm_fallback", bad is not None, placeholders={"state": bad or ""})
        await self.async_send_plan(t)

    async def async_write(self, t: float, d: opentherm.OTDecision) -> None:
        h = self.host
        eid = h.conf.get(CONF_OT_FLOW)
        if not eid:
            return
        old = _f((h.hass.states.get(eid) or State(eid, "unknown")).state)
        try:
            await h.hass.services.async_call("number", "set_value", {ATTR_ENTITY_ID: eid, "value": d.flow},
                                             blocking=True, context=h._own_context())
            self.mem.last_write = t
            if old is None or abs(old - d.flow) >= 0.05:
                h.event("ot_set", old=old, new=d.flow, level=d.level, why=d.why.code, room=h.room())
            h.care.set_result(True)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Roost could not write the flow setpoint: %s", err)
            h.event("set_failed", new=d.flow, error=str(err)[:200])
            h.care.set_result(False, str(err))
            h.decision = control.Decision(None, Reason("ot_set_failed"), d.flow)

    @callback
    def on_flow(self, event: Event[EventStateChangedData]) -> None:
        """The flow setpoint changed by someone else (not Roost's context) while Roost steers: pause, as for a thermostat
        changed by hand. The master then falls back on its own curve after its command timeout."""
        h = self.host
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if old is None or new is None or h.is_own_context(event.context.id) or h.mode != "active" or not h.ot:
            return
        a, b = _f(old.state), _f(new.state)
        if a is None or b is None or abs(a - b) < 0.05 or abs(b - self.mem.flow) < 0.05:
            return
        h.mem.pause_until = time.time() + h.control_settings().pause_hours * 3600
        h.changes.append({"ts": round(time.time()), "from": a, "to": b, "room": h.room(), "flow": True})
        h.event("by_hand", old=a, new=b, room=h.room(), pause_h=h.control_settings().pause_hours, flow=True,
                context_user=bool(event.context.user_id))
        h.hass.async_create_task(h.async_save())
        h._notify()
