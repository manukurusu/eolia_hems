"""Config flow for the Eolia HEMS integration."""


from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from pyhems import create_multicast_socket

from .const import (
    CONF_DEVICE,
    CONF_INTERFACE,
    CONF_MODEL,
    CONF_MODEL_OVERRIDES,
    DEFAULT_INTERFACE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _ignore_datagram(*_: Any) -> None: ...


class EoliaHEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION: int = 1
    MINOR_VERSION: int = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
        ) -> config_entries.OptionsFlow:
        return EoliaHEMSOptionsFlow()

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

class EoliaHEMSOptionsFlow(config_entries.OptionsFlowWithReload):
    """Let the user override the model reported by each device."""

    def __init__(self) -> None:
        self._device_key: str | None = None

    async def async_step_init(
        self,
        user_input: Mapping[str, Any] | None = None,
        ) -> config_entries.ConfigFlowResult:
        devices = _get_device_options(self.hass, self.config_entry)
        if not devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            self._device_key = user_input[CONF_DEVICE]
            return await self.async_step_model()

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE): SelectSelector(
                    SelectSelectorConfig(
                        options=devices,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_model(
        self,
        user_input: Mapping[str, Any] | None = None,
        ) -> config_entries.ConfigFlowResult:
        assert self._device_key is not None
        overrides: dict[str, str] = dict(
            self.config_entry.options.get(CONF_MODEL_OVERRIDES, {})
        )

        if user_input is not None:
            model = str(user_input.get(CONF_MODEL, "")).strip()
            if model:
                overrides[self._device_key] = model
            else:
                _ = overrides.pop(self._device_key, None)
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_MODEL_OVERRIDES: overrides}
            )

        current = overrides.get(self._device_key)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MODEL,
                    description={"suggested_value": current} if current else None,
                ): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="model",
            data_schema=schema,
            description_placeholders={
                "reported_model": _get_reported_model(
                    self.config_entry, self._device_key
                ) or "-",
            },
        )


def _get_device_options(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
    ) -> list[SelectOptionDict]:
    registry = device_registry.async_get(hass)
    options: list[SelectOptionDict] = []
    for device in device_registry.async_entries_for_config_entry(
        registry, entry.entry_id
    ):
        device_key = next(
            (ident for domain, ident in device.identifiers if domain == DOMAIN),
            None,
        )
        if device_key is None:
            continue
        name = device.name_by_user or device.name or device_key
        options.append({"value": device_key, "label": f"{name} ({device_key})"})
    return sorted(options, key=lambda opt: opt["label"])


def _get_reported_model(
    entry: config_entries.ConfigEntry, device_key: str
    ) -> str | None:
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return None
    node = runtime.coordinator.data.get(device_key)
    return node.product_code if node is not None else None


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
