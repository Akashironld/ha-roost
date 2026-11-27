"""Defrosting the outdoor unit: how much of the heat it costs, by outdoor temperature and humidity. Pure Python.

Below a few degrees and in damp air the evaporator ices up; the unit then reverses for a quarter of an hour and takes
heat back from the house. Measured on the author's P80 (22-11-2026, 94 days of the Weheat's defrost meters, 12 days of
humidity): no defrost above ~5 °C or below ~80 % humidity; at 1-5 °C and >= 90 % about one per 7-8 hours heating,
~17 minutes and ~0.65 kWh of heat each; 5 % of the heat at 1-3 °C, 1.4 % at 3-5 °C.

The share of the heat lost:   share = a * max(0, T0 - t_out) * ramp(humidity),   ramp 0 at RH0 .. 1 at RH1, at most CAP.
`a` is learned from the hours with defrost data (learn); without humidity the planner assumes RH_UNKNOWN.
The COP model is learned on the heat before defrosting, and the planner takes the expected share off per hour, so a dry
hour at 2 °C is worth more than a foggy one (heatpump.HeatPumpModel.cop_net).
"""
from __future__ import annotations

T0 = 5.5            # °C: no defrosting above this
RH0, RH1 = 75.0, 95.0
CAP = 0.20
A_PRIOR = 0.015     # share per °C below T0 at high humidity: 5 % at 2 °C
RH_UNKNOWN = 88.0   # no humidity forecast: a damp Dutch winter hour
KWH_PER_DEFROST = 0.65
MIN_PER_DEFROST = 17.0
MIN_HOURS = 30      # cold heating hours with defrost data before `a` is learned
# Today's departure of the unit's own air sensor from the forecast. On a clear calm night the weather service can be
# several degrees colder than the air at the unit (23-11-2026: 4.5 K, Roost expected two defrosts, there was one). The
# usual difference is the learned sensor bias; what is left now lasts some hours (23-11, a week of hours: 0.84 of it an
# hour later, 0.65 after 3, 0.31 after 6), so it fades by ANOMALY_DECAY per hour. Defrosting only.
ANOMALY_DECAY = 0.85
ANOMALY_MAX = 4.0
ANOMALY_SUN = 0.05  # kW/m² of sun: above it the sensor reads the sun on it, no correction
PRIOR_HOURS = 40.0  # the prior counts as this many hours


def ramp(rh: float | None) -> float:
    r = RH_UNKNOWN if rh is None else rh
    return max(0.0, min(1.0, (r - RH0) / (RH1 - RH0)))


def share(t_out: float, rh: float | None, a: float = A_PRIOR) -> float:
    """Share of the heat (before defrosting) taken back by defrosting in this hour."""
    return min(CAP, max(0.0, a) * max(0.0, T0 - t_out) * ramp(rh))


def minutes(t_out: float, rh: float | None, heat_kwh: float, a: float = A_PRIOR) -> float:
    """Expected minutes of defrosting in an hour that makes heat_kwh of heat: for the card."""
    return share(t_out, rh, a) * max(0.0, heat_kwh) / KWH_PER_DEFROST * MIN_PER_DEFROST


def anomaly_ahead(sensor_now: float | None, forecast_now: float | None, bias: float, n: int) -> list[float]:
    """Per hour ahead (0 = now) the correction (K) to add to the forecast for defrosting: the unit's sensor minus its
    usual bias minus the forecast now, fading by ANOMALY_DECAY per hour. Zeros without a reading."""
    if sensor_now is None or forecast_now is None or not -30 < sensor_now < 45:
        return [0.0] * n
    d = max(-ANOMALY_MAX, min(ANOMALY_MAX, sensor_now - bias - forecast_now))
    return [round(d * ANOMALY_DECAY ** i, 2) for i in range(n)]


def air(t_out: float, t_sensor: float | None, bias: float, rad: float = 0.0) -> float:
    """The air at the unit in forecast terms for a past hour: its own sensor less the usual bias (the forecast when
    there is no reading, or sun on the sensor). What `learn` fits on, as the plan uses forecast + anomaly_ahead."""
    ok = t_sensor is not None and -30 < t_sensor < 45 and rad < ANOMALY_SUN
    return t_sensor - bias if ok and t_sensor is not None else t_out


def learn(rows, a_prev: float = A_PRIOR, bias: float = 0.0) -> tuple[float, int]:
    """`a` from hour rows (model.HourRow with Qd and rh): the defrost share of each cold heating hour against
    (T0 - t) * ramp(rh), a least-squares slope through zero, pulled towards the previous value. -> (a, hours used)."""
    sx = sy = 0.0
    n = 0
    for r in rows:
        t = air(r.T_out, r.T_out_sensor, bias, r.rad)
        if r.Qd is None or r.rh is None or r.Q < 0.5 or r.dhw_s > 600 or t >= T0:
            continue
        x = (T0 - t) * ramp(r.rh)
        if x <= 0:
            continue
        s = r.Qd / (r.Q + r.Qd)
        sx += x * x
        sy += x * s
        n += 1
    if n < MIN_HOURS or sx <= 0:
        return a_prev, n
    w = PRIOR_HOURS * (sx / n)                 # the prior as PRIOR_HOURS average hours
    a = (sy + w * a_prev) / (sx + w)
    return round(max(0.0, min(0.1, a)), 4), n
