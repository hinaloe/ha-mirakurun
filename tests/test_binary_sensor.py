"""Tests for Mirakurun binary sensors."""

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .common import ENTRY_ID, entity_id, setup_integration


def _state(hass: HomeAssistant, unique_id: str) -> str:
    state = hass.states.get(entity_id(hass, "binary_sensor", unique_id))
    assert state is not None
    return state.state


async def test_server_and_tuner_binary_sensors(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    assert _state(hass, f"{ENTRY_ID}_server_epg_gathering") == STATE_ON
    assert _state(hass, f"{ENTRY_ID}_tuner_12_fault") == STATE_OFF
    assert _state(hass, f"{ENTRY_ID}_tuner_15_fault") == STATE_ON
