# Eolia HEMS for Home Assistant

A local, cloud-free Home Assistant integration for **Panasonic Eolia** home air conditioners that speak **ECHONET Lite** over your LAN (device class `0x0130`, "Home air conditioner").

Your air conditioner shows up as a native `climate` entity with heat, cool, dry and auto modes, target temperature, fan levels and vertical louver positions. There is no vendor cloud, no account and no external API. Everything is exchanged with the unit itself through UDP multicast on your local network.

> **Scope.** This integration is deliberately narrow. It targets the Eolia air conditioner models I own and only exposes the features those units actually implement. It is not a general ECHONET Lite integration. For other device types (batteries, solar, EV chargers, water heaters, lights), see the [Acknowledgements](#acknowledgements) for the project this one grew out of.

## Features

- **Fully local.** `local_polling`, talking directly to the unit over ECHONET Lite (UDP `3610`, multicast group `224.0.23.0`).
- **Automatic discovery.** Nothing to type in. Compatible units on the network are found and added as devices.
- **A complete `climate` entity:**
  - HVAC modes: `off`, `auto`, `cool`, `heat`, `dry`
  - Target temperature from **16 °C to 30 °C**, clamped to the range the unit reports
  - Current room temperature and humidity
  - Live `hvac_action`: cooling, heating, drying, idle, defrosting, preheating
  - Fan modes: `auto`, `silent`, and levels 1 to 4
  - Swing modes: `auto` plus five fixed vertical louver positions
  - Turn on and turn off
- **Push and poll.** Units announce changes themselves (ECHONET Lite INF), and a poller fills in the rest: 60 seconds normally, 10 seconds for fast-poll properties.
- **Extra entities** for fault status, fault description, cumulative energy, power-saving operation and a buzzer.
- **Repairs.** If nothing is heard from your devices for five minutes, a repair issue is raised and clears itself when traffic returns.
- **Diagnostics** with serial numbers, node IDs and the network interface redacted.

## Supported devices

| Item | Value |
| --- | --- |
| Manufacturer | Panasonic |
| Product line | Eolia home air conditioners with ECHONET Lite / HEMS support |
| ECHONET Lite class | `0x0130` Home air conditioner |
| Connectivity | Wi-Fi or wired LAN adapter, same network as Home Assistant |

Anything that is not a home air conditioner is ignored on purpose (`SUPPORTED_DEVICE_CLASSES` in `const.py`).

### Properties used

The climate entity is built around these ECHONET Lite properties (EPCs):

| EPC | Property | Used for |
| --- | --- | --- |
| `0x80` | Operation status | On, off |
| `0xA0` | Air flow rate | Fan mode |
| `0xA1` | Automatic air flow direction | Swing `auto` vs. fixed |
| `0xA4` | Air flow direction (vertical) | Fixed swing positions |
| `0xAA` | Special state | Defrosting, preheating |
| `0xB0` | Operation mode | HVAC mode |
| `0xB3` | Set temperature | Target temperature |
| `0xBA` | Room relative humidity | Current humidity |
| `0xBB` | Room temperature | Current temperature |

Properties these units do not implement, or that would duplicate the climate entity, are excluded so you do not end up with a pile of `unavailable` entities. That covers horizontal louvers, per-mode set temperatures, outdoor and cooled-air temperature, timers, humidifier and ventilation settings, air purification, and current or power limits (see `EXCLUDED_EPCS_BY_CLASS`).

### Fan and swing labels

Fan speed is reported as numbered levels and mapped to labels that match the remote control: `auto`, `silent`, then `level_1` to `level_4` with increasing airflow.

| Swing mode | Label | Icon |
| --- | --- | --- |
| `auto` | Auto | `mdi:arrow-decision-auto` |
| `uppermost` | Position 1 | `mdi:arrow-up-thin` |
| `upper_center` | Position 2 | `mdi:arrow-top-right-thin` |
| `central` | Position 3 | `mdi:arrow-right-thin` |
| `lower_center` | Position 4 | `mdi:arrow-bottom-right-thin` |
| `lowermost` | Position 5 | `mdi:arrow-down-thin` |

Choosing a fixed position switches the unit out of automatic direction control and sets the louver in one write. Choosing `auto` hands control back to the unit.

## Requirements

- Home Assistant **2026.9.0** or newer.
- The `pyhems==0.8.11` library, installed automatically.
- A network path for **UDP multicast** between Home Assistant and the unit: same Layer 2 network or VLAN (or a multicast relay), with port `3610` and group `224.0.23.0` allowed. Access points with multicast filtering or client isolation will break discovery.
- ECHONET Lite / HEMS enabled on the air conditioner.

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/manukurusu/eolia_hems` as an **Integration**.
3. Search for **Eolia HEMS**, choose **Download**, then restart Home Assistant.

Releases ship as `eolia_hems.zip`, and HACS installs from that asset.

### Manual

Download `eolia_hems.zip` from the [latest release](https://github.com/manukurusu/eolia_hems/releases), unpack it into `<config>/custom_components/eolia_hems/`, and restart Home Assistant.

## Configuration

Everything is done in the UI.

1. Go to **Settings → Devices & services → Add integration** and search for **Eolia HEMS**.
2. Choose the **network interface** for multicast traffic. Leave it on **Auto** unless your host has several interfaces (Ethernet plus Wi-Fi, Docker bridges), in which case pick the one on the same network as the air conditioner.
3. Submit. Home Assistant checks that it can open the multicast socket, then starts discovery.

Units appear as devices shortly afterwards. Only **one** instance can exist (`single_config_entry`), since a single listener serves every unit. To change the interface later, use **Reconfigure**; no devices or entities are lost.

## Entities

| Platform | Entity | Notes |
| --- | --- | --- |
| `climate` | Air conditioner | Main control |
| `binary_sensor` | Fault status | Device class `problem` |
| `sensor` | Fault description | Enumerated fault reason (filter cleaning, reset needed, ...) |
| `sensor` | Cumulative energy consumption | `total_increasing`, where the unit reports it |
| `sensor` | Measured room temperature | Also reflected in the climate entity |
| `switch` | Power-saving operation | Normal vs. power-saving |
| `button` | Buzzer | Beeps the unit, handy to tell units apart |

Configuration and diagnostic properties get the matching Home Assistant entity category, so they stay off your main dashboard by default.

### HVAC mode mapping

| Home Assistant | ECHONET Lite | `hvac_action` while on |
| --- | --- | --- |
| `off` | Operation status off | `off` |
| `auto` | Auto | Cooling or heating, inferred from target vs. current temperature |
| `cool` | Cooling | `cooling` |
| `heat` | Heating | `heating` |
| `dry` | Dehumidification | `drying` |

The unit's special state takes priority when reporting the action, so you see `defrosting` and `preheating` when that is what it is doing. Selecting any mode other than `off` writes the mode and turns the unit on in one request.

## How it works

1. **Listener.** A `HemsClient` from `pyhems` opens a multicast socket on the chosen interface and joins `224.0.23.0:3610`.
2. **Discovery.** Devices are identified by their ECHONET Lite object (EOJ), and their property maps (readable, writable, announced EPCs) are stored per device.
3. **State.** A `DeviceManager` tracks every node, and a coordinator notifies Home Assistant as frames arrive. There is no fixed refresh loop.
4. **Polling.** A `PropertyPoller` covers properties a unit does not announce.
5. **Writes.** Commands are checked against the unit's writable property map first. A non-writable property gives an error naming the EPC rather than a silent failure.
6. **Health.** A monitor runs every minute. After five minutes of silence it raises a repair issue and marks affected entities unavailable, and clears both when traffic resumes.

## Troubleshooting

**The multicast listener cannot start.** Check that UDP multicast to `224.0.23.0:3610` is permitted on the host. In containers, use host networking. Try selecting a specific interface instead of Auto.

**No devices appear.** Confirm ECHONET Lite is enabled on the unit, that both sides share a subnet (or have a multicast relay), that client isolation and multicast filtering are off on your access point, and that IGMP snooping on your switch has a querier.

**"Eolia HEMS devices not responding".** No frames arrived for over five minutes. The unit may be offline, its adapter may have lost Wi-Fi, or multicast is being blocked. The issue closes itself after the next frame.

**"EPC is not writable".** The unit does not allow that property to be changed. The message names the EPC (for example `0xB3`).

**Swing or fan modes are missing.** They only appear when the unit lists the property as writable. Check `set_epcs` in the diagnostics.

To enable debug logging:

```yaml
logger:
  default: warning
  logs:
    custom_components.eolia_hems: debug
    pyhems: debug
```

## Diagnostics

Use **Download diagnostics** on the integration page and attach it to bug reports. It includes class code, manufacturer info, the readable, writable and announced EPC lists, poller statistics and the raw value of each property. The network interface, unique IDs, device keys, node IDs and serial numbers are redacted, as are the identification number (`0x83`) and serial number (`0x8D`) properties.

## Development

```text
custom_components/eolia_hems/
├── __init__.py        # Entry setup and teardown
├── config_flow.py     # Interface selection and reconfigure
├── runtime.py         # HemsClient lifecycle and issue monitor
├── coordinator.py     # Bridges DeviceManager to Home Assistant
├── entity.py, prop.py # Entity base and typed property wrappers
├── const.py           # Supported classes, EPC lists, unit mapping
├── climate.py         # The air conditioner entity
├── sensor.py, binary_sensor.py, switch.py, button.py
├── diagnostics.py
├── icons.json
└── translations/en.json
```

Releases are cut with the manual **Release** GitHub workflow, which writes the version into `manifest.json`, commits, tags `v<version>` and publishes `eolia_hems.zip`. Versions are managed with `bump-my-version`.

Contributions are welcome, especially reports for other Eolia models. Please attach diagnostics to any issue, and keep the scope in mind: features aimed at other ECHONET Lite device classes are better proposed upstream.

## Acknowledgements

This project would not exist without the work of **[sayurin](https://github.com/sayurin)**, and I thank her sincerely.

- **[hems_echonet_lite](https://github.com/sayurin/hems_echonet_lite)** is the Home Assistant integration this one is modelled on. Its architecture, its way of turning ECHONET Lite property definitions into Home Assistant entities, its multicast discovery and its repair-issue design were my reference throughout. If you own devices beyond air conditioners, use hers: it covers a far wider range of ECHONET Lite classes.
- **[pyhems](https://github.com/sayurin/pyhems)** is her Python library doing the heavy lifting underneath: frame encoding, the multicast client, device and node tracking, the property registry with enums, units and ranges, and the poller. This integration is a thin, opinionated layer over it.

Thanks also to the Home Assistant developers and the ECHONET Consortium for the openly published specification that makes local control possible.

## License

Released under the [MIT License](LICENSE).

## Disclaimer

This is an independent community project, not affiliated with or endorsed by Panasonic, the ECHONET Consortium or Home Assistant. Eolia and Panasonic are trademarks of their respective owners. You are sending control commands to real heating and cooling equipment, so use it at your own risk.
