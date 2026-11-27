"""Gouden toestand voor de verbouwing in modules (22-11-2026): Roost op een vaste tijd met vaste sensoren, en alles wat
het naar buiten laat zien (attributen van al zijn entiteiten en het diagnosebestand). Een verbouwing mag daar niets
aan veranderen.

  GOLDEN_OUT=pad.json pytest tests/ha/test_golden_state.py    schrijft de toestand
  GOLDEN_REF=pad.json pytest tests/ha/test_golden_state.py    vergelijkt met een eerder geschreven toestand
Zonder die variabelen draait de test alleen (Roost start en plant).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.roost.diagnostics import async_get_config_entry_diagnostics

from .conftest import prices, setup_roost

T0 = datetime(2026, 11, 20, 10, 7, 0, tzinfo=timezone.utc)
FLOW = "number.thrm_one_a1b2c3_flow_setpoint"
STATE = "sensor.thrm_one_a1b2c3_control_state"
MODE = "select.thrm_one_a1b2c3_control_mode"
ROOM = "sensor.living_room_temperature"


def _site(hass: HomeAssistant) -> None:
    hass.states.async_set(FLOW, "0.0", {"min": 0, "max": 45, "step": 0.5})
    hass.states.async_set(STATE, "home_assistant")
    hass.states.async_set(MODE, "Home Assistant", {"options": ["Home Assistant", "Heating curve"]})
    hass.states.async_set("number.thrm_one_a1b2c3_min_flow", "20.0", {"min": 10, "max": 40})
    hass.states.async_set("number.thrm_one_a1b2c3_max_flow", "40.0", {"min": 25, "max": 50})
    hass.states.async_set(ROOM, "20.3", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("sensor.pv", "1800", {"unit_of_measurement": "W", "device_class": "power"})
    hass.states.async_set("sensor.grid", "-900", {"unit_of_measurement": "W", "device_class": "power"})
    hass.states.async_set("sensor.soc", "42", {"unit_of_measurement": "%", "device_class": "battery"})
    hass.states.async_set("sensor.bat", "-300", {"unit_of_measurement": "W", "device_class": "power"})


def _clean(x):
    """Drop what depends on the wall clock of the test machine rather than on Roost (none expected with a frozen clock)."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in sorted(x.items()) if k not in ("uptime", "python", "last_updated", "last_changed", "last_reported")}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


async def _snapshot(hass: HomeAssistant, entry) -> dict:
    out = {}
    for st in sorted(hass.states.async_all(), key=lambda s: s.entity_id):
        if st.entity_id.split(".")[1].startswith("roost"):
            out[st.entity_id] = {"state": st.state, "attributes": dict(st.attributes)}
    diag = await async_get_config_entry_diagnostics(hass, entry)
    # what background tasks logged, in the order they happened to finish: not Roost's state
    out["diagnostics"] = {k: v for k, v in diag.items() if k not in ("events", "log")}
    text = json.dumps(out, default=str)
    # ids made afresh each run (device, config entries; the diagnostics hash them)
    ids = {entry.entry_id: "<entry>", entry.data["heat_pump"]: "<device>"}
    for k, v in ids.items():
        text = text.replace(k, v)
    snap = _clean(json.loads(text))
    snap["diagnostics"].get("settings", {}).pop("heat_pump", None)
    return snap


async def _run(hass: HomeAssistant, weheat: str, freezer, options: dict) -> dict:
    freezer.move_to(T0)
    prices(hass)
    _site(hass)
    assert await async_setup_component(hass, "websocket_api", {})
    entry = await setup_roost(hass, weheat, options)
    m = entry.runtime_data
    for _ in range(3):
        await m._async_tick(None)
        await hass.async_block_till_done()
    return await _snapshot(hass, entry)


def _compare(name: str, snap: dict) -> None:
    out, ref = os.environ.get("GOLDEN_OUT"), os.environ.get("GOLDEN_REF")
    if out:
        path = f"{out}.{name}.json"
        json.dump(snap, open(path, "w"), indent=1, sort_keys=True)
    if ref:
        want = json.load(open(f"{ref}.{name}.json"))
        assert snap == want, _first_diff(want, snap)


def _first_diff(a, b, path="") -> str:
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: only in one"
            d = _first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return ""
    return "" if a == b else f"{path}: {a!r} != {b!r}"


async def test_golden_thermostat(hass: HomeAssistant, weheat: str, climate_calls, freezer) -> None:
    snap = await _run(hass, weheat, freezer, {"pv_power": "sensor.pv", "grid_power": "sensor.grid"})
    assert snap["sensor.roost_planned_setpoint"]["state"] not in ("unknown", "unavailable")
    _compare("thermostat", snap)


async def test_golden_opentherm_with_solar_and_battery(hass: HomeAssistant, weheat: str, climate_calls, freezer) -> None:
    snap = await _run(hass, weheat, freezer, {
        "control": "opentherm", "ot_flow_setpoint": FLOW, "ot_control_state": STATE, "ot_control_mode": MODE,
        "room_temperature": ROOM, "pv_power": "sensor.pv", "grid_power": "sensor.grid",
        "battery_soc": "sensor.soc", "battery_power": "sensor.bat", "battery_kwh": 10.0, "solar_from_battery": 50})
    assert snap["sensor.roost_planned_setpoint"]["attributes"]["opentherm"]["control"] == "opentherm"
    _compare("opentherm", snap)


async def test_defrost_attributes(hass: HomeAssistant, weheat: str, climate_calls, freezer) -> None:
    """The card's defrost markers: minutes expected per plan hour, and the defrosts seen (none yet)."""
    snap = await _run(hass, weheat, freezer, {})
    a = snap["sensor.roost_planned_setpoint"]["attributes"]
    assert len(a["defrost_min"]) == len(a["plan"])
    assert all(isinstance(m, int) and m >= 0 for m in a["defrost_min"])
    assert a["defrost_seen"] == []
