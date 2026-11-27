"""Notices (repairs), ready to steer, and watching for a window open.

The watching itself is pure: watch(health, readings) keeps the timers in a Health (mgr_common.Health, held by the
manager as `health`: since when each problem is seen, and the notices open) and says which notices should be open;
following() and windows_open() likewise. Notices (held by RoostManager as `notices`) reads the manager into HealthReadings,
opens and closes the notices in Home Assistant (repairs) and notifies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.climate import ClimateEntityFeature

from . import control_detect
from .mgr_common import (  # the shared imports and constants  # noqa: F401
    _LOGGER,
    CONF_COMFORT,
    CONF_DAY_FROM,
    CONF_DAY_MIN,
    CONF_DAY_TO,
    CONF_NIGHT_MIN,
    CONF_THERMOSTAT,
    CONF_WINDOW_SENSORS,
    DOMAIN,
    HOUSE_COLD_K,
    HOUSE_COLD_MIN,
    LEARN_HOUR,
    LEARN_MINUTE,
    NO_LEVER_KW,
    NOT_FOLLOWING_MIN,
    ROOM_SILENT_MIN,
    Health,
    _f,
    _i,
    _iso_ts,
    check,
    comfort,
    datetime,
    dt_util,
    ir,
    schedule,
    time,
    timedelta,
    timezone,
)

if TYPE_CHECKING:
    from .manager import (
        RoostManager,  # for the type checker only: no import cycle at run time
    )


@dataclass(frozen=True)
class HealthReadings:
    """What the health check looks at, at time t."""
    t: float
    on_own_curve: bool          # the unit heats while the thermostat asks for no heat (not with OpenTherm)
    room: float | None
    weheat_found: bool          # Roost found the Weheat entities
    low: float                  # the room's hard minimum now (away, comfort hours or night)
    steering: bool              # Roost steers (active)
    window_open: bool


def watch(h: Health, r: HealthReadings) -> dict[str, bool]:
    """Keep the timers in h and say which notices should be open, in the order they are given."""
    t = r.t
    h.not_following_since = (h.not_following_since or t) if r.on_own_curve else None
    h.room_missing_since = (h.room_missing_since or t) if r.room is None else None
    # Roost steers and the room stays well below its minimum: tell the user (a unit that cannot keep up, a
    # thermostat that does not pass the setpoint on, a model far off)
    cold_now = r.steering and r.room is not None and r.room < r.low - HOUSE_COLD_K and not r.window_open
    h.house_cold_since = (h.house_cold_since or t) if cold_now else None
    return {"not_following": bool(h.not_following_since and t - h.not_following_since > NOT_FOLLOWING_MIN * 60),
            "room_missing": bool(h.room_missing_since and t - h.room_missing_since > ROOM_SILENT_MIN * 60),
            "weheat_missing": not r.weheat_found,
            "house_cold": bool(h.house_cold_since and t - h.house_cold_since >= HOUSE_COLD_MIN * 60)}


def following(h: Health, has_setpoint: bool, t: float) -> bool | None:
    """The unit follows the thermostat (not on its own heating curve); None when its water setpoint is not known."""
    if not has_setpoint:
        return None
    return not (h.not_following_since and t - h.not_following_since > NOT_FOLLOWING_MIN * 60)


def windows_open(states: list) -> bool | None:
    """True when one of the window/door sensors is open, None when none are chosen (or none report)."""
    known = [s.state for s in states if s is not None and s.state in ("on", "off")]
    return ("on" in known) if known else None


METHOD_FRESH_S = 2 * 3600  # the unit's reported control method counts this long (polled every 5 min; kept over restarts)
READY_HOLD_S = 1800        # a change of 'ready' seen by the tick counts once it held this long


class Notices:
    """Held by RoostManager as `notices`; reaches the rest of Roost through the manager (self.h)."""
    def __init__(self, host: RoostManager) -> None:
        self.h = host
        self._flip_since: float | None = None       # since when the tick sees 'ready' differ from what is shown

    def issue(self, key: str, active: bool, fixable: bool = False, placeholders: dict | None = None,
               translation_key: str | None = None, data: dict | None = None) -> None:
        iid = f"{self.h.entry.entry_id}_{key}"
        if active != (key in self.h.health.issues):
            self.h.event("repair", issue=key, active=active)
        if active and key not in self.h.health.issues:
            ir.async_create_issue(self.h.hass, DOMAIN, iid, is_fixable=fixable, severity=ir.IssueSeverity.WARNING,
                                  translation_key=translation_key or key,
                                  data={"entry_id": self.h.entry.entry_id, "issue": key, **(data or {})} if fixable else None,
                                  translation_placeholders={"name": self.h.entry.title, **(placeholders or {})})
            self.h.health.issues.add(key)
        elif not active and key in self.h.health.issues:
            ir.async_delete_issue(self.h.hass, DOMAIN, iid)
            self.h.health.issues.discard(key)

    def issue_comfort(self) -> None:
        """A comfort setting suggested from the changes made by hand (comfort.suggest); the user accepts or ignores it."""
        c = self.h.conf

        def local(ts: float) -> tuple[str, int]:
            loc = dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc))
            return loc.date().isoformat(), loc.hour
        def local_minute(ts: float) -> tuple[str, int]:
            loc = dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc))
            return loc.date().isoformat(), loc.hour * 60 + loc.minute
        sched = comfort.scheduled(self.h.changes, local_minute, time.time())
        self.issue("thermostat_schedule", bool(sched), placeholders={
            "times": ", ".join(f"{s['minute'] // 60:02d}:{s['minute'] % 60:02d} → {s['to']:g} °C" for s in sched)})
        by_schedule = {t for s in sched for t in s["ts"]}
        own = [x for x in self.h.changes if x["ts"] not in by_schedule]
        if c.get(schedule.ENABLED):
            self.h.suggestion = None
            self.issue("comfort", False)
            return
        sug = comfort.suggest(own, local, time.time(), int(c[CONF_DAY_FROM]), int(c[CONF_DAY_TO]),
                              float(c[CONF_COMFORT]), float(c[CONF_DAY_MIN]))
        if self.h.suggestion is not None and (sug is None or sug.as_dict() != self.h.suggestion.as_dict()):
            self.issue("comfort", False)
        self.h.suggestion = sug
        if sug is not None:
            cur = {"comfort": c[CONF_COMFORT], "day_from": c[CONF_DAY_FROM], "day_to": c[CONF_DAY_TO]}[sug.key]
            fmt = (lambda v: f"{float(v):g}") if sug.key == "comfort" else (lambda v: f"{int(v)}:00")
            self.issue("comfort", True, fixable=True, translation_key=f"suggest_{sug.kind}", data=sug.as_dict(),
                        placeholders={"current": fmt(cur), "value": fmt(sug.value), "days": str(sug.days), "count": str(sug.count)})

    async def async_accept_suggestion(self, key: str, value: float) -> None:
        """The user accepted a suggested comfort setting: store it (the entry reloads) and start counting afresh."""
        self.h.changes = []
        self.h.suggestion = None
        await self.h.async_save()
        v = int(value) if key in (CONF_DAY_FROM, CONF_DAY_TO) else float(value)
        self.h.hass.config_entries.async_update_entry(self.h.entry, options={**self.h.entry.options, key: v})

    def thermostat_writable(self) -> bool | None:
        """Can Roost set the thermostat's temperature? False when the climate entity has no target temperature (a
        read-only helper, issue #11); None when unknown (OpenTherm steering, no thermostat, or not loaded yet)."""
        ent = self.h.conf.get(CONF_THERMOSTAT)
        if self.h.ot or not ent or not str(ent).startswith("climate."):
            return None
        st = self.h.hass.states.get(ent)
        feats = st.attributes.get("supported_features") if st is not None else None
        if feats is None:
            return None
        try:
            return bool(int(feats) & ClimateEntityFeature.TARGET_TEMPERATURE)
        except (TypeError, ValueError):
            return None

    def lever(self) -> bool:
        """Does a setpoint move the heat pump? Not when the learned response is too weak, nor when the thermostat
        cannot be set at all."""
        p = self.h.pump
        if p.resp_source == "learned" and p.k is not None and p.k < NO_LEVER_KW:
            return False
        return self.thermostat_writable() is not False

    def following_now(self) -> bool | None:
        """Does the heat pump follow the thermostat? False as well when the unit runs on its own heating curve: it says
        so in its log, or it does not answer steps in the requested water temperature (control_detect). Issue #11: a
        unit on its heating curve with a non-smart thermostat seldom trips the not-following watch. OpenTherm steering
        writes the water temperature itself, so there the thermostat does not matter."""
        f = self.following
        if self.h.ot or f is False:
            return f
        now = self.h.card.cs.weheat_now
        method = control_detect.method_name(now.get("method")) if _iso_ts(now.get("at")) > time.time() - METHOD_FRESH_S else None
        seen = control_detect.detect(self.h.card.steps.steps, time.time()).mode
        if control_detect.HEATING_CURVE in (method, seen):
            return False
        return f

    def update_ready(self, track: bool = True, at_start: bool = False) -> None:
        """Ready to steer, from the last self-check and what is known now about the lever and the heat pump.
        track=False (the tick): a change only counts once it held READY_HOLD_S, so a step window or a log sliding
        over its edge does not open and close the notice. at_start: the thermostat may not be loaded yet, so no
        notice is opened until it is."""
        got = (check.readiness(self.h.check, self.following_now(), self.lever(), self.h.check.get("winter"))
               if self.h.check else (False, []))
        if not track and got[0] != self.h.ready:
            since = self._flip_since if self._flip_since is not None else time.time()
            self._flip_since = since
            if time.time() - since < READY_HOLD_S:
                return
        self._flip_since = None
        self.h.ready, self.h.ready_missing = got
        if at_start and not self.h.ot and self.h.conf.get(CONF_THERMOSTAT) and self.thermostat_writable() is None:
            return                          # the tick decides once the thermostat is there
        self.issue_ready(track)

    def issue_ready(self, track: bool = True) -> None:
        """Tell the user once the self-check says Roost can steer (only while in shadow mode; the user decides, and may
        ask not to be told again). track: a change seen here may notify (the nightly check and a mode change; not the
        tick, which would notify twice next to the not-following notice)."""
        rmse = self.h.check.get("rmse_6h")
        if track:
            if self.h.mode == "active" and getattr(self, "_ready_seen", None) is True and not self.h.ready:
                self.h.care.notify_user("steering_not_ready")     # steering on, and the check no longer passes
            self._ready_seen = self.h.ready
        self.issue("ready_for_active", self.h.mode == "shadow" and self.h.ready and not self.h.ready_muted, fixable=True,
                    placeholders={"rmse": f"{rmse:.2f}" if rmse is not None else "?",
                                  "hours": str(self.h.check.get("heating_hours", 0)), "days": str(self.h.check.get("days", 0))})

    async def async_mute_ready(self) -> None:
        """'Do not tell me again' from the notice: it stays away until the user switches to active themselves (then a
        later 'ready' after going back to shadow is news again)."""
        self.h.ready_muted = True
        self.issue("ready_for_active", False)
        await self.h.async_save()

    def check(self, t: float) -> None:
        # the heat pump heats while the thermostat asks for no heat: it is on its own heating curve
        demand = self.h.read.num(self.h.ent.get("water_setpoint"))
        heating = self.h.pump_state() == "heating" and (self.h.read.kw(self.h.ent.get("power_in")) or 0.0) > 0.4
        room = self.h.room()
        loc = dt_util.as_local(datetime.fromtimestamp(t, tz=timezone.utc))
        low = (self.h.settings().away_min if self.h.is_away(t) else
               float(self.h.conf[CONF_DAY_MIN]) if self.h.is_day(loc) else float(self.h.conf[CONF_NIGHT_MIN]))
        issues = watch(self.h.health, HealthReadings(
            t=t, on_own_curve=bool(heating and demand is not None and demand <= 15 and not self.h.ot),   # OpenTherm: the master's state tells
            room=room, weheat_found=bool(self.h.ent), low=low, steering=self.h.mode == "active",
            window_open=bool(self.h.window.active())))
        self.issue("not_following", issues["not_following"])
        self.issue("room_missing", issues["room_missing"])
        self.issue("weheat_missing", issues["weheat_missing"])
        cold = issues["house_cold"]
        if cold and "house_cold" not in self.h.health.issues:
            self.h.care.notify_user("house_cold", room=f"{room:.1f}", minimum=f"{low:g}")
        self.issue("house_cold", cold, placeholders={"room": f"{room:.1f}" if room is not None else "?", "minimum": f"{low:g}"})
        self.update_ready(track=False)      # the lever and the heat pump's control may change any time

    @property
    def following(self) -> bool | None:
        return following(self.h.health, bool(self.h.ent.get("water_setpoint")), time.time())

    def windows_open(self) -> bool | None:
        """The chosen window/door sensors: True when one is open, None when none are chosen (or none report)."""
        return windows_open([self.h.read.state(e) for e in self.h.conf.get(CONF_WINDOW_SENSORS) or []])

    def watch_window(self, t: float) -> None:
        ev = self.h.window.feed(t, self.h.room(), self.windows_open())
        if ev == "open":
            self.h.event("window", phase="open", via=self.h.window.via, before=self.h.window.before, room=self.h.room())
            self.h._notify()
        elif ev == "end":
            self.h.event("window", phase="end", room=self.h.room())
            self.h.window.prune(t - 400 * 86400)
            if self.h._airing_from is not None:
                self.h._airing_from = None
                self.h.mem.last_write = None          # back to the plan at once, not after the change interval
            # the room is not what the plan expected any more: plan afresh
            self.h.hass.async_create_background_task(self.h._async_tick(None, force_plan="window"), "roost: plan after airing")
            self.h._notify()

    def ready_eta(self) -> tuple[str, datetime | None]:
        """What Roost still waits for before it can steer, and when it expects that (local time, or None)."""
        now = dt_util.now()
        nxt = now.replace(hour=LEARN_HOUR, minute=LEARN_MINUTE, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        missing = [] if self.h.ready else (self.h.ready_missing or ["temperature"])
        code, ts = check.eta(missing, self.h.check, self.h.weheat.import_info if self.h.wh.importing else {}, now.timestamp(), nxt.timestamp())
        return code, dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc)) if ts else None
