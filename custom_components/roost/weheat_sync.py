"""Roost's Weheat login and the heat pump's history, Home Assistant's side: the import in months, the nightly refresh,
the unit's settings and fixed data, the heating curve advice. What is kept and how is in core/weheat.py.

WeheatSync (held by RoostManager as `wh`) reaches the rest of Roost only through WeheatHost: the Weheat bundle
(read and replaced, never held over an await), events, notices, saving, learning."""
from __future__ import annotations

import logging
import time
import traceback
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from homeassistant.util import dt as dt_util

from . import check, curve, history
from .const import CONF_HEAT_PUMP, WEHEAT_IMPORT_DAYS
from .core import weheat as cweheat
from .mgr_common import WEHEAT_FIELDS
from .weheat_api import (
    WeheatLoginNeeded,
    WeheatUnavailable,
    async_fetch_history,
    async_fetch_months,
    async_pump_info,
    async_settings,
    heat_pump_id,
)

_LOGGER = logging.getLogger(f"{__package__}.manager")   # the name it always had (log settings, bug reports)


class WeheatHost(Protocol):
    """What the Weheat side needs of the manager: no more."""
    hass: Any
    entry: Any
    weheat: cweheat.Weheat                   # read and replaced
    card: Any                                # card.login_refused(t): Weheat refused the login
    care: Any                                # care.notify_user
    curve_advice: Any                        # written: the heating curve advice

    @property
    def conf(self) -> dict: ...
    @property
    def pump(self) -> Any: ...
    def settings(self) -> Any: ...
    def event(self, kind: str, **data: Any) -> None: ...
    def spawn(self, coro, name: str, background: bool = True) -> Any: ...
    def _notify(self) -> None: ...
    async def async_save(self) -> None: ...
    async def _async_save_history(self) -> None: ...
    learner: Any                             # learner.async_learn


def _now_iso() -> str:
    return dt_util.now().isoformat(timespec="seconds")


class WeheatSync:
    def __init__(self, host: WeheatHost) -> None:
        self.host = host
        self.importing = False

    def login(self) -> tuple[str | None, str | None]:
        """(Weheat heat pump id, config entry whose login reads the API: Roost's own)."""
        h = self.host
        pump, _ = heat_pump_id(h.hass, h.conf.get(CONF_HEAT_PUMP))
        return pump, h.entry.entry_id

    def ask_login(self, why: str) -> None:
        """No Weheat login, or Weheat refused it: Home Assistant shows 'Reconfigure / re-authenticate' for Roost."""
        h = self.host
        h.event("login_needed", why=why[:200])
        h.card.login_refused(time.time())
        h.care.notify_user("login")
        h.entry.async_start_reauth(h.hass)

    def merge(self, rows: dict[int, dict]) -> None:
        self.host.weheat = cweheat.merge(self.host.weheat, rows)

    def import_progress(self) -> tuple[int, int, datetime | None]:
        """A running Weheat import: months in, months in all, expected end (local time)."""
        i = self.host.weheat.import_info
        if not self.importing:
            return i.get("months_done", i.get("months", 0)), i.get("months", 0), None
        end = check.import_done_at(i, dt_util.now().timestamp(), logs_only=bool(i.get("logs_only")))
        return i.get("months_done", 0), i.get("months", 0), dt_util.as_local(datetime.fromtimestamp(end, tz=timezone.utc))

    def _set(self, **changes: Any) -> None:
        self.host.weheat = replace(self.host.weheat, **changes)

    async def async_refresh(self) -> None:
        """The hours since the last import, from Weheat (read-only), so learning and the self-check use the unit's own
        meters and states. Skipped quietly when the Weheat login is not available."""
        h = self.host
        pump, weheat_entry = self.login()
        if not pump or not weheat_entry:
            return
        got = await async_settings(h.hass, weheat_entry, pump)          # how it is controlled, its heating curve
        if got is not None:
            self._set(settings={**got, "at": _now_iso()})
        await self.async_pump_info()
        w = h.weheat
        if not w.import_info.get("done") or not w.hours or self.importing:
            return
        end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        start = max(end - timedelta(days=30), datetime.fromtimestamp(max(w.hours) - 3 * 3600, tz=timezone.utc))
        try:
            logs, energy, calls = await async_fetch_history(h.hass, weheat_entry, pump, start, end,
                                                            note=lambda **k: h.event("weheat_call", **k),
                                                            last_calls=w.last)
            h.event("weheat_refresh", calls=calls, hours=len(logs))
        except WeheatLoginNeeded as err:
            self.ask_login(str(err))
            return
        except Exception as err:  # noqa: BLE001 - learn with what there is
            _LOGGER.debug("Roost: Weheat refresh skipped: %s", err)
            return
        self.merge(history.weheat_hours(logs, energy))
        await h._async_save_history()

    async def async_pump_info(self) -> None:
        """The unit's fixed data from Weheat (model, gas boiler, hot water tank); kept as it was when Weheat does not
        answer."""
        h = self.host
        pump, weheat_entry = self.login()
        if not pump or not weheat_entry:
            return
        got = await async_pump_info(h.hass, weheat_entry, pump)
        if got is not None:
            was = cweheat.hybrid(h.weheat)
            self._set(pump={**got, "at": _now_iso()})
            if cweheat.hybrid(h.weheat) != was:
                h.event("hybrid", hybrid=cweheat.hybrid(h.weheat), boiler_type=got.get("boiler_type"), hours=h.weheat.boiler_hours)

    async def async_import(self, days: int = WEHEAT_IMPORT_DAYS, logs_only: bool = False) -> None:
        """Read the heat pump's history from Weheat (read-only), then learn. logs_only: the hours are there already
        (with their energy), only fields of the hourly logs are new: no energy logs, so a year takes half an hour
        instead of hours."""
        h = self.host
        if self.importing:
            return
        pump, weheat_entry = self.login()
        if not pump or not weheat_entry:
            self._set(import_info={"status": "no Weheat heat pump found"})
            return
        self.importing = True
        w = h.weheat
        plan = cweheat.plan_import(w.import_info, w.hours, days, logs_only,
                                   dt_util.utcnow().replace(minute=0, second=0, microsecond=0), WEHEAT_FIELDS)
        self._set(import_info=plan.info)
        h._notify()
        learned_once = plan.resumed

        async def on_month(logs: list, energy: list, oldest: datetime) -> None:
            nonlocal learned_once
            rows = history.weheat_hours(logs, energy)
            self.merge(rows)
            await h._async_save_history()
            self._set(import_info=cweheat.month_done(h.weheat.import_info, oldest, len(rows), _now_iso()))
            await h.async_save()                 # a restart carries on from here
            h._notify()
            if not learned_once:                    # the newest month is in: learn from it now, the rest follows
                learned_once = True
                h.spawn(h.learner.async_learn(), "learning after the first month")
        try:
            calls = await async_fetch_months(h.hass, weheat_entry, pump, plan.start, plan.end, on_month,
                                             lambda **k: h.event("weheat_call", **k), w.last,
                                             energy_logs=not plan.logs_only)
            info, hours = h.weheat.import_info, h.weheat.hours
            first = min(hours) if hours else None
            h.event("import", hours=info["hours"], calls=calls, months=info["months_done"])
            self._set(import_info=cweheat.import_done(info, calls, WEHEAT_FIELDS, _now_iso(),
                                                      first and datetime.fromtimestamp(first, tz=timezone.utc).isoformat()))
        except WeheatUnavailable as err:
            # keeps how far it got
            self._set(import_info={**h.weheat.import_info, "status": f"waiting for the Weheat login ({err})"})
            h.event("import_waiting", error=str(err)[:200])
            if isinstance(err, WeheatLoginNeeded):
                self.ask_login(str(err))
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Roost: Weheat import failed")
            self._set(import_info={**h.weheat.import_info, "status": f"failed: {err}"})
            h.event("error", where="import", error=repr(err)[:200], trace=traceback.format_exc(limit=4)[-800:])
        finally:
            self.importing = False
        await h.async_save()
        if h.weheat.import_info.get("done"):
            await h.learner.async_learn()
        h._notify()

    async def async_curve(self, rows: list) -> None:
        """The heating curve advice from the house's heat loss, the emitters and the unit's flow temperatures (nightly,
        after learning). Kept as it was when there is too little data."""
        h = self.host
        if not h.weheat.settings:                    # not asked yet (first night after an update): ask now
            pump, weheat_entry = self.login()
            got = await async_settings(h.hass, weheat_entry, pump) if pump and weheat_entry else None
            if got is not None:
                self._set(settings={**got, "at": _now_iso()})
        hours = h.weheat.hours
        flows = curve.flows_from_weheat(hours)
        adv = await h.hass.async_add_executor_job(curve.advise, rows, flows, curve.emitter_profile(h.conf)[1],
                                                  h.settings().comfort, h.pump.q_min or 0.0, curve.WEHEAT_X,
                                                  curve.opentherm_from_weheat(hours))
        if adv is not None:
            h.curve_advice = adv
