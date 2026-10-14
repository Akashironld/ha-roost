"""24-hour plan of thermostat setpoints: dynamic programming over (room temperature × heat stored). Pure Python.

Ported from the author's Node-RED "Warmte-planner" v2.8. Per quarter of an hour:
- the thermostat heats on the room error only (it does not know the floor): heat output
  w = min(max output, losses − sun + (setpoint − T) · C / tau) while T < setpoint;
- the heat goes into the storage (floor, water) first and reaches the room with the learned lag — this is why floor
  heating overshoots, and why heat can be stored ahead of an expensive evening;
- electricity = heat / COP(outdoor, output); own solar (kW available that hour) is paid at its own value, the rest at
  the grid value of the hour.
Cost of an hour = electricity cost + comfort penalties (hard below the minimum, soft below the comfort temperature in
the day, mild above `warm_from`) + a cost per setpoint change; the value of the heat left after 24 hours counts too
(a deficit fully, a surplus partly: it leaks away). The setpoint is never more than `max_above_room` above the room,
so an OpenTherm thermostat keeps asking for lukewarm water (high COP).
Only the first hour is carried out; the plan is made again every quarter of an hour.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .heatpump import HeatPumpModel
from .model import HouseModel
from .reasons import Reason


@dataclass
class HourIn:
    t_out: float
    wind: float
    rad: float                 # kW/m², global radiation
    p_grid: float              # currency per kWh from the grid (or battery) this hour
    p_own: float               # currency per kWh of own solar this hour (its export value)
    own_kw: float = 0.0        # own solar available for the heat pump this hour (kW)
    day: bool = True           # comfort hours
    hour: int = 0              # local hour (for the explanation and the baseline)


@dataclass
class Settings:
    comfort: float = 20.5          # wanted in the day hours (soft)
    day_min: float = 20.0          # never below in the day hours (hard)
    night_min: float = 19.0        # never below at night (hard)
    store_max: float = 22.5        # how warm the house may get while storing heat
    warm_from: float = 23.0        # mild penalty above this
    max_above_room: float = 1.0    # setpoint at most this above the room (lukewarm water)
    sp_min: float = 18.0
    step: float = 0.5
    penalty_hard: float = 5.0      # currency per °C·hour below the minimum
    penalty_soft: float = 0.10     # per °C·hour below the comfort temperature (day)
    penalty_warm: float = 0.03     # per °C·hour above warm_from
    switch_cost: float = 0.05      # per setpoint change
    tau: float = 1.0               # the thermostat closes a gap in about an hour
    end_factor: float = 0.6        # share of surplus heat after 24 h that still counts
    baseline_night: float | None = None   # baseline thermostat at night (None: same as the day)

    def setpoints(self) -> list[float]:
        out, sp = [], self.sp_min
        while sp <= self.store_max + 1e-9:
            out.append(round(sp, 1))
            sp += self.step
        return out


@dataclass
class HourPlan:
    sp: float
    t_end: float
    kwh: float
    heat: float
    cost: float
    price: float

    def as_dict(self) -> dict:
        return {"sp": self.sp, "t": round(self.t_end, 1), "kwh": round(self.kwh, 2), "heat": round(self.heat, 2),
                "cost": round(self.cost, 3), "price": round(self.price, 4)}


@dataclass
class Plan:
    hours: list[HourPlan]
    cost: float
    kwh: float
    baseline_cost: float
    baseline_kwh: float
    saving: float                  # baseline − plan, with the end state levelled
    min_day: float | None
    notes: list[str] = field(default_factory=list)

    @property
    def first(self) -> HourPlan | None:
        return self.hours[0] if self.hours else None


class Simulator:
    def __init__(self, house: HouseModel, hp: HeatPumpModel, s: Settings) -> None:
        self.m, self.hp, self.s = house, hp, s
        lag = max(0.0, house.lag)
        self.rel = 1.0 if lag < 1e-6 else 1 - (1 - 1 / (1 + lag)) ** 0.25

    def hour(self, T: float, E: float, sp: float, h: HourIn):
        """-> (T_end, E_end, cost, kWh electricity, kWh heat, comfort penalty)"""
        m, s = self.m, self.s
        He = m.loss(h.wind)
        pmax = self.hp.pmax(h.t_out)
        sun = m.g * h.rad
        cost = kwh = heat = pen = 0.0
        own = h.own_kw * 0.25
        hard = s.day_min if h.day else s.night_min
        for _ in range(4):
            loss = He * (T - h.t_out) - m.internal
            w = 0.0
            if T < sp:
                w = loss - sun + (sp - T) * m.C / s.tau
                w = 0.0 if w < 0 else (pmax if w > pmax else w)
            E += w * 0.25
            r = E * self.rel
            E -= r
            T += (r + (sun - loss) * 0.25) / m.C
            if w > 0:
                e = w * 0.25 / self.hp.cop(h.t_out, w)
                eo = e if e < own else own
                cost += eo * h.p_own + (e - eo) * h.p_grid
                kwh += e
                heat += w * 0.25
            if T < hard:
                pen += (hard - T) * 0.25 * s.penalty_hard
            if h.day and T < s.comfort:
                pen += (s.comfort - T) * 0.25 * s.penalty_soft
            if T > s.warm_from:
                pen += (T - s.warm_from) * 0.25 * s.penalty_warm
        return T, E, cost, kwh, heat, pen


def _end_value(sim: Simulator, hours: list[HourIn], comfort: float):
    tail = hours[-6:] or hours
    price = sum(h.p_grid for h in tail) / len(tail)
    cop = sim.hp.cop(hours[-1].t_out, 3.5)
    C = sim.m.C

    def value(T: float, E: float) -> float:
        d = T + E / C - comfort
        return -d * C / cop * price * (1.0 if d < 0 else sim.s.end_factor)
    return value


def plan(house: HouseModel, hp: HeatPumpModel, s: Settings, hours: list[HourIn], t_now: float, e_now: float,
         sp_now: float | None, report: int = 24) -> Plan:
    """Plan over all `hours` (give ~36 so the last shown hours are not distorted by the horizon), report the first
    `report` hours (plan, cost, kWh, saving with the state after `report` hours levelled)."""
    sim = Simulator(house, hp, s)
    sps = s.setpoints()
    NA = len(sps)
    t_lo = min(s.night_min, t_now) - 3.0
    t_hi = max(s.store_max, t_now) + 2.0
    dT = 0.1
    NT = int(round((t_hi - t_lo) / dT)) + 1
    use_e = house.lag >= 0.3
    e_max, dE = 20.0, 1.0
    NE = int(e_max / dE) + 1 if use_e else 1
    end = _end_value(sim, hours, s.comfort)
    H = len(hours)
    end_r = _end_value(sim, hours[:min(report, H)], s.comfort)

    # V[i][j][a]: cost-to-go from room index i, storage index j, with setpoint a currently on the thermostat
    V = [[[end(t_lo + i * dT, j * dE)] * NA for j in range(NE)] for i in range(NT)]

    def interp(Vv, T: float, E: float, a: int) -> float:
        x = (T - t_lo) / dT
        x = 0.0 if x < 0 else (NT - 1.000001 if x > NT - 1.000001 else x)
        i0 = int(x)
        fx = x - i0
        if NE == 1:
            return Vv[i0][0][a] * (1 - fx) + Vv[i0 + 1][0][a] * fx
        y = E / dE
        y = 0.0 if y < 0 else (NE - 1.000001 if y > NE - 1.000001 else y)
        j0 = int(y)
        fy = y - j0
        r0 = Vv[i0][j0][a] * (1 - fx) + Vv[i0 + 1][j0][a] * fx
        r1 = Vv[i0][j0 + 1][a] * (1 - fx) + Vv[i0 + 1][j0 + 1][a] * fx
        return r0 * (1 - fy) + r1 * fy

    choice: list = [None] * H
    for k in range(H - 1, -1, -1):
        h = hours[k]
        Vn = [[[0.0] * NA for _ in range(NE)] for _ in range(NT)]
        ch = [[[0] * NA for _ in range(NE)] for _ in range(NT)]
        for i in range(NT):
            T0 = t_lo + i * dT
            allowed = [a for a in range(NA) if sps[a] <= T0 + s.max_above_room or sps[a] <= s.day_min]
            for j in range(NE):
                E0 = j * dE
                base = {}
                for a in allowed:
                    T1, E1, c, _kwh, _q, pen = sim.hour(T0, E0, sps[a], h)
                    base[a] = c + pen + interp(V, T1, E1, a)
                best_a = min(base, key=base.get)
                best = base[best_a] + s.switch_cost
                row_v, row_c = Vn[i][j], ch[i][j]
                for prev in range(NA):
                    stay = base.get(prev)
                    if stay is not None and stay <= best:
                        row_v[prev], row_c[prev] = stay, prev
                    else:
                        row_v[prev], row_c[prev] = best, best_a
        V, choice[k] = Vn, ch

    # forward from the real state
    prev = min(range(NA), key=lambda a: abs(sps[a] - sp_now)) if sp_now is not None else NA // 2
    T, E = t_now, e_now
    out: list[HourPlan] = []
    total = kwh_tot = 0.0
    min_day = None
    R = min(report, H)
    for k in range(R):
        i = min(NT - 1, max(0, int(round((T - t_lo) / dT))))
        j = min(NE - 1, max(0, int(round(E / dE)))) if NE > 1 else 0
        a = choice[k][i][j][prev]
        T1, E1, c, e, q, _ = sim.hour(T, E, sps[a], hours[k])
        out.append(HourPlan(sps[a], T1, e, q, c, hours[k].p_grid))
        total += c
        kwh_tot += e
        if hours[k].day:
            min_day = T1 if min_day is None else min(min_day, T1)
        T, E, prev = T1, E1, a

    # the steady thermostat to compare with
    Tb, Eb, base_cost, base_kwh = t_now, e_now, 0.0, 0.0
    for h in hours[:R]:
        spb = s.comfort if (h.day or s.baseline_night is None) else s.baseline_night
        Tb, Eb, c, e, _q, _ = sim.hour(Tb, Eb, spb, h)
        base_cost += c
        base_kwh += e
    saving = base_cost - total + end_r(Tb, Eb) - end_r(T, E)
    return Plan(out, total, kwh_tot, base_cost, base_kwh, saving, min_day)


def explain(p: Plan, hours: list[HourIn], room: float, s: Settings) -> Reason:
    """One line on why the first hour is what it is."""
    if not p.hours:
        return Reason("no_plan")
    sp = p.first.sp
    prices = [h.p_grid for h in hours[:12]]
    now = hours[0].p_grid
    cheap = now <= sorted(prices)[len(prices) // 3]
    dear = now >= sorted(prices)[(2 * len(prices)) // 3]
    if hours[0].own_kw >= 0.5 and sp > s.comfort:
        return Reason("store_solar", {"sp": sp})
    if sp > s.comfort and cheap:
        return Reason("store_cheap", {"ct": round(now * 100, 1)})
    if sp < s.comfort and dear:
        return Reason("expensive", {"ct": round(now * 100, 1)})
    if sp <= room - 0.5:
        return Reason("warm_enough", {"room": round(room, 1)})
    return Reason("holding", {"sp": sp})


def replay_day(house: HouseModel, hp: HeatPumpModel, s: Settings, entries: list[dict]) -> tuple[float, float] | None:
    """Yesterday twice with the same model, weather and prices, from the same start: once with the setpoints Roost
    set (or would have set, in shadow mode), once with a steady thermostat. -> (cost with Roost, cost steady),
    each with the heat left at the end valued the same way."""
    if not entries:
        return None
    hours = [HourIn(t_out=e["t_out"], wind=e.get("wind", 3.5), rad=e.get("rad", 0.0), p_grid=e["p_grid"], p_own=e.get("p_own", e["p_grid"]),
                    own_kw=e.get("own", 0.0), day=e.get("day", True)) for e in entries]
    sim = Simulator(house, hp, s)
    end = _end_value(sim, hours, s.comfort)
    T0, E0 = entries[0]["T"], entries[0].get("E", 0.0)
    T, E, cost = T0, E0, 0.0
    for e, h in zip(entries, hours):
        T, E, c, *_ = sim.hour(T, E, float(e["sp"]), h)
        cost += c
    Tb, Eb, base = T0, E0, 0.0
    for h in hours:
        spb = s.comfort if (h.day or s.baseline_night is None) else s.baseline_night
        Tb, Eb, c, *_ = sim.hour(Tb, Eb, spb, h)
        base += c
    return cost - end(T, E), base - end(Tb, Eb)
