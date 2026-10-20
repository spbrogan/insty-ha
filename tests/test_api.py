"""Tests for the router's SSE signal API using synthetic signal data."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.insty_ha.api import (
    async_fetch_signal,
    async_fetch_version,
    flatten_json,
    normalize_signal,
)
from custom_components.insty_ha.const import API_ENDPOINT, VERSION_ENDPOINT


SIGNAL = {
    "provider": "Test Network",
    "mode": "LTE",
    "signal_percent": 36,
    "reg_status": "REGISTERED",
    "iccid": "test-sim",
    "sim_slot": 1,
    "lte": {
        "rssi": -75,
        "rsrp": -109,
        "rsrq": -13,
        "snr_db": 2.6,
        "pci": 0,
        "earfcn": 700,
        "band": 2,
        "band_name": "B2",
    },
    "nr5g": {
        "rsrp": None,
        "rsrq": None,
        "snr_db": None,
        "pci": None,
        "nrarfcn": None,
        "band": None,
        "band_name": None,
    },
    "bands": {
        "primary": [{"radio": "LTE", "band": 12, "band_name": "B12"}],
        "lte_secondary": [],
        "nr5g_secondary": [],
    },
}


class NormalizeSignalTests(unittest.TestCase):
    def test_native_fields_and_legacy_ids(self):
        result = normalize_signal(SIGNAL)
        self.assertEqual(result["signal_percent"], 36)
        self.assertEqual(result["lte_rsrp"], -109)
        self.assertEqual(result["lte_snr_db"], 2.6)
        self.assertEqual(result["lte_pci"], 0)
        self.assertIsNone(result["nr5g_rsrp"])
        self.assertEqual(result["bands_primary_0_band_name"], "B12")
        self.assertEqual(result["cops"], "Test Network")
        self.assertEqual(result["slot"], 1)
        self.assertEqual(result["rssi"], -75)
        self.assertEqual(result["lband"], "B2<br>B12")
        self.assertNotIn("per", result)
        self.assertNotIn("csq", result)

    def test_5g_and_secondary_bands_are_deduplicated(self):
        signal = deepcopy(SIGNAL)
        signal["nr5g"].update(band=77, band_name="N77", rsrp=-95)
        signal["bands"]["lte_secondary"] = [
            {"band": 2, "band_name": "B2"},
            {"band": 66},
        ]
        signal["bands"]["nr5g_secondary"] = [{"band": 78}]
        result = normalize_signal(signal)
        self.assertEqual(result["nr5g_rsrp"], -95)
        self.assertEqual(result["lband"], "B2<br>N77<br>B12<br>B66<br>N78")

    def test_no_service_preserves_nulls_and_zero(self):
        signal = deepcopy(SIGNAL)
        signal.update(signal_percent=0, lte=None, nr5g=None, bands={})
        result = normalize_signal(signal)
        self.assertEqual(result["signal_percent"], 0)
        self.assertEqual(result["lband"], "")
        self.assertNotIn("rssi", result)

    def test_invalid_shapes_are_rejected(self):
        for payload in (
            None, [], {}, {"error": "not ready"},
            {**SIGNAL, "lte": []},
            {**SIGNAL, "bands": []},
            {**SIGNAL, "bands": {"primary": {}}},
            {**SIGNAL, "bands": {"primary": [None]}},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                normalize_signal(payload)

    def test_flattening_retains_unknown_fields(self):
        self.assertEqual(
            flatten_json({"future": [{"value": 0}, {"value": None}]}),
            {"future_0_value": 0, "future_1_value": None},
        )


class FetchSignalTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self, text, content_type="text/event-stream"):
        response = MagicMock(spec=aiohttp.ClientResponse)
        response.content_type = content_type
        response.content = MagicMock()
        response.content.__aiter__.return_value = [
            line.encode() for line in text.splitlines(keepends=True)
        ]
        response.__aenter__.return_value = response
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get.return_value = response
        return session, response

    async def test_named_update_closes_response_after_first_event(self):
        session, response = self.make_session(
            f"event: update\ndata: {json.dumps(SIGNAL)}\n\n"
            "event: update\ndata: invalid second update\n\n"
        )
        self.assertEqual(
            await async_fetch_signal(session, "router"), normalize_signal(SIGNAL)
        )
        session.get.assert_called_once_with(f"http://router{API_ENDPOINT}")
        response.__aexit__.assert_awaited_once()

    async def test_sse_comments_crlf_multiline_and_other_events(self):
        session, _ = self.make_session(
            "\ufeff: heartbeat\r\n\r\n"
            "event: status\r\ndata: not JSON\r\n\r\n"
            "retry: 2000\r\nid: 10\r\nevent:update\r\n"
            'data: {"mode": "LTE",\r\n'
            'data: "signal_percent": 0}\r\n\r\n'
        )
        self.assertEqual(
            await async_fetch_signal(session, "router"),
            {"mode": "LTE", "signal_percent": 0, "lband": ""},
        )

    async def test_invalid_streams_are_rejected_and_closed(self):
        for text, content_type in (
            ("<html>login</html>", "text/html"),
            ('{"mode":"LTE"}', "application/json"),
            ("event: update\ndata: invalid\n\n", "text/event-stream"),
            ("event: update\ndata: []\n\n", "text/event-stream"),
            ("event: update\ndata: {}\n\n", "text/event-stream"),
            ("event: update\ndata: {}", "text/event-stream"),
            (": heartbeat\n\n", "text/event-stream"),
            ("", "text/event-stream"),
        ):
            with self.subTest(text=text, content_type=content_type):
                session, response = self.make_session(text, content_type)
                with self.assertRaises(ValueError):
                    await async_fetch_signal(session, "router")
                response.__aexit__.assert_awaited_once()

    async def test_http_error_is_propagated(self):
        session, response = self.make_session("")
        response.raise_for_status.side_effect = aiohttp.ClientConnectionError("offline")
        with self.assertRaises(aiohttp.ClientError):
            await async_fetch_signal(session, "router")
        response.__aexit__.assert_awaited_once()

    async def test_stalled_stream_times_out_and_closes(self):
        session, response = self.make_session("")

        async def stalled_lines():
            await asyncio.Event().wait()
            yield b""

        response.content.__aiter__.side_effect = stalled_lines
        with patch("custom_components.insty_ha.api.DEFAULT_TIMEOUT", 0.01):
            with self.assertRaises(TimeoutError):
                await async_fetch_signal(session, "router")
        response.__aexit__.assert_awaited_once()

    async def test_real_http_stream_can_stay_open_and_fragment_lines(self):
        release_handler = asyncio.Event()

        async def stream(request):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            for chunk in (b"event: up", b"date\nda", b"ta: ", json.dumps(SIGNAL).encode(), b"\n\n"):
                await response.write(chunk)
            await release_handler.wait()
            return response

        app = web.Application()
        app.router.add_get(API_ENDPOINT, stream)
        async with TestServer(app) as server, aiohttp.ClientSession() as session:
            host = f"{server.host}:{server.port}"
            try:
                result = await asyncio.wait_for(async_fetch_signal(session, host), 2)
                self.assertEqual(result, normalize_signal(SIGNAL))
            finally:
                release_handler.set()


class FetchVersionTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self, payload):
        response = MagicMock(spec=aiohttp.ClientResponse)
        response.json = AsyncMock(return_value=payload)
        response.__aenter__.return_value = response
        session = MagicMock(spec=aiohttp.ClientSession)
        session.get.return_value = response
        return session, response

    async def test_version_is_text_and_response_is_closed(self):
        session, response = self.make_session({"version": "20260729"})
        self.assertEqual(await async_fetch_version(session, "router"), "20260729")
        session.get.assert_called_once_with(f"http://router{VERSION_ENDPOINT}")
        response.json.assert_awaited_once_with(content_type=None)
        response.__aexit__.assert_awaited_once()

    async def test_invalid_versions_are_rejected(self):
        for payload in (None, [], {}, {"version": None}, {"version": 20260729},
                        {"version": ""}, {"version": "  "}):
            with self.subTest(payload=payload):
                session, response = self.make_session(payload)
                with self.assertRaises(ValueError):
                    await async_fetch_version(session, "router")
                response.__aexit__.assert_awaited_once()

    async def test_http_and_json_errors_are_propagated(self):
        for error in (aiohttp.ClientConnectionError("offline"), ValueError("bad JSON")):
            with self.subTest(error=error):
                session, response = self.make_session(None)
                response.json.side_effect = error
                with self.assertRaises(type(error)):
                    await async_fetch_version(session, "router")
                response.__aexit__.assert_awaited_once()

    async def test_stalled_version_times_out_and_closes(self):
        session, response = self.make_session(None)

        async def stalled_json(**kwargs):
            await asyncio.Event().wait()

        response.json.side_effect = stalled_json
        with patch("custom_components.insty_ha.api.DEFAULT_TIMEOUT", 0.01):
            with self.assertRaises(TimeoutError):
                await async_fetch_version(session, "router")
        response.__aexit__.assert_awaited_once()
