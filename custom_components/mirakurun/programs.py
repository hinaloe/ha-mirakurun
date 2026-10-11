"""Schedule helpers built on top of Mirakurun programs."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Program

FALLBACK_DURATION = timedelta(hours=1)

# ARIB STD-B10 content_nibble_level_1
GENRE_KEYS: dict[int, str] = {
    0: "news",
    1: "sports",
    2: "information",
    3: "drama",
    4: "music",
    5: "variety",
    6: "movie",
    7: "anime",
    8: "documentary",
    9: "theater",
    10: "hobby",
    11: "welfare",
    14: "extension",
    15: "other",
}


@dataclass(frozen=True, slots=True)
class ScheduledProgram:
    """A program with a resolved end time."""

    program: Program
    start: datetime
    end: datetime


type Schedule = tuple[ScheduledProgram, ...]


def build_schedule(programs: Iterable[Program]) -> Schedule:
    """Sort programs and resolve end times, including unknown durations."""
    ordered = sorted(programs, key=lambda program: program.start)
    result: list[ScheduledProgram] = []
    for index, program in enumerate(ordered):
        if program.has_known_duration:
            end = program.start + timedelta(milliseconds=program.duration_ms)
        else:
            following = next(
                (p.start for p in ordered[index + 1 :] if p.start > program.start),
                None,
            )
            end = (
                following
                if following is not None
                else program.start + FALLBACK_DURATION
            )
        result.append(ScheduledProgram(program, program.start, end))
    return tuple(result)


def current_program(
    schedule: Sequence[ScheduledProgram], now: datetime
) -> ScheduledProgram | None:
    """Return the program on air at ``now``."""
    return next((item for item in schedule if item.start <= now < item.end), None)


def next_program(
    schedule: Sequence[ScheduledProgram], now: datetime
) -> ScheduledProgram | None:
    """Return the first program starting after ``now``."""
    return next((item for item in schedule if item.start > now), None)


def programs_between(
    schedule: Sequence[ScheduledProgram], start: datetime, end: datetime
) -> list[ScheduledProgram]:
    """Return programs overlapping the given window."""
    return [item for item in schedule if item.end > start and item.start < end]


def next_transition(
    schedule: Sequence[ScheduledProgram], now: datetime
) -> datetime | None:
    """Return the next time a program starts or ends."""
    return min(
        (t for item in schedule for t in (item.start, item.end) if t > now),
        default=None,
    )


def genre_key(lv1: int | None) -> str | None:
    """Return the translation key for an ARIB top level genre."""
    return None if lv1 is None else GENRE_KEYS.get(lv1)
