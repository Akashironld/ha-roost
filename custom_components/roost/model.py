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

Sun: the radiation is the sun on the facade the windows face (sun.py), learned with the rest: every direction from east
to west, half and fully vertical, and plain global radiation are tried; the one that predicts the test days best wins.
Internal gains per hour of the day (cooking, people, and a thermostat that reads high in the sun): the mean error per
local hour after the fit, at half strength and at most 1 kW, kept only when it predicts the test days better.

Fit: the open-loop error of replaying every day from its measured start temperature, PLUS the daily energy balance
(measured heat against what the model needs to make the measured temperatures). Without the balance the storage C
comes out about twice too large and the predicted energy use is wrong (found on the author's data, 12-10-2026).
A pull towards the previous model keeps a few odd days from throwing it off. A new model is only adopted when it
predicts the last days at least as well as the previous one.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Callable

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
FACADES = (90.0, 135.0, 180.0, 225.0, 270.0)
VERTICAL = (0.5, 1.0)
PROFILE_SHRINK, PROFILE_CAP = 0.5, 1.0
# starting values by heat emitter (the data takes over): radiators hold little water and reach the room in minutes; the
# buffer is then the house itself (walls, furniture), smaller than a screed floor
EMITTER_PRIOR = {"floor": {"lag": 1.0, "C": 20.0}, "radiators": {"lag": 0.15, "C": 14.0}, "both": {"lag": 0.6, "C": 17.0}}
EMITTER_STORAGE = {"floor": 1.0, "radiators": 0.7, "both": 0.85}   # share of the floor-heating storage per m²


def starting_values(emitter: str, building_prior: dict | None) -> dict:
    """PRIOR adjusted for the heat emitter and (optional) the building register's heat loss and storage."""
    p = {**PRIOR, **EMITTER_PRIOR.get(emitter, EMITTER_PRIOR["floor"])}
    if building_prior:
        p["H"] = building_prior.get("H", p["H"])
        if "C" in building_prior:
            p["C"] = round(building_prior["C"] * EMITTER_STORAGE.get(emitter, 1.0), 1)
    return p


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
    sun_facade: float = 180.0             # direction the windows face (degrees from north)
    sun_vertical: float = 0.0             # 0: global radiation; 1: all on that facade
    profile: list[float] | None = None    # 24 extra internal gains (kW) per local hour

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

    def internal_at(self, hour: int) -> float:
        """Internal gain in this local hour (hour < 0: unknown, the constant only)."""
        if self.profile and 0 <= hour < 24:
            return self.internal + self.profile[hour]
        return self.internal

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
    hour: int = -1                # local hour of the day (-1: not known)


def within(p: dict) -> bool:
    return all(BOUNDS[k][0] <= p[k] <= BOUNDS[k][1] for k in PARAMS)


def replay(p: dict, idx: dict[int, HourRow], days: list[int], extra: Callable[[int], float] | None = None,
           weights: dict[int, float] | None = None) -> tuple[float, float, float, float]:
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
        wd = weights.get(d, 1.0) if weights else 1.0
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
            x = extra(t) if extra else 0.0
            T += (rel + g * u.rad + P + x - He * (T - u.T_out)) / C
            se += wd * (T - nx.T) ** 2
            n += wd
            q_meas += u.Q
            q_model += He * ((u.T + nx.T) / 2 - u.T_out) - g * u.rad - P - x
            t += 3600
        if whole and idx.get(t) is not None:
            sb += wd * ((q_model + C * (idx[t].T - T0) - q_meas) / 24) ** 2
            nb += wd
    return se, n, sb, nb


def errors(p: dict, idx: dict[int, HourRow], days: list[int], extra: Callable[[int], float] | None = None) -> tuple[float, float, float] | None:
    se, n, sb, nb = replay(p, idx, days, extra)
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


RECENT_HEATING_DAYS = 30     # these newest heating days count fully ...
HEATING_HALF_LIFE = 30.0     # ... older ones halve every this many heating days
NO_HEATING_WEIGHT = 0.25     # a day without heating (summer: windows open, high sun, the heat pump idle) counts less
CHANGED_BY = 0.15            # the newest heating days alone must predict this much better to replace the year's model


def recency_weights(idx: dict[int, HourRow], days: list[int], full: int = RECENT_HEATING_DAYS,
                    half_life: float = HEATING_HALF_LIFE) -> dict[int, float]:
    """Weight per day for learning. Counted in heating days, not calendar days, so a summer without heating does not
    age last winter: in autumn it still counts (there is little new heating yet), but once a new heating season runs it
    takes over (after insulating, a new window, …). Days without heating count a quarter once there are at least 20
    heating days: they say little about a house that is heated, and summer behaviour (open windows) misleads."""
    def heated(d: int) -> bool:
        return sum(idx[d * 86400 + h * 3600].Q for h in range(24) if d * 86400 + h * 3600 in idx) >= 5.0
    heating = sorted((d for d in days if heated(d)), reverse=True)
    damp = NO_HEATING_WEIGHT if len(heating) >= 20 else 1.0
    out = {}
    for d in days:
        newer = sum(1 for x in heating if x > d)
        w = 0.5 ** (max(0, newer - full) / half_life)
        out[d] = w if d in heating else w * damp
    return out


def recent_days(idx: dict[int, HourRow], days: list[int], n: int = RECENT_HEATING_DAYS) -> list[int]:
    """The days from the n-th newest heating day on: the house as it is now."""
    heating = sorted((d for d in days if sum(idx[d * 86400 + h * 3600].Q for h in range(24) if d * 86400 + h * 3600 in idx) >= 5.0),
                     reverse=True)
    if len(heating) < n:
        return []
    return [d for d in days if d >= heating[n - 1]]


def fit(idx: dict[int, HourRow], days: list[int], centre: dict, spread: dict = SPREAD, weights: dict[int, float] | None = None) -> dict:
    """Smallest replay error + balance error, with a pull towards `centre`."""
    def cost(x):
        p = dict(zip(PARAMS, x))
        if not within(p):
            return 1e12
        se, n, sb, nb = replay(p, idx, days, weights=weights)
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


def residual_profile(p: dict, idx: dict[int, HourRow], days: list[int], local_hour: Callable[[int], int]) -> list[float] | None:
    """Mean one-hour error of the model per local hour (kW), centred, at half strength, at most PROFILE_CAP."""
    C, H, g, lag, P, Hw = p["C"], p["H"], p["g"], p["lag"], p["internal"], p["Hw"]
    per: list[list[float]] = [[] for _ in range(24)]
    for d in days:
        E = 0.0
        for k in range(-6, 24):
            t = d * 86400 + k * 3600
            u, nx = idx.get(t), idx.get(t + 3600)
            if u is None or nx is None:
                E = 0.0
                continue
            He = max(0.02, H + Hw * (u.wind - WIND_REF))
            E += u.Q
            rel = E / (1 + lag)
            E -= rel
            if k >= 0:
                per[local_hour(t)].append(C * (nx.T - u.T) - (rel + g * u.rad + P - He * (u.T - u.T_out)))
    if any(len(x) < 5 for x in per):
        return None
    m = [sum(x) / len(x) for x in per]
    mean = sum(m) / 24
    return [round(max(-PROFILE_CAP, min(PROFILE_CAP, PROFILE_SHRINK * (v - mean))), 3) for v in m]


def learn(rows: list[HourRow], previous: HouseModel, eff: Callable[[int, float, float], float] | None = None,
          local_hour: Callable[[int], int] | None = None, prior: dict | None = None,
          facades: tuple[float, ...] | None = None) -> LearnResult:
    """eff(ts, facade, vertical): the sun on that facade in that hour (sun.effective), None: global radiation only.
    local_hour(ts): for the internal gains per hour of the day. prior: starting values that replace the generic house
    (building.prior). facades: the directions with an outside wall (building.facades; None: all)."""
    base = {**PRIOR, **(prior or {})}
    rows = [r for r in rows if 5.0 < r.T < 35.0 and -40.0 < r.T_out < 45.0 and r.Q >= 0]
    days = select_days(rows)
    if len(days) < 7 + TEST_DAYS:
        return LearnResult(previous, False, f"not enough complete days yet ({len(days)}, need {7 + TEST_DAYS})")
    train, test = days[:-TEST_DAYS], days[-TEST_DAYS:]
    centre = previous.params() if previous.source == "learned" else dict(base)
    wts = recency_weights({r.ts: r for r in rows}, days)
    cache: dict[tuple, dict[int, HourRow]] = {}

    def idx_for(facade: float, vertical: float) -> dict[int, HourRow]:
        key = (facade, vertical) if vertical > 0 and eff else (0.0, 0.0)
        if key not in cache:
            cache[key] = {r.ts: (replace(r, rad=eff(r.ts, *key)) if key[1] > 0 else r) for r in rows}
        return cache[key]

    def extra_for(profile: list[float] | None):
        return (lambda t: profile[local_hour(t)]) if profile and local_hour else None

    # the sun: global radiation, and (with direct/diffuse data) each facade direction, half and fully vertical. Chosen
    # on alternate weeks (learn on odd, test on even weeks): a few test days are too few to pick a direction
    odd = [d for d in days if (d // 7) % 2]
    even = [d for d in days if not (d // 7) % 2]
    sel_train, sel_test = (odd, even) if len(odd) >= 10 and len(even) >= 10 else (train, test)
    suns = [(180.0, 0.0)] + ([(f, v) for f in (FACADES if facades is None else facades) for v in VERTICAL] if eff else [])
    tried = []
    for f, v in suns:
        ix = idx_for(f, v)
        p = fit(ix, sel_train, centre, weights=wts) if len(suns) > 1 else None
        e = errors(p, ix, sel_test) if p and within(p) else None
        tried.append((e[2] if e else 1e9, f, v))
    _e, facade, vertical = min(tried, key=lambda x: x[0])
    candidate = fit(idx_for(facade, vertical), train, centre, weights=wts)
    ix_new = idx_for(facade, vertical)
    # the house as it is now: only the newest heating days. Wins when the house changed (insulation, new windows) and the
    # model over the whole year mixes the old and the new house; otherwise the model with more data wins the tie
    recent = [d for d in recent_days({r.ts: r for r in rows}, days) if d in set(train)]
    recent_p = fit(ix_new, recent, centre) if len(recent) >= 10 else None
    options = [("new", candidate, ix_new, None)] + ([("recent", recent_p, ix_new, None)] if recent_p else []) + [
               ("previous", previous.params(), idx_for(previous.sun_facade, previous.sun_vertical), previous.profile),
               ("default", dict(base), idx_for(180.0, 0.0), None)]
    scores = {}
    for name, p, ix, prof in options:
        e = errors(p, ix, test, extra_for(prof)) if within(p) else None
        if e:
            scores[name] = e
    if not scores:
        return LearnResult(previous, False, "no test data")
    if "recent" in scores and "new" in scores and scores["recent"][2] > scores["new"][2] * (1 - CHANGED_BY):
        del scores["recent"]          # not clearly better: a season, not a changed house (the year's model knows winter)
    best = min(v[2] for v in scores.values())
    choice = next(n for n, *_ in options if n in scores and scores[n][2] <= best + MARGIN)
    idx = ix_new
    heating = sum(1 for d in days if sum(idx[d * 86400 + h * 3600].Q for h in range(24) if d * 86400 + h * 3600 in idx) >= 5.0)
    rounded = {k: {"temperature": round(v[0], 3), "balance_kw": round(v[1], 3)} for k, v in scores.items()}
    rounded["sun"] = {f"{f:g}/{v:g}": round(e, 3) for e, f, v in tried if e < 1e9}
    rounded["sun_chosen"] = f"{facade:g}/{vertical:g}"
    if choice in ("new", "recent"):
        if choice == "recent":
            candidate = recent_p
            final = fit(idx, recent + [d for d in test if d not in recent], centre)
        else:
            final = fit(idx, days, centre, weights=wts)
        err = scores[choice]
        profile = None
        if local_hour:
            p_sel = fit(idx, sel_train, centre, weights=wts)
            prof = residual_profile(p_sel, idx, sel_train, local_hour)
            plain, with_prof = errors(p_sel, idx, sel_test), (errors(p_sel, idx, sel_test, extra_for(prof)) if prof else None)
            if plain and with_prof and with_prof[2] < plain[2]:
                profile = residual_profile(final, idx, days, local_hour)
                err = errors(final, idx, test, extra_for(profile)) or err
        m = HouseModel(**{k: round(v, 4) for k, v in final.items()}, error_t=round(err[0], 3),
                       error_balance=round(err[1], 3), days=len(days), heating_days=heating, source="learned",
                       sun_facade=facade, sun_vertical=vertical, profile=profile)
        return LearnResult(m, True, "new model adopted" + (" (from the newest heating days: the house changed)" if choice == "recent" else ""), rounded)
    keep = previous if choice == "previous" else HouseModel(**base)
    keep = HouseModel.from_dict({**keep.as_dict(), "error_t": round(scores[choice][0], 3), "error_balance": round(scores[choice][1], 3)})
    return LearnResult(keep, False, f"{choice} model predicts the last days better: kept", rounded)
