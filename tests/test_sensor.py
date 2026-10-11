"""Tests for Mirakurun sensors."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun import async_remove_config_entry_device
from custom_components.mirakurun.const import DOMAIN

from .common import (
    ENTRY_ID,
    PROGRAMS,
    entity_id,
    load_fixture,
    mock_mirakurun,
    setup_integration,
)


def _state(hass: HomeAssistant, unique_id: str) -> str:
    state = hass.states.get(entity_id(hass, "sensor", unique_id))
    assert state is not None
    return state.state


async def _refresh_status(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_server_sensors(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert _state(hass, f"{ENTRY_ID}_server_tuners_in_use") == "1"
    assert _state(hass, f"{ENTRY_ID}_server_tuners_free") == "1"
    assert _state(hass, f"{ENTRY_ID}_server_streams") == "2"
    assert _state(hass, f"{ENTRY_ID}_server_tuner_respawns") == "1747"


async def test_diagnostic_sensors_disabled_by_default(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    for key in (
        "stored_events",
        "uncaught_exceptions",
        "unhandled_rejections",
        "buffer_overflows",
        "decoder_respawns",
    ):
        entry = entity_registry.async_get(
            entity_id(hass, "sensor", f"{ENTRY_ID}_server_{key}")
        )
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_tuner_sensors(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert _state(hass, f"{ENTRY_ID}_tuner_12_state") == "in_use"
    assert _state(hass, f"{ENTRY_ID}_tuner_12_channel") == "ＢＳ朝日"
    assert _state(hass, f"{ENTRY_ID}_tuner_12_user") == "EPGStation-recorder"
    user = hass.states.get(entity_id(hass, "sensor", f"{ENTRY_ID}_tuner_12_user"))
    assert user.attributes["users"] == [
        {"id": "Mirakurun:getEPG()", "priority": -1},
        {"id": "EPGStation-recorder", "priority": 2},
    ]
    assert _state(hass, f"{ENTRY_ID}_tuner_14_state") == "free"
    assert _state(hass, f"{ENTRY_ID}_tuner_14_channel") == STATE_UNKNOWN
    assert _state(hass, f"{ENTRY_ID}_tuner_15_state") == "fault"


async def test_disabled_tuner_state(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    tuners = load_fixture("tuners.json")
    tuners[1]["isAvailable"] = False
    mock_mirakurun(aioclient_mock, tuners=tuners)
    await setup_integration(hass, config_entry)
    assert _state(hass, f"{ENTRY_ID}_tuner_14_state") == "disabled"


async def test_new_tuner_added_dynamically(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    tuners = load_fixture("tuners.json")
    tuners.append({**tuners[1], "index": 16, "name": "PX-T3"})
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, tuners=tuners)
    await _refresh_status(hass, frozen_now)

    assert _state(hass, f"{ENTRY_ID}_tuner_16_state") == "free"


async def test_removed_tuner_becomes_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, tuners=load_fixture("tuners.json")[:2])
    await _refresh_status(hass, frozen_now)

    assert _state(hass, f"{ENTRY_ID}_tuner_15_state") == STATE_UNAVAILABLE
    assert _state(hass, f"{ENTRY_ID}_tuner_14_state") == "free"


async def test_briefly_missing_tuner_keeps_device_and_entities(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, tuners=load_fixture("tuners.json")[:2])
    await _refresh_status(hass, frozen_now)
    # A broadcast list change while the tuner is missing must not remove its
    # device: tuners are only cleaned up at setup.
    fuji = {**load_fixture("services.json")[0], "id": 3274101056, "serviceId": 1056}
    aioclient_mock.clear_requests()
    mock_mirakurun(
        aioclient_mock,
        tuners=load_fixture("tuners.json")[:2],
        services=[*load_fixture("services.json"), fuji],
        programs={**PROGRAMS, (32736, 1056): []},
    )
    await config_entry.runtime_data.services.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{ENTRY_ID}_tuner_15"), ENTRY_ID
    )
    assert _state(hass, f"{ENTRY_ID}_tuner_15_state") == STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await _refresh_status(hass, frozen_now)

    assert _state(hass, f"{ENTRY_ID}_tuner_15_state") == "fault"
    assert "does not generate unique IDs" not in caplog.text


async def test_tuner_missing_from_one_poll_is_not_added_twice(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, tuners=load_fixture("tuners.json")[:2])
    await _refresh_status(hass, frozen_now)
    assert _state(hass, f"{ENTRY_ID}_tuner_15_state") == STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await _refresh_status(hass, frozen_now)

    assert _state(hass, f"{ENTRY_ID}_tuner_15_state") == "fault"
    assert "does not generate unique IDs" not in caplog.text


async def test_manually_deleted_tuner_stays_deleted(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, tuners=load_fixture("tuners.json")[:2])
    await _refresh_status(hass, frozen_now)
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{ENTRY_ID}_tuner_15"), ENTRY_ID
    )
    assert device is not None
    assert await async_remove_config_entry_device(hass, config_entry, device)
    device_registry.async_remove_device(device.id)
    await hass.async_block_till_done()

    # A tuner the user deleted does not reappear on its own; a reload brings
    # it back.
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await _refresh_status(hass, frozen_now)

    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{ENTRY_ID}_tuner_15_state"
        )
        is None
    )


async def test_status_failure_makes_entities_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, fail_status=True)
    await _refresh_status(hass, frozen_now)

    assert _state(hass, f"{ENTRY_ID}_server_tuners_in_use") == STATE_UNAVAILABLE
    assert _state(hass, f"{ENTRY_ID}_tuner_12_state") == STATE_UNAVAILABLE


async def test_tuner_device_linked_to_server(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    server = device_registry.async_get_device_by_identifier(
        (DOMAIN, ENTRY_ID), ENTRY_ID
    )
    tuner = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{ENTRY_ID}_tuner_12"), ENTRY_ID
    )
    assert server is not None
    assert tuner is not None
    assert tuner.via_device_id == server.id


async def test_broadcasts_are_service_devices(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    broadcast = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{ENTRY_ID}_broadcast_3273601024"), ENTRY_ID
    )
    server = device_registry.async_get_device_by_identifier(
        (DOMAIN, ENTRY_ID), ENTRY_ID
    )
    tuner = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{ENTRY_ID}_tuner_12"), ENTRY_ID
    )
    assert broadcast is not None
    assert server is not None
    assert tuner is not None
    # Broadcasts are not physical devices; HA lists services separately.
    assert broadcast.entry_type is dr.DeviceEntryType.SERVICE
    assert server.entry_type is None
    assert tuner.entry_type is None
