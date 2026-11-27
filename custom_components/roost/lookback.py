"""Looking back: a day in numbers, from the hourly log. Pure Python.

The hourly log (manager.hour_log) holds per hour the room at its start, what the thermostat had and what Roost
planned, the reason, the room predicted for that hour 6 and 1 hours earlier, the heat and electricity of the hour and
its cost. The card's look back draws from it; this sums a day for the day report.
"""
from __future__ import annotations


def _r(v: float | None, n: int = 2) -> float | None:
    return None if v is None else round(v, n)


def measured(entries: list[dict], comfort: float) -> dict | None:
    """What the meters say, no model: the price paid per heating kWh against the same kWh spread like a steady
    thermostat (in proportion to each hour's heat loss, comfort - outdoor) on the same day, and where the electricity
    came from. own solar is worth what it would have earned exported (p_own); battery hours are counted at what the
    planner counted for them (p_grid: the battery's refill cost) against the tariff."""
    rows = [e for e in entries if (e.get("e") or 0.0) > 0.0 and e.get("t_out") is not None]
    kwh = sum(float(e["e"]) for e in rows)
    if kwh < 0.5:
        return None
    tariff: list[float] = [float(e["p_imp"]) if e.get("p_imp") is not None else float(e.get("p_grid") or 0.0) for e in entries]
    loss = [max(0.0, comfort - float(e["t_out"])) if e.get("t_out") is not None else 0.0 for e in entries]
    paid = sum((e.get("e") or 0.0) * p for e, p in zip(entries, tariff, strict=False))
    if sum(loss) <= 0:
        flat = paid
    else:
        flat = sum(w / sum(loss) * kwh * p for w, p in zip(loss, tariff, strict=False))
    sun = sum(e.get("e_sun") or 0.0 for e in entries)
    bat = sum(e.get("e_bat") or 0.0 for e in entries)
    sun_value = sum((e.get("e_sun") or 0.0) * max(0.0, p - float(e.get("p_own", p))) for e, p in zip(entries, tariff, strict=False))
    bat_value = sum((e.get("e_bat") or 0.0) * max(0.0, p - float(e.get("p_grid", p))) for e, p in zip(entries, tariff, strict=False))
    return {"kwh": _r(kwh), "paid": _r(paid, 3), "flat": _r(flat, 3), "timing": _r(flat - paid, 3),
            "ct_paid": _r(paid / kwh * 100, 1), "ct_flat": _r(flat / kwh * 100, 1),
            "sun_kwh": _r(sun), "bat_kwh": _r(bat), "sun_value": _r(sun_value, 3), "bat_value": _r(bat_value, 3)}


def month_measured(days: dict[str, dict], month: str) -> dict | None:
    """The measured parts of the days of a month (day_stats()["measured"]) added up."""
    ms = [d["measured"] for k, d in days.items() if k.startswith(month) and d.get("measured")]
    if not ms:
        return None
    out = {k: _r(sum(m.get(k) or 0.0 for m in ms), 3) for k in ("kwh", "paid", "flat", "timing", "sun_kwh", "bat_kwh",
                                                                  "sun_value", "bat_value")}
    kwh = out["kwh"] or 0.0
    paid, flat = out["paid"] or 0.0, out["flat"] or 0.0
    return {**out, "days": len(ms), "ct_paid": _r(paid / kwh * 100, 1) if kwh else None,
            "ct_flat": _r(flat / kwh * 100, 1) if kwh else None}


def day_stats(entries: list[dict], comfort: float, by_hand: int = 0, cost_replay: float | None = None,
              steady_replay: float | None = None) -> dict:
    """One day: electricity, heat, cost, comfort, thermostat changes and how well the plan predicted the room."""
    kwh = sum(e.get("e") or 0.0 for e in entries)
    heat = sum(e.get("q") or 0.0 for e in entries)
    cost = sum(e.get("cost") or 0.0 for e in entries)
    temps = [e["T"] for e in entries if e.get("T") is not None]
    day = [e for e in entries if e.get("day") and not e.get("away") and e.get("T") is not None]
    weight = lambda e: sum(e["comfort_mask"])/4 if e.get("comfort_mask") is not None else 1.0
    deficit = sum(max(0.0, comfort - e["T"])*weight(e) for e in day)
    below = sum(60*weight(e) for e in day if e["T"] < comfort - 0.3)
    sps = [sp for e in entries if (sp := e.get("sp_t")) is not None]
    changes = sum(1 for a, b in zip(sps, sps[1:], strict=False) if abs(a - b) >= 0.25)
    err = [e["T"] - e["p6"] for e in entries if e.get("p6") is not None and e.get("T") is not None]
    out = {"hours": len(entries), "kwh": _r(kwh), "heat_kwh": _r(heat), "cost": _r(cost, 3),
           "cop": _r(heat / kwh) if kwh > 0.5 else None, "deficit_ch": _r(deficit), "below_min": below,
           "low": _r(min(temps)) if temps else None, "changes": changes, "by_hand": by_hand,
           "pred_mae": _r(sum(abs(x) for x in err) / len(err)) if err else None,
           "pred_max": _r(max(err, key=abs)) if err else None, "pred_hours": len(err),
           "measured": measured(entries, comfort),
           # the replay below is Roost's plan in shadow mode: what it would have saved, not what it did
           "shadow": any(e.get("mode") == "shadow" for e in entries)}
    if cost_replay is not None and steady_replay is not None:
        out.update(saving=_r(steady_replay - cost_replay, 3), steady=_r(steady_replay, 3))
    return out
