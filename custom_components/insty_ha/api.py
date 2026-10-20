"""Read signal snapshots from the Insty Router event stream."""

from __future__ import annotations

import asyncio
import json
from html.parser import HTMLParser
from typing import Any

import aiohttp

from .const import (
    API_ENDPOINT,
    DEFAULT_TIMEOUT,
    MODEM_ENDPOINT,
    REBOOT_ENDPOINT,
    SIM_ENDPOINT,
    STANDBY_ENDPOINT,
    STANDBY_STATES,
    SWITCH_SIM_ENDPOINT,
    UPDATE_ENDPOINT,
    VERSION_ENDPOINT,
)


async def _async_fetch_text(
    session: aiohttp.ClientSession, host: str, endpoint: str
) -> str:
    """Read a text response with the standard request timeout."""
    async with asyncio.timeout(DEFAULT_TIMEOUT):
        async with session.get(f"http://{host}{endpoint}") as response:
            response.raise_for_status()
            return (await response.text()).strip()


async def async_fetch_modem(session: aiohttp.ClientSession, host: str) -> bool:
    """Read whether the modem is reachable."""
    value = await _async_fetch_text(session, host, MODEM_ENDPOINT)
    if value not in ("0", "1"):
        raise ValueError(f"Unexpected modem status: {value!r}")
    return value == "1"


async def async_fetch_standby(session: aiohttp.ClientSession, host: str) -> str:
    """Read the dashboard's on-demand service state."""
    value = await _async_fetch_text(session, host, STANDBY_ENDPOINT)
    if value not in STANDBY_STATES:
        raise ValueError(f"Unexpected standby status: {value!r}")
    return STANDBY_STATES[value]


class _ModemDetailsParser(HTMLParser):
    """Extract the labeled modem details table from the update page."""

    _labels = {
        "Modem IMEI:": "imei",
        "Current SIM ICCID:": "iccid",
        "Current SIM IMSI:": "imsi",
        "Current APN Applied:": "apn",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.details: dict[str, str | None] = {}
        self._row: list[str] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
            self._cell = None
        elif tag in ("td", "th"):
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and len(self._row) == 2:
            label = " ".join(self._row[0].split())
            if key := self._labels.get(label):
                if key in self.details:
                    raise ValueError(f"Duplicate modem detail field: {key}")
                value = self._row[1]
                self.details[key] = None if value in ("", "-", "--") else value


async def async_fetch_modem_details(
    session: aiohttp.ClientSession, host: str
) -> dict[str, str | None]:
    """Read identifiers and the applied APN without invoking update actions."""
    page = await _async_fetch_text(session, host, UPDATE_ENDPOINT)
    parser = _ModemDetailsParser()
    parser.feed(page)
    parser.close()
    if parser.details.keys() != {"imei", "iccid", "imsi", "apn"}:
        raise ValueError("Update page is missing expected modem detail fields")
    return parser.details


async def async_fetch_sim_profile(
    session: aiohttp.ClientSession, host: str
) -> str | None:
    """Read the live SIM label using the dashboard's Active button marker."""
    async with asyncio.timeout(DEFAULT_TIMEOUT):
        async with session.get(f"http://{host}{SIM_ENDPOINT}") as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError("SIM profile request did not return success")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("SIM profiles must be a list")
    active_name = None
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("SIM profile must be an object")
        if profile.get("button_label") == "Active":
            name = profile.get("name") or profile.get("iccid")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Active SIM profile must have a name or ICCID")
            if active_name is not None:
                raise ValueError("Multiple SIM profiles are marked Active")
            active_name = name.strip()
    return active_name


async def async_reboot_modem(session: aiohttp.ClientSession, host: str) -> None:
    """Send the same one-shot GET request as the dashboard's Reboot button."""
    await _async_fetch_text(session, host, REBOOT_ENDPOINT)


async def async_switch_sim(session: aiohttp.ClientSession, host: str) -> None:
    """Send the dashboard's one-shot request to switch to the alternate SIM slot."""
    await _async_fetch_text(session, host, SWITCH_SIM_ENDPOINT)


async def async_fetch_version(session: aiohttp.ClientSession, host: str) -> str:
    """Read the OnChip version displayed by the router dashboard."""
    async with asyncio.timeout(DEFAULT_TIMEOUT):
        async with session.get(f"http://{host}{VERSION_ENDPOINT}") as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    if not isinstance(payload, dict):
        raise ValueError("Version response must be an object")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Version response must contain a nonempty version string")
    return version.strip()


def flatten_json(data: Any, parent_key: str = "") -> dict[str, Any]:
    """Flatten nested objects and lists using underscore-separated keys."""
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


def normalize_signal(payload: Any) -> dict[str, Any]:
    """Expose current stream fields and a unique connected-band summary."""
    if not isinstance(payload, dict) or not {"mode", "signal_percent"} <= payload.keys():
        raise ValueError("Signal update must be an object with mode and signal_percent")

    band_names: list[str] = []

    def add_band(band: Any, prefix: str) -> None:
        if not isinstance(band, dict):
            raise ValueError("Signal radio and band entries must be objects")
        name = band.get("band_name")
        if not name and band.get("band") is not None:
            name = f"{prefix}{band['band']}"
        if name and name not in band_names:
            band_names.append(str(name))

    for radio, prefix in (("lte", "B"), ("nr5g", "N")):
        if payload.get(radio) is not None:
            add_band(payload[radio], prefix)

    bands = payload.get("bands")
    if bands is not None:
        if not isinstance(bands, dict):
            raise ValueError("Signal bands must be an object")
        for group, prefix in (
            ("primary", "B"),
            ("lte_secondary", "B"),
            ("nr5g_secondary", "N"),
        ):
            entries = bands.get(group, [])
            if not isinstance(entries, list):
                raise ValueError(f"Signal bands.{group} must be a list")
            for band in entries:
                add_band(band, prefix)

    data = flatten_json(payload)
    data["connected_bands"] = band_names
    data["connected_band_count"] = len(band_names)
    return data


async def async_fetch_signal(
    session: aiohttp.ClientSession, host: str
) -> dict[str, Any]:
    """Read one complete update event, then close the streaming response."""
    async with asyncio.timeout(DEFAULT_TIMEOUT):
        async with session.get(f"http://{host}{API_ENDPOINT}") as response:
            response.raise_for_status()
            if response.content_type != "text/event-stream":
                raise ValueError("Router did not return a signal event stream")

            event_type = ""
            data_lines: list[str] = []
            async for raw_line in response.content:
                line = raw_line.decode("utf-8-sig").rstrip("\r\n")
                if not line:
                    if event_type == "update" and data_lines:
                        return normalize_signal(json.loads("\n".join(data_lines)))
                    event_type = ""
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]
                if field == "event":
                    event_type = value
                elif field == "data":
                    data_lines.append(value)

    raise ValueError("Signal stream ended before a complete update event")
