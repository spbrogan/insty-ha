"""Sensor platform for the Insty Router integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STANDBY_STATES
from .coordinator import InstyDataUpdateCoordinator


def _to_number(value: Any) -> float | int | None:
    """Convert a raw value to an int/float, stripping units like ``%``."""
    if value is None:
        return None
    text = str(value).strip().rstrip("%").strip()
    if text in ("", "-", "--"):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _clean_text(value: Any) -> str | None:
    """Strip whitespace from a text value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True, kw_only=True)
class InstySensorEntityDescription(SensorEntityDescription):
    """Describes an Insty sensor with a value converter."""

    value_fn: Callable[[Any], Any] = _clean_text
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: dict[str, InstySensorEntityDescription] = {
    "active_sim_profile": InstySensorEntityDescription(
        key="active_sim_profile",
        name="Active SIM Profile",
        icon="mdi:sim",
    ),
    "standby_status": InstySensorEntityDescription(
        key="standby_status",
        name="Standby Status",
        device_class=SensorDeviceClass.ENUM,
        options=list(STANDBY_STATES.values()),
        icon="mdi:pause-circle-outline",
    ),
    "firmware_version": InstySensorEntityDescription(
        key="firmware_version",
        name="OnChip Firmware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "signal_percent": InstySensorEntityDescription(
        key="signal_percent",
        name="Signal Quality",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:signal",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_to_number,
    ),
    "provider": InstySensorEntityDescription(
        key="provider",
        name="Provider",
        icon="mdi:sim",
    ),
    "reg_status": InstySensorEntityDescription(
        key="reg_status",
        name="Registration Status",
        icon="mdi:access-point-network",
    ),
    "sim_slot": InstySensorEntityDescription(
        key="sim_slot",
        name="SIM Slot",
        icon="mdi:sim-outline",
    ),
    **{
        f"{radio}_{metric}": InstySensorEntityDescription(
            key=f"{radio}_{metric}",
            name=f"{label} {name}",
            native_unit_of_measurement=unit,
            device_class=device_class,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_to_number,
        )
        for radio, label in (("lte", "LTE"), ("nr5g", "5G"))
        for metric, name, unit, device_class in (
            (
                "rssi",
                "RSSI",
                SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                SensorDeviceClass.SIGNAL_STRENGTH,
            ),
            (
                "rsrp",
                "RSRP",
                SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                SensorDeviceClass.SIGNAL_STRENGTH,
            ),
            ("rsrq", "RSRQ", SIGNAL_STRENGTH_DECIBELS, None),
            ("snr_db", "SNR", SIGNAL_STRENGTH_DECIBELS, None),
        )
    },
    "mode": InstySensorEntityDescription(
        key="mode",
        name="Network Mode",
        icon="mdi:access-point-network",
    ),
    "connected_band_count": InstySensorEntityDescription(
        key="connected_band_count",
        name="Connected Band Count",
        icon="mdi:radio-tower",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_to_number,
        attr_fn=lambda data: {"bands": data.get("connected_bands", [])},
    ),
    "imsi": InstySensorEntityDescription(
        key="imsi",
        name="IMSI",
        icon="mdi:card-account-details",
    ),
    "imei": InstySensorEntityDescription(
        key="imei",
        name="IMEI",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "apn": InstySensorEntityDescription(
        key="apn",
        name="APN",
        icon="mdi:access-point-network",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "iccid": InstySensorEntityDescription(
        key="iccid",
        name="ICCID",
        icon="mdi:sim",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors dynamically from the router's JSON response."""
    coordinator: InstyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_keys: set[str] = set()

    @callback
    def _add_new_sensors() -> None:
        """Create sensors for any keys not seen before."""
        new_keys = set(coordinator.data or {}) - known_keys - {
            "modem_reachable", "connected_bands",
        }
        if not new_keys:
            return
        known_keys.update(new_keys)
        async_add_entities(
            InstySensor(coordinator, entry, key) for key in sorted(new_keys)
        )

    _add_new_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_sensors))


class InstySensor(CoordinatorEntity[InstyDataUpdateCoordinator], SensorEntity):
    """A sensor representing a single key from the router's JSON response."""

    _attr_has_entity_name = True
    entity_description: InstySensorEntityDescription

    def __init__(
        self,
        coordinator: InstyDataUpdateCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self.entity_description = SENSOR_DESCRIPTIONS.get(
            key,
            InstySensorEntityDescription(
                key=key,
                name=key.replace("_", " ").title(),
            ),
        )
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Insty Router ({coordinator.host})",
            manufacturer="Inseego",
            configuration_url=f"http://{coordinator.host}",
        )

    @property
    def native_value(self) -> Any:
        """Return the converted value for this sensor's key."""
        raw = (self.coordinator.data or {}).get(self._key)
        return self.entity_description.value_fn(raw)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes (e.g. the parsed band list)."""
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator.data or {})

    @property
    def available(self) -> bool:
        """Return True if the key is present in the latest data."""
        return super().available and self._key in (self.coordinator.data or {})
