"""Whether a page is open and still waiting for an answer."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MastConfigEntry
from .entity import MastEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    async_add_entities([MastPageOpenBinarySensor(entry)])


class MastPageOpenBinarySensor(MastEntity, BinarySensorEntity):
    """On while a page this instance sent is still waiting to be answered.

    Hold a siren or a light on this one. It goes off as soon as somebody
    acknowledges on their phone, without a round trip through the house.
    """

    _attr_translation_key = "page_open"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: MastConfigEntry) -> None:
        """Initialize the binary sensor."""
        super().__init__(entry, "page_open")

    @property
    def is_on(self) -> bool:
        """Return true if a page is waiting for an answer."""
        return self._data.watcher.has_open_page

    @property
    def extra_state_attributes(self) -> dict[str, list[dict[str, str]]]:
        """Return the state attributes."""
        return {
            "pages": [
                {
                    "message_id": page.message_id,
                    "title": page.title,
                    "key": page.dedupe_key,
                    "state": page.state,
                    "open_for": int(page.age),
                }
                for page in self._data.watcher.open_pages
            ]
        }
