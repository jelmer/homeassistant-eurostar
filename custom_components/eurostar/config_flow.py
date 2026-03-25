"""Config flow for Eurostar integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_DESTINATION, CONF_ORIGIN, DOMAIN, GTFS_STATIC_URL
from .coordinator import parse_stops_from_gtfs

_LOGGER = logging.getLogger(__name__)


class EurostarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Eurostar."""

    VERSION = 1

    _stations: dict[str, str] | None = None

    async def _get_stations(self) -> dict[str, str]:
        """Fetch and cache the station list from the GTFS feed."""
        if self._stations is not None:
            return self._stations

        session = async_get_clientsession(self.hass)
        async with session.get(GTFS_STATIC_URL) as resp:
            resp.raise_for_status()
            zip_data = await resp.read()

        self._stations = await self.hass.async_add_executor_job(
            parse_stops_from_gtfs, zip_data
        )
        return self._stations

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        try:
            stations = await self._get_stations()
        except Exception:
            _LOGGER.exception("Failed to fetch Eurostar station list")
            return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            origin = user_input[CONF_ORIGIN]
            destination = user_input[CONF_DESTINATION]

            if origin == destination:
                errors["base"] = "same_station"
            else:
                unique_id = f"{origin}_{destination}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                origin_name = stations.get(origin, origin)
                dest_name = stations.get(destination, destination)
                title = f"Eurostar {origin_name} → {dest_name}"

                return self.async_create_entry(title=title, data=user_input)

        # Sort stations by name for the dropdown
        station_options: list[SelectOptionDict] = sorted(
            [{"value": stop_id, "label": name} for stop_id, name in stations.items()],
            key=lambda x: x["label"],
        )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ORIGIN): SelectSelector(
                    SelectSelectorConfig(
                        options=station_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_DESTINATION): SelectSelector(
                    SelectSelectorConfig(
                        options=station_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
