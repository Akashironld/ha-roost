"""The hourly log and the day numbers: what was planned, predicted and what happened (the look back, the saving).

Two bundles: Logs (the hour log, the plan log, the predictions, the thermostat per hour, the frozen day contexts and
the day numbers) and HourAcc (the hour in progress: seconds on hot water, heat, electricity and cost, seconds seen,
the setpoint, where the electricity came from). Pure: the shell (hourlog.py) reads the sensors and the plan into
PlanView / HourView and the values below, and replays a day in the executor."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, tzinfo
from typing import Any, Callable

from .. import heatpump, lookback, model, planner, replan, savings

HOUR_LOG_KEPT = 7 * 24 + 2          # a week of hours: the replay of yesterday and the look back
PLAN_LOG_KEPT = 48                  # the plan's inputs per hour (2 days): to replay a decision exactly
SAVING_DETAIL_DAYS = 7              # the saving per hour of the last days (roost.explain_saving, the report)
SP_HIST_DAYS = 120                  # own record of the thermostat's setpoint per hour


# ------------------------------------------------------------ the bundles
@dataclass(frozen=True)
class Logs:
    hour_log: list[dict] = field(default_factory=list)       # last ~week: state and inputs per hour (the saving)
    plan_log: list[dict] = field(default_factory=list)       # per hour: everything the plan in force saw
    pred: dict[int, dict] = field(default_factory=dict)      # hour start -> room predicted for it 6 h and 1 h ahead
    sp_hist: dict[int, list] = field(default_factory=dict)   # hour -> [mean setpoint, thermostat's reading]
    day_contexts: dict[str, dict] = field(default_factory=dict)   # immutable model/settings to validate each day
    saving_days: dict[str, float] = field(default_factory=dict)   # date -> accepted saving (currency)
    saving_detail: dict[str, dict] = field(default_factory=dict)  # date -> the saving per hour (planner.breakdown)
    day_stats: dict[str, dict] = field(default_factory=dict)      # date -> the day in numbers (look back, report)
    plan_changes: list[dict] = field(default_factory=list)   # the plan changed: before -> after, why
    plan_snap: dict | None = None                            # the plan in force and what it saw (replan.snapshot)
    replayed_with: int | None = None                         # planner.REPLAY_VERSION the days kept were replayed with

    def stored(self, now: float) -> dict:
        """For the main store, under the keys it always had."""
        return {"hour_log": self.hour_log[-HOUR_LOG_KEPT:], "saving_days": dict(sorted(self.saving_days.items())[-62:]),
                "day_stats": dict(sorted(self.day_stats.items())[-62:]),
                "pred": {str(k): v for k, v in self.pred.items() if k > now - 7200},
                "plan_log": self.plan_log[-PLAN_LOG_KEPT:], "replayed_with": self.replayed_with,
                "saving_detail": dict(sorted(self.saving_detail.items())[-SAVING_DETAIL_DAYS:]),
                "day_contexts": dict(sorted(self.day_contexts.items())[-SAVING_DETAIL_DAYS - 1:]),
                "plan_changes": replan.prune(self.plan_changes, now), "plan_snap": self.plan_snap,
                "sp_hist": {str(k): v for k, v in self.sp_hist.items() if k > now - SP_HIST_DAYS * 86400}}

    @classmethod
    def restore(cls, data: dict) -> Logs:
        return cls(hour_log=data.get("hour_log", []), saving_days=data.get("saving_days", {}),
                   day_stats=data.get("day_stats") or {}, pred={int(k): v for k, v in (data.get("pred") or {}).items()},
                   plan_log=data.get("plan_log") or [], saving_detail=data.get("saving_detail") or {},
                   day_contexts=data.get("day_contexts") or {}, replayed_with=data.get("replayed_with"),
                   plan_changes=data.get("plan_changes") or [], plan_snap=data.get("plan_snap"),
                   sp_hist={int(k): v for k, v in (data.get("sp_hist") or {}).items()})


@dataclass(frozen=True)
class HourAcc:
    """The hour in progress."""
    hour: int | None = None
    dhw: float = 0.0            # seconds on hot water
    heat: float = 0.0           # heat delivered to the house (kWh)
    elec: float = 0.0           # heating electricity (kWh) and its cost
    cost: float = 0.0
    obs: float = 0.0            # seconds of this hour Roost saw (a restart: fewer)
    sp: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)     # setpoint × s, s, reading × s, s
    src: tuple[float, float, float] = (0.0, 0.0, 0.0)               # kWh of the heat pump from solar, battery, grid

    def stored(self, last_elec: float | None, last_indoor: float | None, at: float) -> dict:
        """The hour in progress, saved with the rest: a restart within the hour goes on counting from here (R18)."""
        return {"hour": self.hour, "dhw": self.dhw, "heat": self.heat, "elec": self.elec, "cost": self.cost, "obs": self.obs,
                "sp": list(self.sp), "src": list(self.src), "last_elec": last_elec, "last_indoor": last_indoor, "at": at}


# ------------------------------------------------------------ the hour in progress
def new_hour(acc: HourAcc, hour: int) -> HourAcc:
    return HourAcc(hour=hour)


def track(acc: HourAcc, dt: float, sp: float | None, reading: float | None, dhw: bool, heating_kw: float | None,
          src_kw: tuple[float, float, float] | None) -> HourAcc:
    """dt seconds more of the hour: the setpoint and the thermostat's reading, hot water or the heat delivered
    (heating_kw: the unit's output while it heats the house, None when it does not), and where its electricity came
    from (src_kw: solar, battery, grid kW; None when not known)."""
    a = list(acc.sp)
    if sp is not None:
        a[0] += sp * dt
        a[1] += dt
    if reading is not None:
        a[2] += reading * dt
        a[3] += dt
    src = acc.src
    if src_kw is not None:
        s = list(acc.src)
        for i, kw in enumerate(src_kw):
            s[i] += kw * dt / 3600
        src = (s[0], s[1], s[2])
    out = replace(acc, obs=acc.obs + dt, sp=(a[0], a[1], a[2], a[3]), src=src)
    if dhw:
        return replace(out, dhw=acc.dhw + dt)
    if heating_kw is not None:
        return replace(out, heat=acc.heat + max(0.0, heating_kw) * dt / 3600)
    return out


def add_elec(acc: HourAcc, elec: float, cost: float | None) -> HourAcc:
    """The unit's heating electricity counted this tick (core/meters.count_cost), and its cost when priced."""
    return replace(acc, elec=acc.elec + elec, cost=acc.cost + cost if cost is not None else acc.cost)


def close_hour(logs: Logs, acc: HourAcc, hour: int, room: float | None, partial: bool = False) -> Logs:
    """The hour's measurements into its log entry: heating electricity, its cost, heat, hot water, the mean setpoint,
    and how many seconds of it Roost saw (a restart in the hour: `obs` short, so the day is not taken as complete)."""
    log = list(logs.hour_log)
    for i in range(len(log) - 1, max(-1, len(log) - 4), -1):
        if log[i]["ts"] != hour:
            continue
        e = dict(log[i])
        e["dhw"] = round(min(1.0, acc.dhw / 3600), 2)
        e["q"] = round(acc.heat, 2)
        e["e"] = round(acc.elec, 3)
        e["cost"] = round(acc.cost, 4)
        e["obs"] = round(acc.obs)
        if room is not None or "T_end" not in e:
            e["T_end"] = room
        if acc.sp[1] >= 1800:
            e["sp_mean"] = round(acc.sp[0] / acc.sp[1], 2)
        if partial:
            e["partial"] = True
        if sum(acc.src) > 0:
            e["e_sun"], e["e_bat"], e["e_grid"] = (round(x, 3) for x in acc.src)
        log[i] = e
    a = acc.sp
    sp_hist = logs.sp_hist
    if a[1] >= 1800:                      # at least half the hour seen
        sp_hist = {**sp_hist, hour: [round(a[0] / a[1], 2), round(a[2] / a[3], 2) if a[3] >= 1800 else None]}
    return replace(logs, hour_log=log, sp_hist=sp_hist)


@dataclass(frozen=True)
class Restored:
    acc: HourAcc
    meters: tuple[float | None, float | None] | None     # (last_elec, last_indoor) to go on counting from, or None
    close_partial: int | None = None                     # the hour to close as partial (a later hour now)


def restore_acc(d: dict | None, t: float) -> Restored | None:
    """Back after a restart. The same hour: go on counting, from the meter reading Roost had. A later hour: the hour
    that was going on is closed with what was seen of it (marked partial); the meter starts afresh, as the use while
    Home Assistant was down cannot be put in an hour."""
    if not d or d.get("hour") is None:
        return None
    sp = list(d.get("sp") or [0.0, 0.0, 0.0, 0.0])
    src = list(d.get("src") or [0.0, 0.0, 0.0])
    acc = HourAcc(hour=int(d["hour"]), dhw=float(d.get("dhw") or 0.0), heat=float(d.get("heat") or 0.0),
                  elec=float(d.get("elec") or 0.0), cost=float(d.get("cost") or 0.0), obs=float(d.get("obs") or 0.0),
                  sp=(sp[0], sp[1], sp[2], sp[3]), src=(src[0], src[1], src[2]))
    if acc.hour == int(t // 3600 * 3600):
        return Restored(acc, (d.get("last_elec"), d.get("last_indoor")))
    return Restored(acc, None, acc.hour)


# ------------------------------------------------------------ what the hour log sees
@dataclass(frozen=True)
class PlanView:
    """What the hour log needs of the plan in force (manager: plan, plan_at, plan_hours, plan_guess, ...)."""
    plan: planner.Plan | None
    at: float | None
    hours: list[planner.HourIn]
    guess: list[bool]
    on_guess: Any
    w_now: float | None
    corr_kw: Any
    corr_n: Any
    reason_code: Any
    reason_args: dict


@dataclass(frozen=True)
class HourView:
    """One hour as the log sees it: the time, the weather and prices of the plan for it, and the meters now."""
    ts: int                          # start of the UTC hour
    local_hour: int
    room: float
    storage_e: float
    sp: float                        # the setpoint (or OpenTherm level) Roost steered
    sp_t: float | None               # what the thermostat itself has
    ot: dict | None                  # OpenTherm: flow, ot_state, k_factor; None with a thermostat
    w: float                         # heat pump power while heating, kW
    away: bool
    wx: tuple                        # (outdoor °C, ..., wind)
    rad: float                       # sun on the house
    h: planner.HourIn                # the plan's input for this hour
    pred: dict                       # what was predicted for this hour (p1, p6, f6)
    mode: Any
    window: bool
    paused: bool


def day_context(house: dict, pump: dict, settings: dict, rooms: list[dict], comfort_schedule: Any, at: int) -> dict:
    """What a day is replayed with at its end, frozen at its first logged hour."""
    return {"house": house, "pump": pump, "settings": settings, "extra_rooms": len(rooms), "room_settings": rooms,
            "comfort_schedule": comfort_schedule, "at": at, "replay_version": planner.REPLAY_VERSION}


def policy_changed(context: dict, settings: dict, rooms: list[dict], comfort_schedule: Any) -> bool:
    """Whether the settings differ from those the day started with (the day's saving is then unsure)."""
    return (planner.user_settings(context["settings"]) != planner.user_settings(settings)
            or context.get("room_settings", []) != rooms
            or context.get("comfort_schedule") != comfort_schedule)


def settings_changed(logs: Logs, day: str) -> Logs:
    """The day's settings changed (its saving is then unsure): marked in its context."""
    return replace(logs, day_contexts={**logs.day_contexts, day: {**logs.day_contexts[day], "settings_changed": True}})


def flow_measured(logs: Logs, flow_acc: list[float]) -> Logs:
    """The hour that just ended: the flow the heat pump really made while it heated (measured, not asked)."""
    last = {**logs.hour_log[-1], "flow_meas": round(flow_acc[1] / flow_acc[2], 1)}
    return replace(logs, hour_log=logs.hour_log[:-1] + [last])


def with_day_context(logs: Logs, day: str, context: dict) -> Logs:
    return replace(logs, day_contexts=dict(sorted({**logs.day_contexts, day: context}.items())[-SAVING_DETAIL_DAYS - 1:]))


def logged(logs: Logs, hour: int, entry: dict, plan: dict) -> Logs:
    """An hour logged: its entry and what the plan in force saw; predictions older than the last hour dropped."""
    return replace(logs, hour_log=(logs.hour_log + [entry])[-HOUR_LOG_KEPT:], plan_log=(logs.plan_log + [plan])[-PLAN_LOG_KEPT:],
                   pred={k: v for k, v in logs.pred.items() if k > hour - 7200})


def hour_entry(v: HourView, plan: PlanView) -> dict:
    """The hour-log entry: what the thermostat had and the inputs, so the day can be replayed for the saving."""
    h, pr = v.h, v.pred
    return {"ts": v.ts, "T": round(v.room, 2), "E": round(v.storage_e, 2), "sp": v.sp,
            "sp_t": v.sp_t,
            **({"ot": True, **v.ot} if v.ot is not None else {}),
            "w": v.w,
            "away": v.away,
            "t_out": v.wx[0], "rad": round(v.rad, 4), "hour": v.local_hour,
            "wind": v.wx[2] if v.wx[2] is not None else 3.5, "p_grid": h.p_grid, "p_own": h.p_own, "own": h.own_kw,
            "p_imp": None if h.p_imp is None else round(h.p_imp, 4),
            "day": h.day, "comfort_mask": h.comfort_mask,
            # for looking back: the plan, its reason, what was predicted for this hour, the mode
            "sp_plan": plan.plan.first.sp if plan.plan and plan.plan.first else None,
            "reason": plan.reason_code, "args": dict(plan.reason_args),
            "p6": pr.get("p6"), "p1": pr.get("p1"), "mode": v.mode, "window": v.window,
            "paused": v.paused,
            # forecast 6 h before for this hour: [outdoor °C, sun, price, price guessed]
            "f6": pr.get("f6"), "corr": [plan.corr_kw]}


def plan_entry(hour: int, room: float, storage_e: float, sp_now: float | None, plan: PlanView, comfort_schedule: Any) -> dict:
    """Everything the plan in force saw, so a decision can be replayed exactly (planner.plan with these hours, room,
    storage, output and setpoint): per hour ahead [outdoor °C, sun, wind, grid price, own price, own solar kW, hot
    water share, correction kW, price guessed], and the setpoints it planned."""
    p, guess = plan.plan, plan.guess
    return {
        "ts": hour, "at": round(plan.at or 0), "room": round(room, 2), "E": round(storage_e, 2),
        "w_now": None if plan.w_now is None else round(plan.w_now, 2), "sp_now": sp_now,
        "corr": [plan.corr_kw, plan.corr_n],
        "hours": [[round(h.t_out, 1), round(h.rad, 3), round(h.wind, 1), round(h.p_grid, 4), round(h.p_own, 4), round(h.own_kw, 2),
                   round(h.dhw, 2), round(h.extra_kw, 3), guess[i] if i < len(guess) else None] for i, h in enumerate(plan.hours)],
        "sp": [x.sp for x in p.hours] if p else None, "neutral": plan.on_guess,
        "comfort_masks": [h.comfort_mask for h in plan.hours],
        "comfort_schedule": comfort_schedule}


def remember_prediction(pred: dict[int, dict], base: int, p, plan: PlanView) -> dict[int, dict]:
    """pred with the room the plan p expects at the start of the coming hours, 1 and 6 hours ahead (from the hour
    base), and the inputs it expects 6 hours ahead, to set beside what happened."""
    out = dict(pred)
    for j, hp in enumerate(p.hours[:6]):
        ahead = j + 1
        if ahead in (1, 6):
            k = base + ahead * 3600
            out[k] = {**out.get(k, {}), f"p{ahead}": round(hp.t_end, 2)}
    if len(plan.hours) > 6:
        # weather forecast and price errors
        h, guess = plan.hours[6], plan.guess[6] if len(plan.guess) > 6 else None
        k = base + 6 * 3600
        out[k] = {**out.get(k, {}), "f6": [round(h.t_out, 1), round(h.rad, 3), round(h.p_grid, 4), guess]}
    return out


# ------------------------------------------------------------ the day
def local_day(ts: float, tz: tzinfo) -> str:
    return datetime.fromtimestamp(ts, tz=tz).date().isoformat()


def entries_of_day(hour_log: list[dict], day: str, tz: tzinfo) -> list[dict]:
    return [e for e in hour_log if local_day(e["ts"], tz) == day]


def replay_models(context: dict | None, house, pump, settings: planner.Settings) -> tuple:
    """The house, heat pump and settings a day is replayed with: those frozen in its context, else the current ones."""
    if not context:
        return house, pump, settings
    return (model.HouseModel.from_dict(context["house"]), heatpump.HeatPumpModel.from_dict(context["pump"]),
            planner.Settings(**context["settings"]))


def day_quality(entries: list[dict], replayed_hours, expected: int, start: int, context: dict | None, n_rooms: int) -> dict:
    """savings.assess_day with what the day's context says (replayed the current way, extra rooms, settings changed)."""
    return savings.assess_day(entries, replayed_hours, expected, start,
                              bool(context and context.get("replay_version") == planner.REPLAY_VERSION),
                              context["extra_rooms"] if context else n_rooms,
                              bool(context and context.get("settings_changed")))


def by_hand_on(events, day: str) -> int:
    """How often the thermostat was set by hand on the day."""
    return sum(1 for e in events if e.get("kind") == "by_hand" and str(e.get("t", "")).startswith(day))


def day_closed(logs: Logs, day: str, entries: list[dict], res: tuple | None, quality: dict | None, comfort: float,
               by_hand: int) -> Logs:
    """The day replayed (res: planner.replay_day, None when it could not be): its saving (accepted when its quality
    is valid) and its numbers."""
    detail, days = logs.saving_detail, logs.saving_days
    if res is not None and quality is not None:
        detail = {**detail, day: savings.publish(res[2], quality)}
        if quality["valid"]:
            days = {**days, day: detail[day]["saving"]}
        else:
            days = {k: v for k, v in days.items() if k != day}
        detail = dict(sorted(detail.items())[-SAVING_DETAIL_DAYS:])
    stats = lookback.day_stats(entries, comfort, by_hand, res[0] if res else None, res[1] if res else None)
    if quality is not None:
        stats.update(model_saving=stats.get("saving"), saving=detail[day]["saving"], quality=quality)
    return replace(logs, saving_detail=detail, saving_days=days, day_stats={**logs.day_stats, day: stats})


def drop_unchecked(logs: Logs) -> Logs:
    """Older days have no frozen context or validation: their old estimate is kept, but not counted as accepted saving
    in the month total (never replace an unavailable yesterday by an older successful day)."""
    stats, days = dict(logs.day_stats), dict(logs.saving_days)
    for day in list(days):
        st = dict(stats.get(day, {}))
        if not st.get("quality", {}).get("valid"):
            st.update(model_saving=st.get("model_saving", days[day]), saving=None,
                      quality={"valid": False, "status": "unreliable", "reasons": ["missing_context"]})
            days.pop(day)
        stats[day] = st
    return replace(logs, day_stats=stats, saving_days=days)


def logged_days(hour_log: list[dict], tz: tzinfo) -> list[str]:
    return sorted({local_day(e["ts"], tz) for e in hour_log})


# ------------------------------------------------------------ the numbers for the card
def next_breakdown(plan: PlanView) -> dict | None:
    """The saving per hour of the plan in force (planner.breakdown), with the time of each hour."""
    p = plan.plan
    if p is None or not p.breakdown or plan.at is None:
        return None
    base = int(plan.at // 3600 * 3600)
    g = plan.guess
    # Retain legacy fields for existing reports; new plans contain only published tariffs.
    return {**p.breakdown, "neutral": plan.on_guess,
            "hours": [{**r, "ts": base + r["i"] * 3600, "guess": bool(g[r["i"]]) if r["i"] < len(g) else False} for r in p.breakdown["hours"]]}


def model_band(check: dict) -> float | None:
    """How far the model's energy was off this week (heat and electricity, lookback check): the share a saving
    worked out with the model may be off. None before the first check."""
    hr, er = check.get("heat_ratio"), check.get("elec_ratio")
    if hr is None or er is None:
        return None
    return round(min(1.0, abs(1 - float(hr)) + abs(1 - float(er))), 3)


def saving_month(saving_days: dict[str, float], month: str) -> float | None:
    """The accepted saving of the days of a month (YYYY-MM) together."""
    values = [v for k, v in saving_days.items() if k.startswith(month)]
    return round(sum(values), 2) if values else None


def dhw_samples(weheat_hours: dict[int, dict], rows: list, since: float,
                local: Callable[[int], datetime]) -> list[tuple[int, int, float, int]]:
    """(local weekday, local hour, share on hot water, local day number) of the last weeks, Weheat logs first."""
    src = {t: v["dhw_s"] for t, v in weheat_hours.items() if t >= since and "dhw_s" in v}
    if len(src) < 7 * 24:
        src = {r.ts: r.dhw_s for r in rows if r.ts >= since}
    out = []
    for t, secs in src.items():
        loc = local(t)
        out.append((loc.weekday(), loc.hour, secs / 3600, loc.toordinal()))
    return out


# ------------------------------------------------------------ the comfort range: what a setting would have cost
ADVICE_DAYS = 7          # the last week of days that were over
ADVICE_MIN_DAYS = 3      # fewer days with the settings in force: no advice yet


def with_what_if(logs: Logs, day: str, what_if: dict | None) -> Logs:
    """planner.what_if_day of a day into its numbers (day_stats)."""
    if not what_if or day not in logs.day_stats:
        return logs
    return replace(logs, day_stats={**logs.day_stats, day: {**logs.day_stats[day], "what_if": what_if}})


def day_steering(entries: list[dict]) -> bool | None:
    """How the day was steered, from its own hours: True over OpenTherm (each hour has its "ot" part), False with the
    thermostat, None when it changed during the day (no what-if then)."""
    ot = {e.get("ot") is not None for e in entries}
    return None if len(ot) != 1 else ot.pop()


def comfort_advice(day_stats: dict[str, dict], comfort: float, night_min: float, store_max: float) -> dict | None:
    """Per change (eco down/up, top down/off): the extra cost and °C·h below comfort per week, from the last days that
    were over with these same settings. None with fewer than ADVICE_MIN_DAYS such days."""
    same = []
    for day in sorted(day_stats)[-ADVICE_DAYS:]:
        wi = day_stats[day].get("what_if")
        b = (wi or {}).get("base") or {}
        if wi and (b.get("comfort"), b.get("night_min"), b.get("store_max")) == (comfort, night_min, store_max):
            same.append(wi)
    if len(same) < ADVICE_MIN_DAYS:
        return None
    out: dict = {"days": len(same), "night_min": night_min, "store_max": store_max, "comfort": comfort}
    for name in ("eco_down", "eco_up", "top_down", "top_off"):
        xs = [w[name] for w in same if name in w]
        if len(xs) == len(same):
            k = 7.0 / len(xs)
            out[name] = {"week": round(sum(x["cost"] for x in xs) * k, 2), "short": round(sum(x["short"] for x in xs) * k, 1)}
    return out
