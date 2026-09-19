"""Button platform for the Eolia HEMS integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
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
from .prop import EnumProp
from .runtime import EoliaHEMSConfigEntry

PARALLEL_UPDATES = 0

@dataclass(frozen=True, kw_only=True)
class EoliaHEMSButtonEntityDescription(
    ButtonEntityDescription,
    EoliaHEMSEntityDescription,
    ):
    prop: EnumProp
    press_value: str

    @classmethod
    @override
    def build_from_entity_def(
        cls,
        entity_def: EntityDefinition,
        ) -> EoliaHEMSButtonEntityDescription:
        if not entity_def.enum_values:
            raise ValueError(
                f"Button entity requires enum values, but {entity_def.id} has none"
            )
        return cls(
            key=f"{entity_def.epc:02x}",
            prop=EnumProp.from_entity_def(entity_def),
            press_value=entity_def.enum_values[0].key,
            **cls._common_kwargs(entity_def),
        )

_DESCRIPTIONS: dict[int, list[EoliaHEMSButtonEntityDescription]] = (
    build_platform_descriptions(Platform.BUTTON, EoliaHEMSButtonEntityDescription)
)

async def async_setup_entry(
    _hass: HomeAssistant,
    entry: EoliaHEMSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
    setup_common_platform(
        entry,
        async_add_entities,
        Platform.BUTTON.value,
        _DESCRIPTIONS,
        EoliaHEMSButton,
    )

class EoliaHEMSButton(
    EoliaHEMSDescribedEntity[EoliaHEMSButtonEntityDescription],
    ButtonEntity
    ):
    @override
    async def async_press(self) -> None:
        self._send_prop(self.description.prop, self.description.press_value)
