"""DataUpdateCoordinator for the Insty Router integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_ENDPOINT, DEFAULT_SCAN_INTERVAL, DEFAULT_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)


def flatten_json(data: Any, parent_key: str = "") -> dict[str, Any]:
    """Flatten a nested JSON structure into a single-level dict.

    Nested keys are joined with an underscore, e.g. ``{"a": {"b": 1}}``
    becomes ``{"a_b": 1}``. List items are indexed, e.g. ``a_0``.
    """
    items: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            new_key = f"{parent_key}_{key}" if parent_key else str(key)
            items.update(flatten_json(value, new_key))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            new_key = f"{parent_key}_{index}" if parent_key else str(index)
            items.update(flatten_json(value, new_key))
    else:
        items[parent_key] = data
    return items


class InstyDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the router and returns flattened JSON data."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        """Initialize the coordinator."""
        self.host = host
        self._url = f"http://{host}{API_ENDPOINT}"
        self._session = async_get_clientsession(hass)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch and parse data from the router."""
        try:
            async with async_timeout.timeout(DEFAULT_TIMEOUT):
                response = await self._session.get(self._url)
                response.raise_for_status()
                # Some router firmwares return JSON with the wrong content
                # type, so parse the body directly instead of trusting it.
                payload = await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with router: {err}") from err
        except ValueError as err:
            raise UpdateFailed(f"Invalid JSON received from router: {err}") from err

        return flatten_json(payload)
