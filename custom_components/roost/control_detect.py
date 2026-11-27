"""How the heat pump is controlled: on its own heating curve, or by the water temperature an OpenTherm thermostat asks
for (OpenTherm ID 1). Pure Python.

Weheat's API does not say which, so the user sets it and Roost checks it against the unit itself. Hourly correlation
cannot tell: on its heating curve the unit's supply and the thermostat's request drift together over the hours without
one following the other. What does tell is a step: when the requested water temperature steps while the unit runs, the
supply follows it within minutes under OpenTherm and does not move on the heating curve. Measured on a Weheat P80 on its
heating curve (November 2026): 94 steps in 14 days, median gain 0.03.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

HEATING_CURVE = "heating_curve"
OPENTHERM = "opentherm"
OPENTHERM_SMART = "opentherm_smart"
UNKNOWN = "unknown"
# what the unit itself reports it runs on (Weheat's log, currentControlMethod; the weheat package's ControlMethod)
METHODS = {0: "none", 1: HEATING_CURVE, 2: "on_off", 3: OPENTHERM, 4: OPENTHERM_SMART, 5: "cloud_thermostat",
           6: "manual_power", 7: "auto_input_select", 8: "manual_setpoint"}
# how the supply should answer a step in the requested water temperature, per method: only these two can be checked
EXPECT = {HEATING_CURVE: HEATING_CURVE, OPENTHERM: OPENTHERM}

STEP_MIN = 1.0          # °C: a smaller change in the request is not a step
STEP_MAX = 8.0          # °C: a bigger one is a start or a reset of the thermostat, not a step to follow
RUN_BEFORE_S = 600      # the unit ran this long before the step ...
WAIT_S = 1200           # ... and the supply is read this long after it, the request unchanged and the unit still running
WINDOW_S = 7 * 86400    # steps of the last week count
MIN_STEPS = 10
CURVE_BELOW = 0.15      # median gain below this: the supply does not follow the request
FOLLOW_ABOVE = 0.40     # median gain above this: it does


@dataclass
class StepTracker:
    """Collects the unit's answers to steps in the requested water temperature, fed every tick."""
    steps: list[list[float]] = field(default_factory=list)      # [time, gain]
    last_req: float | None = None
    on_since: float | None = None
    pending: list[list[float]] = field(default_factory=list)    # [time, step, supply then, request then]

    def update(self, t: float, request: float | None, supply: float | None, running: bool) -> None:
        self.steps = [s for s in self.steps if s[0] > t - WINDOW_S]
        if not running:
            self.on_since, self.pending, self.last_req = None, [], None
            return
        if self.on_since is None:
            self.on_since = t
        if request is None or supply is None:
            return          # a reading missing for a tick: keep waiting, the run and the steps go on
        # a step waits only while the request stays where it stepped to
        self.pending = [p for p in self.pending if abs(request - p[3]) < 0.05]
        for p in [p for p in self.pending if t - p[0] >= WAIT_S]:
            self.steps.append([round(p[0]), round((supply - p[2]) / p[1], 3)])
            self.pending.remove(p)
        if self.last_req is not None:
            step = request - self.last_req
            if STEP_MIN <= abs(step) <= STEP_MAX and t - self.on_since >= RUN_BEFORE_S:
                self.pending.append([t, step, supply, request])
        self.last_req = request

    def as_dict(self) -> dict:
        return {"steps": self.steps}

    @classmethod
    def from_dict(cls, data: dict | None) -> "StepTracker":
        steps = (data or {}).get("steps") or []
        return cls(steps=[[float(s[0]), float(s[1])] for s in steps if isinstance(s, list) and len(s) == 2])


@dataclass
class Detected:
    mode: str               # heating_curve | opentherm | unknown
    steps: int
    gain: float | None      # median

    def as_dict(self) -> dict:
        return {"detected": self.mode, "steps": self.steps, "gain": self.gain}


def detect(steps: list[list[float]], now: float) -> Detected:
    gains = [g for t, g in steps if t > now - WINDOW_S]
    if len(gains) < MIN_STEPS:
        return Detected(UNKNOWN, len(gains), round(median(gains), 2) if gains else None)
    m = median(gains)
    mode = HEATING_CURVE if m < CURVE_BELOW else OPENTHERM if m > FOLLOW_ABOVE else UNKNOWN
    return Detected(mode, len(gains), round(m, 2))


def method_name(code) -> str | None:
    try:
        return METHODS.get(int(code))
    except (TypeError, ValueError):
        return None


def mismatch(method: str | None, detected: str) -> bool:
    """What the unit runs on (reported or set) and how it answers steps disagree. Only heating curve (does not follow)
    and plain OpenTherm (follows) have an expected answer; the others (smart, on/off, cloud, manual) are not checked."""
    want = EXPECT.get(method or "")
    return want is not None and detected != UNKNOWN and want != detected
