"""Setup form (and Configure form) for the BitaxePID integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import MetricsError, fetch_metrics
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_VARIABLES,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    VARIABLES,
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
            vol.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_VARIABLES, default=defaults.get(CONF_VARIABLES, list(VARIABLES))
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=key, label=label)
                        for key, label in VARIABLES.items()
                    ],
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        }
    )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise the form values (number fields come back as floats)."""
    return {
        CONF_HOST: str(user_input[CONF_HOST]).strip(),
        CONF_PORT: int(user_input[CONF_PORT]),
        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
        CONF_VARIABLES: [k for k in VARIABLES if k in user_input[CONF_VARIABLES]],
    }


async def _can_connect(hass: HomeAssistant, host: str, port: int) -> bool:
    try:
        await fetch_metrics(async_get_clientsession(hass), host, port)
    except MetricsError:
        return False
    return True


class BitaxePIDConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a BitaxePID metrics server."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            settings = _clean(user_input)
            await self.async_set_unique_id(f"{settings[CONF_HOST]}:{settings[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            if not settings[CONF_HOST]:
                errors[CONF_HOST] = "empty_host"
            elif not await _can_connect(self.hass, settings[CONF_HOST], settings[CONF_PORT]):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"BitaxePID {settings[CONF_HOST]}:{settings[CONF_PORT]}",
                    data=settings,
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BitaxePIDOptionsFlow()


class BitaxePIDOptionsFlow(OptionsFlow):
    """Change host, port, sampling time or the selected variables later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            settings = _clean(user_input)
            if not settings[CONF_HOST]:
                errors[CONF_HOST] = "empty_host"
            elif not await _can_connect(self.hass, settings[CONF_HOST], settings[CONF_PORT]):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="", data=settings)
            current = user_input
        return self.async_show_form(
            step_id="init", data_schema=_schema(current), errors=errors
        )
