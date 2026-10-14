"""The setup screens."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import PRICE, THERMOSTAT

DOMAIN = "roost"


async def test_full_flow(hass: HomeAssistant, weheat: str) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": weheat, "thermostat": THERMOSTAT,
                                                                       "import_price": PRICE, "import_weheat_history": False})
    assert r["step_id"] == "energy"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"grid_sign": "import_positive", "weather_source": "open_meteo"})
    assert r["step_id"] == "comfort"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"day_from": 7, "day_to": 22, "comfort": 20.5, "day_min": 20.0,
                                                                       "night_min": 19.0, "store_max": 22.5, "max_above_room": 1.0,
                                                                       "min_interval": 60, "pause_hours": 2, "baseline_night": 0})
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["title"] == "Roost"
    assert r["data"]["heat_pump"] == weheat and r["data"]["thermostat"] == THERMOSTAT


async def test_not_a_weheat_device(hass: HomeAssistant, weheat: str) -> None:
    other = MockConfigEntry(domain="demo")
    other.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id, identifiers={("demo", "x")}, name="Not a heat pump")
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": dev.id, "thermostat": THERMOSTAT,
                                                                       "import_price": PRICE, "import_weheat_history": False})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"heat_pump": "not_weheat"}


async def test_comfort_checks(hass: HomeAssistant, weheat: str) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": weheat, "thermostat": THERMOSTAT,
                                                                       "import_price": PRICE, "import_weheat_history": False})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"grid_sign": "import_positive", "weather_source": "open_meteo"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"day_from": 7, "day_to": 22, "comfort": 19.5, "day_min": 20.0,
                                                                       "night_min": 19.0, "store_max": 19.0, "max_above_room": 1.0,
                                                                       "min_interval": 60, "pause_hours": 2, "baseline_night": 0})
    assert r["type"] is FlowResultType.FORM
    assert r["errors"] == {"comfort": "comfort_below_min", "store_max": "store_below_comfort"}
