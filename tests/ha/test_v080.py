"""v0.8.0 in Home Assistant: the plan held, fallbacks, airing with a window sensor, the unit's minimum run, a house that
stays cold, and the fixes from the 0.7.8 review (R01, R04, R07, R08, R10, R16, R17, R21, R22)."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.roost import diagnostics, rooms, schedule
from custom_components.roost.sensor import SavingMonthSensor

from .conftest import THERMOSTAT, thermostat


@pytest.fixture(autouse=True)
def mutable_test_configuration(entry, monkeypatch):
    m = entry.runtime_data
    conf = m.conf
    monkeypatch.setattr(type(m), "conf", property(lambda _self: conf))


def issue(hass, entry, key):
    return ir.async_get(hass).async_get_issue("roost", f"{entry.entry_id}_{key}")


async def test_the_plan_is_held_until_a_reason(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow().replace(minute=5, second=0, microsecond=0)    # +20 min stays in the same hour
    await m._async_plan(now, "first")
    held = list(m.held.commit.sp)
    m.meters = replace(m.meters, storage_e=m.meters.storage_e + 1.5)                                  # a small change: the plan made afresh might differ
    await m._async_plan(now + timedelta(minutes=20))
    assert [x.sp for x in m.held.plan.hours] == held[:len(m.held.plan.hours)] and m.held.why == "first"
    await m._async_plan(now + timedelta(minutes=40), "settings")
    assert m.held.why == "settings" and m.held.commit.at == pytest.approx((now + timedelta(minutes=40)).timestamp())


async def test_why_plan_sees_new_prices(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow()
    await m._async_plan(now, "first")
    e = m._energy(now, 36)
    assert m._why_plan(now, e, None) is None
    short = (type(e[0])(import_price=e[0].import_price[:10]), e[1])
    m.held.commit.tariff = m.held.commit.tariff[:10]
    assert m._why_plan(now, e, None) == "prices"
    assert m._why_plan(now, short, None) is None


async def test_a_plan_held_from_before_a_restart_is_made_afresh_once(hass, entry):
    # 21-11-2026: the first round after a restart had no prices yet; the plan held from before stayed for hours
    m = entry.runtime_data
    now = dt_util.utcnow()
    await m._async_plan(now, "first")
    e = m._energy(now, 36)
    m._replan_on_start = True                   # as async_start sets it when a plan held was restored
    assert m._why_plan(now, None, None) == "restart"        # no prices yet: nothing made, it stays wanted
    assert m._why_plan(now, e, None) == "restart"
    await m._async_plan(now, "restart", e)
    assert m.held.why == "restart" and m._why_plan(now, e, None) is None


async def test_no_room_falls_back_to_the_comfort_schedule(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow()
    with patch.object(type(m), "room", return_value=None):
        await m._async_plan(now)
        assert m.held.fallback is None and m.reason.code == "no_room"
        later = now + timedelta(minutes=61)
        await m._async_plan(later)
        assert m.held.fallback == "schedule" and m.held.plan is None
        assert m.planned_sp(later.timestamp()) == m.fallback_sp(later.timestamp())
        await m._async_plan(now + timedelta(hours=3, minutes=5))
        assert issue(hass, entry, "fallback") is not None
    await m._async_plan(now + timedelta(hours=3, minutes=10))
    assert m.held.fallback is None and issue(hass, entry, "fallback") is None


async def test_a_failed_write_is_tried_again_soon(hass, entry):
    """R01: the change interval only starts with a change that was made."""
    m = entry.runtime_data
    thermostat(hass, target=19.0, room=20.0)
    await hass.async_block_till_done()
    m.mode = "active"
    t = dt_util.utcnow().timestamp()

    async def boom(call):
        raise RuntimeError("timeout")
    hass.services.async_register("climate", "set_temperature", boom)
    with patch.object(type(m), "planned_sp", return_value=21.0):
        await m._async_control(t)
        assert m.decision.why.code == "set_failed" and m.decision.effective == 19.0
        await m._async_control(t + 60)
        assert m.decision.why.code == "wait" and m.decision.why.args["min"] <= 4
        await m._async_control(t + 5 * 60 + 1)
        assert m.decision.why.code == "set_failed" and m.decision.why.args["min"] == 10     # backs off


async def test_the_unit_runs_a_while_before_roost_lowers(hass, entry, climate_calls):
    m = entry.runtime_data
    thermostat(hass, target=21.5, room=20.9)
    await hass.async_block_till_done()
    m.mode = "active"
    t = dt_util.utcnow().timestamp()
    m._heating_since = t - 10 * 60
    with patch.object(type(m), "planned_sp", return_value=20.0):
        await m._async_control(t)
        assert m.decision.why.code == "min_run" and not climate_calls
        m._heating_since = t - 45 * 60
        m.mem.last_write = None
        await m._async_control(t)
        assert climate_calls and climate_calls[-1].data["temperature"] == 20.0


async def test_a_window_sensor_lowers_the_thermostat_and_closing_restores_the_plan(hass, entry, climate_calls):
    """R13: with a contact the unit stops heating the outdoors; a fall of the room alone only pauses."""
    m = entry.runtime_data
    m.conf["window_sensors"] = ["binary_sensor.window"]
    m.conf["lowest_setpoint"] = 19.0
    thermostat(hass, target=22.0, room=21.0)
    await hass.async_block_till_done()
    m.mode = "active"
    hass.states.async_set("binary_sensor.window", "on")
    t = dt_util.utcnow().timestamp()
    m.notices.watch_window(t)
    await m._async_control(t)
    assert climate_calls[-1].data["temperature"] == 19.0 and m.decision.why.code == "airing"
    n = len(climate_calls)
    m.mode = "shadow"
    thermostat(hass, target=19.0, room=20.5)
    await hass.async_block_till_done()
    m.mode = "active"
    await m._async_control(t + 120)
    assert len(climate_calls) == n                       # once
    hass.states.async_set("binary_sensor.window", "off")
    with patch.object(type(m), "_async_tick") as tick:
        for k in range(1, 4):
            m.notices.watch_window(t + k * 3600)
        assert tick.call_args.kwargs.get("force_plan") == "window"
    assert m._airing_from is None and m.mem.last_write is None


async def test_a_house_below_its_minimum_gets_a_notice(hass, entry):
    m = entry.runtime_data
    m.mode = "active"
    t = dt_util.utcnow().timestamp()
    with patch.object(type(m), "room", return_value=17.5):
        m.notices.check(t)
        assert issue(hass, entry, "house_cold") is None
        m.notices.check(t + 61 * 60)
        assert issue(hass, entry, "house_cold") is not None
    m.notices.check(t + 62 * 60)
    assert issue(hass, entry, "house_cold") is None


async def test_a_missing_meter_makes_no_phantom_use(hass, entry):
    """R16: the defrost meter unavailable and back unchanged: nothing counted."""
    m = entry.runtime_data
    now = dt_util.utcnow()
    defrost = m.ent["elec_defrost"]
    m._count_cost(now)
    before = m.meters.kwh_today
    hass.states.async_set(defrost, "unavailable")
    m._count_cost(now + timedelta(minutes=2))
    hass.states.async_set(defrost, "4.0", {"device_class": "energy", "unit_of_measurement": "kWh"})
    m._count_cost(now + timedelta(minutes=4))
    assert m.meters.kwh_today == before


async def test_energy_without_a_plan_is_priced_or_marked_unpriced(hass, entry):
    """R17: not free."""
    m = entry.runtime_data
    now = dt_util.utcnow()
    elec = m.ent["elec"]
    m._count_cost(now)
    m.held = replace(m.held, plan=None, hours=[], at=None)
    m.prices = replace(m.prices, tariff_now=0.30)
    hass.states.async_set(elec, "1801.0", {"device_class": "energy", "unit_of_measurement": "kWh"})
    m._count_cost(now + timedelta(minutes=2))
    assert m.meters.cost_today == pytest.approx(0.30)
    m.prices = replace(m.prices, tariff_now=None)
    hass.states.async_set(elec, "1802.0", {"device_class": "energy", "unit_of_measurement": "kWh"})
    m._count_cost(now + timedelta(minutes=4))
    assert m.meters.cost_today == pytest.approx(0.30) and m.meters.unpriced_kwh == pytest.approx(1.0)


async def test_a_change_undone_within_the_hour_still_marks_the_day(hass, entry):
    """R04."""
    m = entry.runtime_data
    now = dt_util.utcnow()
    day = dt_util.as_local(now).date().isoformat()
    m.log.day_contexts[day] = {"settings": vars(m.settings()), "room_settings": [], "comfort_schedule": schedule.context(m.conf)}
    m.log.hour_log.append({"ts": int(now.timestamp() // 3600 * 3600)})      # this hour is logged already
    m.hl.log_hour(now)
    assert not m.log.day_contexts[day].get("settings_changed")
    old = m.conf["comfort"]
    m.conf["comfort"] = old + 1
    m.hl.log_hour(now + timedelta(seconds=30))
    m.conf["comfort"] = old
    m.hl.log_hour(now + timedelta(seconds=60))
    assert m.log.day_contexts[day]["settings_changed"]


async def test_failed_learning_keeps_the_models_it_had(hass, entry):
    """R21."""
    m = entry.runtime_data
    house, pump, chk = m.house, m.pump, m.check
    with patch("custom_components.roost.check.self_check", side_effect=RuntimeError("boom")), \
         patch("custom_components.roost.learning.async_rows", return_value=([], {})), \
         patch("custom_components.roost.model.stale", return_value=False), \
         patch("custom_components.roost.model.learn") as learn, \
         patch("custom_components.roost.heatpump.learn", side_effect=lambda rows, p: (p, "")), \
         patch("custom_components.roost.response.learn", side_effect=lambda rows, h, p: (p, "")), \
         patch.object(type(m), "_async_tick"):
        learn.return_value.model = type(house)(C=40.0)
        await m.learner.async_learn()
    assert m.house is house and m.pump is pump and m.check == chk


async def test_month_coverage_counts_absent_days(hass, entry):
    """R22."""
    m = entry.runtime_data
    today = dt_util.now().date()
    if today.day < 3:
        pytest.skip("needs two completed days in this month")
    first = today.replace(day=1).isoformat()
    m.log = replace(m.log, day_stats={first: {"saving": 0.1}})
    m.log = replace(m.log, saving_days={first: 0.1})
    a = SavingMonthSensor(m).extra_state_attributes
    assert a["partial"] and len(a["absent_days"]) == today.day - 2 and a["days_expected"] == today.day - 1


async def test_inherited_room_follows_the_weekly_schedule(hass, entry):
    """R07: a room of kind 'other' without its own hours keeps the house's comfort hours, also weekly ones."""
    m = entry.runtime_data
    m.rooms = [rooms.Room(id="r1", name="Upstairs", sensor="sensor.upstairs", kind="other")]
    hass.states.async_set("sensor.upstairs", "19.0", {"unit_of_measurement": "°C"})
    m.conf.update({schedule.ENABLED: True, schedule.WEEK: schedule.normalise({})})
    now = dt_util.utcnow()
    hours = m._hours_ahead(now, [type("P", (), {"p_grid": .3, "p_own": .3, "own_kw": 0.0})()] * 3, [.3] * 3)
    plan_in, meta = m._rooms_ahead(hours)
    assert plan_in[0]["active"] == [False, False, False]


async def test_an_unread_room_stays_in_the_status(hass, entry):
    """R08."""
    m = entry.runtime_data
    m.rooms = [rooms.Room(id="r1", name="Upstairs", sensor="sensor.upstairs", kind="bedroom")]
    hass.states.async_set("sensor.upstairs", "unavailable")
    plan_in, meta = m._rooms_ahead([])
    assert plan_in == [] and meta[0]["available"] is False and meta[0]["temperature"] is None


def test_diagnostics_scrub_the_location_from_text():
    """R10."""
    text = {"sources": {"weather": "Open-Meteo unavailable: 500, url=https://x/?latitude=52.0912&longitude=5.1214&hourly=t"},
            "log": ["at 52.0912, 5.1214 it failed"]}
    out = diagnostics._scrub(text, ("52.0912", "5.1214"))
    assert "52.0912" not in str(out) and "5.1214" not in str(out) and "hourly=t" in str(out)


async def test_the_card_saves_weekly_periods_without_a_reload(hass, entry):
    """The weekly periods from the card: checked like Configure > Comfort, no reload of Roost."""
    from homeassistant.exceptions import ServiceValidationError
    m = entry.runtime_data
    week = {"monday": [[420, 540], [1050, 1320]], "sunday": "08:30-23:00"}
    with patch.object(type(m), "_async_tick"):
        await hass.services.async_call("roost", "set_settings", {"weekly_comfort": True, "comfort_schedule": week}, blocking=True)
    await hass.async_block_till_done()
    assert entry.runtime_data is m                                   # not reloaded
    assert entry.options[schedule.ENABLED] is True
    assert entry.options[schedule.WEEK]["monday"] == [[420, 540], [1050, 1320]] and entry.options[schedule.WEEK]["tuesday"] == []
    m.conf.update(entry.options)                                     # the test's fixed conf: as Home Assistant merges it
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("roost", "set_settings", {"comfort_schedule": {"monday": [[420, 600], [540, 700]]}}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("roost", "set_settings", {"day_from": 6}, blocking=True)
    with patch.object(type(m), "_async_tick"):
        await hass.services.async_call("roost", "set_settings", {"weekly_comfort": False}, blocking=True)
    assert entry.options[schedule.ENABLED] is False and entry.options[schedule.WEEK]["monday"] == [[420, 540], [1050, 1320]]


async def test_weekly_on_without_periods_starts_from_the_comfort_hours(hass, entry):
    m = entry.runtime_data
    m.conf.pop(schedule.WEEK, None)
    with patch.object(type(m), "_async_tick"):
        await m.care.async_set_settings(weekly_comfort=True)
    assert entry.options[schedule.WEEK]["friday"] == [[int(m.conf["day_from"]) * 60, int(m.conf["day_to"]) * 60]]


async def test_runs_of_the_unit_are_counted_per_day(hass, entry):
    m = entry.runtime_data
    # midday local time: with "now" the runs straddled midnight in the test time zone right after it (22-11-2026)
    t = dt_util.start_of_local_day().timestamp() + 12 * 3600
    from custom_components.roost.core import meters as cmeters
    m.meters = replace(m.meters, runs=())
    for at, on in ((t - 3600, True), (t - 1800, False), (t - 600, True)):
        m.meters = cmeters.track_runs(m.meters, at, on)
    s = m.run_stats(t)
    assert s["heating"] and s["today"]["starts"] == 2
    assert s["today"]["minutes"] == round((30 + 10) / 2)


async def test_an_install_from_v077_starts_and_drops_unchecked_savings(hass, weheat, climate_calls, hass_storage):
    """Upgrading from v0.7.7: its stored state has none of the new fields (frozen day contexts, the plan held, the
    unit's runs, saving quality). Roost starts, steers, and no longer counts the old unchecked days in the month."""
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.roost.const import STORAGE_VERSION
    from .conftest import PRICE
    assert await async_setup_component(hass, "websocket_api", {})
    day = (dt_util.now() - timedelta(days=2)).date().isoformat()
    hass_storage["roost.old077"] = {"version": STORAGE_VERSION, "key": "roost.old077", "data": {
        "mode": "active", "saving_days": {day: 0.42}, "day_stats": {day: {"saving": 0.42, "kwh": 3.1}},
        "saving_detail": {day: {"saving": 0.42}}, "replayed_with": 2, "hour_log": [], "plan_log": [],
        "control": {"last_write": None, "last_sp": 20.5}, "storage_e": 1.2, "today": {"day": day, "cost": 0.5, "kwh": 2.0}}}
    entry = MockConfigEntry(domain="roost", entry_id="old077", title="Roost", unique_id=weheat,
                            data={"heat_pump": weheat, "thermostat": THERMOSTAT, "import_price": PRICE,
                                  "import_weheat_history": False, "weather_source": "open_meteo"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    m = entry.runtime_data
    assert m.mode == "active" and m.held.commit is not None and m.held.plan is not None and isinstance(m.meters.runs, tuple)   # it planned at once
    assert day not in m.log.saving_days and m.hl.saving_month() is None
    assert m.log.day_stats[day]["quality"]["reasons"] == ["missing_context"]
