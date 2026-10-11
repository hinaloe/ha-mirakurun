"""Group Mirakurun services into broadcasts (main service plus subchannels)."""

import asyncio
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from .api import MirakurunClient, MirakurunError
from .models import Program, Service
from .programs import Schedule, ScheduledProgram, build_schedule, current_program

TV_SERVICE_TYPE = 1
SHARED_RATIO_THRESHOLD = 0.5
# Hysteresis for services classified before: a dependent subchannel splits off
# below SPLIT_THRESHOLD, an independent service joins at JOIN_THRESHOLD.
SPLIT_THRESHOLD = 0.4
JOIN_THRESHOLD = 0.6
DISCOVERY_CONCURRENCY = 4

type Classification = dict[int, bool]


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


@dataclass(frozen=True, slots=True)
class Discovery:
    """Broadcasts of the selected channel types and how services were grouped."""

    broadcasts: tuple[Broadcast, ...]
    classification: Classification
    channel_types: frozenset[str]


def group_by_channel(services: Sequence[Service]) -> list[list[Service]]:
    """Group TV services by physical channel, each sorted by service ID."""
    groups: dict[tuple[str, str], list[Service]] = defaultdict(list)
    for service in services:
        if service.type == TV_SERVICE_TYPE:
            groups[(service.channel.type, service.channel.channel)].append(service)
    return [sorted(group, key=lambda s: s.service_id) for group in groups.values()]


def _is_dependent(ratio: float, previous: bool | None) -> bool:
    if previous is None:
        return ratio >= SHARED_RATIO_THRESHOLD
    if previous:
        return ratio >= SPLIT_THRESHOLD
    return ratio >= JOIN_THRESHOLD


def classify_channel(
    services: Sequence[Service],
    main_programs: Sequence[Program] | None,
    now: datetime,
    previous: Mapping[int, bool] | None = None,
) -> list[Broadcast]:
    """Split one physical channel into broadcasts by how often programs are shared.

    ``previous`` maps service IDs to their last classification; it adds
    hysteresis and is used as-is when the main service has no upcoming programs.
    """
    prior = previous or {}
    main, *others = services
    upcoming = [
        item.program for item in build_schedule(main_programs or ()) if item.end > now
    ]
    subs: list[Service] = []
    independents: list[Service] = []
    for service in others:
        if upcoming:
            shared = sum(
                1 for p in upcoming if service.service_id in p.shared_service_ids
            )
            dependent = _is_dependent(shared / len(upcoming), prior.get(service.id))
        else:
            dependent = prior.get(service.id, False)
        if dependent:
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


async def discover(
    client: MirakurunClient,
    now: datetime,
    channel_types: Collection[str],
    previous: Mapping[int, bool],
) -> Discovery:
    """Fetch services and classify the physical channels of the given types."""
    services = await client.get_services()
    groups = group_by_channel(services)
    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def classify(group: list[Service]) -> list[Broadcast]:
        main = group[0]
        programs: list[Program] | None
        async with semaphore:
            try:
                programs = await client.get_programs(main.network_id, main.service_id)
            except MirakurunError:
                programs = None
        return classify_channel(group, programs, now, previous)

    selected = [g for g in groups if g[0].channel.type in channel_types]
    results = await asyncio.gather(*(classify(group) for group in selected))
    classification: Classification = {}
    for group, broadcasts in zip(selected, results, strict=True):
        dependent = {s.id for b in broadcasts for s in b.subs}
        classification.update({s.id: s.id in dependent for s in group[1:]})
    return Discovery(
        broadcasts=tuple(b for result in results for b in result),
        classification=classification,
        channel_types=frozenset(g[0].channel.type for g in groups),
    )


def classification_from_option_map(
    option_map: Mapping[str, Sequence[int]],
) -> Classification:
    """Seed a classification from legacy options: listed subchannels were dependent."""
    return {int(sid): True for subs in option_map.values() for sid in subs}


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
