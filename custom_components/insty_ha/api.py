"""Read signal snapshots from the Insty Router event stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from .const import API_ENDPOINT, DEFAULT_TIMEOUT, VERSION_ENDPOINT


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
    """Expose stream fields and retain legacy sensor keys with direct equivalents."""
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
    for old_key, new_key in (("cops", "provider"), ("slot", "sim_slot"), ("rssi", "lte_rssi")):
        if new_key in data:
            data[old_key] = data[new_key]
    data["lband"] = "<br>".join(band_names)
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
