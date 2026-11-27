"""What the dashboard card shows beside the plan: how the unit is controlled (what it reports and what Roost sees it
do), the unit right now, the states in the card's header and how the saving is worked out; and the card's own state
(CardState: the unit's state and since when, when Weheat was last seen and asked, what it reports, its login).
Pure: the shell (cardstate.py) reads the entities and asks Weheat."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from .. import control_detect

METHOD_POLL_S = 300             # how often Roost asks Weheat which control method the unit runs on (its last log)
METHOD_MIN_S = 120              # never sooner (Weheat: logs at most once every 2 minutes); a change of the unit's state asks
                                # again as soon as that allows, so a switch in the Weheat app shows within minutes
WEHEAT_MISSING_S = 3 * 3600      # no live data from the unit this long: the card says so
COP_MIN_KW = 0.2                 # below this the unit is not really running: no COP shown (never 0)
HOT_WATER = ("dhw", "legionella_prevention")


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds") if ts else None


@dataclass(frozen=True)
class PumpReadings:
    """The unit now, as the card's entities say (the user's choice over what was found on the device)."""
    state: str
    since: float | None                 # in this state since
    last_ran: float | None              # the end of the last run
    requested: float | None             # the water temperature the thermostat asks for
    supply: float | None
    ret: float | None
    in_kw: float | None
    out_kw: float | None


@dataclass(frozen=True)
class StatusInputs:
    """What the card's header looks at."""
    t: float
    decision: Any                       # control.Decision | None
    heat_pump: bool                     # a Weheat heat pump chosen
    weheat_seen: float | None
    login_bad_since: float | None
    fallback: str | None
    fail_since: float | None
    control: dict                       # control_view
    pause_until: float | None
    away: bool
    away_until: float | None


def control_view(weheat_now: dict, steps: list, t: float) -> dict:
    """How the unit is controlled: what it says it runs on (its last log; only the Weheat app changes it, so nothing to
    set here) and what Roost sees it do (control_detect)."""
    method = control_detect.method_name(weheat_now.get("method"))
    d = control_detect.detect(steps, t)
    return {"control_method": method, "control_reported_at": weheat_now.get("at") if method else None,
            "control_detected": d.mode,
            "control_check": {"steps": d.steps, "gain": d.gain, "days": control_detect.WINDOW_S // 86400},
            "control_mismatch": control_detect.mismatch(method, d.mode),
            # Roost writing the water temperature itself (OpenTherm, a THRM ONE or alike): not yet
            "ot_available": False}


def pump_view(r: PumpReadings) -> dict:
    """The unit now."""
    state = r.state
    kind = ("heating" if state == "heating" else "hot_water" if state in HOT_WATER else
            "defrost" if state == "defrosting" else "idle" if state in ("standby", "off", "water_check") else "other")
    sup, ret, p_in, p_out = r.supply, r.ret, r.in_kw, r.out_kw
    return {"state": kind, "raw": state, "since": _iso(r.since),
            "last_ran": _iso(r.last_ran) if kind == "idle" else None,
            # the water temperature the thermostat asks for (OpenTherm ID 1), not the unit's own target
            "requested": r.requested,
            "supply": sup, "return": ret, "delta_t": round(sup - ret, 1) if sup is not None and ret is not None else None,
            "in_kw": None if p_in is None else round(p_in, 2), "out_kw": None if p_out is None else round(p_out, 2),
            "cop": round(p_out / p_in, 1) if p_in and p_out and p_in > COP_MIN_KW and p_out > 0 else None}


def status_view(i: StatusInputs) -> list[dict]:
    """The card's header: what is going on now, most important first. level: info | amber (Roost works around it) |
    red (it could not do its job)."""
    out = []
    d, t = i.decision, i.t
    if d is not None and d.why.code == "set_failed":
        out.append({"code": "set_failed", "level": "red", "args": {"retry_min": d.why.args.get("min")}})
    if i.heat_pump and (i.weheat_seen is None or t - i.weheat_seen > WEHEAT_MISSING_S):
        out.append({"code": "weheat_missing", "level": "amber", "args": {"since": _iso(i.weheat_seen)}})
    if i.login_bad_since:
        out.append({"code": "weheat_login", "level": "amber", "args": {"since": _iso(i.login_bad_since)}})
    if i.fallback in ("no_price", "schedule"):
        out.append({"code": f"fallback_{i.fallback}", "level": "amber", "args": {"since": _iso(i.fail_since)}})
    c = i.control
    if c["control_mismatch"]:
        out.append({"code": "control_mismatch", "level": "amber",
                    "args": {"setting": c["control_method"], "detected": c["control_detected"]}})
    if i.pause_until and t < i.pause_until:
        out.append({"code": "paused", "level": "info", "args": {"until": _iso(i.pause_until)}})
    if i.away:
        out.append({"code": "away", "level": "info", "args": {"until": _iso(i.away_until)}})
    return out


def saving_calc(p) -> dict | None:
    """How the saving of the next 24 h is worked out: steady − plan + what is left at the end (steady − plan).
    None while the plan's saving is not valid (no prices: a fallback): the card shows —, never 0."""
    if p is None or not p.breakdown or not p.breakdown.get("quality", {}).get("valid", True):
        return None
    b = p.breakdown
    return {"steady": b.get("b_cost"), "plan": b.get("cost"), "end_steady": b.get("b_end"), "end_plan": b.get("end"),
            "saving": b.get("saving"), "parts": b.get("parts")}


@dataclass(frozen=True)
class CardState:
    pump_st: str | None = None              # the unit's state as the card last saw it
    pump_since: float | None = None         # ... since
    weheat_seen: float | None = None        # the unit's state last known (live data from Weheat)
    weheat_now: dict = field(default_factory=dict)   # from the unit's last log: {"method", "dhw", "at"}
    method_at: float = 0.0                  # when Weheat was last asked for the control method
    login_bad_since: float | None = None    # Weheat refused Roost's own login since (cleared by the next answer)

    def stored(self) -> dict:
        return {"weheat_seen": self.weheat_seen, "weheat_now": self.weheat_now}

    @classmethod
    def restore(cls, data: dict) -> CardState:
        return cls(weheat_seen=data.get("weheat_seen"), weheat_now=data.get("weheat_now") or {})


def poll_due(c: CardState, t: float, state: str | None, last_logs: float, busy: bool, importing: bool, has_pump: bool) -> bool:
    """Whether to ask Weheat for the control method now: every METHOD_POLL_S, sooner (METHOD_MIN_S) when the unit's
    state changed; never while the log quota (one call per 2 minutes, shared with the import and the nightly
    refresh) is used, a call is out, or an import runs."""
    due = t - c.method_at >= METHOD_POLL_S or (state != c.pump_st and t - c.method_at >= METHOD_MIN_S)
    free = t - last_logs >= METHOD_MIN_S
    return due and free and not busy and not importing and has_pump


def seen(c: CardState, t: float, state: str | None, pump_known: bool) -> CardState:
    """A tick: live data from the unit (its state known), and its state for the card with since when."""
    if pump_known:
        c = replace(c, weheat_seen=t)
    if state != c.pump_st:
        c = replace(c, pump_st=state, pump_since=t)
    return c


def answered(c: CardState, got: dict | None, at: str) -> CardState:
    """Weheat's answer to the control method (None: no answer: kept as it was)."""
    if got is None:
        return c
    c = replace(c, login_bad_since=None)
    if got.get("currentControlMethod") is not None:
        c = replace(c, weheat_now={"method": got.get("currentControlMethod"), "dhw": got.get("dhwControlMethod"), "at": at})
    return c


def login_refused(c: CardState, t: float) -> CardState:
    return replace(c, login_bad_since=c.login_bad_since or t)
