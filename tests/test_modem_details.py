"""Modem details tests using synthetic HTML, never real subscriber identifiers."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.const import EntityCategory

from custom_components.insty_ha.api import async_fetch_modem_details
from custom_components.insty_ha.const import DOMAIN, UPDATE_ENDPOINT
from custom_components.insty_ha.coordinator import InstyDataUpdateCoordinator
from custom_components.insty_ha.sensor import InstySensor, async_setup_entry


DETAILS = {
    "imei": "000000000000001",
    "iccid": "00000000000000000002",
    "imsi": "000000000000003",
    "apn": "test.apn",
}
PAGE = """
<html><table class="table">
<tr><td><label for="name">Modem IMEI:</label></td><td>000000000000001</td></tr>
<tr><td><label for="name">Current SIM ICCID:</label></td><td>00000000000000000002</td></tr>
<tr><td><label for="name">Current SIM IMSI:</label></td><td>000000000000003</td></tr>
<tr><td><label for="name">Current APN Applied:</label></td><td>test.apn</td></tr>
</table><a href="/do-not-call">Advanced tool</a></html>
"""


class ModemDetailsApiTests(unittest.IsolatedAsyncioTestCase):
    def session(self, page=PAGE):
        response = MagicMock(spec=aiohttp.ClientResponse)
        response.text = AsyncMock(return_value=page)
        response.__aenter__.return_value = response
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get.return_value = response
        return session, response

    async def test_reads_exact_page_once_and_preserves_identifier_strings(self):
        session, response = self.session()
        self.assertEqual(await async_fetch_modem_details(session, "router"), DETAILS)
        session.get.assert_called_once_with(f"http://router{UPDATE_ENDPOINT}")
        response.raise_for_status.assert_called_once()
        response.__aexit__.assert_awaited_once()

    async def test_nested_markup_whitespace_and_html_entities(self):
        page = PAGE.replace("Modem IMEI:", " Modem\n IMEI: ").replace(
            "test.apn</td>", " <strong>test&amp;apn</strong> </td>"
        )
        session, _ = self.session(page)
        self.assertEqual(
            await async_fetch_modem_details(session, "router"),
            {**DETAILS, "apn": "test&apn"},
        )

    async def test_empty_values_are_unknown(self):
        page = PAGE
        for key, replacement in zip(DETAILS, ("", " ", "-", "--"), strict=True):
            page = page.replace(DETAILS[key], replacement)
        session, _ = self.session(page)
        self.assertEqual(
            await async_fetch_modem_details(session, "router"),
            dict.fromkeys(DETAILS),
        )

    async def test_missing_duplicate_or_unrecognized_fields_are_rejected(self):
        for page in (
            "<html>Login required</html>",
            PAGE.replace("Current SIM IMSI:", "Different label:"),
            PAGE.replace("</table>", "<tr><td>Modem IMEI:</td><td>duplicate</td></tr></table>"),
            PAGE.replace("<td>test.apn</td>", ""),
        ):
            with self.subTest(page=page):
                session, _ = self.session(page)
                with self.assertRaises(ValueError):
                    await async_fetch_modem_details(session, "router")

    async def test_http_error_and_timeout_close_response(self):
        session, response = self.session()
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            MagicMock(), (), status=500
        )
        with self.assertRaises(aiohttp.ClientResponseError):
            await async_fetch_modem_details(session, "router")
        response.__aexit__.assert_awaited_once()

        session, response = self.session()

        async def stalled():
            await asyncio.Event().wait()

        response.text.side_effect = stalled
        with patch("custom_components.insty_ha.api.DEFAULT_TIMEOUT", 0.01):
            with self.assertRaises(TimeoutError):
                await async_fetch_modem_details(session, "router")
        response.__aexit__.assert_awaited_once()


class ModemDetailsCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = object.__new__(InstyDataUpdateCoordinator)
        self.coordinator.host = "router"
        self.coordinator._session = MagicMock()
        for name, value in (
            ("async_fetch_signal", {"mode": "LTE", "iccid": "stream-sim"}),
            ("async_fetch_version", "20260729"),
            ("async_fetch_modem", True),
            ("async_fetch_sim_profile", None),
            ("async_fetch_standby", "active"),
            ("async_fetch_modem_details", DETAILS),
        ):
            mocked = patch(
                f"custom_components.insty_ha.coordinator.{name}",
                new_callable=AsyncMock,
                return_value=value,
            )
            setattr(self, name, mocked.start())
            self.addCleanup(mocked.stop)

    async def test_merges_details_and_preserves_signal_iccid(self):
        data = await self.coordinator._async_update_data()
        self.assertEqual(
            {key: data[key] for key in DETAILS}, {**DETAILS, "iccid": "stream-sim"}
        )
        self.async_fetch_modem_details.assert_awaited_once_with(
            self.coordinator._session, "router"
        )

    async def test_page_iccid_fills_missing_or_empty_signal_value(self):
        for signal in ({"mode": "LTE"}, {"iccid": None}, {"iccid": ""}):
            self.async_fetch_signal.return_value = signal.copy()
            data = await self.coordinator._async_update_data()
            self.assertEqual(data["iccid"], DETAILS["iccid"])

    async def test_failure_is_isolated_and_recovers_without_stale_details(self):
        for error in (
            TimeoutError("timeout"), aiohttp.ClientConnectionError("offline"),
            ValueError("invalid page"),
        ):
            self.async_fetch_signal.side_effect = [
                {"mode": "LTE", "iccid": "stream-sim"},
                {"mode": "LTE", "iccid": "stream-sim"},
                {"mode": "LTE", "iccid": "stream-sim"},
            ]
            self.async_fetch_modem_details.side_effect = [DETAILS, error, DETAILS]
            first = await self.coordinator._async_update_data()
            self.assertEqual(first["imei"], DETAILS["imei"])
            with self.assertLogs("custom_components.insty_ha.coordinator", level="WARNING"):
                failed = await self.coordinator._async_update_data()
            for key in ("imei", "imsi", "apn"):
                self.assertNotIn(key, failed)
            self.assertEqual(failed["iccid"], "stream-sim")
            self.assertEqual(failed["mode"], "LTE")
            self.assertTrue(failed["modem_reachable"])
            recovered = await self.coordinator._async_update_data()
            self.assertEqual(recovered["imsi"], DETAILS["imsi"])


class ModemDetailsSensorTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_metadata_ids_availability_and_defaults(self):
        coordinator = MagicMock()
        coordinator.host = "router"
        coordinator.data = DETAILS.copy()
        coordinator.last_update_success = True
        entry = MagicMock()
        entry.entry_id = "existing"
        for key, value in DETAILS.items():
            sensor = InstySensor(coordinator, entry, key)
            self.assertEqual(sensor.native_value, value)
            self.assertEqual(sensor.unique_id, f"existing_{key}")
            self.assertEqual(sensor.name, key.upper())
            self.assertIsNone(sensor.entity_description.state_class)
            self.assertIsNone(sensor.entity_description.native_unit_of_measurement)
            self.assertTrue(sensor.entity_description.entity_registry_enabled_default)
            if key in ("imei", "apn"):
                self.assertEqual(sensor.entity_description.entity_category, EntityCategory.DIAGNOSTIC)
            self.assertTrue(sensor.available)
            coordinator.data[key] = None
            self.assertIsNone(sensor.native_value)
            del coordinator.data[key]
            self.assertFalse(sensor.available)

    async def test_new_details_create_sensors_once_without_duplicate_iccid(self):
        coordinator = MagicMock()
        coordinator.host = "router"
        coordinator.data = {"iccid": "stream-sim"}
        entry = MagicMock()
        entry.entry_id = "existing"
        hass = MagicMock()
        hass.data = {DOMAIN: {entry.entry_id: coordinator}}
        added = []
        await async_setup_entry(hass, entry, added.extend)
        listener = coordinator.async_add_listener.call_args.args[0]
        coordinator.data = DETAILS.copy()
        listener()
        listener()
        self.assertEqual(
            sorted(entity.unique_id for entity in added),
            ["existing_apn", "existing_iccid", "existing_imei", "existing_imsi"],
        )
