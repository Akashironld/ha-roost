<p align="center"><img src="assets/icon.png" width="128" alt="Roost logo"></p>
<h1 align="center">Roost</h1>

<p align="center"><b>Smart heating planner for Weheat heat pumps.</b><br>
Plans your thermostat 24 hours ahead on price, weather and the heat your house stores — and learns your house by itself.</p>

> Status: 0.1, early. Roost starts in **shadow mode**: it shows what it would do and why, without touching your
> thermostat, until you switch it to active. Not affiliated with Weheat.

## What it does

- **Plans, instead of reacting.** Every quarter of an hour Roost makes a 24-hour plan of thermostat setpoints. When an
  hour is cheap (or your solar earns little) and an expensive evening follows, it stores heat in the floor; in the
  expensive hours it lets the house run on that stored heat. It weighs the price difference against the heat that
  leaks away and against the better COP in the warm afternoon.
- **Keeps the water lukewarm.** It never asks for much more than the room temperature (at most 1 °C above it by
  default), so an OpenTherm thermostat keeps asking for low water temperatures and the heat pump keeps a high COP.
- **Learns your house** every night from Home Assistant's history: heat loss, how much heat the house stores, how long
  the floor holds it, solar gain through the windows, the effect of wind. A new model is only used when it predicts the
  last days better than the old one, and it must get both the temperatures and the energy use right.
- **Learns your heat pump**: its COP against the outdoor temperature and the output, and how far its outdoor sensor
  reads off (they read high in the sun).
- **Starts from last winter.** One button imports the heat pump's hourly history (up to 13 months) from Weheat through
  your Weheat integration's login — read-only — so Roost knows your house from day one instead of after a winter.
- **Works out the value of energy itself.** Only real solar counts as own solar (export minus battery discharge, never
  more than the solar power), a home battery that fills up anyway makes solar free, and the rest costs the price of
  that hour. With net metering export is worth the import price, so solar is not free yet; after net metering it is.
- **Respects you and the heat pump.** At most one setpoint change per hour; a change by hand pauses Roost for two
  hours; it never goes below your minimum; shadow mode first.
- **Shows what it saves**, against a steady thermostat at your comfort temperature (the usual advice for heat pumps):
  expected saving over the next 24 hours, yesterday and this month.
- **Its own dashboard card** with the 24-hour plan (setpoint, expected room temperature, price per hour, comfort hours;
  slide over it to read each hour).

## Requirements

- Home Assistant 2025.1 or newer, with the recorder.
- A **Weheat heat pump** with the official **Weheat** integration.
- The **thermostat** that drives the heat pump (OpenTherm or on/off), as a `climate` entity. The heat pump must follow
  the thermostat, not its own heating curve — Roost checks this and raises a repair notice if it does not.
- An **electricity price** sensor, best with a forecast in its attributes (Nord Pool, ENTSO-e, Frank Energie, evcc and
  other sensors with a list of `{start, end, value}` are read automatically).
- Optional: a better room sensor, export price, grid power, solar power and forecast, home battery, house power, a
  weather entity (Open-Meteo is used by default: free, no account).

## Installation

1. HACS → three dots → *Custom repositories* → add this repository as an *Integration*.
2. Install **Roost** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Roost*: pick the Weheat heat pump, the thermostat and the price
   (a dynamic price sensor, or your fixed contract's rate with an optional low rate),
   then (optionally) solar, battery and weather, and your comfort temperatures.
4. Add the card: *Edit dashboard → Add card → Roost*.

## Thermostats

Roost steers by changing the room setpoint of the thermostat in Home Assistant, like you would. The heat pump must
follow the thermostat, not only its own heating curve.

| Setup | How well |
|---|---|
| OpenTherm thermostat (Lyric T6, Nest, Tado, …) | Best. How the heat pump responds to the setpoint is learned from the Weheat history (also last winter) |
| On/off thermostat, heat pump on its heating curve when asked | Works. Roost records the setpoint itself, so the response is learned after a few weeks |
| Heat pump only on its heating curve (ignores the thermostat) | Roost cannot steer; a repair says so |

A thermostat with its own schedule or learning (Nest, Tado) works against Roost: turn that schedule off. Roost notices
changes that come back at the same time every day and says so in Repairs.

## Card options

All options are also in the visual editor.

| Option | What | Default |
|---|---|---|
| `entity` | the *Planned setpoint* sensor of Roost | required |
| `title` | own title | `Roost` |
| `compact` | only the header and the tiles (room, thermostat, planned) — handy on a wall tablet | `false` |
| `show_tiles` | room, thermostat and planned setpoint | `true` |
| `show_chart` | the 24-hour plan | `true` (`false` in compact) |
| `show_footer` | the saving | `true` (`false` in compact) |
| `language` | `en` or `nl`; by default the language of your Home Assistant profile | |
| `time_format` | `24` or `12`; by default your profile | |

A `show_…` option you set yourself always wins, so you can start from `compact` and add a part back:

```yaml
type: custom:roost-card
entity: sensor.roost_planned_setpoint
compact: true
show_chart: true
```

## Entities

| Entity | What |
|---|---|
| `select.roost_mode` | off / shadow / active |
| `sensor.roost_planned_setpoint` | the setpoint Roost wants now; reason, decision and the 24-hour plan in the attributes (`reason`/`decision` in English, `reason_code`/`decision_code` with their `_args` for your own translations) |
| `sensor.roost_expected_saving_next_24_h` | against a steady thermostat at your comfort temperature |
| `sensor.roost_saving_yesterday`, `sensor.roost_saving_this_month` | the day replayed with the same model, weather and prices |
| `sensor.roost_heating_cost_today` | heat pump electricity for space heating × the price of each hour |
| `sensor.roost_house_model_error` | how well the learned house model predicts a day (°C); the house's numbers in the attributes |
| `sensor.roost_weheat_import` | status of the Weheat history import |
| `sensor.roost_plan_accuracy` | nightly self-check: how close the plan comes to the room 6 hours ahead (°C); the horizons, heat and electricity against the meters, readiness to steer, the correction and the learned response in the attributes |
| `binary_sensor.roost_paused_changed_by_hand`, `binary_sensor.roost_heat_pump_follows_the_thermostat` | |
| `button.roost_learn_now`, `button.roost_import_history_from_weheat` | |

Switched off by default: heating electricity today, energy value now, heat pump model.
Services: `roost.pause`, `roost.resume`, `roost.import_history`.

## How it decides

Per quarter of an hour the planner simulates the thermostat (it heats on the room error only and does not know the
floor), the heat going into the floor first and reaching the room with the learned lag, losses to outside with wind,
and solar gain. The cost of an hour is the electricity (heat ÷ COP) times the energy value of that hour, plus comfort
penalties (heavy below your minimum, light below your comfort temperature in the day) and a small cost per change. The
cheapest plan over 36 hours wins; the first hour is carried out and the plan is made again every 15 minutes.

## Limits (0.1)

- One thermostat, one room. Hot water is left to the heat pump (Weheat Intelligence plans it itself).
- Without imported history or a winter in Home Assistant, the first weeks use a generic model for a well-insulated
  house with floor heating; it adapts as heating days come in.
- With a weather entity instead of Open-Meteo, solar radiation is estimated from the sun's height and cloud cover.

## Support

Issues and ideas: [GitHub issues](https://github.com/Akashironld/ha-roost/issues). Like it?
[A coffee on Ko-fi](https://ko-fi.com/akashironl) keeps the next feature coming.
