"""Constants for the BitaxePID integration."""

from __future__ import annotations

DOMAIN = "bitaxepid"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_VARIABLES = "variables"

DEFAULT_PORT = 8093  # bitaxepid.py's start_metrics_server() listens here
DEFAULT_SCAN_INTERVAL = 30  # seconds
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 3600

# Every value the metrics server publishes for a miner, as
# {key: label shown in the setup form}. The keys are the JSON field names in
# bitaxepid.py's metrics dict, except "control_strategy", which is read from
# its "pid_settings" field.
VARIABLES: dict[str, str] = {
    "hashrate": "Hashrate",
    "temp": "Temperature",
    "power": "Power",
    "board_voltage": "Board input voltage",
    "current": "Input current",
    "core_voltage_actual": "Core voltage (measured)",
    "frequency": "Frequency (measured)",
    "fanrpm": "Fan speed",
    "target_voltage": "Target core voltage (set by BitaxePID)",
    "target_frequency": "Target frequency (set by BitaxePID)",
    "control_strategy": "Control strategy and tuner settings",
    "timestamp": "Last update time",
}
