# Roost — design (draft 0.2, 14-10-2026)

**Roost: smart heating planner for Weheat heat pumps.**

> A HACS integration for **Weheat heat pumps** (Blackbird P60/P80, Sparrow, …) that are controlled by a room thermostat
> (OpenTherm or on/off). Roost plans the thermostat's setpoint 24 hours ahead on price, weather, the heat stored in
> the house and — when present — own solar and a home battery. It learns the house and the heat pump from Home
> Assistant's own history, using the official **Weheat** integration's sensors. Not affiliated with Weheat.
> First user: the author's house (Blackbird P80, floor heating, Lyric T6 over OpenTherm, AlphaESS battery, solar).
> Successor of the author's Node-RED "Warmte-regelaar" (v1.6, active) and "Warmte-planner" (v2.8, shadow).

## 1. Goals and non-goals

**Goals**
1. **Made for Weheat, simple to set up**: pick the Weheat heat pump and the thermostat; everything else from the Weheat
   integration is found automatically. Required besides that: a price. Solar and a home battery are optional (with or
   without either works), and each makes it better.
2. **Plan, don't threshold**: a 24-hour plan per hour (room temperature × heat stored in the floor/building), so
   pre-heating in cheap or solar hours and coasting through expensive peaks follow from cost, not from rules.
3. **Low water temperature by design**: never ask much more than the room temperature (OpenTherm thermostats request
   hotter water for a bigger gap, which costs COP). A configurable "max setpoint above room".
4. **Learns the house** every night: heat loss (W/K), heat storage (kWh/K), floor lag, solar gain, wind effect,
   internal gains — checked against the last days before it is used. **Learns the heat pump**: COP against outdoor
   temperature and power, and the bias of its outdoor sensor.
5. **Own decisions**: its own value of energy per hour (grid / solar surplus / battery), no Predbat needed.
6. **Respect the user and the heat pump**: manual changes win (pause), at most one setpoint change per hour (configurable),
   minimum run time for the compressor, never below a safe minimum, shadow mode first.

**Non-goals (basic edition)**
- No direct heat-pump control (water temperature, modes): only the thermostat setpoint, like a person would.
- No hot water (DHW) planning — many heat pumps (e.g. Weheat Intelligence) do that themselves.
- No multi-zone in 0.1 (one thermostat, one room sensor; more zones later).
- No cloud. Open-Meteo is the only internet source and is optional.

Related work: OptiSpark (cloud optimisation of heat pumps), RoomMind (self-learning room control). Roost is local,
Weheat-specific (it knows the unit's states and meters) and drives the thermostat a person would use.

## 2. Lessons taken from Hot Water Shower Time (shower_time)

| Lesson | What Roost does |
|---|---|
| Pure logic in modules without HA imports → fast plain pytest | `model.py`, `cop.py`, `value.py`, `planner.py`, `control.py`, `series.py` pure; HA layer thin |
| Real HA tests in CI (pytest-homeassistant-custom-component, recorder before hass) | `tests/ha/` from the start: setup, config flow, a planning run, a manual change, restart |
| Diagnostics from day one (issue form asks for it) | `diagnostics.py`: settings, learned model, plan, sources, last decisions |
| First learning run uses all history; leave out days with HA off or sensors silent | same; also leave out hours with faulty readings (Weheat reports −1 °C on errors) |
| Learn only from clean events | house model only from hours without hot-water runs; COP only from heating hours with enough power |
| Big/fast-changing attributes out of the database; statistics only where they mean something | plan and diagnostics attributes in `_unrecorded_attributes`; state_class only on cost/energy totals |
| Fewer default entities | niche sensors start disabled |
| Card: since HA 2026.9 load only as a Lovelace resource in UI mode, ES2017, ASCII, keep `ha-card`, follow locale | same pattern for the 24-hour plan card (later than 0.1 if needed) |
| Logo in `custom_components/<domain>/brand/` | same |
| Release from CHANGELOG on tag push; Dependabot; git author = GitHub noreply | same workflow files |
| Config-entry reload does not load new Python code | deploy = copy + restart (with the author's OK) |
| Repairs for health checks | thermostat not following (heat pump on its own curve), room sensor silent, learning failing |

## 3. Architecture

```
            ┌──────────────────────── HA (custom_components/roost) ────────────────────────┐
 sensors → │ Sources → Energy value (per hour) → Planner (DP room × storage, 24 h) → Control → climate.set_temperature
 weather → │ Learning (nightly): house model, COP model, outdoor-sensor bias; preference (optional)               │
 history → │ Health checks → Repairs                                                                              │
            └──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 4. Inputs

**From the official Weheat integration** (found automatically on the heat pump's device, by their fixed `translation_key`,
so renamed entities still work):

| translation_key | Used for |
|---|---|
| `heat_pump_state` (enum: standby, heating, dhw, defrosting, legionella_prevention, manual_control, …) | which hours are space heating; leave hot water, legionella, defrost and manual control out of the learning |
| `energy_output_heating`, `electricity_used_heating` (kWh, total_increasing) | heat and electricity per hour → house model and COP model |
| `energy_output_defrost`, `electricity_used_defrost` | defrost losses counted with heating (the net heat that reached the house) |
| `electricity_used_dhw` / `energy_output_dhw` | hot-water hours recognised and left out |
| `outside_temperature` | outdoor reading of the unit (bias against Open-Meteo learned: reads high in the sun) |
| `cop` | live COP (diagnostic, not needed for learning) |
| `power_input`, `power_output` | live: is it heating now, how hard |
| `thermostat_room_temperature`, `thermostat_room_temperature_setpoint` | what the thermostat reports over OpenTherm (fallback room sensor; check that our setpoint arrived) |
| `thermostat_water_setpoint`, `water_outlet_temperature` | water temperature asked/made → check the "lukewarm water" rule works; "following" health check |

**Chosen by the user**

| What | Required | Notes |
|---|---|---|
| Weheat heat pump | yes | the device; entities above are taken from it |
| Thermostat | yes | `climate` entity that drives the Weheat (OpenTherm thermostat or the Weheat's own); Roost only sets its target |
| Room temperature | no | a better room sensor than the thermostat's (default: the thermostat's) |
| Price (import), with forecast | yes | Nord Pool, ENTSO-e, Frank, evcc, … read from attributes (as in Climate Pilot) |
| Price (export) | no | default: same as import (net metering) |
| Solar | no | grid power + PV power (+ solar forecast) |
| Home battery | no | state of charge, power (+ = discharge), capacity, max power |
| Weather | no | Open-Meteo by default (temperature, radiation, wind), or a weather entity |

The Weheat must be set to follow the thermostat (not to its own heating curve); Roost checks this and raises a
repair if the heat pump heats without the thermostat asking.

## 5. Models (pure Python)

**House (two states, per quarter of an hour)** — as validated in the author's house on last winter (4,674 h, 4-fold
cross-validation by week) and on HA's own data since August:
- floor/storage `E`: gains the heat-pump heat `Q`; releases `E / (1 + lag)` per hour into the room;
- room `T`: `T += (release + g·solar + internal − (H + Hw·(wind − 3.5))·(T − T_out)) / C`.
- Fit = open-loop error per day (24 h replay from the measured start) **plus the daily energy balance** (without that,
  C came out twice too big and the energy use wrong: lesson from 12-10), with a prior and a pull towards it.
  Adopt only when it predicts the last days better.
- Prior for a new install: generic values for a well-insulated house with floor heating; learning takes over within
  days. Optional later: import last winter from the Weheat portal export (the author trained on it, 4,674 hours).

**Heat pump**: `COP = α + β·(T_out_sensor) + γ·max(0, Q − q_ref)`, fitted on heating hours (≥ 0.3 kWh electricity, no
hot water). Starting values per model from the author's Blackbird P80 (2,313 winter hours: α 3.04, β 0.19, γ −0.27),
like the *Weheat 200 L* profile in Hot Water Shower Time. Bias of the heat pump's outdoor sensor against Open-Meteo learned at night (median), because some units
read high in the sun.

**Thermostat behaviour** (the important part for OpenTherm): it heats on the room error only and does not know the
floor; heat goes into the floor first. Learned in v0.2 (response.py) from the Weheat logs, which carry the setpoint and
the thermostat's own reading per hour: demand = a·loss + k·(setpoint + offset − thermostat reading), the output
following with a delay (author's Lyric T6 + P80: a 0.9, k 1 kW/°C, offset +0.3, 35 %/h; the thermostat reads 0.8 °C
below the room sensor). An on/off model (gap closed within the hour) overestimated the unit's response ~20-fold.
The search stays static (fast); for a slow unit its plan is polished with the real delay (planner.polish). The planner models that (it is what makes floor heating overshoot), and limits
`setpoint ≤ room + max_above_room` (default 1.0 °C) so the water stays lukewarm.

## 6. Energy value per hour

Reuse Climate Pilot's `value.py`, with the fixes learned on 14-10:
- **only real solar counts as own solar**: export minus battery discharge, never more than PV power now; planned
  export from a battery plan is not solar;
- a home battery that fills up today anyway → solar is valued at the export price;
- energy from the battery is valued at the price of refilling it;
- with net metering, export = import price, so solar is not free (it will be after net metering ends).
Predbat's marginal costs can be used optionally, but default off (they are wrong while Predbat is read-only and
something else drives the battery).

## 7. Planner

- Every 15 min, 24 h, setpoints in 0.5 °C steps between a minimum and a maximum; dynamic programming over
  (room temperature 0.1 °C × stored heat 1 kWh), bilinear interpolation, receding horizon (as the author's v2).
- Cost = electricity (heat ÷ COP) × energy value + comfort penalty (below the band in the day hours, heavier below a
  hard minimum) + a small cost per setpoint change − value of heat left at the end (asymmetric: a deficit counts fully,
  a surplus partly, because it leaks away).
- Solar surplus may raise the band top (load the floor on free solar, up to a maximum), configurable.
- Compares every plan with the user's schedule (a simple day/night setpoint) → "saving vs schedule" in euros.

## 8. Control

- Shadow / active per entry; in shadow nothing is written, the plan and "would set" are shown.
- At most one change per hour (configurable), only send when different, never below the hard minimum.
- Manual change on the thermostat (not by us) → pause N hours (default 2), then return to the plan.
- Thermostat unavailable → do nothing; heat pump not following the thermostat → repair issue.

## 9. Entities

- `select.<name>_mode` (off / shadow / active)
- `sensor.<name>_setpoint` (planned now), attributes: reason, 24-h plan (setpoint, expected room temperature, kWh,
  price), comfort band — attributes not recorded
- `sensor.<name>_cost_24h`, `sensor.<name>_saving_24h` (vs schedule), `sensor.<name>_energy_value`
- `sensor.<name>_house_model` (prediction error °C; attributes H, C, g, lag, wind, internal, last learning),
  `sensor.<name>_cop_model` (diagnostic), `binary_sensor.<name>_manual`, `binary_sensor.<name>_following` (thermostat
  drives the heat pump)
- buttons: learn now; services: pause, resume, boost (temperature for N hours)
- later: a 24-hour plan card (like the author's dashboard card: setpoint, expected room, tariff strip, scrubbing)

## 10. Rollout at the author's house

1. Build + tests (pure and HA) green.
2. Install in shadow next to the Node-RED regelaar (v1.6 keeps control) and the Node-RED v2 shadow planner; compare
   plans and predicted vs measured room temperature for a few weeks of the heating season.
3. When it is at least as good: switch Roost to active, Node-RED regelaar to shadow (the author decides).
4. Then publish (one release, reviewed together).

## 11. Decisions (14-10-2026)

1. **Name**: Roost (domain `roost`), "smart heating planner for Weheat heat pumps".
2. **Card in 0.1: yes** — the 24-hour plan card (setpoint, expected room temperature, tariff strip, comfort band,
   scrubbing per hour), built the way the shower card taught (Lovelace resource in UI mode, ES2017, ASCII, keeps
   `ha-card`, follows locale and 24/12 h, visual editor).
3. **Baseline for "saving"**: a **steady thermostat** at the comfort temperature all day (the usual advice for heat
   pumps with floor heating, and what most Weheat owners run), with an optional night setback. No schedule to type in.
   Shown as *saving today / this month* in euros, computed with the same model and prices, so it is an honest
   like-for-like comparison. Later: also the measured cost against the model's prediction.
4. **Storing heat in the floor is decided by the planner, not by a toggle** (author, 14-10): when the energy value of an
   hour is low — solar that earns little when exported, or simply a cheap hour — and an expensive evening follows, the
   planner loads the floor so the evening needs no expensive power. It weighs the price difference against the heat
   that leaks away while stored and the better COP in the warm afternoon. With net metering this still happens when
   the midday tariff is clearly below the evening tariff; after net metering ends it happens on most sunny days. The
   only setting is **how warm the house may get while storing heat** (default 22.5 °C; equal to the comfort top = off).
5. **Bootstrap: both, each for what it is best at**:
   - **"Import history from Weheat"** (button + config option) is the cleanest source for the heat pump itself: the
     unit's own hourly logs and energy meters since installation, without gaps when Home Assistant was off — heat and
     electricity per hour, seconds per state (heating / hot water / defrost), the thermostat's room temperature and
     setpoint. Read-only, through the login of the user's own Weheat integration; Roost never refreshes or stores that
     token itself (it uses the current access token and retries later). The Weheat portal has no export button.
   - **Home Assistant's long-term statistics** add what Weheat does not know: a better room sensor than the thermostat,
     and measured solar power (solar gain through the windows). Where both exist for an hour, Roost uses Weheat's
     meters with HA's room temperature and solar.
   - **Weather for past hours** from the Open-Meteo archive (outdoor temperature, radiation, wind) when HA has none.

## 11b. Later (noted 14-10-2026)

- **Steer radiator valves of extra rooms** (step 2 of extra rooms): with smart valves in Home Assistant, open them in
  cheap or solar hours and set them back in expensive hours, on the same plan as the main thermostat, so the upstairs
  rooms become a buffer too instead of only a constraint. Start when step 1 (watch rooms, keep minimums; v0.4.0) has
  shown with real data how much those rooms store.

## 12. Build order

1. Pure core, ported from what runs today: `series.py`/`value.py` (from Climate Pilot, with the 14-10 solar fix),
   `model.py` (house model + learning with energy balance and wind, from `warmte-model-leer.py`), `cop.py`,
   `planner.py` (DP from Warmte-planner v2.8), `control.py` (one change per hour, manual → pause, shadow).
2. HA layer: config flow (Weheat device → entities by translation_key; thermostat; price; optional solar/battery/weather),
   manager, learning from statistics, Weheat import, entities, services, repairs, diagnostics.
3. Card.
4. Tests: pure + `tests/ha` (pytest-homeassistant-custom-component), CI, release workflow.
5. Shadow at the author's house next to Node-RED; compare; then the author decides.
