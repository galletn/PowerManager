# Power Manager

Intelligent energy management system for Home Assistant using Node-RED.

Automatically controls devices based on:
- **Electricity tariff** (peak / off-peak / super off-peak)
- **Season** (summer = cooling priority, winter = heating priority)
- **Solar export** (cooling only when exporting to grid)
- **EV charging** (smart charging based on available power)
- **Manual overrides** (family members can override any device)

## Repository Structure

```
PowerManager/
├── flows/                          # Node-RED flows
│   ├── power-manager-v5.json       # Version 5.1 (Dutch)
│   └── power-manager-v6.json       # Version 6.0 (English, recommended)
├── homeassistant/
│   ├── helpers/                    # HA input helpers
│   │   ├── helpers-en.yaml         # English version
│   │   └── helpers-nl.yaml         # Dutch version
│   └── dashboard/                  # Lovelace dashboard cards
│       ├── dashboard-en.yaml       # English version
│       └── dashboard-nl.yaml       # Dutch version
├── docs/                           # Documentation
│   ├── README-en.md                # Full English documentation
│   └── README-nl.md                # Full Dutch documentation
└── README.md                       # This file
```

## Quick Start

### 1. Install HA Helpers

Add contents of `homeassistant/helpers/helpers-en.yaml` to your `configuration.yaml`:

```yaml
# Include in configuration.yaml
input_text: !include_dir_merge_named homeassistant/helpers/
input_select: !include_dir_merge_named homeassistant/helpers/
```

Or copy the contents directly. Restart Home Assistant.

### 2. Import Node-RED Flow

1. Open Node-RED
2. Menu → Import (Ctrl+I)
3. Select `flows/power-manager-v6.json`
4. Click Import → Deploy

### 3. Add Dashboard Cards (Optional)

Copy cards from `homeassistant/dashboard/dashboard-en.yaml` to your Lovelace dashboard.

## Controlled Devices

| Device | Power | Season |
|--------|-------|--------|
| EV Charger (ABB Terra AC) | 4-11 kW | Both |
| Water Heater (Boiler) | 2.5 kW | Both |
| Pool Heat Pump | 2 kW | Summer |
| AC Living Room | 1.5 kW | Both |
| AC Mancave | 1 kW | Both |
| AC Office | 1 kW | Summer |
| AC Bedroom | 1 kW | Summer |
| Electric Heater (Table) | 4.1 kW | Winter |
| Electric Heater (Right) | 2.5 kW | Winter |

## Version History

| Version | Changes |
|---------|---------|
| v6.0 | English translation, input validation, mutex, EV amp threshold |
| v5.1 | Forward-looking plan display, heater timing info |
| v5.0 | Manual overrides, seasonal logic, 4 AC units |

## Documentation

- **English**: [docs/README-en.md](docs/README-en.md)
- **Dutch**: [docs/README-nl.md](docs/README-nl.md)

## License

MIT License - Feel free to use and modify.

## Author

Created for personal home automation use.
