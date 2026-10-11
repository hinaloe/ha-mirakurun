"""Device identifiers for Mirakurun."""

from typing import Any

from homeassistant.config_entries import ConfigEntry


def server_identifier(entry: ConfigEntry[Any]) -> str:
    """Return the device identifier of the server."""
    return entry.entry_id


def tuner_identifier(entry: ConfigEntry[Any], index: int) -> str:
    """Return the device identifier of a tuner."""
    return f"{entry.entry_id}_tuner_{index}"


def broadcast_identifier(entry: ConfigEntry[Any], main_id: int) -> str:
    """Return the device identifier of a broadcast."""
    return f"{entry.entry_id}_broadcast_{main_id}"
