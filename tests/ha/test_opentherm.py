"""OpenTherm steering inside Home Assistant: an OpenTherm master (entities as the THRM ONE makes them), Roost in
shadow and in active mode, the lease, the control mode, the master's state, a change by hand, the options step."""
from __future__ import annotations

import time
from dataclasses import replace

from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.roost.diagnostics import async_get_config_entry_diagnostics

from .conftest import setup_roost

FLOW = "number.thrm_one_a1b2c3_flow_setpoint"
STATE = "sensor.thrm_one_a1b2c3_control_state"
MODE = "select.thrm_one_a1b2c3_control_mode"
MAXF = "sensor.thrm_one_a1b2c3_max_flow_limit_heat_pump"
ROOM = "sensor.living_room_temperature"
OT = {"control": "opentherm", "ot_flow_setpoint": FLOW, "ot_control_state": STATE, "ot_control_mode": MODE,
      "ot_max_flow_sensor": MAXF, "room_temperature": ROOM}


def master(hass: HomeAssistant, state: str = "curve", mode: str = "Heating curve", flow: float = 0.0) -> None:
    hass.states.async_set(FLOW, str(flow), {"min": 0, "max": 45, "step": 0.5})
    hass.states.async_set(STATE, state)
    hass.states.async_set(MODE, mode, {"options": ["Home Assistant", "Heating curve"]})
    hass.states.async_set(MAXF, "40", {"unit_of_measurement": "°C"})
    hass.states.async_set(ROOM, "20.3", {"unit_of_measurement": "°C", "device_class": "temperature"})


async def _setup(hass, weheat):
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, "websocket_api", {})
    master(hass)
    numbers = async_mock_service(hass, "number", "set_value")
    climate = async_mock_service(hass, "climate", "set_temperature")
    entry = await setup_roost(hass, weheat, OT)
    # after the setup: Roost's own select platform loads the select integration, which registers the real service
    selects = async_mock_service(hass, "select", "select_option")
    return entry, numbers, selects, climate


async def test_shadow_plans_flows_and_writes_nothing(hass: HomeAssistant, weheat: str) -> None:
    entry, numbers, selects, climate = await _setup(hass, weheat)
    m = entry.runtime_data
    assert m.ot and m.held.plan is not None
    assert all(h.level == 0 or h.level >= 2.8 for h in m.held.plan.hours)
    await m._async_tick(None)
    assert not numbers and not selects and not climate
    st = hass.states.get("sensor.roost_planned_setpoint")
    ot = st.attributes["opentherm"]
    assert ot["control"] == "opentherm" and len(ot["flows"]) == len(m.held.plan.hours)
    assert all(f == 0 or 20 <= f <= 40 for f in ot["flows"])
    assert st.attributes["plan"][0][0] == ot["flows"][0]
    d = await async_get_config_entry_diagnostics(hass, entry)
    assert d["opentherm"]["control"] == "opentherm"


async def test_active_sets_the_mode_and_keeps_the_lease(hass: HomeAssistant, weheat: str) -> None:
    entry, numbers, selects, climate = await _setup(hass, weheat)
    m = entry.runtime_data
    await m.async_set_mode("active")
    await hass.async_block_till_done()
    assert selects and selects[-1].data == {"entity_id": MODE, "option": "Home Assistant"}
    assert numbers and numbers[-1].data["entity_id"] == FLOW
    assert not climate                                  # no thermostat in OpenTherm mode
    n = len(numbers)
    await m._async_tick(None)                           # within 4 min, same value: nothing
    assert len(numbers) == n
    m.otc.mem.last_write = time.time() - 300             # the lease: written again, also when equal
    await m._async_tick(None)
    assert len(numbers) == n + 1
    # back to shadow: the master's own heating curve
    await m.async_set_mode("shadow")
    await hass.async_block_till_done()
    assert selects[-1].data == {"entity_id": MODE, "option": "Heating curve"}
    assert not climate


async def test_restart_does_not_switch_the_mode_again(hass: HomeAssistant, weheat: str) -> None:
    entry, numbers, selects, _ = await _setup(hass, weheat)
    m = entry.runtime_data
    await m.async_set_mode("active")
    await hass.async_block_till_done()
    n = len(selects)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data._async_tick(None)
    assert len(selects) == n


async def test_master_not_steered_is_a_notice(hass: HomeAssistant, weheat: str) -> None:
    from homeassistant.helpers import issue_registry as ir
    entry, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    await m.async_set_mode("active")
    hass.states.async_set(STATE, "curve_no_command")
    await m._async_tick(None)
    m.otc.mem.bad_since = time.time() - 400
    await m._async_tick(None)
    assert ir.async_get(hass).async_get_issue("roost", f"{entry.entry_id}_opentherm_fallback") is not None
    hass.states.async_set(STATE, "home_assistant")
    await m._async_tick(None)
    assert ir.async_get(hass).async_get_issue("roost", f"{entry.entry_id}_opentherm_fallback") is None


async def test_flow_changed_by_hand_pauses(hass: HomeAssistant, weheat: str) -> None:
    entry, numbers, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    await m.async_set_mode("active")
    await hass.async_block_till_done()
    hass.states.async_set(FLOW, "35.0", {"min": 0, "max": 45}, context=Context())
    await hass.async_block_till_done()
    assert m.mem.pause_until and m.mem.pause_until > time.time()
    n = len(numbers)
    m.otc.mem.last_write = time.time() - 600
    await m._async_tick(None)
    assert len(numbers) == n                            # paused: the master takes over after its timeout


async def test_options_step_finds_the_master(hass: HomeAssistant, weheat: str) -> None:
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, "websocket_api", {})
    master(hass)
    entry = await setup_roost(hass, weheat, {"room_temperature": ROOM})
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "opentherm"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "opentherm"
    block = next(v for k, v in r["data_schema"].schema.items() if str(k) == "ot_entities")   # the folded block
    found = {str(k): (k.description or {}).get("suggested_value") for k in block.schema.schema}
    assert found["ot_flow_setpoint"] == FLOW and found["ot_control_mode"] == MODE
    assert FLOW.split(".", 1)[1] in r["description_placeholders"]["found"] or "✓" in r["description_placeholders"]["found"]
    # OpenTherm without the master's entities: refused
    r2 = await hass.config_entries.options.async_configure(r["flow_id"], {"control": "opentherm"})
    assert r2["errors"] == {"base": "ot_entities"}
    r3 = await hass.config_entries.options.async_configure(r["flow_id"], {
        "control": "opentherm", "ot_entities": {"ot_flow_setpoint": FLOW, "ot_control_state": STATE, "ot_control_mode": MODE},
        "ot_limits": {"ot_min_flow": 20, "ot_max_flow": 40},
        "advanced": {"ot_state_ok": "home_assistant", "ot_mode_ha": "Home Assistant", "ot_mode_curve": "Heating curve",
                     "ot_q_min": 2.8, "ot_start_kwh": 0.2}})
    assert r3["type"] is FlowResultType.MENU
    await hass.async_block_till_done()
    assert entry.options["control"] == "opentherm" and entry.options["ot_flow_setpoint"] == FLOW


async def test_back_to_the_thermostat_puts_the_master_on_its_curve(hass: HomeAssistant, weheat: str) -> None:
    entry, numbers, selects, climate = await _setup(hass, weheat)
    await entry.runtime_data.async_set_mode("active")
    await hass.async_block_till_done()
    assert selects[-1].data["option"] == "Home Assistant"
    hass.config_entries.async_update_entry(entry, options={**entry.options, "control": "thermostat"})
    await hass.async_block_till_done()
    m = entry.runtime_data
    assert not m.ot
    await m._async_tick(None)
    assert selects[-1].data == {"entity_id": MODE, "option": "Heating curve"} and not m.otc.steering


async def test_steering_from_the_card(hass: HomeAssistant, weheat: str) -> None:
    import pytest
    from homeassistant.exceptions import ServiceValidationError
    entry, *_ = await _setup(hass, weheat)
    st = hass.states.get("sensor.roost_planned_setpoint")
    assert st.attributes["control"] == "opentherm" and st.attributes["control_choices"] == {"thermostat": True, "opentherm": True}
    await hass.services.async_call("roost", "set_settings", {"control": "thermostat"}, blocking=True)
    await hass.async_block_till_done()
    assert entry.options["control"] == "thermostat" and not entry.runtime_data.ot
    hass.config_entries.async_update_entry(entry, options={**entry.options, "ot_control_mode": None})
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("roost", "set_settings", {"control": "opentherm"}, blocking=True)


async def test_hot_water_is_not_taken_for_heating(hass: HomeAssistant, weheat: str) -> None:
    entry, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    m.ent["state"] = m.ent.get("state")
    hass.states.async_set(m.ent["state"], "dhw")
    await m._async_tick(None)
    assert m.otc.after_dhw(time.time()) and hass.states.get("sensor.roost_planned_setpoint").attributes["opentherm"]["hot_water"]
    hass.states.async_set(m.ent["state"], "heating")
    assert m.otc.after_dhw(time.time())            # still within the settling time
    assert not m.otc.after_dhw(time.time() + 1000)


async def test_opentherm_settings_from_the_card(hass: HomeAssistant, weheat: str) -> None:
    import pytest
    from homeassistant.exceptions import ServiceValidationError
    hass.states.async_set("number.thrm_one_a1b2c3_min_run_time", "20", {"min": 0, "max": 120})
    entry, *_ = await _setup(hass, weheat)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "ot_min_run_time": "number.thrm_one_a1b2c3_min_run_time"})
    await hass.async_block_till_done()
    m = entry.runtime_data
    assert m.otc.settings().min_run_s == 1200
    m.otc.obs = [[1, 2.0, 0.5, 30, 20, 5, 30, 30]]
    await hass.services.async_call("roost", "set_settings", {"ot_max_starts": 3, "ot_quiet": True, "ot_relearn": True}, blocking=True)
    await hass.async_block_till_done()
    assert entry.runtime_data is m                      # no reload
    assert m.conf["ot_max_starts"] == 3 and m.settings().ot_quiet == [22, 7, 2.8] and m.settings().ot_max_starts == 3
    assert m.otc.obs == []
    ot = hass.states.get("sensor.roost_planned_setpoint").attributes["opentherm"]
    assert ot["min_run"] == 20 and ot["max_starts"] == 3 and ot["quiet"] == [22, 7, 2.8]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("roost", "set_settings", {"ot_min_flow": 40, "ot_max_flow": 30}, blocking=True)


async def test_an_install_from_v082_switched_to_opentherm(hass: HomeAssistant, weheat: str, hass_storage) -> None:
    """Upgrading from v0.8.2: no OpenTherm state stored, a plan held with room setpoints. Switched to OpenTherm and
    active, Roost plans afresh in heat levels (never steering with the old setpoints as levels) and takes the master over."""
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.roost.const import STORAGE_VERSION
    from .conftest import PRICE, THERMOSTAT
    assert await async_setup_component(hass, "websocket_api", {})
    master(hass)
    numbers = async_mock_service(hass, "number", "set_value")
    t = int(time.time() // 3600 * 3600)
    hass_storage["roost.old082"] = {"version": STORAGE_VERSION, "key": "roost.old082", "data": {
        "mode": "active", "hour_log": [], "plan_log": [], "control": {"last_write": None, "last_sp": 20.5}, "storage_e": 1.0,
        "commit": {"at": t, "hour0": t, "sp": [21.5] * 36, "room0": 20.3, "t_end": [20.5] * 36, "t_out": [5.0] * 36,
                   "rad": [0.0] * 36, "tariff": [0.3] * 36}}}
    entry = MockConfigEntry(domain="roost", entry_id="old082", title="Roost", unique_id=weheat,
                            data={"heat_pump": weheat, "thermostat": THERMOSTAT, "import_price": PRICE,
                                  "import_weheat_history": False, "weather_source": "open_meteo"}, options=OT)
    entry.add_to_hass(hass)
    selects = async_mock_service(hass, "select", "select_option")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    m = entry.runtime_data
    assert m.ot and m.held.commit.kind == "level" and all(h.level == 0 or 2.8 <= h.level <= 8 for h in m.held.plan.hours)
    await m._async_tick(None)
    assert numbers and all(c.data["value"] == 0 or 20 <= c.data["value"] <= 40 for c in numbers)


async def test_the_heat_pump_cloud_gone(hass: HomeAssistant, weheat: str) -> None:
    """The Weheat sensors unavailable (cloud down): Roost keeps writing what the plan says, without measurements."""
    entry, numbers, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    await m.async_set_mode("active")
    for eid in list(m.ent.values()):
        hass.states.async_set(eid, "unavailable")
    m.otc.mem.last_write = time.time() - 600
    n = len(numbers)
    await m._async_tick(None)
    assert len(numbers) == n + 1 and m.otc.level_now() == 0.0


async def test_the_master_gone(hass: HomeAssistant, weheat: str) -> None:
    """The master unavailable: a notice after the grace time; writing goes on (it may come back)."""
    from homeassistant.helpers import issue_registry as ir
    entry, numbers, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    await m.async_set_mode("active")
    hass.states.async_set(STATE, "unavailable")
    hass.states.async_set(FLOW, "unavailable")
    await m._async_tick(None)
    m.otc.mem.bad_since = time.time() - 400
    await m._async_tick(None)
    issue = ir.async_get(hass).async_get_issue("roost", f"{entry.entry_id}_opentherm_fallback")
    assert issue is not None and issue.translation_placeholders["state"] == "unavailable"


async def test_restart_while_steering_writes_at_once(hass: HomeAssistant, weheat: str) -> None:
    """Home Assistant restarts while Roost steers: the master keeps the last request; Roost writes again at once."""
    entry, numbers, selects, _ = await _setup(hass, weheat)
    await entry.runtime_data.async_set_mode("active")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    m = entry.runtime_data
    assert m.otc.steering and len(selects) == 1           # the master's mode not switched again
    m.otc.mem.last_write = time.time() - 300              # the restart took 5 minutes
    n = len(numbers)
    await m._async_tick(None)
    assert len(numbers) == n + 1                          # written again in the first round


async def test_live_values_from_the_master_come_first(hass: HomeAssistant, weheat: str) -> None:
    """The master reads the unit at once; the Weheat cloud lags. Its flow counts only while the unit heats the house
    (a Weheat reports its central-heating side there, still during hot water)."""
    entry, *_ = await _setup(hass, weheat)
    hass.states.async_set("sensor.thrm_one_a1b2c3_flow_temperature", "31.5", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("binary_sensor.thrm_one_a1b2c3_heating_active", "on")
    hass.states.async_set("binary_sensor.thrm_one_a1b2c3_hot_water_active", "off")
    hass.config_entries.async_update_entry(entry, options={**entry.options,
        "ot_flow_temperature": "sensor.thrm_one_a1b2c3_flow_temperature",
        "ot_heating_active": "binary_sensor.thrm_one_a1b2c3_heating_active",
        "ot_hot_water_active": "binary_sensor.thrm_one_a1b2c3_hot_water_active"})
    await hass.async_block_till_done()
    m = entry.runtime_data
    hass.states.async_set(m.ent["state"], "standby")              # the cloud has not seen it yet
    assert m.otc.heating() and m.otc.flow_now(time.time()) == 31.5
    hass.states.async_set("binary_sensor.thrm_one_a1b2c3_hot_water_active", "on")
    assert not m.otc.heating() and m.otc.hot_water() and m.otc.after_dhw(time.time())
    assert m.otc.flow_now(time.time()) != 31.5                     # hot water: not the master's (still) CH side
    hass.states.async_set("binary_sensor.thrm_one_a1b2c3_heating_active", "unavailable")
    hass.states.async_set("binary_sensor.thrm_one_a1b2c3_hot_water_active", "unavailable")
    hass.states.async_set(m.ent["state"], "heating")
    assert m.otc.heating()                                          # the master gone: the Weheat state again


async def test_the_hour_logs_the_flow_the_unit_made(hass: HomeAssistant, weheat: str) -> None:
    """The card's look back sets what Roost would ask against what the heat pump made: each hour gets the flow
    measured while it heated (hot water left out), written when the hour has ended."""
    from datetime import datetime, timezone
    entry, *_ = await _setup(hass, weheat)
    hass.states.async_set("sensor.thrm_one_a1b2c3_flow_temperature", "31.5", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("binary_sensor.thrm_one_a1b2c3_heating_active", "on")
    hass.states.async_set("binary_sensor.thrm_one_a1b2c3_hot_water_active", "off")
    hass.config_entries.async_update_entry(entry, options={**entry.options,
        "ot_flow_temperature": "sensor.thrm_one_a1b2c3_flow_temperature",
        "ot_heating_active": "binary_sensor.thrm_one_a1b2c3_heating_active",
        "ot_hot_water_active": "binary_sensor.thrm_one_a1b2c3_hot_water_active"})
    await hass.async_block_till_done()
    m = entry.runtime_data
    await m._async_tick(None)
    hour = time.time() // 3600 * 3600
    assert m.otc.flow_acc[0] == hour and m.otc.flow_acc[2] >= 1
    assert abs(m.otc.flow_acc[1] / m.otc.flow_acc[2] - 31.5) < 1e-6
    m.log = replace(m.log, hour_log=[{"ts": int(hour)}])
    m.hl.log_hour(datetime.fromtimestamp(hour + 3600, tz=timezone.utc))
    assert m.log.hour_log[0]["flow_meas"] == 31.5
    m.otc.flow_acc = [0.0, 0.0, 0.0]               # nothing measured (hot water, standing still): no number
    m.log = replace(m.log, hour_log=[{"ts": int(hour)}])
    m.hl.log_hour(datetime.fromtimestamp(hour + 3600, tz=timezone.utc))
    assert "flow_meas" not in m.log.hour_log[0]


async def test_the_card_gets_the_masters_curve_and_how_far_learning_is(hass: HomeAssistant, weheat: str) -> None:
    """In shadow mode the master heats on its own curve: the card sets that curve's flow against what Roost would
    ask, and shows how far the learning from the unit has come."""
    from custom_components.roost import otlearn
    entry, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    assert m.otc.info()["curve_flow"] is None and m.otc.info()["curve_flow_entity"] is None   # no such sensor: nothing
    hass.states.async_set("sensor.thrm_one_a1b2c3_curve_flow", "29.625", {"unit_of_measurement": "°C"})
    info = m.otc.info()
    assert info["curve_flow"] == 29.625 and info["curve_flow_entity"] == "sensor.thrm_one_a1b2c3_curve_flow"
    assert info["learn_need"] == {"steady": otlearn.MIN_STEADY, "starts": otlearn.MIN_STARTS_KWH}
    await m._async_tick(None)
    assert hass.states.get("sensor.roost_planned_setpoint").attributes["opentherm"]["curve_flow"] == 29.625


async def test_the_indoor_unit_counts_in_todays_electricity_not_in_the_hour_log(hass: HomeAssistant, weheat: str) -> None:
    from datetime import datetime, timezone
    entry, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    assert m.ent.get("elec_indoor")
    now = datetime.now(timezone.utc)
    m._count_cost(now)
    k0, i0, acc0 = m.meters.kwh_today, m.meters.indoor_kwh_today, m.acc.elec
    hass.states.async_set(m.ent["elec_indoor"], "900.2", {"unit_of_measurement": "kWh"})
    m._count_cost(now)
    assert abs(m.meters.indoor_kwh_today - i0 - 0.2) < 1e-9 and abs(m.meters.kwh_today - k0 - 0.2) < 1e-9
    assert m.acc.elec == acc0                     # the hour log keeps the unit's own heating electricity
    hass.states.async_set(m.ent["elec_indoor"], "unavailable")
    m._count_cost(now)
    hass.states.async_set(m.ent["elec_indoor"], "900.3", {"unit_of_measurement": "kWh"})
    m._count_cost(now)
    assert abs(m.meters.indoor_kwh_today - i0 - 0.3) < 1e-9


async def test_the_box_owns_its_flow_limits(hass: HomeAssistant, weheat: str) -> None:
    # 22-11-2026, the author: the box guards the heat pump also without Roost, so its lowest/highest flow apply when it has
    # them (found next to its flow setpoint); another gateway keeps Roost's own settings
    entry, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    assert m.otc.flow_limits() == (20.0, 40.0) and m.otc.box_entity("ot_min_flow_number") is None
    hass.states.async_set("number.thrm_one_a1b2c3_min_flow", "22.0", {"min": 10, "max": 40})
    hass.states.async_set("number.thrm_one_a1b2c3_max_flow", "38.0", {"min": 25, "max": 50})
    assert m.otc.box_entity("ot_min_flow_number") == "number.thrm_one_a1b2c3_min_flow"
    assert m.otc.flow_limits() == (22.0, 38.0) and m.otc.settings().min_flow == 22.0 and m.otc.settings().max_flow == 38.0
    await m._async_tick(None)
    ot = hass.states.get("sensor.roost_planned_setpoint").attributes["opentherm"]
    assert ot["min_flow"] == 22.0 and ot["max_flow_entity"] == "number.thrm_one_a1b2c3_max_flow"
    hass.states.async_set("number.thrm_one_a1b2c3_max_flow", "15.0")      # nonsense on the box: Roost's own again
    assert m.otc.flow_limits() == (20.0, 40.0)


async def test_the_air_at_the_unit_only_when_live(hass: HomeAssistant, weheat: str, freezer) -> None:
    # 23-11-2026: the Weheat cloud was away for 47 minutes and kept its last outdoor value; the box reads the same
    # sensor over OpenTherm and kept going. A stale reading is not used; the box's is, when it has one
    entry, *_ = await _setup(hass, weheat)
    m = entry.runtime_data
    hass.states.async_set(m.ent["outdoor"], "7.5", {"unit_of_measurement": "°C"})
    assert m.unit_air_now() == 7.5
    freezer.tick(3600)                                   # the cloud is quiet for an hour
    assert m.unit_air_now() is None and m.otc.air_entity() is None     # no box reading: the forecast as it is
    hass.states.async_set("sensor.thrm_one_a1b2c3_air_inlet_temperature", "6.8", {"unit_of_measurement": "°C"})
    assert m.otc.air_entity() == "sensor.thrm_one_a1b2c3_air_inlet_temperature" and m.unit_air_now() == 6.8


async def test_the_plan_goes_to_the_box_for_when_roost_is_gone(hass: HomeAssistant, weheat: str) -> None:
    """THRM ONE 1.9.0: Roost sends its flows per hour and the outdoor temperature it planned with; once per new plan,
    else hourly; only while it steers; not at all when the box has no such action (older firmware)."""
    entry, numbers, selects, climate = await _setup(hass, weheat)
    m = entry.runtime_data
    await m._async_tick(None)
    assert m.otc.plan_service() is None and m.otc.plan_sent is None        # no action on the box: nothing
    sent = async_mock_service(hass, "esphome", "thrm_one_a1b2c3_set_plan")
    await m._async_tick(None)
    await m._async_tick(None)
    assert [c.data["flows"] for c in sent] == [[]]                         # shadow: once an empty plan, then nothing
    await m.async_set_mode("active")
    await hass.async_block_till_done()
    assert len(sent) == 2
    d = sent[1].data
    flows, i0 = m.otc.flows(), int(time.time() // 3600) - int(m.held.at // 3600)
    assert d["flows"] == flows[i0:i0 + 36] and len(d["outside"]) == len(d["flows"])
    assert d["outside"][0] == round(m.held.hours[i0].t_out + m.pump.bias + m.held.hours[i0].t_adj, 1)
    assert 0 <= d["sec_into_hour"] < 3600
    await m._async_tick(None)
    assert len(sent) == 2                                                   # the same plan within the hour: not again
    m.otc.plan_sent["t"] -= 3600
    await m._async_tick(None)
    assert len(sent) == 3                                                   # an hour later: again
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["opentherm"]["plan_service"] == "thrm_one_a1b2c3_set_plan" and diag["opentherm"]["plan_sent"]["hours"] == len(d["flows"])
    # the box restarted and lost the plan (it shows 0 hours): again at once, not after the hour
    left = "sensor.thrm_one_a1b2c3_plan_hours_left"
    hass.states.async_set(left, "12.5")
    m.otc.plan_sent["t"] -= 300
    await m._async_tick(None)
    assert len(sent) == 3                                                   # it has the plan: nothing
    hass.states.async_set(left, "0.0")
    await m._async_tick(None)
    assert len(sent) == 4 and sent[-1].data["flows"]
    await m._async_tick(None)
    assert len(sent) == 4                                                   # not again until it could have arrived
    # back to shadow: an empty plan once, so the box forgets it (a box set back to Home Assistant by hand runs no old plan)
    await m.async_set_mode("shadow")
    await hass.async_block_till_done()
    assert sent[-1].data == {"flows": [], "outside": [], "sec_into_hour": 0}
    n = len(sent)
    await m._async_tick(None)
    assert len(sent) == n                                                   # once


async def test_a_failing_plan_send_is_retried_after_ten_minutes(hass: HomeAssistant, weheat: str) -> None:
    """Review 26-11: a failing call is not repeated every tick, and again after 10 minutes (outage test 26-11)."""
    entry, numbers, selects, climate = await _setup(hass, weheat)
    m = entry.runtime_data
    calls = []

    async def broken(call):
        calls.append(call)
        raise RuntimeError("box gone")
    hass.services.async_register("esphome", "thrm_one_a1b2c3_set_plan", broken)
    await m.async_set_mode("active")
    await hass.async_block_till_done()
    assert len(calls) == 1 and m.otc.plan_sent["error"]
    await m._async_tick(None)
    await m._async_tick(None)
    assert len(calls) == 1                                                  # not at every tick
    assert numbers                                                          # steering went on
    m.otc.plan_sent["t"] -= 601
    await m._async_tick(None)
    assert len(calls) == 2                                                  # but within 10 minutes, not an hour


async def test_a_failing_clear_is_retried(hass: HomeAssistant, weheat: str) -> None:
    """Review 27-11: the box away when Roost stops steering: the empty plan again after 10 minutes, not never."""
    entry, numbers, selects, climate = await _setup(hass, weheat)
    m = entry.runtime_data
    calls, ok = [], [False]

    async def flaky(call):
        calls.append(call.data)
        if not ok[0]:
            raise RuntimeError("box gone")
    hass.services.async_register("esphome", "thrm_one_a1b2c3_set_plan", flaky)
    await m._async_tick(None)
    assert calls == [{"flows": [], "outside": [], "sec_into_hour": 0}] and not m.otc.plan_cleared
    await m._async_tick(None)
    assert len(calls) == 1                                                  # not at every tick
    m.otc.clear_failed_at -= 601
    ok[0] = True
    await m._async_tick(None)
    assert len(calls) == 2 and m.otc.plan_cleared                           # again after 10 minutes, and then done
    await m._async_tick(None)
    assert len(calls) == 2


async def test_removing_roost_clears_its_plan_on_the_box(hass: HomeAssistant, weheat: str) -> None:
    """Removed on purpose: the box must not run Roost's last plan when set back to Home Assistant later."""
    entry, numbers, selects, climate = await _setup(hass, weheat)
    sent = async_mock_service(hass, "esphome", "thrm_one_a1b2c3_set_plan")
    await entry.runtime_data.async_set_mode("active")
    await hass.async_block_till_done()
    assert sent and sent[-1].data["flows"]
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert sent[-1].data == {"flows": [], "outside": [], "sec_into_hour": 0}
    assert selects[-1].data["option"] == "Heating curve"
