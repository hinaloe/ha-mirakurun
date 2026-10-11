"""Tests for broadcast grouping."""

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.api import MirakurunClient
from custom_components.mirakurun.broadcast import (
    Broadcast,
    classification_from_option_map,
    classify_channel,
    detect_splits,
    discover,
    distinct_sub_programs,
    group_by_channel,
)
from custom_components.mirakurun.models import Program, Service
from custom_components.mirakurun.programs import build_schedule

from .common import (
    BASE_URL,
    MX1,
    NHK,
    NHK2,
    NOW,
    PROGRAMS,
    at,
    load_fixture,
    make_program,
    mock_mirakurun,
)

LOGGER = "custom_components.mirakurun"
SERVICES = [Service.from_dict(s) for s in load_fixture("services.json")]
BY_SID = {s.service_id: s for s in SERVICES}
NHK_SVC, NHK2_SVC = BY_SID[1024], BY_SID[1025]
MX1_SVC, MX2_SVC = BY_SID[23608], BY_SID[23610]
SHOP_SVC, TOEI_SVC = BY_SID[55], BY_SID[218]


def _programs(key: tuple[int, int]) -> list[Program]:
    return [Program.from_dict(p) for p in PROGRAMS[key]]


def test_group_by_channel() -> None:
    groups = group_by_channel(SERVICES)
    assert [[s.service_id for s in g] for g in groups] == [
        [1024, 1025],
        [23608, 23610],
        [55, 218],
    ]


def test_classify_dependent_subchannel() -> None:
    result = classify_channel([NHK_SVC, NHK2_SVC], _programs(NHK), NOW)
    assert result == [Broadcast(NHK_SVC, (NHK2_SVC,))]


def test_classify_independent_subchannel() -> None:
    result = classify_channel([MX1_SVC, MX2_SVC], _programs(MX1), NOW)
    assert result == [Broadcast(MX1_SVC), Broadcast(MX2_SVC)]


def test_classify_cohabiting_channels() -> None:
    result = classify_channel([SHOP_SVC, TOEI_SVC], [], NOW)
    assert result == [Broadcast(SHOP_SVC), Broadcast(TOEI_SVC)]


def test_classify_failure_makes_everything_independent() -> None:
    result = classify_channel([NHK_SVC, NHK2_SVC], None, NOW)
    assert result == [Broadcast(NHK_SVC), Broadcast(NHK2_SVC)]


def test_classify_ignores_past_programs() -> None:
    past_shared = [
        Program.from_dict(make_program(NHK, 1, at(9), 60, "過去", shared=(1025,))),
        Program.from_dict(make_program(NHK, 2, at(12), 60, "現在")),
    ]
    result = classify_channel([NHK_SVC, NHK2_SVC], past_shared, NOW)
    assert result == [Broadcast(NHK_SVC), Broadcast(NHK2_SVC)]


def test_classify_threshold_is_inclusive() -> None:
    half = [
        Program.from_dict(make_program(NHK, 1, at(12), 60, "共有", shared=(1025,))),
        Program.from_dict(make_program(NHK, 2, at(13), 60, "単独")),
    ]
    result = classify_channel([NHK_SVC, NHK2_SVC], half, NOW)
    assert result == [Broadcast(NHK_SVC, (NHK2_SVC,))]


def test_distinct_sub_programs() -> None:
    main = build_schedule(_programs(NHK))
    sub = build_schedule(_programs(NHK2))
    assert [s.program.name for s in distinct_sub_programs(NHK_SVC, main, sub)] == [
        "国会中継"
    ]


def test_detect_splits() -> None:
    main = build_schedule(_programs(NHK))
    subs = [(NHK2_SVC, build_schedule(_programs(NHK2)))]
    assert detect_splits(NHK_SVC, main, subs, at(12)) == []
    (split,) = detect_splits(NHK_SVC, main, subs, at(12, 30))
    assert split.service == NHK2_SVC
    assert split.program.program.name == "国会中継"
    assert detect_splits(NHK_SVC, main, subs, at(13)) == []
    assert detect_splits(NHK_SVC, main, [(NHK2_SVC, ())], at(12, 30)) == []


def _ratio_programs(total: int, shared: int) -> list[Program]:
    """Main programs of which the first ``shared`` list NHK2 as shared."""
    return [
        Program.from_dict(
            make_program(
                NHK,
                i + 1,
                NOW + timedelta(minutes=10 * i),
                10,
                f"番組{i}",
                shared=(1025,) if i < shared else (),
            )
        )
        for i in range(total)
    ]


@pytest.mark.parametrize(
    ("shared", "previous", "dependent"),
    [
        (10, None, True),  # 0.50, first classification
        (9, None, False),  # 0.45, first classification
        (8, True, True),  # 0.40, stays dependent
        (7, True, False),  # 0.35, splits off
        (11, False, False),  # 0.55, stays independent
        (12, False, True),  # 0.60, joins
    ],
)
def test_classify_hysteresis(
    shared: int, previous: bool | None, dependent: bool
) -> None:
    prior = {} if previous is None else {NHK2_SVC.id: previous}
    result = classify_channel(
        [NHK_SVC, NHK2_SVC], _ratio_programs(20, shared), NOW, prior
    )
    if dependent:
        assert result == [Broadcast(NHK_SVC, (NHK2_SVC,))]
    else:
        assert result == [Broadcast(NHK_SVC), Broadcast(NHK2_SVC)]


def test_classify_failure_keeps_previous() -> None:
    result = classify_channel([NHK_SVC, NHK2_SVC], None, NOW, {NHK2_SVC.id: True})
    assert result == [Broadcast(NHK_SVC, (NHK2_SVC,))]


async def test_discover_filters_types(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, ["GR"], {})
    assert result.broadcasts == (
        Broadcast(NHK_SVC, (NHK2_SVC,)),
        Broadcast(MX1_SVC),
        Broadcast(MX2_SVC),
    )
    assert result.classification == {NHK2_SVC.id: True, MX2_SVC.id: False}
    assert result.unmeasured == frozenset()


async def test_discover_uses_given_services(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, ["GR"], {}, services=SERVICES[:3])
    assert result.broadcasts == (Broadcast(NHK_SVC, (NHK2_SVC,)),)
    assert not any(url.path == "/api/services" for _, url, _, _ in mirakurun.mock_calls)


async def test_discover_without_types(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, [], {})
    assert result.broadcasts == ()
    assert result.classification == {}
    # Channels of unselected types are not measured, but not missed either.
    assert result.unmeasured == frozenset()


async def test_discover_uses_previous_on_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_mirakurun(aioclient_mock, fail_programs={NHK})
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, ["GR"], {NHK2_SVC.id: True})
    assert result.broadcasts[0] == Broadcast(NHK_SVC, (NHK2_SVC,))
    # The prior stays in the coordinator's store; it is not re-reported.
    assert NHK2_SVC.id not in result.classification


def _debug_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.DEBUG and r.name == LOGGER
    ]


async def test_discover_does_not_record_failed_channel(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    mock_mirakurun(aioclient_mock, fail_programs={NHK})
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, ["GR"], {})
    assert result.broadcasts[:2] == (Broadcast(NHK_SVC), Broadcast(NHK2_SVC))
    assert NHK2_SVC.id not in result.classification
    assert result.classification == {MX2_SVC.id: False}
    assert result.unmeasured == frozenset({("GR", "27")})
    messages = _debug_messages(caplog)
    assert len(messages) == 1
    assert "GR 27" in messages[0]
    assert "programs could not be fetched" in messages[0]


async def test_discover_does_not_record_channel_without_upcoming(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    mock_mirakurun(aioclient_mock, programs={**PROGRAMS, MX1: []})
    client = MirakurunClient(async_get_clientsession(hass), BASE_URL)
    result = await discover(client, NOW, ["GR"], {})
    assert MX2_SVC.id not in result.classification
    assert result.classification == {NHK2_SVC.id: True}
    assert result.unmeasured == frozenset({("GR", "16")})
    messages = _debug_messages(caplog)
    assert len(messages) == 1
    assert "GR 16" in messages[0]
    assert "no upcoming programs" in messages[0]


def test_classification_from_option_map() -> None:
    assert classification_from_option_map(
        {"3273601024": [3273601025], "3239123608": []}
    ) == {3273601025: True}
