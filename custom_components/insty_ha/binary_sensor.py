"""Modem connectivity status for the Insty Router."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import InstyDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the modem connectivity entity."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([InstyModemReachable(coordinator, entry)])


class InstyModemReachable(CoordinatorEntity[InstyDataUpdateCoordinator], BinarySensorEntity):
    """Report the dashboard's modem reachability check."""

    _attr_has_entity_name = True
    _attr_name = "Modem Reachable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: InstyDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_modem_reachable"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool | None:
        """Return modem reachability, preserving unknown status."""
        return (self.coordinator.data or {}).get("modem_reachable")

    @property
    def available(self) -> bool:
        """An unsuccessful status request must not appear as disconnected."""
        return super().available and "modem_reachable" in (self.coordinator.data or {})
