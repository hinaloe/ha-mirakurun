"""Config flow for Mirakurun."""

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
import probatio
from yarl import URL

from .api import MirakurunClient, MirakurunError, normalize_url
from .broadcast import TV_SERVICE_TYPE
from .const import (
    CONF_CHANNEL_TYPES,
    CONF_PROGRAM_INTERVAL,
    CONF_SERVICE_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_CHANNEL_TYPES,
    DEFAULT_PROGRAM_INTERVAL,
    DEFAULT_SERVICE_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    MAX_PROGRAM_INTERVAL,
    MAX_SERVICE_INTERVAL,
    MAX_STATUS_INTERVAL,
    MIN_PROGRAM_INTERVAL,
    MIN_SERVICE_INTERVAL,
    MIN_STATUS_INTERVAL,
    default_options,
)
from .coordinator import MirakurunConfigEntry

_LOGGER = logging.getLogger(__name__)

# Channel types are offered in this order, unknown ones alphabetically after.
CHANNEL_TYPE_ORDER = ("GR", "BS", "CS", "SKY")


def _type_order(channel_type: str) -> tuple[int, str]:
    if channel_type in CHANNEL_TYPE_ORDER:
        return CHANNEL_TYPE_ORDER.index(channel_type), channel_type
    return len(CHANNEL_TYPE_ORDER), channel_type


def _option_value(channel_type: str) -> str:
    """Return the selector value for a channel type.

    Selector values double as translation keys, which must be lowercase; the
    options keep Mirakurun's spelling.
    """
    return channel_type.lower()


URL_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        )
    }
)


def _title(url: str) -> str:
    return f"Mirakurun ({URL(url).host})"


def _interval_selector(minimum: int, maximum: int, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement=unit,
            mode=NumberSelectorMode.BOX,
        )
    )


class MirakurunConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mirakurun."""

    VERSION = 1
    MINOR_VERSION = 2

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
            # /api/version shells out to npm and can fail where /api/status works
            await client.get_status()
        except MirakurunError as err:
            # Also reached when the server answers but is not Mirakurun.
            _LOGGER.debug("Mirakurun check of %s failed: %s", url, err)
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
                    return self.async_create_entry(
                        title=_title(url),
                        data={CONF_URL: url},
                        options=default_options(),
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
    """Select broadcast types and polling intervals."""

    def __init__(self) -> None:
        # Selector value -> channel type as Mirakurun spells it.
        self._channel_types: dict[str, str] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form with the channel types the server has."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_CHANNEL_TYPES: [
                        self._channel_types[value]
                        for value in user_input[CONF_CHANNEL_TYPES]
                    ],
                    CONF_STATUS_INTERVAL: int(user_input[CONF_STATUS_INTERVAL]),
                    CONF_PROGRAM_INTERVAL: int(user_input[CONF_PROGRAM_INTERVAL]),
                    CONF_SERVICE_INTERVAL: int(user_input[CONF_SERVICE_INTERVAL]),
                }
            )

        client = MirakurunClient(
            async_get_clientsession(self.hass), self.config_entry.data[CONF_URL]
        )
        try:
            services = await client.get_services()
        except MirakurunError:
            return self.async_abort(reason="cannot_connect")

        available = {s.channel.type for s in services if s.type == TV_SERVICE_TYPE}
        if not available:
            # Saving now could only drop types or store an empty selection.
            return self.async_abort(reason="no_services")
        options = self.config_entry.options
        saved = list(options.get(CONF_CHANNEL_TYPES, DEFAULT_CHANNEL_TYPES))
        # Saved types the server does not report right now (e.g. during a
        # channel scan) stay offered and selected so submitting keeps them.
        offered = sorted(available | set(saved), key=_type_order)
        self._channel_types = {_option_value(t): t for t in offered}
        selected = [_option_value(t) for t in offered if t in saved]
        schema = probatio.Schema(
            {
                probatio.Required(CONF_CHANNEL_TYPES, default=selected): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=_option_value(t), label=t)
                            for t in offered
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key=CONF_CHANNEL_TYPES,
                    )
                ),
                probatio.Required(
                    CONF_STATUS_INTERVAL,
                    default=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
                ): _interval_selector(MIN_STATUS_INTERVAL, MAX_STATUS_INTERVAL, "s"),
                probatio.Required(
                    CONF_PROGRAM_INTERVAL,
                    default=options.get(
                        CONF_PROGRAM_INTERVAL, DEFAULT_PROGRAM_INTERVAL
                    ),
                ): _interval_selector(
                    MIN_PROGRAM_INTERVAL, MAX_PROGRAM_INTERVAL, "min"
                ),
                probatio.Required(
                    CONF_SERVICE_INTERVAL,
                    default=options.get(
                        CONF_SERVICE_INTERVAL, DEFAULT_SERVICE_INTERVAL
                    ),
                ): _interval_selector(MIN_SERVICE_INTERVAL, MAX_SERVICE_INTERVAL, "h"),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
