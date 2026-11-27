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
COMFORT = {"comfort_days": "same", "hours_same": {"comfort_from": "07:00:00", "comfort_to": "22:00:00"}, "comfort": 20.5, "night_min": 19.0, "store_max": 22.5,
           "advanced": {"day_min": 20.0, "lowest_setpoint": 19.0, "max_above_room": 1.0, "min_interval": 60, "pause_hours": 2,
                        "baseline_night": 0, "weather_source": "open_meteo"}}


async def _to_comfort(hass: HomeAssistant, weheat: str, solar: bool = False) -> dict:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": weheat, "thermostat": THERMOSTAT,
                                                                       "import_weheat_history": False})
    assert r["step_id"] == "house"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"emitters": ["floor"], "use_bag": False})
    assert r["step_id"] == "price"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"price_mode": "sensor", "import_price": PRICE})
    assert r["step_id"] == "solar"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"has_solar": solar, "has_battery": False})
    if solar:
        assert r["step_id"] == "solar_details"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"solar_advanced": {"grid_sign": "import_positive"}})
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
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"emitters": ["radiators"], "use_bag": False})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"price_mode": "sensor"})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"import_price": "price_needed"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"price_mode": "fixed"})
    assert r["step_id"] == "price_fixed"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"fixed_price": 0.30, "low_tariff": {"fixed_low_price": 0.25, "low_from": 23,
                                                                       "low_to": 7, "low_weekend": True}})
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
    # 25-11-2026: the hard floor is folded away and follows comfort down, so only the range itself can be wrong
    assert r["errors"] == {"store_max": "store_below_comfort"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**COMFORT, "night_min": 21.0})
    assert r["errors"] == {"night_min": "eco_above_comfort"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**COMFORT, "comfort": 19.5, "store_max": 21.0, "night_min": 18.0})
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["data"]["day_min"] == 19.0 and r["data"]["comfort"] == 19.5


async def test_options_menu_saves_each_part(hass: HomeAssistant, entry) -> None:
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.MENU and r["menu_options"] == ["mode", "comfort", "price", "solar", "notify", "house", "opentherm", "done"]
    assert "comfort" in r["description_placeholders"] and r["description_placeholders"]["saved"] == ""
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**COMFORT, "comfort": 21.0, "store_max": 23.0})
    # saved right away, back in the menu (closing the window loses nothing); Done closes
    assert r["type"] is FlowResultType.MENU and "Comfort" in r["description_placeholders"]["saved"]
    assert entry.options["comfort"] == 21.0
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "done"})
    assert r["type"] is FlowResultType.CREATE_ENTRY and entry.options["comfort"] == 21.0


async def test_options_never_copy_the_weheat_login(hass: HomeAssistant, entry) -> None:
    hass.config_entries.async_update_entry(entry, data={**entry.data, "weheat_auth": "own", "auth_implementation": "roost_x",
                                                        "token": {"access_token": "a", "refresh_token": "r", "expires_at": 0}})
    await hass.async_block_till_done()
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**COMFORT, "comfort": 21.0, "store_max": 23.0})
    assert r["type"] is FlowResultType.MENU
    assert not {"token", "auth_implementation", "weheat_auth"} & set(entry.options) and entry.data["token"]["access_token"] == "a"


def _weheat_registration(hass: HomeAssistant) -> None:
    """The app registration the Weheat integration has (application credentials), as Roost finds it."""
    config_entry_oauth2_flow.async_register_implementation(hass, "weheat", config_entry_oauth2_flow.LocalOAuth2Implementation(
        hass, "weheat", "weheat-client", "secret", "https://auth.example/authorize", "https://auth.example/token"))


async def test_setup_logs_in_with_the_weheat_account(hass: HomeAssistant, weheat: str, current_request_with_host) -> None:
    """After the first screen Weheat's login page: nothing to fill in, the Weheat integration's app registration."""
    _weheat_registration(hass)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": weheat, "thermostat": THERMOSTAT,
                                                                       "import_weheat_history": False})
    assert r["type"] is FlowResultType.EXTERNAL_STEP
    assert r["url"].startswith("https://auth.example/authorize") and "client_id=weheat-client" in r["url"]


async def test_reauth_logs_in_again(hass: HomeAssistant, entry, current_request_with_host) -> None:
    _weheat_registration(hass)
    r = await entry.start_reauth_flow(hass)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "reauth_confirm"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    assert r["type"] is FlowResultType.EXTERNAL_STEP and "client_id=weheat-client" in r["url"]


async def test_reauth_without_an_app_registration(hass: HomeAssistant, entry) -> None:
    """No Weheat integration app registration: Home Assistant asks for application credentials for Roost."""
    assert await async_setup_component(hass, "application_credentials", {})
    r = await entry.start_reauth_flow(hass)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "missing_credentials"


async def test_options_solar_and_battery_on_one_screen(hass: HomeAssistant, entry) -> None:
    """Both blocks with their sensors on one screen; a tick turned off forgets that block's sensors."""
    hass.config_entries.async_update_entry(entry, options={"pv_power": "sensor.pv", "grid_power": "sensor.grid",
                                                           "battery_soc": "sensor.soc", "battery_kwh": 10.0})
    await hass.async_block_till_done()
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "solar"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "solar"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "solar_section": {"has_solar": True, "pv_power": "sensor.pv", "grid_power": "sensor.grid"},
        "battery_section": {"has_battery": False, "battery_soc": "sensor.soc", "battery_kwh": 10.0},
        "solar_advanced": {"grid_sign": "import_positive", "grid_preference": 0.0}})
    assert r["type"] is FlowResultType.MENU
    assert entry.options["pv_power"] == "sensor.pv" and "battery_soc" not in entry.options and "battery_kwh" not in entry.options


async def test_options_a_field_left_empty_is_gone(hass: HomeAssistant, entry) -> None:
    """#3: House power filled in at the setup (the entry's data), left empty in Configure: it is gone, also after a
    reload; the Weheat login in the data stays."""
    hass.config_entries.async_update_entry(entry, data={**entry.data, "pv_power": "sensor.pv", "grid_power": "sensor.grid",
                                                         "battery_soc": "sensor.soc", "house_power": "sensor.house",
                                                         "token": {"access_token": "x"}})
    await hass.async_block_till_done()
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "solar"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "solar_section": {"has_solar": True, "pv_power": "sensor.pv", "grid_power": "sensor.grid"},
        "battery_section": {"has_battery": True, "battery_soc": "sensor.soc"},
        "solar_advanced": {"grid_sign": "import_positive", "grid_preference": 0.0}})
    assert r["type"] is FlowResultType.MENU
    conf = {**entry.data, **entry.options}
    assert "house_power" not in conf and conf["battery_soc"] == "sensor.soc" and entry.data["token"] == {"access_token": "x"}


async def test_options_solar_from_battery(hass: HomeAssistant, entry) -> None:
    """22-11-2026: one setting instead of the battery's use and reserve: solar for the heat pump from this charge on."""
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "solar"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "solar_section": {"has_solar": False},
        "battery_section": {"has_battery": True, "battery_soc": "sensor.soc"},
        "solar_advanced": {"grid_preference": 0.0}})
    assert entry.options["solar_from_battery"] == 50 and "battery_use" not in entry.options
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "solar"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "solar_section": {"has_solar": False},
        "battery_section": {"has_battery": True, "battery_soc": "sensor.soc", "solar_from_battery": 80},
        "solar_advanced": {"grid_preference": 0.0}})
    assert entry.options["solar_from_battery"] == 80


async def test_options_an_emptied_field_is_not_filled_in_again(hass: HomeAssistant, entry) -> None:
    """#3, again: a house power sensor Roost can detect by its name, emptied in Configure, is not suggested again
    when Configure is opened later (and so not saved again with the next change)."""
    hass.states.async_set("sensor.house_power", "450", {"device_class": "power", "unit_of_measurement": "W"})
    hass.config_entries.async_update_entry(entry, data={**entry.data, "pv_power": "sensor.pv", "grid_power": "sensor.grid",
                                                         "battery_soc": "sensor.soc", "house_power": "sensor.house_power"})
    await hass.async_block_till_done()
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "solar"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "solar_section": {"has_solar": True, "pv_power": "sensor.pv", "grid_power": "sensor.grid"},
        "battery_section": {"has_battery": True, "battery_soc": "sensor.soc"},
        "solar_advanced": {"grid_sign": "import_positive", "grid_preference": 0.0}})
    assert "house_power" not in {**entry.data, **entry.options}
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "solar"})
    battery = next(v for k, v in r["data_schema"].schema.items() if str(k) == "battery_section")
    suggested = {str(k): (k.description or {}).get("suggested_value") for k in battery.schema.schema}
    assert suggested.get("house_power") is None and suggested.get("battery_soc") == "sensor.soc", suggested


async def test_built_in_day_ahead_prices_screen(hass: HomeAssistant, weheat: str) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"name": "Roost", "heat_pump": weheat, "thermostat": THERMOSTAT,
                                                                       "import_weheat_history": False})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"emitters": ["floor"], "use_bag": False})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"price_mode": "epex"})      # no sensor needed
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "price_epex"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"epex_zone": "NL", "import_mult": 1.21, "import_add": 0.15,
                                                                       "export_formula_section": {"export_formula": True, "export_mult": 1.0, "export_add": -0.02}})
    assert r["step_id"] == "solar"


async def test_reconfigure_another_thermostat(hass, entry) -> None:
    """Another thermostat (or heat pump) without removing Roost."""
    from homeassistant.data_entry_flow import FlowResultType
    hass.states.async_set("climate.bedroom", "heat", {"temperature": 19.0, "current_temperature": 19.2})
    r = await entry.start_reconfigure_flow(hass)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "reconfigure"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"heat_pump": entry.data["heat_pump"],
                                                                      "thermostat": "climate.bedroom"})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["thermostat"] == "climate.bedroom" and entry.data.get("import_price")


def _box(hass: HomeAssistant, name: str, entities: dict[str, tuple[str, str, dict]]) -> str:
    """An OpenTherm box as a device with its entities: {object_id: (domain, state, attributes)}. Returns the device id."""
    from homeassistant.helpers import entity_registry as er
    box = MockConfigEntry(domain="esphome", title=name)
    box.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=box.entry_id, identifiers={("esphome", name)}, name=name)
    reg = er.async_get(hass)
    for obj, (domain, state, attrs) in entities.items():
        ent = reg.async_get_or_create(domain, "esphome", f"{name}_{obj}", config_entry=box, device_id=dev.id,
                                      suggested_object_id=obj, original_name=attrs.pop("name", None))
        hass.states.async_set(ent.entity_id, state, attrs)
    return dev.id


async def test_the_box_is_found_on_its_device(hass: HomeAssistant, weheat: str) -> None:
    """23-11-2026, the author: the box picked as a device; its entities found on it, by the THRM ONE's names and, for
    another gateway, by what they are (a flow setpoint number, a select with a Home Assistant option, a state)."""
    from custom_components.roost.config_flow import detect_opentherm_device
    thrm = _box(hass, "thrm", {"thrm_one_abc_flow_setpoint": ("number", "0", {"unit_of_measurement": "°C"}),
                               "thrm_one_abc_control_state": ("sensor", "home_assistant", {}),
                               "thrm_one_abc_control_mode": ("select", "Home Assistant", {"options": ["Home Assistant", "Heating curve"]}),
                               "thrm_one_abc_min_flow": ("number", "20", {}), "thrm_one_abc_max_flow": ("number", "40", {})})
    f = detect_opentherm_device(hass, thrm)
    assert f["ot_flow_setpoint"].endswith("_flow_setpoint") and f["ot_control_mode"].endswith("_control_mode")
    assert f["ot_min_flow_number"].endswith("_min_flow") and f["ot_max_flow_number"].endswith("_max_flow")
    other = _box(hass, "otgw", {"otgw_ch_control_setpoint": ("number", "0", {"unit_of_measurement": "°C", "name": "CH control setpoint"}),
                                "otgw_steering": ("select", "Home Assistant", {"options": ["Home Assistant", "Thermostat"]}),
                                "otgw_status": ("sensor", "home_assistant", {})})
    g = detect_opentherm_device(hass, other)
    assert g["ot_flow_setpoint"] == "number.otgw_ch_control_setpoint" and g["ot_control_mode"] == "select.otgw_steering"
    assert g["ot_control_state"] == "sensor.otgw_status"
    assert detect_opentherm_device(hass, None) == {}
    # in the options: only the device picked, the rest found
    from .conftest import setup_roost
    room = "sensor.living_room_temperature"
    hass.states.async_set(room, "20.5", {"device_class": "temperature", "unit_of_measurement": "°C"})
    entry = await setup_roost(hass, weheat, {"room_temperature": room})
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "opentherm"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"control": "opentherm", "ot_device": other})
    assert r["type"] is FlowResultType.MENU, r.get("errors")
    assert entry.options["ot_flow_setpoint"] == "number.otgw_ch_control_setpoint" and entry.options["ot_control_state"] == "sensor.otgw_status"


async def test_comfort_hours_in_three_forms(hass: HomeAssistant, entry) -> None:
    """23-11-2026: the same every day (whole hours as before), weekdays and weekend, or per day; 24-11: on one screen,
    a block per choice (the chosen one open), so another choice is stored at once; it opens again in the form that
    fits what is stored."""
    from custom_components.roost import schedule
    rest = {k: v for k, v in COMFORT.items() if k not in ("comfort_days", "hours_same")}
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    blocks = {str(k): v for k, v in r["data_schema"].schema.items()}
    assert {"hours_same", "hours_week_weekend", schedule.SECTION} <= set(blocks)
    assert not blocks["hours_same"].options["collapsed"] and blocks["hours_week_weekend"].options["collapsed"]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**rest, "comfort_days": "week_weekend",
                                                                         "hours_week_weekend": {"weekdays_from": "06:30:00", "weekdays_to": "22:00:00",
                                                                                                "weekend_from": "08:00:00", "weekend_to": "23:00:00"}})
    assert r["type"] is FlowResultType.MENU, r.get("errors")
    week = entry.options[schedule.WEEK]
    assert entry.options[schedule.ENABLED] and week["monday"] == [[390, 1320]] and week["sunday"] == [[480, 1380]]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    shown = _as_shown(r["data_schema"])
    assert shown["comfort_days"] == "week_weekend" and shown["hours_week_weekend"]["weekend_from"] == "08:00:00"
    blocks = {str(k): v for k, v in r["data_schema"].schema.items()}
    assert blocks["hours_same"].options["collapsed"] and not blocks["hours_week_weekend"].options["collapsed"]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "comfort_days": "same",
                                                                         "hours_same": {"comfort_from": "07:30:00", "comfort_to": "21:00:00"}})
    assert entry.options[schedule.ENABLED] and entry.options[schedule.WEEK]["friday"] == [[450, 1260]]   # half hour: weekly
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**rest, "comfort_days": "same",
                                                                         "hours_same": {"comfort_from": "07:00:00", "comfort_to": "22:00:00"}})
    assert not entry.options[schedule.ENABLED] and entry.options["day_from"] == 7 and entry.options["day_to"] == 22
    # the chosen block without its times: asked for, nothing stored
    before = dict(entry.options)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**rest, "comfort_days": "week_weekend", "hours_week_weekend": {}})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"base": "times_needed"} and dict(entry.options) == before


async def test_price_on_one_screen(hass: HomeAssistant, entry) -> None:
    """24-11-2026: the kind of price and a block per kind on one screen; only the chosen block is stored, the
    others stay as they were; a fixed price without its rate is asked for."""
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "price"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "price"
    shown = _as_shown(r["data_schema"])
    assert shown["price_mode"] == "sensor" and shown["price_sensor"]["import_price"] == entry.data["import_price"]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "price_mode": "fixed"})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"base": "fixed_price_needed"}
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "price_mode": "fixed",
                                                                         "price_fixed": {**shown["price_fixed"], "fixed_price": 0.30}})
    assert r["type"] is FlowResultType.MENU
    o = entry.options
    assert o["price_mode"] == "fixed" and o["fixed_price"] == 0.30 and o["import_price"] == entry.data["import_price"]
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "price"})
    shown = _as_shown(r["data_schema"])
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "price_mode": "epex",
                                                                         "price_epex": {**shown["price_epex"], "import_add": 0.15}})
    assert r["type"] is FlowResultType.MENU
    assert entry.options["price_mode"] == "epex" and entry.options["import_add"] == 0.15 and entry.options["fixed_price"] == 0.30
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "price"})
    shown = _as_shown(r["data_schema"])
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "price_mode": "sensor", "price_sensor": {}})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"base": "price_needed"}


async def test_solar_from_the_energy_dashboard(hass: HomeAssistant) -> None:
    """23-11-2026: what Home Assistant's Energy dashboard knows comes first (its power sensors, the grid's sign, the
    battery's charge); an empty dashboard gives nothing, so the names are searched as before."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.roost import detect
    for eid in ("sensor.pv_w", "sensor.net_w", "sensor.accu_w", "sensor.accu_soc"):
        hass.states.async_set(eid, "1")
    mgr = MagicMock()
    mgr.data = {"energy_sources": [
        {"type": "solar", "stat_energy_from": "sensor.pv_kwh", "stat_rate": "sensor.pv_w"},
        {"type": "grid", "stat_rate": "sensor.net_w", "power_config": {"stat_rate_inverted": "sensor.net_w"}},
        {"type": "battery", "stat_energy_from": "sensor.a", "stat_energy_to": "sensor.b", "power_config": {"stat_rate": "sensor.accu_w"},
         "stat_soc": "sensor.accu_soc"}]}
    with patch("homeassistant.components.energy.data.async_get_manager", AsyncMock(return_value=mgr)):
        got = await detect.async_energy_dashboard(hass)
    assert got == {"pv_power": "sensor.pv_w", "grid_power": "sensor.net_w", "grid_sign": "export_positive",
                   "battery_power": "sensor.accu_w", "battery_soc": "sensor.accu_soc"}
    mgr.data = None
    with patch("homeassistant.components.energy.data.async_get_manager", AsyncMock(return_value=mgr)):
        assert await detect.async_energy_dashboard(hass) == {}


async def test_comfort_all_day_and_midnight_survive_the_form(hass: HomeAssistant, entry) -> None:
    """Review 23-11: an end at 00:00 is midnight. All day (0-24) and 7-24 stay day_from/day_to after opening and
    saving the form unchanged; a week without any comfort hour is refused."""
    from custom_components.roost import schedule
    rest = {k: v for k, v in COMFORT.items() if k not in ("comfort_days", "hours_same")}
    for frm, to in ((0, 24), (7, 24)):
        hass.config_entries.async_update_entry(entry, options={**entry.options, "day_from": frm, "day_to": to, schedule.ENABLED: False})
        r = await hass.config_entries.options.async_init(entry.entry_id)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
        r = await hass.config_entries.options.async_configure(r["flow_id"], {**rest, "comfort_days": "same",
                                                                             "hours_same": _as_shown(r["data_schema"])["hours_same"]})
        assert r["type"] is FlowResultType.MENU
        assert not entry.options[schedule.ENABLED] and (entry.options["day_from"], entry.options["day_to"]) == (frm, to)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**rest, "comfort_days": "same",
                                                                         "hours_same": {"comfort_from": "07:00:00", "comfort_to": "07:00:00"}})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"base": "invalid_schedule"}


def _as_shown(schema) -> dict:
    """What the frontend sends back when a form is submitted untouched: the suggested values, else the defaults,
    sections included (a section left closed is sent as shown too)."""
    import voluptuous as vol
    from homeassistant.data_entry_flow import section
    out: dict = {}
    for key, val in schema.schema.items():
        name = str(key)
        if isinstance(val, section):
            out[name] = _as_shown(val.schema)
            continue
        desc = getattr(key, "description", None) or {}
        if "suggested_value" in desc and desc["suggested_value"] is not None:
            out[name] = desc["suggested_value"]
        elif getattr(key, "default", vol.UNDEFINED) is not vol.UNDEFINED:
            out[name] = key.default()
    return out


async def test_options_sent_as_shown_is_the_way_back(hass: HomeAssistant, entry) -> None:
    """Forms have no back button: a part submitted untouched stores nothing, does not reload Roost and says so in
    the menu."""
    r = await hass.config_entries.options.async_init(entry.entry_id)      # once stored as options, as on a real install
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**COMFORT, "comfort": 21.0, "store_max": 23.0})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "house"})   # old single emitter → ticks
    r = await hass.config_entries.options.async_configure(r["flow_id"], _as_shown(r["data_schema"]))
    await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "done"})
    await hass.async_block_till_done()
    for part in ("house", "opentherm", "price", "solar", "comfort", "notify", "mode"):
        before = (dict(entry.data), dict(entry.options), entry.modified_at)
        r = await hass.config_entries.options.async_init(entry.entry_id)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": part})
        assert r["type"] is FlowResultType.FORM, part
        r = await hass.config_entries.options.async_configure(r["flow_id"], _as_shown(r["data_schema"]))
        assert r["type"] is FlowResultType.MENU, (part, r.get("errors"))
        after = (dict(entry.data), dict(entry.options))
        diff = {i: {k: (before[i].get(k), after[i].get(k)) for k in set(before[i]) | set(after[i]) if before[i].get(k) != after[i].get(k)}
                for i in (0, 1)}
        assert entry.modified_at == before[2], (part, diff)
        assert "Nothing changed" in r["description_placeholders"]["saved"], part
        await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "done"})
        await hass.async_block_till_done()


async def test_options_solar_off_block_still_forgets_its_sensors(hass: HomeAssistant, entry) -> None:
    """A battery sensor left over without the block shown (no charge sensor) is still wiped when solar is sent;
    only the battery's setting stays."""
    hass.config_entries.async_update_entry(entry, options={**entry.data, "battery_power": "sensor.batt_w", "solar_from_battery": 60})
    await hass.async_block_till_done()
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "solar"})
    shown = _as_shown(r["data_schema"])
    assert not shown["battery_section"].get("has_battery")              # no charge sensor: the block shows off
    r = await hass.config_entries.options.async_configure(r["flow_id"], shown)
    assert r["type"] is FlowResultType.MENU
    assert "battery_power" not in entry.options and entry.options["solar_from_battery"] == 60


async def test_price_export_formula_on_and_off(hass: HomeAssistant, entry) -> None:
    """Review 24-11: the day-ahead block's own export price turned on is stored with its formula; turned off again
    it is off (net metering), whatever export numbers stay behind."""
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "price"})
    shown = _as_shown(r["data_schema"])
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "price_mode": "epex", "price_epex": {
        **shown["price_epex"], "export_formula": True, "export_mult": 1.0, "export_add": -0.02}})
    assert r["type"] is FlowResultType.MENU
    o = entry.options
    assert o["price_mode"] == "epex" and o["export_formula"] is True and o["export_add"] == -0.02
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "price"})
    shown = _as_shown(r["data_schema"])
    assert shown["price_epex"]["export_formula"] is True and shown["price_epex"]["export_add"] == -0.02
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "price_epex": {**shown["price_epex"], "export_formula": False}})
    assert r["type"] is FlowResultType.MENU and entry.options["export_formula"] is False


async def test_price_low_tariff_emptied_is_one_rate(hass: HomeAssistant, entry) -> None:
    """Review 24-11: a fixed price with a low rate, the low rate emptied later: one rate again (no fixed_low_price
    stored), as before."""
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "price"})
    shown = _as_shown(r["data_schema"])
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "price_mode": "fixed", "price_fixed": {
        **shown["price_fixed"], "fixed_price": 0.30, "fixed_low_price": 0.25, "low_from": 23, "low_to": 7}})
    assert r["type"] is FlowResultType.MENU and entry.options["fixed_low_price"] == 0.25
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "price"})
    shown = _as_shown(r["data_schema"])
    assert shown["price_fixed"]["fixed_low_price"] == 0.25
    block = {k: v for k, v in shown["price_fixed"].items() if k != "fixed_low_price"}
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**shown, "price_fixed": block})
    assert r["type"] is FlowResultType.MENU
    assert "fixed_low_price" not in entry.options and entry.options["fixed_price"] == 0.30


async def test_setup_comfort_asks_for_the_chosen_times(hass: HomeAssistant, weheat: str) -> None:
    """Review 24-11: in the setup too, the chosen block of comfort hours without its times is asked for, and
    another choice is taken on the same screen."""
    r = await _to_comfort(hass, weheat)
    rest = {k: v for k, v in COMFORT.items() if k not in ("comfort_days", "hours_same")}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**rest, "comfort_days": "week_weekend", "hours_week_weekend": {}})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"base": "times_needed"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {**rest, "comfort_days": "week_weekend", "hours_week_weekend": {
        "weekdays_from": "06:30:00", "weekdays_to": "22:00:00", "weekend_from": "08:00:00", "weekend_to": "23:00:00"}})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["data"]["weekly_comfort"] is True and r["data"]["comfort_schedule"]["saturday"] == [[480, 1380]]


async def test_eco_above_comfort_kept_from_before_does_not_block_saving(hass: HomeAssistant, entry) -> None:
    """25-11-2026: a setup from before the comfort range may have eco (night_min) above comfort: saving the comfort
    screen with another change still works; changing eco or comfort itself is checked."""
    hass.config_entries.async_update_entry(entry, options={**entry.options, "comfort": 20.0, "night_min": 20.5})
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**COMFORT, "comfort": 20.0, "night_min": 20.5, "store_max": 23.0})
    assert r["type"] is FlowResultType.MENU and entry.options["store_max"] == 23.0
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "comfort"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**COMFORT, "comfort": 20.0, "night_min": 21.0, "store_max": 23.0})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"night_min": "eco_above_comfort"}
