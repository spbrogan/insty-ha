"""Constants for the Insty Router integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "insty_ha"

# Default router connection details (from data.py).
DEFAULT_HOST = "192.168.225.1"
API_ENDPOINT = "/cgi-bin/insty/getcsq?getcsq"

# Configuration keys.
CONF_HOST = "host"
CONF_SCAN_INTERVAL = "scan_interval"

# Polling.
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_TIMEOUT = 10
