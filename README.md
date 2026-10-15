<p align="center"><img src="assets/icon.png" width="128" alt="Roost logo"></p>
<h1 align="center">Roost</h1>

<p align="center"><b>Smart heating planner for Weheat heat pumps.</b><br>
Plans your thermostat 24 hours ahead on price, weather and the heat your house stores — and learns your house by itself.</p>

<p align="center">
<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=Akashironld&repository=ha-roost&category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open in HACS" height="36"></a>
<a href="https://ko-fi.com/akashironl/?hidefeed=true&widget=true&embed=true"><img src="https://storage.ko-fi.com/cdn/kofi2.png?v=3" alt="Buy me a coffee on Ko-fi" height="36"></a>
</p>

> **Status: beta.** Roost starts in **shadow mode**: it shows what it would do and why, without touching your
> thermostat, until you let it steer. Not affiliated with Weheat.
>
> 📖 **New here? Follow the [setup and user guide](docs/GUIDE.md)** — from installing to letting Roost steer, step by step.
> What to expect: [simulations](docs/SIMULATIONS.md).
>
> 🧪 **Testing the beta?** What to expect and what to report: [docs/TESTERS.md](docs/TESTERS.md).

## What it does

- **Plans instead of reacting.** Every 15 minutes a 24-hour plan of thermostat settings. When an hour is cheap (or your
  solar earns little) and an expensive evening follows, it charges the floor a little; in the expensive hours the house
  lives off that heat. It weighs the price difference against the heat that leaks away and the better COP in the warm
  afternoon.
- **Keeps the water lukewarm.** It never asks for much more than the room temperature, so an OpenTherm thermostat keeps
  asking for low water temperatures and the heat pump keeps a high COP.
- **Learns your house** every night: heat loss, the heat the house stores, how long the floor holds it, the facade the
  sun comes in through, wind, internal gains per hour of the day. A new model is only used when it predicts better.
- **Learns your heat pump**: its COP, how it responds to the thermostat (an OpenTherm thermostat modulates and the heat
  pump follows slowly — Roost plans with that delay), its lowest output, when it makes hot water.
- **Starts from last winter.** It imports the heat pump's hourly history (a year) from Weheat, read-only,
  with its own Weheat login (you log in with your Weheat account in the setup) — so it knows your house from day one.
- **Checks itself.** Every night it replays the last week with the setpoints that were really on the thermostat (in
  mild weather the last heating weeks instead); when it predicts well enough it offers to take over. Between nights it
  corrects from the last hours — what sunny hours miss as extra sun, so a sunny afternoon does not warm the night.
- **Dynamic or fixed price**, solar, home battery (energy from the battery is valued at what refilling it costs), net
  metering or not.
- **Extra rooms**: radiators upstairs or a bedroom get a minimum in their own hours, so Roost never lets the heat pump
  rest longer than they can take.
- **Respects you.** At most one change an hour, steps aside for two hours when you change the thermostat, never below
  your minimums or its lowest setting, comfort suggestions instead of changing your settings by itself.
- **Its own dashboard card** with the plan, the expected room temperature, the tariff per hour and what it saves.

## Quick start

1. **HACS**: click the button below (or HACS → ⋮ → *Custom repositories* → add this repository as an
   *Integration*) → download **Roost** → restart Home Assistant.

   [![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Akashironld&repository=ha-roost&category=integration)
2. **Settings → Devices & services → Add integration → Roost**
   ([![Add the integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=roost)). Pick your Weheat heat pump and thermostat; Roost fills in
   what it finds (room sensor, price sensor, solar and battery, your comfort temperatures) — check it and submit.
3. **Add the card**: edit a dashboard → *Add card* → *Roost*.
4. Watch it in **shadow mode** for some days. *Configure → Mode* shows what its self-check says and when it expects to
   be ready; when it is, the card shows *Let Roost steer* and a notice in **Settings → Repairs** offers it. Turn off any other schedule or automation on the thermostat first.

Everything else — every screen, every setting, the card, repairs, troubleshooting — is in the
**[guide](docs/GUIDE.md)**.

## Requirements

- Home Assistant **2025.3** or newer, with the recorder.
- A **Weheat** heat pump with the official Weheat integration.
- The **thermostat** that drives it, as a `climate` entity in Home Assistant (OpenTherm best; on/off works). The heat
  pump must follow the thermostat, not only its own heating curve — Roost checks this.
- An **electricity price**: a sensor with the prices of the coming hours (evcc, Nord Pool, Tibber, ENTSO-e, Frank
  Energie, … are read automatically), or your fixed contract's rate.
- Optional: a room sensor, solar and battery sensors, solar forecast, extra room sensors.

## Thermostats and heating

| Setup | How well |
|---|---|
| OpenTherm thermostat (Lyric T6, Nest, Tado, Remeha, …) | Best: the heat pump's response is learned from the Weheat history, also last winter |
| On/off thermostat, heat pump on its heating curve when asked | Works: Roost records the setpoint itself and learns the response in a few weeks |
| Heat pump only on its own heating curve | Roost cannot steer, and says so |

Floor heating stores the most heat, so Roost can shift the most; with radiators the house itself is the buffer and the
saving is smaller. A thermostat with its own schedule or learning works against Roost: turn that off (Roost notices it).

## Reporting a problem

**Settings → Devices & services → Roost → ⋮ → Download diagnostics**, then open a
[bug report](https://github.com/Akashironld/ha-roost/issues/new/choose) and drag the file in. It holds Roost's event log
(every thermostat change and why), the plan's inputs and the learned models — no passwords, no home location.

## Privacy

Roost talks to **Open-Meteo** (weather, with your home location), to **Weheat** (read-only, with the Weheat login you make in
the setup, for the history) and — only if you turn it on — once to **PDOK** (Dutch building register). Nothing
else, no account, no telemetry. Details in the [guide](docs/GUIDE.md#15-privacy-and-safety).

## How it decides

Per quarter of an hour the planner simulates the thermostat and the heat pump's learned response, the heat going into
the floor first and reaching the room with the learned delay, losses to outside with wind, sun on the facade and
internal gains. The cost of an hour is the electricity (heat ÷ COP) times the energy value of that hour, plus comfort
penalties and a small cost per change; extra rooms add their own. A dynamic-programming search over 36 hours finds a
plan, which is then refined with the heat pump's real delay. Only the first hour is carried out; the plan is made again
every 15 minutes. More in [docs/DESIGN.md](docs/DESIGN.md).

## Support

Issues and ideas: [GitHub issues](https://github.com/Akashironld/ha-roost/issues).

Roost is free and open source. If it saves you some money (or keeps your evening warm for less) and you'd like to say
thanks, you can buy me a coffee ☕ — the button opens the Ko-fi tip panel straight away, no account needed:

<a href="https://ko-fi.com/akashironl/?hidefeed=true&widget=true&embed=true"><img src="https://storage.ko-fi.com/cdn/kofi2.png?v=3" alt="Buy me a coffee on Ko-fi" height="36"></a>

Vind je het handig? Een koffie via [Ko-fi](https://ko-fi.com/akashironl/?hidefeed=true&widget=true&embed=true) wordt zeer gewaardeerd. ☕
