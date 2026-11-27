"""Suggestions for the setup: the entities Roost probably needs, so a user mostly checks instead of searching.

Only suggestions (shown filled in, never saved without the user's submit), found by device class, unit, area and
common names (evcc, Nord Pool, Tibber, ENTSO-e, Frank Energie, Solcast, Predbat, AlphaESS, SolarEdge, …).
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import series

PV_WORDS = ("pv", "solar", "zon")
EXPORT_WORDS = ("feedin", "feed_in", "export", "teruglever", "terug")


def _area(hass: HomeAssistant, entity_id: str) -> str | None:
    ent = er.async_get(hass).async_get(entity_id)
    if ent is None:
        return None
    if ent.area_id:
        return ent.area_id
    dev = dr.async_get(hass).async_get(ent.device_id) if ent.device_id else None
    return dev.area_id if dev else None


def _device(hass: HomeAssistant, entity_id: str) -> str | None:
    ent = er.async_get(hass).async_get(entity_id)
    return ent.device_id if ent else None


def _sensors(hass: HomeAssistant, device_class: str | None = None) -> list:
    out = []
    for st in hass.states.async_all("sensor"):
        if st.state in ("unavailable", "unknown"):
            continue
        if device_class and st.attributes.get("device_class") != device_class:
            continue
        out.append(st)
    return out


def _has(eid: str, words) -> bool:
    e = eid.lower()
    return any(w in e for w in words)


def thermostat(hass: HomeAssistant) -> str | None:
    """The one climate entity that heats and does not cool (an air conditioner cools, dries or blows)."""
    found = [st.entity_id for st in hass.states.async_all("climate")
             if "heat" in (st.attributes.get("hvac_modes") or []) and not set(st.attributes.get("hvac_modes") or []) & {"cool", "dry", "fan_only"}]
    return found[0] if len(found) == 1 else None


LIVING = ("woonkamer", "living", "lounge", "huiskamer", "wohnzimmer", "salon", "sejour")


def room_sensor(hass: HomeAssistant, thermostat_id: str | None, heat_pump_device: str | None) -> str | None:
    """A temperature sensor in the thermostat's area (or, when the thermostat has none, in the living room), not of
    the thermostat, the heat pump or another climate device (an air conditioner measures at its own outlet)."""
    if not thermostat_id:
        return None
    area = _area(hass, thermostat_id)
    climate_devices = {_device(hass, st.entity_id) for st in hass.states.async_all("climate")}
    own = {_device(hass, thermostat_id), heat_pump_device} | climate_devices

    def in_area(eid: str) -> bool:
        a = _area(hass, eid)
        return a == area if area else bool(a and _has(a, LIVING))
    found = [st.entity_id for st in _sensors(hass, "temperature")
             if in_area(st.entity_id) and _device(hass, st.entity_id) not in own
             and not _has(st.entity_id, ("outside", "outdoor", "buiten", "water", "dhw", "floor", "vloer"))]
    return found[0] if len(found) == 1 else (sorted(found, key=lambda e: ("temp" not in e, len(e)))[0] if found else None)


def prices(hass: HomeAssistant) -> tuple[str | None, str | None]:
    """(import, export) price sensors with a forecast in their attributes."""
    imp: list[str] = []
    exp: list[str] = []
    for st in hass.states.async_all("sensor"):
        unit = str(st.attributes.get("unit_of_measurement") or "")
        if "kwh" not in unit.lower():
            continue
        if not series.find_slots(dict(st.attributes)):
            continue
        (exp if _has(st.entity_id, EXPORT_WORDS) else imp).append(st.entity_id)
    pick = lambda xs: sorted(xs, key=lambda e: (not _has(e, ("forecast", "grid", "import", "price", "tariff", "prijs")), len(e)))[0] if xs else None
    return pick(imp), pick(exp)


def energy(hass: HomeAssistant) -> dict[str, str]:
    """Solar, grid, battery and house power and the solar forecasts, as far as they can be told apart."""
    out: dict[str, str] = {}
    power = _sensors(hass, "power")
    pv = [s.entity_id for s in power if _has(s.entity_id, PV_WORDS) and not _has(s.entity_id, ("forecast", "battery", "accu", "string", "mppt"))]
    if pv:
        out["pv_power"] = sorted(pv, key=lambda e: (not _has(e, ("current", "production", "power")), len(e)))[0]
    family = _device(hass, out["pv_power"]) if "pv_power" in out else None
    same = lambda e: family is None or _device(hass, e) == family
    grid = [s.entity_id for s in power if _has(s.entity_id, ("grid", "net_power", "meter")) and same(s.entity_id)]
    if grid:
        out["grid_power"] = sorted(grid, key=len)[0]
    soc = [s.entity_id for s in _sensors(hass, "battery") if _has(s.entity_id, ("battery", "accu", "soc")) and same(s.entity_id)
           and not _has(s.entity_id, ("phone", "telefoon", "watch", "car", "auto", "vehicle"))]
    if soc and family is not None:
        out["battery_soc"] = sorted(soc, key=len)[0]
        bp = [s.entity_id for s in power if _has(s.entity_id, ("battery", "accu")) and _device(hass, s.entity_id) == _device(hass, out["battery_soc"])]
        if bp:
            out["battery_power"] = sorted(bp, key=len)[0]
    house = [s.entity_id for s in power if _has(s.entity_id, ("load", "house", "home", "huis", "consumption"))
             and not _has(s.entity_id, ("battery", "accu")) and same(s.entity_id)]
    if house:
        out["house_power"] = sorted(house, key=len)[0]
    kwh = [s for s in _sensors(hass) if str(s.attributes.get("unit_of_measurement") or "").lower() == "kwh"
           and _has(s.entity_id, ("forecast", "verwachting", "predbat", "solcast")) and _has(s.entity_id, PV_WORDS)]
    today = [s.entity_id for s in kwh if _has(s.entity_id, ("today", "vandaag"))]
    tomorrow = [s.entity_id for s in kwh if _has(s.entity_id, ("tomorrow", "morgen"))]
    if today:
        out["pv_forecast"] = sorted(today, key=len)[0]
    if tomorrow:
        out["pv_forecast_tomorrow"] = sorted(tomorrow, key=len)[0]
    return out


def _power_on_device(hass: HomeAssistant, entity_id: str | None, words: tuple = ()) -> str | None:
    """A power sensor on the same device as an energy meter (the dashboard has the kWh meter, Roost wants kW)."""
    dev = _device(hass, entity_id) if entity_id else None
    if dev is None:
        return None
    hits = [s.entity_id for s in _sensors(hass, "power") if _device(hass, s.entity_id) == dev and (not words or _has(s.entity_id, words))]
    return sorted(hits, key=len)[0] if hits else None


async def async_energy_dashboard(hass: HomeAssistant) -> dict[str, str]:
    """What Home Assistant's own Energy dashboard already knows: the solar, grid and battery power sensors (its
    power settings, else a power sensor on the device of its kWh meter), the grid sign and the battery's charge.
    Empty when the dashboard is not set up. Only real entities, never a statistic of another integration."""
    try:
        from homeassistant.components.energy.data import async_get_manager
        prefs: dict[str, Any] = dict((await async_get_manager(hass)).data or {})
    except Exception:  # noqa: BLE001 - no energy integration: the names are searched as before
        return {}
    out: dict[str, str] = {}

    def ok(eid: Any) -> bool:
        return isinstance(eid, str) and "." in eid and ":" not in eid and hass.states.get(eid) is not None
    sources: list[dict[str, Any]] = [dict(x) for x in prefs.get("energy_sources") or [] if isinstance(x, dict)]
    for src in sources:
        kind = src.get("type")
        pc: dict[str, Any] = dict(src.get("power_config") or {})
        if kind == "solar":
            rate = src.get("stat_rate")
            pv = rate if ok(rate) else _power_on_device(hass, src.get("stat_energy_from"), PV_WORDS)
            if pv and "pv_power" not in out:
                out["pv_power"] = pv
        elif kind == "grid":
            if ok(pc.get("stat_rate")):
                out.update({"grid_power": pc["stat_rate"], "grid_sign": "import_positive"})
            elif ok(pc.get("stat_rate_inverted")):
                out.update({"grid_power": pc["stat_rate_inverted"], "grid_sign": "export_positive"})
            elif ok(src.get("stat_rate")) and not pc:
                out.update({"grid_power": src["stat_rate"], "grid_sign": "import_positive"})
            else:
                meter = next((f.get("stat_energy_from") for f in src.get("flow_from") or [] if isinstance(f, dict)), None)
                grid = _power_on_device(hass, meter, ("grid", "net", "meter", "p1", "import"))
                if grid:
                    out["grid_power"] = grid
        elif kind == "battery":
            if ok(pc.get("stat_rate")):
                out["battery_power"] = pc["stat_rate"]          # + = discharging, as Roost counts it
            elif ok(src.get("stat_rate")) and not pc:
                out["battery_power"] = src["stat_rate"]
            if ok(src.get("stat_soc")):
                out["battery_soc"] = src["stat_soc"]
    return out


def friendly(hass: HomeAssistant, entity_id: str | None) -> str:
    if not entity_id:
        return "—"
    st = hass.states.get(entity_id)
    return (st.attributes.get("friendly_name") or entity_id) if st else entity_id
