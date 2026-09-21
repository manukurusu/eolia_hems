"""Config flow for the Eolia HEMS integration."""


from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from pyhems import create_multicast_socket

from .const import CONF_INTERFACE, DEFAULT_INTERFACE, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _ignore_datagram(*_: Any) -> None: ...


class EoliaHEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION: int = 1
    MINOR_VERSION: int = 1

    @override
    async def async_step_user(
        self,
        user_input: Mapping[str, Any] | None = None,
        ) -> config_entries.ConfigFlowResult:
        return await self._async_handle_interface_step("user", user_input)

    async def async_step_reconfigure(
        self,
        user_input: Mapping[str, Any] | None = None,
        ) -> config_entries.ConfigFlowResult:
        return await self._async_handle_interface_step("reconfigure", user_input)

    async def _async_handle_interface_step(
        self,
        step_id: str, user_input: Mapping[str, Any] | None,
        ) -> config_entries.ConfigFlowResult:
        entry = self._get_reconfigure_entry() if step_id == "reconfigure" else None
        current_interface = (
            entry.data.get(CONF_INTERFACE, DEFAULT_INTERFACE)
            if entry
            else DEFAULT_INTERFACE
        )

        interface_options = await _async_get_interface_options(self.hass)
        if not any(opt["value"] == current_interface for opt in interface_options):
            interface_options.append(
                SelectOptionDict(
                    value=current_interface,
                    label=f"Configured ({current_interface})",
                )
            )
        errors: dict[str, str] = {}

        if user_input is not None:
            interface = user_input.get(CONF_INTERFACE, DEFAULT_INTERFACE)

            if error := await self._async_test_multicast(interface):
                errors["base"] = error
            else:
                return self._async_finish_interface_step(entry, interface)

        schema = vol.Schema(
            {
                vol.Optional(CONF_INTERFACE, default=current_interface): (
                    SelectSelector(
                        SelectSelectorConfig(
                            options=interface_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                ),
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    def _async_finish_interface_step(
        self,
        entry: config_entries.ConfigEntry | None,
        interface: str,
        ) -> config_entries.ConfigFlowResult:
        if entry is None:
            return self.async_create_entry(
                title="HEMS", data={CONF_INTERFACE: interface}
            )
        return self.async_update_reload_and_abort(
            entry, data={CONF_INTERFACE: interface}
        )

    async def _async_test_multicast(self, interface: str) -> str | None:
        try:
            protocol = await create_multicast_socket(interface, _ignore_datagram)
        except OSError:
            return "cannot_connect"
        try:
            return None
        finally:
            protocol.close()

async def _async_get_interface_options(hass: HomeAssistant) -> list[SelectOptionDict]:
    options: list[SelectOptionDict] = [
        {"value": DEFAULT_INTERFACE, "label": f"Auto ({DEFAULT_INTERFACE})"}
    ]

    try:
        adapters = await network.async_get_adapters(hass)
        for adapter in adapters:
            if not adapter["enabled"]:
                continue
            name = adapter.get("name", "unknown")
            options.extend(
                {"value": address, "label": f"{name} ({address})"}
                for ipv4 in adapter.get("ipv4", [])
                if (address := ipv4.get("address")) and address != "127.0.0.1"
            )
    except OSError:
        _LOGGER.debug("Failed to enumerate network adapters")

    return options
