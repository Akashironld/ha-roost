"""Setting up, a first plan, shadow and active mode, a manual change, diagnostics."""
from __future__ import annotations

import time

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant

from custom_components.roost.diagnostics import async_get_config_entry_diagnostics

from .conftest import THERMOSTAT, thermostat


def _plan_entity(hass: HomeAssistant) -> str:
    return next(s.entity_id for s in hass.states.async_all("sensor") if s.entity_id.endswith("planned_setpoint"))


async def test_setup_finds_the_weheat_sensors_and_plans(hass: HomeAssistant, entry) -> None:
    assert entry.state is ConfigEntryState.LOADED
    m = entry.runtime_data
    assert {"state", "heat", "elec", "outdoor", "water_setpoint"} <= set(m.ent)
    assert m.pump.source.startswith("profile p80")
    st = hass.states.get(_plan_entity(hass))
    assert st is not None and st.state not in ("unknown", "unavailable")
    assert len(st.attributes["plan"]) == 24
    assert hass.states.get("select.roost_mode").state == "shadow"


async def test_shadow_mode_never_touches_the_thermostat(hass: HomeAssistant, entry, climate_calls) -> None:
    m = entry.runtime_data
    await m._async_tick(None, force_plan=True)
    assert climate_calls == []


async def test_active_mode_sets_the_thermostat(hass: HomeAssistant, entry, climate_calls) -> None:
    m = entry.runtime_data
    thermostat(hass, target=18.0, room=20.6)            # far from any plan
    await m.async_set_mode("active")
    await hass.async_block_till_done()
    assert climate_calls, "no thermostat command in active mode"
    assert climate_calls[-1].data["entity_id"] == THERMOSTAT
    sent = len(climate_calls)
    await m._async_tick(None)
    assert len(climate_calls) == sent                   # at most one change per hour


async def test_manual_change_pauses(hass: HomeAssistant, entry, climate_calls) -> None:
    m = entry.runtime_data
    await m.async_set_mode("active")
    m.mem.last_write = time.time() - 3600
    hass.states.async_set(THERMOSTAT, "heat", {"temperature": 22.0, "current_temperature": 20.6}, context=Context())
    await hass.async_block_till_done()
    assert m.mem.pause_until and m.mem.pause_until > time.time()
    assert hass.states.get("binary_sensor.roost_paused_changed_by_hand").state == "on"


async def test_diagnostics_and_unload(hass: HomeAssistant, entry) -> None:
    d = await async_get_config_entry_diagnostics(hass, entry)
    assert d["mode"] == "shadow" and d["plan"] and d["weheat_entities"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
