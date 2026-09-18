"""Config flow for the Mast integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    MastClient,
    MastError,
    MastRateLimited,
    MastUnknownChannel,
    parse_channel_url,
)
from .const import (
    CONF_CHANNEL_NAME,
    CONF_CHANNEL_URL,
    CONF_HEARTBEAT,
    CONF_HEARTBEAT_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_CHANNEL_URL): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        ),
        vol.Optional(CONF_CHANNEL_NAME): str,
        vol.Optional(CONF_HEARTBEAT, default=False): bool,
        vol.Optional(CONF_HEARTBEAT_INTERVAL, default=5): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=1440,
                step=1,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
)

OPTIONS = vol.Schema(
    {
        vol.Optional(CONF_HEARTBEAT, default=False): bool,
        vol.Optional(CONF_HEARTBEAT_INTERVAL, default=5): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=1440,
                step=1,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
)


class MastConfigFlow(ConfigFlow, domain=DOMAIN):
    """Take a channel URL and prove the key works before storing it."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                target = parse_channel_url(user_input[CONF_CHANNEL_URL])
            except MastError:
                errors[CONF_CHANNEL_URL] = "malformed_url"
            else:
                await self.async_set_unique_id(target.key)
                self._abort_if_unique_id_configured()
                client = MastClient(async_get_clientsession(self.hass), target)
                try:
                    await client.validate()
                except MastUnknownChannel:
                    errors[CONF_CHANNEL_URL] = "unknown_channel"
                except MastRateLimited:
                    errors["base"] = "rate_limited"
                except MastError as err:
                    _LOGGER.debug("Mast key check failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    name = user_input.get(CONF_CHANNEL_NAME) or "Mast"
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_CHANNEL_URL: target.send_url,
                            CONF_CHANNEL_NAME: name,
                        },
                        options={
                            CONF_HEARTBEAT: user_input.get(CONF_HEARTBEAT, False),
                            CONF_HEARTBEAT_INTERVAL: int(
                                user_input.get(CONF_HEARTBEAT_INTERVAL, 5)
                            ),
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point the same entity set at a re-minted key.

        A `disconnect` in the Mast app remints every channel key, so this is the
        ordinary path after a phone is replaced or reinstalled.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                target = parse_channel_url(user_input[CONF_CHANNEL_URL])
            except MastError:
                errors[CONF_CHANNEL_URL] = "malformed_url"
            else:
                client = MastClient(async_get_clientsession(self.hass), target)
                try:
                    await client.validate()
                except MastUnknownChannel:
                    errors[CONF_CHANNEL_URL] = "unknown_channel"
                except MastError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(target.key)
                    self._abort_if_unique_id_mismatch(reason="wrong_channel")
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={CONF_CHANNEL_URL: target.send_url},
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_CHANNEL_URL): selector.TextSelector()}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        """Get the options flow for this handler."""
        return MastOptionsFlow()


class MastOptionsFlow(OptionsFlowWithReload):
    """Heartbeat settings, which only matter on a vitals channel."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_HEARTBEAT: user_input.get(CONF_HEARTBEAT, False),
                    CONF_HEARTBEAT_INTERVAL: int(
                        user_input.get(CONF_HEARTBEAT_INTERVAL, 5)
                    ),
                }
            )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS, dict(self.config_entry.options)
            ),
        )
