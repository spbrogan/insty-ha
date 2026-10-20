"""DataUpdateCoordinator for the Insty Router integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import async_fetch_signal, async_fetch_version
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
        """Fetch a signal snapshot and the OnChip version from the router."""
        try:
            data = await async_fetch_signal(self._session, self.host)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error communicating with router: {err}") from err
        except ValueError as err:
            raise UpdateFailed(f"Invalid signal update received from router: {err}") from err

        try:
            data["firmware_version"] = await async_fetch_version(self._session, self.host)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Unable to fetch OnChip firmware version from %s: %s", self.host, err)
        return data
