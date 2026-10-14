# Changelog

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
