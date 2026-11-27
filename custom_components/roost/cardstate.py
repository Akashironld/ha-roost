"""What the dashboard card shows beside the plan, Home Assistant's side: read the unit's entities (the user's choice
over what was found), ask Weheat which control method the unit runs on, and give the card one summary: view(t).
Read only: nothing here steers the thermostat. What is worked out and kept is in core/card.py.

Card (held by RoostManager as `card`) keeps the CardState bundle and the control steps (control_detect.StepTracker),
and reaches the rest of Roost through the manager (self.h)."""
from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from . import control_detect
from .const import CONF_HEAT_PUMP, CONF_PUMP_ENTITIES, PUMP_ROLES
from .core import card as ccard
from .core.card import (  # noqa: F401 - the names callers and tests use from here
    COP_MIN_KW,
    HOT_WATER,
    METHOD_MIN_S,
    METHOD_POLL_S,
    WEHEAT_MISSING_S,
    PumpReadings,
    StatusInputs,
    control_view,
    pump_view,
    saving_calc,
    status_view,
)

if TYPE_CHECKING:
    from .manager import (
        RoostManager,  # for the type checker only: no import cycle at run time
    )

class Card:
    def __init__(self, host: RoostManager) -> None:
        self.h = host
        self.cs = ccard.CardState()                 # the card's own state (core/card.py)
        self.steps = control_detect.StepTracker()   # what Roost sees the unit do with the water temperature asked
        self.card_ent: dict[str, str] = {}          # the user's choice for the card; Roost's own self.h.ent stays as found
        self._method_busy = False                   # a call for the control method is out

    def restore(self, data: dict) -> None:
        self.steps = control_detect.StepTracker.from_dict(data.get("control_steps"))
        self.cs = ccard.CardState.restore(data)

    def stored(self) -> dict:
        return {"control_steps": self.steps.as_dict(), **self.cs.stored()}

    def apply_pump_entities(self) -> None:
        """The user's choice over what was found on the device (the card's settings), for the card only: what Roost
        reads to plan, count and watch (self.h.ent) stays as found, so a wrong pick cannot change how it steers."""
        self.card_ent = {role: eid for role, eid in (self.h.conf.get(CONF_PUMP_ENTITIES) or {}).items()
                         if role in PUMP_ROLES and isinstance(eid, str) and eid}

    def cent(self, role: str) -> str | None:
        return self.card_ent.get(role) or self.h.ent.get(role)

    def state(self) -> str | None:
        st = self.h.read.state(self.cent("state"))
        return st.state if st else None

    def login_refused(self, t: float) -> None:
        self.cs = ccard.login_refused(self.cs, t)

    async def async_poll_method(self) -> None:
        """Which control method the unit runs on now, from its last log (read-only); kept as it was on no answer."""
        from .weheat_api import WeheatLoginNeeded, async_latest
        pump, login = self.h.wh.login()
        if not pump or not login:
            return
        self._method_busy = True
        if self.h.weheat.last is not None:
            self.h.weheat.last["logs"] = time.time()          # the refresh's pacer keeps 2 minutes from this call too
        try:
            got = await async_latest(self.h.hass, login, pump)
        except WeheatLoginNeeded:
            self.login_refused(time.time())
            return              # the nightly refresh asks for the login; no second notice from here
        finally:
            self._method_busy = False
        self.cs = ccard.answered(self.cs, got, dt_util.now().isoformat(timespec="seconds"))

    # ------------------------------------------------------------ every tick
    def track(self, t: float) -> None:
        state = self.state()
        if ccard.poll_due(self.cs, t, state, (self.h.weheat.last or {}).get("logs", 0.0), self._method_busy,
                          self.h.wh.importing, bool(self.h.conf.get(CONF_HEAT_PUMP))):
            self.cs = replace(self.cs, method_at=t)
            self.h.spawn(self.async_poll_method(), "weheat control method")
        self.cs = ccard.seen(self.cs, t, state, self.h.pump_state() is not None)
        running = state == "heating" and (self.h.read.kw(self.cent("power_in")) or 0.0) > COP_MIN_KW
        self.steps.update(t, self.h.read.temp(self.cent("water_setpoint")), self.h.read.temp(self.cent("water_out")), running)

    # ------------------------------------------------------------ for the card
    def view(self, t: float) -> dict:
        """Everything the card shows beside the plan, in one: how the unit is controlled, the unit now, the header,
        how the saving is worked out."""
        c = self.control_view(t)
        return {**c, "pump": self.pump_view(t), "status": self._status_view(t, c), "saving_calc": self.saving_calc()}

    def control_view(self, t: float) -> dict:
        return control_view(self.cs.weheat_now, self.steps.steps, t)

    def pump_view(self, t: float) -> dict | None:
        """The unit now: None without its state (no Weheat entities): the card leaves the pump detail out."""
        state = self.state()
        if state is None:
            return None
        return pump_view(PumpReadings(
            state=state, since=self.cs.pump_since, last_ran=next((r[1] for r in reversed(self.h.meters.runs) if r[1] is not None), None),
            requested=self.h.read.temp(self.cent("water_setpoint")),
            supply=self.h.read.temp(self.cent("water_out")), ret=self.h.read.temp(self.cent("water_in")),
            in_kw=self.h.read.kw(self.cent("power_in")), out_kw=self.h.read.kw(self.cent("power_out"))))

    def status_view(self, t: float) -> list[dict]:
        return self._status_view(t, self.control_view(t))

    def _status_view(self, t: float, control: dict) -> list[dict]:
        return status_view(StatusInputs(
            t=t, decision=self.h.decision, heat_pump=bool(self.h.conf.get(CONF_HEAT_PUMP)), weheat_seen=self.cs.weheat_seen,
            login_bad_since=self.cs.login_bad_since, fallback=self.h.held.fallback, fail_since=self.h.held.fail_since, control=control,
            pause_until=self.h.mem.pause_until, away=self.h.is_away(), away_until=self.h.mem.away_until))

    def saving_calc(self) -> dict | None:
        return saving_calc(self.h.held.plan)
