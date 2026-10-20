"""Dashboard-equivalent modem actions."""

from __future__ import annotations

import aiohttp

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InstyDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the modem actions."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        InstyRebootModem(coordinator, entry),
        InstySwitchSim(coordinator, entry),
    ])


class InstyRebootModem(ButtonEntity):
    """Request a modem reboot, including when signal polling is unavailable."""

    _attr_has_entity_name = True
    _attr_name = "Reboot Modem"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: InstyDataUpdateCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_reboot_modem"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_press(self) -> None:
        """Send a single reboot request and surface any failure to the user."""
        try:
            await self.coordinator.async_reboot_modem()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(
                f"Could not confirm modem reboot request: {err}. "
                "The modem may already be restarting; check its status before retrying."
            ) from err


class InstySwitchSim(ButtonEntity):
    """Switch SIM slots, including when signal polling is unavailable."""

    _attr_has_entity_name = True
    _attr_name = "Switch SIM Slot"
    _attr_icon = "mdi:sim"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: InstyDataUpdateCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_switch_sim"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_press(self) -> None:
        """Send one switch request and surface any failure to the user."""
        try:
            await self.coordinator.async_switch_sim()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(
                f"Could not confirm SIM slot switch request: {err}. "
                "The SIM slot may already be switching; check its status before retrying."
            ) from err
