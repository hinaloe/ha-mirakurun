"""Constants for the Mirakurun integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "mirakurun"
MANUFACTURER: Final = "Chinachu Project"

CONF_BROADCASTS: Final = "broadcasts"
CONF_BROADCAST_MAP: Final = "broadcast_map"
CONF_STATUS_INTERVAL: Final = "status_interval"
CONF_PROGRAM_INTERVAL: Final = "program_interval"

DEFAULT_STATUS_INTERVAL: Final = 30
MIN_STATUS_INTERVAL: Final = 10
MAX_STATUS_INTERVAL: Final = 300
DEFAULT_PROGRAM_INTERVAL: Final = 30
MIN_PROGRAM_INTERVAL: Final = 5
MAX_PROGRAM_INTERVAL: Final = 180
VERSION_INTERVAL: Final = timedelta(hours=12)
VERSION_RETRY_INTERVAL: Final = timedelta(minutes=30)

RELEASE_URL: Final = "https://github.com/Chinachu/Mirakurun/releases"
