"""Test setup, polling, and sensor behavior against the shared API reader."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import aiohttp
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_registry import EntityRegistry, RegistryEntryDisabler
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.insty_ha.config_flow import InstyConfigFlow
from custom_components.insty_ha import (
    async_migrate_entry,
    async_setup_entry as async_setup_integration,
)
from custom_components.insty_ha.api import normalize_signal
from custom_components.insty_ha.const import DOMAIN
from custom_components.insty_ha.coordinator import InstyDataUpdateCoordinator
from custom_components.insty_ha.sensor import (
    InstySensor,
    SENSOR_DESCRIPTIONS,
    async_setup_entry,
)


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        details = patch(
            "custom_components.insty_ha.coordinator.async_fetch_modem_details",
            new_callable=AsyncMock,
            return_value={},
        )
        details.start()
        self.addCleanup(details.stop)
        self.status_data = {
            "modem_reachable": True,
            "active_sim_profile": "Test SIM",
            "standby_status": "no_standby_plan",
        }
        for name, key in (
            ("async_fetch_modem", "modem_reachable"),
            ("async_fetch_sim_profile", "active_sim_profile"),
            ("async_fetch_standby", "standby_status"),
        ):
            mocked = patch(
                f"custom_components.insty_ha.coordinator.{name}",
                new_callable=AsyncMock,
                return_value=self.status_data[key],
            )
            mocked.start()
            self.addCleanup(mocked.stop)

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
                {**data, **self.status_data, "firmware_version": "20260729"},
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
                        self.assertEqual(
                            await coordinator._async_update_data(),
                            {"mode": "LTE", **self.status_data},
                        )
                    self.assertEqual(
                        await coordinator._async_update_data(),
                        {"mode": "LTE", **self.status_data, "firmware_version": "20260729"},
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
            "connected_bands": ["B2", "N77"],
            "connected_band_count": 2,
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
        for description in SENSOR_DESCRIPTIONS.values():
            self.assertTrue(description.entity_registry_enabled_default)

    def test_numeric_zero_null_and_band_values(self):
        for key, expected in (
            ("signal_percent", 0),
            ("lte_rsrp", -109),
            ("lte_snr_db", 2.6),
            ("nr5g_rsrp", None),
            ("connected_band_count", 2),
        ):
            with self.subTest(key=key):
                sensor = InstySensor(self.coordinator, self.entry, key)
                self.assertEqual(sensor.native_value, expected)
                self.assertTrue(sensor.available)
                self.assertEqual(sensor.unique_id, f"existing-entry_{key}")
        bands = InstySensor(self.coordinator, self.entry, "connected_band_count")
        self.assertEqual(bands.extra_state_attributes, {"bands": ["B2", "N77"]})

    def test_connected_band_count_zero_missing_and_updated_attributes(self):
        sensor = InstySensor(self.coordinator, self.entry, "connected_band_count")
        self.coordinator.data.update(connected_bands=[], connected_band_count=0)
        self.assertEqual(sensor.native_value, 0)
        self.assertEqual(sensor.extra_state_attributes, {"bands": []})
        self.assertTrue(sensor.available)
        self.coordinator.data = {}
        self.assertIsNone(sensor.native_value)
        self.assertFalse(sensor.available)
        self.coordinator.data = {"connected_band_count": 1, "connected_bands": ["N77"]}
        self.assertEqual(sensor.native_value, 1)
        self.assertEqual(sensor.extra_state_attributes, {"bands": ["N77"]})

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
    async def test_signal_creates_only_canonical_sensors(self):
        coordinator = MagicMock()
        coordinator.host = "router"
        coordinator.data = normalize_signal({
            "mode": "LTE", "signal_percent": 40, "provider": "Test Network",
            "sim_slot": 1, "lte": {"rssi": -75},
        })
        entry = MagicMock()
        entry.entry_id = "entry"
        hass = MagicMock()
        hass.data = {DOMAIN: {entry.entry_id: coordinator}}
        added = []
        await async_setup_entry(hass, entry, added.extend)
        listener = coordinator.async_add_listener.call_args.args[0]
        listener()
        self.assertEqual(
            sorted(entity.unique_id for entity in added),
            [
                "entry_connected_band_count", "entry_lte_rssi", "entry_mode", "entry_provider",
                "entry_signal_percent", "entry_sim_slot",
            ],
        )
        self.assertEqual([entity.name for entity in added].count("SIM Slot"), 1)
        for key in (
            "slot", "cops", "rssi", "lband", "csq", "per", "rscp", "ecio",
            "qtwr", "limsrv", "rnc_num", "imsiname", "initial_run",
        ):
            self.assertNotIn(key, SENSOR_DESCRIPTIONS)

    async def test_new_fields_are_added_once_after_updates(self):
        coordinator = MagicMock()
        coordinator.host = "router"
        coordinator.data = {"mode": "LTE", "iccid": "test-sim", "modem_reachable": True}
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


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_removes_only_this_entries_obsolete_sensor_entities(self):
        hass = MagicMock()
        hass.data = {}
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = MagicMock()
        entry.entry_id = "entry"
        entry.version = 1
        entry.data = {"host": "router"}
        registry = create_autospec(EntityRegistry, instance=True)
        obsolete_keys = (
            "slot", "cops", "rssi", "lband", "csq", "per", "rscp", "ecio",
            "qtwr", "limsrv", "rnc_num", "imsiname", "initial_run",
        )
        entities = [
            SimpleNamespace(
                entity_id=f"sensor.old_{key}", domain="sensor", platform=DOMAIN,
                unique_id=f"entry_{key}",
            )
            for key in obsolete_keys
        ]
        entities.extend([
            SimpleNamespace(
                entity_id=f"sensor.keep_{key}", domain="sensor", platform=DOMAIN,
                unique_id=f"entry_{key}", disabled_by=None,
            )
            for key in ("sim_slot", "provider", "lte_rssi", "iccid", "connected_band_count")
        ])
        entities.extend([
            SimpleNamespace(
                entity_id="sensor.other_entry", domain="sensor", platform=DOMAIN,
                unique_id="other_slot",
            ),
            SimpleNamespace(
                entity_id="sensor.other_integration", domain="sensor", platform="other",
                unique_id="entry_slot",
            ),
            SimpleNamespace(
                entity_id="button.other_domain", domain="button", platform=DOMAIN,
                unique_id="entry_slot",
            ),
        ])
        with (
            patch("custom_components.insty_ha.er.async_get", return_value=registry),
            patch("custom_components.insty_ha.er.async_entries_for_config_entry",
                  return_value=entities) as entries,
        ):
            self.assertTrue(await async_migrate_entry(hass, entry))
        entries.assert_called_once_with(registry, "entry")
        self.assertEqual(
            [call.args[0] for call in registry.async_remove.call_args_list],
            [f"sensor.old_{key}" for key in obsolete_keys],
        )
        registry.async_update_entity.assert_not_called()
        hass.config_entries.async_update_entry.assert_called_once_with(
            entry, version=2, minor_version=1
        )

    async def test_migration_enables_identifiers_but_preserves_user_choices(self):
        hass = MagicMock()
        hass.data = {}
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = MagicMock()
        entry.entry_id = "entry"
        entry.version = 1
        entry.data = {"host": "router"}
        registry = create_autospec(EntityRegistry, instance=True)
        entities = [
            SimpleNamespace(
                entity_id=f"sensor.{key}_{label}", domain="sensor", platform=DOMAIN,
                unique_id=f"entry_{key}", disabled_by=reason,
            )
            for key in ("iccid", "imsi")
            for label, reason in (
                ("integration", RegistryEntryDisabler.INTEGRATION),
                ("user", RegistryEntryDisabler.USER),
                ("enabled", None),
            )
        ]
        entities.extend([
            SimpleNamespace(
                entity_id=f"sensor.unrelated_{index}", domain=domain, platform=platform,
                unique_id=unique_id, disabled_by=RegistryEntryDisabler.INTEGRATION,
            )
            for index, (domain, platform, unique_id) in enumerate((
                ("sensor", DOMAIN, "entry_imei"),
                ("sensor", DOMAIN, "other_iccid"),
                ("sensor", "other", "entry_iccid"),
                ("button", DOMAIN, "entry_iccid"),
            ))
        ])
        with (
            patch("custom_components.insty_ha.er.async_get", return_value=registry),
            patch("custom_components.insty_ha.er.async_entries_for_config_entry",
                  return_value=entities) as entries,
        ):
            self.assertTrue(await async_migrate_entry(hass, entry))
        entries.assert_called_once_with(registry, "entry")
        self.assertEqual(
            [(call.args, call.kwargs) for call in registry.async_update_entity.call_args_list],
            [
                ((f"sensor.{key}_integration",), {"disabled_by": None})
                for key in ("iccid", "imsi")
            ],
        )
        registry.async_remove.assert_not_called()

    async def test_current_entries_skip_migration_and_future_versions_are_rejected(self):
        hass = MagicMock()
        entry = MagicMock()
        self.assertEqual(InstyConfigFlow.VERSION, 2)
        with patch("custom_components.insty_ha.er.async_get") as registry:
            entry.version = 2
            self.assertTrue(await async_migrate_entry(hass, entry))
            entry.version = 3
            with self.assertLogs("custom_components.insty_ha", level="ERROR"):
                self.assertFalse(await async_migrate_entry(hass, entry))
        registry.assert_not_called()
        hass.config_entries.async_update_entry.assert_not_called()

    async def test_setup_does_not_repeat_registry_cleanup(self):
        hass = MagicMock()
        hass.data = {}
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = MagicMock()
        entry.entry_id = "entry"
        entry.data = {"host": "router"}
        coordinator = MagicMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        with (
            patch("custom_components.insty_ha.InstyDataUpdateCoordinator",
                  return_value=coordinator),
            patch("custom_components.insty_ha.er.async_get") as registry,
        ):
            self.assertTrue(await async_setup_integration(hass, entry))
        registry.assert_not_called()
        coordinator.async_config_entry_first_refresh.assert_awaited_once_with()
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
        self.assertIs(hass.data[DOMAIN]["entry"], coordinator)
