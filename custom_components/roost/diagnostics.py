"""Diagnostics download: settings, learned models, plan, sources, the last decisions (no secrets are kept by Roost)."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import RoostConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: RoostConfigEntry) -> dict[str, Any]:
    m = entry.runtime_data
    p = m.plan
    return {
        "settings": m.conf, "mode": m.mode, "weheat_entities": m.ent, "heat_pump": m.pump_name,
        "house_model": m.house.as_dict(), "heat_pump_model": m.pump.as_dict(), "learning": m.learn_info, "import": m.import_info,
        "sources": m.sources, "room": m.room(), "thermostat": m.thermostat_sp(), "storage_kwh": m.storage_e,
        "control": m.mem.as_dict(), "decision": m.decision.as_dict() if m.decision else None, "reason": m.reason.as_dict(),
        "plan": [h.as_dict() for h in p.hours] if p else None, "hours": [vars(h) for h in m.plan_hours],
        "saving_days": m.saving_days, "hour_log": m.hour_log[-30:], "weheat_hours_imported": len(m._weheat_hours),
        "pv_k": m.pv_k, "load_profile": m.load_profile, "following": m.following, "issues": sorted(m.health.issues),
    }
