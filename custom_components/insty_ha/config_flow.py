"""Config flow for the Insty Router integration."""

from __future__ import annotations

from typing import Any

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_ENDPOINT, CONF_HOST, DEFAULT_HOST, DEFAULT_TIMEOUT, DOMAIN


class InstyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Insty Router."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            error = await self._async_test_connection(host)
            if error is None:
                return self.async_create_entry(
                    title=f"Insty Router ({host})",
                    data={CONF_HOST: host},
                )
            errors["base"] = error

        data_schema = vol.Schema(
            {vol.Required(CONF_HOST, default=DEFAULT_HOST): str}
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def _async_test_connection(self, host: str) -> str | None:
        """Return an error string if the router cannot be reached, else None."""
        session = async_get_clientsession(self.hass)
        url = f"http://{host}{API_ENDPOINT}"
        try:
            async with async_timeout.timeout(DEFAULT_TIMEOUT):
                response = await session.get(url)
                response.raise_for_status()
                await response.json(content_type=None)
        except aiohttp.ClientError:
            return "cannot_connect"
        except ValueError:
            return "invalid_response"
        return None
