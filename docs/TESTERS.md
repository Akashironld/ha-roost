# Testing Roost (private beta)

Thanks for testing Roost! This page is for the handful of people testing it before it is public. Everything else —
every screen, setting and the card — is in the [setup and user guide](GUIDE.md).

## What to expect

- **Roost starts in shadow mode.** It plans and shows what it would do and why, but does not touch your thermostat.
  It only steers after its self-check is happy **and you switch it on** (*Configure → Mode*, or the card's
  *Let Roost steer* button). You can switch back to shadow or off at any time.
- **It is a beta.** Expect rough edges: odd plans, unclear texts, a setting that does not fit your home. That is what
  this test is for.
- **The repository is private.** Only the testers and the author see the code, the releases and the issues. Please
  do not share the files.

## Install (without HACS)

HACS cannot install from a private repository, so a tester installs by hand. It takes a few minutes.

1. Open the [Releases](../../releases) of this repository and take the newest one (marked *Pre-release*). Under
   **Assets**, download **`roost.zip`**.
2. In your Home Assistant configuration folder (where `configuration.yaml` is — with the *File editor*, *Samba
   share* or *Studio Code Server* app), open the folder **`custom_components`** (create it if it is not there) and
   in it create a folder **`roost`**.
3. Unzip `roost.zip` **into that `roost` folder**, so that `custom_components/roost/manifest.json` exists (not
   `custom_components/roost/roost/…`).
4. **Restart Home Assistant** (Settings → System → ⏻ Restart).
5. Go on with section 4 of the [guide](GUIDE.md#4-add-the-integration-screen-by-screen): *Settings → Devices &
   services → Add integration → Roost*.
6. Roost imports your heat pump's history from Weheat (read-only) through the Weheat integration's login; a year takes
   a few hours in the background. Optional: give Roost its own login under *Reconfigure → Weheat login*, with the same
   Client ID and Secret as the Weheat integration, so the import never waits for that integration's login.

## Updates

- To hear about new versions: on the repository page click **Watch → Custom → Releases**. GitHub then emails you
  when a new version is out.
- To update: download the new `roost.zip`, **delete the old files** in `custom_components/roost`, unzip the new ones
  there and restart Home Assistant. Your settings and what Roost learned stay (they are kept by Home Assistant, not in
  that folder).
- Once Roost is public you can switch to HACS; the guide will say how.

## What I would like to hear

- **Problems**: *Issues → New issue → Bug report*. Please attach the **diagnostics file** (*Settings → Devices &
  services → Roost → ⋮ → Download diagnostics*): it holds what Roost learned, its plan and its decisions, without
  passwords or tokens. It saves a lot of back and forth.
- **After a week in shadow mode**: do its plans make sense to you? Would you have done the same? Is anything on the
  card or in the texts unclear?
- **Your setup**: thermostat (OpenTherm or on/off), dynamic or fixed price, solar or battery — it helps to know which
  combinations were tested.

## Stopping

Remove the integration (*Settings → Devices & services → Roost → ⋮ → Delete*), then delete the folder
`custom_components/roost` and restart. If Roost was steering, check that your thermostat is back on your usual
temperature or schedule.
