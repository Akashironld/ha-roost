"""Roost's Weheat login and the heat pump's history: the import in months, the nightly refresh. A mixin of RoostManager (manager.py): the methods use its state."""
from __future__ import annotations

from .mgr_common import *  # noqa: F401,F403 - the shared imports and constants
from .mgr_common import _LOGGER, _f, _i, _iso_ts  # noqa: F401
from . import curve
from .weheat_api import async_settings


class WeheatMixin:
    def _weheat_last_from_events(self) -> dict[str, float]:
        """The last Weheat call per kind, from the event log (stored by versions before weheat_last was kept)."""
        last: dict[str, float] = {}
        for e in self.events:
            if e.get("kind") == "weheat_call" and e.get("endpoint") in ("logs", "energy"):
                try:
                    last[e["endpoint"]] = datetime.fromisoformat(e["t"]).timestamp()
                except (KeyError, TypeError, ValueError):
                    pass
        return last

    def _weheat_login(self) -> tuple[str | None, str | None]:
        """(Weheat heat pump id, config entry whose login reads the API: Roost's own)."""
        pump, _ = heat_pump_id(self.hass, self.conf.get(CONF_HEAT_PUMP))
        return pump, self.entry.entry_id

    def _ask_login(self, why: str) -> None:
        """No Weheat login, or Weheat refused it: Home Assistant shows 'Reconfigure / re-authenticate' for Roost."""
        self.event("login_needed", why=why[:200])
        self._notify_user("login")
        self.entry.async_start_reauth(self.hass)

    def _merge_weheat(self, rows: dict[int, dict]) -> None:
        history.merge_hours(self._weheat_hours, rows)

    def _energy_before(self, ts: float) -> bool:
        """Most hours of the month before ts have their energy already (an import adding fields, not a first one)."""
        month = [v for t, v in self._weheat_hours.items() if ts - 31 * 86400 <= t < ts]
        return len(month) > 24 * 7 and sum(1 for v in month if "q" in v) > 0.8 * len(month)

    def import_progress(self) -> tuple[int, int, datetime | None]:
        """A running Weheat import: months in, months in all, expected end (local time)."""
        i = self.import_info
        if not self.importing:
            return i.get("months_done", i.get("months", 0)), i.get("months", 0), None
        end = check.import_done_at(i, dt_util.now().timestamp(), logs_only=bool(i.get("logs_only")))
        return i.get("months_done", 0), i.get("months", 0), dt_util.as_local(datetime.fromtimestamp(end, tz=timezone.utc))

    async def _async_refresh_weheat(self) -> None:
        """The hours since the last import, from Weheat (read-only), so learning and the self-check use the unit's own
        meters and states. Skipped quietly when the Weheat login is not available."""
        pump, weheat_entry = self._weheat_login()
        if not pump or not weheat_entry:
            return
        got = await async_settings(self.hass, weheat_entry, pump)          # how it is controlled, its heating curve
        if got is not None:
            self.weheat_settings = {**got, "at": dt_util.now().isoformat(timespec="seconds")}
        if not self.import_info.get("done") or not self._weheat_hours or self.importing:
            return
        end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        start = max(end - timedelta(days=30), datetime.fromtimestamp(max(self._weheat_hours) - 3 * 3600, tz=timezone.utc))
        try:
            logs, energy, calls = await async_fetch_history(self.hass, weheat_entry, pump, start, end,
                                                            note=lambda **k: self.event("weheat_call", **k),
                                                            last_calls=self.weheat_last)
            self.event("weheat_refresh", calls=calls, hours=len(logs))
        except WeheatLoginNeeded as err:
            self._ask_login(str(err))
            return
        except Exception as err:  # noqa: BLE001 - learn with what there is
            _LOGGER.debug("Roost: Weheat refresh skipped: %s", err)
            return
        self._merge_weheat(history.weheat_hours(logs, energy))
        await self._async_save_history()

    async def async_import(self, days: int = WEHEAT_IMPORT_DAYS, logs_only: bool = False) -> None:
        """Read the heat pump's history from Weheat (read-only), then learn. logs_only: the hours are there already
        (with their energy), only fields of the hourly logs are new: no energy logs, so a year takes half an hour
        instead of hours."""
        if self.importing:
            return
        pump, weheat_entry = self._weheat_login()
        if not pump or not weheat_entry:
            self.import_info = {"status": "no Weheat heat pump found"}
            return
        self.importing = True
        prev = self.import_info if not self.import_info.get("done") and self.import_info.get("oldest") else None
        if prev and prev.get("fields_reading") != WEHEAT_FIELDS:
            # cut off by an update that reads more fields: the months done lack them, so start again from the newest;
            # the hourly logs only when the hours have their energy already
            logs_only = logs_only or self._energy_before(datetime.fromisoformat(prev["oldest"]).timestamp())
            prev = None
        end = datetime.fromisoformat(prev["oldest"]) if prev else dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        start = datetime.fromisoformat(prev["from"]) if prev else end - timedelta(days=days)
        if prev and not logs_only:
            # carrying on after a restart: logs only when it was, or when the older hours have their energy already
            logs_only = bool(prev.get("logs_only")) or self._energy_before(end.timestamp())
        self.import_info = {"status": "importing", "from": start.isoformat(), "to": (prev or {}).get("to", end.isoformat()),
                            "logs_only": logs_only, "fields_reading": WEHEAT_FIELDS,
                            "oldest": end.isoformat(), "months_done": (prev or {}).get("months_done", 0),
                            "months": max(1, round((end - start).days / 31) + (prev or {}).get("months_done", 0)),
                            "hours": (prev or {}).get("hours", 0)}
        self._notify()
        learned_once = bool(prev)

        async def on_month(logs: list, energy: list, oldest: datetime) -> None:
            nonlocal learned_once
            rows = history.weheat_hours(logs, energy)
            self._merge_weheat(rows)
            await self._async_save_history()
            info = self.import_info
            info.update(oldest=oldest.isoformat(), months_done=info["months_done"] + 1, hours=info["hours"] + len(rows),
                        at=dt_util.now().isoformat(timespec="seconds"))
            await self.async_save()                 # a restart carries on from here
            self._notify()
            if not learned_once:                    # the newest month is in: learn from it now, the rest follows
                learned_once = True
                self.spawn(self.async_learn(), "learning after the first month")
        try:
            calls = await async_fetch_months(self.hass, weheat_entry, pump, start, end, on_month,
                                             lambda **k: self.event("weheat_call", **k), self.weheat_last,
                                             energy_logs=not logs_only)
            info = self.import_info
            first = min(self._weheat_hours) if self._weheat_hours else None
            self.event("import", hours=info["hours"], calls=calls, months=info["months_done"])
            self.import_info = {"status": "done", "done": True, "fields": WEHEAT_FIELDS, "hours": info["hours"], "calls": calls,
                                "months": info["months_done"],
                                "from": first and datetime.fromtimestamp(first, tz=timezone.utc).isoformat(),
                                "to": info["to"], "at": dt_util.now().isoformat(timespec="seconds")}
        except WeheatUnavailable as err:
            self.import_info.update(status=f"waiting for the Weheat login ({err})")        # keeps how far it got
            self.event("import_waiting", error=str(err)[:200])
            if isinstance(err, WeheatLoginNeeded):
                self._ask_login(str(err))
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Roost: Weheat import failed")
            self.import_info.update(status=f"failed: {err}")
            self.event("error", where="import", error=repr(err)[:200], trace=traceback.format_exc(limit=4)[-800:])
        finally:
            self.importing = False
        await self.async_save()
        if self.import_info.get("done"):
            await self.async_learn()
        self._notify()

    async def _async_curve(self, rows: list) -> None:
        """The heating curve advice from the house's heat loss, the emitters and the unit's flow temperatures (nightly,
        after learning). Kept as it was when there is too little data."""
        if not self.weheat_settings:                    # not asked yet (first night after an update): ask now
            pump, weheat_entry = self._weheat_login()
            got = await async_settings(self.hass, weheat_entry, pump) if pump and weheat_entry else None
            if got is not None:
                self.weheat_settings = {**got, "at": dt_util.now().isoformat(timespec="seconds")}
        flows = curve.flows_from_weheat(self._weheat_hours)
        adv = await self.hass.async_add_executor_job(curve.advise, rows, flows, self.conf.get(CONF_EMITTER, "floor"),
                                                     self.settings().comfort, self.pump.q_min or 0.0, curve.WEHEAT_X,
                                                     curve.opentherm_from_weheat(self._weheat_hours))
        if adv is not None:
            self.curve_advice = adv
