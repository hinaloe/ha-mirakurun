"""Binary sensors for Mirakurun."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MirakurunConfigEntry, StatusCoordinator
from .entity import (
    MirakurunServerEntity,
    MirakurunTunerEntity,
    async_add_tuner_entities,
)
from .models import Tuner

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MirakurunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Mirakurun binary sensors."""
    status = entry.runtime_data.status
    async_add_entities([MirakurunGatheringBinarySensor(status, entry)])
    async_add_tuner_entities(
        entry,
        status,
        lambda tuner: [MirakurunTunerFaultBinarySensor(status, entry, tuner)],
        async_add_entities,
    )


class MirakurunGatheringBinarySensor(MirakurunServerEntity, BinarySensorEntity):
    """On while Mirakurun is gathering the program guide."""

    _attr_translation_key = "epg_gathering"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: StatusCoordinator, entry: MirakurunConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "epg_gathering")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.status.gathering_networks)


class MirakurunTunerFaultBinarySensor(MirakurunTunerEntity, BinarySensorEntity):
    """On when a tuner reports a fault."""

    _attr_translation_key = "tuner_fault"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: StatusCoordinator,
        entry: MirakurunConfigEntry,
        tuner: Tuner,
    ) -> None:
        super().__init__(coordinator, entry, tuner, "fault")

    @property
    def is_on(self) -> bool | None:
        tuner = self.tuner
        return tuner.is_fault if tuner else None
