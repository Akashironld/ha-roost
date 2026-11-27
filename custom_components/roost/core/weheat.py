"""What Roost keeps from Weheat: the unit's hours (its hourly and energy logs), the last call per kind (Weheat's
limits), its own settings and fixed data, and how far the import of its history got. Pure: the shell
(weheat_sync.py) talks to Weheat; these functions keep and plan."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from .. import history


@dataclass(frozen=True)
class Weheat:
    hours: dict[int, dict] = field(default_factory=dict)     # hour ts -> the unit's logs and energy (history store)
    # unix time of the last Weheat call per kind (its limits, over restarts). The one mutable part: weheat_api
    # records its calls in it as it makes them, also while an import runs
    last: dict[str, float] = field(default_factory=dict)
    settings: dict = field(default_factory=dict)             # the unit's own settings (control method, curve)
    pump: dict = field(default_factory=dict)                 # the unit's fixed data (weheat_api.async_pump_info)
    import_info: dict = field(default_factory=dict)          # the import of the history: how far, done
    boiler_hours: int = 0           # hours a gas boiler ran in the last year (history.boiler_hours; at start and save)

    # ------------------------------------------------------------ kept over restarts
    def stored(self) -> dict:
        """For the main store."""
        return {"import": self.import_info, "weheat_settings": self.settings, "weheat_pump": self.pump, "weheat_last": self.last}

    def stored_history(self) -> dict:
        """For the history store."""
        return {"weheat": {str(k): v for k, v in self.hours.items()}}

    @classmethod
    def restore(cls, data: dict, hist: dict, events: Any) -> Weheat:
        hours = {int(k): v for k, v in (hist.get("weheat") or {}).items()}
        return cls(hours=hours, last=data.get("weheat_last") or last_from_events(events),
                   settings=data.get("weheat_settings") or {}, pump=data.get("weheat_pump") or {},
                   import_info=data.get("import", {}), boiler_hours=history.boiler_hours(hours))


def last_from_events(events: Any) -> dict[str, float]:
    """The last Weheat call per kind, from the event log (stored by versions before weheat_last was kept)."""
    last: dict[str, float] = {}
    for e in events:
        if e.get("kind") == "weheat_call" and e.get("endpoint") in ("logs", "energy"):
            try:
                last[e["endpoint"]] = datetime.fromisoformat(e["t"]).timestamp()
            except (KeyError, TypeError, ValueError):
                pass
    return last


def merge(w: Weheat, rows: dict[int, dict]) -> Weheat:
    """Hours from Weheat added to the ones kept, field by field (history.merge_hours): reading the hourly logs alone
    (to add new fields) keeps the energy an hour already has."""
    hours = dict(w.hours)
    for t, v in rows.items():
        hours[t] = {**hours.get(t, {}), **v}
    return replace(w, hours=hours)


def prune(w: Weheat, cut: float) -> Weheat:
    """The hours from cut on, and the gas boiler hours counted again."""
    hours = {k: v for k, v in w.hours.items() if k >= cut}
    return replace(w, hours=hours, boiler_hours=history.boiler_hours(hours))


def hybrid(w: Weheat) -> bool:
    """A gas boiler next to the heat pump (history.is_hybrid)."""
    return history.is_hybrid(w.pump.get("boiler_type"), w.boiler_hours)


def energy_before(hours: dict[int, dict], ts: float) -> bool:
    """Most hours of the month before ts have their energy already (an import adding fields, not a first one)."""
    month = [v for t, v in hours.items() if ts - 31 * 86400 <= t < ts]
    return len(month) > 24 * 7 and sum(1 for v in month if "q" in v) > 0.8 * len(month)


@dataclass(frozen=True)
class ImportPlan:
    start: datetime
    end: datetime
    logs_only: bool
    info: dict              # import_info while it runs
    resumed: bool           # carrying on from an import a restart cut off


def plan_import(info: dict, hours: dict[int, dict], days: int, logs_only: bool, now_hour: datetime, fields: int) -> ImportPlan:
    """Which months to read: from now back `days`, or on from where an import cut off by a restart got (again from
    the newest when the update reads more fields: the months done lack them)."""
    prev = info if not info.get("done") and info.get("oldest") else None
    if prev and prev.get("fields_reading") != fields:
        # cut off by an update that reads more fields: the months done lack them, so start again from the newest;
        # the hourly logs only when the hours have their energy already
        logs_only = logs_only or energy_before(hours, datetime.fromisoformat(prev["oldest"]).timestamp())
        prev = None
    end = datetime.fromisoformat(prev["oldest"]) if prev else now_hour
    start = datetime.fromisoformat(prev["from"]) if prev else end - timedelta(days=days)
    if prev and not logs_only:
        # carrying on after a restart: logs only when it was, or when the older hours have their energy already
        logs_only = bool(prev.get("logs_only")) or energy_before(hours, end.timestamp())
    running = {"status": "importing", "from": start.isoformat(), "to": (prev or {}).get("to", end.isoformat()),
               "logs_only": logs_only, "fields_reading": fields,
               "oldest": end.isoformat(), "months_done": (prev or {}).get("months_done", 0),
               "months": max(1, round((end - start).days / 31) + (prev or {}).get("months_done", 0)),
               "hours": (prev or {}).get("hours", 0)}
    return ImportPlan(start, end, logs_only, running, bool(prev))


def month_done(info: dict, oldest: datetime, rows: int, at: str) -> dict:
    """import_info after one more month."""
    return {**info, "oldest": oldest.isoformat(), "months_done": info["months_done"] + 1, "hours": info["hours"] + rows, "at": at}


def import_done(info: dict, calls: int, fields: int, at: str, first_iso: Any) -> dict:
    """import_info once every month is in."""
    return {"status": "done", "done": True, "fields": fields, "hours": info["hours"], "calls": calls,
            "months": info["months_done"], "from": first_iso, "to": info["to"], "at": at}
