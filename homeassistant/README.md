# BitaxePID for Home Assistant

A Home Assistant integration that reads everything BitaxePID publishes on its
metrics server (`start_metrics_server()` in `bitaxepid.py`, `GET /metrics`)
and shows it as sensors, one device per miner.

## Install

1. Run BitaxePID with its metrics server on:
   - Python: `python bitaxepid.py --ip <miner ip> --serve-metrics` (port 8093).
   - Docker: `SERVE_METRICS=true` and uncomment `ports:` in
     `docker/docker-compose.yml`; the host port is `METRICS_PORT`.

   `http://<host>:<port>/metrics` should then return JSON in a browser.
2. Copy `custom_components/bitaxepid` from this folder into your Home Assistant
   configuration directory (`<config>/custom_components/bitaxepid/`) and
   restart Home Assistant.
3. Settings → Devices & services → Add integration → **BitaxePID**.

## Settings

All four can be changed later with the integration's **Configure** button.

| Setting | Meaning |
|---|---|
| Host | IP address of the machine running BitaxePID (where the metrics server is), which may differ from the miner's own IP |
| Port | metrics port: 8093, or your `METRICS_PORT` in Docker |
| Sampling time | how often to read the metrics, in seconds (5–3600, default 30) |
| Variables | which values become sensors; unticked ones are not read, and their sensors are removed |

## Sensors (per miner)

Hashrate (GH/s), temperature (°C), power (W), board voltage (mV), current (mA),
core voltage (mV), frequency (MHz), fan speed (rpm), target core voltage (mV),
target frequency (MHz), control strategy (`pid` / `tcontrol`, with the full
tuner configuration as attributes), and last update time.

Values are passed through in the units the miner's API reports. A miner that
stops being reported, or a metrics server that can't be reached, shows its
sensors as unavailable. Add one integration entry per metrics server (for
example, one per Docker container).

Requires Home Assistant 2024.11 or newer; no extra Python packages.

## Tests

```
pip install pytest-homeassistant-custom-component
cd homeassistant && python -m pytest
```
