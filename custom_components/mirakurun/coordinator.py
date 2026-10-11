"""Data update coordinators for Mirakurun."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MirakurunClient, MirakurunError
from .broadcast import Broadcast, Classification, Discovery, discover
from .const import (
    CONF_CHANNEL_TYPES,
    CONF_PROGRAM_INTERVAL,
    CONF_SERVICE_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_CHANNEL_TYPES,
    DEFAULT_PROGRAM_INTERVAL,
    DEFAULT_SERVICE_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    VERSION_INTERVAL,
    VERSION_RETRY_INTERVAL,
)
from .models import Service, Status, Tuner, Version
from .programs import Schedule, build_schedule
from .store import ClassificationStore

_LOGGER = logging.getLogger(__package__)

type MirakurunConfigEntry = ConfigEntry[MirakurunRuntimeData]


@dataclass(frozen=True, slots=True)
class StatusData:
    """Server status and tuners fetched together."""

    status: Status
    tuners: tuple[Tuner, ...]


@dataclass(frozen=True, slots=True)
class BroadcastSchedule:
    """Schedules for a broadcast's main service and its subchannels."""

    broadcast: Broadcast
    main: Schedule
    subs: tuple[tuple[Service, Schedule], ...]


def _update_failed(err: MirakurunError) -> UpdateFailed:
    return UpdateFailed(
        translation_domain=DOMAIN,
        translation_key="update_failed",
        translation_placeholders={"error": str(err)},
    )


class StatusCoordinator(DataUpdateCoordinator[StatusData]):
    """Polls server status and tuners."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MirakurunConfigEntry, client: MirakurunClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_status",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)
            ),
        )
        self.client = client

    async def _async_update_data(self) -> StatusData:
        try:
            status, tuners = await asyncio.gather(
                self.client.get_status(), self.client.get_tuners()
            )
        except MirakurunError as err:
            raise _update_failed(err) from err
        return StatusData(status, tuple(tuners))


class ServiceCoordinator(DataUpdateCoordinator[Discovery]):
    """Refreshes the broadcast list and regroups subchannels."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MirakurunConfigEntry,
        client: MirakurunClient,
        store: ClassificationStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_services",
            update_interval=timedelta(
                hours=entry.options.get(CONF_SERVICE_INTERVAL, DEFAULT_SERVICE_INTERVAL)
            ),
            always_update=False,
        )
        self.client = client
        self._store = store
        self._classification: Classification | None = None

    async def _async_update_data(self) -> Discovery:
        if self._classification is None:
            self._classification = await self._store.async_load()
        channel_types = self.config_entry.options.get(
            CONF_CHANNEL_TYPES, list(DEFAULT_CHANNEL_TYPES)
        )
        try:
            discovery = await discover(
                self.client, dt_util.utcnow(), channel_types, self._classification
            )
        except MirakurunError as err:
            raise _update_failed(err) from err
        if not discovery.channel_types:
            # An empty service list (e.g. during a channel scan) must not wipe
            # every broadcast device.
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="no_services")
        merged = {**self._classification, **discovery.classification}
        if merged != self._classification:
            self._classification = merged
            await self._store.async_save(merged)
        return discovery


class ProgramCoordinator(DataUpdateCoordinator[dict[int, BroadcastSchedule]]):
    """Polls programs for the selected broadcasts."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MirakurunConfigEntry,
        client: MirakurunClient,
        services: ServiceCoordinator,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_programs",
            update_interval=timedelta(
                minutes=entry.options.get(
                    CONF_PROGRAM_INTERVAL, DEFAULT_PROGRAM_INTERVAL
                )
            ),
        )
        self.client = client
        self.services = services
        self._schedules: dict[int, Schedule] = {}
        self._failing: set[int] = set()

    async def _async_update_data(self) -> dict[int, BroadcastSchedule]:
        broadcasts = self.services.data.broadcasts
        targets = [s for b in broadcasts for s in (b.main, *b.subs)]
        results = await asyncio.gather(
            *(self.client.get_programs(s.network_id, s.service_id) for s in targets),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException) and not isinstance(
                result, MirakurunError
            ):
                raise result
        errors = [r for r in results if isinstance(r, MirakurunError)]
        if targets and len(errors) == len(targets):
            # The coordinator reports the outage itself; per-service messages
            # would repeat on every refresh while everything fails.
            raise _update_failed(errors[0]) from errors[0]

        schedules: dict[int, Schedule] = {}
        failing: set[int] = set()
        for service, result in zip(targets, results, strict=True):
            if isinstance(result, MirakurunError):
                failing.add(service.id)
                if service.id not in self._failing:
                    _LOGGER.warning(
                        "Failed to fetch programs for %s, keeping previous data: %s",
                        service.name,
                        result,
                    )
                if service.id in self._schedules:
                    schedules[service.id] = self._schedules[service.id]
            elif isinstance(result, list):
                schedules[service.id] = build_schedule(result)
                if service.id in self._failing:
                    _LOGGER.info("Fetching programs for %s recovered", service.name)
        self._failing = failing
        self._schedules = schedules
        return {
            b.main.id: BroadcastSchedule(
                b,
                schedules.get(b.main.id, ()),
                tuple((s, schedules.get(s.id, ())) for s in b.subs),
            )
            for b in broadcasts
        }


class VersionCoordinator(DataUpdateCoordinator[Version]):
    """Polls the installed and latest Mirakurun versions."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MirakurunConfigEntry, client: MirakurunClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_version",
            update_interval=VERSION_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> Version:
        try:
            version = await self.client.get_version()
        except MirakurunError as err:
            self.update_interval = VERSION_RETRY_INTERVAL
            raise _update_failed(err) from err
        self.update_interval = VERSION_INTERVAL
        return version


@dataclass(slots=True)
class MirakurunRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: MirakurunClient
    services: ServiceCoordinator
    status: StatusCoordinator
    programs: ProgramCoordinator
    version: VersionCoordinator
    server_device_id: str = ""
