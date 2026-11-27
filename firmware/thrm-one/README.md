# THRM ONE firmware for Roost

ESPHome firmware for the **[elvinhome THRM ONE](https://elvinhome.io/shop/thrm-one-60)** (ESP32-C6 OpenTherm master),
so that [Roost](../../README.md) can steer a heat pump's **flow temperature** over OpenTherm, while the box stays the
safety layer: it keeps every request within limits and heats on its own heating curve when Roost or Home Assistant is
gone.

Built on the THRM ONE's own open firmware by elvinhome ([codeberg.org/elvinhome/thrm-one](https://codeberg.org/elvinhome/thrm-one),
v0.3.0). Tested on a **Weheat Blackbird P80** set to *OpenTherm* in the Weheat app; other heat pumps and boilers that
take a flow setpoint (OpenTherm ID 1) should work, but have not been tested.

> **Licence: GPL-3.0** (this folder only — see [LICENSE](LICENSE)), as the elvinhome firmware and ESPHome's C++
> components it is built from. Roost itself is MIT. Not affiliated with, endorsed or certified by The OpenTherm
> Association, Weheat or elvinhome. You flash it at your own risk; the THRM ONE's own firmware can always be put back
> (see *Back to the original firmware*).

## What is in it

| File | What |
|---|---|
| `thrm-one-roost.yaml` | The device: Wi-Fi, API, version, the action `set_plan`; includes the files below |
| `base.yaml` | Hardware (pins, OpenTherm interface), from elvinhome |
| `opentherm.yaml` | What goes over the bus: only the IDs the heat pump answers |
| `control.yaml` | Who steers, the limits, anti-cycling, soft start, the fallback heating curve and Roost's plan |
| `ha-sensors.yaml` | Room and outdoor sensor from Home Assistant (set on the device) |
| `wifi-setup.yaml`, `web-login.yaml`, `ethernet.yaml`, `status-led.yaml` | Wi-Fi without reflashing, the web page login, optional Ethernet, the LED codes |
| `web/` | The box's own web page (`http://<ip>/`, login `admin` / `Roost` until you change it) |
| `components/opentherm/` | ESPHome 2026.10.1's OpenTherm component with an edge-timestamp decoder (see below) |
| `decoder-patch/` | The same decoder change as a patch against ESPHome 2026.10.1 |
| `secrets.example.yaml` | Copy to `secrets.yaml` with your Wi-Fi network and password |

**The decoder.** A Weheat answers with a duty cycle of about 600/400 µs instead of 500/500 µs; ESPHome's sampling
decoder then rejects a few percent of the answers. The included component decodes from the signal's edges instead
(`edge_decoder: true`, `rmt_capture: true` in `opentherm.yaml`). elvinhome is bringing this approach into ESPHome
itself ([esphome/esphome#23245](https://github.com/esphome/esphome/pull/23245)); once that is released this firmware
will use the standard component again, without its own copy.

## Install

You need ESPHome **2026.10.1** (the included component belongs to that version) and a THRM ONE connected to the heat
pump's OpenTherm terminals (see elvinhome's manual).

1. Copy this folder, copy `secrets.example.yaml` to `secrets.yaml` and fill in your Wi-Fi network and password.
2. Optional: in `thrm-one-roost.yaml` under `substitutions`, the room sensor (`room_sensor`) and outdoor sensor
   (`outside_sensor`) the box starts with. Both can be changed on the device later.
3. Flash over the air, from the ESPHome dashboard or the command line:
   `esphome run thrm-one-roost.yaml --device <ip of the box>`
   **Not while the heat pump heats**: the box restarts, OpenTherm is silent for some 15 seconds, and a Weheat then
   stops and waits about an hour before it starts again. While it stands still or makes hot water it is fine.
4. Home Assistant finds the box (*ESPHome*); add it. The entities are named `<domain>.thrm_one_<mac6>_<name>`.
5. In the Weheat app, set the heat pump's control to **OpenTherm**.
6. In Roost: *Configure → Steering → OpenTherm*, pick the box. Roost starts in shadow mode; see the
   [guide](../../docs/GUIDE.md#steering-over-opentherm).

**Back to the original firmware**: flash elvinhome's `esphome/thrm-one.yaml` from their repository the same way.

## The agreement with Roost

The box is the safety layer: Roost (or an automation) only decides *which* flow temperature; the box keeps it within
its limits and falls back by itself. Any OpenTherm master that keeps the same agreement works with Roost.

**Roost writes**

| Entity | Meaning |
|---|---|
| `number.…_flow_setpoint` | The flow temperature asked (°C), 0 = no heat demand. Every write renews the request, also the same value; Roost writes at least every 5 minutes |
| `select.…_control_mode` | `Home Assistant` (Roost steers) or `Heating curve` (the box always steers itself). Roost sets it when it starts or stops steering |
| `text.…_heating_curve` | Optional: the fallback curve as `outdoor:flow,…` (2–8 points), filled from Roost's curve advice while `switch.…_follow_roost_curve` is on |
| action `esphome.thrm_one_<mac6>_set_plan` | Roost's plan for when it is gone (below) |

**Roost reads**

| Entity | Meaning |
|---|---|
| `sensor.…_control_state` | Who steers: `home_assistant` · `curve` · `curve_ha_offline` · `curve_no_command` · `plan_ha_offline` · `plan_no_command` · `off` |
| `sensor.…_flow_setpoint_active` | What goes to the heat pump as ID 1 now (after limits and soft start) |
| `sensor.…_flow_temperature`, `…_return_temperature`, `…_air_inlet_temperature` | IDs 25, 28 and 27 (on a monoblock, 27 is the outdoor unit's air inlet) |
| `binary_sensor.…_heat_demand`, `…_heating_active`, `…_compressor_running`, `…_hot_water_active`, `…_fault` | ID 0 |
| `sensor.…_max_flow_limit_heat_pump` | ID 49: the highest flow the heat pump accepts (a Weheat: 40 °C) |
| `number.…_min_flow`, `…_max_flow`, `…_min_run_time`, `…_min_off_time` | The box's limits; Roost plans within them |
| `sensor.…_plan_hours_left` | Hours left of Roost's plan on the box (0 = none) |
| `binary_sensor.…_communication_error` | The heat pump has not answered for 10 s |

**Always, in every state**

- Flow between *Min Flow* and *Max Flow*, at most 45 °C and never above the heat pump's own limit (ID 49).
- Anti-cycling: heat demand at least *Min Run Time* on (default 30 min) and *Min Off Time* off (15 min), also while
  Roost steers. Only the *Heating* switch goes straight through. In the first minute after a restart the demand of
  before the restart holds.
- Soft start: a new demand starts at return + 2 °C; a gap of more than *Soft Start Above* (5 °C) rises 1 °C per minute.
- Hot water: the box sends no hot-water setpoint and leaves hot water enabled; the heat pump makes it itself.

**When requests stop**

| Situation | What the box does | *Control State* |
|---|---|---|
| Roost writes | Follows *Flow Setpoint* within the limits | `home_assistant` |
| No request for *Command Timeout* (15 min), Home Assistant still there | Roost's plan if it has one, else its own curve with the room on/off | `plan_no_command` / `curve_no_command` |
| Home Assistant gone for *Command Timeout* | Roost's plan if it has one, else its own curve (the room counts 30 more minutes) | `plan_ha_offline` / `curve_ha_offline` |
| Requests come back | Roost again at once, without a jump (soft start) | `home_assistant` |
| Restart or power cut | The last request, mode and curve from flash; the timeout counts from the start; no plan | — |
| No outdoor temperature | The chosen source → the other one → *Fixed Flow* | `outside_source` |

The box never restarts because Wi-Fi or Home Assistant is gone (`reboot_timeout: 0s`; ESPHome's default of 15 minutes
would stop a Weheat for an hour every 15 minutes during an outage).

## Roost's plan on the box

While Roost steers, it calls `set_plan` on every new plan and else every hour:

| Field | |
|---|---|
| `flows: float[]` | The flow per hour from the current hour on, 0 = off (at most 36) |
| `outside: float[]` | The outdoor temperature Roost planned with per hour, as the heat pump's air inlet would read it |
| `sec_into_hour: int` | Seconds of the first hour already gone |

An empty plan means "forget it": Roost sends one when it stops steering (shadow, off, removed). The box keeps the plan
in memory only and counts the hours with its own timer (it has no clock, so it does not depend on a time server).
When requests stop it runs the plan hour by hour:

- corrected for the real outdoor temperature (from ID 27): `flow + curve(outdoor now) − curve(outdoor planned)`, at most ±3 °C;
- never more than 5 °C above its own heating curve (without a room sensor it steers blind);
- off for at most 3 hours in a row, counting the time without demand before the plan too (2 hours below 0 °C or
  without an outdoor temperature); then its own curve;
- a plan older than 36 hours, a finished plan or a restart: its own curve.

Roost tries an empty plan again every 10 minutes while the box is away; only when Roost is removed while the box
cannot be reached, the plan stays on it until it runs out or the box restarts.

Tested on 26-11-2026 with the box's Home Assistant connection switched off for 18 minutes: after the timeout it went `plan_no_command` → `plan_ha_offline`, asked 29.4 °C and then, at the next hour, 27.5 °C (Roost's 30 and 28, corrected for a warmer outdoor temperature); the Weheat followed both and went from hot water straight to heating at its lowest speed without a stop. Connected again, Roost took over within a minute. The box did not restart.

## What a Weheat answers over OpenTherm

Scanned on a Blackbird P80 (IDs 1–255): it answers 0, 1, 2, 3, 7, 14, 16, 17, 24, 25, 27, 28, 49, 57, 93–95, 125 and
127, nothing in the manufacturer range. There is no outlet temperature, speed, pressure, starts, hours or fault code
over OpenTherm (those only come from Weheat's cloud). It ignores a maximum modulation (ID 14) and the hot-water bit;
it rests about an hour after any stop.

## Credits

- **elvinhome** designed the THRM ONE and wrote the open firmware this is built on — thank you, Elvin, also for
  providing the author's unit free of charge and for taking the decoder into ESPHome.
- The OpenTherm component is ESPHome's (by Oleg Tarasov and the ESPHome contributors), with the decoder change above.
