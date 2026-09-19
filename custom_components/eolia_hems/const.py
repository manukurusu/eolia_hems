"""Constants for the Eolia HEMS integration."""


import re
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    LIGHT_LUX,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfDensity,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfRatio,
    UnitOfSoundPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from pyhems import (
    DeviceClass,
    EntityDefinition,
    PropertyRole,
)

DOMAIN = "eolia_hems"
CONF_INTERFACE = "interface"
DEFAULT_INTERFACE = "0.0.0.0"
DEFAULT_POLL_INTERVAL = 60
DEFAULT_FAST_POLL_INTERVAL = 10
ISSUE_RUNTIME_CLIENT_ERROR = "runtime_client_error"
ISSUE_RUNTIME_INACTIVE = "runtime_inactive"

RUNTIME_MONITOR_INTERVAL = timedelta(minutes=1)

RUNTIME_MONITOR_MAX_SILENCE = timedelta(minutes=5)

SUPPORTED_DEVICE_CLASSES: frozenset[int] = frozenset({DeviceClass.HOME_AIR_CONDITIONER})

EPC_OPERATION_STATUS = 0x80
EPC_INSTALLATION_LOCATION = 0x81
EPC_FAN_SPEED = 0xA0
EPC_AUTO_DIRECTION = 0xA1
EPC_SWING_AIR_FLOW = 0xA3
EPC_AIR_FLOW_VERTICAL = 0xA4
EPC_SPECIAL_STATE = 0xAA
EPC_OPERATION_MODE = 0xB0
EPC_TARGET_TEMPERATURE = 0xB3
EPC_ROOM_HUMIDITY = 0xBA
EPC_ROOM_TEMPERATURE = 0xBB

DEDICATED_PLATFORM_EPCS: dict[int, frozenset[int]] = {
    DeviceClass.HOME_AIR_CONDITIONER: frozenset(
        {
            EPC_OPERATION_STATUS,
            EPC_FAN_SPEED,
            EPC_SWING_AIR_FLOW,
            EPC_SPECIAL_STATE,
            EPC_OPERATION_MODE,
            EPC_TARGET_TEMPERATURE,
            EPC_ROOM_HUMIDITY,
            EPC_AUTO_DIRECTION,
            EPC_AIR_FLOW_VERTICAL,
        }
    ),
}

DEDICATED_PLATFORM_REQUIRED_EPCS: dict[int, frozenset[int]] = (
    DEDICATED_PLATFORM_EPCS
    | {
        DeviceClass.HOME_AIR_CONDITIONER: DEDICATED_PLATFORM_EPCS[
            DeviceClass.HOME_AIR_CONDITIONER
        ]
        | frozenset({EPC_ROOM_TEMPERATURE}),
    }
)

EXCLUDED_EPCS_BY_CLASS: dict[int, frozenset[int]] = {
    DeviceClass.HOME_AIR_CONDITIONER: frozenset(
        {
            0x84,  # Measured instantaneous power consumption
            0x87,  # Current limit setting
            0x90,  # ON timer-based reservation setting
            0x94,  # OFF timer-based reservation setting
            0x99,  # Power limit setting
            0xA5,  # Air flow direction (horizontal) setting
            0xAB,  # Non-priority state
            0xB1,  # Automatic temperature control setting
            0xB2,  # Normal/highspeed/silent operation setting
            0xB4,  # Set value of relative humidity in dehumidifying mode
            0xB5,  # Set temperature value in cooling mode
            0xB6,  # Set temperature value in heating mode
            0xB7,  # Set temperature value in dehumidifying mode
            0xB8,  # Rated power consumption (cooling/heating/dehumid/circ)
            0xB9,  # Measured value of current consumption
            0xBC,  # Set temperature value of user remote control
            0xBD,  # Measured cooled air temperature
            0xBE,  # Measured outdoor air temperature
            0xBF,  # Relative temperature setting
            0xC0,  # Ventilation function setting
            0xC1,  # Humidifier function setting
            0xC2,  # Ventilation air flow rate setting
            0xC4,  # Degree of humidification setting
            0xCC,  # Special function setting
            0xCE,  # Thermostat setting override function
            0xCF,  # Air purification mode setting
        }
    ),
}

@dataclass(frozen=True, kw_only=True)
class CollectionFieldProjection:
    item_field: str | None
    translation_key: str
    device_class: SensorDeviceClass
    state_class: SensorStateClass
    unit: str
    unique_id_suffix: str

@dataclass(frozen=True, kw_only=True)
class CollectionSensorProjection:
    class_code: int
    result_epc: int
    max_exposed_items: int
    unique_id_prefix: str
    fields: tuple[CollectionFieldProjection, ...]
    coefficient_epcs: tuple[int, ...] = ()
    fast_poll: bool = False

COLLECTION_SENSOR_PROJECTIONS: tuple[CollectionSensorProjection, ...] = ()

MRA_UNIT_TO_HA_UNIT: dict[str, str | None] = {
    "W": UnitOfPower.WATT,
    "kW": UnitOfPower.KILO_WATT,
    "Wh": UnitOfEnergy.WATT_HOUR,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "MJ": UnitOfEnergy.MEGA_JOULE,
    "Celsius": UnitOfTemperature.CELSIUS,
    "%": UnitOfRatio.PERCENTAGE,
    "%RH": UnitOfRatio.PERCENTAGE,
    "A": UnitOfElectricCurrent.AMPERE,
    "mA": UnitOfElectricCurrent.MILLIAMPERE,
    "V": UnitOfElectricPotential.VOLT,
    "ppm": UnitOfRatio.PARTS_PER_MILLION,
    "lux": LIGHT_LUX,
    "dB": UnitOfSoundPressure.DECIBEL,
    "m/s": UnitOfSpeed.METERS_PER_SECOND,
    "L": UnitOfVolume.LITERS,
    "m3": UnitOfVolume.CUBIC_METERS,
    "m3/h": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "second": UnitOfTime.SECONDS,
    "days": UnitOfTime.DAYS,
    "ms": UnitOfTime.MILLISECONDS,
    "degree": DEGREE,
    "r/min": REVOLUTIONS_PER_MINUTE,
    "µg/m³": UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    "mHz": UnitOfFrequency.MILLIHERTZ,
    # No HA equivalent — MRA string is used as-is.
    "Ah": None,
    "digit": None,
    "klux": None,
    "W/mHz": None,
    "W/sec": None,
}

def infer_ha_unit(entity_def: EntityDefinition) -> str | None:
    unit = entity_def.unit
    if not unit:
        return None
    return (
        MRA_UNIT_TO_HA_UNIT.get(unit, unit) or unit
    )

UNIT_DEVICE_CLASS_RULES: tuple[
    tuple[
        tuple[str, ...],
        tuple[tuple[str, SensorDeviceClass | None, NumberDeviceClass | None], ...],
    ],
    ...,
    ] = (
    (("W", "kW"), (("", SensorDeviceClass.POWER, NumberDeviceClass.POWER),)),
    (("Celsius",), (("", SensorDeviceClass.TEMPERATURE, NumberDeviceClass.TEMPERATURE),)),
    (("%RH",), (("", SensorDeviceClass.HUMIDITY, NumberDeviceClass.HUMIDITY),)),
    (("A", "mA"), (("", SensorDeviceClass.CURRENT, NumberDeviceClass.CURRENT),)),
    (("V",), (("", SensorDeviceClass.VOLTAGE, NumberDeviceClass.VOLTAGE),)),
    (("ppm",), (("", SensorDeviceClass.CO2, None),)),
    (("lux",), (("", SensorDeviceClass.ILLUMINANCE, None),)),
    (("dB",), (("", SensorDeviceClass.SOUND_PRESSURE, None),)),
    (("m/s",), (("", SensorDeviceClass.WIND_SPEED, None),)),
    (("m3/h",), (("", SensorDeviceClass.VOLUME_FLOW_RATE, NumberDeviceClass.VOLUME_FLOW_RATE),)),
    (("second", "days"), (("", SensorDeviceClass.DURATION, NumberDeviceClass.DURATION),)),
    (
        ("%",),
        (
            ("humidity", SensorDeviceClass.HUMIDITY, NumberDeviceClass.HUMIDITY),
            ("battery", SensorDeviceClass.BATTERY, NumberDeviceClass.BATTERY),
            # Number entities never reach these sensor-only keywords, but
            # keeping both columns in the same row keeps the table flat.
            ("remaining", SensorDeviceClass.BATTERY, None),
            ("soc", SensorDeviceClass.BATTERY, None),
            ("moisture", SensorDeviceClass.MOISTURE, NumberDeviceClass.MOISTURE),
        ),
    ),
    (
        ("Wh", "kWh", "MJ"),
        (
            # Static ratings (e.g. "AC chargeable capacity") don't fit
            # measurement device classes.
            ("capacity", None, None),
            ("stored", SensorDeviceClass.ENERGY_STORAGE, NumberDeviceClass.ENERGY_STORAGE),
            ("", SensorDeviceClass.ENERGY, NumberDeviceClass.ENERGY),
        ),
    ),
    (
        ("L",),
        (
            # Static tank capacity is not a variable measurement.
            ("capacity", None, None),
            ("tank", SensorDeviceClass.VOLUME_STORAGE, NumberDeviceClass.VOLUME_STORAGE),
            ("remaining", SensorDeviceClass.VOLUME_STORAGE, NumberDeviceClass.VOLUME_STORAGE),
            ("", SensorDeviceClass.WATER, NumberDeviceClass.WATER),
        ),
    ),
    (
        ("m3",),
        (
            ("gas", SensorDeviceClass.GAS, NumberDeviceClass.GAS),
            ("water", SensorDeviceClass.WATER, NumberDeviceClass.WATER),
            ("", SensorDeviceClass.VOLUME, NumberDeviceClass.VOLUME),
        ),
    ),
    (
        ("µg/m³",),
        (
            ("pm2.5", SensorDeviceClass.PM25, None),
            ("pm25", SensorDeviceClass.PM25, None),
        ),
    ),
)

def infer_device_classes(
    entity_def: EntityDefinition,
    ) -> tuple[SensorDeviceClass | None, NumberDeviceClass | None]:
    unit = entity_def.unit
    if not unit:
        return None, None
    name_lower = entity_def.name_en.lower()
    for units, rules in UNIT_DEVICE_CLASS_RULES:
        if unit not in units:
            continue
        for keyword, sensor_dc, number_dc in rules:
            if keyword == "" or keyword in name_lower:
                return sensor_dc, number_dc
        return None, None
    return None, None

_ROLE_TO_ENTITY_CATEGORY: dict[PropertyRole, EntityCategory | None] = {
    PropertyRole.PRIMARY: None,
    PropertyRole.INSTANTANEOUS: None,
    PropertyRole.SETTING: EntityCategory.CONFIG,
    PropertyRole.STATUS: EntityCategory.DIAGNOSTIC,
    PropertyRole.SPECIFICATION: EntityCategory.DIAGNOSTIC,
}

def get_entity_category(entity_def: EntityDefinition) -> EntityCategory | None:
    return _ROLE_TO_ENTITY_CATEGORY[entity_def.role]

def camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
