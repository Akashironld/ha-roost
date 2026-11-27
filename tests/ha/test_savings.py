"""Runtime regression checks: hour boundaries, day snapshots, validation and sensor dates."""
import time
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from homeassistant.util import dt as dt_util

from custom_components.roost import planner
from custom_components.roost.sensor import SavingYesterdaySensor


@pytest.fixture
def berlin_timezone():
    old = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(ZoneInfo("Europe/Berlin"))
    yield
    dt_util.set_default_time_zone(old)


async def test_hour_boundary_forces_plan_before_logging(entry):
    m = entry.runtime_data
    now = dt_util.utcnow().replace(minute=0, second=2, microsecond=0)
    m.held = replace(m.held, at=now.timestamp() - 120)                 # not due on the 15-minute interval, but in the previous hour
    m.log = replace(m.log, hour_log=[])
    m.held = replace(m.held, hours=[planner.HourIn(5, 3.5, 0, 0.1, 0.1), planner.HourIn(5, 3.5, 0, 0.7, 0.7)])
    assert m.plan_hour(now).p_grid == 0.7

    async def new_plan(_now, *_args):
        m.held = replace(m.held, at=_now.timestamp())
        m.held = replace(m.held, hours=[planner.HourIn(5, 3.5, 0, 0.7, 0.7)])

    with patch("custom_components.roost.manager.dt_util.utcnow", return_value=now), \
         patch.object(m, "_async_weather", AsyncMock()), \
         patch.object(m, "_async_plan", AsyncMock(side_effect=new_plan)) as plan, \
         patch.object(m, "_async_control", AsyncMock()):
        m.weather.forecast[int(now.timestamp() // 3600 * 3600)] = (5, 0, 3.5)
        await m._async_tick(None)
    plan.assert_awaited_once()
    assert m.log.hour_log[-1]["p_grid"] == 0.7


async def test_cost_uses_current_hour_before_replanning(entry):
    m = entry.runtime_data
    now = dt_util.utcnow().replace(minute=0, second=2, microsecond=0)
    m.held = replace(m.held, at=now.timestamp() - 120)
    m.held = replace(m.held, hours=[planner.HourIn(5, 3.5, 0, 0.1, 0.1), planner.HourIn(5, 3.5, 0, 0.7, 0.7)])
    m.meters = replace(m.meters, cost_day=dt_util.as_local(now).date().isoformat(), last_elec=10.0, cost_today=0.0)
    with patch.object(m.read, "num", side_effect=[None, 11.0, 0.0]):     # the indoor unit's meter (none), heating, defrost
        m._count_cost(now)
    assert abs(m.meters.cost_today - 0.7) < 1e-9


async def test_day_model_is_a_copy_and_is_not_replaced_by_later_learning(entry):
    m = entry.runtime_data
    now = dt_util.utcnow()
    day = dt_util.as_local(now).date().isoformat()
    m.log = replace(m.log, hour_log=[])
    m.held = replace(m.held, at=now.timestamp())
    m.weather.forecast[int(now.timestamp() // 3600 * 3600)] = (5, 0, 3.5)
    m.hl.log_hour(now)
    original = m.log.day_contexts[day]["house"]["H"]
    m.house.H += 1
    m.log = replace(m.log, hour_log=[])
    m.hl.log_hour(now)
    assert m.log.day_contexts[day]["house"]["H"] == original


async def test_bad_energy_replay_is_retained_but_not_published(entry):
    m = entry.runtime_data
    start = dt_util.start_of_local_day(dt_util.now() - timedelta(days=1))
    expected = round(((start + timedelta(days=1)).timestamp() - start.timestamp()) / 3600)
    day = start.date().isoformat()
    m.log = replace(m.log, hour_log=[{"ts": int(start.timestamp()) + h * 3600, "T": 20.5, "T_end": 20.5,
                   "E": 0.0, "sp": 20.5, "sp_t": 20.5, "t_out": 5.0, "p_grid": 0.3,
                   "e": 0.134 / expected, "q": 0.7 / expected} for h in range(expected)])
    m.log.day_contexts[day] = {"house": m.house.as_dict(), "pump": m.pump.as_dict(),
                           "settings": vars(m.settings()), "extra_rooms": 0, "replay_version": planner.REPLAY_VERSION}
    bd = {"saving": -0.188, "kwh": 3.08, "short": 0, "b_short": 0,
          "hours": [{"t": 20.5} for _ in m.log.hour_log]}
    with patch("custom_components.roost.hourlog.planner.replay_day", return_value=(0.9, 0.712, bd)):
        await m.hl.async_close_day(day)
    assert day not in m.log.saving_days
    assert m.log.saving_detail[day]["model_saving"] == -0.188
    assert m.log.day_stats[day]["saving"] is None
    assert m.log.day_stats[day]["quality"]["reasons"] == ["energy_mismatch"]


async def test_yesterday_does_not_fall_back_to_an_older_successful_day(entry):
    m = entry.runtime_data
    yesterday = (dt_util.now().date() - timedelta(days=1)).isoformat()
    older = (dt_util.now().date() - timedelta(days=2)).isoformat()
    m.log = replace(m.log, saving_days={older: 1.23})
    sensor = SavingYesterdaySensor(m)
    assert sensor.native_value is None and sensor.extra_state_attributes["day"] == yesterday


@pytest.mark.parametrize(("day", "length"), [("2026-10-25", 25), ("2026-03-29", 23)])
async def test_day_close_respects_local_daylight_saving_time(entry, berlin_timezone, day, length):
    m = entry.runtime_data
    start = dt_util.start_of_local_day(datetime.fromisoformat(day))
    m.log = replace(m.log, hour_log=[{"ts": int(start.timestamp()) + h * 3600, "T": 20.5, "T_end": 20.5,
                   "E": 0, "sp": 20.5, "sp_t": 20.5, "t_out": 5, "p_grid": 0.3,
                   "e": 0.3, "q": 1.2} for h in range(length)])
    m.log.day_contexts[day] = {"house": m.house.as_dict(), "pump": m.pump.as_dict(),
                           "settings": vars(m.settings()), "extra_rooms": 0, "replay_version": planner.REPLAY_VERSION}
    bd = {"saving": -0.1, "kwh": length * 0.3, "short": 0, "b_short": 0,
          "hours": [{"t": 20.5} for _ in m.log.hour_log]}
    with patch("custom_components.roost.hourlog.planner.replay_day", return_value=(1.0, 0.9, bd)):
        await m.hl.async_close_day(day)
    assert m.log.day_stats[day]["quality"]["valid"]
    assert m.log.day_stats[day]["quality"]["expected_hours"] == length
    assert m.log.saving_days[day] == -0.1


async def test_shadow_replays_roosts_plan_not_the_users_thermostat(hass, entry) -> None:
    """In shadow mode the hour's log carries what Roost would have set, never the thermostat the user set (19-11-2026:
    a thermostat at 20 all day read as Roost costing money)."""
    import time as _time
    from homeassistant.util import dt as dt_util
    from .conftest import THERMOSTAT
    m = entry.runtime_data
    assert m.mode == "shadow"
    hass.states.async_set(THERMOSTAT, "heat", {"temperature": 23.0, "current_temperature": 20.6})
    m.mem.virtual_sp = None
    m.log = replace(m.log, hour_log=[])
    now = dt_util.utcnow()
    m.weather.forecast[int(now.timestamp() // 3600 * 3600)] = (5, 0, 3.5)
    m.hl.log_hour(now)
    assert m.log.hour_log and m.log.hour_log[-1]["sp"] == m.planned_sp(_time.time()) and m.log.hour_log[-1]["sp"] != 23.0
    assert m.log.hour_log[-1]["sp_t"] == 23.0                     # what the thermostat had stays known (corrections)


async def test_month_shows_measured_parts_and_the_model_band(hass, entry) -> None:
    from homeassistant.util import dt as dt_util
    m = entry.runtime_data
    day = dt_util.now().date().isoformat()
    m.log.day_stats[day] = {"measured": {"kwh": 10.0, "paid": 3.0, "flat": 3.3, "timing": 0.3, "sun_kwh": 1.0, "bat_kwh": 2.0,
                                     "sun_value": 0.0, "bat_value": 0.1}, "shadow": True}
    m.check["heat_ratio"], m.check["elec_ratio"] = 1.02, 0.95
    await m._async_tick(None)
    at = hass.states.get("sensor.roost_saving_this_month").attributes
    assert at["measured"]["timing"] == 0.3 and at["measured"]["ct_paid"] == 30.0 and abs(at["model_band"] - 0.07) < 1e-9


async def test_planned_electricity_sensor(hass, entry) -> None:
    st = hass.states.get("sensor.roost_planned_electricity")
    assert st is not None and st.attributes["hours"] and isinstance(st.attributes["predbat"], dict)


async def test_no_price_just_after_a_start_waits_quietly(entry):
    # 22-11-2026: the price sensor came back a minute after Roost; the card said "no price" meanwhile
    m = entry.runtime_data
    now = time.time()
    m.held, m.reason = replace(m.held, plan=None, fail_since=None), planner.Reason("starting")
    m._started_at = now - 60
    m._plan_failed("no_price", now)
    assert m.reason.code == "starting"
    m._started_at = now - 400
    m._plan_failed("no_price", now)
    assert m.reason.code == "no_price"
