"""Binary sensors: paused after a manual change, and whether the heat pump follows the thermostat."""
from __future__ import annotations

import time

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoostConfigEntry
from .entity import RoostEntity


async def async_setup_entry(hass: HomeAssistant, entry: RoostConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    m = entry.runtime_data
    async_add_entities([PausedSensor(m), FollowingSensor(m)])


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
