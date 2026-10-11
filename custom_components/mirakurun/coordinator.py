"""Data update coordinators for Mirakurun."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MirakurunClient, MirakurunError
from .broadcast import Broadcast
from .const import (
    CONF_PROGRAM_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_PROGRAM_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    VERSION_INTERVAL,
)
from .models import Service, Status, Tuner, Version
from .programs import Schedule, build_schedule

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


class ProgramCoordinator(DataUpdateCoordinator[dict[int, BroadcastSchedule]]):
    """Polls programs for the selected broadcasts."""

    config_entry: MirakurunConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MirakurunConfigEntry,
        client: MirakurunClient,
        broadcasts: tuple[Broadcast, ...],
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
        self.broadcasts = broadcasts
        self._schedules: dict[int, Schedule] = {}

    async def _async_update_data(self) -> dict[int, BroadcastSchedule]:
        services = [s for b in self.broadcasts for s in (b.main, *b.subs)]
        results = await asyncio.gather(
            *(self.client.get_programs(s.network_id, s.service_id) for s in services),
            return_exceptions=True,
        )
        schedules: dict[int, Schedule] = {}
        errors: list[MirakurunError] = []
        for service, result in zip(services, results, strict=True):
            if isinstance(result, MirakurunError):
                errors.append(result)
                if service.id in self._schedules:
                    schedules[service.id] = self._schedules[service.id]
            elif isinstance(result, BaseException):
                raise result
            else:
                schedules[service.id] = build_schedule(result)
        if services and len(errors) == len(services):
            raise _update_failed(errors[0]) from errors[0]
        if errors:
            _LOGGER.debug(
                "Failed to fetch programs for %d of %d services",
                len(errors),
                len(services),
            )
        self._schedules = schedules
        return {
            b.main.id: BroadcastSchedule(
                b,
                schedules.get(b.main.id, ()),
                tuple((s, schedules.get(s.id, ())) for s in b.subs),
            )
            for b in self.broadcasts
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
            return await self.client.get_version()
        except MirakurunError as err:
            raise _update_failed(err) from err


@dataclass(slots=True)
class MirakurunRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: MirakurunClient
    broadcasts: tuple[Broadcast, ...]
    status: StatusCoordinator
    programs: ProgramCoordinator
    version: VersionCoordinator
