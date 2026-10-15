# Changelog

## v0.5.0 — beta (unreleased)

- Weheat history within Weheat's limits for developers (logs at most every 2 minutes, energy logs at most every half
  hour): a month per call (longer is refused), newest month first, Roost learns after the first month and the rest
  comes in the background (a year takes some hours); a restart carries on where it was; from the commissioning date
  at most a year back. Every call is in the event log
- Learning: never more than a year; recent heating counts most — counted in heating days, so a summer without heating
  does not age last winter; days without heating count a quarter; a model of only the newest heating days takes over
  when it clearly predicts better (a house that was insulated)
- Mode in Roost itself: *Configure → Mode* shows what the self-check says (plan error, heating hours, heat, follows,
  lever) and switches off / shadow / active; a *Ready to steer* binary sensor; the card shows a *Let Roost steer*
  button when it is ready (click twice)
- Calmer: a thermostat change has to be worth more (about 1–2 a day instead of ~5), and the comfort temperature weighs
  more, so fewer changes do not cost comfort — chosen with closed-loop simulations of eight kinds of houses
  ([docs/SIMULATIONS.md](docs/SIMULATIONS.md), `tools/sim/sim.py`)
- The saving shown is against a steady thermostat that is as comfortable as Roost's plan (it could be colder before,
  which made a comfortable plan look expensive)
- A setup and user guide ([docs/GUIDE.md](docs/GUIDE.md)); the README is now a front page with a quick start
- When it expects to be ready to steer: after the import, at the next self-check, after more heating, in the heating
  season — or which setting blocks it. In *Configure → Mode*, the card and the *Ready to steer* sensor
- How far the Weheat import is: sensor *Weheat import progress* (%), and "3 of 12 months, done around 13:40" in
  *Configure → Mode* and on the card. The time of the last Weheat call is kept, so a restart during the import still
  keeps Weheat's limits
- The self-check uses the newest week with enough heating when the last week had too little (mild weather, right
  after the import), so Roost can say right away whether it is ready
- Optional: Roost's own Weheat login (*Reconfigure → Weheat login*), with the same Client ID and Secret as the Weheat
  integration; Roost keeps and refreshes it itself, so the import never waits for the Weheat integration's login.
  Default stays the Weheat integration's login
- Hours the heat pump heated without the thermostat asking (the room well above its setpoint, beyond what the learned
  response explains — e.g. its own heating curve in spring and autumn) are left out of learning the response and of
  the self-check, and counted (*unfollowed_hours*)
- A house that changed (insulated): the heat pump's response is learned from the new house's days only, like the
  house model (in the simulation it was too cold before: 15–20 °C·h a week below comfort, now ~1)

## v0.4.1 — setup by subject (unreleased)

- Setup and options by subject: the heat pump and thermostat, the house, the electricity price, solar and home
  battery (two ticks first: only the fields for what the house has), comfort with the regulation and the weather
  folded away under *Advanced*. The options menu shows what is set now; each part saves when submitted
- Likely entities are filled in: the thermostat (a climate entity that heats and does not cool), the room sensor (in
  the thermostat's area, else the living room), price sensors with a forecast, solar/grid/battery/house power of one
  inverter, solar forecasts
- Bug reports: Roost keeps an event log (every thermostat change and why, changes by hand, mode, learning, import,
  repairs, plans it could not make, errors; the last 300, kept over restarts) and its last warnings and errors; the
  diagnostics download now holds those, the versions, the state of every entity Roost reads and the inputs of the
  current plan (to replay it), without the home location. The bug report form explains how to get it
- Comfort settings filled in from the thermostat's last days: the comfort hours, the comfort temperature, the night
  minimum (at most 1.5 °C below comfort: a heat pump does badly with a deep setback)

## v0.4.0 — extra rooms (unreleased)

- Extra rooms the heat pump also heats (radiators upstairs, a bedroom): *Add room* on the integration page, with a
  sensor and a kind (bedroom, kids' room, study, bathroom, other) that sets a minimum and its hours; outside them the
  room may be cool. Roost learns per room how it cools and warms, keeps the minimums in the plan, shows the rooms on the
  card and raises a repair when a room keeps staying too cold
- Needs Home Assistant 2025.3 or newer (rooms are config subentries)

## v0.3.6 — fixed price contracts, comfort suggestions, sun on the facades, internal gains per hour, building register (unreleased)

- Price: dynamic (a price sensor, as before) or a fixed contract: one rate, optionally a low rate with its hours and
  the weekend, optionally a fixed export price (empty = net metering)
- Comfort suggestions: changes made by hand while Roost steers are remembered; when the same kind of change comes back
  on three different days within two weeks, a repair suggests a setting (warmer or cooler in the day, comfort hours
  earlier or later). One click to accept, or ignore it — never changed by itself
- Sun on the facades: the weather now includes direct and diffuse radiation; the house model tries every facade
  direction (east to west, half and fully vertical) next to global radiation and keeps the one that predicts alternate
  weeks best (the author's house: south-east, about 5 % better)
- Internal gains per hour of the day (cooking, people, a thermostat in the sun), at half strength and at most 1 kW,
  kept only when it predicts better
- The weather archive is read again once, for the direct and diffuse radiation
- Optional (off by default, the Netherlands only): building data from the BAG through PDOK, looked up once at the
  home location — construction year and floor area give starting values for the house model, the outside walls
  (walls shared with neighbours left out) limit the facade directions tried. No address is kept; off removes it.
  Not used when the home location is not in or within 25 m of the dwelling; for flats only year and area
- Options: each part saves when it is submitted (the separate *Save* step was easy to miss)
- Weheat import: a status with translated states (done, importing, waiting for the Weheat login, failed)
- Comfort option *Lowest thermostat setting* (default 19 °C): Roost never sets the thermostat lower — also what
  stays on it if Home Assistant is down (it was the night minimum − 1, at most 18)
- Own record of the thermostat's setpoint and reading per hour (120 days), for hours the Weheat logs do not have it
  (an on/off thermostat): the response and the self-check then learn as well
- Repair when changes Roost did not make come back at the same time every day (a schedule in the thermostat, or
  another automation); those changes do not count for comfort suggestions
- Repair when the learned response shows the setpoint hardly moves the heat pump (its own heating curve); not ready
  to steer then
- Setting *Heat emitters* (floor heating, radiators, both): starting values for the house (buffer, delay) and the
  COP, and the wording (the floor, or the house, as the buffer)
- Card: under *Planned* the room temperature expected with it (the planned setpoint is a thermostat setting and
  may be well below the room for a slow unit); clearer reasons: charging the floor, living off the heat in the floor

## v0.2.0 — self-learning: self-check, correction, response to the thermostat, hot water (unreleased)

- Self-check every night: the last 7 days replayed with the setpoints that were really on the thermostat (so it also
  works in shadow mode); the room 1, 6 and 24 hours ahead and the heat and electricity against the meters. New sensor
  *Plan accuracy*; when Roost predicts well enough over enough heating hours and the heat pump follows the thermostat,
  a repair *ready to steer* offers to switch to active (your decision; never automatic)
- Correction from the last hours: when the room got warmer or colder than predicted (sun, visitors, an open window),
  the plan takes that as extra heat, fading out over the coming hours
- The heat pump's response to the thermostat is learned from the Weheat logs (which now include the setpoint and the
  thermostat's own reading per hour). An OpenTherm thermostat modulates: the unit asks for about the house's loss plus
  a gain per degree below the setpoint and follows with a delay (the author's unit: 0.9 × loss + 1 kW per °C, 35 % of
  a change per hour; it kept heating with the room a degree above the setpoint). Also learned: how the thermostat reads
  against the room sensor, the lowest steady output and the COP while cycling below it
- Planner: for a unit that follows slowly, the plan from the search is improved with the real delay (blocks of 1–4
  hours), starting also from a steady thermostat, so it never plans worse than that; the shown plan follows the delay
  from the unit's measured output; "setpoint at most 1 °C above the room" and the steady thermostat to compare with now
  count from what the thermostat reads (the setpoints shown are thermostat settings)
- Hot water: the share of each hour of the week the unit spends on hot water (schedule, legionella) is learned; the
  planner knows no space heating happens then and heats before or after
- Every night the hours since the last Weheat import are read (read-only) before learning; an install imported by an
  older version reads its history again once, for the setpoints
- Card: plan error 6 h and *ready to steer* in the footer

## v0.1.2 — compact card, reasons in your language, prices beyond the forecast (unreleased)

- Card: `compact` option (header and tiles only, for a wall tablet); a `show_…` option set yourself still wins
- Card: the reason and the decision now follow your language (English, Dutch); the planned-setpoint sensor gets
  `reason_code`/`reason_args` and `decision_code`/`decision_args` next to the English text
- Prices: hours the price forecast does not reach yet (tomorrow's day-ahead prices arrive in the afternoon) get the
  price of the same hour a day earlier (remembered, and read from the recorder at start-up) instead of the last known
  price for the whole night
- Card: the bars show the import tariff; hours with a guessed price are faded; sliding over the graph also shows the
  price the planner counts when that differs (the home battery's refill cost, or own solar)
- Weheat lookup uses `DeviceEntry.config_entry_id` where Home Assistant has it (`config_entries` is deprecated)

## v0.1.0 — first version (unreleased)

Roost: smart heating planner for Weheat heat pumps.

- 24-hour plan of thermostat setpoints (dynamic programming over room temperature and the heat stored in the floor),
  planned over 36 hours, renewed every 15 minutes; never more than 1 °C above the room (lukewarm water, high COP)
- Stores heat when an hour is cheap or solar earns little and an expensive one follows; the only setting is how warm
  the house may get while storing
- House model learned every night (heat loss, storage, floor lag, solar gain, wind, internal gains), checked on the
  temperatures and the daily energy balance; adopted only when it predicts better
- Heat pump model: COP against outdoor temperature and output, outdoor-sensor bias, maximum output (Blackbird P80/P60 profiles)
- Import of the heat pump's hourly history from Weheat through the Weheat integration's login (read-only)
- Own energy value per hour: real solar only (export minus battery discharge, at most the solar power), a battery that
  fills anyway, battery refill price, grid price
- Control: shadow / active, at most one change per hour, a change by hand pauses for two hours, never below the minimum
- Saving against a steady thermostat: next 24 hours, yesterday, this month
- Repairs: heat pump not following the thermostat, no room temperature, Weheat sensors missing, learning failed
- Dashboard card with the 24-hour plan, English and Dutch, light and dark theme, visual editor
- Diagnostics download
