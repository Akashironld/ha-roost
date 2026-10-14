"""House model and learning it from hourly history. Pure Python (no Home Assistant imports).

Model per hour, the same shape the planner uses (validated on the author's house: a winter of Weheat data, 4,674 h,
4-fold cross-validation by week, and Home Assistant's own data):

    storage:  E += heat;  release = E / (1 + lag);  E -= release
    room:     T += (release + g * radiation + internal - (H + Hw * (wind - 3.5)) * (T - T_out)) / C

    C         heat storage of the house (kWh/K)
    H         heat loss at 3.5 m/s wind (kW/K)
    Hw        extra heat loss per m/s of wind (kW/K per m/s)
    g         solar gain (kW per kW/m² of global radiation: an effective window area in m²)
    internal  constant gain (kW; may be negative: ventilation, a cold ground floor)
    lag       mean time heat stays in the floor/water before it reaches the room (hours)

Fit: the open-loop error of replaying every day from its measured start temperature, PLUS the daily energy balance
(measured heat against what the model needs to make the measured temperatures). Without the balance the storage C
comes out about twice too large and the predicted energy use is wrong (found on the author's data, 12-10-2026).
A pull towards the previous model keeps a few odd days from throwing it off. A new model is only adopted when it
predicts the last days at least as well as the previous one.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

WIND_REF = 3.5
PARAMS = ("C", "H", "g", "lag", "internal", "Hw")
BOUNDS = {"C": (4.0, 80.0), "H": (0.04, 0.6), "g": (0.0, 15.0), "lag": (0.0, 6.0), "internal": (-0.6, 1.2), "Hw": (-0.02, 0.06)}
# a well-insulated house with floor heating; wide spread: data takes over quickly
PRIOR = {"C": 20.0, "H": 0.14, "g": 4.0, "lag": 1.0, "internal": 0.0, "Hw": 0.006}
SPREAD = {"C": 10.0, "H": 0.08, "g": 3.0, "lag": 0.8, "internal": 0.25, "Hw": 0.006}
SIGMA_T = 0.7        # typical open-loop error per hour (°C); errors within a day are related: a day counts as ~1 observation
SIGMA_BAL = 0.4      # typical daily energy-balance error (kW average)
TEST_DAYS = 3
MARGIN = 0.03        # within this, prefer the model with more evidence behind it


@dataclass
class HouseModel:
    C: float = PRIOR["C"]
    H: float = PRIOR["H"]
    g: float = PRIOR["g"]
    lag: float = PRIOR["lag"]
    internal: float = PRIOR["internal"]
    Hw: float = PRIOR["Hw"]
    error_t: float | None = None          # °C, replay error on the test days
    error_balance: float | None = None    # kW, daily balance error on the test days
    days: int = 0
    heating_days: int = 0
    source: str = "default"

    def params(self) -> dict:
        return {k: getattr(self, k) for k in PARAMS}

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "HouseModel":
        m = cls()
        for k, v in (d or {}).items():
            if hasattr(m, k):
                setattr(m, k, v)
        return m

    def loss(self, wind: float) -> float:
        return max(0.02, self.H + self.Hw * (wind - WIND_REF))

    @property
    def time_constant_h(self) -> float:
        return self.C / self.H if self.H > 0 else float("inf")


@dataclass
class HourRow:
    """One hour of history."""
    ts: int                       # start of the hour, epoch seconds
    T: float                      # room temperature (mean)
    T_out: float                  # outdoor temperature (weather service)
    Q: float                      # heat into the house for space heating (kWh, defrost taken off)
    rad: float = 0.0              # global radiation (kW/m²)
    wind: float = WIND_REF        # m/s at 10 m
    E: float = 0.0                # electricity for space heating (kWh)
    T_out_sensor: float | None = None   # the heat pump's own outdoor reading
    dhw_s: float = 0.0            # seconds of hot water / legionella in the hour
    heating_s: float = 0.0        # seconds of space heating in the hour
    sp: float | None = None       # room setpoint on the thermostat (mean over the hour)
    T_th: float | None = None     # the thermostat's own room reading
    room_sensor: bool = False     # T comes from a separate room sensor (not the thermostat)


def within(p: dict) -> bool:
    return all(BOUNDS[k][0] <= p[k] <= BOUNDS[k][1] for k in PARAMS)


def replay(p: dict, idx: dict[int, HourRow], days: list[int]) -> tuple[float, int, float, int]:
    """Per day from 00:00 UTC: start at the measured room temperature, warm the storage up with the 6 hours before,
    then 24 hours with only heat, sun, wind and outdoor temperature. Also the energy balance per day.
    -> (sum of squared °C errors, hours, sum of squared daily balance errors in kW, days)"""
    C, H, g, lag, P, Hw = p["C"], p["H"], p["g"], p["lag"], p["internal"], p["Hw"]
    se = sb = 0.0
    n = nb = 0
    for d in days:
        t = d * 86400
        r0 = idx.get(t)
        if r0 is None:
            continue
        T, E = r0.T, 0.0
        T0, q_meas, q_model, whole = T, 0.0, 0.0, True
        for k in range(6, 0, -1):
            q = idx.get(t - 3600 * k)
            if q:
                E += q.Q
                E -= E / (1 + lag)
        for _ in range(24):
            u, nx = idx.get(t), idx.get(t + 3600)
            if u is None or nx is None:
                whole = False
                break
            He = max(0.02, H + Hw * (u.wind - WIND_REF))
            E += u.Q
            rel = E / (1 + lag)
            E -= rel
            T += (rel + g * u.rad + P - He * (T - u.T_out)) / C
            se += (T - nx.T) ** 2
            n += 1
            q_meas += u.Q
            q_model += He * ((u.T + nx.T) / 2 - u.T_out) - g * u.rad - P
            t += 3600
        if whole and idx.get(t) is not None:
            sb += ((q_model + C * (idx[t].T - T0) - q_meas) / 24) ** 2
            nb += 1
    return se, n, sb, nb


def errors(p: dict, idx: dict[int, HourRow], days: list[int]) -> tuple[float, float, float] | None:
    se, n, sb, nb = replay(p, idx, days)
    if not n or not nb:
        return None
    a, b = math.sqrt(se / n), math.sqrt(sb / nb)
    return a, b, math.hypot(a, b)


def nelder_mead(f, x0: list[float], step: list[float], iterations: int = 300) -> list[float]:
    n = len(x0)
    pts = [list(x0)] + [[x0[j] + (step[i] if j == i else 0.0) for j in range(n)] for i in range(n)]
    vals = [f(x) for x in pts]
    for _ in range(iterations):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        c = [sum(pts[i][j] for i in range(n)) / n for j in range(n)]
        xr = [c[j] + (c[j] - pts[n][j]) for j in range(n)]
        fr = f(xr)
        if fr < vals[0]:
            xe = [c[j] + 2 * (c[j] - pts[n][j]) for j in range(n)]
            fe = f(xe)
            pts[n], vals[n] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[n - 1]:
            pts[n], vals[n] = xr, fr
        else:
            xc = [c[j] + 0.5 * (pts[n][j] - c[j]) for j in range(n)]
            fc = f(xc)
            if fc < vals[n]:
                pts[n], vals[n] = xc, fc
            else:
                for i in range(1, n + 1):
                    pts[i] = [pts[0][j] + 0.5 * (pts[i][j] - pts[0][j]) for j in range(n)]
                    vals[i] = f(pts[i])
    return pts[0]


def fit(idx: dict[int, HourRow], days: list[int], centre: dict, spread: dict = SPREAD) -> dict:
    """Smallest replay error + balance error, with a pull towards `centre`."""
    def cost(x):
        p = dict(zip(PARAMS, x))
        if not within(p):
            return 1e12
        se, n, sb, nb = replay(p, idx, days)
        if n == 0:
            return 1e12
        return se / (SIGMA_T ** 2 * 24) + sb / SIGMA_BAL ** 2 + sum(((p[k] - centre[k]) / spread[k]) ** 2 for k in PARAMS)
    x = nelder_mead(cost, [centre[k] for k in PARAMS], [spread[k] * 0.5 for k in PARAMS])
    return dict(zip(PARAMS, x))


def select_days(rows: list[HourRow], recent_days: int = 60, heating_days: int = 120) -> list[int]:
    """Complete days only (≥ 23 hours): all recent days, plus the most recent heating days before them, so a winter
    learned once stays in the model when summer comes."""
    per: dict[int, list[HourRow]] = {}
    for r in rows:
        per.setdefault(r.ts // 86400, []).append(r)
    full = sorted(d for d, rs in per.items() if len(rs) >= 23)
    if not full:
        return []
    last = full[-1]
    recent = [d for d in full if d > last - recent_days]
    older_heating = [d for d in full if d <= last - recent_days and sum(r.Q for r in per[d]) >= 5.0]
    return sorted(set(recent + older_heating[-heating_days:]))


@dataclass
class LearnResult:
    model: HouseModel
    adopted: bool
    reason: str
    scores: dict = field(default_factory=dict)


def learn(rows: list[HourRow], previous: HouseModel) -> LearnResult:
    rows = [r for r in rows if 5.0 < r.T < 35.0 and -40.0 < r.T_out < 45.0 and r.Q >= 0]
    idx = {r.ts: r for r in rows}
    days = select_days(rows)
    if len(days) < 7 + TEST_DAYS:
        return LearnResult(previous, False, f"not enough complete days yet ({len(days)}, need {7 + TEST_DAYS})")
    train, test = days[:-TEST_DAYS], days[-TEST_DAYS:]
    centre = previous.params() if previous.source == "learned" else dict(PRIOR)
    candidate = fit(idx, train, centre)
    options = [("new", candidate), ("previous", previous.params()), ("default", dict(PRIOR))]
    scores = {}
    for name, p in options:
        e = errors(p, idx, test) if within(p) else None
        if e:
            scores[name] = e
    if not scores:
        return LearnResult(previous, False, "no test data")
    best = min(v[2] for v in scores.values())
    choice = next(n for n, _ in options if n in scores and scores[n][2] <= best + MARGIN)
    heating = sum(1 for d in days if sum(idx[d * 86400 + h * 3600].Q for h in range(24) if d * 86400 + h * 3600 in idx) >= 5.0)
    rounded = {k: {"temperature": round(v[0], 3), "balance_kw": round(v[1], 3)} for k, v in scores.items()}
    if choice == "new":
        final = fit(idx, days, centre)
        m = HouseModel(**{k: round(v, 4) for k, v in final.items()}, error_t=round(scores["new"][0], 3),
                       error_balance=round(scores["new"][1], 3), days=len(days), heating_days=heating, source="learned")
        return LearnResult(m, True, "new model adopted", rounded)
    keep = previous if choice == "previous" else HouseModel()
    keep = HouseModel.from_dict({**keep.as_dict(), "error_t": round(scores[choice][0], 3), "error_balance": round(scores[choice][1], 3)})
    return LearnResult(keep, False, f"{choice} model predicts the last days better: kept", rounded)
