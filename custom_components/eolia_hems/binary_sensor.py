"""Binary sensor platform for the Eolia HEMS integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from propcache.api import cached_property
from pyhems import EntityDefinition

from .entity import (
    EoliaHEMSDescribedEntity,
    EoliaHEMSEntityDescription,
    build_platform_descriptions,
    setup_common_platform,
)
from .prop import BinaryProp
from .runtime import EoliaHEMSConfigEntry

PARALLEL_UPDATES = 0


def _infer_binary_device_class(
    entity_def: EntityDefinition,
    ) -> BinarySensorDeviceClass | None:
    if "fault" in entity_def.name_en.lower():
        return BinarySensorDeviceClass.PROBLEM
    return None

@dataclass(frozen=True, kw_only=True)
class EoliaHEMSBinarySensorEntityDescription(
    BinarySensorEntityDescription, EoliaHEMSEntityDescription
    ):
    prop: BinaryProp

    @classmethod
    @override
    def build_from_entity_def(
        cls,
        entity_def: EntityDefinition,
    ) -> EoliaHEMSBinarySensorEntityDescription:
        return cls(
            key=f"{entity_def.epc:02x}",
            device_class=_infer_binary_device_class(entity_def),
            prop=BinaryProp.from_entity_def(entity_def),
            **cls._common_kwargs(entity_def),
        )

_DESCRIPTIONS: dict[int, list[EoliaHEMSBinarySensorEntityDescription]] = (
    build_platform_descriptions(
        Platform.BINARY_SENSOR, EoliaHEMSBinarySensorEntityDescription
    )
)

async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EoliaHEMSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
    setup_common_platform(
        entry,
        async_add_entities,
        Platform.BINARY_SENSOR.value,
        _DESCRIPTIONS,
        EoliaHEMSBinarySensor,
    )

class EoliaHEMSBinarySensor(
    EoliaHEMSDescribedEntity[EoliaHEMSBinarySensorEntityDescription],
    BinarySensorEntity,
    ):
    @cached_property
    @override
    def is_on(self) -> bool | None:
        return self.description.prop.get(self._node)
