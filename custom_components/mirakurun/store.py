"""Persistent storage of how services were grouped into broadcasts."""

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .broadcast import Classification
from .const import DOMAIN

_LOGGER = logging.getLogger(__package__)

STORAGE_VERSION = 1


class ClassificationStore:
    """Stores, per config entry, whether each subchannel depends on its main."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, bool]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.classification"
        )

    async def async_load(self) -> Classification:
        data: Any = await self._store.async_load()
        if data is None:
            return {}
        if isinstance(data, dict) and all(
            isinstance(key, str) and key.isdecimal() and isinstance(value, bool)
            for key, value in data.items()
        ):
            return {int(key): value for key, value in data.items()}
        # Losing the grouping only means measuring it again.
        _LOGGER.warning("Ignoring invalid stored broadcast grouping: %r", data)
        return {}

    async def async_save(self, classification: Mapping[int, bool]) -> None:
        await self._store.async_save(
            {str(key): value for key, value in classification.items()}
        )

    async def async_remove(self) -> None:
        await self._store.async_remove()
