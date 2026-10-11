"""Tests for the Mirakurun config flow."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.mirakurun.const import (
    CONF_CHANNEL_TYPES,
    CONF_PROGRAM_INTERVAL,
    CONF_SERVICE_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
)

from .common import (
    BASE_URL,
    DEFAULT_OPTIONS,
    create_entry,
    mock_mirakurun,
    setup_integration,
)

OTHER_URL = "http://other.local:40772"


@pytest.fixture
def mock_setup_entry() -> Iterator[AsyncMock]:
    with patch(
        "custom_components.mirakurun.async_setup_entry", return_value=True
    ) as mock:
        yield mock


async def test_user_flow(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: f"{BASE_URL}/api/"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Mirakurun (mirakurun.local)"
    assert result["data"] == {CONF_URL: BASE_URL}
    assert result["options"] == DEFAULT_OPTIONS
    assert len(mock_setup_entry.mock_calls) == 1


async def test_user_flow_invalid_url_then_recovers(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "mirakurun.local:40772"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_cannot_connect_then_recovers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_mirakurun(aioclient_mock, fail_status=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    mock_mirakurun(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_without_version_endpoint(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_setup_entry: AsyncMock,
) -> None:
    # /api/version needs npm on the server and must not gate the connection check
    mock_mirakurun(aioclient_mock, fail_version=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_unknown_error(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.mirakurun.config_flow.MirakurunClient.get_status",
        side_effect=RuntimeError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: BASE_URL}
        )
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_already_configured_with_different_spelling(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, mock_setup_entry: AsyncMock
) -> None:
    MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: f" {BASE_URL}/api "}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_mirakurun(aioclient_mock, base_url=OTHER_URL)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: f"{OTHER_URL}/"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data == {CONF_URL: OTHER_URL}
    assert config_entry.title == "Mirakurun (other.local)"


async def test_reconfigure_without_version_endpoint(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_mirakurun(aioclient_mock, base_url=OTHER_URL, fail_version=True)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: OTHER_URL}
    )
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data == {CONF_URL: OTHER_URL}


async def test_reconfigure_same_url(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: BASE_URL}
    )
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_to_other_configured_server(
    hass: HomeAssistant,
    mirakurun: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    MockConfigEntry(domain=DOMAIN, data={CONF_URL: OTHER_URL}).add_to_hass(hass)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: OTHER_URL}
    )
    assert result["reason"] == "already_configured"


async def test_reconfigure_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    mock_mirakurun(aioclient_mock, base_url=OTHER_URL, fail_status=True)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "nonsense"}
    )
    assert result["errors"] == {CONF_URL: "invalid_url"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: OTHER_URL}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    await setup_integration(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CHANNEL_TYPES: ["CS"],
            CONF_STATUS_INTERVAL: 60,
            CONF_PROGRAM_INTERVAL: 10,
            CONF_SERVICE_INTERVAL: 6,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_CHANNEL_TYPES: ["CS"],
        CONF_STATUS_INTERVAL: 60,
        CONF_PROGRAM_INTERVAL: 10,
        CONF_SERVICE_INTERVAL: 6,
    }
    broadcasts = config_entry.runtime_data.services.data.broadcasts
    assert [b.main.service_id for b in broadcasts] == [55, 218]


async def test_options_flow_offers_server_types(
    hass: HomeAssistant, mirakurun: AiohttpClientMocker
) -> None:
    entry = create_entry({**DEFAULT_OPTIONS, CONF_CHANNEL_TYPES: ["GR", "SKY"]})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    key = next(k for k in schema if k == CONF_CHANNEL_TYPES)
    assert schema[key].config["options"] == ["CS", "GR"]
    assert key.default() == ["GR"]


async def test_options_flow_cannot_connect(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    mock_mirakurun(aioclient_mock, fail_services=True)
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
