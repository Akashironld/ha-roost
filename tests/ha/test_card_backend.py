"""What the renewed card reads beside the plan (cardstate.py): how the unit is controlled, the unit now, the header's
states and how the saving is worked out; and the two settings the card can change."""
import time
from dataclasses import replace

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.roost import control_detect as cd


def plan_sensor(hass):
    return next(s for s in hass.states.async_all("sensor") if s.entity_id.endswith("planned_setpoint"))


async def refresh(hass, m):
    await m._async_tick(None)
    await hass.async_block_till_done()
    return plan_sensor(hass).attributes


def add_on_device(hass, m, key, state, unit=None):
    """One more Weheat sensor on the heat pump's device (the fixture has only what Roost needed so far)."""
    reg = er.async_get(hass)
    any_ent = next(e for e in er.async_entries_for_device(reg, m.conf["heat_pump"]))
    ent = reg.async_get_or_create("sensor", "weheat", f"hp-1_{key}", config_entry=hass.config_entries.async_get_entry(any_ent.config_entry_id),
                                  device_id=m.conf["heat_pump"], translation_key=key, suggested_object_id=f"heat_pump_{key}")
    hass.states.async_set(ent.entity_id, state, {"unit_of_measurement": unit} if unit else {})
    return ent.entity_id


async def test_the_unit_idle_and_running(hass, entry):
    m = entry.runtime_data
    out = add_on_device(hass, m, "water_outlet_temperature", "31.0", "°C")
    inn = add_on_device(hass, m, "water_inlet_temperature", "27.5", "°C")
    m._resolve_weheat()
    a = await refresh(hass, m)
    assert a["pump"]["state"] == "idle" and a["pump"]["cop"] is None          # standby: no COP, never 0
    assert a["pump"]["supply"] == 31.0 and a["pump"]["return"] == 27.5 and a["pump"]["delta_t"] == 3.5
    hass.states.async_set(m.ent["state"], "heating")
    hass.states.async_set(m.ent["power_in"], "1200", {"unit_of_measurement": "W"})
    hass.states.async_set(m.ent["power_out"], "5400", {"unit_of_measurement": "W"})
    a = await refresh(hass, m)
    p = a["pump"]
    assert p["state"] == "heating" and p["in_kw"] == 1.2 and p["out_kw"] == 5.4 and p["cop"] == 4.5
    assert p["requested"] == 10.0          # what the thermostat asks for (ID 1), not the unit's own target
    hass.states.async_set(m.ent["state"], "dhw")
    assert (await refresh(hass, m))["pump"]["state"] == "hot_water"
    assert out and inn


async def test_without_the_unit_the_card_leaves_the_pump_out(hass, entry):
    m = entry.runtime_data
    hass.states.async_set(m.ent["state"], "unavailable")
    a = await refresh(hass, m)
    assert a["pump"] is None
    assert a["control_detected"] == cd.UNKNOWN and a["control_method"] is None and a["ot_available"] is False


async def test_the_reported_method_and_a_mismatch(hass, entry):
    m = entry.runtime_data
    m.card.cs = replace(m.card.cs, weheat_now={"method": 1, "dhw": 3, "at": "2026-11-17T17:00:00+01:00"})       # heating curve, as the unit reports
    a = await refresh(hass, m)
    assert a["control_method"] == "heating_curve" and a["control_reported_at"] and not a["control_mismatch"]
    now = time.time()
    m.card.steps.steps = [[now - 3600 * i, 0.02] for i in range(12)]                # does not follow: as it says
    assert not (await refresh(hass, m))["control_mismatch"]
    m.card.steps.steps = [[now - 3600 * i, 0.9] for i in range(12)]                 # follows: not what a curve does
    a = await refresh(hass, m)
    assert a["control_detected"] == cd.OPENTHERM and a["control_mismatch"]
    st = next(s for s in a["status"] if s["code"] == "control_mismatch")
    assert st["level"] == "amber" and st["args"] == {"setting": "heating_curve", "detected": "opentherm"}
    for code in (4, 2, 5):                                                     # smart, on/off, cloud: not checked
        m.card.cs = replace(m.card.cs, weheat_now={"method": code})
        assert not (await refresh(hass, m))["control_mismatch"]
    m.card.cs = replace(m.card.cs, weheat_now={})
    a = await refresh(hass, m)
    assert a["control_method"] is None and a["control_reported_at"] is None and not a["control_mismatch"]


async def test_steps_survive_a_restart(hass, entry):
    m = entry.runtime_data
    m.card.steps.steps = [[time.time() - 60, 0.05]]
    await m.async_save()
    data = await m._store.async_load()
    assert data["control_steps"]["steps"] == m.card.steps.steps


async def test_choosing_other_pump_entities(hass, entry):
    m = entry.runtime_data
    hass.states.async_set("sensor.my_supply", "35.5", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.my_power", "900", {"unit_of_measurement": "W"})
    own = dict(m.ent)
    await hass.services.async_call("roost", "set_settings", {"pump_entities": {"water_out": "sensor.my_supply",
                                                                               "power_in": "sensor.my_power"}}, blocking=True)
    assert m.card.card_ent == {"water_out": "sensor.my_supply", "power_in": "sensor.my_power"}
    assert m.ent == own                     # what Roost plans, counts and watches with stays as found
    a = await refresh(hass, m)
    assert a["pump"]["supply"] == 35.5 and a["pump"]["in_kw"] == 0.9
    await hass.services.async_call("roost", "set_settings", {"pump_entities": {"water_out": ""}}, blocking=True)
    assert m.card.card_ent == {"power_in": "sensor.my_power"} and m.ent == own
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("roost", "set_settings", {"pump_entities": {"elec": "sensor.my_supply"}}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("roost", "set_settings", {"pump_entities": {"water_out": "sensor.nope"}}, blocking=True)


async def test_header_states(hass, entry):
    m = entry.runtime_data
    a = await refresh(hass, m)
    assert not any(s["code"] == "weheat_missing" for s in a["status"])
    m.card.cs = replace(m.card.cs, weheat_seen=time.time() - 4 * 3600)
    hass.states.async_set(m.ent["state"], "unavailable")
    a = await refresh(hass, m)
    assert any(s["code"] == "weheat_missing" and s["level"] == "amber" for s in a["status"])
    await hass.services.async_call("roost", "pause", {"hours": 2}, blocking=True)
    a = await refresh(hass, m)
    paused = next(s for s in a["status"] if s["code"] == "paused")
    assert paused["level"] == "info" and paused["args"]["until"]
    codes = [s["code"] for s in a["status"]]
    assert codes.index("weheat_missing") < codes.index("paused")          # problems before information


async def test_saving_calc_adds_up_or_is_unknown(hass, entry):
    m = entry.runtime_data
    a = await refresh(hass, m)
    c = a["saving_calc"]
    if c is not None:
        assert c["saving"] == pytest.approx(c["steady"] - c["plan"] + c["end_steady"] - c["end_plan"], abs=0.01)
    m.held.plan.breakdown["quality"] = {**m.held.plan.breakdown.get("quality", {}), "valid": False}   # a fallback without prices
    assert m.card.saving_calc() is None                                                        # the card shows —, never 0


async def test_polling_the_method(hass, entry):
    from unittest.mock import patch
    m = entry.runtime_data
    with patch("custom_components.roost.weheat_api.async_latest", return_value={"currentControlMethod": 4, "dhwControlMethod": 3}):
        await m.card.async_poll_method()
    assert m.card.cs.weheat_now["method"] == 4 and m.card.cs.weheat_now["dhw"] == 3
    with patch("custom_components.roost.weheat_api.async_latest", return_value=None):
        await m.card.async_poll_method()
    assert m.card.cs.weheat_now["method"] == 4                                          # no answer: kept


async def test_the_method_is_asked_often_but_within_weheats_limit(hass, entry):
    from unittest.mock import patch
    from custom_components.roost import cardstate
    m = entry.runtime_data
    calls = []
    with patch.object(type(m), "spawn", lambda self, coro, name, background=True: (calls.append(name), coro.close())):
        t = time.time()
        m.card.cs, m.weheat.last["logs"] = replace(m.card.cs, method_at=t - cardstate.METHOD_POLL_S - 1), t - 300
        m.card.track(t)
        assert calls == ["weheat control method"]
        m.weheat.last["logs"] = t                                   # a log call just now (the refresh or this poll)
        m.card.cs = replace(m.card.cs, method_at=t - cardstate.METHOD_POLL_S - 1)
        m.card.track(t + 30)
        assert len(calls) == 1                                       # waits for Weheat's 2 minutes
        m.weheat.last["logs"] = t - 200
        m.card.cs = replace(m.card.cs, method_at=t - 150, pump_st="standby")
        hass.states.async_set(m.ent["state"], "heating")             # the unit changed state: ask again soon
        m.card.track(t + 40)
        assert len(calls) == 2


async def test_an_expired_weheat_login_shows_and_clears(hass, entry):
    from unittest.mock import patch
    from custom_components.roost.weheat_api import WeheatLoginNeeded
    m = entry.runtime_data
    with patch("custom_components.roost.weheat_api.async_latest", side_effect=WeheatLoginNeeded("400")):
        await m.card.async_poll_method()
    a = await refresh(hass, m)
    st = next(s for s in a["status"] if s["code"] == "weheat_login")
    assert st["level"] == "amber" and st["args"]["since"]
    with patch("custom_components.roost.weheat_api.async_latest", return_value={"currentControlMethod": 1}):
        await m.card.async_poll_method()                                   # logged in again: Weheat answers
    a = await refresh(hass, m)
    assert not any(s["code"] == "weheat_login" for s in a["status"]) and a["control_method"] == "heating_curve"


async def test_the_method_is_not_asked_while_an_import_runs(hass, entry):
    """The import uses Weheat's log quota: the card waits until it is done (core/shell ombouw, 24-11-2026: the check
    read an attribute that had moved, and so never waited)."""
    from unittest.mock import patch
    from custom_components.roost import cardstate
    m = entry.runtime_data
    calls = []
    with patch.object(type(m), "spawn", lambda self, coro, name, background=True: (calls.append(name), coro.close())):
        t = time.time()
        m.card.cs, m.weheat.last["logs"] = replace(m.card.cs, method_at=t - cardstate.METHOD_POLL_S - 1), t - 300
        m.wh.importing = True
        m.card.track(t)
        assert calls == []
        m.wh.importing = False
        m.card.track(t + 1)
        assert calls == ["weheat control method"]
