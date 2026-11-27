"""Config flow by subject: heat pump and thermostat, the house, the price, solar and battery, comfort (with the\nregulation folded away), extra rooms as subentries. Likely entities are filled in (detect.py)."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from aiohttp import ClientTimeout
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2FlowHandler

from . import check, comfort, curve, detect, epex, schedule
from .const import (
    CONF_AUTH_FROM,
    CONF_BASELINE_NIGHT,
    CONF_BATTERY_KWH,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_COMFORT,
    CONF_CONTROL,
    CONF_DAY_FROM,
    CONF_DAY_MIN,
    CONF_DAY_TO,
    CONF_EMITTERS,
    CONF_EPEX_ZONE,
    CONF_EXPORT_ADD,
    CONF_EXPORT_FORMULA,
    CONF_EXPORT_MULT,
    CONF_EXPORT_PRICE,
    CONF_FIXED_EXPORT_PRICE,
    CONF_FIXED_LOW_PRICE,
    CONF_FIXED_PRICE,
    CONF_GRID_POWER,
    CONF_GRID_PREFERENCE,
    CONF_GRID_SIGN,
    CONF_HAS_BATTERY,
    CONF_HAS_SOLAR,
    CONF_HEAT_PUMP,
    CONF_HOUSE_POWER,
    CONF_IMPORT_ADD,
    CONF_IMPORT_MULT,
    CONF_IMPORT_ON_SETUP,
    CONF_IMPORT_PRICE,
    CONF_LOW_FROM,
    CONF_LOW_TO,
    CONF_LOW_WEEKEND,
    CONF_MAX_ABOVE,
    CONF_MIN_INTERVAL,
    CONF_NIGHT_MIN,
    CONF_NOTIFY,
    CONF_OT_CH_ACTIVE,
    CONF_OT_COMM,
    CONF_OT_DHW_ACTIVE,
    CONF_OT_FLOW,
    CONF_OT_FLOW_TEMP,
    CONF_OT_FOLLOW,
    CONF_OT_MAX,
    CONF_OT_MAX_FLOW,
    CONF_OT_MAX_FLOW_NUM,
    CONF_OT_MAX_STARTS,
    CONF_OT_MIN_FLOW,
    CONF_OT_MIN_FLOW_NUM,
    CONF_OT_MIN_OFF,
    CONF_OT_MIN_RUN,
    CONF_OT_MODE,
    CONF_OT_MODE_CURVE,
    CONF_OT_MODE_HA,
    CONF_OT_Q_MIN,
    CONF_OT_QUIET,
    CONF_OT_QUIET_FROM,
    CONF_OT_QUIET_MAX,
    CONF_OT_QUIET_TO,
    CONF_OT_START_KWH,
    CONF_OT_STATE,
    CONF_OT_STATE_OK,
    CONF_PAUSE_HOURS,
    CONF_PRICE_MODE,
    CONF_PV_FORECAST,
    CONF_PV_FORECAST_TOMORROW,
    CONF_PV_POWER,
    CONF_ROOM,
    CONF_SOLAR_FROM_SOC,
    CONF_SP_MIN,
    CONF_STORE_MAX,
    CONF_THERMOSTAT,
    CONF_USE_BAG,
    CONF_WEATHER,
    CONF_WEATHER_SOURCE,
    CONF_WEEKLY,
    CONF_WEHEAT_AUTH,
    CONF_WINDOW_SENSORS,
    CONTROLS,
    DEFAULTS,
    DOMAIN,
    EMITTER_KINDS,
    GRID_SIGNS,
    OT_ENTITY_SUFFIX,
    PRICE_MODES,
    WEATHER_SOURCES,
    WEHEAT,
)
from .rooms import KINDS as ROOM_KINDS
from .volcompat import vol
from .weheat_api import API_URL, heat_pump_id, weheat_implementation

_LOGGER = logging.getLogger(__name__)


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


async def _sees_pump(hass: HomeAssistant, token: str, pump: str | None) -> bool | None:
    """Does this Weheat login see the heat pump? None: could not tell (then the login is kept)."""
    try:
        async with async_get_clientsession(hass).get(f"{API_URL}/api/v1/heat-pumps", timeout=ClientTimeout(total=30),
                                                     headers={"Authorization": f"Bearer {token}"}) as r:
            r.raise_for_status()
            pumps = await r.json()
    except Exception:  # noqa: BLE001
        return None
    if not pump or not isinstance(pumps, list):
        return None
    return any(str(p.get("id")) == str(pump) for p in pumps if isinstance(p, dict))


LOGIN_KEYS = ("token", "auth_implementation", CONF_WEHEAT_AUTH, CONF_AUTH_FROM)
UNCHANGED = "="                 # in the menu's _saved: that part was sent as shown, nothing stored


def _sel(options, key):
    return selector.SelectSelector(selector.SelectSelectorConfig(options=options, translation_key=key,
                                                                 mode=selector.SelectSelectorMode.DROPDOWN))


DEG = _num(10, 30, 0.5, "°C")


SOLAR_KEYS = [CONF_GRID_POWER, CONF_GRID_SIGN, CONF_PV_POWER, CONF_PV_FORECAST, CONF_PV_FORECAST_TOMORROW]
BATTERY_KEYS = [CONF_BATTERY_SOC, CONF_BATTERY_POWER, CONF_BATTERY_KWH, CONF_SOLAR_FROM_SOC, CONF_HOUSE_POWER]
ADVANCED = "advanced"
ADVANCED_KEYS = [CONF_DAY_MIN, CONF_SP_MIN, CONF_MAX_ABOVE, CONF_MIN_INTERVAL, CONF_PAUSE_HOURS, CONF_BASELINE_NIGHT, CONF_WEATHER_SOURCE, CONF_WEATHER]


def start_schema() -> vol.Schema:
    """First step: which heat pump and which thermostat."""
    return vol.Schema({
        vol.Required(CONF_NAME, default="Roost"): selector.TextSelector(),
        vol.Required(CONF_HEAT_PUMP): selector.DeviceSelector(selector.DeviceSelectorConfig(integration="weheat")),
        vol.Required(CONF_THERMOSTAT): _ent("climate"),
        vol.Required(CONF_IMPORT_ON_SETUP, default=True): selector.BooleanSelector(),
    })


def house_schema(with_thermostat: bool, thermostat_required: bool = True) -> vol.Schema:
    """The house: room sensor, heat emitters, building register. Steering over OpenTherm: no thermostat needed."""
    s: dict = {}
    if with_thermostat:
        s[(vol.Required if thermostat_required else vol.Optional)(CONF_THERMOSTAT)] = _ent("climate")
    s[vol.Optional(CONF_ROOM)] = _ent("sensor", "temperature")
    s[vol.Required(CONF_EMITTERS, default=["floor"])] = selector.SelectSelector(selector.SelectSelectorConfig(
        options=EMITTER_KINDS, translation_key="emitters", multiple=True, mode=selector.SelectSelectorMode.LIST))
    s[vol.Required(CONF_USE_BAG, default=DEFAULTS[CONF_USE_BAG])] = selector.BooleanSelector()
    s[vol.Optional(CONF_WINDOW_SENSORS)] = selector.EntitySelector(selector.EntitySelectorConfig(
        domain="binary_sensor", device_class=["window", "door", "opening"], multiple=True))
    return vol.Schema(s)


def price_mode_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_PRICE_MODE, default=DEFAULTS[CONF_PRICE_MODE]): _sel(PRICE_MODES, "price_mode"),
        vol.Optional(CONF_IMPORT_PRICE): _ent(["sensor", "input_number"]),
        vol.Optional(CONF_EXPORT_PRICE): _ent(["sensor", "input_number"]),
    })


def price_epex_schema(currency: str, country: str | None, export_open: bool = False) -> vol.Schema:
    """Built-in day-ahead prices: the bidding zone, and what a kWh costs (and earns) = day-ahead × multiplier + amount."""
    unit = f"{currency}/kWh"
    zones = selector.SelectSelector(selector.SelectSelectorConfig(options=epex.ZONES, mode=selector.SelectSelectorMode.DROPDOWN))
    d = DEFAULTS
    return vol.Schema({
        vol.Required(CONF_EPEX_ZONE, default=epex.zone_for(country)): zones,
        vol.Required(CONF_IMPORT_MULT, default=d[CONF_IMPORT_MULT]): _num(0, 3, 0.001),
        vol.Required(CONF_IMPORT_ADD, default=d[CONF_IMPORT_ADD]): _num(-1, 1, 0.001, unit),
        # export at its own price: only when there is no net metering (folded away while it is off)
        vol.Optional(EXPORT_SECTION): section(vol.Schema({
            vol.Required(CONF_EXPORT_FORMULA, default=d[CONF_EXPORT_FORMULA]): selector.BooleanSelector(),
            vol.Required(CONF_EXPORT_MULT, default=d[CONF_EXPORT_MULT]): _num(0, 3, 0.001),
            vol.Required(CONF_EXPORT_ADD, default=d[CONF_EXPORT_ADD]): _num(-1, 1, 0.001, unit),
        }), {"collapsed": not export_open}),
    })


def price_schema(currency: str, low_open: bool = False) -> vol.Schema:
    """A fixed contract: one rate, optionally a low rate at night and in the weekend (its hours folded away until
    there is one), optionally a fixed export price."""
    unit = f"{currency}/kWh"
    return vol.Schema({
        vol.Required(CONF_FIXED_PRICE): _num(0, 2, 0.001, unit),
        vol.Optional(CONF_FIXED_EXPORT_PRICE): _num(-1, 2, 0.001, unit),
        vol.Optional(LOW_SECTION): section(vol.Schema({
            vol.Optional(CONF_FIXED_LOW_PRICE): _num(0, 2, 0.001, unit),
            vol.Required(CONF_LOW_FROM, default=DEFAULTS[CONF_LOW_FROM]): _num(0, 23, 1, "h"),
            vol.Required(CONF_LOW_TO, default=DEFAULTS[CONF_LOW_TO]): _num(0, 23, 1, "h"),
            vol.Required(CONF_LOW_WEEKEND, default=DEFAULTS[CONF_LOW_WEEKEND]): selector.BooleanSelector(),
        }), {"collapsed": not low_open}),
    })


PRICE_SECTIONS = {"sensor": "price_sensor", "epex": "price_epex", "fixed": "price_fixed"}
PRICE_KEYS = {"sensor": [CONF_IMPORT_PRICE, CONF_EXPORT_PRICE],
              "epex": [CONF_EPEX_ZONE, CONF_IMPORT_MULT, CONF_IMPORT_ADD, CONF_EXPORT_FORMULA, CONF_EXPORT_MULT, CONF_EXPORT_ADD],
              "fixed": [CONF_FIXED_PRICE, CONF_FIXED_EXPORT_PRICE, CONF_FIXED_LOW_PRICE, CONF_LOW_FROM, CONF_LOW_TO, CONF_LOW_WEEKEND]}


def price_options_schema(currency: str, country: str | None, mode: str) -> vol.Schema:
    """Options: one screen, the kind of price and a block per kind with its fields, the chosen one open; only the
    block of the chosen kind is stored (another choice needs no extra screen)."""
    epex_s = price_epex_schema(currency, country).schema
    fixed_s = price_schema(currency).schema

    def flat(schema: dict) -> dict:
        out: dict = {}
        for k, v in schema.items():
            if isinstance(v, section):
                out.update(v.schema.schema)
            else:
                out[vol.Optional(str(k), default=k.default) if isinstance(k, vol.Required) and str(k) != CONF_FIXED_PRICE
                    else vol.Optional(str(k))] = v
        return out
    blocks = {"sensor": {vol.Optional(CONF_IMPORT_PRICE): _ent(["sensor", "input_number"]),
                         vol.Optional(CONF_EXPORT_PRICE): _ent(["sensor", "input_number"])},
              "epex": flat(epex_s), "fixed": flat(fixed_s)}
    return vol.Schema({vol.Required(CONF_PRICE_MODE, default=DEFAULTS[CONF_PRICE_MODE]): _sel(PRICE_MODES, "price_mode"),
                       **{vol.Optional(PRICE_SECTIONS[m]): section(vol.Schema(b), {"collapsed": m != mode}) for m, b in blocks.items()}})


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
    if battery:
        s[vol.Optional(CONF_BATTERY_SOC)] = _ent("sensor", "battery")
        s[vol.Optional(CONF_BATTERY_POWER)] = _ent("sensor", "power")
        s[vol.Optional(CONF_BATTERY_KWH)] = _num(0, 200, 0.1, "kWh")
        s[vol.Required(CONF_SOLAR_FROM_SOC, default=DEFAULTS[CONF_SOLAR_FROM_SOC])] = _num(0, 100, 5, "%")
        s[vol.Optional(CONF_HOUSE_POWER)] = _ent("sensor", "power")
    # rarely touched: the grid meter's sign (the Energy dashboard tells it) and a preference for own energy
    s[vol.Optional(SOLAR_ADV)] = section(vol.Schema({
        vol.Required(CONF_GRID_SIGN, default=DEFAULTS[CONF_GRID_SIGN]): _sel(GRID_SIGNS, "grid_sign"),
        vol.Optional(CONF_GRID_PREFERENCE, default=DEFAULTS[CONF_GRID_PREFERENCE]): _num(0, 0.5, 0.005),
    }), {"collapsed": True})
    return vol.Schema(s)


SOLAR_SECTION, BATTERY_SECTION = "solar_section", "battery_section"


def solar_options_schema(solar: bool, battery: bool) -> vol.Schema:
    """Options: one screen, a block for solar (and the grid meter) and one for the home battery, each with its tick
    and its sensors; the block of what the house has is open."""
    sol = solar_details_schema(True, False).schema
    bat = solar_details_schema(False, True).schema
    adv = next(k for k in sol if str(k) == SOLAR_ADV)
    return vol.Schema({
        vol.Required(SOLAR_SECTION): section(vol.Schema({vol.Required(CONF_HAS_SOLAR, default=False): selector.BooleanSelector(),
                                                         **{k: v for k, v in sol.items() if str(k) != SOLAR_ADV}}),
                                             {"collapsed": not solar}),
        vol.Required(BATTERY_SECTION): section(vol.Schema({vol.Required(CONF_HAS_BATTERY, default=False): selector.BooleanSelector(),
                                                           **{k: v for k, v in bat.items() if str(k) != SOLAR_ADV}}),
                                               {"collapsed": not battery}),
        adv: sol[adv],
    })


# The comfort hours as people think of them: the same every day (most), weekdays and weekend, or per day (several
# periods a day, as text). Stored as before: day_from/day_to for whole hours every day, else the weekly schedule.
DAYS_KIND = "comfort_days"
DAYS_KINDS = ["same", "week_weekend", "per_day"]
TIMES = {"same": ("comfort_from", "comfort_to"), "week_weekend": ("weekdays_from", "weekdays_to", "weekend_from", "weekend_to")}
HOURS_SECTIONS = {"same": "hours_same", "week_weekend": "hours_week_weekend", "per_day": schedule.SECTION}
THERMOSTAT_ONLY = (CONF_SP_MIN, CONF_MAX_ABOVE, CONF_MIN_INTERVAL)      # nothing to do with steering over OpenTherm


def _clock(minutes: int) -> str:
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}:00"


def _minutes(text: Any) -> int:
    """A time from the time picker ("07:30:00") -> minutes, on the quarter hour the schedule keeps."""
    h, m = (str(text or "0:0").split(":") + ["0"])[:2]
    return min(1440, int(round((int(h) * 60 + int(m)) / 15) * 15))


def comfort_schema(kind: str = "same", opentherm: bool = False) -> vol.Schema:
    """What everyone sets; the regulation and the weather source folded away under 'advanced'. The comfort hours:
    one choice and a block per choice, the chosen one open — another choice needs no extra screen, only its block
    counts."""
    d = DEFAULTS
    adv: dict = {}
    if not opentherm:          # the thermostat's own limits: not used when Roost steers the flow
        adv[vol.Required(CONF_SP_MIN, default=d[CONF_SP_MIN])] = _num(14, 25, 0.5, "°C")
        adv[vol.Required(CONF_MAX_ABOVE, default=d[CONF_MAX_ABOVE])] = _num(0.5, 3, 0.5, "°C")
        adv[vol.Required(CONF_MIN_INTERVAL, default=d[CONF_MIN_INTERVAL])] = _num(15, 240, 15, "min")
    advanced = vol.Schema({
        vol.Required(CONF_DAY_MIN, default=d[CONF_DAY_MIN]): DEG,      # the hard floor: follows comfort down (_flat)
        **adv,
        vol.Required(CONF_PAUSE_HOURS, default=d[CONF_PAUSE_HOURS]): _num(0.5, 12, 0.5, "h"),
        vol.Required(CONF_BASELINE_NIGHT, default=d[CONF_BASELINE_NIGHT]): _num(0, 30, 0.5, "°C"),
        vol.Required(CONF_WEATHER_SOURCE, default=d[CONF_WEATHER_SOURCE]): _sel(WEATHER_SOURCES, "weather_source"),
        vol.Optional(CONF_WEATHER): _ent("weather"),
    })
    hours: dict = {vol.Required(DAYS_KIND, default="same"): _sel(DAYS_KINDS, DAYS_KIND)}
    for k, keys in TIMES.items():
        hours[vol.Optional(HOURS_SECTIONS[k])] = section(vol.Schema({vol.Optional(key): selector.TimeSelector() for key in keys}),
                                                         {"collapsed": kind != k})
    hours[vol.Optional(schedule.SECTION)] = section(vol.Schema({
        **{vol.Optional(day, default=""): selector.TextSelector() for day in schedule.DAYS},
    }), {"collapsed": kind != "per_day"})
    return vol.Schema({
        **hours,
        # the comfort range (at least comfort, may warm up to store_max) and eco outside the comfort hours (25-11-2026:
        # four loose numbers read as the planner's inner workings; same keys, so nothing to migrate)
        vol.Required(CONF_COMFORT, default=d[CONF_COMFORT]): DEG,
        vol.Required(CONF_STORE_MAX, default=d[CONF_STORE_MAX]): DEG,
        vol.Required(CONF_NIGHT_MIN, default=d[CONF_NIGHT_MIN]): DEG,
        vol.Required(ADVANCED): section(advanced, {"collapsed": True}),
    })


def _flat(user_input: dict) -> dict:
    """A form with a section -> one level, as stored. The comfort hours (DAYS_KIND and its times) become day_from/
    day_to (whole hours, every day) or the weekly schedule; the form of before (day_from/day_to and the weekly
    section with its tick) is still taken as it was."""
    times = {k for ks in TIMES.values() for k in ks}
    for k in ("hours_same", "hours_week_weekend"):          # the blocks of the form -> one level
        user_input = {**{x: v for x, v in user_input.items() if x != k}, **(user_input.get(k) or {})}
    out = {k: v for k, v in user_input.items() if k not in (ADVANCED, schedule.SECTION, DAYS_KIND, *times)}
    out.update(user_input.get(ADVANCED) or {})
    if CONF_DAY_MIN in out and CONF_COMFORT in out and float(out[CONF_DAY_MIN]) > float(out[CONF_COMFORT]):
        out[CONF_DAY_MIN] = float(out[CONF_COMFORT]) - 0.5      # the hard floor follows comfort down (it is folded away)
    kind = user_input.get(DAYS_KIND)
    if kind in TIMES:
        def period(a_key: str, b_key: str) -> list[int]:
            a, b = _minutes(user_input.get(a_key)), _minutes(user_input.get(b_key))
            return [a, 1440 if b == 0 else b]       # an end at 00:00 is midnight (24:00), not the start of the day
        if kind == "same":
            a, b = period("comfort_from", "comfort_to")
            if a % 60 == 0 and b % 60 == 0 and b > a:
                out.update({CONF_DAY_FROM: a // 60, CONF_DAY_TO: b // 60, schedule.ENABLED: False})
                return out
            week = {day: [[a, b % 1440 if b < a else b]] for day in schedule.DAYS}
        else:
            wd, we = period("weekdays_from", "weekdays_to"), period("weekend_from", "weekend_to")
            week = {day: [list(wd)] if i < 5 else [list(we)] for i, day in enumerate(schedule.DAYS)}
        week = {day: [[a, b] for a, b in periods if a != b] for day, periods in week.items()}
        try:
            out[schedule.WEEK] = schedule.normalise(week) if any(week.values()) else {d: "" for d in schedule.DAYS}
        except ValueError:
            out[schedule.WEEK] = {day: schedule.format_day(p) for day, p in week.items()}   # shown again for correction
        out[schedule.ENABLED] = True
        first = next((p[0] for p in week.values() if p), [7 * 60, 22 * 60])
        out[CONF_DAY_FROM] = first[0] // 60
        out[CONF_DAY_TO] = min(24, max(out[CONF_DAY_FROM] + 1, -(-first[1] // 60))) if first[1] > first[0] else 24
        return out
    if kind == "per_day":
        weekly = user_input.get(schedule.SECTION) or {}
        raw = {day: weekly.get(day, "") for day in schedule.DAYS}
        try:
            out[schedule.WEEK] = schedule.normalise(raw)
        except ValueError:
            out[schedule.WEEK] = raw
        out[schedule.ENABLED] = True
        return out
    if schedule.SECTION in user_input:
        weekly = user_input[schedule.SECTION] or {}
        out[schedule.ENABLED] = bool(weekly.get("enabled", False))
        raw = {day: weekly.get(day, "") for day in schedule.DAYS}
        try:
            out[schedule.WEEK] = schedule.normalise(raw)
        except ValueError:
            out[schedule.WEEK] = raw             # keep the invalid input visible for correction
    return out


def _times_missing(user_input: dict) -> dict[str, str]:
    """The chosen block of comfort hours must have its times (the fields are optional: the other blocks may stay empty)."""
    kind = user_input.get(DAYS_KIND)
    block = user_input.get(HOURS_SECTIONS.get(str(kind), "")) or {}
    if kind in TIMES and not all(block.get(k) for k in TIMES[kind]):
        return {"base": "times_needed"}
    return {}


def days_kind(values: dict) -> str:
    """Which form of the comfort hours fits what is stored: the same every day, weekdays and weekend, or per day."""
    if not values.get(schedule.ENABLED):
        return "same"
    week = values.get(schedule.WEEK) or {}
    try:
        week = schedule.normalise(week)
    except ValueError:
        return "per_day"
    days = [week.get(day, []) for day in schedule.DAYS]
    if any(len(p) > 1 for p in days):
        return "per_day"
    if all(p == days[0] for p in days) and days[0]:
        return "same"
    if all(p == days[0] for p in days[:5]) and days[5] == days[6] and days[0] and days[5]:
        return "week_weekend"
    return "per_day"


def _nested(values: dict, kind: str | None = None) -> dict:
    """Stored values -> suggested values for a form with the 'advanced' section and the comfort hours."""
    legacy = [[int(values.get(CONF_DAY_FROM, DEFAULTS[CONF_DAY_FROM]))*60,
               int(values.get(CONF_DAY_TO, DEFAULTS[CONF_DAY_TO]))*60]]
    week = values.get(schedule.WEEK, {})
    weekly: dict[str, Any] = {"enabled": bool(values.get(schedule.ENABLED, False))}
    for day in schedule.DAYS:
        periods = week.get(day, legacy)
        weekly[day] = periods if isinstance(periods, str) else schedule.format_day(periods)
    shown = kind or days_kind(values)
    times: dict[str, str] = {}
    norm = week if not isinstance(week, dict) else {d: (p if not isinstance(p, str) else []) for d, p in week.items()}
    if values.get(schedule.ENABLED) and norm:
        wd, we = (norm.get("monday") or legacy)[0], (norm.get("saturday") or norm.get("monday") or legacy)[0]
    else:
        wd = we = legacy[0]
    times.update({"comfort_from": _clock(wd[0]), "comfort_to": _clock(wd[1]), "weekdays_from": _clock(wd[0]),
                  "weekdays_to": _clock(wd[1]), "weekend_from": _clock(we[0]), "weekend_to": _clock(we[1])})
    weekly.pop("enabled", None)
    return {**{k: v for k, v in values.items() if k not in (*ADVANCED_KEYS, schedule.ENABLED, schedule.WEEK, CONF_DAY_FROM, CONF_DAY_TO)},
            ADVANCED: {k: values[k] for k in ADVANCED_KEYS if k in values},
            DAYS_KIND: shown, **{sec: {k: times[k] for k in TIMES[kd]} for kd, sec in HOURS_SECTIONS.items() if kd in TIMES},
            schedule.SECTION: weekly}


LOW_SECTION, EXPORT_SECTION, SOLAR_ADV = "low_tariff", "export_formula_section", "solar_advanced"


def _unsection(user_input: dict, *names: str) -> dict:
    """Folded blocks of a form -> one level, as stored."""
    out = {k: v for k, v in user_input.items() if k not in names}
    for n in names:
        out.update(user_input.get(n) or {})
    return out


def _sectioned(values: dict, blocks: dict[str, list[str]]) -> dict:
    """Stored values -> suggested values for a form with folded blocks."""
    out = dict(values)
    for name, keys in blocks.items():
        out[name] = {k: values[k] for k in keys if k in values}
    return out


def _suggest(hass: HomeAssistant, values: dict, found: dict) -> dict:
    """Detected entities fill only what is still empty."""
    return {**{k: v for k, v in found.items() if v}, **{k: v for k, v in values.items() if v not in (None, "")}}


OT_KEYS = [CONF_CONTROL, CONF_OT_FLOW, CONF_OT_STATE, CONF_OT_MODE, CONF_OT_MAX, CONF_OT_COMM, CONF_OT_STATE_OK, CONF_OT_MODE_HA,
           CONF_OT_MODE_CURVE, CONF_OT_Q_MIN, CONF_OT_MIN_FLOW, CONF_OT_MAX_FLOW, CONF_OT_START_KWH, CONF_OT_MIN_RUN, CONF_OT_MIN_OFF,
           CONF_OT_FOLLOW, CONF_OT_FLOW_TEMP, CONF_OT_CH_ACTIVE, CONF_OT_DHW_ACTIVE, CONF_OT_MAX_STARTS, CONF_OT_QUIET,
           CONF_OT_QUIET_FROM, CONF_OT_QUIET_TO, CONF_OT_QUIET_MAX, CONF_OT_MIN_FLOW_NUM, CONF_OT_MAX_FLOW_NUM]


OT_DEVICE = "ot_device"
OT_MANUAL = "ot_entities"         # section: the box's entities by hand (another gateway, or to correct what was found)
OT_LIMITS = "ot_limits"           # section: lowest and highest flow (folded away when the box keeps its own)
OT_QUIET_SECTION = "ot_quiet_hours"
OT_ENTITY_KEYS = [CONF_OT_FLOW, CONF_OT_STATE, CONF_OT_MODE, CONF_OT_MAX, CONF_OT_COMM, CONF_OT_MIN_RUN, CONF_OT_MIN_OFF,
                  CONF_OT_MIN_FLOW_NUM, CONF_OT_MAX_FLOW_NUM, CONF_OT_FOLLOW, CONF_OT_FLOW_TEMP, CONF_OT_CH_ACTIVE,
                  CONF_OT_DHW_ACTIVE]


def opentherm_schema(manual_open: bool = False, limits_open: bool = True) -> vol.Schema:
    """How Roost steers: a room setpoint on the thermostat, or a flow temperature through an OpenTherm master (any
    master that keeps the agreement: a flow setpoint written every few minutes, a state, a control mode). The box is
    picked as a device and its entities are found on it; by hand only in a folded block."""
    d = DEFAULTS
    entities = vol.Schema({
        vol.Optional(CONF_OT_FLOW): _ent("number"),
        vol.Optional(CONF_OT_STATE): _ent("sensor"),
        vol.Optional(CONF_OT_MODE): _ent(["select", "input_select"]),
        vol.Optional(CONF_OT_MAX): _ent("sensor"),
        vol.Optional(CONF_OT_COMM): _ent("binary_sensor"),
        vol.Optional(CONF_OT_MIN_RUN): _ent(["number", "input_number"]),
        vol.Optional(CONF_OT_MIN_OFF): _ent(["number", "input_number"]),
        vol.Optional(CONF_OT_MIN_FLOW_NUM): _ent(["number", "input_number"]),
        vol.Optional(CONF_OT_MAX_FLOW_NUM): _ent(["number", "input_number"]),
        vol.Optional(CONF_OT_FOLLOW): _ent(["switch", "input_boolean"]),
        vol.Optional(CONF_OT_FLOW_TEMP): _ent("sensor", "temperature"),
        vol.Optional(CONF_OT_CH_ACTIVE): _ent("binary_sensor"),
        vol.Optional(CONF_OT_DHW_ACTIVE): _ent("binary_sensor"),
    })
    return vol.Schema({
        vol.Required(CONF_CONTROL, default=d[CONF_CONTROL]): _sel(CONTROLS, "control"),
        vol.Optional(OT_DEVICE): selector.DeviceSelector(),
        vol.Optional(OT_MANUAL): section(entities, {"collapsed": not manual_open}),
        vol.Required(CONF_OT_MAX_STARTS, default=d[CONF_OT_MAX_STARTS]): _num(0, 24, 1),
        vol.Optional(OT_LIMITS): section(vol.Schema({
            vol.Required(CONF_OT_MIN_FLOW, default=d[CONF_OT_MIN_FLOW]): _num(10, 40, 0.5, "°C"),
            vol.Required(CONF_OT_MAX_FLOW, default=d[CONF_OT_MAX_FLOW]): _num(25, 50, 0.5, "°C"),
        }), {"collapsed": not limits_open}),
        vol.Optional(OT_QUIET_SECTION): section(vol.Schema({
            vol.Required(CONF_OT_QUIET, default=d[CONF_OT_QUIET]): selector.BooleanSelector(),
            vol.Required(CONF_OT_QUIET_FROM, default=d[CONF_OT_QUIET_FROM]): _num(0, 23, 1, "h"),
            vol.Required(CONF_OT_QUIET_TO, default=d[CONF_OT_QUIET_TO]): _num(0, 23, 1, "h"),
            vol.Required(CONF_OT_QUIET_MAX, default=d[CONF_OT_QUIET_MAX]): _num(0.5, 10, 0.1, "kW"),
        }), {"collapsed": True}),
        # starting values Roost replaces with what it measures, and the box's state/option texts: rarely touched
        vol.Optional(ADVANCED): section(vol.Schema({
            vol.Required(CONF_OT_Q_MIN, default=d[CONF_OT_Q_MIN]): _num(0.5, 10, 0.1, "kW"),
            vol.Required(CONF_OT_START_KWH, default=d[CONF_OT_START_KWH]): _num(0, 2, 0.05, "kWh"),
            vol.Required(CONF_OT_STATE_OK, default=d[CONF_OT_STATE_OK]): selector.TextSelector(),
            vol.Required(CONF_OT_MODE_HA, default=d[CONF_OT_MODE_HA]): selector.TextSelector(),
            vol.Required(CONF_OT_MODE_CURVE, default=d[CONF_OT_MODE_CURVE]): selector.TextSelector(),
        }), {"collapsed": True}),
    })


OT_ADVANCED_KEYS = [CONF_OT_Q_MIN, CONF_OT_START_KWH, CONF_OT_STATE_OK, CONF_OT_MODE_HA, CONF_OT_MODE_CURVE]


def detect_opentherm_device(hass: HomeAssistant, device_id: str | None) -> dict:
    """The box's entities found on its device: first by the THRM ONE's names (OT_ENTITY_SUFFIX), then by what they are
    for another gateway: a number in °C about the flow setpoint, a select with a Home Assistant option, a sensor that
    reads home_assistant."""
    if not device_id:
        return {}
    ents = [e for e in er.async_entries_for_device(er.async_get(hass), device_id) if not e.disabled_by]
    out: dict[str, str] = {}
    for key, (domain, suffix) in OT_ENTITY_SUFFIX.items():
        hit = [e.entity_id for e in ents if e.domain == domain and e.entity_id.endswith(suffix)]
        if hit:
            out[key] = sorted(hit, key=len)[0]

    def text(e) -> str:
        return f"{e.entity_id} {e.original_name or ''} {e.name or ''}".lower()
    if CONF_OT_FLOW not in out:
        flows = [e.entity_id for e in ents if e.domain == "number" and any(w in text(e) for w in ("flow", "aanvoer", "ch_setpoint", "control_setpoint"))
                 and "setpoint" in text(e) and "max" not in text(e) and "min" not in text(e)]
        if flows:
            out[CONF_OT_FLOW] = sorted(flows, key=len)[0]
    if CONF_OT_MODE not in out:
        for e in ents:
            st = hass.states.get(e.entity_id)
            if e.domain in ("select", "input_select") and st is not None and "Home Assistant" in (st.attributes.get("options") or []):
                out[CONF_OT_MODE] = e.entity_id
                break
    if CONF_OT_STATE not in out:
        for e in ents:
            st = hass.states.get(e.entity_id)
            if e.domain == "sensor" and st is not None and st.state == DEFAULTS[CONF_OT_STATE_OK]:
                out[CONF_OT_STATE] = e.entity_id
                break
    return out


def _ot_device_of(hass: HomeAssistant, entity_id: str | None) -> str | None:
    ent = er.async_get(hass).async_get(entity_id) if entity_id else None
    return ent.device_id if ent else None


def detect_opentherm(hass: HomeAssistant) -> dict:
    """An OpenTherm master keeping Roost's agreement, by the end of its entity ids (the THRM ONE: number.thrm_one_*_flow_setpoint
    and so on): only when exactly one flow setpoint is found, and the other entities of the same device prefix."""
    flows = [st.entity_id for st in hass.states.async_all("number") if st.entity_id.endswith(OT_ENTITY_SUFFIX[CONF_OT_FLOW][1])]
    if len(flows) != 1:
        return {}
    prefix = flows[0].split(".", 1)[1][: -len(OT_ENTITY_SUFFIX[CONF_OT_FLOW][1])]
    out = {}
    for key, (domain, suffix) in OT_ENTITY_SUFFIX.items():
        eid = f"{domain}.{prefix}{suffix}"
        if hass.states.get(eid) is not None:
            out[key] = eid
    return out


def _check_opentherm(user_input: dict, opts: dict) -> dict[str, str]:
    if user_input.get(CONF_CONTROL) != "opentherm":
        return {} if opts.get(CONF_THERMOSTAT) else {"base": "ot_thermostat"}
    if not all(user_input.get(k) for k in (CONF_OT_FLOW, CONF_OT_STATE, CONF_OT_MODE)):
        return {"base": "ot_entities"}
    if not opts.get(CONF_ROOM):
        return {"base": "ot_room"}
    if float(user_input.get(CONF_OT_MIN_FLOW, 20)) >= float(user_input.get(CONF_OT_MAX_FLOW, 40)):
        return {"base": "ot_limits"}
    return {}


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "")}


def _check_weheat(hass: HomeAssistant, device_id: str) -> bool:
    keys = {e.translation_key for e in er.async_entries_for_device(er.async_get(hass), device_id)}
    return {WEHEAT["state"], WEHEAT["heat"], WEHEAT["elec"]} <= keys


def _check_price(d: dict) -> dict[str, str]:
    return {CONF_IMPORT_PRICE: "price_needed"} if d.get(CONF_PRICE_MODE, "sensor") == "sensor" and not d.get(CONF_IMPORT_PRICE) else {}


def _check_comfort(d: dict, before: dict | None = None) -> dict[str, str]:
    errors = {}
    if schedule.WEEK in d:
        try:
            week = schedule.normalise(d[schedule.WEEK])
            if d.get(schedule.ENABLED) and not any(week.values()):
                errors["base"] = "invalid_schedule"         # no comfort hour in the whole week
        except ValueError:
            errors["base"] = "invalid_schedule"
    elif d.get(schedule.ENABLED):
        errors["base"] = "invalid_schedule"
    # (comfort below the hard floor cannot happen: _flat lets the floor follow comfort down)
    # eco above comfort: refused when one of the two is set now, not for a value kept from before the comfort range
    changed = before is None or any(float(d[k]) != float(before.get(k, d[k])) for k in (CONF_COMFORT, CONF_NIGHT_MIN))
    if changed and float(d[CONF_NIGHT_MIN]) > float(d[CONF_COMFORT]):
        errors[CONF_NIGHT_MIN] = "eco_above_comfort"
    if float(d[CONF_STORE_MAX]) < float(d[CONF_COMFORT]):
        errors[CONF_STORE_MAX] = "store_below_comfort"
    if float(d.get(CONF_SP_MIN, 0)) > float(d[CONF_COMFORT]):
        errors["base"] = "lowest_above_comfort"
    if not d.get(schedule.ENABLED) and int(d.get(CONF_DAY_TO, 22)) <= int(d.get(CONF_DAY_FROM, 7)):
        errors["base"] = "day_order"
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
    elif o.get(CONF_PRICE_MODE) == "epex":
        price = (f"EPEX {o.get(CONF_EPEX_ZONE) or epex.zone_for(hass.config.country)} × {n(o.get(CONF_IMPORT_MULT, 1))}"
                 f" + {n(o.get(CONF_IMPORT_ADD, 0))} {cur}/kWh")
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
        "comfort": f"{_texts(hass)['weekly'] if o.get(schedule.ENABLED) else str(int(o[CONF_DAY_FROM])) + '–' + str(int(o[CONF_DAY_TO]))} · {n(o[CONF_COMFORT])}–{n(max(float(o[CONF_STORE_MAX]), float(o[CONF_COMFORT])))} °C · eco {n(o[CONF_NIGHT_MIN])} °C",
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


ETA_TEXT = {
    "en": {"weekly": "Weekly schedule", "ready": "now.", "lever": "not yet: the setpoint does not move the heat pump (see the repair notice).",
           "following": "not yet: first set the heat pump to follow the thermostat (in the Weheat app).",
           "import": "around {time}, after the Weheat import and the learning that follows, if the self-check then passes.",
           "heating": "around {time}: it needs more heating hours first.",
           "heating_season": "when the heating season starts: too little heating now to check the plan.",
           "check": "maybe at the next self-check, {time}. Until it predicts well enough it learns every night.",
           "importing": "Weheat import: {done} of {total} months, done around {time}.",
           "basis_week": "the last week",
           "unchanged": "↩️ Nothing changed: {part}", "saved": "✅ Saved: {part}", "parts": {"mode": "Mode", "opentherm": "Steering", "house": "The house", "price": "Electricity price",
                                                "solar": "Solar and home battery", "comfort": "Comfort", "notify": "Notifications"},
           "basis_winter": "the last {weeks} heating weeks of the past year, because the last week had too little heating — {passed} of {weeks} good on their own (needs {need}), and the medians below must be within the limits",
           "today": "today", "tomorrow": "tomorrow"},
    "nl": {"weekly": "Weekplanning", "ready": "nu.", "lever": "nog niet: het setpoint stuurt de warmtepomp niet (zie de reparatiemelding).",
           "following": "nog niet: zet de warmtepomp eerst op het volgen van de thermostaat (in de Weheat-app).",
           "import": "rond {time}, na de Weheat-import en het leren daarna, als de zelfcontrole dan slaagt.",
           "heating": "rond {time}: er zijn eerst meer stookuren nodig.",
           "heating_season": "als het stookseizoen begint: nu wordt te weinig gestookt om het plan te controleren.",
           "check": "mogelijk bij de volgende zelfcontrole, {time}. Tot hij goed genoeg voorspelt leert hij elke nacht bij.",
           "importing": "Weheat-import: {done} van {total} maanden, klaar rond {time}.",
           "basis_week": "de afgelopen week",
           "unchanged": "↩️ Niets gewijzigd: {part}", "saved": "✅ Opgeslagen: {part}", "parts": {"mode": "Modus", "opentherm": "Sturing", "house": "Huis en thermostaat", "price": "Stroomprijs",
                                                    "solar": "Zon en thuisaccu", "comfort": "Comfort", "notify": "Meldingen"},
           "basis_winter": "de laatste {weeks} stookweken van het afgelopen jaar, omdat de afgelopen week te weinig stookte — {passed} van {weeks} los goed (nodig: {need}), en de medianen hieronder moeten binnen de grenzen liggen",
           "today": "vandaag", "tomorrow": "morgen"},
    "de": {"weekly": "Wochenplan", "ready": "jetzt.", "lever": "noch nicht: der Sollwert bewegt die Wärmepumpe nicht (siehe die Reparaturmeldung).",
           "following": "noch nicht: stelle die Wärmepumpe zuerst so ein, dass sie dem Thermostat folgt (in der Weheat-App).",
           "import": "gegen {time}, nach dem Weheat-Import und dem Lernen danach, wenn die Selbstprüfung dann besteht.",
           "heating": "gegen {time}: es braucht erst mehr Heizstunden.",
           "heating_season": "wenn die Heizsaison beginnt: jetzt wird zu wenig geheizt, um den Plan zu prüfen.",
           "check": "vielleicht bei der nächsten Selbstprüfung, {time}. Bis es gut genug vorhersagt, lernt es jede Nacht.",
           "importing": "Weheat-Import: {done} von {total} Monaten, fertig gegen {time}.",
           "basis_week": "der letzten Woche",
           "unchanged": "↩️ Nichts geändert: {part}", "saved": "✅ Gespeichert: {part}", "parts": {"mode": "Modus", "opentherm": "Steuerung", "house": "Haus und Thermostat", "price": "Strompreis",
                                                    "solar": "Solar und Heimspeicher", "comfort": "Komfort", "notify": "Benachrichtigungen"},
           "basis_winter": "den letzten {weeks} Heizwochen des vergangenen Jahres, weil die letzte Woche zu wenig geheizt hat — {passed} von {weeks} einzeln gut (nötig: {need}), und die Mediane unten müssen innerhalb der Grenzen liegen",
           "today": "heute", "tomorrow": "morgen"},
    "fr": {"weekly": "Planning hebdomadaire", "ready": "maintenant.", "lever": "pas encore : la consigne ne fait pas varier la pompe à chaleur (voir la notification de réparation).",
           "following": "pas encore : réglez d'abord la pompe à chaleur pour suivre le thermostat (dans l'application Weheat).",
           "import": "vers {time}, après l'import Weheat et l'apprentissage qui suit, si l'auto-contrôle réussit alors.",
           "heating": "vers {time} : il faut d'abord plus d'heures de chauffe.",
           "heating_season": "au début de la saison de chauffe : trop peu de chauffe maintenant pour vérifier le plan.",
           "check": "peut-être au prochain auto-contrôle, {time}. Tant qu'il ne prévoit pas assez bien, il apprend chaque nuit.",
           "importing": "Import Weheat : {done} sur {total} mois, terminé vers {time}.",
           "basis_week": "la dernière semaine",
           "unchanged": "↩️ Rien de modifié : {part}", "saved": "✅ Enregistré : {part}", "parts": {"mode": "Mode", "opentherm": "Pilotage", "house": "La maison et le thermostat", "price": "Prix de l'électricité",
                                                     "solar": "Solaire et batterie domestique", "comfort": "Confort", "notify": "Notifications"},
           "basis_winter": "les {weeks} dernières semaines de chauffe de l'année passée, car la dernière semaine a trop peu chauffé — {passed} sur {weeks} bonnes à elles seules (requis : {need}), et les médianes ci-dessous doivent être dans les limites",
           "today": "aujourd'hui", "tomorrow": "demain"},
}


def _texts(hass: HomeAssistant) -> dict:
    """The in-code texts in the user's language (English when Roost does not speak it)."""
    lang = (hass.config.language or "en")[:2]
    return ETA_TEXT.get(lang, ETA_TEXT["en"])


def _eta_text(hass: HomeAssistant, mgr) -> str:
    """Expected ready to steer, as a sentence in the user's language."""
    t = _texts(hass)
    if mgr is None:
        return "—"
    code, when = mgr.notices.ready_eta()
    text = t[code] if when is None else t[code].format(time=_when(t, when))
    if mgr.wh.importing:
        done, total, end = mgr.wh.import_progress()
        text += "\n" + t["importing"].format(done=done, total=total, time=_when(t, end) if end else "—")
    return text


def _when(t: dict, when) -> str:
    from homeassistant.util import dt as dt_util
    today = dt_util.now().date()
    day = t["today"] if when.date() == today else t["tomorrow"] if (when.date() - today).days == 1 else when.strftime("%d-%m")
    return f"{day} {when:%H:%M}"


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


class RoostConfigFlow(AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Setup in steps by subject: heat pump and thermostat, the house, the price, solar and battery, comfort.
    After the first screen Weheat's login page: Roost keeps its own Weheat login (read-only history), through the app
    registration the Weheat integration already has. Reauth when it is missing or expired."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        return {"scope": "openid offline_access"}

    async def _async_login(self) -> ConfigFlowResult:
        """Weheat's login page, with the app registration the Weheat integration already has (nothing to fill in);
        without one, Roost's own application credentials (Home Assistant asks for them)."""
        impl = await weheat_implementation(self.hass)
        if impl is None:
            self._auth_from = DOMAIN
            return await self.async_step_pick_implementation()
        self.flow_impl, self._auth_from = impl, "weheat"
        return await self.async_step_auth()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """No Weheat login yet (an install from before 0.5.3), or it expired: log in with the Weheat account."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self._async_login()

    async def async_oauth_create_entry(self, data: dict) -> ConfigFlowResult:
        """The Weheat login came back: check it sees this heat pump, keep it in the entry's data."""
        entry = self._get_reauth_entry() if self.source == SOURCE_REAUTH else None
        pump, _ = heat_pump_id(self.hass, (entry.data if entry else self._data).get(CONF_HEAT_PUMP))
        if await _sees_pump(self.hass, data["token"]["access_token"], pump) is False:
            return self.async_abort(reason="wrong_account")
        login = {"auth_implementation": data["auth_implementation"], "token": data["token"], CONF_AUTH_FROM: self._auth_from}
        if entry is not None:
            return self.async_update_reload_and_abort(entry, data_updates=login)
        self._data.update(login)
        return await self.async_step_house()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {"room": RoomSubentryFlow}

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, Any] = {}
        self._auth_from = DOMAIN

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
                if await weheat_implementation(self.hass) is not None:
                    return await self._async_login()
                return await self.async_step_house()        # no app registration to use: Roost asks later (reauth)
        return self._form("user", start_schema(), _suggest(self.hass, user_input or {}, {CONF_THERMOSTAT: detect.thermostat(self.hass)}), errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Another heat pump or thermostat, without removing Roost (what it learned stays: the house is the same)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        schema = vol.Schema({
            vol.Required(CONF_HEAT_PUMP): selector.DeviceSelector(selector.DeviceSelectorConfig(integration="weheat")),
            vol.Optional(CONF_THERMOSTAT): _ent("climate"),
        })
        if user_input is not None:
            pump = user_input[CONF_HEAT_PUMP]
            if not _check_weheat(self.hass, pump):
                errors[CONF_HEAT_PUMP] = "not_weheat"
            elif any(e.unique_id == pump and e.entry_id != entry.entry_id for e in self._async_current_entries()):
                return self.async_abort(reason="already_configured")
            else:
                data = {k: v for k, v in entry.data.items() if k not in (CONF_HEAT_PUMP, CONF_THERMOSTAT)}
                data.update(_clean(user_input))
                return self.async_update_reload_and_abort(entry, data=data, unique_id=pump)
        values = {k: entry.data[k] for k in (CONF_HEAT_PUMP, CONF_THERMOSTAT) if entry.data.get(k)}
        return self._form("reconfigure", schema, user_input or values, errors)

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
                if user_input.get(CONF_PRICE_MODE) == "epex":
                    return await self.async_step_price_epex()
                return await self.async_step_solar()
        imp, exp = detect.prices(self.hass)
        return self._form("price", price_mode_schema(), _suggest(self.hass, user_input or {}, {CONF_IMPORT_PRICE: imp, CONF_EXPORT_PRICE: exp}), errors)

    async def async_step_price_epex(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(_clean(_unsection(user_input, EXPORT_SECTION)))
            return await self.async_step_solar()
        return self.async_show_form(step_id="price_epex", data_schema=price_epex_schema(self.hass.config.currency or "EUR", self.hass.config.country))

    async def async_step_price_fixed(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(_clean(_unsection(user_input, LOW_SECTION)))
            return await self.async_step_solar()
        return self.async_show_form(step_id="price_fixed", data_schema=price_schema(self.hass.config.currency or "EUR"))

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if user_input.get(CONF_HAS_SOLAR) or user_input.get(CONF_HAS_BATTERY):
                return await self.async_step_solar_details()
            return await self.async_step_comfort()
        found = {**detect.energy(self.hass), **await detect.async_energy_dashboard(self.hass)}
        return self._form("solar", solar_schema(), {CONF_HAS_SOLAR: bool(found.get(CONF_PV_POWER) or found.get(CONF_PV_FORECAST)),
                                                     CONF_HAS_BATTERY: bool(found.get(CONF_BATTERY_SOC))})

    async def async_step_solar_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = solar_details_schema(bool(self._data.get(CONF_HAS_SOLAR)), bool(self._data.get(CONF_HAS_BATTERY)))
        if user_input is not None:
            self._data.update(_clean(_unsection(user_input, SOLAR_ADV)))
            return await self.async_step_comfort()
        found = {**detect.energy(self.hass), **await detect.async_energy_dashboard(self.hass)}
        return self._form("solar_details", schema, _sectioned(found, {SOLAR_ADV: [CONF_GRID_SIGN, CONF_GRID_PREFERENCE]}))

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        shown = getattr(self, "_days_kind", None)
        if user_input is not None:
            kind = user_input.get(DAYS_KIND, shown)
            flat = _flat(user_input)
            errors = _times_missing(user_input) or _check_comfort(flat)
            if not errors:
                data = {**self._data, **_clean(flat)}
                title = data.pop(CONF_NAME, "Roost")
                return self.async_create_entry(title=title, data=data)
            return self._form("comfort", comfort_schema(kind or "same"), _nested(flat, kind), errors)
        found = await _comfort_from_history(self.hass, self._data.get(CONF_THERMOSTAT))
        values = _nested(found or {})
        self._days_kind = values[DAYS_KIND]
        return self._form("comfort", comfort_schema(self._days_kind), values, errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RoostOptionsFlow()


class RoostOptionsFlow(OptionsFlow):
    """The same subjects as a menu with what is set now; each part saves when it is submitted. Order: what is
    changed often first (mode, comfort, price, solar, notifications), what is set once at the end (house, steering)."""

    def __init__(self) -> None:
        self._opts: dict[str, Any] | None = None
        self._saved: str | None = None

    @property
    def opts(self) -> dict[str, Any]:
        if self._opts is None:
            self._opts = {k: v for k, v in {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}.items()
                          if k not in LOGIN_KEYS}      # the Weheat login stays in the entry's data only
            o = self._opts
            o.setdefault(CONF_HAS_SOLAR, bool(o.get(CONF_PV_POWER) or o.get(CONF_PV_FORECAST) or o.get(CONF_GRID_POWER)))
            o.setdefault(CONF_HAS_BATTERY, bool(o.get(CONF_BATTERY_SOC)))
        return self._opts

    def _update(self, schema: vol.Schema, user_input: dict) -> None:
        for key in schema.schema:
            if str(key) == schedule.SECTION and schedule.SECTION in user_input:
                self.opts.pop(schedule.ENABLED, None)
                self.opts.pop(schedule.WEEK, None)
            if str(key) == ADVANCED:
                for k in ADVANCED_KEYS:
                    self.opts.pop(k, None)
            self.opts.pop(str(key), None)
        self.opts.update(_clean(_flat(user_input)))

    async def _async_saved(self, part: str | None = None) -> ConfigFlowResult:
        """A part was submitted: save it right away (closing the window loses nothing) and go back to the menu."""
        cur: Mapping[str, Any] = self.cur_step or {}
        step = cur.get("step_id", "")
        part = part or step
        # a field left empty is gone: also from what the setup stored, which the options are laid over (#3)
        data = {k: v for k, v in self.config_entry.data.items() if k in LOGIN_KEYS or k in self.opts}
        changed = self.hass.config_entries.async_update_entry(self.config_entry, data=data, options=dict(self.opts))
        # sent as shown: nothing stored, Roost not reloaded — the way back to the menu (forms have no back button)
        self._saved = part if changed else f"{UNCHANGED}{part}"
        return await self.async_step_init()

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        rooms = sum(1 for s in self.config_entry.subentries.values() if s.subentry_type == "room")
        t = _texts(self.hass)
        part = (self._saved or "").removeprefix(UNCHANGED)
        key = "unchanged" if (self._saved or "").startswith(UNCHANGED) else "saved"
        saved = t[key].format(part=t["parts"].get(part, part)) + "\n\n" if self._saved else ""
        return self.async_show_menu(step_id="init", menu_options=["mode", "comfort", "price", "solar", "notify", "house", "opentherm", "done"],
                                    description_placeholders={**_summary(self.hass, self.opts, rooms), "saved": saved})

    async def async_step_done(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(data=dict(self.opts))

    async def async_step_mode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Off, shadow or active, with what the self-check says: here, in Roost itself."""
        mgr = getattr(self.config_entry, "runtime_data", None)
        if user_input is not None:
            same = mgr is None or user_input["mode"] == mgr.mode
            if mgr is not None and not same:
                await mgr.async_set_mode(user_input["mode"])
            self._saved = f"{UNCHANGED}mode" if same else "mode"
            return await self.async_step_init()
        c = mgr.check if mgr else {}
        ok, no = "✅", "⏳"
        missing = set(mgr.ready_missing) if mgr else {"temperature"}
        w = c.get("winter") if c.get("heating_hours", 0) < check.READY_HEATING_HOURS else None
        t = _texts(self.hass)
        if w:                       # mild weather: judged on the last heating weeks
            c = {**c, "rmse_6h": w.get("rmse_6h"), "heat_ratio": w.get("heat_ratio")}
            passed = check.winter_ok(w)
            missing = missing | ({"temperature", "heat"} if not passed else set())
        ph = {"plan_error": f"{c['rmse_6h']:.2f}" if c.get("rmse_6h") is not None else "—", "plan_ok": no if "temperature" in missing else ok,
              "hours": f"{w.get('weeks', 0)} × {check.WINTER_WEEK_HOURS}+" if w else str(c.get("heating_hours", 0)),
              "hours_ok": no if "heating_hours" in missing else ok,
              "heat": f"{c['heat_ratio']:.2f}" if c.get("heat_ratio") is not None else "—", "heat_ok": no if "heat" in missing else ok,
              "basis": t["basis_winter"].format(passed=w.get("passed", 0), weeks=w.get("weeks", 0), need=check.WINTER_PASS)
              if w else t["basis_week"],
              "follows": no if "following" in missing else ok, "lever": no if "lever" in missing else ok,
              "verdict": ok if mgr and mgr.ready else no, "eta": _eta_text(self.hass, mgr)}
        schema = vol.Schema({vol.Required("mode", default=mgr.mode if mgr else "shadow"): _sel(["off", "shadow", "active"], "mode")})
        return self.async_show_form(step_id="mode", data_schema=schema, description_placeholders=ph)

    async def async_step_opentherm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """How Roost steers: the thermostat, or the flow through an OpenTherm master. The box is a device; its
        entities are found on it (by hand only in the folded block, for another gateway or to correct)."""
        errors: dict[str, str] = {}
        device = None
        shown_dev, shown_ents = getattr(self, "_ot_shown", (None, {}))
        if user_input is not None:
            device = user_input.get(OT_DEVICE)
            block = {k: v for k, v in (user_input.get(OT_MANUAL) or {}).items() if v}
            found = detect_opentherm_device(self.hass, device)
            if device and device != shown_dev:
                # another box: what it has, and only what was changed by hand in the block (not what was shown)
                manual = {k: v for k, v in block.items() if v != shown_ents.get(k)}
            else:
                manual, found = block, ({} if OT_MANUAL in user_input else found)     # the block as left is the truth
            flat = {k: v for k, v in user_input.items() if k not in (ADVANCED, OT_DEVICE, OT_MANUAL, OT_LIMITS, OT_QUIET_SECTION)}
            flat.update({k: self.opts[k] for k in OT_ADVANCED_KEYS if k in self.opts})     # a section left out: kept
            flat.update({k: self.opts[k] for k in (CONF_OT_MIN_FLOW, CONF_OT_MAX_FLOW, CONF_OT_QUIET, CONF_OT_QUIET_FROM,
                                                   CONF_OT_QUIET_TO, CONF_OT_QUIET_MAX) if k in self.opts})
            for sec in (ADVANCED, OT_LIMITS, OT_QUIET_SECTION):
                flat.update(user_input.get(sec) or {})
            flat.update({k: v for k, v in user_input.items() if k in OT_ENTITY_KEYS and v})    # the form of before
            flat.update({**found, **manual})                 # what was picked by hand wins over what was found
            errors = _check_opentherm(flat, self.opts)
            if not errors:
                for k in OT_KEYS:
                    self.opts.pop(k, None)
                self.opts.update(_clean(flat))
                return await self._async_saved()
        o = {**self.opts, **(_clean(flat) if user_input is not None else {})}    # after an error: what was just entered
        device = device or _ot_device_of(self.hass, o.get(CONF_OT_FLOW)) or _ot_device_of(self.hass, detect_opentherm(self.hass).get(CONF_OT_FLOW))
        found = detect_opentherm_device(self.hass, device) or detect_opentherm(self.hass)
        ents = {**{k: v for k, v in found.items() if not o.get(k)}, **{k: o[k] for k in OT_ENTITY_KEYS if o.get(k)}}
        missing = [k for k in (CONF_OT_FLOW, CONF_OT_STATE, CONF_OT_MODE) if not ents.get(k)]
        box_limits = bool(ents.get(CONF_OT_MIN_FLOW_NUM) and ents.get(CONF_OT_MAX_FLOW_NUM))
        values = {**{k: v for k, v in o.items() if k not in OT_ENTITY_KEYS}, OT_DEVICE: device, OT_MANUAL: ents,
                  OT_LIMITS: {k: o[k] for k in (CONF_OT_MIN_FLOW, CONF_OT_MAX_FLOW) if k in o},
                  OT_QUIET_SECTION: {k: o[k] for k in (CONF_OT_QUIET, CONF_OT_QUIET_FROM, CONF_OT_QUIET_TO, CONF_OT_QUIET_MAX) if k in o},
                  ADVANCED: {k: o[k] for k in OT_ADVANCED_KEYS if k in o}}
        values = {k: v for k, v in values.items() if v is not None}
        lines = [f"✓ {detect.friendly(self.hass, ents[k])}" for k in OT_ENTITY_KEYS if ents.get(k)]
        self._ot_shown = (device, dict(ents))
        schema = opentherm_schema(manual_open=bool(missing) and o.get(CONF_CONTROL) == "opentherm", limits_open=not box_limits)
        return self.async_show_form(step_id="opentherm", data_schema=self.add_suggested_values_to_schema(schema, values),
                                    errors=errors, description_placeholders={"found": "\n".join(lines) or "—"})

    async def async_step_house(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = house_schema(True, self.opts.get(CONF_CONTROL) != "opentherm")
        if user_input is not None:
            self._update(schema, user_input)
            return await self._async_saved()
        values = {**self.opts, CONF_EMITTERS: curve.emitter_ticks(self.opts)}     # the single choice of before, as ticks
        return self.async_show_form(step_id="house", data_schema=self.add_suggested_values_to_schema(schema, values))

    async def async_step_price(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """One screen: the kind of price and its block; the other blocks are left as they were."""
        errors: dict[str, str] = {}
        mode = self.opts.get(CONF_PRICE_MODE, DEFAULTS[CONF_PRICE_MODE])
        currency, country = self.hass.config.currency or "EUR", self.hass.config.country
        if user_input is not None:
            mode = user_input.get(CONF_PRICE_MODE, mode)
            block = {k: v for k, v in (user_input.get(PRICE_SECTIONS[mode]) or {}).items() if v not in (None, "")}
            if mode == "sensor" and not block.get(CONF_IMPORT_PRICE):
                errors["base"] = "price_needed"
            elif mode == "fixed" and block.get(CONF_FIXED_PRICE) is None:
                errors["base"] = "fixed_price_needed"
            if not errors:
                for k in PRICE_KEYS[mode]:
                    self.opts.pop(k, None)
                self.opts[CONF_PRICE_MODE] = mode
                self.opts.update(_clean(block))
                return await self._async_saved()
        values = {CONF_PRICE_MODE: mode, **{sec: {k: self.opts[k] for k in PRICE_KEYS[m] if self.opts.get(k) not in (None, "")}
                                            for m, sec in PRICE_SECTIONS.items()}}
        if user_input is not None:          # after an error: what was just entered
            values.update({k: v for k, v in user_input.items() if k in (CONF_PRICE_MODE, *PRICE_SECTIONS.values())})
        return self.async_show_form(step_id="price", data_schema=self.add_suggested_values_to_schema(
            price_options_schema(currency, country, mode), values), errors=errors)

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        o = self.opts
        if user_input is not None:
            sol, bat = user_input.get(SOLAR_SECTION) or {}, user_input.get(BATTERY_SECTION) or {}
            # a block off forgets its sensors; the battery's one setting (not a sensor) stays while the block stays
            # off, so a form sent as shown changes nothing (solar_from_battery's default without a battery)
            keep = [CONF_SOLAR_FROM_SOC] if not bat.get(CONF_HAS_BATTERY) else []
            for k in SOLAR_KEYS + BATTERY_KEYS + [CONF_HAS_SOLAR, CONF_HAS_BATTERY, CONF_GRID_PREFERENCE]:
                if k not in keep:
                    o.pop(k, None)
            o.update(_clean({k: v for k, v in sol.items() if sol.get(CONF_HAS_SOLAR) or k == CONF_HAS_SOLAR}))
            o.update(_clean({k: v for k, v in bat.items() if bat.get(CONF_HAS_BATTERY) or k == CONF_HAS_BATTERY}))
            o.update(_clean({k: v for k, v in user_input.items() if k not in (SOLAR_SECTION, BATTERY_SECTION, SOLAR_ADV)}))
            o.update(_clean(user_input.get(SOLAR_ADV) or {}))
            return await self._async_saved()
        solar, battery = bool(o.get(CONF_HAS_SOLAR)), bool(o.get(CONF_HAS_BATTERY))
        # detected sensors only for a block not set up yet: in a block already set up, a field left empty was emptied
        # on purpose and must not come back filled in (#3)
        dash = await detect.async_energy_dashboard(self.hass)
        found: dict[str, Any] = {k: v for k, v in {**detect.energy(self.hass), **dash}.items()
                 if not ((solar and k in SOLAR_KEYS) or (battery and k in BATTERY_KEYS))}
        if not (solar or battery) and dash:      # the Energy dashboard knows the house: the blocks open, ticked
            found.update({CONF_HAS_SOLAR: bool(dash.get(CONF_PV_POWER)), CONF_HAS_BATTERY: bool(dash.get(CONF_BATTERY_SOC) or dash.get(CONF_BATTERY_POWER))})
            solar, battery = bool(found[CONF_HAS_SOLAR]), bool(found[CONF_HAS_BATTERY])
        values = _suggest(self.hass, o, found)
        suggested = {SOLAR_SECTION: {k: values[k] for k in [CONF_HAS_SOLAR] + SOLAR_KEYS if k in values},
                     BATTERY_SECTION: {k: values[k] for k in [CONF_HAS_BATTERY] + BATTERY_KEYS if k in values},
                     SOLAR_ADV: {k: values[k] for k in (CONF_GRID_SIGN, CONF_GRID_PREFERENCE) if k in values}}
        return self.async_show_form(step_id="solar", data_schema=self.add_suggested_values_to_schema(
            solar_options_schema(solar, battery), suggested))

    async def async_step_notify(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Notifications: off until the user picks where they go (a notify entity, or a notify service such as
        notify.mobile_app_phone); the weekly summary on top of that."""
        schema = vol.Schema({vol.Optional(CONF_NOTIFY, default=""): selector.TextSelector(),
                             vol.Required(CONF_WEEKLY, default=False): selector.BooleanSelector()})
        if user_input is not None:
            for k, v in ((CONF_NOTIFY, str(user_input.get(CONF_NOTIFY) or "").strip()), (CONF_WEEKLY, bool(user_input.get(CONF_WEEKLY)))):
                if v or k in self.opts:             # off and never set: nothing to store (sent as shown changes nothing)
                    self.opts[k] = v
            return await self._async_saved()
        return self.async_show_form(step_id="notify", data_schema=self.add_suggested_values_to_schema(
            schema, {CONF_NOTIFY: self.opts.get(CONF_NOTIFY, ""), CONF_WEEKLY: bool(self.opts.get(CONF_WEEKLY))}))

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        ot = self.opts.get(CONF_CONTROL) == "opentherm"
        shown = days_kind(self.opts)
        if user_input is not None:
            kind = user_input.get(DAYS_KIND, shown)
            flat = _flat(user_input)
            errors = _times_missing(user_input) or _check_comfort({**{k: self.opts[k] for k in (CONF_DAY_FROM, CONF_DAY_TO) if k in self.opts}, **flat}, self.opts)
            if not errors:
                for k in (*ADVANCED_KEYS, schedule.ENABLED, schedule.WEEK) if DAYS_KIND in user_input else ():
                    if k in ADVANCED_KEYS and ot and k in THERMOSTAT_ONLY:
                        continue                            # not on the form: kept
                    self.opts.pop(k, None)
                self._update(comfort_schema(kind, ot), user_input)
                if not flat.get(schedule.ENABLED):
                    self.opts[schedule.ENABLED] = False
                return await self._async_saved()
            shown, values = kind, _nested({**self.opts, **flat}, kind)       # after an error: what was just entered
        else:
            values = _nested(self.opts, shown)
        return self.async_show_form(step_id="comfort", data_schema=self.add_suggested_values_to_schema(
            comfort_schema(shown, ot), values), errors=errors)
