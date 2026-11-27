"""Learning, Home Assistant's side: every night the house, the heat pump and the extra rooms from the hours kept
(learning.py reads them), the self-check and readiness, the heating curve advice; once, the building register.
The models themselves are learned by pure functions (model.learn, heatpump.learn, response.learn, rooms.learn,
check.self_check), in the executor.

Learner (held by RoostManager as `learner`) reaches the rest of Roost through the manager (self.h)."""
from __future__ import annotations

import time
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import building, check, curve, heatpump, model, response, rooms, sun
from .const import CONF_DAY_FROM, CONF_DAY_TO, CONF_USE_BAG
from .core import weather as cweather
from .mgr_common import _LOGGER, NO_LEVER_KW, ClientTimeout

if TYPE_CHECKING:
    from .manager import (
        RoostManager,  # for the type checker only: no import cycle at run time
    )


class Learner:
    def __init__(self, host: RoostManager) -> None:
        self.h = host
        self._learning = False

    async def async_building(self) -> None:
        """Opt-in: the building register (BAG via PDOK) around the home location, once (again when the home moves).
        Only the construction year, the floor area and the directions of the outside walls are kept."""
        if not self.h.conf.get(CONF_USE_BAG):
            return
        lat, lon = round(self.h.hass.config.latitude, 5), round(self.h.hass.config.longitude, 5)
        if self.h.building and abs(self.h.building.get("lat", 0) - lat) < 1e-4 and abs(self.h.building.get("lon", 0) - lon) < 1e-4:
            return
        bb = building.bbox(lat, lon)
        session = async_get_clientsession(self.h.hass)
        try:
            got = {}
            for kind in ("pand", "verblijfsobject"):
                async with session.get(building.WFS.format(kind=kind, **bb), timeout=ClientTimeout(total=30)) as r:
                    r.raise_for_status()
                    got[kind] = await r.json(content_type=None)
            b = await self.h.hass.async_add_executor_job(building.parse, got["pand"], got["verblijfsobject"], lat, lon)
        except Exception as err:  # noqa: BLE001 - optional: without it Roost starts from a generic house
            _LOGGER.info("Roost: building register not available: %s", err)
            return
        self.h.building = {**b, "lat": lat, "lon": lon} if b else {"lat": lat, "lon": lon, "none": True}
        if b and self.h.house.source != "learned" and building.prior(b):
            self.h.house = model.HouseModel(**self.house_start(), source="building register")
        await self.h.async_save()


    async def async_learn_rooms(self, rows: list[model.HourRow]) -> None:
        """Per extra room: its model from the hourly means of its sensor, and a repair when it stays too cold."""
        if not self.h.rooms:
            return
        from .learning import async_hourly_means
        means = await async_hourly_means(self.h, [r.sensor for r in self.h.rooms], days=60)
        idx = {r.ts: r for r in rows}
        c = self.h.conf
        for r in self.h.rooms:
            m = means.get(r.sensor) or {}
            samples = [(m[t], m[t + 3600], idx[t].Q, idx[t].T_out, idx[t].T) for t in sorted(m) if t + 3600 in m and t in idx]
            learned = await self.h.hass.async_add_executor_job(rooms.learn, samples)
            if learned:
                self.h.room_models[r.id] = learned
            lo, a, b = r.settings(int(c[CONF_DAY_FROM]), int(c[CONF_DAY_TO]))
            since = time.time() - 3 * 86400
            log = []
            for t in sorted(x for x in m if x >= since):
                loc = dt_util.as_local(datetime.fromtimestamp(t, tz=timezone.utc))
                log.append((loc.date().isoformat(), rooms.active(loc.hour, a, b), m[t], lo))
            self.h.notices.issue(f"room_cold_{r.id}", rooms.too_cold(log), translation_key="room_cold",
                        placeholders={"room": r.name, "minimum": f"{lo:g}", "hours": f"{a}:00–{b}:00"})


    def house_start(self) -> dict:
        """Starting values for the house model: heat emitter and (opt-in) the building register."""
        return model.starting_values(curve.emitter_profile(self.h.conf)[0], building.prior(self.h.building))


    async def async_nightly(self, _now: datetime) -> None:
        await self.h.wh.async_refresh()
        await self.async_learn()


    async def async_learn(self) -> None:
        if self._learning:
            return
        self._learning = True
        try:
            from .learning import async_rows
            if not self.h.weather.forecast:
                await self.h._async_weather()           # just after a start the forecast service may not have answered yet
            rows, extra = await async_rows(self.h)
            if model.stale(rows, time.time()):
                # without the newest hours the test days would be weeks old (seen 18-10-2026: the last row in July after
                # a restart without weather, and a summer model taken in October): wait for the next run
                newest = max((r.ts for r in rows), default=None)
                self.h.event("learn_skipped", reason="no recent hours",
                           newest=datetime.fromtimestamp(newest, tz=timezone.utc).isoformat() if newest else None)
                return
            # airing: those hours look like a house that suddenly loses much more heat; leave them out
            rows = [r for r in rows if r.ts not in self.h.window.hours]
            # hours without the setpoint in the Weheat logs (an on/off thermostat): Roost's own record of the thermostat
            sp_hist = self.h.log.sp_hist
            rows = [replace(r, sp=sp_hist[r.ts][0] if r.sp is None else r.sp,
                            T_th=sp_hist[r.ts][1] if r.T_th is None else r.T_th) if r.ts in sp_hist else r for r in rows]
            wx_all = cweather.learning_rows(self.h.weather)
            lat, lon = self.h.hass.config.latitude, self.h.hass.config.longitude

            def eff(ts: int, facade: float, vertical: float) -> float:
                wx = wx_all.get(ts)
                return sun.effective(ts, wx, lat, lon, facade, vertical) if wx else 0.0
            hours = {r.ts: self.h.local_hour(r.ts) for r in rows}
            house = await self.h.hass.async_add_executor_job(model.learn, rows, self.h.house, eff, hours.__getitem__,
                                                           self.house_start(), building.facades(self.h.building, model.FACADES))
            # from here on the rows carry the sun on the learned facade and their local hour
            hm = house.model
            rows = [replace(r, rad=eff(r.ts, hm.sun_facade, hm.sun_vertical) if hm.sun_vertical > 0 else r.rad, hour=hours[r.ts]) for r in rows]
            pump, note = await self.h.hass.async_add_executor_job(heatpump.learn, rows, self.h.pump)
            pump, note_r = await self.h.hass.async_add_executor_job(response.learn, rows, house.model, pump)
            note = "; ".join(x for x in (note, note_r) if x)
            samples = self.h.hl.dhw_samples(rows)
            prof, fixed = response.dhw_forecast(samples)
            if prof:
                pump.dhw, pump.dhw_weeks, pump.dhw_fixed = prof, round(len(samples) / 168, 1), fixed
            # check the new pair before it is used: a failure from here on keeps the models, check and readiness it had
            chk = await self.h.hass.async_add_executor_job(check.self_check, rows, house.model, pump)
            if chk.get("heating_hours", 0) < check.READY_HEATING_HOURS:      # mild weather: the last heating weeks decide
                winter = await self.h.hass.async_add_executor_job(check.winter_check, rows, house.model, pump)
                if winter:
                    chk["winter"] = winter
            chk["at"] = dt_util.now().isoformat(timespec="seconds")
            self.h.house, self.h.pump, self.h.check = house.model, pump, chk
            weak = self.h.pump.resp_source == "learned" and self.h.pump.k is not None and self.h.pump.k < NO_LEVER_KW
            self.h.notices.issue("no_lever", weak, placeholders={"k": f"{self.h.pump.k or 0:.2f}"})
            self.h.notices.update_ready()
            self.h.notices.issue_comfort()
            await self.async_learn_rooms(rows)
            await self.h.wh.async_curve(rows)
            if extra.get("pv_k"):
                self.h.pv_k = extra["pv_k"]
            if extra.get("load_profile"):
                self.h.load_profile = extra["load_profile"]
            self.h.learn_info = {"at": dt_util.now().isoformat(timespec="seconds"), "house": house.reason, "scores": house.scores,
                               "heat_pump": note, "rows": len(rows), "heating_hours": sum(1 for r in rows if r.Q > 0.3),
                               "rows_with_setpoint": sum(1 for r in rows if r.sp is not None),
                               "rows_with_room_sensor": sum(1 for r in rows if r.room_sensor),
                               "rows_with_thermostat_reading": sum(1 for r in rows if r.T_th is not None),
                               "last_row": datetime.fromtimestamp(max(r.ts for r in rows), tz=timezone.utc).isoformat() if rows else None,
                               "weheat_hours": sum(1 for r in rows if r.ts in self.h.weheat.hours),
                               # heating without the thermostat asking (own heating curve?): left out of response and check
                               "unfollowed_hours": len(model.unfollowed(rows, self.h.house, self.h.pump))}
            self.h.notices.issue("learning_failed", False)
            self.h.event("learned", house=house.reason, heat_pump=note[:300], plan_error_6h=self.h.check.get("rmse_6h"),
                       ready=self.h.ready, rows=len(rows))
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Roost learning failed")
            self.h.notices.issue("learning_failed", True)
            self.h.care.notify_user("learning_failed")
            self.h.event("error", where="learning", error=repr(err)[:200], trace=traceback.format_exc(limit=4)[-800:])
        finally:
            self._learning = False
        await self.h.async_save()
        await self.h._async_tick(None, force_plan=True)

