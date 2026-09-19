""" Data coordinator for the Eolia HEMS integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pyhems import (
    DeviceManager,
    NodeState,
)

from .const import DOMAIN

if TYPE_CHECKING:
    from .health import RuntimeHealth

_LOGGER = logging.getLogger(__name__)

class EoliaHEMSCoordinator(DataUpdateCoordinator[dict[str, NodeState]]):
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry,
        device_manager: DeviceManager,
        health: RuntimeHealth,
        ) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=None,
            config_entry=config_entry,
        )

        self.data: dict[str, NodeState] = {}
        self.device_manager: DeviceManager = device_manager
        self.device_info_cache: dict[str, DeviceInfo] = {}
        self._health: RuntimeHealth = health

        _ = device_manager.on_device_added(self._on_device_added)
        _ = device_manager.on_device_updated(self._on_device_updated)

    @callback
    def _on_device_added(self, device_key: str) -> None:
        _LOGGER.debug(device_key)
        self.async_set_updated_data(dict(self.device_manager.data))

    @callback
    def _on_device_updated(self, device_key: str) -> None:
        _LOGGER.debug(device_key)
        self.async_update_listeners()

    @property
    def last_runtime_activity_at(self) -> float | None:
        return self._health.last_runtime_activity_at

    def record_runtime_activity(self, timestamp: float) -> None:
        self._health.last_runtime_activity_at = timestamp
