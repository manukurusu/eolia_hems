"""Climate platform for the Eolia HEMS integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
)
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    Platform,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyhems import DeviceClass, NodeState

from .const import (
    DEDICATED_PLATFORM_REQUIRED_EPCS,
    DOMAIN,
    EPC_AIR_FLOW_VERTICAL,
    EPC_AUTO_DIRECTION,
    EPC_FAN_SPEED,
    EPC_OPERATION_MODE,
    EPC_OPERATION_STATUS,
    EPC_ROOM_HUMIDITY,
    EPC_ROOM_TEMPERATURE,
    EPC_SPECIAL_STATE,
    EPC_TARGET_TEMPERATURE,
)
from .coordinator import EoliaHEMSCoordinator
from .entity import EoliaHEMSEntity, setup_dedicated_platform
from .prop import BinaryProp, EnumProp, NumericProp
from .runtime import EoliaHEMSConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_SUPPORTED_HVAC_MODES: list[HVACMode] = [
    HVACMode.OFF,
    HVACMode.AUTO,
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.DRY,
]

_PYHEMS_TO_HA_ACTION: dict[str, HVACAction | None] = {
    "other": HVACAction.IDLE,
    "auto": None,
    "cooling": HVACAction.COOLING,
    "heating": HVACAction.HEATING,
    "dehumidification": HVACAction.DRYING,
    "circulation": HVACAction.FAN,
}

_PYHEMS_TO_HA_MODE: dict[str, HVACMode] = {
    "auto": HVACMode.AUTO,
    "cooling": HVACMode.COOL,
    "heating": HVACMode.HEAT,
    "dehumidification": HVACMode.DRY,
}

_PYHEMS_SPECIAL_STATE_TO_ACTION: dict[str, HVACAction | None] = {
    "normal": None,
    "defrosting": HVACAction.DEFROSTING,
    "preheating": HVACAction.PREHEATING,
    "heat_removal": HVACAction.IDLE,
}

_HA_TO_PYHEMS_MODE: dict[HVACMode, str] = {
    HVACMode.AUTO: "auto",
    HVACMode.COOL: "cooling",
    HVACMode.HEAT: "heating",
    HVACMode.DRY: "dehumidification",
}

SWING_AUTO = "auto"
_A1_AUTO = "auto"
_A1_NON_AUTOMATIC = "non_auto"

@dataclass(frozen=True, kw_only=True)
class EoliaHEMSClimateEntityDescription(ClimateEntityDescription):
    op_status: BinaryProp
    op_mode_prop: EnumProp
    special_state_prop: EnumProp
    target_temp_prop: NumericProp
    room_temp_prop: NumericProp
    humidity_prop: NumericProp
    fan_mode_prop: EnumProp
    auto_direction_prop: EnumProp
    vertical_direction_prop: EnumProp

_DESCRIPTIONS: dict[int, EoliaHEMSClimateEntityDescription] = {
    DeviceClass.HOME_AIR_CONDITIONER: EoliaHEMSClimateEntityDescription(
        key="climate",
        op_status=BinaryProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_OPERATION_STATUS
        ),
        op_mode_prop=EnumProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_OPERATION_MODE
        ),
        special_state_prop=EnumProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_SPECIAL_STATE
        ),
        target_temp_prop=NumericProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_TARGET_TEMPERATURE
        ),
        room_temp_prop=NumericProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_ROOM_TEMPERATURE
        ),
        humidity_prop=NumericProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_ROOM_HUMIDITY
        ),
        fan_mode_prop=EnumProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_FAN_SPEED
        ),
        auto_direction_prop=EnumProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_AUTO_DIRECTION
        ),
        vertical_direction_prop=EnumProp.from_registry(
            DeviceClass.HOME_AIR_CONDITIONER, EPC_AIR_FLOW_VERTICAL
        ),
    )
}

async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EoliaHEMSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_dedicated_platform(
        entry,
        async_add_entities,
        Platform.CLIMATE.value,
        _DESCRIPTIONS,
        EoliaHEMSClimate,
    )

class EoliaHEMSClimate(EoliaHEMSEntity, ClimateEntity):
    entity_description: EoliaHEMSClimateEntityDescription
    _attr_name: str | None  = None
    _attr_temperature_unit: UnitOfTemperature = UnitOfTemperature.CELSIUS
    _attr_translation_key: str = "climate"
    _attr_hvac_modes: list[HVACMode] = _SUPPORTED_HVAC_MODES

    def __init__(
        self,
        coordinator: EoliaHEMSCoordinator,
        node: NodeState,
        description: EoliaHEMSClimateEntityDescription,
        ) -> None:
        super().__init__(coordinator, node)
        self.entity_description = description
        self._attr_unique_id: str = f"{node.device_key}-{description.key}"
        self._subscribed_epcs: frozenset[int] = DEDICATED_PLATFORM_REQUIRED_EPCS.get(
            node.eoj.class_code, frozenset()
        )
        if description.target_temp_prop.min_value is not None:
            self._attr_min_temp: float = description.target_temp_prop.min_value
        if description.target_temp_prop.max_value is not None:
            self._attr_max_temp: float = description.target_temp_prop.max_value
        self._attr_target_temperature_step:float = description.target_temp_prop.step
        self._attr_precision: float = description.target_temp_prop.precision

        features = ClimateEntityFeature(0)
        swing_modes: list[str] | None = None

        if EPC_TARGET_TEMPERATURE in node.set_epcs:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE

        if EPC_FAN_SPEED in node.set_epcs:
            features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes:list[str] = description.fan_mode_prop.options

        if EPC_AUTO_DIRECTION in node.set_epcs:
            modes = self._build_direction_swing_modes(description, node)
            if modes:
                features |= ClimateEntityFeature.SWING_MODE
                swing_modes = modes
        if EPC_OPERATION_STATUS in node.set_epcs:
            features |= ClimateEntityFeature.TURN_ON
            features |= ClimateEntityFeature.TURN_OFF
        self._attr_supported_features: ClimateEntityFeature = features
        self._attr_swing_modes: list[str] | None = swing_modes

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        if (status := self._operation_status()) is None:
            return None
        if not status:
            return HVACMode.OFF
        key = self.entity_description.op_mode_prop.get(self._node)
        return _PYHEMS_TO_HA_MODE.get(key) if key is not None else None

    @staticmethod
    def _build_direction_swing_modes(
        description: EoliaHEMSClimateEntityDescription,
        node: NodeState,
        ) -> list[str]:
        a1_options = description.auto_direction_prop.options
        modes: list[str] = []
        if _A1_AUTO in a1_options:
            modes.append(SWING_AUTO)
        if (
            EPC_AIR_FLOW_VERTICAL in node.set_epcs
            and _A1_NON_AUTOMATIC in a1_options
        ):
            modes.extend(description.vertical_direction_prop.options)
        return modes

    def _operation_status(self) -> bool | None:
        return self.entity_description.op_status.get(self._node)

    @property
    @override
    def hvac_action(self) -> HVACAction | None:
        special_key = self.entity_description.special_state_prop.get(self._node)
        if (special_key is not None
            and special_key in _PYHEMS_SPECIAL_STATE_TO_ACTION
            and (action := _PYHEMS_SPECIAL_STATE_TO_ACTION[special_key]) is not None):
                return action
        if (status := self._operation_status()) is None:
            return None
        if not status:
            return HVACAction.OFF
        if (mode_key := self.entity_description.op_mode_prop.get(self._node)) is None:
            return None
        if mode_key not in _PYHEMS_TO_HA_ACTION:
            return None
        action = _PYHEMS_TO_HA_ACTION[mode_key]
        return action if action is not None else self._infer_auto_action()

    @property
    @override
    def fan_mode(self) -> str | None:
        return self.entity_description.fan_mode_prop.get(self._node)

    @property
    @override
    def swing_mode(self) -> str | None:
        a1 = self.entity_description.auto_direction_prop.get(self._node)
        if a1 is None:
            return None
        if a1 == _A1_AUTO:
            return SWING_AUTO
        return self.entity_description.vertical_direction_prop.get(self._node)

    @property
    @override
    def current_temperature(self) -> float | None:
        value = self.entity_description.room_temp_prop.get(self._node)
        return float(value) if value is not None else None

    @property
    @override
    def current_humidity(self) -> float | None:
        value = self.entity_description.humidity_prop.get(self._node)
        return float(value) if value is not None else None

    @property
    @override
    def target_temperature(self) -> float | None:
        value = self.entity_description.target_temp_prop.get(self._node)
        return float(value) if value is not None else None

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        _LOGGER.debug(
            "async_set_hvac_mode: Requested mode=%s, current mode=%s",
            hvac_mode,
            self.hvac_mode,
        )

        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return

        if EPC_OPERATION_MODE not in self._node.set_epcs:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="epc_not_writable",
                translation_placeholders={"epc_list": f"0x{EPC_OPERATION_MODE:02X}"},
            )

        if EPC_OPERATION_STATUS not in self._node.set_epcs:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="epc_not_writable",
                translation_placeholders={"epc_list": f"0x{EPC_OPERATION_STATUS:02X}"},
            )

        pyhems_mode = _HA_TO_PYHEMS_MODE.get(hvac_mode)
        if pyhems_mode is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_value",
                translation_placeholders={"value": str(hvac_mode)},
            )
        self._send_properties(
            [
                self.entity_description.op_mode_prop.make_property(pyhems_mode),
                self.entity_description.op_status.make_property(True),
            ]
        )

    @override
    async def async_turn_on(self) -> None:
        if EPC_OPERATION_STATUS not in self._node.set_epcs:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="epc_not_writable",
                translation_placeholders={"epc_list": f"0x{EPC_OPERATION_STATUS:02X}"},
            )
        self._send_prop(self.entity_description.op_status, True)

    @override
    async def async_turn_off(self) -> None:
        if EPC_OPERATION_STATUS not in self._node.set_epcs:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="epc_not_writable",
                translation_placeholders={"epc_list": f"0x{EPC_OPERATION_STATUS:02X}"},
            )
        self._send_prop(self.entity_description.op_status, False)

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE not in kwargs or kwargs[ATTR_TEMPERATURE] is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="target_temperature_required",
            )
        if EPC_TARGET_TEMPERATURE not in self._node.set_epcs:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="epc_not_writable",
                translation_placeholders={
                    "epc_list": f"0x{EPC_TARGET_TEMPERATURE:02X}"
                },
            )
        temperature = float(kwargs[ATTR_TEMPERATURE])
        clamped = min(max(temperature, self._attr_min_temp), self._attr_max_temp)
        self._send_prop(self.entity_description.target_temp_prop, clamped)

    @override
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in (self._attr_fan_modes or ()):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_value",
                translation_placeholders={"value": fan_mode},
            )
        self._send_prop(self.entity_description.fan_mode_prop, fan_mode)

    @override
    async def async_set_swing_mode(self, swing_mode: str) -> None:
        desc = self.entity_description
        if swing_mode == SWING_AUTO:
            self._send_prop(desc.auto_direction_prop, _A1_AUTO)
            return
        if swing_mode not in desc.vertical_direction_prop.options:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_value",
                translation_placeholders={"value": swing_mode},
            )
        self._send_properties(
            [
                desc.auto_direction_prop.make_property(_A1_NON_AUTOMATIC),
                desc.vertical_direction_prop.make_property(swing_mode),
            ]
        )

    def _infer_auto_action(self) -> HVACAction:
        target = self.target_temperature
        current = self.current_temperature
        if target is None or current is None:
            return HVACAction.IDLE
        if target <= current:
            return HVACAction.COOLING
        return HVACAction.HEATING
