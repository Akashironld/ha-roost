"""The actual HA form, planner inputs, control minimum and daily context."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pytest
from homeassistant.util import dt as dt_util
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from custom_components.roost import schedule, planner, value
from .test_config_flow import COMFORT


async def open_comfort(hass,entry):
    flow=await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(flow["flow_id"],{"next_step_id":"comfort"})


def form(**days):
    base={k:v for k,v in deepcopy(COMFORT).items() if k!="hours_same"}
    return {**base,"comfort_days":"per_day",schedule.SECTION:dict(days)}


async def per_day(hass,flow,**days):
    """Choose 'per day' and fill in the days, on the same screen (24-11: no screen in between)."""
    return await hass.config_entries.options.async_configure(flow["flow_id"],form(**days))


async def test_weekly_form_stores_canonical_periods_and_empty_days(hass,entry):
    flow=await open_comfort(hass,entry)
    result=await per_day(hass,flow,monday="07:00-09:00,17:30-22:00",saturday="09:00-24:00")
    assert result["type"] is FlowResultType.MENU
    assert entry.options[schedule.ENABLED] is True
    assert entry.options[schedule.WEEK]["monday"]==[[420,540],[1050,1320]]
    assert entry.options[schedule.WEEK]["tuesday"]==[]
    flow=await hass.config_entries.options.async_configure(flow["flow_id"],{"next_step_id":"comfort"})
    # Reopen: shown per day again; back to the same hours every day
    assert {str(k) for k in flow["data_schema"].schema} >= {schedule.SECTION}
    r=await hass.config_entries.options.async_configure(flow["flow_id"],deepcopy(COMFORT))
    assert r["type"] is FlowResultType.MENU
    assert entry.options[schedule.ENABLED] is False and entry.options["day_from"]==7 and entry.options["day_to"]==22


async def test_invalid_schedule_never_changes_options(hass,entry):
    before=dict(entry.options)
    flow=await open_comfort(hass,entry)
    result=await per_day(hass,flow,sunday="22:00-02:00",monday="01:00-03:00")
    assert result["type"] is FlowResultType.FORM and result["errors"]=={"base":"invalid_schedule"}
    assert dict(entry.options)==before


async def test_unrelated_options_keep_the_weekly_schedule(hass,entry):
    flow=await open_comfort(hass,entry)
    await per_day(hass,flow,monday="06:30-08:30")
    expected=entry.options[schedule.WEEK]
    flow=await hass.config_entries.options.async_init(entry.entry_id)
    flow=await hass.config_entries.options.async_configure(flow["flow_id"],{"next_step_id":"house"})
    await hass.config_entries.options.async_configure(flow["flow_id"],{"thermostat":"climate.living_room","emitters":["floor"],"use_bag":False})
    assert entry.options[schedule.ENABLED] and entry.options[schedule.WEEK]==expected


async def test_runtime_quarters_follow_local_weekday_and_current_control_minimum(hass,entry,monkeypatch):
    m=entry.runtime_data
    c=m.conf
    c.update({schedule.ENABLED:True,schedule.WEEK:schedule.normalise({"monday":"07:30-09:00"}),"day_min":20.5,"night_min":18.5})
    monkeypatch.setattr(type(m),"conf",property(lambda self:c))
    old=dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(ZoneInfo("Europe/Amsterdam"))
    try:
        now=datetime(2026,10,26,6,0,tzinfo=timezone.utc)  # Monday 07:00 local
        base=int(now.timestamp())
        m.weather=replace(m.weather, forecast={base+i*3600:(5.,0.,3.5) for i in range(3)})
        hours=m._hours_ahead(now,[value.HourPrices(.3,.3,0,"grid")]*3,[.3]*3)
        assert hours[0].comfort_mask==(False,False,True,True)
        assert hours[1].comfort_mask==(True,)*4
        assert hours[2].comfort_mask==(False,)*4
        assert not m.is_day(dt_util.as_local(now))
        assert m.is_day(dt_util.as_local(now.replace(minute=30)))
        m.mode="shadow";m.held=replace(m.held,hours=hours,at=now.timestamp())   # v0.8.0: the plan for this hour
        with patch("custom_components.roost.manager.control.decide",wraps=__import__("custom_components.roost.control",fromlist=["decide"]).decide) as decide:
            await m._async_control(now.timestamp())
            assert decide.call_args.args[4]==18.5
            await m._async_control(now.replace(minute=30).timestamp())
            assert decide.call_args.args[4]==20.5
    finally:
        dt_util.set_default_time_zone(old)


async def test_legacy_card_hours_cannot_silently_override_enabled_weekly_schedule(hass,entry,monkeypatch):
    m=entry.runtime_data;c=m.conf;c[schedule.ENABLED]=True
    monkeypatch.setattr(type(m),"conf",property(lambda self:c))
    with pytest.raises(ServiceValidationError):
        await m.care.async_set_settings(day_from=8)


async def test_weekly_change_is_frozen_and_invalidates_mixed_day(hass,entry,monkeypatch):
    m=entry.runtime_data;c=m.conf
    c.update({schedule.ENABLED:True,schedule.WEEK:schedule.normalise({"monday":"07:00-09:00"})})
    monkeypatch.setattr(type(m),"conf",property(lambda self:c))
    # noon of today in the test's own time zone: an hour later is the same day (23-11-2026: at 08:xx in Amsterdam it
    # was 23:xx in the tests' US/Pacific, the next hour a new day, and the test failed for that one hour each day)
    now=dt_util.as_utc(dt_util.start_of_local_day()+__import__("datetime").timedelta(hours=12))
    # Match this fixture's actual local weekday so the captured schedule is unambiguous.
    m.log=replace(m.log,hour_log=[],day_contexts={})
    m.weather.forecast[int(now.timestamp())]=(6.,0.,3.5)
    m.held=replace(m.held,hours=[planner.HourIn(6,3.5,0,.3,.3)],at=now.timestamp())
    m.hl.log_hour(now)
    day=dt_util.as_local(now).date().isoformat()
    assert m.log.day_contexts[day]["comfort_schedule"]==schedule.context(c)
    frozen=deepcopy(m.log.day_contexts[day]["comfort_schedule"])
    # Replace, do not mutate, exactly as an HA options update does.
    c[schedule.WEEK]=schedule.normalise({"monday":"17:00-22:00"})
    later=now+__import__("datetime").timedelta(hours=1)
    m.weather.forecast[int(later.timestamp())]=(6.,0.,3.5)
    m.held=replace(m.held,at=later.timestamp())
    m.hl.log_hour(later)
    assert m.log.day_contexts[day]["settings_changed"] is True
    assert m.log.day_contexts[day]["comfort_schedule"]==frozen
