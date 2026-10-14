# Changelog

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
