"""Tests for schedule helpers."""

from datetime import timedelta

from custom_components.mirakurun.models import Program
from custom_components.mirakurun.programs import (
    build_schedule,
    current_program,
    genre_key,
    next_program,
    next_transition,
)

from .common import NHK, PROGRAMS, at, make_program


def _programs(*payloads: dict) -> list[Program]:
    return [Program.from_dict(p) for p in payloads]


NHK_PROGRAMS = _programs(*PROGRAMS[NHK])


def test_known_durations() -> None:
    schedule = build_schedule(NHK_PROGRAMS)
    assert [(s.start, s.end) for s in schedule] == [
        (at(11), at(12, 30)),
        (at(12, 30), at(13)),
        (at(13), at(14)),
    ]


def test_input_is_sorted() -> None:
    schedule = build_schedule(reversed(NHK_PROGRAMS))
    assert [s.program.name for s in schedule] == ["ニュース", "天気", "ドキュメント"]


def test_unknown_duration_ends_at_next_program() -> None:
    schedule = build_schedule(
        _programs(
            make_program(NHK, 1, at(11), None, "延長あり"),
            make_program(NHK, 2, at(12, 15), 30, "次"),
        )
    )
    assert schedule[0].end == at(12, 15)


def test_unknown_duration_without_next_lasts_one_hour() -> None:
    schedule = build_schedule(_programs(make_program(NHK, 1, at(11), None, "最後")))
    assert schedule[0].end == at(11) + timedelta(hours=1)


def test_current_and_next_program() -> None:
    schedule = build_schedule(NHK_PROGRAMS)
    assert current_program(schedule, at(12)).program.name == "ニュース"
    assert next_program(schedule, at(12)).program.name == "天気"
    # start is inclusive, end is exclusive
    assert current_program(schedule, at(12, 30)).program.name == "天気"
    assert current_program(schedule, at(14)) is None
    assert next_program(schedule, at(13)) is None


def test_current_program_in_gap() -> None:
    schedule = build_schedule(
        _programs(
            make_program(NHK, 1, at(11), 30, "前"),
            make_program(NHK, 2, at(12), 30, "後"),
        )
    )
    assert current_program(schedule, at(11, 45)) is None
    assert next_program(schedule, at(11, 45)).program.name == "後"


def test_next_transition() -> None:
    schedule = build_schedule(NHK_PROGRAMS)
    assert next_transition(schedule, at(12)) == at(12, 30)
    assert next_transition(schedule, at(12, 30)) == at(13)
    assert next_transition(schedule, at(14)) is None
    assert next_transition((), at(12)) is None


def test_genre_key() -> None:
    assert genre_key(0) == "news"
    assert genre_key(7) == "anime"
    assert genre_key(15) == "other"
    assert genre_key(12) is None
    assert genre_key(None) is None
