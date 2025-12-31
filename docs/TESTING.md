# Power Manager Testing Guide

This document describes how to run tests and add new test scenarios.

## Quick Start

```bash
# Install dependencies
npm install

# Run all tests
npm test

# Run unit tests only
npm run test:unit

# Run tests in watch mode (during development)
npm run test:watch
```

## Test Structure

```
test/
├── unit/                    # Pure function tests (no Node-RED)
│   ├── tariff.test.js       # Tariff calculation tests
│   ├── validation.test.js   # Input validation tests
│   ├── timing.test.js       # Timing/hysteresis tests
│   └── formatting.test.js   # Output formatting tests
│
├── flow/                    # Node-RED flow tests
│   └── power-manager.flow.test.js
│
└── fixtures/                # Test scenario data
    ├── winter-offpeak-ev.json
    ├── summer-export-cool.json
    ├── sensor-unavailable.json
    └── index.js             # Fixture loader
```

## Unit Tests

Unit tests cover pure functions that don't require Node-RED:

### Tariff Tests
Tests for `getTariffInfo()`, `getNextNonPeak()`, `isPeakTariff()`, etc.

```javascript
test('peak at 08:00', () => {
    const date = new Date('2024-01-15T08:00:00');
    const result = getTariffInfo(date);
    expect(result.tariff).toBe('peak');
    expect(result.max).toBe(2500);
});
```

### Validation Tests
Tests for `safeNum()`, `safeStr()`, `parseOverride()`, etc.

```javascript
test('parses unavailable as fallback', () => {
    expect(safeNum('unavailable', 100)).toBe(100);
});
```

### Timing Tests
Tests for `canSwitch()`, `shouldAdjustEvAmps()`, etc.

```javascript
test('blocks if off time too short', () => {
    const state = { on: false, lastChange: now - 60000 };
    expect(canSwitch(state, true, now)).toBe(false);
});
```

## Fixtures

Fixtures define test scenarios in JSON format:

```json
{
  "name": "winter_offpeak_ev_charge",
  "description": "EV should start charging in winter off-peak",
  "timestamp": "2024-01-15T02:30:00Z",
  "inputs": {
    "p1_power": 0.5,
    "pv_power": 0,
    "ev_state": 129,
    // ... all sensor values
  },
  "expectedDecisions": {
    "ev": { "action": "on", "amps": 16 }
  },
  "expectedPlanContains": [
    "SUPER OFF PEAK",
    "EV: Starting"
  ]
}
```

### Using Fixtures in Tests

```javascript
const { fixtures } = require('../fixtures');

test('winter off-peak EV charging', () => {
    const fixture = fixtures.winterOffpeakEv;
    const inputs = validateInputs(fixture.inputs);
    const result = calculateDecisions(
        inputs,
        defaultConfig,
        createInitialDeviceStates(),
        new Date(fixture.timestamp).getTime()
    );

    expect(result.decisions.ev.action).toBe('on');
});
```

### Adding New Fixtures

1. Create a new JSON file in `test/fixtures/`:

```json
{
  "name": "my_scenario",
  "description": "Description of what this tests",
  "timestamp": "2024-01-15T12:00:00Z",
  "inputs": {
    // Copy from an existing fixture and modify
  },
  "expectedDecisions": {
    // What devices should do
  }
}
```

2. Add to the fixtures index in `test/fixtures/index.js`:

```javascript
const fixtures = {
    // ... existing fixtures
    myScenario: loadFixture('my-scenario')
};
```

## Flow Tests

Flow tests use `node-red-node-test-helper` to test actual Node-RED flows:

```javascript
const helper = require('node-red-node-test-helper');

describe('Power Manager Flow', () => {
    afterEach(() => helper.unload());

    test('processes input and produces output', async () => {
        const flow = [/* flow nodes */];
        await helper.load([], flow);

        const n1 = helper.getNode('node1');
        n1.receive({ payload: 'test' });

        // Assert outputs
    });
});
```

## Mock Adapter

The mock adapter simulates Home Assistant for testing:

```javascript
const { createDefaultMock } = require('../../src/adapters/mock-adapter');

const mock = createDefaultMock({
    'sensor.electricity_meter_power_consumption': 1.5,
    'sensor.abb_terra_ac_charging_state': 129
});

// Simulate service calls
mock.callService('switch', 'turn_on', { entity_id: 'switch.boiler' });

// Check what was called
const commands = mock.getCommands();
expect(commands[0].service).toBe('turn_on');
```

## Coverage Requirements

The project enforces coverage thresholds:

| Metric | Threshold |
|--------|-----------|
| Branches | 80% |
| Functions | 90% |
| Lines | 85% |
| Statements | 85% |

Run coverage report:
```bash
npm test -- --coverage
```

## Continuous Integration

Tests run automatically on:
- Every push to `main`
- Every pull request

See `.github/workflows/test.yml` for the CI configuration.

## Debugging Tests

### Run single test file
```bash
npx jest test/unit/tariff.test.js
```

### Run tests matching pattern
```bash
npx jest -t "peak at 08:00"
```

### Run with verbose output
```bash
npm test -- --verbose
```

### Debug in VS Code
Add to `.vscode/launch.json`:
```json
{
    "type": "node",
    "request": "launch",
    "name": "Jest Tests",
    "program": "${workspaceFolder}/node_modules/jest/bin/jest",
    "args": ["--runInBand"],
    "console": "integratedTerminal"
}
```

## Simulator Dashboard

The simulator dashboard allows interactive testing without Home Assistant.

### Setup

1. Install node-red-dashboard:

   ```bash
   cd ~/.node-red
   npm install node-red-dashboard
   ```

2. Import the simulator flow:
   - Open Node-RED editor
   - Menu → Import → select `node-red/simulator.json`
   - Deploy

3. Open dashboard at `http://localhost:1880/ui`

### Usage

1. **Select Scenario**: Choose a pre-defined scenario from the dropdown:
   - Winter Off-Peak EV - Tests EV charging during night tariff
   - Summer Export Cool - Tests cooling when exporting solar
   - Sensor Unavailable - Tests graceful handling of missing data
   - Custom - Manual input for any scenario

2. **Adjust Inputs**: Use sliders and dropdowns to modify:
   - Grid Power (kW) - Positive = import, negative = export
   - Solar Power (W) - Current PV production
   - Temperatures - Room temperatures for AC decisions
   - EV State - No car, ready, charging, full
   - Summer Mode - Toggle pool/cooling season
   - Overrides - Manual AC and EV controls

3. **Run Decision**: Click "Run Decision Engine" to execute

4. **View Results**:
   - Plan - Status line and action descriptions
   - Decisions - Active device changes
   - Meta Info - Tariff, headroom, season details
   - JSON Output - Full decision object for debugging

### Adding Custom Scenarios

Add scenarios to the simulator by editing the "Load Fixture" function node:

```javascript
const fixtures = {
    'my-scenario': {
        timestamp: '2024-06-15T14:00:00Z',
        inputs: {
            p1_power: -1.5,  // Exporting
            pv_power: 4000,
            pool_season: 'on',
            // ... other inputs
        }
    }
};
```

## Best Practices

1. **Test one thing per test** - Each test should verify one behavior
2. **Use descriptive names** - Test names should describe the scenario
3. **Use fixtures for complex scenarios** - Don't repeat input data
4. **Test edge cases** - Boundaries, unavailable sensors, zero values
5. **Keep tests fast** - Unit tests should run in milliseconds
6. **Avoid testing implementation** - Test behavior, not internals
