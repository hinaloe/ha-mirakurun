"""Tests for Mirakurun diagnostics."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .common import setup_integration


async def test_diagnostics(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result["entry"]["data"] == {"url": "**REDACTED**"}
    assert result["entry"]["options"]["broadcasts"] == [
        "3273601024",
        "3239123608",
        "3239123610",
    ]
    assert result["status"]["version"] == "4.0.0-beta.18"
    assert len(result["tuners"]) == 3
    assert result["version"] == {"current": "4.0.0-beta.18", "latest": "4.1.5"}
    assert result["programs"]["3273601024"] == {"main": 3, "subs": {"3273601025": 3}}
