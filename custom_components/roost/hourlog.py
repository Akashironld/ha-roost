"""The hourly log and the day numbers: what was planned, predicted and what happened (the look back). A mixin of RoostManager (manager.py): the methods use its state."""
from __future__ import annotations

from .mgr_common import *  # noqa: F401,F403 - the shared imports and constants
from .mgr_common import _LOGGER, _f, _i, _iso_ts  # noqa: F401


class HourLogMixin:
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
        pr = self.pred.get(hour, {})
        self.hour_log.append({"ts": hour, "T": round(room, 2), "E": round(self.storage_e, 2), "sp": sp, "sp_t": self.thermostat_sp(),
                              "t_out": wx[0], "rad": round(self.sun_on_house(hour, wx), 4), "hour": dt_util.as_local(now).hour,
                              "wind": wx[2] if wx[2] is not None else 3.5, "p_grid": h.p_grid, "p_own": h.p_own, "own": h.own_kw,
                              "day": self.is_day(dt_util.as_local(now)),
                              # for looking back: the plan, its reason, what was predicted for this hour, the mode
                              "sp_plan": self.plan.first.sp if self.plan and self.plan.first else None,
                              "reason": self.reason.code, "args": dict(self.reason.args),
                              "p6": pr.get("p6"), "p1": pr.get("p1"), "mode": self.mode, "window": hour in self.window.hours,
                              "paused": bool(self.mem.pause_until and self.mem.pause_until > time.time())})
        self.hour_log = self.hour_log[-HOUR_LOG_KEPT:]
        self.pred = {k: v for k, v in self.pred.items() if k > hour - 7200}
        self.spawn(self.async_save(), "save the hour", background=False)   # a crash or power cut loses at most an hour

    def _remember_prediction(self, now: datetime, p) -> None:
        """The room the plan expects at the start of the coming hours, 1 and 6 hours ahead, to set beside what happened."""
        base = int(now.timestamp() // 3600 * 3600)
        for j, hp in enumerate(p.hours[:6]):
            ahead = j + 1
            if ahead in (1, 6):
                self.pred.setdefault(base + ahead * 3600, {})[f"p{ahead}"] = round(hp.t_end, 2)

    async def _async_close_day(self, day: str) -> None:
        """Replay yesterday with what Roost set and with a steady thermostat, from the same start (same model, same
        weather, same prices): the difference is the saving."""
        entries = [e for e in self.hour_log if dt_util.as_local(datetime.fromtimestamp(e["ts"], tz=timezone.utc)).date().isoformat() == day]
        if len(entries) < 20:
            return
        res = await self.hass.async_add_executor_job(planner.replay_day, self.house, self.pump, self.settings(), entries)
        if res is not None:
            self.saving_days[day] = round(res[1] - res[0], 3)
        by_hand = sum(1 for e in self.events if e.get("kind") == "by_hand" and str(e.get("t", "")).startswith(day))
        self.day_stats[day] = lookback.day_stats(entries, self.settings().comfort, by_hand,
                                                 res[0] if res else None, res[1] if res else None)
        await self.async_save()

    def history_payload(self, days: int = 7) -> dict:
        """Everything the card's look back needs (websocket roost/history): the hours, the events that explain them,
        the days in numbers."""
        cut = time.time() - days * 86400
        kinds = {"set", "by_hand", "pause", "resume", "mode", "learned", "set_failed", "login_needed", "window"}
        return {"hours": [e for e in self.hour_log if e["ts"] >= cut],
                "events": [e for e in self.events if e.get("kind") in kinds and _iso_ts(e.get("t")) >= cut],
                "days": dict(sorted(self.day_stats.items())[-62:]),
                "comfort": self.settings().comfort, "currency": self.hass.config.currency or "EUR", "mode": self.mode}

    def saving_month(self) -> float:
        month = dt_util.now().date().isoformat()[:7]
        return round(sum(v for k, v in self.saving_days.items() if k.startswith(month)), 2)
