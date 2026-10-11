"""Group Mirakurun services into broadcasts (main service plus subchannels)."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from .api import MirakurunClient, MirakurunError
from .models import Program, Service
from .programs import Schedule, ScheduledProgram, build_schedule, current_program

TV_SERVICE_TYPE = 1
SHARED_RATIO_THRESHOLD = 0.5
DISCOVERY_CONCURRENCY = 4


@dataclass(frozen=True, slots=True)
class Broadcast:
    """A main service and the subchannels that usually simulcast it."""

    main: Service
    subs: tuple[Service, ...] = ()


@dataclass(frozen=True, slots=True)
class SubchannelSplit:
    """A subchannel currently airing something other than the main service."""

    service: Service
    program: ScheduledProgram


def group_by_channel(services: Sequence[Service]) -> list[list[Service]]:
    """Group TV services by physical channel, each sorted by service ID."""
    groups: dict[tuple[str, str], list[Service]] = defaultdict(list)
    for service in services:
        if service.type == TV_SERVICE_TYPE:
            groups[(service.channel.type, service.channel.channel)].append(service)
    return [sorted(group, key=lambda s: s.service_id) for group in groups.values()]


def classify_channel(
    services: Sequence[Service],
    main_programs: Sequence[Program] | None,
    now: datetime,
) -> list[Broadcast]:
    """Split one physical channel into broadcasts by how often programs are shared."""
    main, *others = services
    upcoming = [
        item.program for item in build_schedule(main_programs or ()) if item.end > now
    ]
    if not upcoming:
        return [Broadcast(service) for service in services]
    subs: list[Service] = []
    independents: list[Service] = []
    for service in others:
        shared = sum(1 for p in upcoming if service.service_id in p.shared_service_ids)
        if shared / len(upcoming) >= SHARED_RATIO_THRESHOLD:
            subs.append(service)
        else:
            independents.append(service)
    return [Broadcast(main, tuple(subs)), *(Broadcast(s) for s in independents)]


async def discover_broadcasts(
    client: MirakurunClient, now: datetime
) -> list[Broadcast]:
    """Fetch services and classify every physical channel."""
    services = await client.get_services()
    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def classify(group: list[Service]) -> list[Broadcast]:
        main = group[0]
        programs: list[Program] | None
        async with semaphore:
            try:
                programs = await client.get_programs(main.network_id, main.service_id)
            except MirakurunError:
                programs = None
        return classify_channel(group, programs, now)

    results = await asyncio.gather(
        *(classify(group) for group in group_by_channel(services))
    )
    return [broadcast for result in results for broadcast in result]


def to_option_map(broadcasts: Sequence[Broadcast]) -> dict[str, list[int]]:
    """Serialize broadcasts for config entry options."""
    return {str(b.main.id): [s.id for s in b.subs] for b in broadcasts}


def default_selection(broadcasts: Sequence[Broadcast]) -> list[str]:
    """Return the broadcasts selected by default: every terrestrial broadcast."""
    return [str(b.main.id) for b in broadcasts if b.main.channel.type == "GR"]


def resolve_broadcasts(
    option_map: Mapping[str, Sequence[int]],
    selected: Sequence[str],
    services: Sequence[Service],
) -> list[Broadcast]:
    """Rebuild selected broadcasts, skipping services that no longer exist."""
    by_id = {service.id: service for service in services}
    result: list[Broadcast] = []
    for key in selected:
        main = by_id.get(int(key))
        if main is None:
            continue
        subs = tuple(by_id[sid] for sid in option_map.get(key, ()) if sid in by_id)
        result.append(Broadcast(main, subs))
    return result


def _main_keys(main_schedule: Schedule) -> set[tuple[int, datetime]]:
    return {(item.program.event_id, item.start) for item in main_schedule}


def _is_distinct(
    main: Service, main_keys: set[tuple[int, datetime]], item: ScheduledProgram
) -> bool:
    return (
        main.service_id not in item.program.shared_service_ids
        and (item.program.event_id, item.start) not in main_keys
    )


def distinct_sub_programs(
    main: Service, main_schedule: Schedule, sub_schedule: Schedule
) -> list[ScheduledProgram]:
    """Return subchannel programs that are not simulcasts of the main service."""
    keys = _main_keys(main_schedule)
    return [item for item in sub_schedule if _is_distinct(main, keys, item)]


def detect_splits(
    main: Service,
    main_schedule: Schedule,
    subs: Sequence[tuple[Service, Schedule]],
    now: datetime,
) -> list[SubchannelSplit]:
    """Return subchannels airing their own program at ``now``."""
    keys = _main_keys(main_schedule)
    splits: list[SubchannelSplit] = []
    for service, schedule in subs:
        current = current_program(schedule, now)
        if current is not None and _is_distinct(main, keys, current):
            splits.append(SubchannelSplit(service, current))
    return splits
