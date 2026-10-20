"""Constants for the Insty Router integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "insty_ha"

# Default router connection details.
DEFAULT_HOST = "192.168.225.1"
API_ENDPOINT = "/cgi-bin/insty/signal_stream"
VERSION_ENDPOINT = "/cgi-bin/insty/getcsq?version"
MODEM_ENDPOINT = "/cgi-bin/insty/getcsq?checkmodem"
STANDBY_ENDPOINT = "/cgi-bin/insty/getcsq?checkstandby"
SIM_ENDPOINT = "/cgi-bin/insty/esim"
REBOOT_ENDPOINT = "/cgi-bin/insty/getcsq?reboot"
SWITCH_SIM_ENDPOINT = "/cgi-bin/insty/switchsim"

STANDBY_STATES = {
    "0": "no_standby_plan",
    "1": "active",
    "2": "standby",
    "3": "activating",
}

# Configuration keys.
CONF_HOST = "host"
CONF_SCAN_INTERVAL = "scan_interval"

# Polling.
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_TIMEOUT = 10
