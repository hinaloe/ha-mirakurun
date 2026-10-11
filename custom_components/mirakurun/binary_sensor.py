"""Binary sensors for Mirakurun."""

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .broadcast import Broadcast, SubchannelSplit, detect_splits
from .coordinator import MirakurunConfigEntry, ProgramCoordinator, StatusCoordinator
from .entity import (
    MirakurunBroadcastEntity,
    MirakurunServerEntity,
    MirakurunTunerEntity,
    async_add_tuner_entities,
)
from .identifiers import broadcast_identifier
from .models import Tuner

PARALLEL_UPDATES = 0

SPLIT_KEY = "subchannel_split"


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
    _async_sync_split_sensors(hass, entry, async_add_entities)


def _async_sync_split_sensors(
    hass: HomeAssistant,
    entry: MirakurunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Keep one split sensor per broadcast that has subchannels.

    Subchannels can join or split off when the broadcast list is regrouped, so
    the sensors are added and removed as the grouping changes.
    """
    services = entry.runtime_data.services
    programs = entry.runtime_data.programs
    registry = er.async_get(hass)
    added: set[int] = set()

    @callback
    def sync() -> None:
        wanted = {b.main.id: b for b in services.data.broadcasts if b.subs}
        wanted_ids = {
            f"{broadcast_identifier(entry, main_id)}_{SPLIT_KEY}" for main_id in wanted
        }
        for registry_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id
        ):
            if (
                registry_entry.domain == BINARY_SENSOR_DOMAIN
                and registry_entry.unique_id.endswith(f"_{SPLIT_KEY}")
                and registry_entry.unique_id not in wanted_ids
            ):
                registry.async_remove(registry_entry.entity_id)
        added.intersection_update(wanted)
        new = [
            MirakurunSubchannelSplitBinarySensor(programs, entry, broadcast)
            for main_id, broadcast in wanted.items()
            if main_id not in added
        ]
        added.update(wanted)
        if new:
            async_add_entities(new)

    sync()
    entry.async_on_unload(services.async_add_listener(sync))


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


class MirakurunSubchannelSplitBinarySensor(
    MirakurunBroadcastEntity, BinarySensorEntity
):
    """On while a subchannel airs something other than the main service."""

    _attr_translation_key = "subchannel_split"

    def __init__(
        self,
        coordinator: ProgramCoordinator,
        entry: MirakurunConfigEntry,
        broadcast: Broadcast,
    ) -> None:
        super().__init__(coordinator, entry, broadcast, SPLIT_KEY)

    def _splits(self) -> list[SubchannelSplit]:
        schedule = self.schedule
        if schedule is None:
            return []
        return detect_splits(
            self.broadcast.main, schedule.main, schedule.subs, dt_util.utcnow()
        )

    @property
    def is_on(self) -> bool:
        return bool(self._splits())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "subchannels": [
                {
                    "service": split.service.name,
                    "program": split.program.program.name,
                    "end": split.program.end.isoformat(),
                }
                for split in self._splits()
            ]
        }
