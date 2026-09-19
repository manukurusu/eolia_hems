"""Switch platform for the Eolia HEMS integration."""


from __future__ import annotations

from dataclasses import dataclass
from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
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

@dataclass(frozen=True, kw_only=True)
class EoliaHEMSSwitchEntityDescription(
    SwitchEntityDescription, EoliaHEMSEntityDescription
    ):
    prop: BinaryProp

    @classmethod
    @override
    def build_from_entity_def(
        cls,
        entity_def: EntityDefinition,
        ) -> EoliaHEMSSwitchEntityDescription:
        return cls(
            key=f"{entity_def.epc:02x}",
            prop=BinaryProp.from_entity_def(entity_def),
            **cls._common_kwargs(entity_def),
        )

_DESCRIPTIONS: dict[int, list[EoliaHEMSSwitchEntityDescription]] = (
    build_platform_descriptions(Platform.SWITCH, EoliaHEMSSwitchEntityDescription)
)

async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EoliaHEMSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
    setup_common_platform(
        entry,
        async_add_entities,
        Platform.SWITCH.value,
        _DESCRIPTIONS,
        EoliaHEMSSwitch,
    )

class EoliaHEMSSwitch(
    EoliaHEMSDescribedEntity[EoliaHEMSSwitchEntityDescription], SwitchEntity
    ):
    @property
    @override
    def is_on(self) -> bool | None:
        return self.description.prop.get(self._node)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        self._send_prop(self.description.prop, True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        self._send_prop(self.description.prop, False)
