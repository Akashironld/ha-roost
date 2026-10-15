# Testing Roost (beta)

Thanks for trying Roost while it is in beta! This page is about testing: what to expect, how to install and update,
and what is useful to report. Every screen, setting and the card are in the [setup and user guide](GUIDE.md).

## What to expect

- **Roost starts in shadow mode.** It plans and shows what it would do and why, but does not touch your thermostat.
  It only steers after its self-check is happy **and you switch it on** (*Configure → Mode*, or the card's
  *Let Roost steer* button). You can switch back to shadow or off at any time.
- **It is a beta.** Expect rough edges: odd plans, unclear texts, a setting that does not fit your home. That is what
  this test is for.

## Install

With [HACS](https://hacs.xyz):

1. **HACS → ⋮ → Custom repositories**: paste `https://github.com/Akashironld/ha-roost`, type **Integration**, **Add**.
2. Search HACS for **Roost** → **Download** → restart Home Assistant.
3. **Settings → Devices & services → Add integration → Roost**, and go on with section 4 of the
   [guide](GUIDE.md#4-add-the-integration-screen-by-screen).
4. After the first setup screen Weheat's login page opens: log in with your Weheat account (nothing else to fill in).
   Roost then imports your heat pump's history from Weheat (read-only); a year takes a few hours in the background.

Without HACS: download **`roost.zip`** from the newest [release](https://github.com/Akashironld/ha-roost/releases),
unzip it into `custom_components/roost` in your Home Assistant configuration folder (so that
`custom_components/roost/manifest.json` exists) and restart.

## Updates

- HACS offers new versions by itself (*Settings → Updates*). To hear about them on GitHub: on the repository page
  **Watch → Custom → Releases**.
- Without HACS: download the new `roost.zip`, **delete the old files** in `custom_components/roost`, unzip the new ones
  there and restart. Your settings and what Roost learned stay (Home Assistant keeps them, not that folder).
- Updating from 0.5.2: Home Assistant shows *Re-authenticate* at Roost once — click it and log in with your Weheat
  account.

## What I would like to hear

- **Problems**: *Issues → New issue → Bug report*. Please attach the **diagnostics file** (*Settings → Devices &
  services → Roost → ⋮ → Download diagnostics*): it holds what Roost learned, its plan and its decisions, without
  passwords or tokens. It saves a lot of back and forth.
- **After a week in shadow mode**: do its plans make sense to you? Would you have done the same? Is anything on the
  card or in the texts unclear?
- **Your setup**: thermostat (OpenTherm or on/off), dynamic or fixed price, solar or battery — it helps to know which
  combinations were tested.

## Stopping

Remove the integration (*Settings → Devices & services → Roost → ⋮ → Delete*), then remove Roost in HACS (or delete
the folder `custom_components/roost`) and restart. If Roost was steering, check that your thermostat is back on your
usual temperature or schedule.
