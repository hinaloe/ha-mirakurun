"""Tests for following broadcasts added to and removed from Mirakurun."""

from collections.abc import Collection
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import DOMAIN

from .common import (
    ENTRY_ID,
    PROGRAMS,
    at,
    entity_id,
    load_fixture,
    make_program,
    mock_mirakurun,
    setup_integration,
)

FUJI = (32741, 1056)
FUJI_SERVICE: dict[str, Any] = {
    "id": 3274101056,
    "serviceId": 1056,
    "networkId": 32741,
    "name": "フジテレビ",
    "type": 1,
    "remoteControlKeyId": 8,
    "channel": {"type": "GR", "channel": "21"},
    "hasLogoData": True,
}
FUJI_PROGRAMS = {**PROGRAMS, FUJI: [make_program(FUJI, 500, at(11), 120, "ドラマ")]}
FUJI_KEY = f"{ENTRY_ID}_broadcast_3274101056"
MX2_KEY = f"{ENTRY_ID}_broadcast_3239123610"
NHK_KEY = f"{ENTRY_ID}_broadcast_3273601024"


def _services(
    *, add: list[dict[str, Any]] | None = None, drop: Collection[int] = ()
) -> list[dict[str, Any]]:
    services = [s for s in load_fixture("services.json") if s["id"] not in drop]
    return services + (add or [])


async def _refresh_services(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.services.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)


def _program_fetches(aioclient_mock: AiohttpClientMocker, service_id: int) -> int:
    return sum(
        1
        for _method, url, _data, _headers in aioclient_mock.mock_calls
        if url.path == "/api/programs" and url.query.get("serviceId") == str(service_id)
    )


async def test_new_broadcast_added_without_reload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(
        aioclient_mock, services=_services(add=[FUJI_SERVICE]), programs=FUJI_PROGRAMS
    )
    await _refresh_services(hass, config_entry)

    state = hass.states.get(entity_id(hass, "sensor", f"{FUJI_KEY}_current_program"))
    assert state is not None
    assert state.state == "ドラマ"


async def test_removed_broadcast_device_removed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=_services(drop={3239123610}))
    await _refresh_services(hass, config_entry)

    assert (
        device_registry.async_get_device_by_identifier((DOMAIN, MX2_KEY), ENTRY_ID)
        is None
    )
    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{MX2_KEY}_current_program"
        )
        is None
    )


async def test_broadcast_returns_after_removal(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=_services(drop={3239123610}))
    await _refresh_services(hass, config_entry)
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await _refresh_services(hass, config_entry)
    # The program refresh is debounced; let its cooldown pass.
    frozen_now.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get(entity_id(hass, "sensor", f"{MX2_KEY}_current_program"))
    assert state is not None
    assert state.state == "MX2特番"


async def test_disabled_broadcast_survives_refresh(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device_by_identifier((DOMAIN, MX2_KEY), ENTRY_ID)
    assert device is not None
    device_registry.async_update_device(
        device.id, disabled_by=dr.DeviceEntryDisabler.USER
    )

    aioclient_mock.clear_requests()
    mock_mirakurun(
        aioclient_mock, services=_services(add=[FUJI_SERVICE]), programs=FUJI_PROGRAMS
    )
    await _refresh_services(hass, config_entry)

    device = device_registry.async_get_device_by_identifier((DOMAIN, MX2_KEY), ENTRY_ID)
    assert device is not None
    assert device.disabled_by is dr.DeviceEntryDisabler.USER


async def test_disabled_broadcast_programs_not_fetched(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    device = device_registry.async_get_device_by_identifier((DOMAIN, MX2_KEY), ENTRY_ID)
    assert device is not None
    device_registry.async_update_device(
        device.id, disabled_by=dr.DeviceEntryDisabler.USER
    )

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await hass.config_entries.async_reload(ENTRY_ID)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert _program_fetches(aioclient_mock, 23610) == 0
    assert 3239123610 not in config_entry.runtime_data.programs.data


async def test_split_sensor_added_when_subchannel_appears(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_mirakurun(aioclient_mock, services=_services(drop={3273601025}))
    await setup_integration(hass, config_entry)
    assert (
        entity_registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{NHK_KEY}_subchannel_split"
        )
        is None
    )

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await _refresh_services(hass, config_entry)

    assert (
        hass.states.get(entity_id(hass, "binary_sensor", f"{NHK_KEY}_subchannel_split"))
        is not None
    )
