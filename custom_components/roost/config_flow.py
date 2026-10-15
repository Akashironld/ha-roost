"""Config flow by subject: heat pump and thermostat, the house, the price, solar and battery, comfort (with the\nregulation folded away), extra rooms as subentries. Likely entities are filled in (detect.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry, ConfigFlow, ConfigFlowResult, ConfigSubentryFlow, OptionsFlow, SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_BASELINE_NIGHT, CONF_BATTERY_KW, CONF_BATTERY_KWH, CONF_BATTERY_POWER, CONF_BATTERY_RESERVE, CONF_BATTERY_SOC,
    CONF_COMFORT, CONF_DAY_FROM, CONF_DAY_MIN, CONF_DAY_TO, CONF_EXPORT_PRICE, CONF_GRID_POWER, CONF_GRID_PREFERENCE,
    CONF_GRID_SIGN, CONF_HEAT_PUMP, CONF_HOUSE_POWER, CONF_IMPORT_ON_SETUP, CONF_IMPORT_PRICE, CONF_MAX_ABOVE,
    CONF_MIN_INTERVAL, CONF_NIGHT_MIN, CONF_PAUSE_HOURS, CONF_PV_FORECAST, CONF_PV_FORECAST_TOMORROW, CONF_PV_POWER,
    CONF_ROOM, CONF_STORE_MAX, CONF_THERMOSTAT, CONF_WEATHER, CONF_WEATHER_SOURCE, DEFAULTS, DOMAIN, GRID_SIGNS, WEATHER_SOURCES,
    WEHEAT, CONF_FIXED_EXPORT_PRICE, CONF_FIXED_LOW_PRICE, CONF_FIXED_PRICE, CONF_LOW_FROM, CONF_LOW_TO, CONF_LOW_WEEKEND,
    CONF_EMITTER, CONF_HAS_BATTERY, CONF_HAS_SOLAR, CONF_PRICE_MODE, CONF_SP_MIN, CONF_USE_BAG, EMITTERS, PRICE_MODES,
)
from . import comfort, detect
from .rooms import KINDS as ROOM_KINDS


def _ent(domain, device_class=None):
    cfg = {"domain": domain}
    if device_class:
        cfg["device_class"] = device_class
    return selector.EntitySelector(selector.EntitySelectorConfig(**cfg))


def _num(lo, hi, step, unit=None):
    cfg = {"min": lo, "max": hi, "step": step, "mode": selector.NumberSelectorMode.BOX}
    if unit:
        cfg["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**cfg))


def _sel(options, key):
    return selector.SelectSelector(selector.SelectSelectorConfig(options=options, translation_key=key,
                                                                 mode=selector.SelectSelectorMode.DROPDOWN))


DEG = _num(10, 30, 0.5, "°C")


SOLAR_KEYS = [CONF_GRID_POWER, CONF_GRID_SIGN, CONF_PV_POWER, CONF_PV_FORECAST, CONF_PV_FORECAST_TOMORROW]
BATTERY_KEYS = [CONF_BATTERY_SOC, CONF_BATTERY_POWER, CONF_BATTERY_KWH, CONF_BATTERY_KW, CONF_BATTERY_RESERVE, CONF_HOUSE_POWER]
ADVANCED = "advanced"
ADVANCED_KEYS = [CONF_SP_MIN, CONF_MAX_ABOVE, CONF_MIN_INTERVAL, CONF_PAUSE_HOURS, CONF_BASELINE_NIGHT, CONF_WEATHER_SOURCE, CONF_WEATHER]


def start_schema() -> vol.Schema:
    """First step: which heat pump and which thermostat."""
    return vol.Schema({
        vol.Required(CONF_NAME, default="Roost"): selector.TextSelector(),
        vol.Required(CONF_HEAT_PUMP): selector.DeviceSelector(selector.DeviceSelectorConfig(integration="weheat")),
        vol.Required(CONF_THERMOSTAT): _ent("climate"),
        vol.Required(CONF_IMPORT_ON_SETUP, default=True): selector.BooleanSelector(),
    })


def house_schema(with_thermostat: bool) -> vol.Schema:
    """The house: room sensor, heat emitters, building register."""
    s: dict = {}
    if with_thermostat:
        s[vol.Required(CONF_THERMOSTAT)] = _ent("climate")
    s[vol.Optional(CONF_ROOM)] = _ent("sensor", "temperature")
    s[vol.Required(CONF_EMITTER, default=DEFAULTS[CONF_EMITTER])] = _sel(EMITTERS, "emitter")
    s[vol.Required(CONF_USE_BAG, default=DEFAULTS[CONF_USE_BAG])] = selector.BooleanSelector()
    return vol.Schema(s)


def price_mode_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_PRICE_MODE, default=DEFAULTS[CONF_PRICE_MODE]): _sel(PRICE_MODES, "price_mode"),
        vol.Optional(CONF_IMPORT_PRICE): _ent(["sensor", "input_number"]),
        vol.Optional(CONF_EXPORT_PRICE): _ent(["sensor", "input_number"]),
    })


def price_schema(currency: str) -> vol.Schema:
    """A fixed contract: one rate, optionally a low rate at night and in the weekend, optionally a fixed export price."""
    unit = f"{currency}/kWh"
    return vol.Schema({
        vol.Required(CONF_FIXED_PRICE): _num(0, 2, 0.001, unit),
        vol.Optional(CONF_FIXED_LOW_PRICE): _num(0, 2, 0.001, unit),
        vol.Required(CONF_LOW_FROM, default=DEFAULTS[CONF_LOW_FROM]): _num(0, 23, 1, "h"),
        vol.Required(CONF_LOW_TO, default=DEFAULTS[CONF_LOW_TO]): _num(0, 23, 1, "h"),
        vol.Required(CONF_LOW_WEEKEND, default=DEFAULTS[CONF_LOW_WEEKEND]): selector.BooleanSelector(),
        vol.Optional(CONF_FIXED_EXPORT_PRICE): _num(-1, 2, 0.001, unit),
    })


def solar_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_HAS_SOLAR, default=False): selector.BooleanSelector(),
        vol.Required(CONF_HAS_BATTERY, default=False): selector.BooleanSelector(),
    })


def solar_details_schema(solar: bool, battery: bool) -> vol.Schema:
    """Only the fields for what the house has."""
    s: dict = {}
    if solar:
        s[vol.Optional(CONF_PV_POWER)] = _ent("sensor", "power")
        s[vol.Optional(CONF_PV_FORECAST)] = _ent("sensor")
        s[vol.Optional(CONF_PV_FORECAST_TOMORROW)] = _ent("sensor")
        s[vol.Optional(CONF_GRID_POWER)] = _ent("sensor", "power")
        s[vol.Required(CONF_GRID_SIGN, default=DEFAULTS[CONF_GRID_SIGN])] = _sel(GRID_SIGNS, "grid_sign")
    if battery:
        s[vol.Optional(CONF_BATTERY_SOC)] = _ent("sensor", "battery")
        s[vol.Optional(CONF_BATTERY_POWER)] = _ent("sensor", "power")
        s[vol.Optional(CONF_BATTERY_KWH)] = _num(0, 200, 0.1, "kWh")
        s[vol.Optional(CONF_BATTERY_KW)] = _num(0, 50, 0.1, "kW")
        s[vol.Optional(CONF_BATTERY_RESERVE, default=DEFAULTS[CONF_BATTERY_RESERVE])] = _num(0, 100, 1, "%")
        s[vol.Optional(CONF_HOUSE_POWER)] = _ent("sensor", "power")
    s[vol.Optional(CONF_GRID_PREFERENCE, default=DEFAULTS[CONF_GRID_PREFERENCE])] = _num(0, 0.5, 0.005)
    return vol.Schema(s)


def comfort_schema() -> vol.Schema:
    """What everyone sets; the regulation and the weather source folded away under 'advanced'."""
    d = DEFAULTS
    advanced = vol.Schema({
        vol.Required(CONF_SP_MIN, default=d[CONF_SP_MIN]): _num(14, 25, 0.5, "°C"),
        vol.Required(CONF_MAX_ABOVE, default=d[CONF_MAX_ABOVE]): _num(0.5, 3, 0.5, "°C"),
        vol.Required(CONF_MIN_INTERVAL, default=d[CONF_MIN_INTERVAL]): _num(15, 240, 15, "min"),
        vol.Required(CONF_PAUSE_HOURS, default=d[CONF_PAUSE_HOURS]): _num(0.5, 12, 0.5, "h"),
        vol.Required(CONF_BASELINE_NIGHT, default=d[CONF_BASELINE_NIGHT]): _num(0, 30, 0.5, "°C"),
        vol.Required(CONF_WEATHER_SOURCE, default=d[CONF_WEATHER_SOURCE]): _sel(WEATHER_SOURCES, "weather_source"),
        vol.Optional(CONF_WEATHER): _ent("weather"),
    })
    return vol.Schema({
        vol.Required(CONF_DAY_FROM, default=d[CONF_DAY_FROM]): _num(0, 23, 1, "h"),
        vol.Required(CONF_DAY_TO, default=d[CONF_DAY_TO]): _num(1, 24, 1, "h"),
        vol.Required(CONF_COMFORT, default=d[CONF_COMFORT]): DEG,
        vol.Required(CONF_DAY_MIN, default=d[CONF_DAY_MIN]): DEG,
        vol.Required(CONF_NIGHT_MIN, default=d[CONF_NIGHT_MIN]): DEG,
        vol.Required(CONF_STORE_MAX, default=d[CONF_STORE_MAX]): DEG,
        vol.Required(ADVANCED): section(advanced, {"collapsed": True}),
    })


def _flat(user_input: dict) -> dict:
    """A form with a section -> one level, as stored."""
    out = {k: v for k, v in user_input.items() if k != ADVANCED}
    out.update(user_input.get(ADVANCED) or {})
    return out


def _nested(values: dict) -> dict:
    """Stored values -> suggested values for a form with the 'advanced' section."""
    return {**{k: v for k, v in values.items() if k not in ADVANCED_KEYS}, ADVANCED: {k: values[k] for k in ADVANCED_KEYS if k in values}}


def _suggest(hass: HomeAssistant, values: dict, found: dict) -> dict:
    """Detected entities fill only what is still empty."""
    return {**{k: v for k, v in found.items() if v}, **{k: v for k, v in values.items() if v not in (None, "")}}


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "")}


def _check_weheat(hass: HomeAssistant, device_id: str) -> bool:
    keys = {e.translation_key for e in er.async_entries_for_device(er.async_get(hass), device_id)}
    return {WEHEAT["state"], WEHEAT["heat"], WEHEAT["elec"]} <= keys


def _check_price(d: dict) -> dict[str, str]:
    return {CONF_IMPORT_PRICE: "price_needed"} if d.get(CONF_PRICE_MODE, "sensor") == "sensor" and not d.get(CONF_IMPORT_PRICE) else {}


def _check_comfort(d: dict) -> dict[str, str]:
    errors = {}
    if float(d[CONF_COMFORT]) < float(d[CONF_DAY_MIN]):
        errors[CONF_COMFORT] = "comfort_below_min"
    if float(d[CONF_STORE_MAX]) < float(d[CONF_COMFORT]):
        errors[CONF_STORE_MAX] = "store_below_comfort"
    if float(d.get(CONF_SP_MIN, 0)) > float(d[CONF_COMFORT]):
        errors["base"] = "lowest_above_comfort"
    if int(d[CONF_DAY_TO]) <= int(d[CONF_DAY_FROM]):
        errors[CONF_DAY_TO] = "day_order"
    if d.get(CONF_WEATHER_SOURCE) == "entity" and not d.get(CONF_WEATHER):
        errors["base"] = "weather_needed"
    return errors


async def _comfort_from_history(hass: HomeAssistant, thermostat: str | None, days: int = 14) -> dict | None:
    """Comfort settings suggested from the thermostat's setpoints in the recorder (comfort.from_history)."""
    if not thermostat:
        return None
    try:
        from homeassistant.components.recorder import get_instance, history
        from homeassistant.util import dt as dt_util
        end = dt_util.utcnow()
        start = end - timedelta(days=days)
        res = await get_instance(hass).async_add_executor_job(
            partial(history.state_changes_during_period, hass, start, end, entity_id=thermostat, include_start_time_state=True))
        changes = sorted((s.last_changed.timestamp(), s.attributes.get("temperature")) for s in res.get(thermostat, []))
        samples = []
        t, i, sp = start.timestamp() + 1800, 0, None
        while t < end.timestamp():
            while i < len(changes) and changes[i][0] <= t:
                sp = changes[i][1] if changes[i][1] is not None else sp
                i += 1
            if sp is not None:
                samples.append((dt_util.as_local(datetime.fromtimestamp(t, tz=timezone.utc)).hour, float(sp)))
            t += 3600
        return comfort.from_history(samples)
    except Exception:  # noqa: BLE001 - only a suggestion: the defaults remain
        return None


def _summary(hass: HomeAssistant, o: dict, rooms: int) -> dict[str, str]:
    """What is set now, for the options menu (names and numbers only: the words come from the translation)."""
    def n(v):
        return f"{float(v):g}"
    cur = hass.config.currency or "EUR"
    if o.get(CONF_PRICE_MODE) == "fixed":
        price = f"{n(o.get(CONF_FIXED_PRICE, 0))} {cur}/kWh" + (f" / {n(o[CONF_FIXED_LOW_PRICE])}" if o.get(CONF_FIXED_LOW_PRICE) is not None else "")
    else:
        price = detect.friendly(hass, o.get(CONF_IMPORT_PRICE))
    solar = []
    if o.get(CONF_PV_POWER) or o.get(CONF_PV_FORECAST):
        solar.append(detect.friendly(hass, o.get(CONF_PV_POWER) or o.get(CONF_PV_FORECAST)))
    if o.get(CONF_BATTERY_SOC):
        solar.append(f"{n(o[CONF_BATTERY_KWH])} kWh" if o.get(CONF_BATTERY_KWH) else detect.friendly(hass, o.get(CONF_BATTERY_SOC)))
    return {
        "house": " · ".join(x for x in (detect.friendly(hass, o.get(CONF_THERMOSTAT)), detect.friendly(hass, o.get(CONF_ROOM)) if o.get(CONF_ROOM) else "") if x),
        "price": price,
        "solar": " · ".join(solar) or "—",
        "comfort": f"{int(o[CONF_DAY_FROM])}–{int(o[CONF_DAY_TO])} · {n(o[CONF_COMFORT])} °C · min {n(o[CONF_DAY_MIN])} / {n(o[CONF_NIGHT_MIN])} °C",
        "rooms": str(rooms),
    }


def room_schema() -> vol.Schema:
    """An extra room: a sensor, its kind (the defaults for its minimum and hours) and, if wanted, other values."""
    return vol.Schema({
        vol.Required("name"): selector.TextSelector(),
        vol.Required("sensor"): _ent("sensor", "temperature"),
        vol.Required("kind", default="other"): _sel(list(ROOM_KINDS), "room_kind"),
        vol.Optional("minimum"): _num(10, 24, 0.5, "°C"),
        vol.Optional("hour_from"): _num(0, 23, 1, "h"),
        vol.Optional("hour_to"): _num(0, 24, 1, "h"),
    })


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or change an extra room the heat pump also heats."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            data = _clean(user_input)
            return self.async_create_entry(title=data["name"], data=data)
        return self.async_show_form(step_id="user", data_schema=room_schema())

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        if user_input is not None:
            data = _clean(user_input)
            return self.async_update_and_abort(self._get_entry(), sub, title=data["name"], data=data)
        return self.async_show_form(step_id="reconfigure", data_schema=self.add_suggested_values_to_schema(room_schema(), dict(sub.data)))


class RoostConfigFlow(ConfigFlow, domain=DOMAIN):
    """Setup in steps by subject: heat pump and thermostat, the house, the price, solar and battery, comfort."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {"room": RoomSubentryFlow}

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def _form(self, step_id: str, schema: vol.Schema, values: dict, errors: dict | None = None) -> ConfigFlowResult:
        return self.async_show_form(step_id=step_id, data_schema=self.add_suggested_values_to_schema(schema, values), errors=errors or {})

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _check_weheat(self.hass, user_input[CONF_HEAT_PUMP]):
                errors[CONF_HEAT_PUMP] = "not_weheat"
            else:
                await self.async_set_unique_id(user_input[CONF_HEAT_PUMP])
                self._abort_if_unique_id_configured()
                self._data.update(_clean(user_input))
                return await self.async_step_house()
        return self._form("user", start_schema(), _suggest(self.hass, user_input or {}, {CONF_THERMOSTAT: detect.thermostat(self.hass)}), errors)

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(_clean(user_input))
            return await self.async_step_price()
        room = detect.room_sensor(self.hass, self._data.get(CONF_THERMOSTAT), self._data.get(CONF_HEAT_PUMP))
        return self._form("house", house_schema(False), {CONF_ROOM: room} if room else {})

    async def async_step_price(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_price(user_input)
            if not errors:
                self._data.update(_clean(user_input))
                if user_input.get(CONF_PRICE_MODE) == "fixed":
                    return await self.async_step_price_fixed()
                return await self.async_step_solar()
        imp, exp = detect.prices(self.hass)
        return self._form("price", price_mode_schema(), _suggest(self.hass, user_input or {}, {CONF_IMPORT_PRICE: imp, CONF_EXPORT_PRICE: exp}), errors)

    async def async_step_price_fixed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(_clean(user_input))
            return await self.async_step_solar()
        return self.async_show_form(step_id="price_fixed", data_schema=price_schema(self.hass.config.currency or "EUR"))

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if user_input.get(CONF_HAS_SOLAR) or user_input.get(CONF_HAS_BATTERY):
                return await self.async_step_solar_details()
            return await self.async_step_comfort()
        found = detect.energy(self.hass)
        return self._form("solar", solar_schema(), {CONF_HAS_SOLAR: bool(found.get(CONF_PV_POWER) or found.get(CONF_PV_FORECAST)),
                                                     CONF_HAS_BATTERY: bool(found.get(CONF_BATTERY_SOC))})

    async def async_step_solar_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = solar_details_schema(bool(self._data.get(CONF_HAS_SOLAR)), bool(self._data.get(CONF_HAS_BATTERY)))
        if user_input is not None:
            self._data.update(_clean(user_input))
            return await self.async_step_comfort()
        return self._form("solar_details", schema, detect.energy(self.hass))

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            flat = _flat(user_input)
            errors = _check_comfort(flat)
            if not errors:
                data = {**self._data, **_clean(flat)}
                title = data.pop(CONF_NAME, "Roost")
                return self.async_create_entry(title=title, data=data)
            return self._form("comfort", comfort_schema(), _nested(flat), errors)
        found = await _comfort_from_history(self.hass, self._data.get(CONF_THERMOSTAT))
        return self._form("comfort", comfort_schema(), _nested(found or {}), errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RoostOptionsFlow()


class RoostOptionsFlow(OptionsFlow):
    """The same subjects as a menu with what is set now; each part saves when it is submitted."""

    def __init__(self) -> None:
        self._opts: dict[str, Any] | None = None

    @property
    def opts(self) -> dict[str, Any]:
        if self._opts is None:
            self._opts = {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}
            o = self._opts
            o.setdefault(CONF_HAS_SOLAR, bool(o.get(CONF_PV_POWER) or o.get(CONF_PV_FORECAST) or o.get(CONF_GRID_POWER)))
            o.setdefault(CONF_HAS_BATTERY, bool(o.get(CONF_BATTERY_SOC)))
        return self._opts

    def _update(self, schema: vol.Schema, user_input: dict) -> None:
        for key in schema.schema:
            if str(key) == ADVANCED:
                for k in ADVANCED_KEYS:
                    self.opts.pop(k, None)
            self.opts.pop(str(key), None)
        self.opts.update(_clean(_flat(user_input)))

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self.opts)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        rooms = sum(1 for s in self.config_entry.subentries.values() if s.subentry_type == "room")
        return self.async_show_menu(step_id="init", menu_options=["mode", "house", "price", "solar", "comfort"],
                                    description_placeholders=_summary(self.hass, self.opts, rooms))

    async def async_step_mode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Off, shadow or active, with what the self-check says: here, in Roost itself."""
        mgr = getattr(self.config_entry, "runtime_data", None)
        if user_input is not None:
            if mgr is not None:
                await mgr.async_set_mode(user_input["mode"])
            return self.async_abort(reason="mode_set")
        c = mgr.check if mgr else {}
        ok, no = "✅", "⏳"
        missing = set(mgr.ready_missing) if mgr else {"temperature"}
        ph = {"plan_error": f"{c['rmse_6h']:.2f}" if c.get("rmse_6h") is not None else "—", "plan_ok": no if "temperature" in missing else ok,
              "hours": str(c.get("heating_hours", 0)), "hours_ok": no if "heating_hours" in missing else ok,
              "heat": f"{c['heat_ratio']:.2f}" if c.get("heat_ratio") is not None else "—", "heat_ok": no if "heat" in missing else ok,
              "follows": no if "following" in missing else ok, "lever": no if "lever" in missing else ok,
              "verdict": ok if mgr and mgr.ready else no}
        schema = vol.Schema({vol.Required("mode", default=mgr.mode if mgr else "shadow"): _sel(["off", "shadow", "active"], "mode")})
        return self.async_show_form(step_id="mode", data_schema=schema, description_placeholders=ph)

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = house_schema(True)
        if user_input is not None:
            self._update(schema, user_input)
            return self._save()
        return self.async_show_form(step_id="house", data_schema=self.add_suggested_values_to_schema(schema, self.opts))

    async def async_step_price(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        schema = price_mode_schema()
        if user_input is not None:
            errors = _check_price(user_input)
            if not errors:
                self._update(schema, user_input)
                if user_input.get(CONF_PRICE_MODE) == "fixed":
                    return await self.async_step_price_fixed()
                return self._save()
        return self.async_show_form(step_id="price", data_schema=self.add_suggested_values_to_schema(schema, self.opts), errors=errors)

    async def async_step_price_fixed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = price_schema(self.hass.config.currency or "EUR")
        if user_input is not None:
            self._update(schema, user_input)
            return self._save()
        return self.async_show_form(step_id="price_fixed", data_schema=self.add_suggested_values_to_schema(schema, self.opts))

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.opts.update(user_input)
            if not user_input.get(CONF_HAS_SOLAR):
                for k in SOLAR_KEYS:
                    self.opts.pop(k, None)
            if not user_input.get(CONF_HAS_BATTERY):
                for k in BATTERY_KEYS:
                    self.opts.pop(k, None)
            if user_input.get(CONF_HAS_SOLAR) or user_input.get(CONF_HAS_BATTERY):
                return await self.async_step_solar_details()
            return self._save()
        return self.async_show_form(step_id="solar", data_schema=self.add_suggested_values_to_schema(solar_schema(), self.opts))

    async def async_step_solar_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = solar_details_schema(bool(self.opts.get(CONF_HAS_SOLAR)), bool(self.opts.get(CONF_HAS_BATTERY)))
        if user_input is not None:
            self._update(schema, user_input)
            return self._save()
        return self.async_show_form(step_id="solar_details",
                                    data_schema=self.add_suggested_values_to_schema(schema, _suggest(self.hass, self.opts, detect.energy(self.hass))))

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        schema = comfort_schema()
        if user_input is not None:
            errors = _check_comfort(_flat(user_input))
            if not errors:
                self._update(schema, user_input)
                return self._save()
        return self.async_show_form(step_id="comfort", data_schema=self.add_suggested_values_to_schema(schema, _nested(self.opts)), errors=errors)
