"""Constants for the Mirakurun integration."""

from datetime import timedelta
from typing import Any, Final

DOMAIN: Final = "mirakurun"
MANUFACTURER: Final = "Chinachu Project"

CONF_CHANNEL_TYPES: Final = "channel_types"
CONF_STATUS_INTERVAL: Final = "status_interval"
CONF_PROGRAM_INTERVAL: Final = "program_interval"
CONF_SERVICE_INTERVAL: Final = "service_interval"

# Legacy option of config entry minor version 1, read only by the migration.
CONF_BROADCAST_MAP: Final = "broadcast_map"

DEFAULT_CHANNEL_TYPES: Final = ("GR",)
DEFAULT_STATUS_INTERVAL: Final = 30
MIN_STATUS_INTERVAL: Final = 10
MAX_STATUS_INTERVAL: Final = 300
DEFAULT_PROGRAM_INTERVAL: Final = 30
MIN_PROGRAM_INTERVAL: Final = 5
MAX_PROGRAM_INTERVAL: Final = 180
DEFAULT_SERVICE_INTERVAL: Final = 24
MIN_SERVICE_INTERVAL: Final = 1
MAX_SERVICE_INTERVAL: Final = 168
PROGRAM_FETCH_CONCURRENCY: Final = 4
VERSION_INTERVAL: Final = timedelta(hours=12)
VERSION_RETRY_INTERVAL: Final = timedelta(minutes=30)
# Look again soon when broadcasts vanish: Mirakurun refills its services one
# channel at a time after restarting with a changed channels.yml.
SERVICE_RECHECK_INTERVAL: Final = timedelta(minutes=15)

RELEASE_URL: Final = "https://github.com/Chinachu/Mirakurun/releases"


def default_options() -> dict[str, Any]:
    """Return the options of a new config entry."""
    return {
        CONF_CHANNEL_TYPES: list(DEFAULT_CHANNEL_TYPES),
        CONF_STATUS_INTERVAL: DEFAULT_STATUS_INTERVAL,
        CONF_PROGRAM_INTERVAL: DEFAULT_PROGRAM_INTERVAL,
        CONF_SERVICE_INTERVAL: DEFAULT_SERVICE_INTERVAL,
    }
