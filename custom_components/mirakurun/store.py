"""Persistent storage of how services were grouped into broadcasts."""

from collections.abc import Mapping

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .broadcast import Classification
from .const import DOMAIN

STORAGE_VERSION = 1


class ClassificationStore:
    """Stores, per config entry, whether each subchannel depends on its main."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, bool]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.classification"
        )

    async def async_load(self) -> Classification:
        data = await self._store.async_load()
        return {int(key): bool(value) for key, value in (data or {}).items()}

    async def async_save(self, classification: Mapping[int, bool]) -> None:
        await self._store.async_save(
            {str(key): value for key, value in classification.items()}
        )

    async def async_remove(self) -> None:
        await self._store.async_remove()
