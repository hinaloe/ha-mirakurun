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


def is_broadcast_identifier(entry: ConfigEntry[Any], identifier: str) -> bool:
    """Return whether a device identifier belongs to a broadcast."""
    return identifier.startswith(f"{entry.entry_id}_broadcast_")


def broadcast_main_id(entry: ConfigEntry[Any], identifier: str) -> int | None:
    """Return the main service ID of a broadcast device identifier."""
    if not is_broadcast_identifier(entry, identifier):
        return None
    suffix = identifier.removeprefix(f"{entry.entry_id}_broadcast_")
    return int(suffix) if suffix.isdecimal() else None
