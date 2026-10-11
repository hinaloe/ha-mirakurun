"""Tests for the classification store."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
import pytest

from custom_components.mirakurun.const import DOMAIN
from custom_components.mirakurun.store import STORAGE_VERSION, ClassificationStore

from .common import ENTRY_ID


async def test_round_trip(hass: HomeAssistant) -> None:
    store = ClassificationStore(hass, ENTRY_ID)
    await store.async_save({3273601025: True, 3239123610: False})
    assert await store.async_load() == {3273601025: True, 3239123610: False}


@pytest.mark.parametrize("data", [{"abc": True}, [1, 2], {"1": "false"}])
async def test_invalid_data_loads_empty(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture, data: Any
) -> None:
    await Store[Any](
        hass, STORAGE_VERSION, f"{DOMAIN}.{ENTRY_ID}.classification"
    ).async_save(data)

    assert await ClassificationStore(hass, ENTRY_ID).async_load() == {}
    assert [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "custom_components.mirakurun"
    ]
