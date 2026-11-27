"""Constants for Roost."""
from __future__ import annotations

DOMAIN = "roost"
STORAGE_VERSION = 1
CARD_URL = "/roost/roost-card.js"

# setup
CONF_HEAT_PUMP = "heat_pump"            # device id of the Weheat heat pump
CONF_THERMOSTAT = "thermostat"
CONF_PUMP_ENTITIES = "pump_entities"    # {role: entity_id}: the user's choice over the entities found on the device
CONF_ROOM = "room_temperature"
CONF_IMPORT_PRICE = "import_price"
CONF_EXPORT_PRICE = "export_price"
CONF_GRID_POWER = "grid_power"
CONF_GRID_SIGN = "grid_sign"            # import_positive | export_positive
CONF_PV_POWER = "pv_power"
CONF_PV_FORECAST = "pv_forecast"
CONF_PV_FORECAST_TOMORROW = "pv_forecast_tomorrow"
CONF_BATTERY_SOC = "battery_soc"
CONF_BATTERY_POWER = "battery_power"    # + = discharging
CONF_BATTERY_KWH = "battery_kwh"
CONF_SOLAR_FROM_SOC = "solar_from_battery"   # % charge of the home battery from which solar surplus is free for the heat pump
CONF_HOUSE_POWER = "house_power"
CONF_WEATHER_SOURCE = "weather_source"  # open_meteo | entity
CONF_WEATHER = "weather_entity"
CONF_IMPORT_ON_SETUP = "import_weheat_history"
CONF_HAS_SOLAR = "has_solar"            # setup: show the solar fields
CONF_HAS_BATTERY = "has_battery"        # setup: show the home battery fields
CONF_EMITTER = "emitter"                # floor | radiators | both: starting values and wording (before the ticks below)
CONF_EMITTERS = "emitters"              # what the house has, ticked: floor, radiators, lt_radiators, fan_coils
CONF_WINDOW_SENSORS = "window_sensors"  # optional: window/door sensors (a window open: Roost waits, does not learn from it)
CONF_USE_BAG = "use_bag"                # opt-in: building data from the Dutch register (PDOK)
CONF_WEHEAT_AUTH = "weheat_auth"           # 0.5.2 only (the login choice): kept out of the options, nothing reads it
CONF_AUTH_FROM = "auth_from"               # Roost's Weheat login: whose app registration ("weheat": the Weheat integration's, or "roost")
CONF_PRICE_MODE = "price_mode"          # sensor (dynamic, with a forecast) | epex (built in) | fixed (a contract)
CONF_EPEX_ZONE = "epex_zone"            # bidding zone for the built-in day-ahead prices
CONF_IMPORT_MULT = "import_mult"        # built-in prices: what a kWh costs = day-ahead × multiplier + fixed amount
CONF_IMPORT_ADD = "import_add"
CONF_EXPORT_FORMULA = "export_formula"  # export by its own formula (off: net metering, export worth the import price)
CONF_EXPORT_MULT = "export_mult"
CONF_EXPORT_ADD = "export_add"
CONF_FIXED_PRICE = "fixed_price"        # per kWh, all in
CONF_FIXED_LOW_PRICE = "fixed_low_price"  # optional: the low (night/weekend) rate
CONF_LOW_FROM = "low_from"
CONF_LOW_TO = "low_to"
CONF_LOW_WEEKEND = "low_weekend"
CONF_FIXED_EXPORT_PRICE = "fixed_export_price"  # optional: empty = net metering (export worth the import price)

# comfort and control (options)
CONF_DAY_FROM = "day_from"
CONF_DAY_TO = "day_to"
CONF_COMFORT = "comfort"
CONF_WEEKLY_COMFORT = "weekly_comfort"
CONF_DAY_MIN = "day_min"
CONF_NIGHT_MIN = "night_min"
CONF_STORE_MAX = "store_max"
CONF_SP_MIN = "lowest_setpoint"        # Roost never sets the thermostat lower (also what stays if HA is down)
CONF_MAX_ABOVE = "max_above_room"
CONF_MIN_INTERVAL = "min_interval"
CONF_PAUSE_HOURS = "pause_hours"
CONF_NOTIFY = "notify_target"           # optional: where Roost sends a notification (off when empty)
CONF_WEEKLY = "weekly_report"           # a summary every Monday morning (needs CONF_NOTIFY)
AWAY_MIN = 16.0                         # the default minimum while away
CONF_BASELINE_NIGHT = "baseline_night"  # 0 = no night setback in the comparison
CONF_GRID_PREFERENCE = "grid_preference"

# how Roost steers (options): a room setpoint on a thermostat, or a flow temperature through an OpenTherm master
# (opentherm.py). The master's entities are chosen, so any master that keeps the same agreement works.
CONF_CONTROL = "control"                # thermostat | opentherm
CONF_OT_FLOW = "ot_flow_setpoint"       # number: flow asked (°C), 0 = no heat demand; written at least every 5 min
CONF_OT_STATE = "ot_control_state"      # sensor: who steers the master now
CONF_OT_MODE = "ot_control_mode"        # select: Home Assistant (Roost steers) or the master's own heating curve
CONF_OT_MAX = "ot_max_flow_sensor"      # optional sensor: the highest flow the heat pump accepts (OpenTherm ID 49)
CONF_OT_COMM = "ot_communication_error"  # optional binary_sensor: the heat pump does not answer the master
CONF_OT_STATE_OK = "ot_state_ok"        # the state value that means "steered by Home Assistant"
CONF_OT_MODE_HA = "ot_mode_ha"          # the select option for Roost steering
CONF_OT_MODE_CURVE = "ot_mode_curve"    # the select option for the master's own heating curve
START_GRACE_S = 300                     # after a start: no "no price" for this long while the price sensor comes back
CONF_OT_Q_MIN = "ot_q_min"              # lowest steady heat output of the heat pump (kW)
CONF_OT_MIN_FLOW = "ot_min_flow"
CONF_OT_MIN_FLOW_NUM = "ot_min_flow_number"  # optional number on the box: its lowest flow (it owns the limits when it has them)
CONF_OT_MAX_FLOW_NUM = "ot_max_flow_number"  # optional number on the box: its highest flow
CONF_OT_MAX_FLOW = "ot_max_flow"
CONF_OT_START_KWH = "ot_start_kwh"      # electricity a start costs extra (kWh)
CONF_OT_MIN_RUN = "ot_min_run_time"     # optional number on the master: its minimum run time (min)
CONF_OT_MIN_OFF = "ot_min_off_time"     # optional number on the master: its minimum off time (min)
CONF_OT_FOLLOW = "ot_follow_curve"      # optional switch on the master: its fallback curve follows Roost's advice
CONF_OT_FLOW_TEMP = "ot_flow_temperature"  # optional sensor: the flow the master reads now (OpenTherm ID 25)
CONF_OT_CH_ACTIVE = "ot_heating_active"    # optional binary_sensor: the unit heats the house now (ID 0, CH)
CONF_OT_DHW_ACTIVE = "ot_hot_water_active"  # optional binary_sensor: the unit makes hot water now (ID 0, DHW)
CONF_OT_MAX_STARTS = "ot_max_starts"    # at most this many starts in 24 hours (0: no limit)
CONF_OT_QUIET = "ot_quiet"              # quiet hours on: not above CONF_OT_QUIET_MAX kW from .. to
CONF_OT_QUIET_FROM = "ot_quiet_from"
CONF_OT_QUIET_TO = "ot_quiet_to"
CONF_OT_QUIET_MAX = "ot_quiet_max"
CONTROLS = ["thermostat", "opentherm"]
OT_ENTITY_SUFFIX = {CONF_OT_FLOW: ("number", "_flow_setpoint"), CONF_OT_STATE: ("sensor", "_control_state"),
                    CONF_OT_MODE: ("select", "_control_mode"), CONF_OT_MAX: ("sensor", "_max_flow_limit_heat_pump"),
                    CONF_OT_COMM: ("binary_sensor", "_communication_error"), CONF_OT_MIN_RUN: ("number", "_min_run_time"),
                    CONF_OT_MIN_OFF: ("number", "_min_off_time"), CONF_OT_FOLLOW: ("switch", "_follow_roost_curve"),
                    CONF_OT_FLOW_TEMP: ("sensor", "_flow_temperature"), CONF_OT_CH_ACTIVE: ("binary_sensor", "_heating_active"),
                    CONF_OT_DHW_ACTIVE: ("binary_sensor", "_hot_water_active"), CONF_OT_MIN_FLOW_NUM: ("number", "_min_flow"),
                    CONF_OT_MAX_FLOW_NUM: ("number", "_max_flow")}

DEFAULTS = {
    CONF_WEEKLY_COMFORT: False,
    CONF_DAY_FROM: 7, CONF_DAY_TO: 22, CONF_COMFORT: 20.5, CONF_DAY_MIN: 20.0, CONF_NIGHT_MIN: 19.0, CONF_STORE_MAX: 22.5, CONF_SP_MIN: 19.0,
    CONF_MAX_ABOVE: 1.0, CONF_MIN_INTERVAL: 60, CONF_PAUSE_HOURS: 2, CONF_BASELINE_NIGHT: 0, CONF_GRID_PREFERENCE: 0.0,
    CONF_GRID_SIGN: "import_positive", CONF_WEATHER_SOURCE: "open_meteo", CONF_SOLAR_FROM_SOC: 50, CONF_IMPORT_ON_SETUP: True,
    CONF_PRICE_MODE: "sensor", CONF_IMPORT_MULT: 1.21, CONF_IMPORT_ADD: 0.0, CONF_EXPORT_FORMULA: False,
    CONF_EXPORT_MULT: 1.0, CONF_EXPORT_ADD: 0.0, CONF_USE_BAG: False, CONF_EMITTER: "floor", CONF_LOW_FROM: 23, CONF_LOW_TO: 7, CONF_LOW_WEEKEND: True,
    CONF_CONTROL: "thermostat", CONF_OT_STATE_OK: "home_assistant", CONF_OT_MODE_HA: "Home Assistant", CONF_OT_MODE_CURVE: "Heating curve",
    CONF_OT_Q_MIN: 2.8, CONF_OT_MIN_FLOW: 20.0, CONF_OT_MAX_FLOW: 40.0, CONF_OT_START_KWH: 0.2,
    CONF_OT_MAX_STARTS: 6, CONF_OT_QUIET: False, CONF_OT_QUIET_FROM: 22, CONF_OT_QUIET_TO: 7, CONF_OT_QUIET_MAX: 2.8,
}
PRICE_MODES = ["sensor", "epex", "fixed"]
EMITTER_KINDS = ["floor", "radiators", "lt_radiators", "fan_coils"]
MODES = ["off", "shadow", "active"]
GRID_SIGNS = ["import_positive", "export_positive"]
WEATHER_SOURCES = ["open_meteo", "entity"]

# Weheat integration entities by translation_key (the Weheat integration's own names)
WEHEAT = {
    "state": "heat_pump_state",
    "heat": "energy_output_heating",
    "heat_defrost": "energy_output_defrost",
    "elec": "electricity_used_heating",
    "elec_defrost": "electricity_used_defrost",
    "elec_dhw": "electricity_used_dhw",
    # the indoor unit (pumps, control, modem): a meter of its own, outside the unit's total and its COP. Measured
    # 22/23-11-2026 on a P80: the unit meters its own input (indoorUnitInputCurrent), nothing else on the group. ~55 W
    # idle above ~6 °C outside, ~108 W idle below ~4 °C (its circulation pump runs on against frost, ~53 W), ~110-140 W
    # while heating
    "elec_indoor": "electricity_used_indoor_unit",
    # for the card's Energy tab only: the hot water's heat and the unit's own total (standby and cooling as well)
    "heat_dhw": "energy_output_dhw",
    "elec_total": "electricity_used",
    "dhw_top": "dhw_top_temperature",              # the top of the hot-water tank: empty below response.TOP_EMPTY
    "outdoor": "outside_temperature",
    "cop": "cop",
    "power_in": "power_input",
    "power_out": "power_output",
    "thermostat_room": "thermostat_room_temperature",
    "thermostat_setpoint": "thermostat_room_temperature_setpoint",
    "water_setpoint": "thermostat_water_setpoint",
    "water_out": "water_outlet_temperature",
    # for the card's pump detail only (state, request, supply, return, power): none of these steers Roost
    "water_in": "water_inlet_temperature",
    "compressor": "compressor_rpm",
}
# the roles a user may point to another entity (the card's settings; other brands, other names): {role: entity_id}
PUMP_ROLES = ("state", "water_setpoint", "water_out", "water_in", "power_in", "power_out")

TICK_SECONDS = 120
PLAN_MINUTES = 15
WEATHER_MINUTES = 30
LEARN_HOUR, LEARN_MINUTE = 3, 30
HISTORY_DAYS = 365            # never more than a year: a house changes (insulation), recent heating counts most
WEHEAT_IMPORT_DAYS = 365
