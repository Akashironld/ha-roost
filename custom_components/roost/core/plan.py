"""What the planner gets and what the plan in force says now. Pure: the shell (manager.py) reads the room, the unit,
the weather and the prices; these functions put them into the planner's hours and read the plan back per hour."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, cast

from .. import check, defrost, planner, response, rooms, stick
from .. import weather as om
from . import weather as cweather


# ------------------------------------------------------------ the plan in force
@dataclass(frozen=True)
class Held:
    """The plan in force and what it was made with."""
    plan: planner.Plan | None = None
    hours: list[planner.HourIn] = field(default_factory=list)     # the planner's input per hour
    at: float | None = None                                        # when it was made
    tariff: list[float] = field(default_factory=list)              # published import price per plan hour
    guess: list[bool] = field(default_factory=list)    # legacy diagnostic shape; new plans contain only known tariffs
    on_guess: bool = False                              # legacy snapshot field; no guessed prices in new plans
    w_now: float | None = None                          # the unit's output the plan started from (kW)
    commit: stick.Commitment | None = None              # the plan held: its setpoints and what it expected (stick.py)
    why: str | None = None                              # why the plan held was made afresh (stick.why_plan)
    fallback: str | None = None         # "no_price": planned on one flat price; "schedule": the comfort schedule
    fail_since: float | None = None     # planning has failed since (no price, room or weather)
    room_status: list[dict] = field(default_factory=list)          # the extra rooms for the card

    def stored(self) -> dict:
        return {"commit": self.commit.as_dict() if self.commit else None}

    @classmethod
    def restore(cls, data: dict) -> Held:
        return cls(commit=stick.Commitment.from_dict(data.get("commit")))


@dataclass(frozen=True)
class Failed:
    """What a failed round means: the reason to show, a fallback to the comfort schedule started now (an event),
    and whether the notice is open."""
    reason: str
    to_schedule: bool
    notice: bool


def failed(h: Held, code: str, t: float, started_at: float, grace_s: float, fallback_s: float,
           notice_s: float) -> tuple[Held, Failed | None]:
    """No plan could be made. The plan held stays for its current hour for fallback_s; after that, the comfort
    schedule (fallback "schedule") rather than whatever the thermostat was last given (a high setpoint to store heat,
    or a low one in an expensive hour). None: just started without a price (it often comes a minute after Roost)."""
    since = h.fail_since or t
    h = replace(h, fail_since=since)
    if code == "no_price" and h.plan is None and t - started_at < grace_s:
        return h, None
    reason, to_schedule = code, False
    if t - since >= fallback_s:
        to_schedule = h.fallback != "schedule"
        h = replace(h, plan=None, hours=[], tariff=[], guess=[], commit=None, fallback="schedule")
        reason = "fallback_schedule"
    return h, Failed(reason, to_schedule, bool(h.fallback and t - since >= notice_s))


def adopted(h: Held, p: planner.Plan, hours: list[planner.HourIn], at: float, w_now: float | None, tariff: list[float],
            guess: list[bool], room_status: list[dict], commit: stick.Commitment | None, why: str | None,
            fallback: str | None) -> Held:
    """A plan made: in force from now. commit/why: a plan made afresh (None: the plan held was worked out again)."""
    if commit is not None:
        h = replace(h, commit=commit, why=why)
    return replace(h, plan=p, hours=hours, at=at, w_now=w_now, tariff=tariff, guess=guess, on_guess=False,
                   room_status=room_status, fallback=fallback, fail_since=h.fail_since if fallback else None)


# ------------------------------------------------------------ the plan in force, per hour
def index(plan_at: float | None, t: float) -> int | None:
    """Which hour of the plan made at plan_at holds at t (None: no plan)."""
    return None if plan_at is None else int(t // 3600) - int(plan_at // 3600)


def hour_in(plan_at: float | None, hours: list[planner.HourIn], t: float) -> planner.HourIn | None:
    """The planner's input for the UTC hour of t, also before a new plan is ready at the hour boundary."""
    i = index(plan_at, t)
    return hours[i] if i is not None and 0 <= i < len(hours) else None


def setpoint(plan: planner.Plan | None, plan_at: float | None, t: float) -> float | None:
    """The plan's setpoint for the hour of t (None: no plan, or beyond it)."""
    i = index(plan_at, t)
    if plan is not None and i is not None and 0 <= i < len(plan.hours):
        return plan.hours[i].sp
    return None


def level(plan: planner.Plan | None, plan_at: float | None, t: float) -> float | None:
    """OpenTherm: the plan's heat output for the hour of t (its setpoint where it has no level)."""
    i = index(plan_at, t)
    if plan is not None and i is not None and 0 <= i < len(plan.hours):
        h = plan.hours[i]
        return h.level if h.level is not None else h.sp
    return None


def fallback_sp(away: bool, day: bool, away_min: float, comfort: float, night_min: float) -> float:
    """The comfort schedule: comfort in the comfort hours, the night minimum outside them, the away minimum away."""
    if away:
        return away_min
    return comfort if day else night_min


# ------------------------------------------------------------ the planner's input
def hours_ahead(base: int, t: float, prices: list, tariff: list[float], weather: cweather.Weather, *,
                local: Callable[[int], datetime], dhw_share: Callable[[int, int], float], dhw_top: float | None,
                dhw_now: bool, unit_air: float | None, bias: float, outdoor: Callable[[], float | None], sun: Callable[[int, tuple], float],
                weekly: bool, is_day: Callable[[datetime], bool], corr_kw: float, corr_slow: float,
                away: Callable[[int], bool]) -> list[planner.HourIn]:
    """The planner's hours from now (base: the start of this UTC hour, t: now): weather (the forecast, else the
    unit's outdoor reading for this hour, read only then), sun on the house, prices, comfort per hour (or per quarter with weekly
    periods), hot water, the defrost anomaly and the correction. [] when there is no weather at all."""
    shares = []
    for i in range(len(prices)):
        loc = local(base + i * 3600)
        shares.append(dhw_share(loc.weekday(), loc.hour))
    # an empty tank top: a unit that picks its own times reheats within the next hours (response.dhw_soon)
    shares = response.dhw_soon(shares, dhw_top)
    # the air at the unit against the forecast now, fading over the next hours: for defrosting (defrost.py)
    # the forecast for this moment (between this hour's and the next), only from a forecast fetched lately
    w0, w1 = weather.get(base), weather.get(base + 3600)
    f_now = None
    # in the sun the unit's sensor reads the sun, not the air (23-11-2026: 10.5 °C at a forecast of 0 °C): only
    # without sun on it
    if cweather.fresh(weather, t) and w0 is not None and w0[0] is not None and (w0[1] or 0.0) < defrost.ANOMALY_SUN:
        f_now = w0[0] if w1 is None or w1[0] is None else w0[0] + (w1[0] - w0[0]) * (t - base) / 3600
    adj = defrost.anomaly_ahead(unit_air, f_now, bias, len(prices))
    out = []
    last = None
    for i, p in enumerate(prices):
        wx = weather.get(base + i * 3600) or last
        if wx is None:
            t_out = outdoor()
            if t_out is None:
                return []
            wx = (t_out - bias, 0.0, 3.5)
        last = wx
        loc = local(base + i * 3600)
        dhw = shares[i]
        if i == 0 and dhw_now:
            dhw = max(dhw, 0.5)                     # making hot water right now
        rad = sun(base + i * 3600, wx)
        mask: tuple[bool, bool, bool, bool] | None = None
        if weekly:
            mask = cast(tuple[bool, bool, bool, bool],       # the four quarter-hours
                        tuple(is_day(local(base + i * 3600 + q * 900)) for q in range(4)))
        out.append(planner.HourIn(t_out=wx[0], wind=wx[2] if wx[2] is not None else 3.5, rad=rad,
                                  p_grid=p.p_grid, p_own=p.p_own, own_kw=p.own_kw, day=any(mask) if mask else is_day(loc),
                                  comfort_mask=mask, hour=loc.hour, dhw=dhw, rh=om.humidity(wx), t_adj=adj[i],
                                  extra_kw=check.fade(corr_kw, i) + corr_slow, away=away(base + i * 3600),
                                  p_imp=tariff[i] if i < len(tariff) else None))
    return out


def rooms_ahead(extra: list[rooms.Room], temps: dict[str, float | None], models: dict[str, Any], day_from: int, day_to: int,
                hours: list[planner.HourIn]) -> tuple[list[dict], list[dict]]:
    """The extra rooms for the planner (model, temperature now, minimum, hours it holds) and for the card. temps:
    each room's temperature now (°C; None when not read)."""
    plan_in: list[dict] = []
    meta: list[dict] = []
    for r in extra:
        T = temps.get(r.id)
        lo, a, b = r.settings(day_from, day_to)
        m = models.get(r.id) or rooms.RoomModel()
        if T is None:
            # not read now: no minimum to plan for, but it stays in the status (and the saving is not whole-house)
            meta.append({"id": r.id, "name": r.name, "kind": r.kind, "temperature": None, "minimum": lo, "from": a, "to": b,
                         "active_now": False, "model": m.source, "model_error": m.error, "available": False, "expected": []})
            continue
        inherits = r.hour_from is None and rooms.KINDS.get(r.kind, rooms.KINDS["other"])["from"] is None
        # a room that keeps the house's comfort hours follows the weekly comfort periods too
        act = [h.day if inherits else rooms.active(h.hour, a, b) for h in hours]
        plan_in.append({"model": m, "T": T, "min": lo, "active": act})
        meta.append({"id": r.id, "name": r.name, "kind": r.kind, "temperature": round(T, 1), "minimum": lo, "from": a, "to": b,
                     "active_now": act[0] if act else False, "model": m.source, "model_error": m.error})
    return plan_in, meta
