"""Tests for the Mirakurun API client."""

from datetime import UTC, datetime

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.api import (
    MirakurunClient,
    MirakurunConnectionError,
    MirakurunResponseError,
    normalize_url,
)
from custom_components.mirakurun.models import ChannelRef, TunerUser, Version

from .common import BASE_URL, NHK, at, make_program


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://mirakurun.local:40772", "http://mirakurun.local:40772"),
        ("http://mirakurun.local:40772/", "http://mirakurun.local:40772"),
        ("http://mirakurun.local:40772/api", "http://mirakurun.local:40772"),
        (" http://mirakurun.local:40772/api/ ", "http://mirakurun.local:40772"),
        ("https://tv.example.com/mirakurun/api", "https://tv.example.com/mirakurun"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["mirakurun.local:40772", "ftp://host", "http://", ""])
def test_normalize_url_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_url(raw)


def _client(hass: HomeAssistant) -> MirakurunClient:
    return MirakurunClient(async_get_clientsession(hass), f"{BASE_URL}/api/")


async def test_get_version(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    client = _client(hass)
    assert client.base_url == BASE_URL
    assert await client.get_version() == Version("4.0.0-beta.18", "4.1.5")


async def test_get_status(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    status = await _client(hass).get_status()
    assert status.version == "4.0.0-beta.18"
    assert status.tuner_device_streams == 2
    assert status.stored_events == 26849
    assert status.gathering_networks == (4, 7)
    assert status.error_counts["tunerDeviceRespawn"] == 1747


async def test_get_tuners(hass: HomeAssistant, mirakurun: AiohttpClientMocker) -> None:
    tuners = await _client(hass).get_tuners()
    assert [t.index for t in tuners] == [12, 14, 15]
    first = tuners[0]
    assert first.name == "PT3-S1"
    assert first.types == ("BS", "CS")
    assert first.is_using and not first.is_free and not first.is_fault
    assert first.top_user == TunerUser("EPGStation-recorder", 2, "ＢＳ朝日")
    assert tuners[1].top_user is None
    assert tuners[2].is_fault


async def test_get_services(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    services = await _client(hass).get_services()
    assert len(services) == 7
    nhk = services[0]
    assert nhk.id == 3273601024
    assert nhk.service_id == 1024
    assert nhk.network_id == 32736
    assert nhk.name == "ＮＨＫ総合１・東京"
    assert nhk.type == 1
    assert nhk.remote_control_key_id == 1
    assert nhk.channel == ChannelRef("GR", "27")
    assert nhk.has_logo_data
    assert services[5].remote_control_key_id is None


@pytest.mark.parametrize(
    "payload", [{"current": "4.0.0"}, {"current": "4.0.0", "latest": ""}]
)
def test_version_without_latest(payload: dict[str, str]) -> None:
    assert Version.from_dict(payload) == Version("4.0.0", None)


async def test_get_programs(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    programs = await _client(hass).get_programs(*NHK)
    assert len(programs) == 3
    first = programs[0]
    assert first.id == 32736 * 10**10 + 1024 * 10**5 + 1
    assert first.event_id == 1
    assert first.start == datetime(2026, 10, 11, 11, 0, tzinfo=UTC)
    assert first.duration_ms == 90 * 60_000
    assert first.has_known_duration
    assert first.name == "ニュース"
    assert first.description == "ニュース description"
    assert first.genre_lv1 == 0
    assert first.genre_lv2 == 1
    assert first.shared_service_ids == frozenset({1024, 1025})


async def test_program_with_unknown_duration(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    payload = make_program(NHK, 9, at(12), None, "未定")
    del payload["description"]
    aioclient_mock.get(
        f"{BASE_URL}/api/programs",
        params={"networkId": 32736, "serviceId": 1024},
        json=[payload],
    )
    (program,) = await _client(hass).get_programs(*NHK)
    assert program.duration_ms == 1
    assert not program.has_known_duration
    assert program.description is None
    assert program.genre_lv1 is None
    assert program.genre_lv2 is None
    assert program.shared_service_ids == frozenset()


async def test_http_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE_URL}/api/version", status=500)
    with pytest.raises(MirakurunResponseError):
        await _client(hass).get_version()


@pytest.mark.parametrize("exc", [TimeoutError(), aiohttp.ClientError()])
async def test_connection_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, exc: Exception
) -> None:
    aioclient_mock.get(f"{BASE_URL}/api/version", exc=exc)
    with pytest.raises(MirakurunConnectionError):
        await _client(hass).get_version()


async def test_invalid_json(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE_URL}/api/version", text="not json")
    with pytest.raises(MirakurunResponseError):
        await _client(hass).get_version()


async def test_unexpected_payload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE_URL}/api/tuners", json={"unexpected": True})
    with pytest.raises(MirakurunResponseError):
        await _client(hass).get_tuners()
