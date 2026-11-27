"""Websocket roost/energy: the card's Energy tab (energy_table.py) from Home Assistant's long-term statistics."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from homeassistant.components import websocket_api
from homeassistant.components.recorder import get_instance, statistics
from homeassistant.components.recorder import history as rh
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from . import energy_table, value
from .const import (
    CONF_BATTERY_POWER,
    CONF_EXPORT_PRICE,
    CONF_FIXED_EXPORT_PRICE,
    CONF_FIXED_PRICE,
    CONF_GRID_POWER,
    CONF_GRID_SIGN,
    CONF_HOUSE_POWER,
    CONF_IMPORT_PRICE,
    CONF_PRICE_MODE,
    CONF_PV_POWER,
    CONF_ROOM,
    DOMAIN,
)
from .volcompat import vol


def _ids(mgr) -> dict[str, str]:
    """Role -> statistic id: the Weheat meters and temperatures, the room, the price sensor (all in, sensor mode)."""
    conf = mgr.conf
    ids = {role: mgr.ent[role] for role in (*energy_table.ENERGY, "outdoor", "water_out") if mgr.ent.get(role)}
    if conf.get(CONF_ROOM):
        ids["room"] = conf[CONF_ROOM]
    if conf.get(CONF_PRICE_MODE, "sensor") == "sensor" and conf.get(CONF_IMPORT_PRICE):
        ids["price"] = conf[CONF_IMPORT_PRICE]
        if conf.get(CONF_EXPORT_PRICE):
            ids["price_export"] = conf[CONF_EXPORT_PRICE]
    # where the heat pump's electricity came from: solar, the home battery and the house (or the grid meter)
    for role, key in (("pv", CONF_PV_POWER), ("battery", CONF_BATTERY_POWER), ("house", CONF_HOUSE_POWER), ("grid", CONF_GRID_POWER)):
        if conf.get(key):
            ids[role] = conf[key]
    return ids


def _kw(hass: HomeAssistant, eid: str) -> float:
    """Factor from a power sensor's unit to kW (W unless it says kW)."""
    st = hass.states.get(eid)
    unit = str(st.attributes.get("unit_of_measurement", "W")).lower() if st is not None else "w"
    return 1.0 if unit == "kw" else 0.001


async def _async_defrosts(hass: HomeAssistant, mgr, start: datetime) -> tuple[dict[int, int], int | None]:
    """Defrosts per hour from the unit's state history (Home Assistant keeps some days of it) and the first hour it
    covers; ({}, None) without a state entity or history."""
    eid = mgr.ent.get("state")
    if not eid:
        return {}, None
    try:
        res = await get_instance(hass).async_add_executor_job(partial(
            rh.state_changes_during_period, hass, start, dt_util.utcnow(), entity_id=eid, no_attributes=True,
            include_start_time_state=True))
    except Exception:  # noqa: BLE001 - no recorder history: the numbers are estimated from the defrost meter
        return {}, None
    states = res.get(eid, [])
    if not states:
        return {}, None
    out: dict[int, int] = {}
    prev = None
    for st in states:
        t = int(st.last_changed.timestamp())
        if st.state == "defrosting" and prev != "defrosting":
            out[t - t % 3600] = out.get(t - t % 3600, 0) + 1
        if st.state not in ("unavailable", "unknown"):
            prev = st.state
    # the state at the start is known (the first row then sits at the start): every hour counts; otherwise the
    # history begins later (purged) and counts from its first whole hour
    first = int(states[0].last_changed.timestamp())
    if first <= start.timestamp() + 60:
        return out, int(start.timestamp()) - int(start.timestamp()) % 3600
    return out, first - first % 3600 + 3600


async def async_energy(hass: HomeAssistant, mgr, period: str) -> dict:
    conf = mgr.conf
    now = dt_util.now()
    zone = dt_util.get_default_time_zone()
    start = energy_table.first_start(now, period).replace(tzinfo=zone).astimezone(timezone.utc)
    ids = _ids(mgr)
    stats = await get_instance(hass).async_add_executor_job(
        statistics.statistics_during_period, hass, start, dt_util.utcnow(), set(ids.values()), "hour", None,
        {"mean", "min", "change"})
    hours: dict[int, dict] = {}
    for role, eid in ids.items():
        for r in stats.get(eid, []):
            st = r["start"]
            ts = int(st if isinstance(st, (int, float)) else datetime.fromisoformat(str(st)).timestamp())
            v = hours.setdefault(ts, {})
            change, mean, low = r.get("change"), r.get("mean"), r.get("min")
            if role in energy_table.ENERGY:
                if change is not None:
                    v[role] = float(change)
            else:
                if mean is not None:
                    v[role] = float(mean)
                if role == "outdoor" and low is not None:
                    v["outdoor_min"] = float(low)
    # hours without any meter say nothing (the unit or Home Assistant was away)
    hours = {t: v for t, v in hours.items() if any(k in v for k in energy_table.ENERGY)}
    # power sensors to kW; no sensor for the house: from the grid meter, solar and battery
    k = {role: _kw(hass, ids[role]) for role in ("pv", "battery", "house", "grid") if role in ids}
    imp_pos = conf.get(CONF_GRID_SIGN, "import_positive") == "import_positive"
    for v in hours.values():
        for role, f in k.items():
            if role in v:
                v[role] *= f
        if "house" not in ids and "grid" in v and "pv" in v:
            v["house"] = value.house_use(v["grid"], v["pv"], v.get("battery"), imp_pos)
    defrosts, counted_from = await _async_defrosts(hass, mgr, start)
    pump = mgr.pump
    bias = pump.bias or 0.0
    fixed = conf.get(CONF_FIXED_PRICE) if conf.get(CONF_PRICE_MODE) == "fixed" else None
    fixed_exp = conf.get(CONF_FIXED_EXPORT_PRICE) if conf.get(CONF_PRICE_MODE) == "fixed" else None
    rows = energy_table.build(
        hours, period, lambda ts: dt_util.as_local(datetime.fromtimestamp(ts, tz=timezone.utc)),
        # the model's COP is at the weather service's temperature: the unit's own sensor reads `bias` higher
        cop_expected=lambda t, q: pump.cop(t - bias, q),
        log={e["ts"]: e for e in mgr.log.hour_log}, fixed_price=float(fixed) if fixed is not None else None,
        fixed_export=float(fixed_exp) if fixed_exp not in (None, "") else None,
        moment=lambda n: int(n.replace(tzinfo=zone).timestamp()), defrosts=defrosts, counted_from=counted_from)
    return {"period": period, "rows": rows, "currency": hass.config.currency or "EUR",
            "model": pump.source,
            "has": sorted(ids)}


@websocket_api.websocket_command({vol.Required("type"): "roost/energy", vol.Required("entity_id"): str,
                                  vol.Optional("period", default="day"): vol.In(list(energy_table.PERIODS))})
@websocket_api.async_response
async def ws_energy(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The Energy tab of the Roost that owns this entity."""
    ent = er.async_get(hass).async_get(msg["entity_id"])
    entry = hass.config_entries.async_get_entry(ent.config_entry_id) if ent and ent.config_entry_id else None
    mgr = getattr(entry, "runtime_data", None) if entry and entry.domain == DOMAIN else None
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No Roost for this entity")
        return
    connection.send_result(msg["id"], await async_energy(hass, mgr, msg["period"]))
