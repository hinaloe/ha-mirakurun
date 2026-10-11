"""Base entities and device info for Mirakurun."""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from homeassistant.const import CONF_URL
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .broadcast import Broadcast
from .const import DOMAIN, MANUFACTURER
from .coordinator import (
    BroadcastSchedule,
    MirakurunConfigEntry,
    ProgramCoordinator,
    StatusCoordinator,
)
from .identifiers import broadcast_identifier, server_identifier, tuner_identifier
from .models import Tuner
from .programs import next_transition


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
        via_device_id=entry.runtime_data.server_device_id,
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
        # A broadcast is not a physical device; HA lists services separately.
        entry_type=DeviceEntryType.SERVICE,
        via_device_id=entry.runtime_data.server_device_id,
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
        # Tuners that drop out keep their entities (they turn unavailable), so
        # known indexes are never forgotten; stale tuners go away at setup.
        new = [t for t in coordinator.data.tuners if t.index not in known]
        if not new:
            return
        known.update(t.index for t in new)
        async_add_entities(entity for tuner in new for entity in factory(tuner))

    add_new_tuners()
    entry.async_on_unload(coordinator.async_add_listener(add_new_tuners))


def async_add_broadcast_entities(
    entry: MirakurunConfigEntry,
    factory: Callable[[Broadcast], Iterable[Entity]],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add entities for current broadcasts and for broadcasts found later.

    A broadcast counts as handled once the factory returns entities for it; as
    a guard, one that got none is offered again on the next refresh.
    Broadcasts that disappear are forgotten, so they get entities again if they
    come back.
    """
    services = entry.runtime_data.services
    handled: set[int] = set()

    @callback
    def add_new_broadcasts() -> None:
        broadcasts = services.data.broadcasts
        handled.intersection_update(b.main.id for b in broadcasts)
        entities: list[Entity] = []
        for broadcast in broadcasts:
            if broadcast.main.id in handled:
                continue
            created = list(factory(broadcast))
            if created:
                handled.add(broadcast.main.id)
                entities.extend(created)
        if entities:
            async_add_entities(entities)

    add_new_broadcasts()
    entry.async_on_unload(services.async_add_listener(add_new_broadcasts))


class MirakurunBroadcastEntity(MirakurunEntity[ProgramCoordinator]):
    """An entity of a broadcast device that refreshes at program boundaries."""

    def __init__(
        self,
        coordinator: ProgramCoordinator,
        entry: MirakurunConfigEntry,
        broadcast: Broadcast,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self.broadcast = broadcast
        self._attr_unique_id = f"{broadcast_identifier(entry, broadcast.main.id)}_{key}"
        self._attr_device_info = broadcast_device_info(entry, broadcast)
        self._unsub_transition: CALLBACK_TYPE | None = None

    @property
    def schedule(self) -> BroadcastSchedule | None:
        """Return the latest schedules for this broadcast."""
        return self.coordinator.data.get(self.broadcast.main.id)

    @property
    def available(self) -> bool:
        """Return whether programs are known for this broadcast."""
        return super().available and self.schedule is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_transition()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_transition()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._schedule_transition()
        super()._handle_coordinator_update()

    @callback
    def _cancel_transition(self) -> None:
        if self._unsub_transition is not None:
            self._unsub_transition()
            self._unsub_transition = None

    @callback
    def _schedule_transition(self) -> None:
        self._cancel_transition()
        schedule = self.schedule
        if schedule is None:
            return
        now = dt_util.utcnow()
        candidates = [
            t
            for t in (
                next_transition(schedule.main, now),
                *(next_transition(sub, now) for _, sub in schedule.subs),
            )
            if t is not None
        ]
        if candidates:
            self._unsub_transition = async_track_point_in_utc_time(
                self.hass, self._handle_transition, min(candidates)
            )

    @callback
    def _handle_transition(self, _now: datetime) -> None:
        self._unsub_transition = None
        self._schedule_transition()
        self.async_write_ha_state()
