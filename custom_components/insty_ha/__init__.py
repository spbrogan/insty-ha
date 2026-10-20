"""The Insty Router integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_HOST, DOMAIN
from .coordinator import InstyDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Insty Router from a config entry."""
    coordinator = InstyDataUpdateCoordinator(hass, entry.data[CONF_HOST])
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Clean up old entities once when upgrading to config entry version 2."""
    if entry.version > 2:
        _LOGGER.error("Cannot migrate unsupported config entry version %s", entry.version)
        return False

    if entry.version == 1:
        registry = er.async_get(hass)
        removed_ids = {
            f"{entry.entry_id}_{key}"
            for key in (
                "slot", "cops", "rssi", "lband", "csq", "per", "rscp", "ecio",
                "qtwr", "limsrv", "rnc_num", "imsiname", "initial_run",
            )
        }
        enabled_ids = {f"{entry.entry_id}_{key}" for key in ("iccid", "imsi")}
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity.domain != Platform.SENSOR or entity.platform != DOMAIN:
                continue
            if entity.unique_id in removed_ids:
                registry.async_remove(entity.entity_id)
            elif (
                entity.unique_id in enabled_ids
                and entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
            ):
                registry.async_update_entity(entity.entity_id, disabled_by=None)
        hass.config_entries.async_update_entry(entry, version=2, minor_version=1)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
