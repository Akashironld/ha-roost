"""v0.8.1: the remaining points of the 0.7.8 review — restarts (R18, R19), daylight saving time (R06, R15), price and
solar coverage (R05, R09, R14), weather units (R12) and a change by hand right after Roost's own (R20)."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.roost import savings


@pytest.fixture(autouse=True)
def mutable_test_configuration(entry, monkeypatch):
    m = entry.runtime_data
    conf = m.conf
    monkeypatch.setattr(type(m), "conf", property(lambda _self: conf))


async def test_a_restart_within_the_hour_goes_on_counting(hass, entry):
    """R18: the hour in progress is saved; back in the same hour, Roost counts on from it and from the meter reading."""
    m = entry.runtime_data
    t = dt_util.utcnow().timestamp()
    hour = int(t // 3600 * 3600)
    m.acc = replace(m.acc, hour=hour, elec=0.6, cost=0.18, heat=2.0, dhw=1200.0, obs=1500.0)
    m.meters = replace(m.meters, last_elec=1801.4)
    saved = m.hl.stored_acc()
    m.acc = replace(m.acc, hour=None, elec=0.0)
    m.meters = replace(m.meters, last_elec=None)
    assert m.hl.restore(saved, t + 60)[0] == 1801.4          # what the manager goes on counting from
    assert m.acc.hour == hour and m.acc.elec == 0.6 and m.acc.cost == 0.18 and m.acc.obs == 1500.0


async def test_a_restart_over_the_hour_closes_it_as_partial(hass, entry):
    """R18: the hour that was going on gets what was seen of it, marked partial, and the day is not complete."""
    m = entry.runtime_data
    t = dt_util.utcnow().timestamp()
    hour = int(t // 3600 * 3600) - 3600
    m.log = replace(m.log, hour_log=[{"ts": hour, "T": 20.5}])
    m.acc = replace(m.acc, hour=hour, elec=0.6, cost=0.18, heat=2.0, dhw=0.0, obs=1500.0)
    m.meters = replace(m.meters, last_elec=1801.4)
    saved = m.hl.stored_acc()
    m.meters = replace(m.meters, last_elec=None)
    assert m.hl.restore(saved, t) is None                     # a later hour: the meter starts afresh
    e = m.log.hour_log[0]
    assert e["e"] == 0.6 and e["cost"] == 0.18 and e["partial"] and e["obs"] == 1500
    assert m.acc.hour is None and m.meters.last_elec is None
    q = savings.assess_day([{**e, "ts": hour}], {"hours": [], "kwh": 0.6}, 1, hour, True)
    assert "partial_hours" in q["reasons"]


async def test_stored_heat_is_aged_over_the_downtime(hass, entry):
    """R19: 4 kWh in the floor after 3 hours down is less, after a minute down nearly the same."""
    m = entry.runtime_data
    t = dt_util.utcnow().timestamp()
    m.house.lag = 1.0
    m.meters = replace(m.meters, storage_e=4.0)
    m._age_storage(t - 60, t)
    assert 3.9 < m.meters.storage_e <= 4.0
    m.meters = replace(m.meters, storage_e=4.0)
    m._age_storage(t - 3 * 3600, t)
    assert m.meters.storage_e == pytest.approx(4.0 * 0.5 ** 3)
    m.meters = replace(m.meters, storage_e=4.0)
    m._age_storage(None, t)
    assert m.meters.storage_e == 4.0


def test_day_lists_follow_the_real_day_length():
    """R06: a 25-hour day of 25 prices is 25 hours of an hour each; tomorrow starts at the real local midnight."""
    from custom_components.roost import series
    mids = [1_792_965_600.0, 1_793_055_600.0, 1_793_142_000.0]          # 25 Oct (25 h), 26 Oct, 27 Oct (Amsterdam)
    s = series.slots_from_day_list(list(range(25)), mids[0], mids[1])
    assert s[0][1] - s[0][0] == 3600 and s[-1][1] == mids[1]
    slots = series.find_slots({"today": list(range(25)), "tomorrow": list(range(24))}, mids[0], mids)
    assert min(x[0] for x in slots if x[0] >= mids[1]) == mids[1] and len(slots) == 49


def test_a_future_hour_needs_all_of_it_and_the_first_solar_hour_is_a_rate():
    """R05: only its first quarter published is not a price for the hour. R09: 2 kW with 15 minutes left is 2 kW."""
    from custom_components.roost import series
    t0 = 1_800_000_000 - 1_800_000_000 % 3600
    slots = [(t0, t0 + 3600, 0.30), (t0 + 3600, t0 + 4500, 0.10)]
    assert series.hourly(slots, t0 + 600, 2, fill_last=False) == [0.30, 0.10]
    assert series.hourly(slots, t0 + 600, 2, fill_last=False, full=True) == [0.30, None]
    pv = [(t0, t0 + 7200, 2.0)]
    assert series.energy_per_hour(pv, t0 + 2700, 2) == [0.5, 2.0]
    assert series.energy_per_hour(pv, t0 + 2700, 2, rate_first=True) == [2.0, 2.0]


async def test_the_load_profile_follows_local_hours_over_dst(hass, entry):
    """R15: on 25 October the hour 02:00 comes twice; the profile follows the clock, not 'now + i'."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    m = entry.runtime_data
    old = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(ZoneInfo("Europe/Amsterdam"))
    try:
        m.load_profile = [float(h) for h in range(24)]
        now = datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc)       # 00:30 local, summer time
        from custom_components.roost import prices
        with patch.object(prices, "sensor_series", side_effect=lambda p, *a: (p, [0.3] * 6)):
            inp, _ = m._energy(now, 6)
        assert inp.load_kwh == [0.0, 1.0, 2.0, 2.0, 3.0, 4.0]
    finally:
        dt_util.set_default_time_zone(old)


async def test_two_solar_forecasts_for_the_same_hours_count_once(hass, entry):
    """R14."""
    m = entry.runtime_data
    t0 = int(dt_util.utcnow().timestamp() // 3600 * 3600) + 3600
    fc = [{"period_start": dt_util.utc_from_timestamp(t0 + h * 3600).isoformat(), "pv_estimate": 2.0} for h in range(3)]
    hass.states.async_set("sensor.pv_today", "5", {"detailedForecast": fc})
    hass.states.async_set("sensor.pv_tomorrow", "5", {"detailedForecast": fc})
    m.conf.update(pv_forecast="sensor.pv_today", pv_forecast_tomorrow="sensor.pv_tomorrow")
    pv = m._pv_forecast(t0, 3)
    assert pv == pytest.approx([2.0, 2.0, 2.0])


async def test_weather_entity_units_are_converted(hass, entry):
    """R12: 69.8 °F and 9 m/s are 21 °C and 9 m/s, not 69.8 °C and 2.5 m/s."""
    from homeassistant.core import ServiceRegistry
    m = entry.runtime_data
    m.conf.update(weather_source="entity", weather_entity="weather.home")
    hass.states.async_set("weather.home", "sunny", {"temperature_unit": "°F", "wind_speed_unit": "m/s"})
    ts = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    resp = {"weather.home": {"forecast": [{"datetime": ts.isoformat(), "temperature": 69.8, "wind_speed": 9.0, "cloud_coverage": 0}]}}
    from custom_components.roost.core import weather as cweather
    m.weather = cweather.Weather()

    async def call(self, *a, **k):
        return resp
    with patch.object(ServiceRegistry, "async_call", call):
        await m._async_weather()
    t, _rad, wind = m.weather.forecast[int(ts.timestamp())]
    assert t == pytest.approx(21.0) and wind == pytest.approx(9.0)


async def test_a_change_by_a_user_right_after_roost_still_pauses(hass, entry):
    """R20: within 60 s of Roost's own change, a change that carries a user is that user's."""
    import time
    from homeassistant.core import Context
    from .conftest import THERMOSTAT
    m = entry.runtime_data
    hass.states.async_set(THERMOSTAT, "heat", {"temperature": 21.0, "current_temperature": 20.6})
    await hass.async_block_till_done()
    m.mode, m.mem.pause_until, m.mem.last_write = "active", None, time.time() - 30
    hass.states.async_set(THERMOSTAT, "heat", {"temperature": 19.0, "current_temperature": 20.6}, context=Context())
    await hass.async_block_till_done()
    assert not m.mem.pause_until                                     # no user: taken for our own change coming back
    hass.states.async_set(THERMOSTAT, "heat", {"temperature": 18.5, "current_temperature": 20.6}, context=Context(user_id="abc"))
    await hass.async_block_till_done()
    assert m.mem.pause_until and m.mem.pause_until > time.time()


async def test_a_partial_hour_seen_half_or_more_adds_to_the_thermostat_history(hass, entry):
    """25-11-2026: an hour cut off by a restart was closed as partial, but the stored thermostat history was put back
    over it, so the hour's mean setpoint and reading were lost. Seen for half an hour or more, it counts now."""
    m = entry.runtime_data
    t = dt_util.utcnow().timestamp()
    hour = int(t // 3600 * 3600) - 3600
    m.log = replace(m.log, hour_log=[{"ts": hour, "T": 20.5}], sp_hist={})
    m.acc = replace(m.acc, hour=hour, obs=2400.0, sp=(20.0 * 2400, 2400.0, 19.5 * 2400, 2400.0))
    data = {**m.log.stored(t), "acc": m.hl.stored_acc()}
    m.acc = replace(m.acc, hour=None)
    with patch.object(m._store, "async_load", return_value=data), patch.object(m._hist_store, "async_load", return_value={}):
        await m.async_start()
    assert m.log.sp_hist.get(hour) == [20.0, 19.5]
    assert m.log.hour_log[-1]["partial"] and m.log.hour_log[-1]["sp_mean"] == 20.0


async def test_a_failing_what_if_never_stops_closing_the_day(hass, entry):
    """25-11-2026: the what-if is only the card's advice; an error in it must not keep the day from being saved."""
    m = entry.runtime_data
    start = dt_util.start_of_local_day() - timedelta(days=1)
    day = dt_util.as_local(start).date().isoformat()
    entries = [{"ts": int(start.timestamp()) + i * 3600, "T": 20.5, "E": 1.0, "w": 0.0, "sp": 20.0, "t_out": 5.0,
                "p_grid": 0.3, "day": True, "e": 0.3, "q": 1.2} for i in range(24)]
    m.log = replace(m.log, hour_log=entries)
    with patch("custom_components.roost.planner.what_if_day", side_effect=RuntimeError("boom")):
        await m.hl.async_close_day(day)
    assert day in m.log.day_stats and "what_if" not in m.log.day_stats[day]
