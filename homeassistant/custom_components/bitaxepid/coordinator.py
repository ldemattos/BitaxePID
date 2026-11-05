"""Polls the BitaxePID metrics server on the configured sampling time."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MetricsError, fetch_metrics
from .const import CONF_SCAN_INTERVAL, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


def entry_settings(entry: ConfigEntry) -> dict[str, Any]:
    """Settings from setup, overridden by anything changed later in Configure."""
    return {**entry.data, **entry.options}


class BitaxePIDCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Holds the latest {mac_address: metrics} read from the server."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        settings = entry_settings(entry)
        self.host: str = settings[CONF_HOST]
        self.port: int = int(settings.get(CONF_PORT, DEFAULT_PORT))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.host}:{self.port}",
            update_interval=timedelta(
                seconds=int(settings.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            return await fetch_metrics(self._session, self.host, self.port)
        except MetricsError as err:
            raise UpdateFailed(str(err)) from err
