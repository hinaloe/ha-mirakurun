"""Tests for broadcast entities."""

from datetime import datetime

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import CONF_PROGRAM_INTERVAL, DOMAIN

from .common import (
    DEFAULT_OPTIONS,
    ENTRY_ID,
    NHK,
    NHK2,
    PROGRAMS,
    at,
    create_entry,
    entity_id,
    make_program,
    mock_mirakurun,
    setup_integration,
)

NHK_KEY = f"{ENTRY_ID}_broadcast_3273601024"
MX1_KEY = f"{ENTRY_ID}_broadcast_3239123608"


async def _move_to(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: datetime
) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done(wait_background_tasks=True)


def _program_fetches(aioclient_mock: AiohttpClientMocker) -> int:
    return sum("/api/programs" in str(call[1]) for call in aioclient_mock.mock_calls)


async def _setup_without_boundary_polling(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Set up with a program interval that never fires on a boundary."""
    mock_mirakurun(aioclient_mock)
    entry = create_entry({**DEFAULT_OPTIONS, CONF_PROGRAM_INTERVAL: 180})
    await setup_integration(hass, entry)


async def test_program_sensors(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)

    current = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_current_program"))
    assert current.state == "ニュース"
    assert current.attributes["start"] == at(11).isoformat()
    assert current.attributes["end"] == at(12, 30).isoformat()
    assert current.attributes["description"] == "ニュース description"
    assert current.attributes["genre"] == "news"
    assert current.attributes["genre_detail"] == 1

    upcoming = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_next_program"))
    assert upcoming.state == "天気"
    assert upcoming.attributes["start"] == at(12, 30).isoformat()


async def test_program_sensors_follow_transitions(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    frozen_now: FrozenDateTimeFactory,
) -> None:
    await _setup_without_boundary_polling(hass, aioclient_mock)
    fetches = _program_fetches(aioclient_mock)
    await _move_to(hass, frozen_now, at(12, 30))
    assert _program_fetches(aioclient_mock) == fetches

    current = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_current_program"))
    assert current.state == "天気"
    upcoming = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_next_program"))
    assert upcoming.state == "ドキュメント"


async def test_subchannel_split(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    frozen_now: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
) -> None:
    await _setup_without_boundary_polling(hass, aioclient_mock)
    fetches = _program_fetches(aioclient_mock)
    split_id = entity_id(hass, "binary_sensor", f"{NHK_KEY}_subchannel_split")
    assert hass.states.get(split_id).state == STATE_OFF
    assert hass.states.get(split_id).attributes["subchannels"] == []

    await _move_to(hass, frozen_now, at(12, 30))
    assert _program_fetches(aioclient_mock) == fetches
    state = hass.states.get(split_id)
    assert state.state == STATE_ON
    assert state.attributes["subchannels"] == [
        {
            "service": "ＮＨＫ総合２・東京",
            "program": "国会中継",
            "end": at(13).isoformat(),
        }
    ]

    await _move_to(hass, frozen_now, at(13))
    assert hass.states.get(split_id).state == STATE_OFF
    assert _program_fetches(aioclient_mock) == fetches

    assert (
        entity_registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{MX1_KEY}_subchannel_split"
        )
        is None
    )


async def test_calendar(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    calendar_id = entity_id(hass, "calendar", f"{NHK_KEY}_schedule")

    state = hass.states.get(calendar_id)
    assert state.state == STATE_ON
    assert state.attributes["message"] == "ニュース"

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": calendar_id,
            "start_date_time": at(10),
            "end_date_time": at(15),
        },
        blocking=True,
        return_response=True,
    )
    summaries = [event["summary"] for event in response[calendar_id]["events"]]
    assert summaries == [
        "ニュース",
        "天気",
        "[ＮＨＫ総合２・東京] 国会中継",
        "ドキュメント",
    ]

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": calendar_id,
            "start_date_time": at(13, 30),
            "end_date_time": at(15),
        },
        blocking=True,
        return_response=True,
    )
    assert [e["summary"] for e in response[calendar_id]["events"]] == ["ドキュメント"]


async def test_calendar_current_event_prefers_main_service(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    sub_special = make_program(NHK2, 30, at(10, 30), 120, "副音声特番", genre=0)
    mock_mirakurun(
        aioclient_mock, programs={**PROGRAMS, NHK2: [sub_special, *PROGRAMS[NHK2][1:]]}
    )
    await setup_integration(hass, config_entry)
    calendar_id = entity_id(hass, "calendar", f"{NHK_KEY}_schedule")

    # The subchannel program started before the main one but must not win
    state = hass.states.get(calendar_id)
    assert state.attributes["message"] == "ニュース"


async def test_broadcast_without_programs(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock, programs={**PROGRAMS, NHK: []})
    await setup_integration(hass, config_entry)

    current = hass.states.get(entity_id(hass, "sensor", f"{NHK_KEY}_current_program"))
    assert current.state == STATE_UNKNOWN
    calendar = hass.states.get(entity_id(hass, "calendar", f"{NHK_KEY}_schedule"))
    # NHK2 still airs its own program at 12:30, but nothing is on air now
    assert calendar.state == STATE_OFF
