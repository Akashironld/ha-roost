"""What the parts of the Roost runtime share: imports, constants and small helpers (manager.py and the parts it holds)."""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any, Callable

from aiohttp import ClientTimeout
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder import history as rh
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import (
    building,
    check,
    comfort,
    control,
    epex,
    heatpump,
    history,
    lookback,
    model,
    planner,
    response,
    rooms,
    schedule,
    series,
    stick,
    sun,
    value,
    window,
)
from . import weather as om
from .const import (
    AWAY_MIN,
    CONF_BASELINE_NIGHT,
    CONF_BATTERY_KWH,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_COMFORT,
    CONF_DAY_FROM,
    CONF_DAY_MIN,
    CONF_DAY_TO,
    CONF_EMITTER,
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
    CONF_HEAT_PUMP,
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
    CONF_WINDOW_SENSORS,
    DEFAULTS,
    DOMAIN,
    LEARN_HOUR,
    LEARN_MINUTE,
    PLAN_MINUTES,
    STORAGE_VERSION,
    TICK_SECONDS,
    WEATHER_MINUTES,
    WEHEAT,
    WEHEAT_IMPORT_DAYS,
)
from .reasons import Reason
from .util import num as _f
from .weheat_api import (
    WeheatLoginNeeded,
    WeheatUnavailable,
    async_fetch_history,
    async_fetch_months,
    heat_pump_id,
)

_LOGGER = logging.getLogger(f"{__package__}.manager")   # the name it always had (log settings, bug reports)
HOUR_LOG_KEPT = 7 * 24 + 2                       # a week of hours: the replay of yesterday and the look back
PLAN_LOG_KEPT = 48                               # the plan's inputs per hour (2 days): to replay a decision exactly
HYBRID_MAX_ABOVE = 0.5                           # a hybrid: the setpoint at most this above the room (no gas boiler for storing)
SAVING_DETAIL_DAYS = 7                           # the saving per hour of the last days (roost.explain_saving, the report)


def _iso_ts(v) -> float:
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except (TypeError, ValueError):
        return 0.0
DHW_STATES = ("dhw", "legionella_prevention")
DHW_WEEKS = 8                 # hot water profile from the last weeks
EVENTS_KEPT = 300             # what Roost did, for a bug report
SP_HIST_DAYS = 120            # own record of the thermostat's setpoint per hour
NO_LEVER_KW = 0.2             # learned gain below this (kW per °C): the setpoint hardly moves the heat pump
HISTORY_KEEP_DAYS = 400       # Weheat hours and past weather kept: a year for learning, and a month to spare
WEHEAT_FIELDS = 4             # 2: the setpoint per hour; 3: flow and return temperature; 4: thermostat demand, backup
                              # heater, boiler, compressor limits, errors, flow rate (history.EXTRA_LOGS)
NOT_FOLLOWING_MIN = 45
ROOM_SILENT_MIN = 30
FALLBACK_MIN = 60           # no plan for this long (no price, room or weather): a fallback instead of the last setpoint
FALLBACK_NOTICE_H = 3       # ... and a notice when it lasts this long
MIN_RUN_MIN = 40            # the unit started heating less than this ago: Roost does not lower the setpoint yet
HOUSE_COLD_K = 0.5          # the room this far below its minimum ...
HOUSE_COLD_MIN = 60         # ... for this long while Roost steers: a notice


def _i(v: Any) -> int | None:
    x = _f(v)
    return None if x is None else int(x)




@dataclass
class Health:
    not_following_since: float | None = None
    room_missing_since: float | None = None
    house_cold_since: float | None = None
    issues: set = field(default_factory=set)

__all__ = [  # what the parts of the runtime take from here (explicit imports, no star)
    "ATTR_ENTITY_ID", "ATTR_UNIT_OF_MEASUREMENT", "AWAY_MIN", "Any", "CONF_BASELINE_NIGHT",
    "CONF_BATTERY_KWH", "CONF_BATTERY_POWER", "CONF_BATTERY_SOC", "CONF_SOLAR_FROM_SOC",
    "CONF_COMFORT", "CONF_DAY_FROM", "CONF_DAY_MIN", "CONF_DAY_TO", "CONF_EMITTER", "CONF_EPEX_ZONE",
    "CONF_EXPORT_ADD", "CONF_EXPORT_FORMULA", "CONF_EXPORT_MULT", "CONF_EXPORT_PRICE", "CONF_FIXED_EXPORT_PRICE",
    "CONF_FIXED_LOW_PRICE", "CONF_FIXED_PRICE", "CONF_GRID_POWER", "CONF_GRID_PREFERENCE", "CONF_GRID_SIGN",
    "CONF_HEAT_PUMP", "CONF_IMPORT_ADD", "CONF_IMPORT_MULT", "CONF_IMPORT_ON_SETUP", "CONF_IMPORT_PRICE",
    "CONF_LOW_FROM", "CONF_LOW_TO", "CONF_LOW_WEEKEND", "CONF_MAX_ABOVE", "CONF_MIN_INTERVAL", "CONF_NIGHT_MIN",
    "CONF_PAUSE_HOURS", "CONF_PRICE_MODE", "CONF_PV_FORECAST", "CONF_PV_FORECAST_TOMORROW", "CONF_PV_POWER",
    "CONF_ROOM", "CONF_SP_MIN", "CONF_STORE_MAX", "CONF_THERMOSTAT", "CONF_USE_BAG", "CONF_WEATHER",
    "CONF_WEATHER_SOURCE", "CONF_WINDOW_SENSORS", "Callable", "ClientTimeout", "ConfigEntry", "Context", "DEFAULTS",
    "DHW_STATES",
    "DHW_WEEKS", "DOMAIN", "EVENTS_KEPT", "EVENT_HOMEASSISTANT_STOP", "Event", "EventStateChangedData", "FALLBACK_MIN",
    "FALLBACK_NOTICE_H",
    "HISTORY_KEEP_DAYS", "HOUR_LOG_KEPT", "HOUSE_COLD_K", "HOUSE_COLD_MIN", "HYBRID_MAX_ABOVE", "Health",
    "HomeAssistant", "LEARN_HOUR", "LEARN_MINUTE", "MIN_RUN_MIN", "NOT_FOLLOWING_MIN", "NO_LEVER_KW",
    "PLAN_LOG_KEPT", "PLAN_MINUTES", "ROOM_SILENT_MIN", "Reason", "SAVING_DETAIL_DAYS", "SP_HIST_DAYS",
    "STATE_UNAVAILABLE", "STATE_UNKNOWN", "STORAGE_VERSION", "State", "Store", "TICK_SECONDS", "UnitOfTemperature",
    "WEATHER_MINUTES", "WEHEAT", "WEHEAT_FIELDS", "WEHEAT_IMPORT_DAYS", "WeheatLoginNeeded", "WeheatUnavailable",
    "_LOGGER", "_f", "_i", "_iso_ts", "async_fetch_history", "async_fetch_months", "async_get_clientsession",
    "async_track_state_change_event", "async_track_time_change", "async_track_time_interval", "asyncio",
    "building", "callback", "check", "comfort", "control", "datetime", "deque", "dt_util", "epex", "er",
    "get_instance", "heat_pump_id", "heatpump", "history", "ir", "lookback", "model", "om", "partial", "planner",
    "replace", "response", "rh", "rooms", "schedule", "series", "stick", "sun", "time", "timedelta", "timezone",
    "traceback", "value", "window",
]
