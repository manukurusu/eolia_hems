"""Diagnostics support for the Eolia HEMS integration."""


from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from pyhems import (
    DeviceManager,
    NodeState,
)

from .const import (
    CONF_INTERFACE,
    DOMAIN,
)
from .runtime import EoliaHEMSConfigEntry

TO_REDACT = {
    CONF_INTERFACE,
    CONF_UNIQUE_ID,
    "device_key",
    "node_id",
    "serial_number",
}

TO_REDACT_PROPERTY_EPCS = frozenset({0x83, 0x8D})

def _format_epcs(epcs: frozenset[int]) -> str:
    return " ".join([f"{epc:02X}" for epc in sorted(epcs)])

def _format_properties(properties: Mapping[int, bytes]) -> dict[str, str]:
    return {
        f"0x{epc:02X}": REDACTED if epc in TO_REDACT_PROPERTY_EPCS else edt.hex(" ")
        for epc, edt in sorted(properties.items())
    }

def _node_to_dict(node: NodeState, device_manager: DeviceManager) -> dict[str, Any]:
    eoj = node.eoj

    node_dict = {
        "device_key": node.device_key,
        "eoj": f"0x{eoj:06X}",
        "class_code": f"0x{eoj.class_code:04X}",
        "instance": eoj.instance_number,
        "node_id": node.node_id,
        "manufacturer_code": f"0x{node.manufacturer_code:06X}",
        "manufacturer_name_en": node.manufacturer_name_en,
        "manufacturer_name_ja": node.manufacturer_name_ja,
        "product_code": node.product_code,
        "serial_number": node.serial_number,
        "get_epcs": _format_epcs(node.get_epcs),
        "set_epcs": _format_epcs(node.set_epcs),
        "inf_epcs": _format_epcs(node.inf_epcs),
        "attempted_inf_epcs": _format_epcs(node.attempted_inf_epcs),
        "confirmed_inf_epcs": _format_epcs(node.confirmed_inf_epcs),
        "failed_inf_epcs": _format_epcs(node.failed_inf_epcs),
        "poll_epcs": _format_epcs(node.poll_epcs),
        "fast_poll_epcs": _format_epcs(node.fast_poll_epcs),
        "effective_poll_epcs": _format_epcs(
            device_manager.effective_poll_epcs(node.device_key)
        ),
        "effective_fast_poll_epcs": _format_epcs(
            device_manager.effective_fast_poll_epcs(node.device_key)
        ),
        "observed_batch_capacity": node.observed_batch_capacity,
        "properties": _format_properties(node.properties),
    }
    return node_dict

def _add_poller_stats(
    node_dict: dict[str, Any],
    *,
    device_key: str,
    entry: EoliaHEMSConfigEntry,
    ) -> None:
    stats = entry.runtime_data.property_poller.get_device_stats(device_key)
    node_dict["poller"] = {
        "normal_interval": round(stats.normal_interval, 3),
        "fast_interval": (
            None if stats.fast_interval is None else round(stats.fast_interval, 3)
        ),
        "latency_ewma": (
            None if stats.latency_ewma is None else round(stats.latency_ewma, 3)
        ),
        "consecutive_failures": stats.consecutive_failures,
    }

def _get_device_key(device: DeviceEntry) -> str | None:
    for domain, identifier in device.identifiers:
        if domain == DOMAIN:
            return identifier
    return None

async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    entry: EoliaHEMSConfigEntry,
    ) -> dict[str, Any]:
    controller = entry.runtime_data
    coordinator = controller.coordinator
    health = controller.health

    devices: list[dict[str, Any]] = []
    for _, node in sorted(coordinator.data.items()):
        node_dict = _node_to_dict(node, coordinator.device_manager)
        _add_poller_stats(node_dict, device_key=node.device_key, entry=entry)
        devices.append(node_dict)

    data = {
        "config_entry": entry.as_dict(),
        "runtime": {
            "device_count": len(coordinator.data),
            "last_runtime_activity_seen": coordinator.last_runtime_activity_at
            is not None,
            "last_frame_received": coordinator.device_manager.last_frame_received_at
            is not None,
            "health": {
                "last_client_error": health.last_client_error,
                "last_client_error_recorded": health.last_client_error_at is not None,
                "last_restart_recorded": health.last_restart_at is not None,
                "restart_attempts": health.restart_attempts,
            },
            "tasks": {
                "event_consumer_task_done": (
                    coordinator.device_manager.event_consumer_task_done
                ),
            },
        },
        "devices": devices,
    }
    return async_redact_data(data, TO_REDACT)

async def async_get_device_diagnostics(
    _hass: HomeAssistant,
    entry: EoliaHEMSConfigEntry,
    device: DeviceEntry,
    ) -> dict[str, Any]:
    device_key = _get_device_key(device)
    if device_key is None:
        return {"error": "device_not_found", "reason": "missing_identifier"}

    coordinator = entry.runtime_data.coordinator
    node = coordinator.data.get(device_key)
    if node is None:
        return async_redact_data(
            {"device_key": device_key, "node_known": False}, TO_REDACT
        )

    node_dict = _node_to_dict(node, coordinator.device_manager)
    _add_poller_stats(node_dict, device_key=node.device_key, entry=entry)

    return async_redact_data(node_dict, TO_REDACT)
