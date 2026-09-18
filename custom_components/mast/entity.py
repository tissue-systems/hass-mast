"""Shared entity base: every entity belongs to the one channel's device."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

if TYPE_CHECKING:
    from . import MastConfigEntry


class MastEntity(Entity):
    """One channel is one device: a phone somebody carries."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: MastConfigEntry, key: str) -> None:
        """Initialize the entity."""
        self._entry = entry
        self._data = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.runtime_data.channel_name,
            manufacturer="Tissue Systems",
            model="Mast channel",
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            self._data.watcher.async_add_listener(self.async_write_ha_state)
        )
