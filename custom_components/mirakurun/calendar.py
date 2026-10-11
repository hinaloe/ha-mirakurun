# Copyright 2026 hinaloe
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Program guide calendars for Mirakurun."""

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .broadcast import Broadcast, distinct_sub_programs
from .coordinator import MirakurunConfigEntry, ProgramCoordinator
from .entity import MirakurunBroadcastEntity, async_add_broadcast_entities
from .programs import ScheduledProgram, current_program

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MirakurunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up program guide calendars."""
    programs = entry.runtime_data.programs
    async_add_broadcast_entities(
        entry,
        lambda broadcast: [MirakurunCalendar(programs, entry, broadcast)],
        async_add_entities,
    )


def _to_event(item: ScheduledProgram, prefix: str | None) -> CalendarEvent:
    summary = item.program.name or ""
    if prefix:
        summary = f"[{prefix}] {summary}"
    return CalendarEvent(
        start=item.start,
        end=item.end,
        summary=summary,
        description=item.program.description,
        uid=str(item.program.id),
    )


class MirakurunCalendar(MirakurunBroadcastEntity, CalendarEntity):
    """Programs of the main service plus distinct subchannel programs."""

    _attr_translation_key = "schedule"

    def __init__(
        self,
        coordinator: ProgramCoordinator,
        entry: MirakurunConfigEntry,
        broadcast: Broadcast,
    ) -> None:
        super().__init__(coordinator, entry, broadcast, "schedule")

    def _items(self) -> list[tuple[ScheduledProgram, str | None]]:
        schedule = self.schedule
        if schedule is None:
            return []
        items: list[tuple[ScheduledProgram, str | None]] = [
            (item, None) for item in schedule.main
        ]
        for service, sub_schedule in schedule.subs:
            items.extend(
                (item, service.name)
                for item in distinct_sub_programs(
                    self.broadcast.main, schedule.main, sub_schedule
                )
            )
        return sorted(items, key=lambda pair: pair[0].start)

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        schedule = self.schedule
        if schedule is not None and (main := current_program(schedule.main, now)):
            return _to_event(main, None)
        return next(
            (
                _to_event(item, prefix)
                for item, prefix in self._items()
                if item.end > now
            ),
            None,
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            _to_event(item, prefix)
            for item, prefix in self._items()
            if item.end > start_date and item.start < end_date
        ]
