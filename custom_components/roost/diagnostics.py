"""Diagnostics download for a bug report: everything needed to see what happened and to replay the plan.

Settings, versions, the state of every entity Roost reads, the learned models, the self-check, the inputs and the result
of the current plan, the last hours, what Roost did and why (its event log), and its last warnings and errors. Roost keeps
no passwords or tokens; the home location is left out.
"""
from __future__ import annotations

import re
import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from . import RoostConfigEntry, recent_log
from .const import WEHEAT
from .manager import HOUR_LOG_KEPT, PLAN_LOG_KEPT

REDACT = {"lat", "lon", "latitude", "longitude", "access_token", "refresh_token", "token"}
# the location inside text as well: a weather URL in an error, a log line ("latitude=52.1&longitude=5.1")
_LOC = re.compile(r"((?:lat|lon|latitude|longitude)=)-?\d+(?:\.\d+)?", re.IGNORECASE)


def _scrub(v: Any, numbers: tuple[str, ...]) -> Any:
    """Remove the home location from every text, however deep: query parameters and the coordinates themselves."""
    if isinstance(v, str):
        v = _LOC.sub(r"\1**REDACTED**", v)
        for n in numbers:
            v = v.replace(n, "**REDACTED**")
        return v
    if isinstance(v, dict):
        return {k: _scrub(x, numbers) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_scrub(x, numbers) for x in v]
    return v


def _state(hass: HomeAssistant, entity_id: str | None) -> dict | None:
    if not entity_id:
        return None
    st = hass.states.get(entity_id)
    if st is None:
        return {"entity_id": entity_id, "state": "missing"}
    a = st.attributes
    out = {"entity_id": entity_id, "state": st.state, "unit": a.get("unit_of_measurement"), "device_class": a.get("device_class"),
           "last_updated": st.last_updated.isoformat(), "attributes": sorted(a.keys())[:40]}
    if entity_id.startswith("climate."):
        out.update({k: a.get(k) for k in ("temperature", "current_temperature", "hvac_action", "hvac_modes", "min_temp", "max_temp")})
    return out


async def _version(hass: HomeAssistant, domain: str) -> str | None:
    try:
        integ = await async_get_integration(hass, domain)
    except Exception:  # noqa: BLE001
        return None
    return "built-in" if integ.is_built_in else str(integ.version)


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: RoostConfigEntry) -> dict[str, Any]:
    m = entry.runtime_data
    p = m.held.plan
    conf = m.conf
    entity_ids = sorted({v for k, v in conf.items() if isinstance(v, str) and "." in v and k != "name"} | set(m.ent.values())
                        | {r.sensor for r in m.rooms})
    data = {
        "versions": {"roost": await _version(hass, "roost"), "home_assistant": HA_VERSION, "weheat": await _version(hass, "weheat")},
        "settings": conf, "mode": m.mode, "heat_pump": m.pump_name, "weheat_entities": m.ent,
        "weheat_roles_missing": sorted(set(WEHEAT) - set(m.ent)),
        "entities": [_state(hass, e) for e in entity_ids],
        "now": {"room": m.room(), "thermostat_setpoint": m.thermostat_sp(), "thermostat_reading": m.thermostat_reading(),
                "pump_state": m.pump_state(), "storage_kwh": m.meters.storage_e, "following": m.notices.following, "sources": m.sources,
                "reason": m.reason.as_dict(), "decision": m.decision.as_dict() if m.decision else None, "control": m.mem.as_dict(),
                "correction_kw": m.corr_kw, "correction_hours": m.corr_n},
        "models": {"house": m.house.as_dict(), "heat_pump": m.pump.as_dict(),
                   "rooms": {k: v.as_dict() for k, v in m.room_models.items()}, "building": m.building},
        "learning": m.learn_info, "import": m.weheat.import_info,
        "heating_curve": m.curve_advice.as_dict() if m.curve_advice else None, "opentherm": m.otc.info() if m.ot else None, "weheat_settings": m.weheat.settings, "weheat_pump": m.weheat.pump, "hybrid": m.hybrid, "check": m.check, "ready_to_steer": m.ready, "still_missing": m.ready_missing, "ready_muted": m.ready_muted,
        "thermostat_writable": m.notices.thermostat_writable(), "following": m.notices.following_now(),
        "control": m.card.control_view(time.time()),
        "held": {"commit": m.held.commit.as_dict() if m.held.commit else None, "why": m.held.why, "fallback": m.held.fallback,
                 "unpriced_kwh_today": m.meters.unpriced_kwh},
        "plan": {"settings": vars(m.settings()), "control": vars(m.control_settings()),
                 "inputs": [vars(h) for h in m.held.hours], "hours": [h.as_dict() for h in p.hours] if p else None,
                 "tariff": m.held.tariff, "tariff_guessed": m.held.guess,
                 "cost": p.cost if p else None, "steady_cost": p.baseline_cost if p else None, "rooms": m.held.room_status},
        "hour_log": m.log.hour_log[-HOUR_LOG_KEPT:], "plan_log": m.log.plan_log[-PLAN_LOG_KEPT:], "saving_days": m.log.saving_days, "day_stats": m.log.day_stats,
        "day_contexts": m.log.day_contexts,
        "saving_explained": {"next_24h": m.hl.next_breakdown(), "days": m.log.saving_detail}, "plan_changes": m.log.plan_changes,
        "thermostat_history": {str(k): v for k, v in sorted(m.log.sp_hist.items())[-72:]},
        "rooms": [vars(r) for r in m.rooms], "changes_by_hand": m.changes[-40:],
        "suggestion": m.suggestion.as_dict() if m.suggestion else None, "issues": sorted(m.health.issues),
        "events": list(m.events), "log": list(recent_log(hass).records),
        "weheat_hours_imported": len(m.weheat.hours), "gas_boiler_hours": m.weheat.boiler_hours, "pv_k": m.pv_k, "load_profile": m.load_profile,
    }
    # the coordinates as Home Assistant has them, written out the ways a URL or message would (4+ decimals only: a
    # short number like 52.1 also occurs as a temperature or a price)
    numbers = tuple(sorted({f"{x:.{d}f}" for x in (hass.config.latitude, hass.config.longitude) if x
                            for d in (4, 5, 6)} | {repr(x) for x in (hass.config.latitude, hass.config.longitude)
                                                    if x and len(repr(x).split(".")[-1]) >= 4}, key=len, reverse=True))
    return _scrub(async_redact_data(data, REDACT), numbers)
