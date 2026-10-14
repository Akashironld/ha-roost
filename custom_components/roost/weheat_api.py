"""Read-only access to a Weheat heat pump's history through the login of the user's Weheat integration.

Roost never refreshes or stores the Weheat token: the Weheat integration refreshes it every couple of minutes, and
Roost only uses the current access token. When it has expired, the import waits and tries again later.
Endpoints are the Weheat third-party API the Weheat integration itself uses (hourly logs and energy logs)."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)
API_URL = "https://api.weheat.nl/third_party"
CHUNK_DAYS = 7


class WeheatUnavailable(Exception):
    """No usable Weheat login right now."""


def heat_pump_id(hass: HomeAssistant, device_id: str) -> tuple[str | None, str | None]:
    """(Weheat heat pump id, config entry id of the Weheat integration) for a device."""
    dev = dr.async_get(hass).async_get(device_id)
    if dev is None:
        return None, None
    hp = next((i[1] for i in dev.identifiers if i[0] == "weheat"), None)
    entry = next((e for e in dev.config_entries if (ce := hass.config_entries.async_get_entry(e)) and ce.domain == "weheat"), None)
    return hp, entry


def _token(hass: HomeAssistant, entry_id: str) -> str:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise WeheatUnavailable("the Weheat integration is not set up")
    tok = (entry.data or {}).get("token") or {}
    access, expires = tok.get("access_token"), tok.get("expires_at")
    if not access:
        raise WeheatUnavailable("the Weheat integration has no login")
    if expires is not None and float(expires) < time.time() + 30:
        raise WeheatUnavailable("the Weheat login is being refreshed")
    return access


async def _get(hass: HomeAssistant, entry_id: str, path: str, params: dict) -> list[dict]:
    for attempt in range(4):
        try:
            token = _token(hass, entry_id)
        except WeheatUnavailable:
            if attempt == 3:
                raise
            await asyncio.sleep(40)             # the Weheat integration refreshes its token within ~2 minutes
            continue
        async with async_get_clientsession(hass).get(f"{API_URL}{path}", params=params, timeout=60,
                                                     headers={"Authorization": f"Bearer {token}"}) as r:
            if r.status == 401 and attempt < 3:
                await asyncio.sleep(40)
                continue
            r.raise_for_status()
            data = await r.json()
            return data if isinstance(data, list) else []
    return []


def _fmt(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def async_fetch_history(hass: HomeAssistant, entry_id: str, pump_id: str, start: datetime, end: datetime,
                              progress=None) -> tuple[list[dict], list[dict]]:
    """Hourly logs and hourly energy logs between start and end, a week at a time."""
    logs: list[dict] = []
    energy: list[dict] = []
    t = start
    while t < end:
        t2 = min(end, t + timedelta(days=CHUNK_DAYS))
        q = {"startTime": _fmt(t), "endTime": _fmt(t2), "interval": "Hour"}
        logs += await _get(hass, entry_id, f"/api/v1/heat-pumps/{pump_id}/logs", q)
        energy += await _get(hass, entry_id, f"/api/v1/energy-logs/{pump_id}", q)
        if progress:
            progress(t2)
        t = t2
        await asyncio.sleep(0.5)                # be gentle with the API
    return logs, energy
