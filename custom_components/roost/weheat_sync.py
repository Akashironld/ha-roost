"""Roost's Weheat login and the heat pump's history: the import in months, the nightly refresh. A mixin of RoostManager (manager.py): the methods use its state."""
from __future__ import annotations

from .mgr_common import *  # noqa: F401,F403 - the shared imports and constants
from .mgr_common import _LOGGER, _f, _i, _iso_ts  # noqa: F401


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
        self.entry.async_start_reauth(self.hass)

    def import_progress(self) -> tuple[int, int, datetime | None]:
        """A running Weheat import: months in, months in all, expected end (local time)."""
        i = self.import_info
        if not self.importing:
            return i.get("months_done", i.get("months", 0)), i.get("months", 0), None
        end = check.import_done_at(i, dt_util.now().timestamp())
        return i.get("months_done", 0), i.get("months", 0), dt_util.as_local(datetime.fromtimestamp(end, tz=timezone.utc))

    async def _async_refresh_weheat(self) -> None:
        """The hours since the last import, from Weheat (read-only), so learning and the self-check use the unit's own
        meters and states. Skipped quietly when the Weheat login is not available."""
        if not self.import_info.get("done") or not self._weheat_hours or self.importing:
            return
        pump, weheat_entry = self._weheat_login()
        if not pump or not weheat_entry:
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
        self._weheat_hours.update(history.weheat_hours(logs, energy))
        await self._async_save_history()

    async def async_import(self, days: int = WEHEAT_IMPORT_DAYS) -> None:
        """Read the heat pump's history from Weheat (read-only), then learn."""
        if self.importing:
            return
        pump, weheat_entry = self._weheat_login()
        if not pump or not weheat_entry:
            self.import_info = {"status": "no Weheat heat pump found"}
            return
        self.importing = True
        prev = self.import_info if not self.import_info.get("done") and self.import_info.get("oldest") else None
        end = datetime.fromisoformat(prev["oldest"]) if prev else dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        start = datetime.fromisoformat(prev["from"]) if prev else end - timedelta(days=days)
        self.import_info = {"status": "importing", "from": start.isoformat(), "to": (prev or {}).get("to", end.isoformat()),
                            "oldest": end.isoformat(), "months_done": (prev or {}).get("months_done", 0),
                            "months": max(1, round((end - start).days / 31) + (prev or {}).get("months_done", 0)),
                            "hours": (prev or {}).get("hours", 0)}
        self._notify()
        learned_once = bool(prev)

        async def on_month(logs: list, energy: list, oldest: datetime) -> None:
            nonlocal learned_once
            rows = history.weheat_hours(logs, energy)
            self._weheat_hours.update(rows)
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
                                             lambda **k: self.event("weheat_call", **k), self.weheat_last)
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
