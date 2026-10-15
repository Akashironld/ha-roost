"""The setup screens: by subject, with the regulation folded away, and the options menu."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow, device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import PRICE, THERMOSTAT

DOMAIN = "roost"
COMFORT = {"day_from": 7, "day_to": 22, "comfort": 20.5, "day_min": 20.0, "night_min": 19.0, "store_max": 22.5,
           "advanced": {"lowest_setpoint": 19.0, "max_above_room": 1.0, "min_interval": 60, "pause_hours": 2,
                        "baseline_night": 0, "weather_source": "open_meteo"}}


async def _to_comfort(hass: HomeAssistant, weheat: str, solar: bool = False) -> dict:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": weheat, "thermostat": THERMOSTAT,
                                                                       "import_weheat_history": False})
    assert r["step_id"] == "house"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"emitter": "floor", "use_bag": False})
    assert r["step_id"] == "price"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"price_mode": "sensor", "import_price": PRICE})
    assert r["step_id"] == "solar"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"has_solar": solar, "has_battery": False})
    if solar:
        assert r["step_id"] == "solar_details"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"grid_sign": "import_positive"})
    assert r["step_id"] == "comfort"
    return r


async def test_full_flow(hass: HomeAssistant, weheat: str) -> None:
    r = await _to_comfort(hass, weheat, solar=True)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], COMFORT)
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["title"] == "Roost"
    d = r["data"]
    assert d["heat_pump"] == weheat and d["thermostat"] == THERMOSTAT and d["import_price"] == PRICE
    assert d["max_above_room"] == 1.0 and "advanced" not in d                # the section is stored flat


async def test_fixed_price(hass: HomeAssistant, weheat: str) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": weheat, "thermostat": THERMOSTAT,
                                                                       "import_weheat_history": False})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"emitter": "radiators", "use_bag": False})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"price_mode": "sensor"})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"import_price": "price_needed"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"price_mode": "fixed"})
    assert r["step_id"] == "price_fixed"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"fixed_price": 0.30, "fixed_low_price": 0.25, "low_from": 23,
                                                                       "low_to": 7, "low_weekend": True})
    assert r["step_id"] == "solar"


async def test_not_a_weheat_device(hass: HomeAssistant, weheat: str) -> None:
    other = MockConfigEntry(domain="demo")
    other.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id, identifiers={("demo", "x")}, name="Not a heat pump")
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": dev.id, "thermostat": THERMOSTAT,
                                                                       "import_weheat_history": False})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"heat_pump": "not_weheat"}


async def test_comfort_checks(hass: HomeAssistant, weheat: str) -> None:
    r = await _to_comfort(hass, weheat)
    bad = {**COMFORT, "comfort": 19.5, "store_max": 19.0}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], bad)
    assert r["type"] is FlowResultType.FORM
    assert r["errors"] == {"comfort": "comfort_below_min", "store_max": "store_below_comfort"}


async def test_options_menu_saves_each_part(hass: HomeAssistant, entry) -> None:
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.MENU and r["menu_options"] == ["mode", "house", "price", "solar", "comfort"]
    assert "comfort" in r["description_placeholders"]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**COMFORT, "comfort": 21.0, "store_max": 23.0})
    assert r["type"] is FlowResultType.CREATE_ENTRY and entry.options["comfort"] == 21.0


async def test_reconfigure_weheat_login(hass: HomeAssistant, entry) -> None:
    """Reconfigure → Weheat login: the Weheat integration's (default), or Roost's own, which needs application
    credentials first (Home Assistant then offers to add them)."""
    assert await async_setup_component(hass, "application_credentials", {})
    r = await entry.start_reconfigure_flow(hass)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "reconfigure"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"weheat_auth": "own"})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "missing_credentials"
    r = await entry.start_reconfigure_flow(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"weheat_auth": "integration"})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "reconfigure_successful"
    assert entry.data["weheat_auth"] == "integration" and "token" not in entry.data
    assert entry.data["thermostat"] == THERMOSTAT                       # the rest of the setup is kept


async def test_options_never_copy_the_weheat_login(hass: HomeAssistant, entry) -> None:
    hass.config_entries.async_update_entry(entry, data={**entry.data, "weheat_auth": "own", "auth_implementation": "roost_x",
                                                        "token": {"access_token": "a", "refresh_token": "r", "expires_at": 0}})
    await hass.async_block_till_done()
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**COMFORT, "comfort": 21.0, "store_max": 23.0})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert not {"token", "auth_implementation", "weheat_auth"} & set(entry.options) and entry.data["token"]["access_token"] == "a"


async def test_own_login_uses_the_weheat_integrations_registration(hass: HomeAssistant, entry, current_request_with_host) -> None:
    """With the Weheat integration's app registration in Home Assistant, Roost's own login goes straight to Weheat's
    login page: nothing to fill in."""
    config_entry_oauth2_flow.async_register_implementation(hass, "weheat", config_entry_oauth2_flow.LocalOAuth2Implementation(
        hass, "weheat", "weheat-client", "secret", "https://auth.example/authorize", "https://auth.example/token"))
    r = await entry.start_reconfigure_flow(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"weheat_auth": "own"})
    assert r["type"] is FlowResultType.EXTERNAL_STEP
    assert r["url"].startswith("https://auth.example/authorize") and "client_id=weheat-client" in r["url"]
