"""The notify entity: `notify.send_message` reaches the phone."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MastConfigEntry
from .api import MastError
from .entity import MastEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the notify platform."""
    async_add_entities([MastNotifyEntity(entry)])


class MastNotifyEntity(MastEntity, NotifyEntity):
    """A plain notification. Anything that needs an answer uses `mast.page`."""

    _attr_name = None
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, entry: MastConfigEntry) -> None:
        """Initialize the notify entity."""
        super().__init__(entry, "notify")

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message."""
        fields = {"body": message}
        if title:
            fields["title"] = title
        try:
            await self._data.client.send(fields)
        except MastError as err:
            raise HomeAssistantError(str(err)) from err
