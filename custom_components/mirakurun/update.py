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

"""Update entity reporting new Mirakurun releases."""

from homeassistant.components.update import UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import RELEASE_URL
from .coordinator import MirakurunConfigEntry, VersionCoordinator
from .entity import MirakurunEntity, server_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MirakurunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the update entity."""
    async_add_entities([MirakurunUpdate(entry.runtime_data.version, entry)])


class MirakurunUpdate(MirakurunEntity[VersionCoordinator], UpdateEntity):
    """Shows whether a newer Mirakurun is available. Installing is not supported."""

    _attr_name = None
    _attr_title = "Mirakurun"
    _attr_release_url = RELEASE_URL

    def __init__(
        self, coordinator: VersionCoordinator, entry: MirakurunConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_server_update"
        self._attr_device_info = server_device_info(entry)

    @property
    def installed_version(self) -> str | None:
        data = self.coordinator.data
        return data.current if data is not None else None

    @property
    def latest_version(self) -> str | None:
        data = self.coordinator.data
        return data.latest if data is not None else None
