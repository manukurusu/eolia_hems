"""Sensor platform for the Eolia HEMS integration."""


from __future__ import annotations

from dataclasses import dataclass
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyhems import EntityDefinition, EnumCodec, get_codec

from .const import infer_device_classes, infer_ha_unit
from .entity import (
    EoliaHEMSDescribedEntity,
    EoliaHEMSEntityDescription,
    build_platform_descriptions,
    setup_common_platform,
)
from .prop import EnumProp, NumericProp
from .runtime import EoliaHEMSConfigEntry

PARALLEL_UPDATES = 0

def _infer_state_class(entity_def: EntityDefinition) -> SensorStateClass:
    if "cumulative" in entity_def.name_en.lower():
        return SensorStateClass.TOTAL_INCREASING
    return SensorStateClass.MEASUREMENT

@dataclass(frozen=True, kw_only=True)
class EoliaHEMSSensorEntityDescription(
    SensorEntityDescription, EoliaHEMSEntityDescription
    ):
    prop: EnumProp | NumericProp

    @classmethod
    @override
    def build_from_entity_def(
        cls,
        entity_def: EntityDefinition,
    ) -> EoliaHEMSSensorEntityDescription:
        codec = get_codec(entity_def)
        if isinstance(codec, EnumCodec):
            enum_prop = EnumProp.from_entity_def(entity_def)
            return cls(
                key=f"{entity_def.epc:02x}",
                device_class=SensorDeviceClass.ENUM,
                options=enum_prop.options,
                prop=enum_prop,
                **cls._common_kwargs(entity_def),
            )
        return cls(
            key=f"{entity_def.epc:02x}_{entity_def.byte_offset}",
            device_class=infer_device_classes(entity_def)[0],
            native_unit_of_measurement=infer_ha_unit(entity_def),
            state_class=_infer_state_class(entity_def),
            prop=NumericProp.from_entity_def(entity_def),
            **cls._common_kwargs(entity_def),
        )

_DESCRIPTIONS: dict[int, list[EoliaHEMSSensorEntityDescription]] = (
    build_platform_descriptions(Platform.SENSOR, EoliaHEMSSensorEntityDescription)
)

async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EoliaHEMSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
    setup_common_platform(
        entry,
        async_add_entities,
        Platform.SENSOR.value,
        _DESCRIPTIONS,
        EoliaHEMSSensor,
    )

class EoliaHEMSSensor(
    EoliaHEMSDescribedEntity[EoliaHEMSSensorEntityDescription],
    SensorEntity,
    ):
    @property
    @override
    def native_value(self) -> float | int | str | None:
        return self.description.prop.get(self._node)
