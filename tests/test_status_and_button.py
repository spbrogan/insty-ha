"""Read-only status and mocked reboot tests; never reboot a physical modem."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError

from custom_components.insty_ha import PLATFORMS
from custom_components.insty_ha.api import (
    async_fetch_modem,
    async_fetch_sim_profile,
    async_fetch_standby,
    async_reboot_modem,
)
from custom_components.insty_ha.binary_sensor import InstyModemReachable
from custom_components.insty_ha.button import InstyRebootModem
from custom_components.insty_ha.const import (
    MODEM_ENDPOINT, REBOOT_ENDPOINT, SIM_ENDPOINT, STANDBY_ENDPOINT, STANDBY_STATES,
)
from custom_components.insty_ha.coordinator import InstyDataUpdateCoordinator
from custom_components.insty_ha.sensor import InstySensor


class StatusApiTests(unittest.IsolatedAsyncioTestCase):
    def session(self, text="", payload=None):
        response = MagicMock(spec=aiohttp.ClientResponse)
        response.text = AsyncMock(return_value=text)
        response.json = AsyncMock(return_value=payload)
        response.__aenter__.return_value = response
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get.return_value = response
        return session, response

    async def test_modem_boolean_values_and_invalid_status(self):
        for raw, expected in (("1\n", True), (" 0 ", False)):
            session, response = self.session(text=raw)
            self.assertIs(await async_fetch_modem(session, "router"), expected)
            session.get.assert_called_once_with(f"http://router{MODEM_ENDPOINT}")
            response.__aexit__.assert_awaited_once()
        for raw in ("", "2", "<html>login</html>"):
            session, _ = self.session(text=raw)
            with self.assertRaises(ValueError):
                await async_fetch_modem(session, "router")

    async def test_all_standby_states_and_unknown_code(self):
        for code, expected in STANDBY_STATES.items():
            session, _ = self.session(text=f"{code}\n")
            self.assertEqual(await async_fetch_standby(session, "router"), expected)
            session.get.assert_called_once_with(f"http://router{STANDBY_ENDPOINT}")
        session, _ = self.session(text="4")
        with self.assertRaises(ValueError):
            await async_fetch_standby(session, "router")

    async def test_sim_selection_matches_dashboard_not_account_status(self):
        session, _ = self.session(payload={"status": "success", "profiles": [
            {"status": "active", "name": "Wrong SIM", "button_label": "Enable"},
            {"name": "Live SIM", "button_label": "Active"},
        ]})
        self.assertEqual(await async_fetch_sim_profile(session, "router"), "Live SIM")
        session.get.assert_called_once_with(f"http://router{SIM_ENDPOINT}")
        for profiles, expected in (
            ([], None),
            ([{"name": "Inactive", "button_label": "Enable"}], None),
            ([{"button_label": "Active", "iccid": "test-sim"}], "test-sim"),
        ):
            session, _ = self.session(payload={"status": "success", "profiles": profiles})
            self.assertEqual(await async_fetch_sim_profile(session, "router"), expected)

    async def test_invalid_sim_payload_is_rejected(self):
        for payload in (
            [], {}, {"status": "error"}, {"status": "success", "profiles": {}},
            {"status": "success", "profiles": [None]},
            {"status": "success", "profiles": [{"button_label": "Active"}]},
            {"status": "success", "profiles": [
                {"name": "A", "button_label": "Active"},
                {"name": "B", "button_label": "Active"},
            ]},
        ):
            session, _ = self.session(payload=payload)
            with self.assertRaises(ValueError):
                await async_fetch_sim_profile(session, "router")

    async def test_reboot_uses_exact_dashboard_get_once(self):
        session, response = self.session(text="")
        await async_reboot_modem(session, "router")
        session.get.assert_called_once_with(f"http://router{REBOOT_ENDPOINT}")
        response.raise_for_status.assert_called_once()
        response.__aexit__.assert_awaited_once()

    async def test_reboot_http_error_is_not_retried(self):
        session, response = self.session()
        response.raise_for_status.side_effect = aiohttp.ClientConnectionError("offline")
        with self.assertRaises(aiohttp.ClientError):
            await async_reboot_modem(session, "router")
        session.get.assert_called_once()

    async def test_text_request_timeout_closes_response(self):
        session, response = self.session()

        async def stalled():
            await asyncio.Event().wait()

        response.text.side_effect = stalled
        with patch("custom_components.insty_ha.api.DEFAULT_TIMEOUT", 0.01):
            with self.assertRaises(TimeoutError):
                await async_fetch_modem(session, "router")
        response.__aexit__.assert_awaited_once()


class StatusEntityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = MagicMock()
        self.coordinator.last_update_success = True
        self.coordinator.async_reboot_modem = AsyncMock()
        self.coordinator.data = {
            "modem_reachable": False, "standby_status": "activating",
            "active_sim_profile": None,
        }
        self.entry = MagicMock()
        self.entry.entry_id = "entry"

    async def test_platforms_and_values(self):
        self.assertEqual(set(PLATFORMS), {Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON})
        modem = InstyModemReachable(self.coordinator, self.entry)
        self.assertFalse(modem.is_on)
        self.assertTrue(modem.available)
        self.coordinator.data["modem_reachable"] = True
        self.assertTrue(modem.is_on)
        del self.coordinator.data["modem_reachable"]
        self.assertIsNone(modem.is_on)
        self.assertFalse(modem.available)
        profile = InstySensor(self.coordinator, self.entry, "active_sim_profile")
        self.assertIsNone(profile.native_value)
        standby = InstySensor(self.coordinator, self.entry, "standby_status")
        self.assertEqual(standby.native_value, "activating")
        self.assertEqual(standby.entity_description.options, list(STANDBY_STATES.values()))

    async def test_reboot_button_delegates_even_when_signal_unavailable(self):
        self.coordinator.last_update_success = False
        button = InstyRebootModem(self.coordinator, self.entry)
        self.assertTrue(button.available)
        self.assertEqual(button.unique_id, "entry_reboot_modem")
        await button.async_press()
        self.coordinator.async_reboot_modem.assert_awaited_once_with()

    async def test_button_errors_are_visible_and_not_retried(self):
        for error in (TimeoutError("timeout"), aiohttp.ClientConnectionError("offline")):
            self.coordinator.async_reboot_modem.reset_mock()
            self.coordinator.async_reboot_modem.side_effect = error
            button = InstyRebootModem(self.coordinator, self.entry)
            with self.assertRaisesRegex(HomeAssistantError, "may already be restarting"):
                await button.async_press()
            self.coordinator.async_reboot_modem.assert_awaited_once_with()

    async def test_coordinator_delegates_reboot(self):
        coordinator = object.__new__(InstyDataUpdateCoordinator)
        coordinator.host = "router"
        coordinator._session = MagicMock()
        with patch(
            "custom_components.insty_ha.coordinator.async_reboot_modem",
            new_callable=AsyncMock,
        ) as reboot:
            await coordinator.async_reboot_modem()
            reboot.assert_awaited_once_with(coordinator._session, "router")

    async def test_status_failure_is_isolated_and_recovers(self):
        coordinator = object.__new__(InstyDataUpdateCoordinator)
        coordinator.host = "router"
        coordinator._session = MagicMock()
        with (
            patch("custom_components.insty_ha.coordinator.async_fetch_signal",
                  new_callable=AsyncMock, side_effect=[{"mode": "LTE"}, {"mode": "LTE"}]),
            patch("custom_components.insty_ha.coordinator.async_fetch_version",
                  new_callable=AsyncMock, return_value="20260729"),
            patch("custom_components.insty_ha.coordinator.async_fetch_modem",
                  new_callable=AsyncMock, side_effect=[ValueError("bad status"), False]),
            patch("custom_components.insty_ha.coordinator.async_fetch_sim_profile",
                  new_callable=AsyncMock, return_value=None),
            patch("custom_components.insty_ha.coordinator.async_fetch_standby",
                  new_callable=AsyncMock, return_value="standby"),
        ):
            with self.assertLogs("custom_components.insty_ha.coordinator", level="WARNING"):
                failed = await coordinator._async_update_data()
            self.assertNotIn("modem_reachable", failed)
            self.assertEqual(failed["standby_status"], "standby")
            self.assertIsNone(failed["active_sim_profile"])
            recovered = await coordinator._async_update_data()
            self.assertIs(recovered["modem_reachable"], False)
