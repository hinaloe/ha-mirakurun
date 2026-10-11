"""Config flow for Mirakurun."""

from collections.abc import Sequence
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util
import probatio
from yarl import URL

from .api import MirakurunClient, MirakurunError, normalize_url
from .broadcast import Broadcast, default_selection, discover_broadcasts, to_option_map
from .const import (
    CONF_BROADCAST_MAP,
    CONF_BROADCASTS,
    CONF_PROGRAM_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_PROGRAM_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    MAX_PROGRAM_INTERVAL,
    MAX_STATUS_INTERVAL,
    MIN_PROGRAM_INTERVAL,
    MIN_STATUS_INTERVAL,
)
from .coordinator import MirakurunConfigEntry

_LOGGER = logging.getLogger(__name__)

URL_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        )
    }
)


def build_options(
    broadcasts: Sequence[Broadcast],
    selected: list[str] | None = None,
    status_interval: int = DEFAULT_STATUS_INTERVAL,
    program_interval: int = DEFAULT_PROGRAM_INTERVAL,
) -> dict[str, Any]:
    """Build config entry options from classified broadcasts."""
    return {
        CONF_BROADCAST_MAP: to_option_map(broadcasts),
        CONF_BROADCASTS: default_selection(broadcasts)
        if selected is None
        else selected,
        CONF_STATUS_INTERVAL: status_interval,
        CONF_PROGRAM_INTERVAL: program_interval,
    }


def _title(url: str) -> str:
    return f"Mirakurun ({URL(url).host})"


class MirakurunConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mirakurun."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: MirakurunConfigEntry,
    ) -> MirakurunOptionsFlow:
        """Return the options flow."""
        return MirakurunOptionsFlow()

    async def _async_check(self, url: str) -> dict[str, str]:
        client = MirakurunClient(async_get_clientsession(self.hass), url)
        try:
            await client.get_version()
        except MirakurunError:
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error while connecting to Mirakurun")
            return {"base": "unknown"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the server URL."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                self._async_abort_entries_match({CONF_URL: url})
                errors = await self._async_check(url)
                if not errors:
                    client = MirakurunClient(async_get_clientsession(self.hass), url)
                    try:
                        broadcasts = await discover_broadcasts(client, dt_util.utcnow())
                    except MirakurunError:
                        errors["base"] = "cannot_connect"
                    else:
                        return self.async_create_entry(
                            title=_title(url),
                            data={CONF_URL: url},
                            options=build_options(broadcasts),
                        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(URL_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the server URL."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                if url != entry.data[CONF_URL]:
                    self._async_abort_entries_match({CONF_URL: url})
                errors = await self._async_check(url)
                if not errors:
                    return self.async_update_reload_and_abort(
                        entry, title=_title(url), data_updates={CONF_URL: url}
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                URL_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
        )


class MirakurunOptionsFlow(OptionsFlowWithReload):
    """Select broadcasts and polling intervals."""

    def __init__(self) -> None:
        self._broadcasts: list[Broadcast] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form, re-classifying broadcasts on open."""
        if user_input is not None:
            return self.async_create_entry(
                data=build_options(
                    self._broadcasts,
                    selected=list(user_input[CONF_BROADCASTS]),
                    status_interval=int(user_input[CONF_STATUS_INTERVAL]),
                    program_interval=int(user_input[CONF_PROGRAM_INTERVAL]),
                )
            )

        client = MirakurunClient(
            async_get_clientsession(self.hass), self.config_entry.data[CONF_URL]
        )
        try:
            self._broadcasts = await discover_broadcasts(client, dt_util.utcnow())
        except MirakurunError:
            return self.async_abort(reason="cannot_connect")

        options = self.config_entry.options
        available = {str(b.main.id) for b in self._broadcasts}
        selected = [
            key
            for key in options.get(CONF_BROADCASTS, default_selection(self._broadcasts))
            if key in available
        ]
        schema = probatio.Schema(
            {
                probatio.Required(CONF_BROADCASTS, default=selected): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=str(b.main.id),
                                label=f"{b.main.channel.type}: {b.main.name}",
                            )
                            for b in self._broadcasts
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                probatio.Required(
                    CONF_STATUS_INTERVAL,
                    default=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_STATUS_INTERVAL,
                        max=MAX_STATUS_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                probatio.Required(
                    CONF_PROGRAM_INTERVAL,
                    default=options.get(
                        CONF_PROGRAM_INTERVAL, DEFAULT_PROGRAM_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_PROGRAM_INTERVAL,
                        max=MAX_PROGRAM_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
