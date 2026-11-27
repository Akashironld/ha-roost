"""Roost's read-only Weheat calls: the login, refused tokens, Weheat not answering, the latest log, the pacing."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roost import weheat_api as api

PUMP = "hp-1"


@pytest.fixture
def token(monkeypatch):
    async def fake(hass, entry_id):
        return "tok"
    monkeypatch.setattr(api, "_access", fake)


async def test_no_login_asks_for_one(hass: HomeAssistant) -> None:
    with pytest.raises(api.WeheatLoginNeeded):
        await api._access(hass, "nope")
    e = MockConfigEntry(domain="roost", data={})
    e.add_to_hass(hass)
    with pytest.raises(api.WeheatLoginNeeded):
        await api._access(hass, e.entry_id)


async def test_latest_log(hass: HomeAssistant, aioclient_mock, token) -> None:
    url = f"{api.API_URL}/api/v1/heat-pumps/{PUMP}/logs/latest"
    aioclient_mock.get(url, json={"currentControlMethod": "OpenTherm"})
    assert (await api.async_latest(hass, "e", PUMP))["currentControlMethod"] == "OpenTherm"
    aioclient_mock.clear_requests()
    aioclient_mock.get(url, status=500)
    assert await api.async_latest(hass, "e", PUMP) is None          # Weheat down: unknown, tried again later
    aioclient_mock.clear_requests()
    aioclient_mock.get(url, status=401)
    with pytest.raises(api.WeheatLoginNeeded):
        await api.async_latest(hass, "e", PUMP)
    aioclient_mock.clear_requests()
    aioclient_mock.get(url, json=["not", "a", "dict"])
    assert await api.async_latest(hass, "e", PUMP) is None


async def test_get_lists_and_refusals(hass: HomeAssistant, aioclient_mock, token) -> None:
    aioclient_mock.get(f"{api.API_URL}/x", json=[{"a": 1}])
    assert await api._get(hass, "e", "/x", {}) == [{"a": 1}]
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{api.API_URL}/x", json={"not": "a list"})
    assert await api._get(hass, "e", "/x", {}) == []
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{api.API_URL}/x", status=401)
    with pytest.raises(api.WeheatLoginNeeded):
        await api._get(hass, "e", "/x", {})


async def test_pacer_keeps_weheats_limits(monkeypatch) -> None:
    waited = []

    async def sleep(s):
        waited.append(s)
    monkeypatch.setattr(api.asyncio, "sleep", sleep)
    p = api.Pacer({})
    await p.wait("logs")
    await p.wait("logs")
    await p.wait("energy")
    assert waited and 100 < waited[0] <= api.Pacer.GAP["logs"] and p.calls == 3
