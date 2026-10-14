"""Combine the hourly sources into model rows. Pure Python.

Per hour, each value from the best source that has it:
- heat and electricity for space heating: the Weheat logs (imported) — the unit's own meters, no gaps when Home
  Assistant was off — else Home Assistant's long-term statistics of the Weheat energy sensors;
- seconds per state (heating / hot water / legionella / defrost / manual): the Weheat logs;
- room temperature: the room sensor chosen in Roost (HA statistics), else the thermostat's reading in the Weheat logs,
  else the thermostat's reading in HA;
- the heat pump's outdoor reading: Weheat logs, else HA statistics;
- outdoor temperature, radiation and wind: the weather service (forecast with past days, or the archive).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .model import WIND_REF, HourRow

BAD_LOW, BAD_HIGH = 0.5, 95.0          # Weheat reports -1 °C (and other nonsense) when a sensor fails


def _ts(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        return int(x / 1000 if x > 1e11 else x)
    if isinstance(v, datetime):
        return int((v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp())
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _temp(v: Any) -> float | None:
    x = _f(v)
    return x if x is not None and BAD_LOW < x < BAD_HIGH else None


def _outdoor(v: Any) -> float | None:
    x = _f(v)
    return x if x is not None and -45.0 < x < 50.0 and x != -1.0 else None


def weheat_hours(logs: list[dict], energy: list[dict]) -> dict[int, dict]:
    """Weheat hourly logs + energy logs -> {hour ts: {...}} (keys as in the API, camelCase)."""
    out: dict[int, dict] = {}
    for x in logs or []:
        t = _ts(x.get("timeBucket"))
        if t is None:
            continue
        t -= t % 3600
        out.setdefault(t, {}).update({
            "room": _temp(x.get("tRoomAverage")),
            "sensor_out": _outdoor(x.get("tAirInAverage")),
            "heating_s": (_f(x.get("heatPumpStateHeating")) or 0.0) + (_f(x.get("heatPumpStateHeatingDefrost")) or 0.0),
            "dhw_s": sum(_f(x.get(k)) or 0.0 for k in ("heatPumpStateDhw", "heatPumpStateLegionella", "heatPumpStateDhwDefrost")),
            "manual_s": _f(x.get("heatPumpStateManualControl")) or 0.0,
        })
    for x in energy or []:
        t = _ts(x.get("timeBucket"))
        if t is None:
            continue
        t -= t % 3600
        q = (_f(x.get("totalEOutHeating")) or 0.0) + (_f(x.get("totalEOutHeatingDefrost")) or 0.0)
        e = (_f(x.get("totalEInHeating")) or 0.0) + (_f(x.get("totalEInHeatingDefrost")) or 0.0)
        out.setdefault(t, {}).update({"q": max(0.0, q), "e": max(0.0, e),
                                      "dhw_e": (_f(x.get("totalEInDhw")) or 0.0) + (_f(x.get("totalEInDhwDefrost")) or 0.0)})
    return out


def build_rows(weheat: dict[int, dict], ha: dict[int, dict], weather: dict[int, tuple]) -> list[HourRow]:
    """ha: {hour ts: {"room", "thermostat_room", "q", "e", "dhw_e", "sensor_out"}} from long-term statistics.
    weather: {hour ts: (t_out, radiation kW/m², wind m/s)}."""
    rows: list[HourRow] = []
    for t in sorted(set(weheat) | set(ha)):
        w, h = weheat.get(t, {}), ha.get(t, {})
        wx = weather.get(t)
        if wx is None or wx[0] is None:
            continue
        room = h.get("room")
        if room is None:
            room = w.get("room") if w.get("room") is not None else h.get("thermostat_room")
        if room is None or not (BAD_LOW < room < BAD_HIGH):
            continue
        if "q" in w:
            q, e, dhw_e = w["q"], w.get("e", 0.0), w.get("dhw_e", 0.0)
        elif h.get("q") is not None:
            q, e, dhw_e = max(0.0, h["q"]), max(0.0, h.get("e") or 0.0), max(0.0, h.get("dhw_e") or 0.0)
        else:
            continue
        if w.get("manual_s", 0.0) > 600:               # someone ran the unit by hand: not normal operation
            continue
        dhw_s = w.get("dhw_s", 3600.0 if dhw_e > 0.05 else 0.0)
        rows.append(HourRow(ts=t, T=room, T_out=wx[0], Q=q, rad=max(0.0, wx[1] or 0.0), wind=wx[2] if wx[2] is not None else WIND_REF,
                            E=e, T_out_sensor=w.get("sensor_out") if w.get("sensor_out") is not None else h.get("sensor_out"),
                            dhw_s=dhw_s, heating_s=w.get("heating_s", 0.0)))          # seconds only known from the Weheat logs
    return rows
