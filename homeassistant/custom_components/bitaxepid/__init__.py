"""BitaxePID integration for Home Assistant.

Reads everything BitaxePID publishes through its metrics server
(start_metrics_server() in bitaxepid.py, endpoint GET /metrics) and shows it
as Home Assistant sensors, one device per miner.

HOW TO USE
==========

1. Make BitaxePID serve its metrics:
   - bare Python: start it with --serve-metrics (or METRICS_SERVE: true in
     its config); it then listens on port 8093.
   - Docker: set SERVE_METRICS=true and uncomment the `ports:` mapping in
     docker/docker-compose.yml; the host port is METRICS_PORT (default 8093).
   Check it from a browser: http://<host>:<port>/metrics should return JSON.

2. Install this integration: copy the folder
       homeassistant/custom_components/bitaxepid
   into your Home Assistant configuration directory, so that you end up with
       <config>/custom_components/bitaxepid/__init__.py
   then restart Home Assistant.

3. Add it: Settings -> Devices & services -> Add integration -> "BitaxePID".
   Fill in:
   - Host: IP address (or host name) of the machine running BitaxePID, which
     is where the metrics server lives - not necessarily the miner itself.
   - Port: the metrics port (8093, or your METRICS_PORT in Docker).
   - Sampling time: how often to read the metrics, in seconds.
   - Variables: tick the values you want as sensors; unticked ones are not
     read into Home Assistant at all.

4. Change any of these later with the integration's "Configure" button.
   Every miner reported by the metrics server shows up as its own device,
   named after the end of its MAC address. Add one integration entry per
   metrics server (e.g. one per Docker container / port).

Requires Home Assistant 2024.11 or newer. No extra Python packages.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import BitaxePIDCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type BitaxePIDConfigEntry = ConfigEntry[BitaxePIDCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: BitaxePIDConfigEntry) -> bool:
    """Set up one BitaxePID metrics server."""
    coordinator = BitaxePIDCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Host, port, sampling time and the variable selection can be changed in
    # the options; reload so they take effect.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: BitaxePIDConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: BitaxePIDConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
