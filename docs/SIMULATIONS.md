# Simulations

`tools/sim/sim.py` runs Roost in a closed loop against a "true" house that differs from what Roost knows, and compares
it with a steady thermostat. Run it before a release:

```bash
python3 tools/sim/sim.py               # all scenarios, 7 days, in parallel
SIM_SEED=2 python3 tools/sim/sim.py    # another week of weather, prices and noise
SIM_SETTINGS='{"switch_cost": 0.10}' python3 tools/sim/sim.py   # try planner settings
```

## How

1. **Learning.** 40 days of history from the true house under an ordinary schedule (day 20.5, night 19.5, now and then
   a change by hand). Roost learns its house model and the heat pump's response from it, as in Home Assistant. The
   learned model is never exactly the truth (e.g. offset 0.1 instead of 0.3, heat loss 0.135 instead of 0.15).
2. **Steering, 7 days.** Every hour Roost plans 36 hours ahead with a weather forecast whose error grows with the hours
   ahead, its control rules apply (at most one change an hour), the correction from the last hours is on. The true
   house then runs the hour with the real weather, random internal gains (cooking, people) and the true response.
3. **Steady thermostat.** One setting day and night (the usual advice for heat pumps): the lowest that is at least as
   comfortable as Roost was (°C·hours below the comfort temperature in the comfort hours, hours below the minimums).
   Roost's cost is levelled for the heat left in the house at the end.

## Scenarios

| Scenario | House and heat pump |
|---|---|
| home | Floor heating, a slow modulating OpenTherm unit (35 % of a change per hour), dynamic price, January |
| radiators | Radiators: a fast unit, a small buffer |
| fixed | Fixed price, one rate |
| double | Fixed price with a night/weekend rate |
| mismatch | The house loses 30 % more than Roost learned, a 2.5 °C forecast error after 24 h |
| spring | Mild and sunny |
| onoff | On/off thermostat, heating curve when asked |
| bedroom | An extra bedroom upstairs (radiators) with a minimum of 17 °C from 19 to 23 h |
| insulated | Insulated since last winter: 90 days of the old house in the history (heat loss 0.22 kW/K), then 40 days of the new one (0.12) |
| old | A 1930s house: heat loss 0.28 kW/K, radiators, a fast unit |
| newbuild | A new build: heat loss 0.07 kW/K, a heavy floor (delay 2 h), much glass; the unit is oversized and cycles |
| apartment | Small, little storage, warm neighbours |
| cold | A cold snap: −4 °C on average, the unit near its maximum |
| volatile | Dynamic price with cheap windy nights (8–24 ct), cheap sunny noons (2–26 ct) and steep evenings (40–70 ct) |
| slowpump | The heat pump follows twice as slowly as Roost learned, with half the gain |
| autumn | Mild; in the history the unit also heats on its own curve now and then (heat the thermostat did not ask for) |

## Results (v0.5.2, three weeks of different weather and prices)

Saving against the equally comfortable steady thermostat, mean of three weeks (range):

| Scenario | Saving | Comfort | Thermostat changes |
|---|---|---|---|
| home | 1.6 % (0.8–2.9) | as steady | ~1 a day |
| radiators | 8.2 % (6.5–10.8) | as steady (lowest room 19.8–20.2 °C) | ~2 a day |
| fixed | 3.5 % (1.6–5.1) | as steady | ~2 a day |
| double | 3.2 % (2.8–3.9) | as steady | ~2 a day |
| mismatch | 2.8 % (1.5–4.1) | a little below comfort (≈ 1 °C·h a day) | ~2–3 a day |
| spring | 1.9 % (0.2–5.0) | as steady | ~1 a day |
| onoff | 6.9 % (5.9–8.1) | as steady | ~2 a day |
| bedroom | 1.5 % (0.2–2.6) | as steady; the bedroom never below its minimum (the steady thermostat: 0–4 h) | ~2 a day |
| insulated | 3.3 % (1.0–5.9) | as steady (≈ 0.1 °C·h a day below comfort) | ~3 a day |
| old | 5.8 % (4.6–7.7) | as steady (both ≈ 0.5 °C·h a day below: the unit is at its limit) | ~2 a day |
| newbuild | 7.3 % (5.1–10.7) | ≈ 0.2 °C·h a day below comfort | ~2 a day |
| apartment | 3.2 % (0.0–7.5) | as steady | < 1 a day |
| cold | 4.8 % (4.4–5.2) | ≈ 0.2 °C·h a day below comfort | ~3 a day |
| volatile | 10.2 % (9.5–10.7) | as steady | ~3 a day |
| slowpump | 1.5 % (1.1–2.3) | ≈ 0.3 °C·h a day below comfort | ~1–2 a day |
| autumn | 3.6 % (0.0–5.8) | ≈ 0.2 °C·h a day below comfort | ~1 a day |

What these say:

- **A slow modulating heat pump on a floor shifts little.** The heat pump already smooths its output, and it follows a
  new setpoint over hours; the saving is mostly the better COP of the warmer hours. Faster units (radiators, on/off)
  can be steered more and save more.
- **A fixed price still saves a few percent**: heating more in the warmer, more efficient hours.
- **A model that is off costs a little comfort, not money**: the correction from the last hours limits it.
- **The bigger the price swings, the more it saves**: ~10 % with steep evening peaks and cheap nights or noons.
- **Well insulated houses with a heavy floor and leaky old houses with radiators both save 5–7 %**: the first stores
  heat for long, the second follows a new setpoint fast.
- **A heat pump that responds differently than learned** (slower, less gain) still saves a little and costs a little
  comfort; the nightly learning then corrects the response.
- **Extra rooms cost a little saving** for keeping them warm enough — which a steady thermostat does not always do.
- These are simulations with a simple price shape (night ~22 ct, evening peak ~45 ct). Real houses, prices and
  heat pumps differ; beta testers' diagnostics will tell.

## What the simulations changed

| Found | Changed |
|---|---|
| ~5 thermostat changes a day for little gain | Cost per change 0.05 → 0.15 €: ~1–2 a day, about the same saving |
| With fewer changes, a bit more time below comfort | Comfort penalty 0.10 → 0.20 € per °C·hour |
| A deeper search (longer blocks, more starting plans) found cheaper plans on the model, not in the closed loop: it exploits model errors | Kept the simple search |
| After insulating, the house model learned the new house but the heat pump's response still came from the old one: 15–20 °C·h a week below comfort | The response is learned from the same newest heating days as the house model when the house changed: ~1 °C·h a week |
| A heat pump that also heats on its own curve (spring, autumn) taught the response wrong: hours with heat the thermostat did not ask for | Those hours are recognised (the room more above the setpoint than the learned response explains) and left out of the response and the self-check; the response fit also leaves out its worst 10 % of windows |
| Fitting the house with the noise level the data really has (instead of a typical one) found parameters closer to the truth (floor delay, storage) — but steered worse: −3 % in the old house, colder at home | Not used: the model that predicts the closed loop best is not the one with the truest parameters |
| A threshold for storing heat above comfort cost more than it saved (radiators, on/off) | Not used |
| The saving shown was against a steady thermostat that could be colder than Roost's plan, making a comfortable plan look expensive | The steady thermostat to compare with is now the lowest that is as comfortable as the plan (card, *expected saving*, *saving yesterday*) |
