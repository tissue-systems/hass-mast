"""An event entity carrying the answer, so an automation can trigger on it.

The bus events are the low-level surface. This entity is the one that shows up
in the automation editor's trigger picker, so nobody has to type an event name.
"""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MastConfigEntry
from .const import EVENT_ACKNOWLEDGED, EVENT_EXPIRED, EVENT_RESOLVED
from .entity import MastEntity

_EVENT_TYPES = {
    EVENT_ACKNOWLEDGED: "acknowledged",
    EVENT_RESOLVED: "resolved",
    EVENT_EXPIRED: "expired",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event platform."""
    async_add_entities([MastAnswerEvent(entry)])


class MastAnswerEvent(MastEntity, EventEntity):
    """Fires when a page reaches its end: answered, closed, or given up on."""

    _attr_translation_key = "answer"
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(_EVENT_TYPES.values())

    def __init__(self, entry: MastConfigEntry) -> None:
        """Initialize the event entity."""
        super().__init__(entry, "answer")
        self._channel = entry.runtime_data.channel_name

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        for name in _EVENT_TYPES:
            self.async_on_remove(
                self.hass.bus.async_listen(name, self._handle, self._is_mine)
            )

    @callback
    def _is_mine(self, event_data: dict) -> bool:
        # Two channels on one instance share the bus, so an entity must only
        # report the pages its own channel sent.
        return event_data.get("channel") == self._channel

    @callback
    def _handle(self, event: Event) -> None:
        event_type = _EVENT_TYPES.get(event.event_type)
        if event_type is None:
            return
        data = dict(event.data)
        data.pop("channel", None)
        self._trigger_event(event_type, data)
        self.async_write_ha_state()
