"""Config flow: the Weheat heat pump, its thermostat and a price; then solar/battery/weather (optional) and comfort."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_BASELINE_NIGHT, CONF_BATTERY_KW, CONF_BATTERY_KWH, CONF_BATTERY_POWER, CONF_BATTERY_RESERVE, CONF_BATTERY_SOC,
    CONF_COMFORT, CONF_DAY_FROM, CONF_DAY_MIN, CONF_DAY_TO, CONF_EXPORT_PRICE, CONF_GRID_POWER, CONF_GRID_PREFERENCE,
    CONF_GRID_SIGN, CONF_HEAT_PUMP, CONF_HOUSE_POWER, CONF_IMPORT_ON_SETUP, CONF_IMPORT_PRICE, CONF_MAX_ABOVE,
    CONF_MIN_INTERVAL, CONF_NIGHT_MIN, CONF_PAUSE_HOURS, CONF_PV_FORECAST, CONF_PV_FORECAST_TOMORROW, CONF_PV_POWER,
    CONF_ROOM, CONF_STORE_MAX, CONF_THERMOSTAT, CONF_WEATHER, CONF_WEATHER_SOURCE, DEFAULTS, DOMAIN, GRID_SIGNS, WEATHER_SOURCES,
    WEHEAT,
)


def _ent(domain, device_class=None):
    cfg = {"domain": domain}
    if device_class:
        cfg["device_class"] = device_class
    return selector.EntitySelector(selector.EntitySelectorConfig(**cfg))


def _num(lo, hi, step, unit=None):
    return selector.NumberSelector(selector.NumberSelectorConfig(min=lo, max=hi, step=step, unit_of_measurement=unit,
                                                                 mode=selector.NumberSelectorMode.BOX))


def _sel(options, key):
    return selector.SelectSelector(selector.SelectSelectorConfig(options=options, translation_key=key,
                                                                 mode=selector.SelectSelectorMode.DROPDOWN))


DEG = _num(10, 30, 0.5, "°C")


def basics_schema(first: bool) -> vol.Schema:
    s: dict = {}
    if first:
        s[vol.Required(CONF_NAME, default="Roost")] = selector.TextSelector()
        s[vol.Required(CONF_HEAT_PUMP)] = selector.DeviceSelector(selector.DeviceSelectorConfig(integration="weheat"))
    s[vol.Required(CONF_THERMOSTAT)] = _ent("climate")
    s[vol.Optional(CONF_ROOM)] = _ent("sensor", "temperature")
    s[vol.Required(CONF_IMPORT_PRICE)] = _ent(["sensor", "input_number"])
    s[vol.Optional(CONF_EXPORT_PRICE)] = _ent(["sensor", "input_number"])
    if first:
        s[vol.Required(CONF_IMPORT_ON_SETUP, default=True)] = selector.BooleanSelector()
    return vol.Schema(s)


def energy_schema() -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_GRID_POWER): _ent("sensor", "power"),
        vol.Required(CONF_GRID_SIGN, default=DEFAULTS[CONF_GRID_SIGN]): _sel(GRID_SIGNS, "grid_sign"),
        vol.Optional(CONF_PV_POWER): _ent("sensor", "power"),
        vol.Optional(CONF_PV_FORECAST): _ent("sensor"),
        vol.Optional(CONF_PV_FORECAST_TOMORROW): _ent("sensor"),
        vol.Optional(CONF_BATTERY_SOC): _ent("sensor", "battery"),
        vol.Optional(CONF_BATTERY_POWER): _ent("sensor", "power"),
        vol.Optional(CONF_BATTERY_KWH): _num(0, 200, 0.1, "kWh"),
        vol.Optional(CONF_BATTERY_KW): _num(0, 50, 0.1, "kW"),
        vol.Optional(CONF_BATTERY_RESERVE, default=DEFAULTS[CONF_BATTERY_RESERVE]): _num(0, 100, 1, "%"),
        vol.Optional(CONF_HOUSE_POWER): _ent("sensor", "power"),
        vol.Optional(CONF_GRID_PREFERENCE, default=DEFAULTS[CONF_GRID_PREFERENCE]): _num(0, 0.5, 0.005),
        vol.Required(CONF_WEATHER_SOURCE, default=DEFAULTS[CONF_WEATHER_SOURCE]): _sel(WEATHER_SOURCES, "weather_source"),
        vol.Optional(CONF_WEATHER): _ent("weather"),
    })


def comfort_schema() -> vol.Schema:
    d = DEFAULTS
    return vol.Schema({
        vol.Required(CONF_DAY_FROM, default=d[CONF_DAY_FROM]): _num(0, 23, 1, "h"),
        vol.Required(CONF_DAY_TO, default=d[CONF_DAY_TO]): _num(1, 24, 1, "h"),
        vol.Required(CONF_COMFORT, default=d[CONF_COMFORT]): DEG,
        vol.Required(CONF_DAY_MIN, default=d[CONF_DAY_MIN]): DEG,
        vol.Required(CONF_NIGHT_MIN, default=d[CONF_NIGHT_MIN]): DEG,
        vol.Required(CONF_STORE_MAX, default=d[CONF_STORE_MAX]): DEG,
        vol.Required(CONF_MAX_ABOVE, default=d[CONF_MAX_ABOVE]): _num(0.5, 3, 0.5, "°C"),
        vol.Required(CONF_MIN_INTERVAL, default=d[CONF_MIN_INTERVAL]): _num(15, 240, 15, "min"),
        vol.Required(CONF_PAUSE_HOURS, default=d[CONF_PAUSE_HOURS]): _num(0.5, 12, 0.5, "h"),
        vol.Required(CONF_BASELINE_NIGHT, default=d[CONF_BASELINE_NIGHT]): _num(0, 30, 0.5, "°C"),
    })


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "")}


def _check_weheat(hass: HomeAssistant, device_id: str) -> bool:
    keys = {e.translation_key for e in er.async_entries_for_device(er.async_get(hass), device_id)}
    return {WEHEAT["state"], WEHEAT["heat"], WEHEAT["elec"]} <= keys


def _check_comfort(d: dict) -> dict[str, str]:
    errors = {}
    if float(d[CONF_COMFORT]) < float(d[CONF_DAY_MIN]):
        errors[CONF_COMFORT] = "comfort_below_min"
    if float(d[CONF_STORE_MAX]) < float(d[CONF_COMFORT]):
        errors[CONF_STORE_MAX] = "store_below_comfort"
    if int(d[CONF_DAY_TO]) <= int(d[CONF_DAY_FROM]):
        errors[CONF_DAY_TO] = "day_order"
    return errors


def _check_weather(d: dict) -> dict[str, str]:
    return {CONF_WEATHER: "weather_needed"} if d.get(CONF_WEATHER_SOURCE) == "entity" and not d.get(CONF_WEATHER) else {}


class RoostConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _check_weheat(self.hass, user_input[CONF_HEAT_PUMP]):
                errors[CONF_HEAT_PUMP] = "not_weheat"
            else:
                await self.async_set_unique_id(user_input[CONF_HEAT_PUMP])
                self._abort_if_unique_id_configured()
                self._data.update(_clean(user_input))
                return await self.async_step_energy()
        return self.async_show_form(step_id="user", data_schema=self.add_suggested_values_to_schema(basics_schema(True), user_input or {}),
                                    errors=errors)

    async def async_step_energy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_weather(user_input)
            if not errors:
                self._data.update(_clean(user_input))
                return await self.async_step_comfort()
        return self.async_show_form(step_id="energy", data_schema=self.add_suggested_values_to_schema(energy_schema(), user_input or {}),
                                    errors=errors)

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_comfort(user_input)
            if not errors:
                data = {**self._data, **user_input}
                title = data.pop(CONF_NAME, "Roost")
                return self.async_create_entry(title=title, data=data)
        return self.async_show_form(step_id="comfort", data_schema=self.add_suggested_values_to_schema(comfort_schema(), user_input or {}),
                                    errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RoostOptionsFlow()


class RoostOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._opts: dict[str, Any] | None = None

    @property
    def opts(self) -> dict[str, Any]:
        if self._opts is None:
            self._opts = {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}
        return self._opts

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["basics", "energy", "comfort", "save"])

    def _update(self, schema: vol.Schema, user_input: dict) -> None:
        for key in schema.schema:
            self.opts.pop(str(key), None)
        self.opts.update(_clean(user_input))

    async def async_step_basics(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._update(basics_schema(False), user_input)
            return await self.async_step_init()
        return self.async_show_form(step_id="basics", data_schema=self.add_suggested_values_to_schema(basics_schema(False), self.opts))

    async def async_step_energy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_weather(user_input)
            if not errors:
                self._update(energy_schema(), user_input)
                return await self.async_step_init()
        return self.async_show_form(step_id="energy", data_schema=self.add_suggested_values_to_schema(energy_schema(), self.opts), errors=errors)

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_comfort(user_input)
            if not errors:
                self._update(comfort_schema(), user_input)
                return await self.async_step_init()
        return self.async_show_form(step_id="comfort", data_schema=self.add_suggested_values_to_schema(comfort_schema(), self.opts), errors=errors)

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(data=self.opts)
