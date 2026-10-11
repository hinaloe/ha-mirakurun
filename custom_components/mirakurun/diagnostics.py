"""Diagnostics for Mirakurun."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant

from .const import CONF_BROADCASTS, CONF_PROGRAM_INTERVAL, CONF_STATUS_INTERVAL
from .coordinator import MirakurunConfigEntry

TO_REDACT = {CONF_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MirakurunConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    status = data.status.data
    version = data.version.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": {
                key: entry.options.get(key)
                for key in (
                    CONF_BROADCASTS,
                    CONF_STATUS_INTERVAL,
                    CONF_PROGRAM_INTERVAL,
                )
            },
        },
        "status": asdict(status.status),
        "tuners": [asdict(tuner) for tuner in status.tuners],
        "version": asdict(version) if version is not None else None,
        "programs": {
            str(main_id): {
                "main": len(schedule.main),
                "subs": {str(service.id): len(sub) for service, sub in schedule.subs},
            }
            for main_id, schedule in data.programs.data.items()
        },
    }
