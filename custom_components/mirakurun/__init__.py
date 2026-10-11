"""The Mirakurun integration."""

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
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
from .entity import (
    broadcast_identifier,
    server_device_info,
    server_identifier,
    tuner_identifier,
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.UPDATE,
]


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
    server_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **server_device_info(entry)
    )
    entry.runtime_data.server_device_id = server_device.id
    _async_remove_stale_devices(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MirakurunConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing devices that no longer exist on the server."""
    return not device_entry.identifiers & _current_identifiers(entry)


def _current_identifiers(entry: MirakurunConfigEntry) -> set[tuple[str, str]]:
    data = entry.runtime_data
    identifiers = {(DOMAIN, server_identifier(entry))}
    identifiers.update(
        (DOMAIN, tuner_identifier(entry, tuner.index))
        for tuner in data.status.data.tuners
    )
    identifiers.update(
        (DOMAIN, broadcast_identifier(entry, broadcast.main.id))
        for broadcast in data.broadcasts
    )
    return identifiers


@callback
def _async_remove_stale_devices(
    hass: HomeAssistant, entry: MirakurunConfigEntry
) -> None:
    current = _current_identifiers(entry)
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & current:
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )
