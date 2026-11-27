"""What Roost learns about the heat pump for OpenTherm steering, from the unit's own measurements. Pure Python.

The settings (lowest output, extra electricity per start) are starting values: another make or model differs, so
Roost measures them from samples taken while the unit heats (every OBS_S, also in shadow mode, whoever steers):
heat out (kW), electricity in (kW), flow, room and outdoor temperature, and minutes since the start of the run.

- q_min      lowest steady output: a low percentile of the heat in steady running (≥ STEADY_MIN into a run). The
             lowest speed is where a unit spends long runs in mild weather, so it shows up there.
- k          emitter: median of heat / (flow − room)^n in steady running (n fixed by the kind of emitter).
- cop_low    no longer learned (22-11-2026): the measured output stood on both sides of the fit (selection bias), so
             the planner keeps its fixed ot_cop_low; the field stays for stored values.
- start_kwh  extra electricity of a start: per run, the electricity in the first START_MIN minus that heat at the
             run's steady COP.
- rest_min   how long the unit waited before starting again after it stopped while heat was still asked (a Weheat:
             ~60 min); shown, the planner's whole hours off cover up to 60.
Each is used once there are enough samples (MIN_*), else the setting stays.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .util import fill

OBS_S = 600                 # one sample per 10 min while heating
KEEP_S = 21 * 86400
STEADY_MIN = 25.0           # minutes into a run before a sample counts as steady (start peak, floor warming)
START_MIN = 20.0
MIN_STEADY = 72             # 12 hours of steady samples
MIN_STARTS = 3              # stops, for the rest after a stop
MIN_STARTS_KWH = 8          # starts, for the extra electricity of a start: a small number from a few starts swings (21-11:
                            # 0.0 from 4; 28 starts measured on the author's P80 give 0.03 kWh, the setting says 0.2)
Q_PCT = 0.10
Q_MIN_SHARE = 0.7           # a learned lowest output is used down to this share of the setting (otmgr.ot_q_min)
LIMITS = {"q_min": (0.5, 8.0), "k": (0.03, 3.0), "cop_low": (0.0, 1.0), "start_kwh": (0.0, 1.5), "n": (0.9, 1.6)}
N_SPREAD = 3.0              # °C: the flow above the room must vary this much in the samples to learn n


@dataclass
class OTLearned:
    q_min: float | None = None
    k: float | None = None
    n: float | None = None          # emitter exponent, when the flow varied enough to tell
    cop_low: float | None = None
    start_kwh: float | None = None
    rest_min: float | None = None
    steady: int = 0
    starts: int = 0

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "OTLearned":
        return fill(cls(), d)


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _clamp(key: str, v: float) -> float:
    lo, hi = LIMITS[key]
    return round(max(lo, min(hi, v)), 3)


def sample(ts: float, q_out: float | None, p_in: float | None, flow: float | None, room: float | None, t_out: float | None,
           run_min: float | None, asked: float) -> list | None:
    """One observation, or None when something is missing. asked: the flow asked then (0 = no demand)."""
    if q_out is None or p_in is None or run_min is None or q_out <= 0.1 or p_in <= 0.05:
        return None
    return [round(ts), round(q_out, 3), round(p_in, 3), None if flow is None else round(flow, 2),
            None if room is None else round(room, 2), None if t_out is None else round(t_out, 1), round(run_min, 1), asked]


def learn(obs: list[list], stops: list[list], hp, n: float) -> OTLearned:
    """obs: samples (sample()); stops: [stop ts, next start ts or None, heat asked meanwhile]; hp: the COP model."""
    out = OTLearned()
    steady = [o for o in obs if o[6] >= STEADY_MIN]
    out.steady = len(steady)
    if len(steady) >= MIN_STEADY:
        qs = sorted(o[1] for o in steady)
        out.q_min = _clamp("q_min", qs[int(len(qs) * Q_PCT)])
        pts = [(o[3] - o[4], o[1]) for o in steady if o[3] is not None and o[4] is not None and o[3] - o[4] >= 2.0]
        if len(pts) >= MIN_STEADY:
            dts = sorted(d for d, _ in pts)
            if dts[int(len(dts) * 0.9)] - dts[int(len(dts) * 0.1)] >= N_SPREAD:
                # log q = log k + n log(flow - room): the slope is n, when the flow varied enough
                xs = [math.log(d) for d, _ in pts]
                ys = [math.log(q) for _, q in pts]
                mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
                sxx = sum((x - mx) ** 2 for x in xs)
                if sxx > 0:
                    out.n = _clamp("n", sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx)
            nn = out.n or n
            out.k = _clamp("k", _median([q / d ** nn for d, q in pts]))
    # starts: runs are the samples between gaps; a run begins where run_min is small
    runs: list[list[list]] = []
    for o in sorted(obs):
        if not runs or o[6] < runs[-1][-1][6] or o[0] - runs[-1][-1][0] > 2 * OBS_S + 60:
            runs.append([])
        runs[-1].append(o)
    extra = []
    for r in runs:
        first = [o for o in r if o[6] < START_MIN]
        later = [o for o in r if o[6] >= STEADY_MIN]
        if not first or r[0][6] > OBS_S / 60 + 1 or len(later) < 3:
            continue                                 # the start itself not seen, or too short a run to compare
        cop = _median([o[1] / o[2] for o in later])
        dt = OBS_S / 3600
        extra.append(sum((o[2] - o[1] / cop) * dt for o in first))
    out.starts = len(extra)
    if len(extra) >= MIN_STARTS_KWH:
        out.start_kwh = _clamp("start_kwh", _median(extra))
    waits = [(b - a) / 60 for a, b, asked in stops if b is not None and asked]
    if len(waits) >= MIN_STARTS:
        out.rest_min = round(_median(waits))
    return out
