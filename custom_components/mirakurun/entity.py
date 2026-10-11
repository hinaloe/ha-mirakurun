"""Base entities and device info for Mirakurun."""

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .broadcast import Broadcast
from .const import DOMAIN, MANUFACTURER
from .coordinator import MirakurunConfigEntry, StatusCoordinator
from .models import Tuner


def server_identifier(entry: MirakurunConfigEntry) -> str:
    """Return the device identifier of the server."""
    return entry.entry_id


def tuner_identifier(entry: MirakurunConfigEntry, index: int) -> str:
    """Return the device identifier of a tuner."""
    return f"{entry.entry_id}_tuner_{index}"


def broadcast_identifier(entry: MirakurunConfigEntry, main_id: int) -> str:
    """Return the device identifier of a broadcast."""
    return f"{entry.entry_id}_broadcast_{main_id}"


def server_device_info(entry: MirakurunConfigEntry) -> DeviceInfo:
    """Return device info for the server."""
    return DeviceInfo(
        identifiers={(DOMAIN, server_identifier(entry))},
        name=entry.title,
        manufacturer=MANUFACTURER,
        model="Mirakurun",
        sw_version=entry.runtime_data.status.data.status.version,
        configuration_url=entry.data[CONF_URL],
    )


def tuner_device_info(entry: MirakurunConfigEntry, tuner: Tuner) -> DeviceInfo:
    """Return device info for a tuner."""
    return DeviceInfo(
        identifiers={(DOMAIN, tuner_identifier(entry, tuner.index))},
        name=tuner.name,
        manufacturer=MANUFACTURER,
        model=f"Tuner ({'/'.join(tuner.types)})",
        via_device=(DOMAIN, server_identifier(entry)),  # type: ignore[typeddict-unknown-key]
    )


def broadcast_device_info(
    entry: MirakurunConfigEntry, broadcast: Broadcast
) -> DeviceInfo:
    """Return device info for a broadcast."""
    main = broadcast.main
    return DeviceInfo(
        identifiers={(DOMAIN, broadcast_identifier(entry, main.id))},
        name=main.name,
        manufacturer=MANUFACTURER,
        model=f"{main.channel.type} {main.channel.channel}",
        via_device=(DOMAIN, server_identifier(entry)),  # type: ignore[typeddict-unknown-key]
    )


class MirakurunEntity[CoordinatorT: DataUpdateCoordinator[Any]](
    CoordinatorEntity[CoordinatorT]
):
    """Base class for Mirakurun entities."""

    _attr_has_entity_name = True


class MirakurunServerEntity(MirakurunEntity[StatusCoordinator]):
    """An entity of the server device."""

    def __init__(
        self, coordinator: StatusCoordinator, entry: MirakurunConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_server_{key}"
        self._attr_device_info = server_device_info(entry)


class MirakurunTunerEntity(MirakurunEntity[StatusCoordinator]):
    """An entity of a tuner device."""

    def __init__(
        self,
        coordinator: StatusCoordinator,
        entry: MirakurunConfigEntry,
        tuner: Tuner,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._index = tuner.index
        self._attr_unique_id = f"{tuner_identifier(entry, tuner.index)}_{key}"
        self._attr_device_info = tuner_device_info(entry, tuner)

    @property
    def tuner(self) -> Tuner | None:
        """Return the latest data for this tuner."""
        return next(
            (t for t in self.coordinator.data.tuners if t.index == self._index), None
        )

    @property
    def available(self) -> bool:
        """Return whether the tuner still exists."""
        return super().available and self.tuner is not None


def async_add_tuner_entities(
    entry: MirakurunConfigEntry,
    coordinator: StatusCoordinator,
    factory: Callable[[Tuner], Iterable[Entity]],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add entities for current tuners and for tuners that appear later."""
    known: set[int] = set()

    @callback
    def add_new_tuners() -> None:
        new = [t for t in coordinator.data.tuners if t.index not in known]
        if not new:
            return
        known.update(t.index for t in new)
        async_add_entities(entity for tuner in new for entity in factory(tuner))

    add_new_tuners()
    entry.async_on_unload(coordinator.async_add_listener(add_new_tuners))
