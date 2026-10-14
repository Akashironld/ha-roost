"""Sensors: the planned setpoint (with the 24-hour plan for the card), cost and saving, the learned models."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import RoostConfigEntry
from .entity import RoostEntity


async def async_setup_entry(hass: HomeAssistant, entry: RoostConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    m = entry.runtime_data
    async_add_entities([SetpointSensor(m), SavingNext24hSensor(m), SavingYesterdaySensor(m), SavingMonthSensor(m),
                        CostTodaySensor(m), EnergyTodaySensor(m), EnergyValueSensor(m), HouseModelSensor(m), HeatPumpModelSensor(m),
                        ImportSensor(m)])


def _cur(hass) -> str:
    return hass.config.currency or "EUR"


class SetpointSensor(RoostEntity, SensorEntity):
    """The setpoint Roost wants now; the attributes carry the plan the dashboard card draws."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:home-thermometer"
    _unrecorded_attributes = frozenset({"plan", "start", "comfort", "day_min", "night_min", "store_max", "day_hours"})

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "setpoint")

    @property
    def native_value(self):
        p = self.mgr.plan
        return p.first.sp if p and p.first else None

    @property
    def extra_state_attributes(self):
        m = self.mgr
        p, d = m.plan, m.decision
        s = m.settings()
        attrs = {"mode": m.mode, "reason": m.reason, "decision": d.reason if d else None, "room": m.room(),
                 "thermostat": m.thermostat_sp(), "storage_kwh": round(m.storage_e, 1),
                 "paused_until": datetime.fromtimestamp(m.mem.pause_until, tz=dt_util.UTC).isoformat() if m.mem.pause_until else None,
                 "comfort": s.comfort, "day_min": s.day_min, "night_min": s.night_min, "store_max": s.store_max}
        if p:
            attrs["start"] = datetime.fromtimestamp(m.plan_at - m.plan_at % 3600, tz=dt_util.UTC).isoformat() if m.plan_at else None
            attrs["plan"] = [[h.sp, round(h.t_end, 1), round(h.kwh, 2), round(h.price * 100, 1)] for h in p.hours]
            attrs["day_hours"] = [1 if h.day else 0 for h in m.plan_hours[:len(p.hours)]]
            attrs["cost_24h"] = round(p.cost, 2)
            attrs["steady_cost_24h"] = round(p.baseline_cost, 2)
            attrs["kwh_24h"] = round(p.kwh, 1)
        return attrs


class _Money(RoostEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    @property
    def native_unit_of_measurement(self) -> str:
        return _cur(self.hass)


class SavingNext24hSensor(_Money):
    _attr_icon = "mdi:piggy-bank-outline"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "saving_next_24h")

    @property
    def native_value(self):
        p = self.mgr.plan
        return round(p.saving, 2) if p else None


class SavingYesterdaySensor(_Money):
    _attr_icon = "mdi:piggy-bank"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "saving_yesterday")

    @property
    def native_value(self):
        d = self.mgr.saving_days
        return d[max(d)] if d else None

    @property
    def extra_state_attributes(self):
        return {"day": max(self.mgr.saving_days) if self.mgr.saving_days else None}


class SavingMonthSensor(_Money):
    _attr_icon = "mdi:piggy-bank"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "saving_month")

    @property
    def native_value(self):
        return self.mgr.saving_month()

    @property
    def last_reset(self):
        n = dt_util.now()
        return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class CostTodaySensor(_Money):
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "cost_today")

    @property
    def native_value(self):
        return round(self.mgr.cost_today, 2)

    @property
    def last_reset(self):
        return dt_util.start_of_local_day()


class EnergyTodaySensor(RoostEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 1
    _attr_entity_registry_enabled_default = False

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "energy_today")

    @property
    def native_value(self):
        return round(self.mgr.kwh_today, 2)


class EnergyValueSensor(RoostEntity, SensorEntity):
    _attr_icon = "mdi:cash-clock"
    _attr_suggested_display_precision = 3
    _attr_entity_registry_enabled_default = False

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "energy_value")

    @property
    def native_unit_of_measurement(self) -> str:
        return f"{_cur(self.hass)}/kWh"

    @property
    def native_value(self):
        h = self.mgr.plan_hours
        return round(h[0].p_grid, 4) if h else None

    @property
    def extra_state_attributes(self):
        h = self.mgr.plan_hours
        return {"own_solar_kw": round(h[0].own_kw, 2), "own_solar_value": round(h[0].p_own, 4)} if h else None


class HouseModelSensor(RoostEntity, SensorEntity):
    """How well the learned house model predicts a day (°C); the house's numbers in the attributes."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:home-analytics"
    _unrecorded_attributes = frozenset({"learning"})

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "house_model")

    @property
    def native_value(self):
        return self.mgr.house.error_t

    @property
    def extra_state_attributes(self):
        h = self.mgr.house
        return {"heat_loss_w_per_k": round(h.H * 1000), "wind_w_per_k_per_m_s": round(h.Hw * 1000, 1), "storage_kwh_per_k": round(h.C, 1),
                "floor_lag_h": round(h.lag, 2), "solar_gain_m2": round(h.g, 2), "internal_gain_kw": round(h.internal, 2),
                "time_constant_h": round(h.time_constant_h), "balance_error_kw": h.error_balance, "days": h.days,
                "heating_days": h.heating_days, "source": h.source, "learning": self.mgr.learn_info}


class HeatPumpModelSensor(RoostEntity, SensorEntity):
    """COP the model expects at 7 °C outside and 3 kW of heat."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:heat-pump-outline"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "heat_pump_model")

    @property
    def native_value(self):
        return round(self.mgr.pump.cop(7.0, 3.0), 2)

    @property
    def extra_state_attributes(self):
        p = self.mgr.pump
        return {"alpha": p.alpha, "beta": p.beta, "gamma": p.gamma, "outdoor_sensor_bias": p.bias,
                "max_output_kw_at_0": round(p.pmax(0.0), 1), "max_output_kw_at_10": round(p.pmax(10.0), 1), "hours": p.hours, "source": p.source}


class ImportSensor(RoostEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-download-outline"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "weheat_import")

    @property
    def native_value(self):
        i = self.mgr.import_info
        return "importing" if self.mgr.importing else ("done" if i.get("done") else (i.get("status") or "not yet")[:250])

    @property
    def extra_state_attributes(self):
        return dict(self.mgr.import_info)
