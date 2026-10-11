"""Shared helpers for Mirakurun tests."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import (
    CONF_BROADCAST_MAP,
    CONF_CHANNEL_TYPES,
    CONF_PROGRAM_INTERVAL,
    CONF_SERVICE_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
)

BASE_URL = "http://mirakurun.local:40772"
ENTRY_ID = "01JMIRAKURUNTESTENTRY00000"
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures"

NHK = (32736, 1024)
NHK2 = (32736, 1025)
MX1 = (32391, 23608)
MX2 = (32391, 23610)
SHOP = (7, 55)
TOEI = (7, 218)


def at(hour: int, minute: int = 0) -> datetime:
    """Return a UTC time on the test day."""
    return NOW.replace(hour=hour, minute=minute)


def load_fixture(name: str) -> Any:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_program(
    service: tuple[int, int],
    event_id: int,
    start: datetime,
    minutes: int | None,
    name: str,
    *,
    shared: Iterable[int] = (),
    genre: int | None = None,
    genre_lv2: int = 0,
) -> dict[str, Any]:
    """Build a Mirakurun program payload. ``minutes=None`` means unknown duration."""
    network_id, service_id = service
    item: dict[str, Any] = {
        "id": network_id * 10**10 + service_id * 10**5 + event_id,
        "eventId": event_id,
        "serviceId": service_id,
        "networkId": network_id,
        "startAt": int(start.timestamp() * 1000),
        "duration": minutes * 60_000 if minutes is not None else 1,
        "isFree": True,
        "name": name,
        "description": f"{name} description",
    }
    if genre is not None:
        item["genres"] = [{"lv1": genre, "lv2": genre_lv2, "un1": 15, "un2": 15}]
    shared_ids = list(shared)
    if shared_ids:
        item["relatedItems"] = [
            {"type": "shared", "serviceId": sid, "eventId": event_id}
            for sid in shared_ids
        ]
    return item


PROGRAMS: dict[tuple[int, int], list[dict[str, Any]]] = {
    NHK: [
        make_program(
            NHK, 1, at(11), 90, "ニュース", shared=(1024, 1025), genre=0, genre_lv2=1
        ),
        make_program(NHK, 2, at(12, 30), 30, "天気", shared=(1024,), genre=0),
        make_program(NHK, 3, at(13), 60, "ドキュメント", shared=(1024, 1025), genre=8),
    ],
    NHK2: [
        make_program(NHK2, 1, at(11), 90, "ニュース", shared=(1024, 1025), genre=0),
        make_program(NHK2, 20, at(12, 30), 30, "国会中継", genre=0),
        make_program(NHK2, 3, at(13), 60, "ドキュメント", shared=(1024, 1025), genre=8),
    ],
    MX1: [
        make_program(MX1, 100, at(11, 30), 60, "MXニュース", genre=0),
        make_program(MX1, 101, at(12, 30), 60, "アニメ", genre=7),
    ],
    MX2: [make_program(MX2, 200, at(11), 120, "MX2特番", genre=5)],
    SHOP: [make_program(SHOP, 300, at(10), 240, "通販")],
    TOEI: [make_program(TOEI, 400, at(10), 240, "時代劇", genre=3)],
}

DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_CHANNEL_TYPES: ["GR"],
    CONF_STATUS_INTERVAL: 30,
    CONF_PROGRAM_INTERVAL: 30,
    CONF_SERVICE_INTERVAL: 1,
}

# Options written by phase 1 (config entry minor version 1).
LEGACY_OPTIONS: dict[str, Any] = {
    CONF_BROADCAST_MAP: {
        "3273601024": [3273601025],
        "3239123608": [],
        "3239123610": [],
    },
    "broadcasts": ["3273601024", "3239123608", "3239123610"],
    CONF_STATUS_INTERVAL: 45,
    CONF_PROGRAM_INTERVAL: 30,
}


def mock_mirakurun(
    aioclient_mock: AiohttpClientMocker,
    *,
    base_url: str = BASE_URL,
    status: Mapping[str, Any] | None = None,
    tuners: Sequence[Mapping[str, Any]] | None = None,
    services: Sequence[Mapping[str, Any]] | None = None,
    programs: Mapping[tuple[int, int], list[dict[str, Any]]] | None = None,
    fail_programs: Iterable[tuple[int, int]] = (),
    fail_status: bool = False,
    fail_version: bool = False,
    fail_services: bool = False,
) -> None:
    """Register mocked Mirakurun API responses."""
    api = f"{base_url}/api"
    failing = set(fail_programs)

    def register(path: str, payload: Any, fail: bool) -> None:
        if fail:
            aioclient_mock.get(f"{api}/{path}", exc=aiohttp.ClientError())
        else:
            aioclient_mock.get(f"{api}/{path}", json=payload)

    register("version", load_fixture("version.json"), fail_version)
    register(
        "status",
        dict(status) if status is not None else load_fixture("status.json"),
        fail_status,
    )
    register(
        "tuners",
        list(tuners) if tuners is not None else load_fixture("tuners.json"),
        fail_status,
    )
    register(
        "services",
        list(services) if services is not None else load_fixture("services.json"),
        fail_services,
    )
    for (network_id, service_id), items in (programs or PROGRAMS).items():
        params = {"networkId": network_id, "serviceId": service_id}
        if (network_id, service_id) in failing:
            aioclient_mock.get(
                f"{api}/programs", params=params, exc=aiohttp.ClientError()
            )
        else:
            aioclient_mock.get(f"{api}/programs", params=params, json=items)


def create_entry(
    options: Mapping[str, Any] | None = None, minor_version: int = 3
) -> MockConfigEntry:
    """Create a config entry for the mocked server."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Mirakurun",
        data={CONF_URL: BASE_URL},
        options=dict(options if options is not None else DEFAULT_OPTIONS),
        entry_id=ENTRY_ID,
        minor_version=minor_version,
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Resolve an entity ID from its unique ID."""
    result = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert result is not None, unique_id
    return result
