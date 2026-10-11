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
    assert result["entry"]["options"]["channel_types"] == ["GR"]
    assert result["broadcasts"] == 3
    assert result["status"]["version"] == "4.0.0-beta.18"
    assert len(result["tuners"]) == 3
    users = [user for tuner in result["tuners"] for user in tuner["users"]]
    assert users
    assert {user["id"] for user in users} == {"**REDACTED**"}
    assert all("priority" in user and "channel_name" in user for user in users)
    assert result["version"] == {"current": "4.0.0-beta.18", "latest": "4.1.5"}
    assert result["programs"]["3273601024"] == {"main": 3, "subs": {"3273601025": 3}}
