"""Tests for setting up the Mirakurun integration."""

from datetime import timedelta
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
    CONF_CHANNEL_TYPES,
    CONF_PROGRAM_INTERVAL,
    CONF_SERVICE_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_SERVICE_INTERVAL,
    DOMAIN,
    SERVICE_RECHECK_INTERVAL,
    VERSION_INTERVAL,
    VERSION_RETRY_INTERVAL,
)
from custom_components.mirakurun.store import ClassificationStore

from .common import (
    DEFAULT_OPTIONS,
    ENTRY_ID,
    LEGACY_OPTIONS,
    MX1,
    NHK,
    NHK2,
    PROGRAMS,
    create_entry,
    load_fixture,
    mock_mirakurun,
    setup_integration,
)

LOGGER = "custom_components.mirakurun"


async def test_setup_and_unload(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    data = config_entry.runtime_data
    broadcasts = data.services.data.broadcasts
    assert [b.main.service_id for b in broadcasts] == [1024, 23608, 23610]
    assert [s.service_id for s in broadcasts[0].subs] == [1025]
    assert len(data.status.data.tuners) == 3
    assert data.version.data.latest == "4.1.5"
    nhk = data.programs.data[3273601024]
    assert [s.program.name for s in nhk.main] == ["ニュース", "天気", "ドキュメント"]
    assert [s.program.name for s in nhk.subs[0][1]][1] == "国会中継"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_without_channel_types(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    entry = create_entry({**DEFAULT_OPTIONS, CONF_CHANNEL_TYPES: []})
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.services.data.broadcasts == ()
    assert entry.runtime_data.programs.last_update_success
    assert entry.runtime_data.programs.data == {}


async def test_status_interval_option(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    entry = create_entry({**DEFAULT_OPTIONS, CONF_STATUS_INTERVAL: 60})
    await setup_integration(hass, entry)
    assert entry.runtime_data.status.update_interval == timedelta(seconds=60)


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

    renamed = [dict(p) for p in PROGRAMS[NHK]]
    renamed[1]["name"] = "気象情報"
    aioclient_mock.clear_requests()
    mock_mirakurun(
        aioclient_mock, programs={**PROGRAMS, NHK: renamed}, fail_programs={NHK2}
    )
    await programs.async_refresh()

    assert programs.last_update_success
    nhk = programs.data[3273601024]
    assert [s.program.name for s in nhk.main] == [
        "ニュース",
        "気象情報",
        "ドキュメント",
    ]
    assert nhk.subs[0][1] == before


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


async def test_program_failure_without_previous_data_is_logged_plainly(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_mirakurun(aioclient_mock, fail_programs={NHK2})
    await setup_integration(hass, config_entry)

    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == LOGGER
    ]
    assert len(warnings) == 1
    assert warnings[0].startswith("Failed to fetch programs for ＮＨＫ総合２・東京: ")
    assert "keeping previous data" not in warnings[0]


async def test_total_program_failure_logs_no_per_service_messages(
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
    mock_mirakurun(aioclient_mock, fail_programs=set(PROGRAMS))
    await programs.async_refresh()
    await programs.async_refresh()
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await programs.async_refresh()

    # The coordinator itself reports the outage; per-service messages would
    # repeat on every refresh while everything fails.
    assert not [
        r
        for r in caplog.records
        if r.name == LOGGER and " programs for " in r.getMessage()
    ]


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


async def test_classification_is_saved(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert await ClassificationStore(hass, ENTRY_ID).async_load() == {
        3273601025: True,
        3239123610: False,
    }


async def test_saved_classification_used_when_channel_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    await ClassificationStore(hass, ENTRY_ID).async_save({3239123610: True})
    mock_mirakurun(aioclient_mock, fail_programs={MX1})
    await setup_integration(hass, config_entry)
    broadcasts = config_entry.runtime_data.services.data.broadcasts
    mx1 = next(b for b in broadcasts if b.main.service_id == 23608)
    assert [s.service_id for s in mx1.subs] == [23610]


async def test_empty_service_list_keeps_broadcasts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=[])
    await services.async_refresh()

    assert not services.last_update_success
    assert len(services.data.broadcasts) == 3
    # Mirakurun is probably refilling its services; look again soon.
    assert services.update_interval == SERVICE_RECHECK_INTERVAL


async def test_vanished_selected_type_keeps_broadcasts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services

    aioclient_mock.clear_requests()
    cs_only = [s for s in load_fixture("services.json") if s["channel"]["type"] == "CS"]
    mock_mirakurun(aioclient_mock, services=cs_only)
    await services.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert not services.last_update_success
    assert len(services.data.broadcasts) == 3
    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{ENTRY_ID}_broadcast_3273601024"), config_entry.entry_id
    )
    assert services.update_interval == SERVICE_RECHECK_INTERVAL


async def test_selected_type_without_broadcasts_is_not_missing(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    entry = create_entry({**DEFAULT_OPTIONS, CONF_CHANNEL_TYPES: ["GR", "BS"]})
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    services = entry.runtime_data.services
    await services.async_refresh()
    assert services.last_update_success


async def test_server_device_follows_mirakurun_version(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    server = device_registry.async_get_device_by_identifier(
        (DOMAIN, ENTRY_ID), config_entry.entry_id
    )
    assert server is not None
    assert server.sw_version == "4.0.0-beta.18"

    aioclient_mock.clear_requests()
    mock_mirakurun(
        aioclient_mock, status={**load_fixture("status.json"), "version": "4.1.0"}
    )
    await config_entry.runtime_data.status.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    server = device_registry.async_get(server.id)
    assert server is not None
    assert server.sw_version == "4.1.0"


async def test_remove_device_while_not_loaded(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    mock_mirakurun(aioclient_mock, fail_services=True)
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{ENTRY_ID}_broadcast_999")},
    )
    assert not await async_remove_config_entry_device(hass, config_entry, device)


async def test_migrates_legacy_options(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    entry = create_entry(LEGACY_OPTIONS, minor_version=1)
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 3
    assert entry.options == {**DEFAULT_OPTIONS, CONF_STATUS_INTERVAL: 45}
    assert entry.options[CONF_SERVICE_INTERVAL] == DEFAULT_SERVICE_INTERVAL
    stored = await ClassificationStore(hass, ENTRY_ID).async_load()
    assert stored[3273601025] is True


async def test_migrates_legacy_options_without_intervals(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    legacy = {
        key: value
        for key, value in LEGACY_OPTIONS.items()
        if key not in (CONF_STATUS_INTERVAL, CONF_PROGRAM_INTERVAL)
    }
    entry = create_entry(legacy, minor_version=1)
    await setup_integration(hass, entry)
    assert entry.options == DEFAULT_OPTIONS


@pytest.mark.parametrize(("old", "new"), [(24, DEFAULT_SERVICE_INTERVAL), (6, 6)])
async def test_migrates_service_interval(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, old: int, new: int
) -> None:
    # The interval used to cover full regroups (default 24 h); it now sets the
    # light check, so the old default moves to the new one.
    entry = create_entry({**DEFAULT_OPTIONS, CONF_SERVICE_INTERVAL: old}, 2)
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 3
    assert entry.options == {**DEFAULT_OPTIONS, CONF_SERVICE_INTERVAL: new}


async def test_newer_major_version_is_not_migrated(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=dict(create_entry().data),
        options=DEFAULT_OPTIONS,
        version=2,
    )
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_remove_entry_removes_classification(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await ClassificationStore(hass, ENTRY_ID).async_load() == {}


DEFAULT_SERVICE_UPDATE = timedelta(hours=DEFAULT_SERVICE_INTERVAL)


async def test_vanished_broadcast_is_rechecked_soon(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services
    assert services.update_interval == DEFAULT_SERVICE_UPDATE

    # A broadcast missing from one refresh (e.g. while Mirakurun refills its
    # services) is looked for again soon instead of after a full interval.
    without_mx2 = [s for s in load_fixture("services.json") if s["id"] != 3239123610]
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=without_mx2)
    await services.async_refresh()
    assert services.update_interval == SERVICE_RECHECK_INTERVAL

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await services.async_refresh()
    assert services.update_interval == DEFAULT_SERVICE_UPDATE


async def test_broadcast_missing_at_setup_is_rechecked_soon(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{ENTRY_ID}_broadcast_999")},
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.runtime_data.services.update_interval == (
        SERVICE_RECHECK_INTERVAL
    )


async def test_setup_without_missing_broadcasts_keeps_interval(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{ENTRY_ID}_broadcast_3273601024")},
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.runtime_data.services.update_interval == (
        DEFAULT_SERVICE_UPDATE
    )
