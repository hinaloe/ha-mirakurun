"""Config flow for Mirakurun."""

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class MirakurunConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mirakurun."""

    VERSION = 1
