"""Unpublished tariffs must not participate in either planning or battery valuation."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.roost import value
from custom_components.roost.sensor import SavingNext24hSensor, SetpointSensor

from .conftest import PRICE


@pytest.fixture(autouse=True)
def mutable_test_configuration(entry, monkeypatch):
    """Change this test's configuration without reloading the integration or writing a config entry."""
    m = entry.runtime_data
    conf = m.conf
    monkeypatch.setattr(type(m), "conf", property(lambda _self: conf))


def publish(hass, now, count, price=0.30):
    base = now.replace(minute=0, second=0, microsecond=0)
    rates = [{"start": (base + timedelta(hours=i)).isoformat(),
              "end": (base + timedelta(hours=i + 1)).isoformat(), "value": price}
             for i in range(count)]
    hass.states.async_set(PRICE, str(price), {"unit_of_measurement": "EUR/kWh", "rates": rates})


@pytest.mark.parametrize("mode", ["sensor", "epex"])
async def test_old_prices_never_fill_the_unpublished_tail(hass, entry, mode):
    m = entry.runtime_data
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    base = int(now.timestamp())
    m.conf["price_mode"] = mode
    m._epex = [(base + i*3600, base + (i+1)*3600, .1) for i in range(8)]
    m.conf.update(import_mult=1., import_add=0.)
    publish(hass, now, 8)
    key = "epex_import" if mode == "epex" else PRICE
    m.price_seen[key] = {base + i*3600 - 86400: .95 for i in range(36)}
    a = m._energy(now, 36)
    assert a is not None and len(a[0].import_price) == 8
    m.price_seen[key] = {base + i*3600 - 86400: -.50 for i in range(36)}
    b = m._energy(now, 36)
    assert a == b


async def test_horizon_is_clipped_before_battery_valuation(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    publish(hass, now, 10)
    m.conf.update(battery_soc="sensor.price_test_soc", battery_kwh=14., battery_kw=5.)
    hass.states.async_set("sensor.price_test_soc", "80")
    with patch("custom_components.roost.prices.value.compute", wraps=value.compute) as compute:
        inp, ev = m._energy(now, 36)
    assert len(compute.call_args.args[0].import_price) == 10
    assert len(inp.import_price) == len(ev.value) == 10


async def test_unpublished_export_prices_also_bound_the_horizon(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    publish(hass, now, 10)
    m.conf["export_price"] = "sensor.price_test_export"
    rates = [{"start": now.isoformat(), "end": (now + timedelta(hours=3)).isoformat(), "value": .05}]
    hass.states.async_set("sensor.price_test_export", ".05", {"unit_of_measurement": "EUR/kWh", "rates": rates})
    inp, ev = m._energy(now, 36)
    assert len(inp.import_price) == len(inp.export_price) == len(ev.value) == 3


async def test_missing_configured_export_price_is_not_replaced_by_import(hass, entry):
    m = entry.runtime_data
    m.conf["export_price"] = "sensor.missing_export"
    assert m._energy(dt_util.utcnow(), 36) is None


async def test_a_gap_stops_planning_even_if_later_prices_exist(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    publish(hass, now, 12)
    attrs = dict(hass.states.get(PRICE).attributes)
    attrs["rates"] = [r for i, r in enumerate(attrs["rates"]) if i != 5]
    hass.states.async_set(PRICE, ".30", attrs)
    inp, _ = m._energy(now, 36)
    assert len(inp.import_price) == 5


async def test_plan_extends_when_prices_are_published_and_partial_saving_is_unavailable(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    publish(hass, now, 8)
    await m._async_plan(now)
    assert len(m.plan_hours) == len(m.plan.hours) == 8
    assert not any(m.plan_guess)
    assert "incomplete_forecast" in m.plan.breakdown["quality"]["reasons"]
    assert SavingNext24hSensor(m).native_value is None
    attrs = SetpointSensor(m).extra_state_attributes
    assert attrs["price_horizon_hours"] == 8 and attrs["cost_24h"] is None
    assert attrs["price_limited_until"] == (now + timedelta(hours=8)).isoformat()

    publish(hass, now, 36)
    await m._async_plan(now + timedelta(seconds=1))
    assert len(m.plan_hours) == 36 and len(m.plan.hours) == 24
    assert "incomplete_forecast" not in m.plan.breakdown["quality"]["reasons"]
    assert SetpointSensor(m).extra_state_attributes["price_limited_until"] is None


async def test_a_sensor_without_forecast_only_publishes_the_current_hour(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow()
    hass.states.async_set(PRICE, "-0.05", {"unit_of_measurement": "EUR/kWh"})
    inp, _ = m._energy(now, 36)
    assert inp.import_price == [-.05]


async def test_fixed_contract_still_has_a_full_horizon(entry):
    m = entry.runtime_data
    m.conf.update(price_mode="fixed", fixed_price=.3, fixed_export_price=.05)
    inp, _ = m._energy(dt_util.utcnow(), 36)
    assert inp.import_price == [.3]*36 and inp.export_price == [.05]*36


async def test_missing_current_price_drops_an_old_plan(hass, entry):
    m = entry.runtime_data
    now = dt_util.utcnow()
    assert m.plan is not None
    hass.states.async_set(PRICE, "unavailable")
    await m._async_plan(now)
    assert m.plan is None and m.plan_hours == [] and m.plan_tariff == []
    assert m.reason.code == "no_price"
