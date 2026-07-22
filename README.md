# Insty Router — Home Assistant Integration

A simple Home Assistant custom integration that polls an Insty Connect
router, reads the JSON response from its unathenticated API endpoint,
and exposes every value in that response as a Home Assistant sensor.

- **Router IP (default):** `192.168.225.1`
- **API endpoint:** `/cgi-bin/insty/getcsq?getcsq`

## How it works

1. On setup, you enter the router's IP address (pre-filled with the default).
2. A `DataUpdateCoordinator` polls `http://<host>/cgi-bin/insty/getcsq?getcsq`
   every 30 seconds.
3. The JSON response is flattened (nested keys joined with `_`), and one
   sensor is created per value. New keys that appear later are added
   automatically.

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
- If your firmware returns a different endpoint or requires authentication,
  update `API_ENDPOINT` in `const.py` and add auth to `coordinator.py`.
