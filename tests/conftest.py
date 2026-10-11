"""Fixtures for Mirakurun tests."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .common import NOW, create_entry, mock_mirakurun


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations."""


@pytest.fixture(autouse=True)
def frozen_now(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time at the test reference time."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def mirakurun(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock a healthy Mirakurun server."""
    mock_mirakurun(aioclient_mock)
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return the default config entry."""
    return create_entry()
