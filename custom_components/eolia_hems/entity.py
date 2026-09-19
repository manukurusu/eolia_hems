"""Base entity classes for the Eolia HEMS integration."""


import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self, cast, override

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pyhems import REGISTRY, EntityDefinition, NodeState, Property

from .const import (
    DEDICATED_PLATFORM_EPCS,
    DOMAIN,
    EXCLUDED_EPCS_BY_CLASS,
    SUPPORTED_DEVICE_CLASSES,
    get_entity_category,
)
from .coordinator import EoliaHEMSCoordinator
from .prop import Prop
from .runtime import EoliaHEMSConfigEntry

_LOGGER = logging.getLogger(__name__)

def can_process_enum_values(entity: EntityDefinition) -> bool:
    if not entity.enum_values:
        return True

    keys: set[str] = set()
    for enum_val in entity.enum_values:
        if enum_val.key in keys:
            return False
        keys.add(enum_val.key)

    return True

def infer_platform(entity: EntityDefinition) -> Platform | None:
    if entity.get != "notApplicable":
        writable = entity.set != "notApplicable"
        if entity.enum_values:
            if len(entity.enum_values) == 1:
                return None
            if entity.is_binary:
                return Platform.SWITCH if writable else Platform.BINARY_SENSOR
            return Platform.SELECT if writable else Platform.SENSOR
        if entity.format is None:
            return None
        return Platform.NUMBER if writable else Platform.SENSOR

    if (
        entity.set != "notApplicable"
        and entity.enum_values
        and len(entity.enum_values) == 1
    ):
        return Platform.BUTTON
    return None

def _get_or_build_device_info(
    coordinator: EoliaHEMSCoordinator, node: NodeState
    ) -> DeviceInfo:
    cache = coordinator.device_info_cache
    if (cached := cache.get(node.device_key)) is not None:
        return cached

    suggested_area: str | None = None
    if (location := node.installation_location) is not None:
        suggested_area = location.name

    if node.class_name_en is not None:
        translation_key = f"class_{node.eoj.class_code:04x}"
        translation_placeholders: dict[str, str] | None = None
    else:
        translation_key = "unknown_class"
        translation_placeholders = {
            "class_code": f"0x{node.eoj.class_code:04X}",
        }

    device_info = DeviceInfo(
        identifiers={(DOMAIN, node.device_key)},
        manufacturer=node.manufacturer_name,
        model=node.product_code,
        serial_number=node.serial_number,
        suggested_area=suggested_area,
        translation_key=translation_key,
        translation_placeholders=translation_placeholders,
    )
    cache[node.device_key] = device_info
    return device_info

class EoliaHEMSEntity(CoordinatorEntity[EoliaHEMSCoordinator]):
    _attr_has_entity_name: bool = True

    def __init__(
        self,
        coordinator: EoliaHEMSCoordinator,
        node: NodeState,
        ) -> None:
        super().__init__(coordinator)
        self._node: NodeState = node
        self._attr_device_info: DeviceInfo | ChildDeviceInfo | None = (
            _get_or_build_device_info(coordinator, node)
        )
        self._subscribed_epcs: frozenset[int] = frozenset()
        self._unsub_epc_subscription: Callable[[], None] | None = None

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub_epc_subscription = self.coordinator.device_manager.subscribe_epcs(
            self._node.device_key, self._subscribed_epcs
        )

    @override
    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_epc_subscription is not None:
            self._unsub_epc_subscription()
            self._unsub_epc_subscription = None
        await super().async_will_remove_from_hass()

    @property
    @override
    def available(self) -> bool:
        if not super().available:
            return False
        return (
            self.coordinator.device_manager.is_device_polling_available(
                self._node.device_key
            )
            is not False
        )

    def _send_property(self, epc: int, value: bytes) -> None:
        self._send_properties(properties=[Property(epc=epc, edt=value)])

    def _send_properties(self, properties: list[Property]) -> None:
        node = self._node

        not_writable = [
            prop.epc for prop in properties if prop.epc not in node.set_epcs
        ]

        if not_writable:
            hex_list = ", ".join(f"0x{epc:02X}" for epc in not_writable)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="epc_not_writable",
                translation_placeholders={"epc_list": hex_list},
            )

        config_entry = cast(EoliaHEMSConfigEntry, self.coordinator.config_entry)
        controller = config_entry.runtime_data

        sent = controller.client.set_properties(
            node_id=node.node_id,
            deoj=node.eoj,
            properties=properties,
        )

        if not sent:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="target_node_unknown",
            )

        controller.property_poller.schedule_immediate_poll(node.device_key)

    def _send_prop[ValueT](self, prop: Prop[ValueT], value: ValueT) -> None:
        self._send_properties([prop.make_property(value)])

@dataclass(frozen=True, kw_only=True)
class EoliaHEMSEntityDescription(EntityDescription):
    epc: int
    manufacturer_code: int | None = None
    coefficient_epcs: tuple[int, ...] = ()

    def should_create(self, node: NodeState) -> bool:
        if self.epc not in node.get_epcs and self.epc not in node.set_epcs:
            return False
        if self.manufacturer_code is not None:
            return node.manufacturer_code == self.manufacturer_code
        return True

    @classmethod
    def _common_kwargs(
        cls,
        entity_def: EntityDefinition,
        ) -> dict[str, Any]:
        return {
            "translation_key": entity_def.id,
            "epc": entity_def.epc,
            "entity_category": get_entity_category(entity_def),
            "manufacturer_code": entity_def.manufacturer_code,
            "coefficient_epcs": entity_def.coefficient_epcs or (),
        }

    @classmethod
    def build_from_entity_def(
        cls,
        entity_def: EntityDefinition,
        ) -> Self:
        _LOGGER.debug(entity_def)
        raise NotImplementedError

class EoliaHEMSDescribedEntity[DescriptionT: EoliaHEMSEntityDescription](
    EoliaHEMSEntity
    ):

    description: DescriptionT

    def __init__(
        self,
        coordinator: EoliaHEMSCoordinator,
        node: NodeState,
        description: DescriptionT,
        ) -> None:

        if not description.should_create(node):
            raise ValueError(
                f"Entity created for EPC 0x{description.epc:02X} "
                + "that doesn't meet creation criteria"
            )
        super().__init__(coordinator, node)
        self.description = description
        self.entity_description: EntityDescription = description
        self._attr_unique_id: str | None = f"{node.device_key}-{description.key}"
        self._attr_translation_key: str | None = description.translation_key

        self._subscribed_epcs: frozenset[int] = frozenset(
            {description.epc}
        ) | frozenset(
            description.coefficient_epcs
        )

def build_platform_descriptions[DescriptionT: EoliaHEMSEntityDescription](
    platform_type: Platform,
    description_cls: type[DescriptionT],
    ) -> dict[int, list[DescriptionT]]:
    descriptions: dict[int, list[DescriptionT]] = {}
    for class_code, entity_defs in REGISTRY.entities.items():
        if class_code not in SUPPORTED_DEVICE_CLASSES:
            continue
        excluded = DEDICATED_PLATFORM_EPCS.get(
            class_code, frozenset()
        ) | EXCLUDED_EPCS_BY_CLASS.get(class_code, frozenset())
        descriptions[class_code] = [
            description_cls.build_from_entity_def(entity_def)
            for entity_def in entity_defs
            if infer_platform(entity_def) == platform_type
            and entity_def.epc not in excluded
            and can_process_enum_values(entity_def)
            and not (entity_def.set != "notApplicable" and entity_def.byte_offset > 0)
        ]
    return descriptions

def setup_common_platform[DescriptionT: EoliaHEMSEntityDescription](
    entry: EoliaHEMSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    platform_domain: str,
    descriptions_by_class_code: dict[int, list[DescriptionT]],
    entity_factory: Callable[[EoliaHEMSCoordinator, NodeState, DescriptionT], Entity],
    ) -> None:

    @callback
    def _entity_factory(
        coordinator: EoliaHEMSCoordinator,
        node: NodeState,
        ) -> list[Entity]:
        entities: list[Entity] = []
        for description in descriptions_by_class_code.get(node.eoj.class_code, []):
            if not description.should_create(node):
                _LOGGER.debug(
                    "Skipping %s for %s: EPC 0x%02X not meeting criteria",
                    description.key,
                    node.device_key,
                    description.epc,
                )
                continue
            entities.append(entity_factory(coordinator, node, description))
        return entities

    setup_echonet_lite_device_platform(
        entry,
        async_add_entities,
        platform_domain=platform_domain,
        entity_factory=_entity_factory,
    )

def setup_dedicated_platform[DescriptionT](
    entry: EoliaHEMSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    platform_domain: str,
    descriptions: dict[int, DescriptionT],
    entity_factory: Callable[[EoliaHEMSCoordinator, NodeState, DescriptionT], Entity],
    ) -> None:

    @callback
    def _entity_factory(
        coordinator: EoliaHEMSCoordinator, node: NodeState
        ) -> list[Entity]:
        if (description := descriptions.get(node.eoj.class_code)) is None:
            return []
        return [entity_factory(coordinator, node, description)]

    setup_echonet_lite_device_platform(
        entry,
        async_add_entities,
        platform_domain=platform_domain,
        entity_factory=_entity_factory,
    )

def _has_enabled_entity_candidate(
    hass: HomeAssistant,
    platform_domain: str,
    entities: list[Entity],
    ) -> bool:
    er = entity_registry.async_get(hass)
    for entity in entities:
        if (unique_id := entity.unique_id) is None:
            return True
        if (
            entity_id := er.async_get_entity_id(
                platform_domain, DOMAIN, unique_id
            )
        ) is None:
            return True
        if (entry := er.async_get(entity_id)) is None:
            return True
        if entry.disabled_by is None:
            return True
    return False

def setup_echonet_lite_device_platform(
    entry: EoliaHEMSConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    *,
    platform_domain: str,
    entity_factory: Callable[[EoliaHEMSCoordinator, NodeState], list[Entity]],
    ) -> None:
    coordinator = entry.runtime_data.coordinator
    known_device_keys: set[str] = set()

    @callback
    def _async_check_new_devices() -> None:
        new_keys = coordinator.data.keys() - known_device_keys
        if not new_keys:
            return
        known_device_keys.update(new_keys)
        new_entities: list[Entity] = []
        for device_key in new_keys:
            node = coordinator.data.get(device_key)
            if node is None:
                continue
            device_entities = entity_factory(coordinator, node)
            if not device_entities or not _has_enabled_entity_candidate(
                coordinator.hass, platform_domain, device_entities
            ):
                _ = coordinator.device_manager.subscribe_epcs(device_key, frozenset())
            new_entities.extend(device_entities)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_check_new_devices))

    _async_check_new_devices()
