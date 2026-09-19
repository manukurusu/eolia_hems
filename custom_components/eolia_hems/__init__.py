"""The Eolia HEMS integration."""

import logging
from typing import (
    Final,
    cast,
)

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry
from pyhems import (
    REGISTRY,
    DeviceManager,
    HemsClient,
    PropertyPoller,
    PropertyRole,
    get_collection_binding,
)

from .const import (
    COLLECTION_SENSOR_PROJECTIONS,
    CONF_INTERFACE,
    DEDICATED_PLATFORM_REQUIRED_EPCS,
    DEFAULT_FAST_POLL_INTERVAL,
    DEFAULT_INTERFACE,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    EPC_INSTALLATION_LOCATION,
    EXCLUDED_EPCS_BY_CLASS,
    RUNTIME_MONITOR_INTERVAL,
    RUNTIME_MONITOR_MAX_SILENCE,
    SUPPORTED_DEVICE_CLASSES,
)
from .coordinator import EoliaHEMSCoordinator
from .health import RuntimeHealth
from .runtime import (
    EoliaHEMSConfigEntry,
    RuntimeController,
    RuntimeIssueMonitor,
)

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
]

_LOGGER = logging.getLogger(__name__)

def _collection_projection_epcs(class_code: int) -> frozenset[int]:
    """Return the EPCs needed by class_code's curated collection projections."""
    epcs: set[int] = set()
    for projection in COLLECTION_SENSOR_PROJECTIONS:
        if projection.class_code != class_code:
            continue
        epcs.add(projection.result_epc)
        epcs.update(projection.coefficient_epcs)
        binding = get_collection_binding(class_code, projection.result_epc)
        if binding is not None and binding.count_epc is not None:
            epcs.add(binding.count_epc)
    return frozenset(epcs)

def _build_monitored_epcs() -> dict[int, frozenset[int]]:
    result: dict[int, frozenset[int]] = {
        class_code: frozenset(entity_def.epc for entity_def in entity_defs)
        for class_code, entity_defs in REGISTRY.entities.items()
    }
    for class_code, epcs in DEDICATED_PLATFORM_REQUIRED_EPCS.items():
        result[class_code] = result.get(class_code, frozenset()) | epcs
    for class_code in list(result):
        result[class_code] = result[class_code] | {EPC_INSTALLATION_LOCATION}
    for class_code, excluded in EXCLUDED_EPCS_BY_CLASS.items():
        result[class_code] = result.get(class_code, frozenset()) - excluded
    for class_code in {p.class_code for p in COLLECTION_SENSOR_PROJECTIONS}:
        result[class_code] = result.get(class_code, frozenset()) | (
            _collection_projection_epcs(class_code)
        )
    return {
        class_code: epcs
        for class_code, epcs in result.items()
        if class_code in SUPPORTED_DEVICE_CLASSES
    }

def _build_fast_poll_epcs() -> dict[int, frozenset[int]]:
    result: dict[int, frozenset[int]] = {}
    for class_code, entity_defs in REGISTRY.entities.items():
        candidates = frozenset(
            entity_def.epc
            for entity_def in entity_defs
            if entity_def.role is PropertyRole.INSTANTANEOUS
        )
        candidates &= _MONITORED_EPCS.get(class_code, frozenset())
        if candidates:
            result[class_code] = candidates
    for projection in COLLECTION_SENSOR_PROJECTIONS:
        if not projection.fast_poll:
            continue
        candidates = frozenset({projection.result_epc}) & _MONITORED_EPCS.get(
            projection.class_code, frozenset()
        )
        if candidates:
            result[projection.class_code] = (
                result.get(projection.class_code, frozenset()) | candidates
            )
    return {
        class_code: epcs
        for class_code, epcs in result.items()
        if class_code in SUPPORTED_DEVICE_CLASSES
    }

_MONITORED_EPCS: Final[dict[int, frozenset[int]]] = _build_monitored_epcs()

_FAST_POLL_EPCS: Final[dict[int, frozenset[int]]] = _build_fast_poll_epcs()

async def async_migrate_entry(
    hass: HomeAssistant, entry: EoliaHEMSConfigEntry
    ) -> bool:
    """Migrate old config entry to new format."""
    if entry.version == 1 and entry.minor_version < 1:
        # Version 1.0 → 1.1: Move CONF_INTERFACE from options to data
        new_data = dict(entry.data)
        new_options = dict(entry.options)
        if CONF_INTERFACE in new_options:
            new_data[CONF_INTERFACE] = new_options.pop(CONF_INTERFACE)
        new_options.clear()
        _ = hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, minor_version=1
        )
        _LOGGER.debug("Migrated config entry to version 1.1")
    return True

async def async_setup_entry(
    hass: HomeAssistant,
    entry: EoliaHEMSConfigEntry,
    ) -> bool:
    """Set up Eolia HEMS from a config entry."""

    interface = cast(str, entry.data.get(CONF_INTERFACE, DEFAULT_INTERFACE))
    _LOGGER.debug("Setting up Eolia HEMS with interface %s", interface)
    _LOGGER.debug(
        "Monitored EPCs (polling/notification) per device class: %s",
        {
            hex(class_code): " ".join(f"{epc:02x}" for epc in epcs)
            for class_code, epcs in _MONITORED_EPCS.items()
        },
    )
    _LOGGER.debug(
        "Fast-poll EPCs per device class: %s",
        {
            hex(class_code): " ".join(f"{epc:02x}" for epc in epcs)
            for class_code, epcs in _FAST_POLL_EPCS.items()
        },
    )

    client = HemsClient(interface=interface)

    device_manager = DeviceManager(
        client=client,
        monitored_epcs=_MONITORED_EPCS,
        class_code_filter=SUPPORTED_DEVICE_CLASSES,
        fast_epcs=_FAST_POLL_EPCS,
    )

    runtime_health = RuntimeHealth()

    coordinator = EoliaHEMSCoordinator(
        hass,
        config_entry=entry,
        device_manager=device_manager,
        health=runtime_health,
    )

    issue_monitor = RuntimeIssueMonitor(
        hass,
        coordinator,
        threshold=RUNTIME_MONITOR_MAX_SILENCE.total_seconds(),
        interval=RUNTIME_MONITOR_INTERVAL,
    )
    _ = device_manager.on_runtime_activity(issue_monitor.record_activity)

    property_poller = PropertyPoller(
        device_manager,
        poll_interval=DEFAULT_POLL_INTERVAL,
        fast_poll_interval=DEFAULT_FAST_POLL_INTERVAL,
    )

    controller = RuntimeController(
        hass,
        entry,
        client=client,
        coordinator=coordinator,
        property_poller=property_poller,
        issue_monitor=issue_monitor,
        health=runtime_health,
    )

    await controller.async_start()

    entry.runtime_data = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: EoliaHEMSConfigEntry,
    device_entry: device_registry.DeviceEntry,
    ) -> bool:
    """Remove a config entry from a device.
    Removal is permitted when the device is unknown or its liveness polling
    has failed.
    """

    _LOGGER.debug(hass)

    coordinator = config_entry.runtime_data.coordinator
    device_keys = {
        identifier
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    }
    if not device_keys:
        return True
    return any(
        (node := coordinator.data.get(device_key)) is None
        or node.polling_available is False
        for device_key in device_keys
    )

async def async_unload_entry(
    hass: HomeAssistant, entry: EoliaHEMSConfigEntry,
    ) -> bool:
    """Unload a config entry."""

    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    runtime = entry.runtime_data
    if runtime:
        await runtime.async_stop()

    return True
