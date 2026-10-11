"""Tests for setting up the Mirakurun integration."""

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun import async_remove_config_entry_device
from custom_components.mirakurun.const import (
    DOMAIN,
    VERSION_INTERVAL,
    VERSION_RETRY_INTERVAL,
)

from .common import ENTRY_ID, NHK, NHK2, PROGRAMS, mock_mirakurun, setup_integration

LOGGER = "custom_components.mirakurun"


async def test_setup_and_unload(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    data = config_entry.runtime_data
    assert [b.main.service_id for b in data.broadcasts] == [1024, 23608, 23610]
    assert [s.service_id for s in data.broadcasts[0].subs] == [1025]
    assert len(data.status.data.tuners) == 3
    assert data.version.data.latest == "4.1.5"
    nhk = data.programs.data[3273601024]
    assert [s.program.name for s in nhk.main] == ["ニュース", "天気", "ドキュメント"]
    assert [s.program.name for s in nhk.subs[0][1]][1] == "国会中継"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_services_fail(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock, fail_services=True)
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_status_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock, fail_status=True)
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_succeeds_without_version(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock, fail_version=True)
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert not config_entry.runtime_data.version.last_update_success


async def test_program_refresh_keeps_previous_data_on_partial_failure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    programs = config_entry.runtime_data.programs
    before = programs.data[3273601024].subs[0][1]

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, fail_programs={NHK2})
    await programs.async_refresh()

    assert programs.last_update_success
    assert programs.data[3273601024].subs[0][1] == before


async def test_program_refresh_fails_when_everything_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    programs = config_entry.runtime_data.programs

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, fail_programs=set(PROGRAMS))
    await programs.async_refresh()

    assert not programs.last_update_success


async def test_setup_with_service_without_programs(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock, programs={**PROGRAMS, NHK: []})
    await setup_integration(hass, config_entry)
    assert config_entry.runtime_data.programs.data[3273601024].main == ()


async def test_stale_broadcast_device_removed(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    stale = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{ENTRY_ID}_broadcast_999")},
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get(stale.id) is None
    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{ENTRY_ID}_broadcast_3273601024"), config_entry.entry_id
    )


async def test_remove_config_entry_device(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    tuner = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{ENTRY_ID}_tuner_14"), config_entry.entry_id
    )
    assert tuner is not None
    assert not await async_remove_config_entry_device(hass, config_entry, tuner)

    gone = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{ENTRY_ID}_tuner_99")},
    )
    assert await async_remove_config_entry_device(hass, config_entry, gone)


async def test_program_failure_and_recovery_are_logged_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    programs = config_entry.runtime_data.programs
    caplog.set_level(logging.INFO, logger="custom_components.mirakurun")

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, fail_programs={NHK2})
    await programs.async_refresh()
    await programs.async_refresh()
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and r.name == LOGGER
    ]
    assert len(warnings) == 1
    assert "ＮＨＫ総合２・東京" in warnings[0].getMessage()
    assert not [
        r for r in caplog.records if r.levelno == logging.INFO and r.name == LOGGER
    ]

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await programs.async_refresh()
    await programs.async_refresh()
    infos = [
        r for r in caplog.records if r.levelno == logging.INFO and r.name == LOGGER
    ]
    assert len(infos) == 1
    assert "ＮＨＫ総合２・東京" in infos[0].getMessage()
    assert (
        len(
            [
                r
                for r in caplog.records
                if r.levelno == logging.WARNING and r.name == LOGGER
            ]
        )
        == 1
    )


async def test_version_retry_interval(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock, fail_version=True)
    await setup_integration(hass, config_entry)
    version = config_entry.runtime_data.version
    assert version.update_interval == VERSION_RETRY_INTERVAL

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await version.async_refresh()
    assert version.last_update_success
    assert version.update_interval == VERSION_INTERVAL

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, fail_version=True)
    await version.async_refresh()
    assert version.update_interval == VERSION_RETRY_INTERVAL
