"""Buttons: learn now, import history from Weheat."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoostConfigEntry
from .const import DOMAIN, WEHEAT_IMPORT_DAYS
from .entity import RoostEntity


async def async_setup_entry(hass: HomeAssistant, entry: RoostConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    m = entry.runtime_data
    async_add_entities([LearnButton(m), ImportButton(m)])


class LearnButton(RoostEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:school-outline"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "learn_now")

    async def async_press(self) -> None:
        self.hass.async_create_background_task(self.mgr.async_learn(), f"{DOMAIN} learning")


class ImportButton(RoostEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:cloud-download-outline"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "import_history")

    async def async_press(self) -> None:
        self.hass.async_create_background_task(self.mgr.async_import(WEHEAT_IMPORT_DAYS), f"{DOMAIN} weheat import")
