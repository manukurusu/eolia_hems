"""Runtime lifecycle management for the Eolia HEMS integration."""


from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry
from homeassistant.helpers.event import async_track_time_interval
from pyhems import HemsClient, HemsErrorEvent, PropertyPoller, RuntimeEvent

from .const import DOMAIN, ISSUE_RUNTIME_CLIENT_ERROR, ISSUE_RUNTIME_INACTIVE
from .coordinator import EoliaHEMSCoordinator
from .health import RuntimeHealth

_LOGGER = logging.getLogger(__name__)

class RuntimeIssueMonitor:
    """Monitor runtime activity and surface repair issues."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: EoliaHEMSCoordinator,
        *,
        threshold: float,
        interval: timedelta,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialise the monitor with inactivity threshold and check interval."""
        self._hass: HomeAssistant = hass
        self._coordinator: EoliaHEMSCoordinator = coordinator
        self._threshold: float = threshold
        self._interval: timedelta = interval
        self._monotonic: Callable[[], float] = monotonic
        self._cancel_interval: Callable[[], None] | None = None
        self._inactivity_issue_active: bool = False
        self._client_issue_active: bool = False
        self._unavailable_device_keys: set[str] = set()

    def start(self) -> None:
        """Begin checking for runtime inactivity.

        Seeds ``last_runtime_activity_at`` with the current monotonic time so
        that a total absence of incoming frames (never a single activity
        observed) still trips the threshold. Without this baseline the
        inactivity check silently skips every tick while
        ``last_runtime_activity_at is None``.
        """
        if self._cancel_interval is not None:
            return
        self.record_activity(self._monotonic())
        self._cancel_interval = async_track_time_interval(
            self._hass, self._async_check_runtime, self._interval
        )

    def stop(self) -> None:
        """Stop monitoring and clear any active issue."""
        if self._cancel_interval:
            self._cancel_interval()
            self._cancel_interval = None
        self._clear_inactivity_issue_if_needed()
        self.clear_client_error()
        self._unavailable_device_keys.clear()

    @callback
    def record_activity(self, timestamp: float) -> None:
        """Note that activity was observed and clear issues if present."""
        self._coordinator.record_runtime_activity(timestamp)
        self._clear_inactivity_issue_if_needed()

    @callback
    def _async_check_runtime(self, _now: datetime) -> None:
        unavailable_device_keys = {
            device_key
            for device_key in self._coordinator.data
            if self._coordinator.device_manager.is_device_polling_available(device_key)
            is False
        }
        if unavailable_device_keys != self._unavailable_device_keys:
            self._unavailable_device_keys = unavailable_device_keys
            self._coordinator.async_update_listeners()

        last_activity_at = self._coordinator.last_runtime_activity_at
        if last_activity_at is None:
            return
        if self._monotonic() - last_activity_at < self._threshold:
            self._clear_inactivity_issue_if_needed()
            return
        if self._inactivity_issue_active:
            return
        minutes = max(int(self._threshold // 60), 1)
        issue_registry.async_create_issue(
            self._hass,
            DOMAIN,
            ISSUE_RUNTIME_INACTIVE,
            issue_domain=DOMAIN,
            is_fixable=False,
            severity=issue_registry.IssueSeverity.WARNING,
            translation_key="runtime_inactive",
            translation_placeholders={"minutes": str(minutes)},
        )
        _LOGGER.warning(
            "No Eolia HEMS frames received for %d minutes; "
            + "devices may be offline",
            minutes,
        )
        self._inactivity_issue_active = True
        self._coordinator.async_update_listeners()

    @callback
    def _clear_inactivity_issue_if_needed(self) -> None:
        if self._inactivity_issue_active:
            issue_registry.async_delete_issue(self._hass, DOMAIN, ISSUE_RUNTIME_INACTIVE)
            self._inactivity_issue_active = False
            _LOGGER.info("Eolia HEMS communication restored")
            self._coordinator.async_update_listeners()

    @callback
    def record_client_error(self, message: str) -> None:
        issue_registry.async_create_issue(
            self._hass,
            DOMAIN,
            ISSUE_RUNTIME_CLIENT_ERROR,
            issue_domain=DOMAIN,
            is_fixable=False,
            severity=issue_registry.IssueSeverity.ERROR,
            translation_key="runtime_client_error",
            translation_placeholders={"error": message},
        )
        self._client_issue_active = True

    @callback
    def clear_client_error(self) -> None:
        if self._client_issue_active:
            issue_registry.async_delete_issue(self._hass, DOMAIN, ISSUE_RUNTIME_CLIENT_ERROR)
            self._client_issue_active = False


class RuntimeController:
    def __init__(
        self,
        hass: HomeAssistant,
        entry: EoliaHEMSConfigEntry,
        *,
        client: HemsClient,
        coordinator: EoliaHEMSCoordinator,
        property_poller: PropertyPoller,
        issue_monitor: RuntimeIssueMonitor,
        health: RuntimeHealth,
        ) -> None:
        self._hass: HomeAssistant = hass
        self._entry: ConfigEntry = entry
        self.client: HemsClient = client
        self.coordinator: EoliaHEMSCoordinator = coordinator
        self.property_poller: PropertyPoller = property_poller
        self.issue_monitor: RuntimeIssueMonitor = issue_monitor
        self.health: RuntimeHealth = health
        self._restart_lock: asyncio.Lock = asyncio.Lock()
        self._error_tasks: set[asyncio.Task[None]] = set()
        self.unsubscribe_runtime: Callable[[], None] = lambda: None

    async def async_start(self) -> None:
        await self.coordinator.device_manager.async_start()
        unsubscribe = self.client.subscribe(self._handle_runtime_event)
        try:
            await self.client.start()
        except OSError as err:
            unsubscribe()
            await self.coordinator.device_manager.async_stop()
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="runtime_start_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self.unsubscribe_runtime = unsubscribe

        self.coordinator.async_set_updated_data({})

        self.issue_monitor.start()

        self.property_poller.start()

    async def async_stop(self) -> None:
        self.unsubscribe_runtime()
        self.issue_monitor.stop()
        self.property_poller.stop()
        for task in tuple(self._error_tasks):
            _ = task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._error_tasks.clear()
        await self.coordinator.device_manager.async_stop()
        await self.client.stop()

    @callback
    def _handle_runtime_event(self, event: RuntimeEvent) -> None:
        if not isinstance(event, HemsErrorEvent):
            return
        task = self._entry.async_create_background_task(
            self._hass,
            self._async_handle_runtime_error(event),
            name="eolia_hems_runtime_error",
        )
        self._error_tasks.add(task)
        task.add_done_callback(self._error_tasks.discard)

    async def _async_handle_runtime_error(self, event: HemsErrorEvent) -> None:
        self.health.last_client_error = str(event.error)
        self.health.last_client_error_at = event.received_at
        _LOGGER.warning(
            "Eolia HEMS client encountered an error: %s",
            event.error,
        )
        self.issue_monitor.record_client_error(str(event.error))
        await self._async_restart_runtime()

    async def _async_restart_runtime(self) -> None:
        if self._restart_lock.locked():
            return
        async with self._restart_lock:
            self.health.restart_attempts += 1
            try:
                await self.client.stop()
            except (
                OSError,
                RuntimeError,
            ) as err:
                _LOGGER.debug("Failed to stop Eolia HEMS runtime client: %s", err)
            try:
                await self.client.start()
            except OSError as err:
                _LOGGER.error("Failed to restart Eolia HEMS runtime client: %s", err)
                self.health.last_client_error = str(err)
                self.health.last_client_error_at = time.monotonic()
                self.issue_monitor.record_client_error(str(err))
                return
            self.health.last_restart_at = time.monotonic()
            self.issue_monitor.clear_client_error()
            self.issue_monitor.record_activity(time.monotonic())
            self.coordinator.async_set_updated_data(
                dict(self.coordinator.device_manager.data)
            )


EoliaHEMSConfigEntry = ConfigEntry[RuntimeController]
