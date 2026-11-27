"""Roost's Weheat history (read-only): the import month by month, a login refused, Weheat failing, the refresh of
the hours since, the unit's fixed data. Weheat itself is stood in for."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.roost import history, weheat_sync
from custom_components.roost.weheat_api import WeheatLoginNeeded

H = int(dt_util.utcnow().timestamp() // 3600 * 3600)


@pytest.fixture
def fake(monkeypatch):
    calls = {"months": 0, "history": 0, "learn": 0}

    async def months(hass, entry_id, pump, start, end, on_month, note, last, energy_logs=True):
        for i in range(2):
            calls["months"] += 1
            await on_month([{"t": H - i * 86400}], [], end - timedelta(days=31 * (i + 1)))
        return 4

    async def hist(hass, entry_id, pump, start, end, note=None, last_calls=None):
        calls["history"] += 1
        return [{"t": H}], [], 2

    async def settings(hass, entry_id, pump):
        return {"control": "heating_curve"}

    async def pump_info(hass, entry_id, pump):
        return {"model": "P80", "boiler_type": None}

    monkeypatch.setattr(weheat_sync, "async_fetch_months", months)
    monkeypatch.setattr(weheat_sync, "async_fetch_history", hist)
    monkeypatch.setattr(weheat_sync, "async_settings", settings)
    monkeypatch.setattr(weheat_sync, "async_pump_info", pump_info)
    monkeypatch.setattr(history, "weheat_hours", lambda logs, energy: {l["t"]: {"q": 1.0, "e": 0.25, "room": 20.5} for l in logs})
    return calls


async def _no_learning(m, calls):
    async def learn():
        calls["learn"] += 1
    m.learner.async_learn = learn


async def test_import_month_by_month_then_learn(hass: HomeAssistant, entry, fake) -> None:
    m = entry.runtime_data
    await _no_learning(m, fake)
    await m.wh.async_import(days=60)
    await hass.async_block_till_done()
    assert m.weheat.import_info["done"] and m.weheat.import_info["months"] == 2 and m.weheat.import_info["calls"] == 4
    assert H in m.weheat.hours and fake["learn"] >= 1
    assert m.wh.import_progress()[:2] == (2, 2)


async def test_import_with_the_login_refused_waits_and_asks(hass: HomeAssistant, entry, monkeypatch) -> None:
    async def refused(*a, **k):
        raise WeheatLoginNeeded("401")
    monkeypatch.setattr(weheat_sync, "async_fetch_months", refused)
    m = entry.runtime_data
    await m.wh.async_import(days=30)
    assert "waiting" in m.weheat.import_info["status"] and not m.wh.importing
    assert any(e["kind"] == "login_needed" for e in m.events)


async def test_import_failing_is_reported_not_raised(hass: HomeAssistant, entry, monkeypatch) -> None:
    async def broken(*a, **k):
        raise RuntimeError("weheat changed its API")
    monkeypatch.setattr(weheat_sync, "async_fetch_months", broken)
    m = entry.runtime_data
    await m.wh.async_import(days=30)
    assert m.weheat.import_info["status"].startswith("failed") and any(e["kind"] == "error" for e in m.events)


async def test_refresh_reads_the_hours_since(hass: HomeAssistant, entry, fake) -> None:
    m = entry.runtime_data
    m.weheat = replace(m.weheat, import_info={"done": True}, hours={H - 86400: {"q": 1.0}})
    await m.wh.async_refresh()
    assert fake["history"] == 1 and H in m.weheat.hours
    assert m.weheat.settings["control"] == "heating_curve" and m.weheat.pump["model"] == "P80"


async def test_refresh_with_the_login_refused_asks_for_it(hass: HomeAssistant, entry, fake, monkeypatch) -> None:
    async def refused(*a, **k):
        raise WeheatLoginNeeded("401")
    monkeypatch.setattr(weheat_sync, "async_fetch_history", refused)
    m = entry.runtime_data
    m.weheat = replace(m.weheat, import_info={"done": True}, hours={H - 86400: {"q": 1.0}})
    await m.wh.async_refresh()
    assert any(e["kind"] == "login_needed" for e in m.events)


async def test_a_hybrid_is_noticed(hass: HomeAssistant, entry, monkeypatch) -> None:
    async def hybrid(hass, entry_id, pump):
        return {"model": "P80", "boiler_type": 1}
    monkeypatch.setattr(weheat_sync, "async_pump_info", hybrid)
    m = entry.runtime_data
    m.weheat = replace(m.weheat, boiler_hours=500)
    await m.wh.async_pump_info()
    assert m.weheat.pump["boiler_type"] == 1
