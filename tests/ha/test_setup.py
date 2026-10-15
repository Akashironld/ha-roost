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


async def test_without_a_weheat_login_it_asks_for_one(hass: HomeAssistant, entry) -> None:
    """Installed without a Weheat login (or from before 0.5.3): Home Assistant shows the re-authenticate notice."""
    flows = hass.config_entries.flow.async_progress_by_handler("roost")
    assert any(f["context"]["source"] == "reauth" for f in flows), flows


async def test_built_in_day_ahead_prices(hass: HomeAssistant, weheat: str, aioclient_mock, climate_calls) -> None:
    """Price mode 'epex': Roost fetches the day-ahead prices itself and plans with day-ahead × multiplier + amount."""
    from homeassistant.setup import async_setup_component
    from homeassistant.util import dt as dt_util

    from custom_components.roost import epex

    from .conftest import setup_roost

    t0 = int(dt_util.utcnow().timestamp() // 3600 * 3600) - 3600
    quarters = list(range(0, 48 * 4))
    aioclient_mock.get(epex.URL, json={"unix_seconds": [t0 + q * 900 for q in quarters],
                                       "price": [100.0 if (q // 4) % 2 else 300.0 for q in quarters], "unit": "EUR / MWh"})
    assert await async_setup_component(hass, "websocket_api", {})
    entry = await setup_roost(hass, weheat, options={"price_mode": "epex", "epex_zone": "NL", "import_mult": 1.21,
                                                     "import_add": 0.15})
    m = entry.runtime_data
    assert aioclient_mock.call_count == 1 and m.sources.get("epex") == "ok"
    assert m.sources.get("price") == "epex"
    tariff = [round(x, 4) for x in m.plan_tariff[:4]]
    assert set(tariff[1:]) <= {round(0.1 * 1.21 + 0.15, 4), round(0.3 * 1.21 + 0.15, 4)}, tariff


async def test_look_back_over_the_websocket(hass: HomeAssistant, entry) -> None:
    """The card's look back: roost/history for the planned-setpoint entity gives the hours, events and days. (The
    handler is called with a stand-in connection: the web server is a mock in these tests.)"""
    from custom_components.roost import _ws_history

    class Conn:
        def __init__(self) -> None:
            self.result, self.error = None, None

        def send_result(self, msg_id, result) -> None:
            self.result = result

        def send_error(self, msg_id, code, message) -> None:
            self.error = code

        def async_handle_exception(self, msg, err) -> None:
            raise err

    m = entry.runtime_data
    m.hour_log.append({"ts": int(time.time() // 3600 * 3600) - 3600, "T": 20.4, "sp_t": 20.5, "sp_plan": 20.5, "p6": 20.6,
                       "reason": "holding", "args": {}, "p_grid": 0.3, "q": 1.2, "day": True})
    ok = Conn()
    _ws_history(hass, ok, {"id": 1, "type": "roost/history", "entity_id": _plan_entity(hass), "days": 2})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert ok.result and ok.result["hours"][-1]["p6"] == 20.6 and "events" in ok.result and "days" in ok.result
    bad = Conn()
    _ws_history(hass, bad, {"id": 2, "type": "roost/history", "entity_id": "sensor.not_roost", "days": 7})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert bad.error == "not_found" and bad.result is None
