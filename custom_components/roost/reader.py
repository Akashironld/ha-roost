"""Reading Home Assistant: the state of an entity as a number, a temperature in °C or a power in kW (None when it is
not there or not known). The one place the runtime turns entity states into the values the core works with."""
from __future__ import annotations

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State

from . import history
from .util import num as _f


class Reader:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def state(self, eid: str | None) -> State | None:
        if not eid:
            return None
        st = self.hass.states.get(eid)
        return None if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) else st

    def num(self, eid: str | None) -> float | None:
        st = self.state(eid)
        return _f(st.state) if st else None

    def temp(self, eid: str | None) -> float | None:
        st = self.state(eid)
        v = _f(st.state) if st else None
        if (v is not None and st is not None
                and st.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == UnitOfTemperature.FAHRENHEIT):
            v = (v - 32) * 5 / 9
        return v if v is not None and history.BAD_LOW < v < history.BAD_HIGH else None

    def kw(self, eid: str | None) -> float | None:
        st = self.state(eid)
        v = _f(st.state) if st else None
        if st is None or v is None:
            return None
        u = (st.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or "").lower()
        return v / 1000 if u == "w" else v

    def sys_to_c(self, v: float | None) -> float | None:
        if v is None:
            return None
        return (v - 32) * 5 / 9 if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else v

    def c_to_sys(self, v: float) -> float:
        return round(v * 9 / 5 + 32) if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else v
