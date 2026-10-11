"""Data models for Mirakurun API responses."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

UNKNOWN_DURATION_MS = 1


def _from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


@dataclass(frozen=True, slots=True)
class Version:
    """Installed and latest Mirakurun versions."""

    current: str
    latest: str | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Version:
        latest = data.get("latest")
        return cls(current=str(data["current"]), latest=str(latest) if latest else None)


@dataclass(frozen=True, slots=True)
class Status:
    """Server status."""

    version: str
    tuner_device_streams: int
    stored_events: int | None
    gathering_networks: tuple[int, ...]
    error_counts: Mapping[str, int]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Status:
        epg = data.get("epg") or {}
        streams = data.get("streamCount") or {}
        stored = epg.get("storedEvents")
        errors = data.get("errorCount") or {}
        return cls(
            version=str(data["version"]),
            tuner_device_streams=int(streams.get("tunerDevice", 0)),
            stored_events=int(stored) if stored is not None else None,
            gathering_networks=tuple(
                int(n) for n in epg.get("gatheringNetworks") or ()
            ),
            error_counts={str(key): int(value) for key, value in errors.items()},
        )


@dataclass(frozen=True, slots=True)
class TunerUser:
    """A client currently using a tuner."""

    id: str
    priority: int
    channel_name: str | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TunerUser:
        channel = (data.get("streamSetting") or {}).get("channel") or {}
        name = channel.get("name")
        return cls(
            id=str(data["id"]),
            priority=int(data.get("priority", 0)),
            channel_name=str(name) if name else None,
        )


@dataclass(frozen=True, slots=True)
class Tuner:
    """A tuner device."""

    index: int
    name: str
    types: tuple[str, ...]
    users: tuple[TunerUser, ...]
    is_available: bool
    is_free: bool
    is_using: bool
    is_fault: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Tuner:
        return cls(
            index=int(data["index"]),
            name=str(data["name"]),
            types=tuple(str(t) for t in data.get("types") or ()),
            users=tuple(TunerUser.from_dict(u) for u in data.get("users") or ()),
            is_available=bool(data.get("isAvailable", False)),
            is_free=bool(data.get("isFree", False)),
            is_using=bool(data.get("isUsing", False)),
            is_fault=bool(data.get("isFault", False)),
        )

    @property
    def top_user(self) -> TunerUser | None:
        """Return the user with the highest priority."""
        return max(self.users, key=lambda user: user.priority, default=None)


@dataclass(frozen=True, slots=True)
class ChannelRef:
    """A physical channel."""

    type: str
    channel: str


@dataclass(frozen=True, slots=True)
class Service:
    """A broadcast service."""

    id: int
    service_id: int
    network_id: int
    name: str
    type: int
    remote_control_key_id: int | None
    channel: ChannelRef
    has_logo_data: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Service:
        channel = data["channel"]
        key = data.get("remoteControlKeyId")
        return cls(
            id=int(data["id"]),
            service_id=int(data["serviceId"]),
            network_id=int(data["networkId"]),
            name=str(data["name"]),
            type=int(data["type"]),
            remote_control_key_id=int(key) if key is not None else None,
            channel=ChannelRef(
                type=str(channel["type"]), channel=str(channel["channel"])
            ),
            has_logo_data=bool(data.get("hasLogoData", False)),
        )


@dataclass(frozen=True, slots=True)
class Program:
    """A program in the EPG."""

    id: int
    network_id: int
    service_id: int
    event_id: int
    start: datetime
    duration_ms: int
    name: str | None
    description: str | None
    genre_lv1: int | None
    shared_service_ids: frozenset[int]

    @property
    def has_known_duration(self) -> bool:
        """Return whether the broadcaster announced the duration."""
        return self.duration_ms > UNKNOWN_DURATION_MS

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Program:
        network_id = int(data["networkId"])
        genres = data.get("genres") or ()
        shared = frozenset(
            int(item["serviceId"])
            for item in data.get("relatedItems") or ()
            if item.get("type") == "shared"
            and int(item.get("networkId", network_id)) == network_id
        )
        return cls(
            id=int(data["id"]),
            network_id=network_id,
            service_id=int(data["serviceId"]),
            event_id=int(data["eventId"]),
            start=_from_ms(int(data["startAt"])),
            duration_ms=int(data["duration"]),
            name=data.get("name") or None,
            description=data.get("description") or None,
            genre_lv1=int(genres[0]["lv1"]) if genres else None,
            shared_service_ids=shared,
        )
