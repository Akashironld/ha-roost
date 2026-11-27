"""Heat pump model: COP, outdoor-sensor bias and maximum heat output, learned from hourly history. Pure Python.

COP = alpha + beta * T_sensor + gamma * max(0, Q - Q_REF)
    T_sensor  the heat pump's own outdoor reading (the COP curve belongs to it; it reads high in the sun, so for
              planning Roost uses the weather forecast plus the learned bias)
    Q         heat output that hour (kWh); above Q_REF the water gets hotter and the COP drops

Starting values come from a Weheat Blackbird P80 (2,313 winter hours of the author's unit); a few hundred hours of
the user's own data take over (ridge pull towards the start values, weight ~200 hours).

The model also holds how the unit responds to the thermostat and when it makes hot water (learned in response.py).
An OpenTherm thermostat modulates: the heat asked for is about the house's loss plus a gain per degree the thermostat's
own reading is below the setpoint, and the unit follows that demand with a delay:
    demand = a · loss + k · (setpoint + offset − thermostat reading),  thermostat reading = room + th_diff
    output moves towards the demand by `follow` of the gap per hour (1 = at once); when the thermostat asks for
    nothing at all (demand ≤ 0) the unit stops at once (`stops`: seen on a Lyric T6 + Blackbird P80, and 5 % closer
    to a year of its hourly heat than a slow fall; a slow fall made the planner count on heat that never came, so it
    lowered the setpoint each time the unit ran and the unit ran in short bursts)
    q_min         lowest steady heat output; below it the unit cycles, at cyc × the COP
    dhw           share of each hour of the week (Monday 00:00 first, local time) spent on hot water: no space heating
Without learned values (k None) it is a thermostat that closes a gap within the hour: k = C per hour, no delay.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TypedDict

from . import defrost
from .util import fill, solve

Q_REF = 3.5
COP_MIN, COP_MAX = 1.6, 7.5

# per model family: COP start values and the maximum heat output line (kW) = a + b * T_out, clamped
class _Profile(TypedDict):
    alpha: float
    beta: float
    gamma: float
    pmax_a: float
    pmax_b: float
    pmax_lo: float
    pmax_hi: float


PROFILES: dict[str, _Profile] = {
    "p80": {"alpha": 3.04, "beta": 0.19, "gamma": -0.27, "pmax_a": 5.7, "pmax_b": 0.15, "pmax_lo": 5.3, "pmax_hi": 7.0},
    "p60": {"alpha": 3.04, "beta": 0.19, "gamma": -0.35, "pmax_a": 4.3, "pmax_b": 0.11, "pmax_lo": 4.0, "pmax_hi": 5.3},
    "generic": {"alpha": 3.0, "beta": 0.18, "gamma": -0.3, "pmax_a": 4.5, "pmax_b": 0.12, "pmax_lo": 3.5, "pmax_hi": 7.0},
}


# radiators need warmer water than a floor: a lower COP to start from (the unit's own meters take over)
EMITTER_COP = {"floor": 0.0, "radiators": -0.7, "both": -0.35}     # by kind; curve.emitter_profile weighs the ticks


def profile_for(model_name: str | None) -> str:
    n = (model_name or "").lower()
    if "p80" in n:
        return "p80"
    if "p60" in n:
        return "p60"
    return "generic"


# Weheat manual 6.3 (23-11-2026): below 5 °C outside the circulation pump runs all the time against frost (measured on
# the P80: the indoor unit 55 W idle above ~6 °C, 108 W below ~4 °C). In such hours heating adds no pump electricity.
FROST_PUMP = 5.0

@dataclass
class HeatPumpModel:
    alpha: float = PROFILES["p80"]["alpha"]
    beta: float = PROFILES["p80"]["beta"]
    gamma: float = PROFILES["p80"]["gamma"]
    pmax_a: float = PROFILES["p80"]["pmax_a"]
    pmax_b: float = PROFILES["p80"]["pmax_b"]
    pmax_lo: float = PROFILES["p80"]["pmax_lo"]
    pmax_hi: float = PROFILES["p80"]["pmax_hi"]
    bias: float = 1.0                  # heat pump outdoor sensor minus weather service, at night (°C)
    hours: int = 0                     # heating hours behind the COP fit
    source: str = "profile"
    # response to the thermostat (learned in response.py)
    a: float = 1.0                     # share of the house's loss the demand follows
    k: float | None = None             # kW per °C below the setpoint; None: the house's C per hour (closes a gap in an hour)
    offset: float = 0.0                # the unit heats towards setpoint + offset (°C, in the thermostat's reading)
    follow: float = 1.0                # share of the gap between output and demand closed per hour
    stops: bool = True                 # no demand at all: the output stops at once (False: it falls with `follow`)
    th_diff: float = 0.0               # thermostat reading minus the room sensor (°C)
    q_min: float = 0.0                 # lowest steady heat output (kW); 0 = unknown
    cyc: float = 1.0                   # COP factor while cycling below q_min
    resp_hours: int = 0
    resp_error: float | None = None    # kWh per hour over 6 hours, heat output predicted against measured
    resp_source: str = "default"
    dhw: list[float] | None = None     # 168 values: share of the hour on hot water, Monday 00:00 first (local time)
    dhw_weeks: float = 0.0
    dhw_fixed: float | None = None     # how fixed the hot-water times are (1 = a timer, low = the unit picks its own)
    # the indoor unit's electricity (its own meter, outside the COP): when idle, and on top of that per hour running
    indoor_idle_kw: float | None = None
    indoor_run_kw: float | None = None
    # defrosting: share of the heat lost per °C below defrost.T0 in damp air (defrost.py). The COP above is learned on
    # the heat after defrosting, so it holds an hour of typical humidity; cop_net corrects it for the hour's own
    defrost_a: float = defrost.A_PRIOR
    defrost_hours: int = 0

    @classmethod
    def for_profile(cls, name: str) -> "HeatPumpModel":
        p = PROFILES.get(name, PROFILES["generic"])
        return cls(**p, source=f"profile {name}")

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None, profile: str = "p80") -> "HeatPumpModel":
        return fill(cls.for_profile(profile), d)

    def cop(self, t_out: float, q_kw: float) -> float:
        """COP at the weather service's outdoor temperature (bias added) and a heat output in kW."""
        c = self.alpha + self.beta * (t_out + self.bias) + self.gamma * max(0.0, q_kw - Q_REF)
        return max(COP_MIN, min(COP_MAX, c))

    def pumps_anyway(self, t_out: float, t_adj: float = 0.0) -> bool:
        """The unit's circulation pump runs on its own in this hour (frost protection below FROST_PUMP at its own
        sensor), so the indoor unit uses no more electricity while the unit heats than while it waits."""
        return t_out + self.bias + t_adj < FROST_PUMP

    def defrost_factor(self, t_out: float, rh: float | None) -> float:
        """This hour's defrosting against an hour of typical humidity (what cop() was learned on): below 1 in damp air,
        above 1 in dry air, 1 without a humidity forecast (22-11-2026: counting all of it again on top of the learned
        COP took the cheap cold nights away in the simulations)."""
        if rh is None:
            return 1.0
        return (1.0 - defrost.share(t_out, rh, self.defrost_a)) / (1.0 - defrost.share(t_out, defrost.RH_UNKNOWN, self.defrost_a))

    def cop_net(self, t_out: float, q_kw: float, rh: float | None = None, t_adj: float = 0.0) -> float:
        """COP of the heat that reaches the house in this hour's humidity (cop() is that of a typical hour); t_adj:
        today's correction of the forecast for the air at the unit (defrost.anomaly_ahead), for defrosting only."""
        f = self.defrost_factor(t_out + t_adj, rh)
        return self.cop(t_out, q_kw) if f == 1.0 else max(COP_MIN, min(COP_MAX, self.cop(t_out, q_kw) * f))

    def pmax(self, t_out: float) -> float:
        return max(self.pmax_lo, min(self.pmax_hi, self.pmax_a + self.pmax_b * t_out))

    def demand(self, loss_net: float, sp: float, room: float, C: float) -> float:
        """Heat the thermostat asks for (kW, not clamped): loss_net = loss − sun − other gains."""
        k = self.k if self.k is not None else C
        return self.a * loss_net + k * (sp + self.offset - room - self.th_diff)

    def dhw_share(self, weekday: int, hour: int) -> float:
        """Expected share of this local hour spent on hot water (weekday 0 = Monday)."""
        if not self.dhw or len(self.dhw) != 168:
            return 0.0
        return self.dhw[(weekday % 7) * 24 + hour % 24]




def learn(rows, previous: HeatPumpModel, prior_hours: float = 200.0) -> tuple[HeatPumpModel, str]:
    """rows: model.HourRow. Uses hours with ≥ 0.3 kWh electricity for heating and almost no hot water."""
    m = HeatPumpModel.from_dict(previous.as_dict())
    use = [r for r in rows if r.E >= 0.3 and r.dhw_s < 600 and r.T_out_sensor is not None and r.Q > 0 and 1.0 <= r.Q / r.E <= 8.0]
    notes = []
    if len(use) >= 30:
        theta0 = [m.alpha, m.beta, m.gamma]
        X = [[1.0, r.T_out_sensor, max(0.0, r.Q - Q_REF)] for r in use]
        y = [r.Q / r.E for r in use]
        A = [[0.0] * 3 for _ in range(3)]
        b = [0.0] * 3
        for xi, yi in zip(X, y, strict=False):
            for i in range(3):
                b[i] += xi[i] * yi
                for j in range(3):
                    A[i][j] += xi[i] * xi[j]
        for i in range(3):            # pull towards the start values, as if they were `prior_hours` hours
            lam = prior_hours * max(1e-6, sum(x[i] ** 2 for x in X) / len(X))
            A[i][i] += lam
            b[i] += lam * theta0[i]
        th = solve(A, b)
        if th and 2.0 <= th[0] <= 6.0 and 0.03 <= th[1] <= 0.4 and -0.8 <= th[2] <= 0.0:
            m.alpha, m.beta, m.gamma = (round(v, 3) for v in th)
            m.hours, m.source = len(use), "learned"
            notes.append(f"COP from {len(use)} heating hours")
        else:
            notes.append("COP fit out of range: kept")
    else:
        notes.append(f"COP: {len(use)} heating hours, need 30")
    night = sorted(r.T_out_sensor - r.T_out for r in rows if r.T_out_sensor is not None and r.rad < 0.01
                   and -30 < r.T_out_sensor < 45)
    if len(night) >= 24:
        m.bias = round(max(-3.0, min(5.0, night[len(night) // 2])), 2)
        notes.append(f"outdoor sensor bias {m.bias:+.1f} °C")
    # maximum output: only ever raised above the profile, from hours the Weheat logs show as fully heating at a high
    # output (whole hours at low power in mild weather say nothing about the maximum)
    pts = [(r.T_out, r.Q) for r in rows if r.heating_s >= 3300 and r.dhw_s < 60 and r.Q > m.pmax(r.T_out) * 0.97]
    if len(pts) >= 5:
        over = sorted(q - m.pmax(t) for t, q in pts)
        lift = over[int(len(over) * 0.9)]
        if lift > 0:
            m.pmax_a = round(m.pmax_a + lift, 2)
            m.pmax_hi = round(m.pmax_hi + lift, 2)
            notes.append(f"maximum output raised {lift:+.1f} kW ({len(pts)} hours above the profile)")
    a, n_def = defrost.learn(rows, m.defrost_a, m.bias)
    if n_def >= defrost.MIN_HOURS:
        m.defrost_a, m.defrost_hours = a, n_def
        notes.append(f"defrost {a:.3f} per °C ({n_def} cold hours)")
    else:
        notes.append(f"defrost: {n_def} cold heating hours with humidity, need {defrost.MIN_HOURS}")
    idle, run = learn_indoor(rows, m.bias)
    if idle is not None and run is not None:
        m.indoor_idle_kw, m.indoor_run_kw = idle, run
        notes.append(f"indoor unit {idle * 1000:.0f} W idle, +{run * 1000:.0f} W running")
    return m, "; ".join(notes)


INDOOR_MIN_HOURS = 24


def learn_indoor(rows, bias: float = 0.0) -> tuple[float | None, float | None]:
    """The indoor unit's meter (HourRow.Ei) against the share of the hour the unit heated: idle kW (the intercept) and
    the extra kW of a whole hour running (the slope). Hours with hot water are left out (its pump runs then too), and
    hours with heat but no heating seconds (those seconds come only from the Weheat logs) say nothing about the share,
    and cold hours neither (the pump runs against frost then, heating or not: HeatPumpModel.pumps_anyway)."""
    pts = []
    for r in rows:
        if r.Ei is None or r.dhw_s > 60 or not 0.0 <= r.Ei < 1.0:
            continue
        # below ~5 °C at the unit its pump runs all the time (frost protection): idle then is not idle
        t_air = r.T_out_sensor if r.T_out_sensor is not None else r.T_out + bias
        if t_air < FROST_PUMP + 1.0:          # a degree of margin: hours around the switch are mixed
            continue
        if r.heating_s > 0:
            pts.append((min(1.0, r.heating_s / 3600.0), r.Ei))
        elif r.Q < 0.05 and r.E < 0.02:
            pts.append((0.0, r.Ei))
    idle = [e for f, e in pts if f == 0.0]
    full = [e for f, e in pts if f >= 0.5]
    if len(idle) < INDOOR_MIN_HOURS or len(full) < INDOOR_MIN_HOURS:
        return None, None
    n = len(pts)
    mf, me = sum(f for f, _ in pts) / n, sum(e for _, e in pts) / n
    sff = sum((f - mf) ** 2 for f, _ in pts)
    if sff <= 0:
        return None, None
    slope = sum((f - mf) * (e - me) for f, e in pts) / sff
    a = me - slope * mf
    return round(max(0.0, min(0.5, a)), 3), round(max(0.0, min(0.5, slope)), 3)
