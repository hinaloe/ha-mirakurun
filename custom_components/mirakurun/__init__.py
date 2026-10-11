"""The Mirakurun integration."""

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MirakurunClient, MirakurunError
from .broadcast import resolve_broadcasts
from .const import CONF_BROADCAST_MAP, CONF_BROADCASTS, DOMAIN
from .coordinator import (
    MirakurunConfigEntry,
    MirakurunRuntimeData,
    ProgramCoordinator,
    StatusCoordinator,
    VersionCoordinator,
)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Set up Mirakurun from a config entry."""
    client = MirakurunClient(async_get_clientsession(hass), entry.data[CONF_URL])
    try:
        services = await client.get_services()
    except MirakurunError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    broadcasts = tuple(
        resolve_broadcasts(
            entry.options.get(CONF_BROADCAST_MAP, {}),
            entry.options.get(CONF_BROADCASTS, []),
            services,
        )
    )
    status = StatusCoordinator(hass, entry, client)
    programs = ProgramCoordinator(hass, entry, client, broadcasts)
    version = VersionCoordinator(hass, entry, client)

    await status.async_config_entry_first_refresh()
    await programs.async_config_entry_first_refresh()
    # The latest version comes from npm via Mirakurun and may be unreachable;
    # it must not block setup.
    await version.async_refresh()

    entry.runtime_data = MirakurunRuntimeData(
        client, broadcasts, status, programs, version
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
