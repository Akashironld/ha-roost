# Changelog

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
