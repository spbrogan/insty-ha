"""Test setup, polling, and sensor behavior against the shared API reader."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.insty_ha.config_flow import InstyConfigFlow
from custom_components.insty_ha.const import DOMAIN
from custom_components.insty_ha.coordinator import InstyDataUpdateCoordinator
from custom_components.insty_ha.sensor import (
    InstySensor,
    SENSOR_DESCRIPTIONS,
    async_setup_entry,
)


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_and_coordinator_use_same_reader(self):
        flow = InstyConfigFlow()
        flow.hass = MagicMock()
        coordinator = object.__new__(InstyDataUpdateCoordinator)
        coordinator.host = "router"
        coordinator._session = MagicMock()
        data = {"mode": "LTE", "signal_percent": 30}
        with (
            patch(
                "custom_components.insty_ha.config_flow.async_get_clientsession",
                return_value=coordinator._session,
            ),
            patch(
                "custom_components.insty_ha.config_flow.async_fetch_signal",
                new_callable=AsyncMock,
                return_value=data,
            ) as setup_fetch,
            patch(
                "custom_components.insty_ha.coordinator.async_fetch_signal",
                new_callable=AsyncMock,
                return_value=data,
            ) as poll_fetch,
            patch(
                "custom_components.insty_ha.coordinator.async_fetch_version",
                new_callable=AsyncMock,
                return_value="20260729",
            ) as version_fetch,
        ):
            self.assertIsNone(await flow._async_test_connection("router"))
            self.assertEqual(
                await coordinator._async_update_data(),
                {**data, "firmware_version": "20260729"},
            )
            setup_fetch.assert_awaited_once_with(coordinator._session, "router")
            poll_fetch.assert_awaited_once_with(coordinator._session, "router")
            version_fetch.assert_awaited_once_with(coordinator._session, "router")

    async def test_version_failure_does_not_interrupt_signal_and_recovers(self):
        for error in (
            TimeoutError("stalled"), aiohttp.ClientConnectionError("offline"),
            ValueError("invalid version"),
        ):
            with self.subTest(error=error):
                coordinator = object.__new__(InstyDataUpdateCoordinator)
                coordinator.host = "router"
                coordinator._session = MagicMock()
                with (
                    patch(
                        "custom_components.insty_ha.coordinator.async_fetch_signal",
                        new_callable=AsyncMock,
                        side_effect=[{"mode": "LTE"}, {"mode": "LTE"}],
                    ),
                    patch(
                        "custom_components.insty_ha.coordinator.async_fetch_version",
                        new_callable=AsyncMock,
                        side_effect=[error, "20260729"],
                    ),
                ):
                    with self.assertLogs(
                        "custom_components.insty_ha.coordinator", level="WARNING"
                    ):
                        self.assertEqual(await coordinator._async_update_data(), {"mode": "LTE"})
                    self.assertEqual(
                        await coordinator._async_update_data(),
                        {"mode": "LTE", "firmware_version": "20260729"},
                    )

    async def test_config_and_polling_report_errors(self):
        for error, expected in (
            (TimeoutError("stalled"), "cannot_connect"),
            (aiohttp.ClientConnectionError("offline"), "cannot_connect"),
            (ValueError("invalid stream"), "invalid_response"),
        ):
            with self.subTest(error=error):
                flow = InstyConfigFlow()
                flow.hass = MagicMock()
                coordinator = object.__new__(InstyDataUpdateCoordinator)
                coordinator.host = "router"
                coordinator._session = MagicMock()
                with (
                    patch("custom_components.insty_ha.config_flow.async_get_clientsession"),
                    patch(
                        "custom_components.insty_ha.config_flow.async_fetch_signal",
                        new_callable=AsyncMock,
                        side_effect=error,
                    ),
                    patch(
                        "custom_components.insty_ha.coordinator.async_fetch_signal",
                        new_callable=AsyncMock,
                        side_effect=error,
                    ),
                ):
                    self.assertEqual(await flow._async_test_connection("router"), expected)
                    with self.assertRaises(UpdateFailed) as raised:
                        await coordinator._async_update_data()
                    self.assertIs(raised.exception.__cause__, error)


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = MagicMock()
        self.coordinator.host = "router"
        self.coordinator.last_update_success = True
        self.coordinator.data = {
            "signal_percent": 0,
            "lte_rsrp": -109,
            "lte_snr_db": 2.6,
            "nr5g_rsrp": None,
            "lband": "B2<br>N77",
            "firmware_version": "20260729",
        }
        self.entry = MagicMock()
        self.entry.entry_id = "existing-entry"

    def test_radio_measurement_units_and_state_classes(self):
        for radio in ("lte", "nr5g"):
            for metric in ("rssi", "rsrp", "rsrq", "snr_db"):
                with self.subTest(radio=radio, metric=metric):
                    description = SENSOR_DESCRIPTIONS[f"{radio}_{metric}"]
                    power = metric in ("rssi", "rsrp")
                    self.assertEqual(
                        description.native_unit_of_measurement, "dBm" if power else "dB"
                    )
                    self.assertEqual(description.state_class, SensorStateClass.MEASUREMENT)
                    self.assertEqual(
                        description.device_class,
                        SensorDeviceClass.SIGNAL_STRENGTH if power else None,
                    )
        self.assertEqual(SENSOR_DESCRIPTIONS["signal_percent"].native_unit_of_measurement, "%")
        self.assertFalse(SENSOR_DESCRIPTIONS["iccid"].entity_registry_enabled_default)

    def test_numeric_zero_null_and_band_values(self):
        for key, expected in (
            ("signal_percent", 0),
            ("lte_rsrp", -109),
            ("lte_snr_db", 2.6),
            ("nr5g_rsrp", None),
            ("lband", 2),
        ):
            with self.subTest(key=key):
                sensor = InstySensor(self.coordinator, self.entry, key)
                self.assertEqual(sensor.native_value, expected)
                self.assertTrue(sensor.available)
                self.assertEqual(sensor.unique_id, f"existing-entry_{key}")
        bands = InstySensor(self.coordinator, self.entry, "lband")
        self.assertEqual(bands.extra_state_attributes, {"bands": ["B2", "N77"]})

    def test_missing_keys_and_failed_updates_are_unavailable(self):
        sensor = InstySensor(self.coordinator, self.entry, "lte_rsrp")
        self.coordinator.last_update_success = False
        self.assertFalse(sensor.available)
        self.coordinator.last_update_success = True
        self.coordinator.data = {}
        self.assertFalse(sensor.available)
        self.assertIsNone(sensor.native_value)

    def test_firmware_sensor_is_diagnostic_text_and_unavailable_when_missing(self):
        sensor = InstySensor(self.coordinator, self.entry, "firmware_version")
        self.assertEqual(sensor.native_value, "20260729")
        self.assertEqual(sensor.unique_id, "existing-entry_firmware_version")
        self.assertEqual(sensor.entity_description.entity_category, EntityCategory.DIAGNOSTIC)
        self.assertIsNone(sensor.entity_description.state_class)
        self.assertIsNone(sensor.entity_description.native_unit_of_measurement)
        self.assertTrue(sensor.available)
        del self.coordinator.data["firmware_version"]
        self.assertFalse(sensor.available)
        self.assertIsNone(sensor.native_value)


class DynamicSensorTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_fields_are_added_once_after_updates(self):
        coordinator = MagicMock()
        coordinator.host = "router"
        coordinator.data = {"mode": "LTE", "iccid": "test-sim"}
        entry = MagicMock()
        entry.entry_id = "existing-entry"
        hass = MagicMock()
        hass.data = {DOMAIN: {entry.entry_id: coordinator}}
        added = []

        def add_entities(entities):
            added.extend(entities)

        await async_setup_entry(hass, entry, add_entities)
        listener = coordinator.async_add_listener.call_args.args[0]
        coordinator.data["nr5g_rsrp"] = -95
        listener()
        listener()
        self.assertEqual(
            sorted(entity.unique_id for entity in added),
            ["existing-entry_iccid", "existing-entry_mode", "existing-entry_nr5g_rsrp"],
        )
