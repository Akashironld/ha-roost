"""OpenTherm steering: from the planned heat output to a flow temperature for an OpenTherm master. Pure Python.

Roost asks the heat pump for a flow temperature through an OpenTherm master in Home Assistant (first: the elvinhome
THRM ONE with its own firmware). The master is the safety layer: it keeps limits, a soft start and a minimum run and
off time, and falls back to its own heating curve when Roost stops writing. The agreement with the master:

- Roost writes the flow setpoint (a `number`) at least every LEASE_S, also when the value is the same; 0 = no heat
  demand. A master that hears nothing for its command timeout (THRM ONE: 15 min) takes over on its heating curve.
- Roost watches the master's state (a `sensor`): anything but the "steered by Home Assistant" value while Roost
  steers is a notice.
- Roost sets the master's control mode (a `select`) to Home Assistant when it starts steering and back to the heating
  curve when it stops.

What the plan chose is a heat output per hour (planner.plan_ot). The flow that gives it comes from the emitter
(curve.py: Q = k · (flow − room)^n). Two things correct that within the hour:

- **heat feedback**: the heat the unit makes (its power_output) against the level planned; the flow moves by 0.5 °C
  at most every TRIM_EVERY_S, at most ±TRIM_MAX, not in the first TRIM_AFTER_S after a start (the start peak);
- **k learned**: the heat measured at the flow measured slowly corrects the emitter's k (k_factor), so the trim goes
  back towards zero and the next hours start closer.

Rules from measurements on a Weheat P80 (20-11-2026):
- it cannot run below ~2.8 kW (900 rpm). Asked for a flow it cannot keep that low, the flow overshoots, the unit
  stops itself and then rests ~60 min. So while it runs Roost never asks below the flow of the lowest output, and on
  the lowest level, once running steadily, GUARD below the flow it makes: it settles at its own lowest speed (long and
  low), whatever that is for this make, and Roost learns that output (otlearn.py);
- the first 15-20 min after a start are expensive: on only at the turn of the hour (unless the room is below its hard
  minimum), never off within MIN_RUN_S of a start (the master would keep it running anyway), and not off when the
  plan heats again the next hour (a stop costs the master's minimum off time and the unit's rest: an hour).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .reasons import Reason
from .util import fill

LEASE_S = 240            # write at least this often (the agreement says 5 min; a tick is 2 min)
TRIM_EVERY_S = 600
TRIM_AFTER_S = 1200
TRIM_MAX = 2.0
TRIM_DEADBAND = 0.4      # kW: heat this close to the level planned is right
GUARD = 0.5              # °C: on the lowest level, at most this below the flow the unit makes
MIN_RUN_S = 1800
K_RATE = 0.03            # share per tick the emitter's k moves towards what is measured
K_LIMITS = (0.6, 1.6)
URGENT_K = 0.3           # room this far below its hard minimum: start at once (also when the plan says off)
NO_PLAN_S = 3600         # without a plan or a room reading this long: stop writing, the master falls back
LOW_FLOOR = 0.6          # lowest level: never below the flow of this share of q_min (a stale or odd flow reading)
LOW_BAND = 1.0           # kW: on the lowest level the unit is at its own lowest output while it makes at most this more
UPSET_KW = (0.3, 1.5)    # kW: heat below the first (a defrost), or more than the second above the level with its flow
                         # above the flow asked (it speeds up on its own): no trim, no learning of k, no following up
SETTLE_S = 900           # after such an upset, this long before the heat and flow count again
WINDUP = 1.0             # °C: the flow asked is this far from the flow made: the unit has not caught up, trim no further
DEFAULT_K, DEFAULT_N = 0.3, 1.1     # floor heating, ~2.8 kW at 10 °C flow above the room (author's P80, 20-11)


@dataclass
class OTSettings:
    q_min: float = 2.8
    min_flow: float = 20.0
    max_flow: float = 40.0
    step: float = 0.5
    min_run_s: float = MIN_RUN_S     # the master's minimum run time (read from it when known)
    k: float = DEFAULT_K
    n: float = DEFAULT_N


@dataclass
class OTMemory:
    level: float = 0.0               # the level steered now (kW, 0 = off)
    flow: float = 0.0                # the flow asked now (0 = no demand); in shadow mode: what would be asked
    last_write: float | None = None
    level_hour: int | None = None    # the hour (epoch h) the level last went on or off
    on_since: float | None = None
    trim: float = 0.0
    trim_at: float | None = None
    k_factor: float = 1.0
    bad_since: float | None = None   # the master's state not "steered by HA" since
    ok_at: float | None = None       # last round with a plan and a room reading
    low_at: float | None = None      # lowest level: when the flow last moved with the unit's own flow
    upset_at: float | None = None    # last defrost or speed-up of its own (UPSET_KW)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "OTMemory":
        return fill(cls(), d)


@dataclass
class OTDecision:
    flow: float          # flow asked (°C), 0 = no heat demand
    level: float         # heat output it is meant to give (kW)
    write: bool          # send it now (active mode only)
    why: Reason

    def as_dict(self) -> dict:
        return {"flow": self.flow, "level": self.level, "write": self.write, "why": self.why.as_dict()}


def flow_for(level: float, room: float, k: float, n: float) -> float:
    """The flow that makes `level` kW into a room at `room` °C (EN 442 emitter)."""
    if level <= 0:
        return 0.0
    return room + (level / max(1e-3, k)) ** (1 / n)


def level_for(flow: float, room: float, k: float, n: float) -> float:
    """The heat (kW) emitters give at a flow: the inverse of flow_for (the simulator's house uses it)."""
    return 0.0 if flow <= room else k * (flow - room) ** n


def _round(v: float, step: float) -> float:
    return round(round(v / step) * step, 2)


def decide(now: float, planned: float | None, room: float | None, hard_min: float, mem: OTMemory, cs: OTSettings,
           active: bool, measured_kw: float | None = None, measured_flow: float | None = None, running: bool = False,
           pump_max_flow: float | None = None, paused_min: float | None = None,
           next_level: float | None = None) -> OTDecision:
    """What to ask the master now. planned: the plan's heat output for this hour (kW) or None (no plan).
    measured_kw / measured_flow / running: what the unit does now. pump_max_flow: the highest flow the unit accepts
    (OpenTherm ID 49). paused_min: changed by hand, minutes left. next_level: the plan's level for the next hour (None:
    not known, or off for a reason that must act now, as an open window). Updates mem (also in shadow mode, as if sent)."""
    hour = int(now // 3600)
    if paused_min is not None:
        return OTDecision(mem.flow, mem.level, False, Reason("paused", {"min": round(paused_min)}))
    cold = room is not None and room < hard_min - URGENT_K
    if (planned is None or room is None) and not cold:
        # nothing to go on: keep the last request a while (a plan comes back within minutes), then stop writing so the
        # master falls back on its own heating curve after its command timeout
        keep = mem.ok_at is not None and now - mem.ok_at < NO_PLAN_S
        return OTDecision(mem.flow, mem.level, keep and _lease_due(now, mem, active), Reason("no_plan" if planned is None else "no_room"))
    assert room is not None             # without a room only a cold room (which has one) gets this far
    if planned is not None:
        mem.ok_at = now
    level, why = planned or 0.0, Reason("following")
    if cold and level <= 0:
        level, why = cs.q_min, Reason("urgent")            # below the hard minimum: heat, whatever the plan says
    on, want_on = mem.level > 0, level > 0
    if on != want_on:
        urgent = want_on and cold
        if not on and not urgent and mem.level_hour == hour:
            level, why = 0.0, Reason("ot_wait_hour")
        elif on and mem.on_since is not None and now - mem.on_since < cs.min_run_s:
            mins = (cs.min_run_s - (now - mem.on_since)) / 60
            level, why = cs.q_min, Reason("min_run", {"min": round(mins)})
        elif on and next_level is not None and next_level > 0:
            # off only for the rest of this hour and on again the next: no stop. A stop costs an hour (the master's
            # minimum off time, the unit's rest) and a start; 21-11-2026 10:58 a 2-minute "off" kept it off till 11:59
            level, why = cs.q_min, Reason("ot_bridge")
        elif on and mem.level_hour == hour and room >= hard_min:
            level, why = cs.q_min, Reason("ot_wait_hour")
        elif urgent:
            why = Reason("urgent")
    if (level > 0) != on:
        mem.level_hour = hour
        mem.on_since = now if level > 0 else None
        mem.trim, mem.trim_at = 0.0, None
    elif level > 0 and abs(level - mem.level) > 1e-6:
        mem.trim, mem.trim_at = 0.0, None
    k = cs.k * mem.k_factor
    if level > 0 and running and measured_kw is not None and (measured_kw < UPSET_KW[0] or (
            measured_kw > max(level, cs.q_min) + UPSET_KW[1] and measured_flow is not None and mem.flow > 0
            and measured_flow > mem.flow + WINDUP)):
        # a defrost (no heat) or the unit speeding up on its own (far more heat, its flow above the flow asked): its
        # heat and flow say nothing about the emitter or the flow asked (21-11-2026: k learned up to 1.37, the trim
        # pushed the flow up). More heat at the flow asked is the emitter's k being off: that is learned
        mem.upset_at = now
    settled = mem.upset_at is None or now - mem.upset_at >= SETTLE_S
    if level > 0 and running and settled and measured_kw is not None and measured_flow is not None \
            and mem.on_since is not None and now - mem.on_since >= TRIM_AFTER_S and measured_flow > room + 1:
        # what the emitter really gives: k moves slowly towards it
        k_seen = measured_kw / (measured_flow - room) ** cs.n
        f = min(K_LIMITS[1], max(K_LIMITS[0], k_seen / cs.k))
        mem.k_factor = round(mem.k_factor + K_RATE * (f - mem.k_factor), 4)
        if level > cs.q_min + 1e-6 and (mem.trim_at is None or now - mem.trim_at >= TRIM_EVERY_S):
            err = measured_kw - level
            # anti-windup: no further up while the unit has not reached the flow asked (or down while it is above it);
            # a gap that keeps growing makes it speed up on its own after ~20 min
            up_ok = mem.flow <= measured_flow + WINDUP
            down_ok = mem.flow >= measured_flow - WINDUP
            if err < -TRIM_DEADBAND and up_ok:
                mem.trim = min(TRIM_MAX, mem.trim + cs.step)
                mem.trim_at = now
            elif err > TRIM_DEADBAND and down_ok:
                mem.trim = max(-TRIM_MAX, mem.trim - cs.step)
                mem.trim_at = now
    hi = min(cs.max_flow, pump_max_flow) if pump_max_flow else cs.max_flow
    if level > 0:
        steady = running and measured_flow is not None and mem.on_since is not None and now - mem.on_since >= TRIM_AFTER_S
        if level <= cs.q_min + 1e-6 and steady and measured_flow is not None:
            # lowest level, running: just below the flow it makes, so it settles at its own lowest speed, whatever that
            # is for this unit (and Roost learns it, otlearn.py); never more than GUARD below, or it would stop itself.
            # Never below the flow of LOW_FLOOR × q_min: a reading that follows the request down (or is stale) must not
            # walk it down until the unit stops
            flow = _follow_low(now, max(measured_flow - GUARD, flow_for(LOW_FLOOR * cs.q_min, room, k, cs.n)),
                               level, measured_kw, measured_flow, settled, mem, cs)
        else:
            floor = flow_for(cs.q_min, room, k, cs.n) + 1.0   # never below what its lowest output makes
            flow = max(flow_for(level, room, k, cs.n) + mem.trim, floor)
            if level <= cs.q_min + 1e-6 and running and measured_flow is not None and measured_flow - GUARD > flow:
                # the start: do not stop it either, but only follow its flow up while it runs at its lowest output
                flow = _follow_low(now, measured_flow - GUARD, level, measured_kw, measured_flow, settled, mem, cs,
                                   base=flow)
        flow = _round(max(cs.min_flow, min(hi, flow)), cs.step)
    else:
        flow = 0.0
    changed = flow != mem.flow
    mem.level, mem.flow = level, flow
    write = active and (changed or _lease_due(now, mem, True))
    return OTDecision(flow, level, write, why)


def take_over(now: float, mem: OTMemory, running: bool, cs: OTSettings, flow_now: float | None = None) -> None:
    """Roost starts steering (shadow or the heating curve before): from what the unit does now, not from the shadow's
    own idea of it. A unit that runs counts as just started (the minimum run and on/off only at the turn of the hour
    then hold); one that does not, as off. 21-11-2026 08:58: the shadow had the hour off while the curve ran the unit
    at its lowest speed; Roost wrote 0 at once, asked again at 09:00, and the master's minimum off time kept it still
    for an hour."""
    hour = int(now // 3600)
    mem.trim, mem.trim_at, mem.low_at = 0.0, None, None
    if running:
        mem.level = mem.level if mem.level > 0 else cs.q_min
        mem.on_since, mem.level_hour = now, hour
        if flow_now is not None and flow_now > 0:
            mem.flow = _round(max(cs.min_flow, min(cs.max_flow, flow_now)), cs.step)
    else:
        mem.level, mem.flow, mem.on_since, mem.level_hour = 0.0, 0.0, None, None


def _follow_low(now: float, want: float, level: float, measured_kw: float | None, measured_flow: float, settled: bool,
                mem: OTMemory, cs: OTSettings, base: float | None = None) -> float:
    """The lowest level's flow next to the flow the unit makes (`want`: GUARD below it). The unit regulates on the flow
    asked, so following its flow up is a loop that feeds itself: asked above what it makes it speeds up, its flow rises,
    the flow asked follows (21-11-2026: 33 -> 38.5 °C in 13 min at 9.7 kW on a 2.8 kW level). So:
    - up only while it makes about the level (its lowest output, LOW_BAND) and has settled, one step per round (its
      heat reading lags a minute or two): a warm floor at the lowest speed gives a higher flow, asking less stops it;
    - else not up (held);
    - down by one step per TRIM_EVERY_S at most (a reading that follows the request down, or a flow still rising
      after a start: dropping at once would leave it above the flow asked at its lowest speed, and it stops);
    - during and SETTLE_S after a defrost: held.
    base: the flow worked out without the unit's flow (the start), never asked below it."""
    prev = mem.flow if mem.flow > 0 else (base or 0.0)
    floor = base or 0.0
    moved = mem.low_at is None or now - mem.low_at >= TRIM_EVERY_S
    if prev <= 0:
        return want
    if want > prev + 1e-6:
        at_low = measured_kw is not None and measured_kw <= max(level, cs.q_min) + LOW_BAND
        if at_low and settled:
            return max(floor, min(want, prev + cs.step))
        return max(floor, prev)
    if want < prev - 1e-6:
        if not settled:
            return max(floor, prev)                   # a defrost: its flow drops for minutes, hold
        if moved:
            mem.low_at = now
            return max(floor, want, prev - cs.step)
        return max(floor, prev)
    return max(floor, prev)


def _lease_due(now: float, mem: OTMemory, active: bool) -> bool:
    return active and (mem.last_write is None or now - mem.last_write >= LEASE_S)


def watch(now: float, state: str | None, ok: str, steering: bool, mem: OTMemory, grace_s: float = 300) -> str | None:
    """The master's state while Roost steers: None when fine, else the state (also 'unavailable'), once it has been so
    for grace_s (a write just made takes a control round of the master to show)."""
    if not steering or state == ok:
        mem.bad_since = None
        return None
    mem.bad_since = mem.bad_since or now
    return (state or "unavailable") if now - mem.bad_since >= grace_s else None
