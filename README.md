# Insty Router — Home Assistant Integration

A simple Home Assistant custom integration that polls an Insty Connect
router, reads its unauthenticated local signal event stream,
and exposes every value in each signal update as a Home Assistant sensor.

- **Router IP (default):** `192.168.225.1`
- **API endpoint:** `/cgi-bin/insty/signal_stream`
- **OnChip version endpoint:** `/cgi-bin/insty/getcsq?version`

## How it works

1. On setup, you enter the router's IP address (pre-filled with the default).
2. A `DataUpdateCoordinator` connects to
   `http://<host>/cgi-bin/insty/signal_stream` every 30 seconds. It reads the
   first complete `event: update` server-sent event (SSE), parses its JSON
   `data`, and closes the connection. Setup uses the same reader to validate
   the router. Requests time out after 10 seconds.
3. The signal update is flattened (nested keys joined with `_`), and one
   sensor is created per value. New keys that appear later are added
   automatically.
4. Signal quality (`signal_percent`) is a percentage. LTE and 5G RSSI/RSRP
   sensors use dBm; RSRQ and SNR use dB. Registration status, provider, SIM
   slot, ICCID, and individual primary/secondary band fields are also exposed.
   Missing radio measurements remain unknown rather than becoming zero.
5. The **OnChip Firmware Version** diagnostic sensor (`firmware_version`) reads
   the separate version endpoint every polling cycle. Its state is the version
   string shown by the dashboard (for example, `20260729`), not necessarily the
   router's underlying OS version. If this request fails, a warning is logged
   and only this sensor becomes unavailable; signal sensors continue updating.
   The sensor is created automatically after the first successful version read.
6. Additional dashboard status checks refresh each polling cycle:
   - **Modem Reachable**: a diagnostic connectivity binary sensor using
     `getcsq?checkmodem`. An unsuccessful request is unavailable, not disconnected.
   - **Active SIM Profile**: the name (or ICCID fallback) of the profile marked
     `button_label: "Active"` by `/cgi-bin/insty/esim`, matching the dashboard.
     No active profile is shown as unknown.
   - **Standby Status**: `no_standby_plan`, `active`, `standby`, or `activating`,
     from `getcsq?checkstandby`.
   Individual status failures are logged and do not invalidate other successful
   values. Text sensors appear after their first successful response.
7. **IMEI**, **ICCID**, **IMSI**, and **APN** read the modem details table from
   `/cgi-bin/insty/update` every polling cycle. These are text sensors, preserving
   leading zeros in identifiers. APN is the currently applied APN, not a saved
   profile setting. The existing ICCID sensor keeps its ID and prefers the signal
   stream value, using the update page only when that value is missing or empty.
   IMEI and APN are diagnostic sensors. All sensors are enabled by default.
   During the one-time upgrade to config entry version 2, ICCID and IMSI entities
   previously disabled by the integration are enabled automatically; manually
   disabled entities stay disabled.
   Empty table values are unknown. Request or page-format failures are logged and
   make page-only values unavailable without interrupting signal sensors. Sensors
   are added automatically after the first successful read; no update or other
   advanced tool action is invoked.

### Reboot Modem button

The **Reboot Modem** configuration button sends a single
`GET /cgi-bin/insty/getcsq?reboot`, exactly like the dashboard's Reboot button.
It restarts the modem, not the entire router, and does not perform a factory
reset. This interrupts cellular service. Normal polling detects recovery;
temporary unavailable sensors during reboot are expected.

The button remains usable when signal polling fails. Request failures are
reported to Home Assistant and are not automatically retried: a dropped
connection can mean the modem already started rebooting. Check its status
before retrying. No reboot is performed during setup or polling.

### Switch SIM Slot button

The **Switch SIM Slot** configuration button sends a single
`GET /cgi-bin/insty/switchsim`, matching the dashboard's Alternate SIM Slot
control. It switches to the alternate slot rather than selecting a specific
numbered slot. This interrupts cellular service; normal polling updates the
SIM slot sensor and detects recovery.

The button remains usable when signal polling fails. Request failures are
reported to Home Assistant and are not automatically retried: a dropped
connection can mean the switch already started. Check the SIM slot before
retrying, since another press could switch it back. No SIM switch is performed
during setup or polling.

No speed tests are run or scheduled by this integration.

### Upgrading from the old API

Existing configurations do not need to be recreated. Duplicate compatibility
sensors have been removed:

| Removed sensor key | Replacement sensor key | Name |
| --- | --- | --- |
| `slot` | `sim_slot` | SIM Slot |
| `cops` | `provider` | Provider |
| `rssi` | `lte_rssi` | LTE RSSI |
| `lband` | `connected_band_count` | Connected Band Count |

Reloading the integration or restarting Home Assistant runs a one-time migration
to config entry version 2, removing these old sensor entries from this
integration's entity registry. Normal setup and polling contain no legacy key
filtering or repeated registry cleanup.
Update dashboards and automations referencing the removed entities to use
their replacements; entity names customized in Home Assistant may differ.
The `mode` and `iccid` sensor IDs are unchanged. Connected Band Count includes
unique active LTE/5G bands and primary/secondary bands, with the names available
as a list in its `bands` attribute. No service is represented by a count of zero
and an empty list, not an HTML-formatted string.

The migration also removes obsolete CSQ, packet error rate, RSCP, Ec/Io, tower
quality, LIM server, RNC number, IMSI name, and Initial Run entities. Their
definitions are no longer part of the integration. Signal percentage is **not**
mapped to packet error rate or CSQ; use Signal Quality instead.
Firmware exposing only the old `getcsq?getcsq` endpoint is not supported by
this version.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=spbrogan&repository=insty-ha&category=integration)

1. Make sure [HACS](https://hacs.xyz) is installed.
2. In HACS, open the three-dot menu (top right) → **Custom repositories**.
3. Add `https://github.com/spbrogan/insty-ha` with category **Integration**.
4. Search for **Insty Router** in HACS and click **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration** and search for
   **Insty Router**.
7. Enter the router IP (or accept the default `192.168.225.1`).

### Manual

1. Copy the `custom_components/insty_ha` folder into your Home Assistant
   `config/custom_components/` directory:

   ```
   <config>/custom_components/insty_ha/
   ```

2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for
   **Insty Router**.
4. Enter the router IP (or accept the default `192.168.225.1`).

## Notes

- The integration uses local polling only — no cloud access.
- The router must expose the `signal_stream` SSE endpoint used by the updated
  InstyConnect dashboard. Authentication is not currently supported.
- Stream, HTTP, timeout, and malformed-data errors are reported during setup
  or make sensors unavailable until the next successful poll.

## Tests

On Linux with Python 3.14.2 or newer and Home Assistant's dependencies installed:

```sh
python -m pip install --upgrade homeassistant pytest
python -m pytest tests -q
```

Tests use synthetic signal data and a local HTTP stream, not a physical router.
Last verified with Home Assistant 2026.10.2 and Python 3.14.8.
