"""Roost: smart heating planner for Weheat heat pumps."""
from __future__ import annotations

import json
import logging
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er, issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import CARD_URL, DOMAIN
from .manager import RoostManager

_LOGGER = logging.getLogger(__name__)


class RecentLog(logging.Handler):
    """The last warnings and errors of Roost's own loggers, for the diagnostics download (a bug report)."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: deque = deque(maxlen=60)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc = "".join(traceback.format_exception(*record.exc_info))[-1200:] if record.exc_info else None
            self.records.append({"t": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"), "level": record.levelname,
                                 "logger": record.name, "message": record.getMessage()[:600], "exception": exc})
        except Exception:  # noqa: BLE001 - never break logging
            pass


def recent_log(hass: HomeAssistant) -> RecentLog:
    data = hass.data.setdefault(DOMAIN, {})
    if "recent_log" not in data:
        handler = RecentLog()
        logging.getLogger(__package__).addHandler(handler)
        data["recent_log"] = handler
    return data["recent_log"]

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type RoostConfigEntry = ConfigEntry[RoostManager]


@websocket_api.websocket_command({vol.Required("type"): "roost/history", vol.Required("entity_id"): str,
                                  vol.Optional("days", default=7): vol.All(int, vol.Range(min=1, max=7))})
@websocket_api.async_response
async def _ws_history(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The look back for the card: the hours, events and days of the Roost that owns this entity."""
    ent = er.async_get(hass).async_get(msg["entity_id"])
    entry = hass.config_entries.async_get_entry(ent.config_entry_id) if ent and ent.config_entry_id else None
    mgr = getattr(entry, "runtime_data", None) if entry and entry.domain == DOMAIN else None
    if mgr is None:
        connection.send_error(msg["id"], "not_found", "No Roost for this entity")
        return
    connection.send_result(msg["id"], mgr.history_payload(msg["days"]))


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard card, register the services and the card's look back (websocket)."""
    websocket_api.async_register_command(hass, _ws_history)
    card = Path(__file__).parent / "frontend" / "roost-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), True)])
    version = hass.data.setdefault(DOMAIN, {}).get("version")
    if version is None:
        from homeassistant.loader import async_get_integration
        version = str((await async_get_integration(hass, DOMAIN)).version)
        hass.data[DOMAIN]["version"] = version
    url = f"{CARD_URL}?v={version}"
    add_extra_js_url(hass, url, es5=True)             # legacy frontend (older browsers, wall tablets)
    if _resources(hass) is not None:
        # Dashboards managed in the UI: the card only as a dashboard resource (an early start-page module can be
        # invisible after Home Assistant 2026.9 swaps in its scoped element registry, mostly in the mobile apps).
        hass.async_create_task(_async_card_as_resource(hass, url))
    else:
        add_extra_js_url(hass, url)

    def managers() -> list[RoostManager]:
        return [m for e in hass.config_entries.async_entries(DOMAIN) if isinstance(m := getattr(e, "runtime_data", None), RoostManager)]

    def targets(call: ServiceCall) -> list[RoostManager]:
        ms = managers()
        if not ms:
            raise ServiceValidationError("Roost is not set up")
        return ms

    async def pause(call: ServiceCall) -> None:
        for m in targets(call):
            await m.async_pause(call.data["hours"])

    async def resume(call: ServiceCall) -> None:
        for m in targets(call):
            await m.async_resume()

    async def import_history(call: ServiceCall) -> None:
        for m in targets(call):
            m.spawn(m.async_import(int(call.data["days"])), "weheat import")

    hass.services.async_register(DOMAIN, "pause", pause, vol.Schema({vol.Optional("hours", default=2): vol.All(vol.Coerce(float), vol.Range(min=0.25, max=72))}))
    hass.services.async_register(DOMAIN, "resume", resume, vol.Schema({}))
    hass.services.async_register(DOMAIN, "import_history", import_history,
                                 vol.Schema({vol.Optional("days", default=365): vol.All(vol.Coerce(int), vol.Range(min=7, max=365))}))
    return True


def _resources(hass: HomeAssistant):
    """The dashboard resources, when they are managed in the UI (not in YAML).

    Home Assistant keeps them under hass.data["lovelace"]: a dict up to early 2025, an object since. Only the
    storage collection can be changed; YAML resources are left alone."""
    try:
        from homeassistant.components.lovelace.resources import ResourceStorageCollection
    except ImportError:  # pragma: no cover - very old or changed Home Assistant
        return None
    data = hass.data.get("lovelace")
    res = data.get("resources") if isinstance(data, dict) else getattr(data, "resources", None)
    return res if isinstance(res, ResourceStorageCollection) else None


async def _async_card_as_resource(hass: HomeAssistant, url: str) -> None:
    if not await _async_register_resource(hass, url):
        add_extra_js_url(hass, url)                     # could not add the resource: fall back to the start page


async def _async_register_resource(hass: HomeAssistant, url: str) -> bool:
    """Add the card to the dashboard resources, or bring its version up to date. True when it is there."""
    res = _resources(hass)
    if res is None:
        return False
    try:
        await res.async_get_info()                       # loads the collection
        for item in res.async_items():
            if str(item.get("url", "")).split("?")[0] == CARD_URL:
                if item.get("url") != url or item.get("type") != "module":     # stored as "type"
                    await res.async_update_item(item["id"], {"res_type": "module", "url": url})
                return True
        await res.async_create_item({"res_type": "module", "url": url})
        return True
    except Exception:  # noqa: BLE001 - the card then loads from the start page
        _LOGGER.warning("Could not add the Roost card to the dashboard resources", exc_info=True)
        return False


async def async_setup_entry(hass: HomeAssistant, entry: RoostConfigEntry) -> bool:
    recent_log(hass)
    manager = RoostManager(hass, entry)
    entry.runtime_data = manager
    await manager.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.conf_key = _conf_key(entry)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RoostConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: RoostConfigEntry) -> None:
    """Removed by the user: take its repair notices with it, and the dashboard resource with the last one."""
    if not [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        if (res := _resources(hass)) is not None:
            try:
                await res.async_get_info()
                for item in res.async_items():
                    if str(item.get("url", "")).split("?")[0] == CARD_URL:
                        await res.async_delete_item(item["id"])
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Could not remove the card from the dashboard resources", exc_info=True)
    for issue_id in [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN and i.startswith(entry.entry_id)]:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _conf_key(entry: RoostConfigEntry) -> str:
    """The settings, without Roost's own Weheat token (refreshed in the entry now and then: no reason to reload)."""
    return json.dumps({"data": {k: v for k, v in entry.data.items() if k != "token"}, "options": dict(entry.options),
                       "rooms": {sid: dict(sub.data) for sid, sub in entry.subentries.items()}}, sort_keys=True, default=str)


async def _reload(hass: HomeAssistant, entry: RoostConfigEntry) -> None:
    mgr = getattr(entry, "runtime_data", None)
    if mgr is not None and getattr(mgr, "conf_key", None) == _conf_key(entry):
        return
    await hass.config_entries.async_reload(entry.entry_id)
