"""Sensors describing how the last page went."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MastConfigEntry
from .entity import MastEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    async_add_entities(
        [
            MastOpenPagesSensor(entry),
            MastAckedBySensor(entry),
            MastTimeToAckSensor(entry),
        ]
    )


class MastOpenPagesSensor(MastEntity, SensorEntity):
    """How many pages are waiting for an answer."""

    entity_description = SensorEntityDescription(
        key="open_pages",
        translation_key="open_pages",
        state_class=SensorStateClass.MEASUREMENT,
    )

    def __init__(self, entry: MastConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(entry, "open_pages")

    @property
    def native_value(self) -> int:
        """Return the number of open pages."""
        return len(self._data.watcher.open_pages)


class MastAckedBySensor(MastEntity, SensorEntity):
    """Which device answered the last page.

    Mast reports the device rather than the person. One owner may carry both a
    phone and a watch, and it is useful to know which one they picked up.
    """

    entity_description = SensorEntityDescription(
        key="last_acked_by",
        translation_key="last_acked_by",
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    def __init__(self, entry: MastConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(entry, "last_acked_by")

    @property
    def native_value(self) -> str | None:
        """Return the device that answered the last page."""
        return self._data.watcher.last_acked_by


class MastTimeToAckSensor(MastEntity, SensorEntity):
    """Seconds between the last page landing and a person answering it.

    It carries a measurement state class, so long-term statistics keep the
    average time this household takes to answer.
    """

    entity_description = SensorEntityDescription(
        key="last_time_to_ack",
        translation_key="last_time_to_ack",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
    )

    def __init__(self, entry: MastConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(entry, "last_time_to_ack")

    @property
    def native_value(self) -> int | None:
        """Return how long the last page waited, in seconds."""
        return self._data.watcher.last_open_for
