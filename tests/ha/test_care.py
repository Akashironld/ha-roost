"""What the user meets when something goes wrong or needs a decision: the repair buttons, notifications, the
thermostat gone, changes that fail, away and home."""
from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.roost import care, repairs

from .conftest import THERMOSTAT


def _issue(hass, entry, key):
    return ir.async_get(hass).async_get_issue("roost", f"{entry.entry_id}_{key}")


async def test_ready_for_active_repair_switches_on(hass: HomeAssistant, entry) -> None:
    m = entry.runtime_data
    flow = await repairs.async_create_fix_flow(hass, "x_ready_for_active", {"entry_id": entry.entry_id, "issue": "ready_for_active"})
    flow.hass = hass
    r = await flow.async_step_init()
    assert r["type"] == "menu" and r["menu_options"] == ["confirm", "mute"]    # issue #11: a way out
    r = await flow.async_step_confirm()
    assert r["type"] == "form" and r["step_id"] == "confirm"
    r = await flow.async_step_confirm({})
    assert r["type"] == "create_entry" and m.mode == "active"


async def test_ready_notice_can_be_muted_and_stays_away(hass: HomeAssistant, entry) -> None:
    """Issue #11: 'do not show this again' closes the notice and keeps it closed, also over a restart."""
    m = entry.runtime_data
    m.mode, m.ready = "shadow", True
    m.check = {"heating_hours": 200, "rmse_6h": 0.2, "heat_ratio": 1.0}
    m.notices.issue_ready()
    assert "ready_for_active" in m.health.issues
    flow = await repairs.async_create_fix_flow(hass, "x_ready_for_active", {"entry_id": entry.entry_id, "issue": "ready_for_active"})
    flow.hass = hass
    r = await flow.async_step_mute()
    assert r["type"] == "create_entry" and m.mode == "shadow" and m.ready_muted
    assert "ready_for_active" not in m.health.issues
    m.notices.update_ready()
    assert "ready_for_active" not in m.health.issues


PASSING = {"heating_hours": 500, "rmse_6h": 0.2, "heat_ratio": 1.0}


async def test_ready_needs_a_thermostat_roost_can_set(hass: HomeAssistant, entry) -> None:
    """Issue #11: a read-only climate helper (no target temperature) is no lever, so no 'ready to steer'."""
    m = entry.runtime_data
    m.mode, m.check = "shadow", dict(PASSING)
    st = hass.states.get(THERMOSTAT)
    hass.states.async_set(THERMOSTAT, st.state, {**st.attributes, "supported_features": 0})
    assert m.notices.thermostat_writable() is False
    m.notices.update_ready()
    assert not m.ready and "lever" in m.ready_missing and "ready_for_active" not in m.health.issues
    hass.states.async_set(THERMOSTAT, st.state, {**st.attributes, "supported_features": 1})
    assert m.notices.thermostat_writable() is True
    m.notices.update_ready()
    assert m.ready and "ready_for_active" in m.health.issues


async def test_ready_not_while_the_unit_runs_on_its_heating_curve(hass: HomeAssistant, entry) -> None:
    """Issue #11: the unit on its own heating curve ignores the thermostat; its log or its answer to steps tells."""
    from dataclasses import replace
    m = entry.runtime_data
    m.mode, m.check = "shadow", dict(PASSING)
    st = hass.states.get(THERMOSTAT)
    hass.states.async_set(THERMOSTAT, st.state, {**st.attributes, "supported_features": 1})
    m.notices.update_ready()
    assert m.ready
    fresh = dt_util.now().isoformat(timespec="seconds")
    m.card.cs = replace(m.card.cs, weheat_now={"method": 1, "at": fresh})                              # heating curve
    m.notices.update_ready()
    assert not m.ready and m.ready_missing == ["following"] and "ready_for_active" not in m.health.issues
    old = (dt_util.now() - timedelta(hours=3)).isoformat(timespec="seconds")
    m.card.cs = replace(m.card.cs, weheat_now={"method": 1, "at": old})        # an old log (kept over a restart) does not block
    m.notices.update_ready()
    assert m.ready
    m.card.cs = replace(m.card.cs, weheat_now={"method": 3, "at": fresh})                              # OpenTherm
    m.notices.update_ready()
    assert m.ready
    m.card.cs = replace(m.card.cs, weheat_now={})                                                     # unknown ...
    m.card.steps.steps = [[time.time() - i * 3600, 0.02] for i in range(12)]                          # ... but it ignores steps
    m.notices.update_ready()
    assert not m.ready and m.ready_missing == ["following"]


async def test_comfort_suggestion_repair_stores_it(hass: HomeAssistant, entry) -> None:
    flow = await repairs.async_create_fix_flow(hass, "x_comfort", {"entry_id": entry.entry_id, "issue": "comfort",
                                                                   "key": "comfort", "value": 21.0})
    assert isinstance(flow, repairs.ComfortSuggestionFlow)
    flow.hass = hass
    r = await flow.async_step_confirm({})
    await hass.async_block_till_done()
    assert r["type"] == "create_entry" and entry.runtime_data.conf["comfort"] == 21.0


async def test_a_repair_for_a_removed_entry_closes(hass: HomeAssistant, entry) -> None:
    flow = await repairs.async_create_fix_flow(hass, "x", {"entry_id": "gone"})
    flow.hass = hass
    assert (await flow.async_step_confirm({}))["type"] == "create_entry"


async def test_notifications_only_when_chosen_and_not_too_often(hass: HomeAssistant, entry) -> None:
    m = entry.runtime_data
    sent = async_mock_service(hass, "notify", "phone")
    m.care.notify_user("set_failed", n=3, error="x")              # no target chosen: nothing
    await hass.async_block_till_done()
    assert not sent
    hass.config_entries.async_update_entry(entry, options={**entry.options, "notify_target": "notify.phone"})
    await hass.async_block_till_done()
    m = entry.runtime_data
    m.care.notify_user("set_failed", n=3, error="x")
    m.care.notify_user("set_failed", n=4, error="y")              # the same within NOTIFY_AGAIN_H: once
    await hass.async_block_till_done()
    mine = [c for c in sent if "thermostat" in c.data["message"]]    # (the login notice may come too)
    assert len(mine) == 1 and "3" in mine[0].data["message"]
    m.care.notify_user("set_failed", force=True, n=5, error="z")
    await hass.async_block_till_done()
    assert len([c for c in sent if "thermostat" in c.data["message"]]) == 2


async def test_a_failing_notification_does_not_stop_roost(hass: HomeAssistant, entry) -> None:
    m = entry.runtime_data
    await m.care.async_send("notify.nothing_here", "t", "m")      # no such service: logged, an event, no exception
    assert any(e["kind"] == "notify_failed" for e in m.events)


async def test_thermostat_gone_is_a_notice_in_active_mode_and_back_plans_again(hass: HomeAssistant, entry) -> None:
    m = entry.runtime_data
    await m.async_set_mode("active")
    hass.states.async_set(THERMOSTAT, "unavailable")
    t = time.time()
    m.care.watch_thermostat(t)
    assert _issue(hass, entry, "thermostat_unavailable") is None
    m.care.watch_thermostat(t + care.THERMOSTAT_GONE_MIN * 60 + 1)
    assert _issue(hass, entry, "thermostat_unavailable") is not None
    hass.states.async_set(THERMOSTAT, "heat", {"temperature": 20.5, "current_temperature": 20.6})
    m.care.watch_thermostat(t + care.THERMOSTAT_GONE_MIN * 60 + 60)
    await hass.async_block_till_done()
    assert _issue(hass, entry, "thermostat_unavailable") is None
    assert any(e["kind"] == "thermostat_back" for e in m.events)


async def test_failed_changes_become_a_notice_and_one_success_clears_it(hass: HomeAssistant, entry) -> None:
    m = entry.runtime_data
    for _ in range(care.SET_FAILS - 1):
        m.care.set_result(False, "boom")
    assert _issue(hass, entry, "set_failed") is None
    m.care.set_result(False, "boom")
    assert _issue(hass, entry, "set_failed") is not None
    m.care.set_result(True)
    assert _issue(hass, entry, "set_failed") is None


async def test_back_to_comfort_when_steering_stops(hass: HomeAssistant, entry, climate_calls) -> None:
    m = entry.runtime_data
    hass.states.async_set(THERMOSTAT, "heat", {"temperature": 18.0, "current_temperature": 20.6})
    await m.care.async_back_to_comfort("test")
    assert climate_calls[-1].data["temperature"] == float(m.conf["comfort"])
    n = len(climate_calls)
    hass.states.async_set(THERMOSTAT, "heat", {"temperature": float(m.conf["comfort"]), "current_temperature": 20.6})
    await m.care.async_back_to_comfort("test")                    # already there: nothing
    assert len(climate_calls) == n


async def test_away_and_home(hass: HomeAssistant, entry) -> None:
    m = entry.runtime_data
    await m.care.async_away(time.time() + 86400, 15.0)
    assert m.is_away() and m.settings().away_min == 15.0
    await m.care.async_home()
    assert not m.is_away() and any(e["kind"] == "home" for e in m.events)


async def test_the_tick_changes_ready_only_once_it_held(hass: HomeAssistant, entry, monkeypatch) -> None:
    """A change seen by the tick counts after READY_HOLD_S: no notice that opens and closes as a window slides."""
    from custom_components.roost import health
    m = entry.runtime_data
    m.mode, m.check, m.ready = "shadow", dict(PASSING), False
    now = [1_800_000_000.0]
    monkeypatch.setattr(health.time, "time", lambda: now[0])
    m.notices.update_ready(track=False)
    assert not m.ready
    now[0] += health.READY_HOLD_S - 60
    m.notices.update_ready(track=False)
    assert not m.ready
    now[0] += 120
    m.notices.update_ready(track=False)
    assert m.ready and "ready_for_active" in m.health.issues


async def test_opentherm_readiness_ignores_the_thermostat_and_the_curve_log(hass: HomeAssistant, entry, monkeypatch) -> None:
    """OpenTherm steering writes the water temperature itself: a read-only thermostat or a heating-curve log changes
    nothing there (the author's own setup)."""
    from dataclasses import replace
    m = entry.runtime_data
    monkeypatch.setattr(type(m), "ot", property(lambda self: True))
    st = hass.states.get(THERMOSTAT)
    hass.states.async_set(THERMOSTAT, st.state, {**st.attributes, "supported_features": 0})
    m.card.cs = replace(m.card.cs, weheat_now={"method": 1, "at": dt_util.now().isoformat(timespec="seconds")})
    m.card.steps.steps = [[time.time() - i * 3600, 0.02] for i in range(12)]
    assert m.notices.thermostat_writable() is None and m.notices.lever() is True
    assert m.notices.following_now() == m.notices.following


async def test_muted_survives_a_save_and_switching_to_active_undoes_it(hass: HomeAssistant, entry) -> None:
    m = entry.runtime_data
    saved = {}
    m._store.async_save = AsyncMock(side_effect=lambda d: saved.update(d))
    await m.notices.async_mute_ready()
    assert saved["ready_muted"] is True
    await m.async_set_mode("active")
    assert m.ready_muted is False


async def test_comfort_suggestion_starts_at_its_confirmation(hass: HomeAssistant, entry) -> None:
    flow = await repairs.async_create_fix_flow(hass, "x_comfort", {"entry_id": entry.entry_id, "issue": "comfort",
                                                                   "key": "comfort", "value": 21.0})
    flow.hass = hass
    r = await flow.async_step_init()
    assert r["type"] == "form" and r["step_id"] == "confirm"
