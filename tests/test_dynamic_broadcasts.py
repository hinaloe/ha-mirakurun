"""Tests for following broadcasts added to and removed from Mirakurun."""

import asyncio
from collections.abc import Collection
from datetime import timedelta
from typing import Any
from unittest.mock import patch

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

from custom_components.mirakurun.api import MirakurunClient
from custom_components.mirakurun.broadcast import discover
from custom_components.mirakurun.const import (
    CONF_CHANNEL_TYPES,
    DEFAULT_SERVICE_INTERVAL,
    DOMAIN,
    PROGRAM_FETCH_CONCURRENCY,
    REGROUP_INTERVAL,
    SERVICE_RECHECK_INTERVAL,
    UNMEASURED_RETRY_WINDOW,
)
from custom_components.mirakurun.models import Program
from custom_components.mirakurun.store import ClassificationStore

from .common import (
    DEFAULT_OPTIONS,
    ENTRY_ID,
    MX1,
    PROGRAMS,
    at,
    create_entry,
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


def _calls(aioclient_mock: AiohttpClientMocker, path: str) -> int:
    return sum(
        1
        for _method, url, _data, _headers in aioclient_mock.mock_calls
        if url.path == path
    )


def _discover_spy() -> Any:
    """Count regroups: the coordinator calls discover() only to regroup."""
    return patch("custom_components.mirakurun.coordinator.discover", wraps=discover)


async def test_light_check_skips_regroup_when_unchanged(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services
    before = services.data

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    with _discover_spy() as spy:
        await _refresh_services(hass, config_entry)

    assert services.last_update_success
    assert _calls(aioclient_mock, "/api/services") == 1
    assert spy.call_count == 0
    assert services.data is before


async def test_changed_service_list_regroups(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services

    aioclient_mock.clear_requests()
    mock_mirakurun(
        aioclient_mock, services=_services(add=[FUJI_SERVICE]), programs=FUJI_PROGRAMS
    )
    with _discover_spy() as spy:
        await _refresh_services(hass, config_entry)

    assert spy.call_count == 1
    # The service list fetched for the check is reused for the regroup.
    assert _calls(aioclient_mock, "/api/services") == 1
    assert 3274101056 in {b.main.id for b in services.data.broadcasts}


async def test_unchanged_service_list_regroups_daily(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services

    with _discover_spy() as spy:
        frozen_now.tick(REGROUP_INTERVAL - timedelta(minutes=1))
        aioclient_mock.clear_requests()
        mock_mirakurun(aioclient_mock)
        await _refresh_services(hass, config_entry)
        assert spy.call_count == 0

        frozen_now.tick(timedelta(minutes=1))
        aioclient_mock.clear_requests()
        mock_mirakurun(aioclient_mock)
        await _refresh_services(hass, config_entry)
        assert spy.call_count == 1
    assert services.last_update_success


async def test_service_of_unselected_type_does_not_regroup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services
    before = services.data
    notified: list[None] = []
    config_entry.async_on_unload(
        services.async_add_listener(lambda: notified.append(None))
    )
    # A service on an existing unselected type (CS) and one of a type the
    # server did not have before (BS).
    extra = [
        {
            **FUJI_SERVICE,
            "id": 700300,
            "serviceId": 300,
            "networkId": 7,
            "channel": {"type": "CS", "channel": "CS10"},
        },
        {
            **FUJI_SERVICE,
            "id": 400101,
            "serviceId": 101,
            "networkId": 4,
            "channel": {"type": "BS", "channel": "BS15_0"},
        },
    ]

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, services=_services(add=extra))
    with _discover_spy() as spy:
        await _refresh_services(hass, config_entry)

    assert services.last_update_success
    assert spy.call_count == 0
    assert services.data is before
    assert notified == []


async def test_guards_fire_on_light_check(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services
    before = services.data

    for payload in ([], [s for s in _services() if s["channel"]["type"] == "CS"]):
        services.update_interval = timedelta(hours=1)
        aioclient_mock.clear_requests()
        mock_mirakurun(aioclient_mock, services=payload)
        with _discover_spy() as spy:
            await _refresh_services(hass, config_entry)

        assert not services.last_update_success
        assert spy.call_count == 0
        assert services.data is before
        assert services.update_interval == SERVICE_RECHECK_INTERVAL


async def test_unmeasured_channel_is_regrouped_soon(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    # MX has no programs yet at setup (e.g. right after Mirakurun refilled its
    # services), so that channel is not measured.
    mock_mirakurun(aioclient_mock, programs={**PROGRAMS, MX1: []})
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services
    assert services.update_interval == SERVICE_RECHECK_INTERVAL

    # The unchanged lineup is regrouped again, now measuring every channel.
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    with _discover_spy() as spy:
        await _refresh_services(hass, config_entry)
    assert spy.call_count == 1
    assert services.update_interval == REGULAR_INTERVAL
    stored = await ClassificationStore(hass, ENTRY_ID).async_load()
    assert stored[3239123610] is False

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    with _discover_spy() as spy:
        await _refresh_services(hass, config_entry)
    assert spy.call_count == 0


REGULAR_INTERVAL = timedelta(hours=DEFAULT_SERVICE_INTERVAL)
MX_UNMEASURED = {**PROGRAMS, MX1: []}


async def _refresh_counting(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry: MockConfigEntry,
    **mock: Any,
) -> int:
    """Refresh the services and return how many regroups it ran."""
    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock, **mock)
    with _discover_spy() as spy:
        await _refresh_services(hass, entry)
    return spy.call_count


async def test_unmeasured_channel_keeps_retrying_within_window(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock, programs=MX_UNMEASURED)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services

    frozen_now.tick(SERVICE_RECHECK_INTERVAL)
    regroups = await _refresh_counting(
        hass, aioclient_mock, config_entry, programs=MX_UNMEASURED
    )
    assert regroups == 1
    assert services.update_interval == SERVICE_RECHECK_INTERVAL


async def test_unmeasured_retry_ends_after_window(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock, programs=MX_UNMEASURED)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services

    # A channel that stays unmeasured falls back to the daily regroup.
    frozen_now.tick(UNMEASURED_RETRY_WINDOW)
    regroups = await _refresh_counting(
        hass, aioclient_mock, config_entry, programs=MX_UNMEASURED
    )
    assert regroups == 1
    assert services.update_interval == REGULAR_INTERVAL

    frozen_now.tick(REGROUP_INTERVAL - timedelta(minutes=1))
    regroups = await _refresh_counting(
        hass, aioclient_mock, config_entry, programs=MX_UNMEASURED
    )
    assert regroups == 0

    frozen_now.tick(timedelta(minutes=1))
    regroups = await _refresh_counting(
        hass, aioclient_mock, config_entry, programs=MX_UNMEASURED
    )
    assert regroups == 1


async def test_lineup_change_restarts_unmeasured_retry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    mock_mirakurun(aioclient_mock, programs=MX_UNMEASURED)
    await setup_integration(hass, config_entry)
    services = config_entry.runtime_data.services
    frozen_now.tick(UNMEASURED_RETRY_WINDOW)
    await _refresh_counting(hass, aioclient_mock, config_entry, programs=MX_UNMEASURED)
    assert services.update_interval == REGULAR_INTERVAL

    regroups = await _refresh_counting(
        hass,
        aioclient_mock,
        config_entry,
        services=_services(add=[FUJI_SERVICE]),
        programs={**FUJI_PROGRAMS, MX1: []},
    )
    assert regroups == 1
    assert services.update_interval == SERVICE_RECHECK_INTERVAL


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


# NHK main programs that share nothing with NHK2, so NHK2 splits off.
NHK_ALONE = {
    **PROGRAMS,
    (32736, 1024): [
        {k: v for k, v in p.items() if k != "relatedItems"}
        for p in PROGRAMS[(32736, 1024)]
    ],
}
NHK_SPLIT_ID = f"{NHK_KEY}_subchannel_split"


async def test_split_sensor_follows_regrouping(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    split_entity = entity_id(hass, "binary_sensor", NHK_SPLIT_ID)

    # A changed service list triggers the regroup.
    aioclient_mock.clear_requests()
    mock_mirakurun(
        aioclient_mock,
        services=_services(add=[FUJI_SERVICE]),
        programs={**NHK_ALONE, FUJI: FUJI_PROGRAMS[FUJI]},
    )
    await _refresh_services(hass, config_entry)

    assert (
        entity_registry.async_get_entity_id("binary_sensor", DOMAIN, NHK_SPLIT_ID)
        is None
    )
    assert hass.states.get(split_entity) is None

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    await _refresh_services(hass, config_entry)

    assert hass.states.get(entity_id(hass, "binary_sensor", NHK_SPLIT_ID)) is not None


async def test_leftover_split_sensor_removed_at_setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "binary_sensor", DOMAIN, NHK_SPLIT_ID, config_entry=config_entry
    )
    mock_mirakurun(aioclient_mock, services=_services(drop={3273601025}))
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert (
        entity_registry.async_get_entity_id("binary_sensor", DOMAIN, NHK_SPLIT_ID)
        is None
    )


async def test_program_fetches_are_bounded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    in_flight = 0
    peak = 0
    real_get_programs = MirakurunClient.get_programs

    async def counting(
        self: MirakurunClient, network_id: int, service_id: int
    ) -> list[Program]:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0)
            return await real_get_programs(self, network_id, service_id)
        finally:
            in_flight -= 1

    mock_mirakurun(aioclient_mock)
    entry = create_entry({**DEFAULT_OPTIONS, CONF_CHANNEL_TYPES: ["GR", "CS"]})
    with patch.object(MirakurunClient, "get_programs", counting):
        await setup_integration(hass, entry)

    schedules = entry.runtime_data.programs.data
    assert len(schedules) == 5
    targets = [
        s for b in schedules.values() for s in (b.broadcast.main, *b.broadcast.subs)
    ]
    assert len(targets) > PROGRAM_FETCH_CONCURRENCY
    assert 1 < peak <= PROGRAM_FETCH_CONCURRENCY
