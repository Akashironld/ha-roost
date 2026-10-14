"""Roost: smart heating planner for Weheat heat pumps."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import CARD_URL, DOMAIN
from .manager import RoostManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type RoostConfigEntry = ConfigEntry[RoostManager]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard card and register the services."""
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
            hass.async_create_background_task(m.async_import(int(call.data["days"])), f"{DOMAIN} weheat import")

    hass.services.async_register(DOMAIN, "pause", pause, vol.Schema({vol.Optional("hours", default=2): vol.All(vol.Coerce(float), vol.Range(min=0.25, max=72))}))
    hass.services.async_register(DOMAIN, "resume", resume, vol.Schema({}))
    hass.services.async_register(DOMAIN, "import_history", import_history,
                                 vol.Schema({vol.Optional("days", default=400): vol.All(vol.Coerce(int), vol.Range(min=7, max=1500))}))
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
    manager = RoostManager(hass, entry)
    entry.runtime_data = manager
    await manager.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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


async def _reload(hass: HomeAssistant, entry: RoostConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
