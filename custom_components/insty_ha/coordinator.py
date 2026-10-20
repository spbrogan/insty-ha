"""DataUpdateCoordinator for the Insty Router integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    async_fetch_modem,
    async_fetch_modem_details,
    async_fetch_signal,
    async_fetch_sim_profile,
    async_fetch_standby,
    async_fetch_version,
    async_reboot_modem,
    async_switch_sim,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class InstyDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the router and returns flattened JSON data."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        """Initialize the coordinator."""
        self.host = host
        self._session = async_get_clientsession(hass)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch signal, status, and diagnostic values from the router."""
        try:
            data = await async_fetch_signal(self._session, self.host)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error communicating with router: {err}") from err
        except ValueError as err:
            raise UpdateFailed(f"Invalid signal update received from router: {err}") from err

        for key, fetch in (
            ("firmware_version", async_fetch_version),
            ("modem_reachable", async_fetch_modem),
            ("active_sim_profile", async_fetch_sim_profile),
            ("standby_status", async_fetch_standby),
        ):
            try:
                data[key] = await fetch(self._session, self.host)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.warning("Unable to fetch %s from %s: %s", key, self.host, err)

        try:
            details = await async_fetch_modem_details(self._session, self.host)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Unable to fetch modem details from %s: %s", self.host, err)
        else:
            for key, value in details.items():
                if key != "iccid" or not data.get("iccid"):
                    data[key] = value
        return data

    async def async_reboot_modem(self) -> None:
        """Request a modem reboot without retrying a potentially accepted action."""
        await async_reboot_modem(self._session, self.host)

    async def async_switch_sim(self) -> None:
        """Switch SIM slots without retrying a potentially accepted action."""
        await async_switch_sim(self._session, self.host)
