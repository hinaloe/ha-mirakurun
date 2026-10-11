"""Tests for the Mirakurun update entity."""

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import RELEASE_URL

from .common import BASE_URL, ENTRY_ID, entity_id, mock_mirakurun, setup_integration


async def test_update_entity(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    state = hass.states.get(entity_id(hass, "update", f"{ENTRY_ID}_server_update"))
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "4.0.0-beta.18"
    assert state.attributes["latest_version"] == "4.1.5"
    assert state.attributes["release_url"] == RELEASE_URL


async def test_update_entity_unavailable_without_version(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock, fail_version=True)
    await setup_integration(hass, config_entry)
    state = hass.states.get(entity_id(hass, "update", f"{ENTRY_ID}_server_update"))
    assert state.state == STATE_UNAVAILABLE


async def test_update_entity_unknown_without_latest(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/api/version", json={"current": "4.0.0-beta.18", "latest": ""}
    )
    mock_mirakurun(aioclient_mock)
    await setup_integration(hass, config_entry)
    state = hass.states.get(entity_id(hass, "update", f"{ENTRY_ID}_server_update"))
    assert state.state == STATE_UNKNOWN
    assert state.attributes["installed_version"] == "4.0.0-beta.18"
    assert state.attributes["latest_version"] is None
