"""The Mirakurun integration."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MirakurunClient
from .broadcast import classification_from_option_map
from .const import (
    CONF_BROADCAST_MAP,
    CONF_PROGRAM_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
    default_options,
)
from .coordinator import (
    MirakurunConfigEntry,
    MirakurunRuntimeData,
    ProgramCoordinator,
    ServiceCoordinator,
    StatusCoordinator,
    VersionCoordinator,
)
from .entity import server_device_info
from .identifiers import (
    broadcast_identifier,
    is_broadcast_identifier,
    server_identifier,
    tuner_identifier,
)
from .store import ClassificationStore

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Set up Mirakurun from a config entry."""
    client = MirakurunClient(async_get_clientsession(hass), entry.data[CONF_URL])
    services = ServiceCoordinator(
        hass, entry, client, ClassificationStore(hass, entry.entry_id)
    )
    status = StatusCoordinator(hass, entry, client)
    programs = ProgramCoordinator(hass, entry, client, services)
    version = VersionCoordinator(hass, entry, client)

    await services.async_config_entry_first_refresh()
    await status.async_config_entry_first_refresh()
    await programs.async_config_entry_first_refresh()
    # The latest version comes from npm via Mirakurun and may be unreachable;
    # it must not block setup.
    await version.async_refresh()

    entry.runtime_data = MirakurunRuntimeData(
        client, services, status, programs, version
    )
    server_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **server_device_info(entry)
    )
    entry.runtime_data.server_device_id = server_device.id
    _async_remove_stale_devices(hass, entry)

    @callback
    def _async_broadcasts_changed() -> None:
        _async_remove_stale_devices(hass, entry, broadcasts_only=True)
        entry.async_create_background_task(
            hass, programs.async_request_refresh(), f"{DOMAIN}_program_refresh"
        )

    entry.async_on_unload(services.async_add_listener(_async_broadcasts_changed))

    @callback
    def _async_status_changed() -> None:
        # The server device is created once; keep its version current.
        registry = dr.async_get(hass)
        version = status.data.status.version
        device = registry.async_get(server_device.id, include_child_devices=False)
        if device is not None and device.sw_version != version:
            registry.async_update_device(server_device.id, sw_version=version)

    entry.async_on_unload(status.async_add_listener(_async_status_changed))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> bool:
    """Migrate per-broadcast options (minor version 1) to broadcast types."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        legacy = dict(entry.options)
        options = default_options()
        for key in (CONF_STATUS_INTERVAL, CONF_PROGRAM_INTERVAL):
            if key in legacy:
                options[key] = legacy[key]
        await ClassificationStore(hass, entry.entry_id).async_save(
            classification_from_option_map(legacy.get(CONF_BROADCAST_MAP, {}))
        )
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: MirakurunConfigEntry) -> None:
    """Remove stored data of a deleted config entry."""
    await ClassificationStore(hass, entry.entry_id).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MirakurunConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing devices that no longer exist on the server."""
    if entry.state is not ConfigEntryState.LOADED:
        # Without runtime data the current devices are unknown.
        return False
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
        for broadcast in data.services.data.broadcasts
    )
    return identifiers


@callback
def _async_remove_stale_devices(
    hass: HomeAssistant, entry: MirakurunConfigEntry, *, broadcasts_only: bool = False
) -> None:
    """Remove devices that no longer exist on the server.

    Tuners only change with Mirakurun's configuration, so runtime cleanup
    (``broadcasts_only``) leaves them alone; a tuner that briefly drops out of
    the status keeps its device and entities.
    """
    current = _current_identifiers(entry)
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if device.identifiers & current:
            continue
        if broadcasts_only and not any(
            is_broadcast_identifier(entry, identifier)
            for domain, identifier in device.identifiers
            if domain == DOMAIN
        ):
            continue
        registry.async_remove_device(device.id)
