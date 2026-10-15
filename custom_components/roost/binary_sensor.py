"""Binary sensors: paused after a manual change, whether the heat pump follows the thermostat, ready to steer."""
from __future__ import annotations

import time

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoostConfigEntry
from .entity import RoostEntity


async def async_setup_entry(hass: HomeAssistant, entry: RoostConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    m = entry.runtime_data
    async_add_entities([PausedSensor(m), FollowingSensor(m), ReadySensor(m)])


class PausedSensor(RoostEntity, BinarySensorEntity):
    _attr_icon = "mdi:hand-back-right-outline"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "paused")

    @property
    def is_on(self):
        p = self.mgr.mem.pause_until
        return bool(p and time.time() < p)


class FollowingSensor(RoostEntity, BinarySensorEntity):
    _attr_icon = "mdi:link-variant"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "following")

    @property
    def is_on(self):
        return self.mgr.following


class ReadySensor(RoostEntity, BinarySensorEntity):
    """The nightly self-check says Roost predicts well enough to steer (what is still missing in the attributes)."""

    _attr_icon = "mdi:check-decagram-outline"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "ready")

    @property
    def is_on(self):
        return self.mgr.ready

    @property
    def extra_state_attributes(self):
        c = self.mgr.check
        return {"still_missing": self.mgr.ready_missing, "plan_error_6h": c.get("rmse_6h"), "heating_hours": c.get("heating_hours"),
                "heat_ratio": c.get("heat_ratio"), "checked": c.get("at")}
