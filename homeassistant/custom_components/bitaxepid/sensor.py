"""Sensors for each value in the BitaxePID metrics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BitaxePIDConfigEntry
from .const import CONF_VARIABLES, DOMAIN, VARIABLES
from .coordinator import BitaxePIDCoordinator, entry_settings


def _number(key: str) -> Callable[[dict[str, Any]], StateType]:
    """Read a numeric field; None (unknown) if missing or not a number."""

    def read(metrics: dict[str, Any]) -> StateType:
        value = metrics.get(key)
        if isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return read


def _settings(metrics: dict[str, Any]) -> dict[str, Any]:
    settings = metrics.get("pid_settings")
    return settings if isinstance(settings, dict) else {}


@dataclass(frozen=True, kw_only=True)
class BitaxePIDSensorDescription(SensorEntityDescription):
    """How to read one sensor out of a miner's metrics."""

    value_fn: Callable[[dict[str, Any]], StateType]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


# Entity names (shorter than the setup-form labels in const.VARIABLES).
NAMES: dict[str, str] = {
    "hashrate": "Hashrate",
    "temp": "Temperature",
    "power": "Power",
    "board_voltage": "Board voltage",
    "current": "Current",
    "core_voltage_actual": "Core voltage",
    "frequency": "Frequency",
    "fanrpm": "Fan speed",
    "target_voltage": "Target core voltage",
    "target_frequency": "Target frequency",
    "control_strategy": "Control strategy",
    "timestamp": "Last update",
}


def _measurement(
    key: str,
    unit: str | None,
    device_class: SensorDeviceClass | None = None,
    precision: int | None = None,
) -> BitaxePIDSensorDescription:
    return BitaxePIDSensorDescription(
        key=key,
        name=NAMES[key],
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision,
        value_fn=_number(key),
    )


# Units are the ones the miner's own API (AxeOS) reports in; BitaxePID passes
# the values through unchanged.
SENSORS: tuple[BitaxePIDSensorDescription, ...] = (
    _measurement("hashrate", "GH/s", precision=1),
    _measurement("temp", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, 1),
    _measurement("power", UnitOfPower.WATT, SensorDeviceClass.POWER, 2),
    _measurement(
        "board_voltage", UnitOfElectricPotential.MILLIVOLT, SensorDeviceClass.VOLTAGE, 0
    ),
    _measurement(
        "current", UnitOfElectricCurrent.MILLIAMPERE, SensorDeviceClass.CURRENT, 0
    ),
    _measurement(
        "core_voltage_actual",
        UnitOfElectricPotential.MILLIVOLT,
        SensorDeviceClass.VOLTAGE,
        0,
    ),
    _measurement("frequency", UnitOfFrequency.MEGAHERTZ, SensorDeviceClass.FREQUENCY, 0),
    _measurement("fanrpm", REVOLUTIONS_PER_MINUTE, precision=0),
    _measurement(
        "target_voltage", UnitOfElectricPotential.MILLIVOLT, SensorDeviceClass.VOLTAGE, 1
    ),
    _measurement(
        "target_frequency", UnitOfFrequency.MEGAHERTZ, SensorDeviceClass.FREQUENCY, 0
    ),
    BitaxePIDSensorDescription(
        key="control_strategy",
        name=NAMES["control_strategy"],
        entity_category=EntityCategory.DIAGNOSTIC,
        # State: "pid" or "tcontrol". Attributes: the whole effective tuner
        # configuration (gains, limits, TARGET_TEMP, TCONTROL_*, ...).
        value_fn=lambda m: _settings(m).get("CONTROL_STRATEGY"),
        attributes_fn=_settings,
    ),
    BitaxePIDSensorDescription(
        key="timestamp",
        name=NAMES["timestamp"],
        entity_category=EntityCategory.DIAGNOSTIC,
        # BitaxePID's local time as text ("YYYY-MM-DD HH:MM:SS", no zone).
        value_fn=lambda m: m.get("timestamp"),
    ),
)

assert {d.key for d in SENSORS} == set(VARIABLES) == set(NAMES), "keys out of sync"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BitaxePIDConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the selected sensors for every miner the server reports."""
    coordinator = entry.runtime_data
    selected = set(entry_settings(entry).get(CONF_VARIABLES, list(VARIABLES)))
    descriptions = [d for d in SENSORS if d.key in selected]
    known_macs: set[str] = set()

    # A variable unticked in Configure: drop its sensors instead of leaving
    # them behind as "no longer provided".
    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registry_entry.domain != "sensor":
            continue
        # unique_id is "<aa:bb:cc:dd:ee:ff>_<key>"; the MAC has no underscores.
        key = registry_entry.unique_id.split("_", 1)[-1]
        if key not in selected:
            registry.async_remove(registry_entry.entity_id)

    @callback
    def _add_new_miners() -> None:
        # Miners can appear later (the list is empty until BitaxePID's first
        # tuning cycle), so check on every update.
        new_macs = [mac for mac in (coordinator.data or {}) if mac not in known_macs]
        if not new_macs:
            return
        known_macs.update(new_macs)
        async_add_entities(
            BitaxePIDSensor(coordinator, mac, description)
            for mac in new_macs
            for description in descriptions
        )

    _add_new_miners()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_miners))


class BitaxePIDSensor(CoordinatorEntity[BitaxePIDCoordinator], SensorEntity):
    """One value of one miner."""

    entity_description: BitaxePIDSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BitaxePIDCoordinator,
        mac: str,
        description: BitaxePIDSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._mac = mac
        mac_id = format_mac(mac)
        self._attr_unique_id = f"{mac_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac_id)},
            connections={(CONNECTION_NETWORK_MAC, mac_id)},
            name=f"Bitaxe {mac_id[-8:].replace(':', '').upper()}",
            manufacturer="Bitaxe",
            model="Tuned by BitaxePID",
            configuration_url=f"http://{coordinator.host}:{coordinator.port}/metrics",
        )

    @property
    def _metrics(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get(self._mac)

    @property
    def available(self) -> bool:
        # Unavailable if the server is unreachable or no longer reports this miner.
        return super().available and self._metrics is not None

    @property
    def native_value(self) -> StateType:
        metrics = self._metrics
        return None if metrics is None else self.entity_description.value_fn(metrics)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        metrics = self._metrics
        if metrics is None or self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(metrics)
