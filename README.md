# Power Manager

Intelligent energy management system for Home Assistant using Node-RED.

Automatically controls devices based on:
- **Electricity tariff** (peak / off-peak / super off-peak)
- **Season** (summer = cooling priority, winter = heating priority)
- **Solar export** (cooling only when exporting to grid)
- **EV charging** (smart charging based on available power)
- **Manual overrides** (family members can override any device)

## Features

- Fully testable logic with 90%+ test coverage
- Deterministic decision engine
- Mock Home Assistant adapter for local testing
- Scenario-based regression testing
- CI/CD with GitHub Actions

## Repository Structure

```
Power Manager/
├── node-red/
│   └── flows.json              # Main Node-RED flow
│
├── src/
│   ├── logic/                  # Pure business logic (testable)
│   │   ├── tariff.js           # Tariff calculation
│   │   ├── decisions.js        # Device decision engine
│   │   ├── timing.js           # Timing/hysteresis
│   │   ├── validation.js       # Input sanitization
│   │   └── formatting.js       # Output formatting
│   │
│   ├── adapters/
│   │   └── mock-adapter.js     # HA mock for testing
│   │
│   └── config/
│       └── default-config.js   # Default configuration
│
├── test/
│   ├── unit/                   # Unit tests
│   ├── flow/                   # Flow integration tests
│   └── fixtures/               # Test scenarios (JSON)
│
├── homeassistant/
│   ├── helpers/                # HA input helpers
│   └── dashboard/              # Lovelace cards
│
├── docs/
│   ├── README.md               # Full documentation
│   └── TESTING.md              # Testing guide
│
├── archive/
│   └── v5/                     # Archived Dutch version
│
├── package.json
├── jest.config.js
└── .github/workflows/test.yml  # CI pipeline
```

## Quick Start

### Development Setup

```bash
# Install dependencies
npm install

# Run tests
npm test

# Run tests in watch mode
npm run test:watch
```

### Home Assistant Setup

1. **Add Helpers**: Copy `homeassistant/helpers/helpers.yaml` to your HA config
2. **Import Flow**: Import `node-red/flows.json` into Node-RED
3. **Add Dashboard**: Copy cards from `homeassistant/dashboard/dashboard.yaml`

## Testing

```bash
# Run all tests with coverage
npm test

# Run unit tests only
npm run test:unit

# Run specific test file
npx jest test/unit/tariff.test.js
```

See [docs/TESTING.md](docs/TESTING.md) for detailed testing documentation.

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

## Architecture

The system uses a clean separation between:

1. **Pure Logic** (`src/logic/`) - Testable functions with no I/O
2. **Adapters** (`src/adapters/`) - Interface to Home Assistant
3. **Flow** (`node-red/flows.json`) - Orchestration and wiring

This allows testing the decision engine without Node-RED or Home Assistant.

## Version History

| Version | Changes |
|---------|---------|
| v6.1 | Testable architecture, extracted logic modules, CI/CD |
| v6.0 | English translation, input validation, mutex, EV amp threshold |
| v5.1 | Forward-looking plan display, heater timing info |
| v5.0 | Manual overrides, seasonal logic, 4 AC units |

## Documentation

- **Full Guide**: [docs/README.md](docs/README.md)
- **Testing**: [docs/TESTING.md](docs/TESTING.md)
- **Analysis**: [ANALYSIS.md](ANALYSIS.md)

## License

MIT License - Feel free to use and modify.
