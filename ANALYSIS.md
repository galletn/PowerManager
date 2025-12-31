# Power Manager - Analysis & Refactoring Plan

## A) Flow Analysis

### A1. Node Inventory

| Node ID | Type | Name | Role |
|---------|------|------|------|
| `config_node` | function | CONFIG | Configuration storage (flow context) |
| `init_state` | function | Init State | Device state initialization |
| `trigger_gate` | function | Gate (mutex) | Concurrent execution prevention |
| `validate_inputs` | function | Validate Inputs | Input sanitization |
| `power_manager` | function | Power Manager v6 | **Main decision engine (~450 LOC)** |
| `ev_handler` | function | EV Handler | Transform EV commands |
| `pool_handler` | function | Pool Handler | Transform Pool commands |
| 30x | api-current-state | Various | Sequential HA state gathering |
| 14x | api-call-service | Various | HA service execution |

### A2. Pure Logic vs I/O

#### Pure Functions (Testable without runtime)

```
+-- Tariff Logic
|   +-- getTariffInfo(date) -> { tariff, max, end, next, nextTime }
|   +-- getNextNonPeak(date) -> { time, tariff, max }
|
+-- Timing Logic
|   +-- canSwitch(device, targetState) -> boolean
|
+-- Input Processing
|   +-- safeNum(val, fallback) -> number
|   +-- safeStr(val, fallback) -> string
|   +-- parseOverride(val) -> 'auto' | 'cool' | 'heat' | 'off'
|
+-- Formatting
|   +-- fmtW(watts) -> string
|   +-- fmtTime(hours) -> string
|
+-- Decision Engine (extractable)
    +-- calculateAvailablePower(p1, maxImport) -> watts
    +-- shouldCharge(evState, tariff, headroom, config) -> Decision
    +-- shouldHeatBoiler(time, tariff, boilerFull, headroom, config) -> Decision
    +-- winterPriority(inputs, config) -> DeviceDecisions
    +-- summerPriority(inputs, config) -> DeviceDecisions
```

#### I/O Dependencies (Require mocking)

| Dependency | Current Usage | Mock Strategy |
|------------|---------------|---------------|
| `flow.get/set()` | State persistence | Inject state store |
| `Date.now()` | Timing calculations | Inject clock |
| `new Date()` | Tariff calculation | Inject clock |
| `node.status()` | UI feedback | No-op or capture |
| `node.warn()` | Logging | Capture to array |
| HA api-current-state | State reading | Mock adapter |
| HA api-call-service | Device control | Command capture |

### A3. Anti-patterns Detected

#### 1. Monolithic Function Node (CRITICAL)
**Location:** `power_manager` node
**Problem:** 450+ lines of mixed concerns:
- Configuration reading
- Tariff calculation
- Override parsing
- Device decision logic (winter/summer)
- State management
- Logging
- Output formatting

**Impact:** Cannot test individual rules, hard to maintain

#### 2. Implicit Mutable State
**Location:** `flow.set('deviceState', ...)`, `flow.set('actionLog', ...)`
**Problem:** State scattered across flow context:
```javascript
deviceState = {
    ev: { on: false, lastChange: 0, amps: 0 },
    boiler: { on: false, lastChange: 0 },
    // ...
}
```
**Impact:** Race conditions possible, state not inspectable during tests

#### 3. Side Effects During Decision Making
**Location:** `updateState()` and `logAction()` called inline
**Problem:** Decision logic mutates state as side effect:
```javascript
if (decisions.ev.action === 'on') {
    outputs[0] = { payload: { action: 'turn_on', amps: decisions.ev.amps } };
    updateState('ev', true, { amps: decisions.ev.amps });  // SIDE EFFECT
    logAction(`EV ON @ ${decisions.ev.amps}A`);             // SIDE EFFECT
}
```
**Impact:** Cannot test decisions without also running side effects

#### 4. Non-Injectable Clock
**Location:** `new Date()` and `Date.now()` called directly
**Problem:** Tariff tests require specific times, timing tests require controlled time
**Impact:** Tests are non-deterministic, cannot test edge cases like 06:29 vs 06:31

#### 5. Sequential Blocking State Chain
**Location:** 30 `api-current-state` nodes in series
**Problem:**
- Single point of failure (any node breaks chain)
- Latency stacking (30 sequential calls)
- All-or-nothing gathering

**Impact:** Slow, fragile, hard to test partial failures

#### 6. Log Throttling in Business Logic
**Location:** `logAction()` function
```javascript
if (lastActions[actionKey] && (now - lastActions[actionKey]) < 30000) {
    return; // Skip duplicate log
}
```
**Impact:** Logging behavior affects test assertions, non-deterministic

### A4. Untestable Parts (Current State)

| Component | Why Untestable | Fix Required |
|-----------|----------------|--------------|
| Tariff at specific time | `new Date()` hardcoded | Inject clock |
| Device timing (hysteresis) | `Date.now()` hardcoded | Inject clock |
| State persistence | `flow.get/set()` | State adapter |
| HA state gathering | Requires live HA | Mock adapter |
| HA service calls | Requires live HA | Command capture |
| Log throttling | Time-dependent | Inject clock |

---

## B) Test Strategy

### B1. Test Pyramid

```
                    ┌─────────────────┐
                    │   E2E Tests     │  (Optional: Full HA mock)
                    │   with Sim UI   │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │        Flow Tests           │
              │   (node-red-node-test-helper)│
              │   - Full flow execution     │
              │   - Mocked HA adapter       │
              └──────────────┬──────────────┘
                             │
    ┌────────────────────────┴────────────────────────┐
    │                   Unit Tests                     │
    │   - Pure functions (no Node-RED runtime)        │
    │   - Jest/Mocha, fast, deterministic             │
    │   - Tariff, decisions, formatting, validation   │
    └──────────────────────────────────────────────────┘
```

### B2. Unit Test Coverage (Target: 90%+)

| Module | Functions | Test Cases |
|--------|-----------|------------|
| `tariff.js` | `getTariffInfo`, `getNextNonPeak` | 15 (all time slots + weekends) |
| `decisions.js` | `winterPriority`, `summerPriority` | 25+ (per device + combinations) |
| `validation.js` | `safeNum`, `safeStr`, `parseOverride` | 12 (types + edge cases) |
| `timing.js` | `canSwitch`, timing helpers | 8 (boundaries, edge cases) |
| `formatting.js` | `fmtW`, `fmtTime` | 6 (units, rounding) |

### B3. Flow Test Coverage

| Scenario | Input States | Expected Commands |
|----------|--------------|-------------------|
| Winter normal | 2kW import, peak | No changes |
| Winter off-peak start | 0W, off-peak, heaters off | Heaters ON |
| Summer export | -2kW, PV high, hot inside | Cooling ON |
| EV plugged peak | EV ready, peak | Wait for off-peak |
| EV plugged off-peak | EV ready, off-peak, headroom | EV ON + amps |
| Sensor unavailable | P1 = 'unavailable' | Safe fallback |
| Multiple overrides | AC=cool, Pool=off | Respect overrides |
| Boiler deadline | 06:00, super-off-peak, not full | URGENT boiler |

### B4. Scenario Matrix (Table-Driven)

```json
{
  "name": "winter_offpeak_ev_charge",
  "description": "EV should start charging in winter off-peak with headroom",
  "inputs": {
    "timestamp": "2024-01-15T02:00:00Z",
    "p1Power": 0.5,
    "pvPower": 0,
    "poolSeason": "off",
    "evState": 129,
    "evSwitch": "off",
    "boilerSwitch": "off",
    "boilerPower": 2400
  },
  "expectedCommands": [
    { "device": "ev", "action": "on", "amps": 16 }
  ],
  "invariants": [
    { "type": "never", "condition": "heater during peak" },
    { "type": "always", "condition": "respect manual override" }
  ]
}
```

---

## C) Target Architecture

### C1. Repository Structure

```
Power Manager/
├── node-red/
│   ├── flows.json              # Main flow (thin orchestration)
│   ├── flows-simulator.json    # Simulator tab
│   └── settings.js             # Node-RED settings
│
├── src/
│   ├── logic/
│   │   ├── tariff.js           # Tariff calculation
│   │   ├── decisions.js        # Device decision engine
│   │   ├── timing.js           # Timing/hysteresis logic
│   │   ├── validation.js       # Input sanitization
│   │   ├── formatting.js       # Output formatting
│   │   └── index.js            # Re-exports
│   │
│   ├── adapters/
│   │   ├── ha-adapter.js       # Real HA interface
│   │   ├── mock-adapter.js     # Test mock
│   │   └── types.js            # TypeScript-style JSDoc types
│   │
│   └── config/
│       ├── default-config.js   # Default configuration
│       └── schema.js           # Config validation schema
│
├── test/
│   ├── unit/
│   │   ├── tariff.test.js
│   │   ├── decisions.test.js
│   │   ├── timing.test.js
│   │   └── validation.test.js
│   │
│   ├── flow/
│   │   ├── power-manager.flow.test.js
│   │   └── helpers.js
│   │
│   ├── fixtures/
│   │   ├── winter-offpeak-ev.json
│   │   ├── summer-export-cool.json
│   │   ├── sensor-unavailable.json
│   │   └── index.js            # Fixture loader
│   │
│   └── setup.js                # Test configuration
│
├── homeassistant/
│   ├── helpers/
│   │   └── helpers.yaml
│   └── dashboard/
│       └── dashboard.yaml
│
├── archive/
│   └── v5/                     # Archived v5 files
│
├── docs/
│   ├── README.md               # Main documentation
│   ├── TESTING.md              # Testing guide
│   └── SIMULATOR.md            # Simulator guide
│
├── package.json
├── jest.config.js
├── .github/
│   └── workflows/
│       └── test.yml            # CI pipeline
│
└── README.md
```

### C2. Module Design

#### `src/logic/tariff.js`
```javascript
/**
 * Calculate tariff information for a given timestamp
 * @param {Date} date - The timestamp to check
 * @returns {{ tariff: string, max: number, end: number, next: string, nextTime: string }}
 */
function getTariffInfo(date) {
    const time = date.getHours() + date.getMinutes() / 60;
    const isWeekend = date.getDay() === 0 || date.getDay() === 6;
    // ... pure logic, no side effects
}

module.exports = { getTariffInfo, getNextNonPeak };
```

#### `src/logic/decisions.js`
```javascript
/**
 * Calculate device decisions based on current state
 * @param {InputState} inputs - Validated sensor readings
 * @param {Config} config - System configuration
 * @param {DeviceState} deviceState - Current device states with timestamps
 * @param {number} now - Current timestamp (injectable for testing)
 * @returns {DecisionResult} - Commands to execute
 */
function calculateDecisions(inputs, config, deviceState, now) {
    const tariff = getTariffInfo(new Date(now));
    const isSummer = inputs.poolSeason === 'on';

    if (isSummer) {
        return summerPriority(inputs, config, deviceState, tariff, now);
    } else {
        return winterPriority(inputs, config, deviceState, tariff, now);
    }
}
```

#### `src/adapters/mock-adapter.js`
```javascript
class MockHAAdapter {
    constructor() {
        this.states = {};
        this.commands = [];
    }

    setState(entityId, value) {
        this.states[entityId] = value;
    }

    getState(entityId) {
        return this.states[entityId] ?? 'unavailable';
    }

    callService(domain, service, data) {
        this.commands.push({ domain, service, data, timestamp: Date.now() });
    }

    getCommands() {
        return this.commands;
    }

    reset() {
        this.states = {};
        this.commands = [];
    }
}
```

### C3. Refactored Flow Structure

```
┌─────────────┐    ┌─────────────┐    ┌──────────────┐
│  Triggers   │───▶│  Gather     │───▶│  Validate    │
│  (interval/ │    │  States     │    │  Inputs      │
│   P1 change)│    │  (parallel) │    │              │
└─────────────┘    └─────────────┘    └──────┬───────┘
                                             │
                                             ▼
┌─────────────┐    ┌─────────────┐    ┌──────────────┐
│  Execute    │◀───│  Decision   │◀───│  Load        │
│  Commands   │    │  Engine     │    │  State       │
│  (adapters) │    │  (pure JS)  │    │              │
└─────────────┘    └─────────────┘    └──────────────┘
                          │
                          ▼
                   ┌──────────────┐
                   │  Log/Status  │
                   │  Update      │
                   └──────────────┘
```

**Key Changes:**
1. State gathering parallelized (join node)
2. Decision engine calls external JS module
3. Commands are explicit objects, not inline side effects
4. Logging separated from decision making

---

## D) Refactoring Phases

### Phase 0 (P0): Foundation
**Goal:** Extract pure functions, enable first unit tests

| Task | Node(s) | Output |
|------|---------|--------|
| Extract `tariff.js` | `power_manager` | `src/logic/tariff.js` |
| Extract `validation.js` | `validate_inputs` | `src/logic/validation.js` |
| Extract `formatting.js` | `power_manager` | `src/logic/formatting.js` |
| Create `package.json` | - | NPM project setup |
| Create first unit tests | - | `test/unit/*.test.js` |

**Behavior Guarantee:** No flow changes, functions extracted verbatim

### Phase 1 (P1): Decision Engine
**Goal:** Extract core logic, introduce adapters

| Task | Node(s) | Output |
|------|---------|--------|
| Extract `timing.js` | `power_manager` | `src/logic/timing.js` |
| Extract `decisions.js` | `power_manager` | Main decision logic |
| Create `mock-adapter.js` | - | Test mock for HA |
| Create flow tests | - | `test/flow/*.test.js` |
| Inject clock | `power_manager` | Testable timing |

**Behavior Guarantee:** Outputs identical, timing now injectable

### Phase 2 (P2): Parallel State Gathering
**Goal:** Optimize state gathering, improve reliability

| Task | Node(s) | Output |
|------|---------|--------|
| Parallel state gather | 30 serial nodes | Join node pattern |
| Error handling per state | Each state node | Graceful degradation |
| State schema validation | Before decision | Type safety |

**Behavior Guarantee:** Same decisions, faster execution, better error handling

### Phase 3 (P3): Simulator Dashboard
**Goal:** Visual debugging and scenario replay

| Task | Output |
|------|--------|
| Create simulator tab | `node-red/flows-simulator.json` |
| Fixture loader node | Load JSON scenarios |
| Command collector | Display decisions |
| Time controls | Manual time advancement |

---

## E) Detailed Node Refactoring

### E1. CONFIG Node
**Current:** Stores config in flow context
**Change:** Load from `src/config/default-config.js`, still use flow context for runtime
**Why:** Config now versionable, testable, documentable

### E2. Power Manager v6 Node
**Current:** 450 LOC monolith
**Change:** Thin adapter that calls:
```javascript
const { calculateDecisions } = require('/data/power-manager/src/logic/decisions.js');
const decisions = calculateDecisions(msg.validated, config, deviceState, Date.now());
```
**Lines After:** ~50 LOC (input/output mapping only)

### E3. Validate Inputs Node
**Current:** Inline validation functions
**Change:** Call external module:
```javascript
const { validateInputs } = require('/data/power-manager/src/logic/validation.js');
msg.validated = validateInputs(msg);
```

### E4. EV Handler / Pool Handler
**Current:** Transform to HA service format
**Keep:** These are already thin adapters, minimal change needed
**Improve:** Add input validation, explicit error handling

---

## F) Test Infrastructure

### F1. Jest Configuration
```javascript
// jest.config.js
module.exports = {
    testEnvironment: 'node',
    testMatch: ['**/test/**/*.test.js'],
    collectCoverageFrom: ['src/**/*.js'],
    coverageThreshold: {
        global: { branches: 80, functions: 90, lines: 85 }
    }
};
```

### F2. Flow Test Setup
```javascript
// test/flow/helpers.js
const helper = require('node-red-node-test-helper');
const MockAdapter = require('../../src/adapters/mock-adapter');

async function loadFlow(flowFile) {
    const flow = require(flowFile);
    await helper.load([], flow);
    return helper;
}

function createMockContext() {
    return {
        adapter: new MockAdapter(),
        clock: { now: () => Date.now() }
    };
}
```

### F3. CI Pipeline
```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npm test
      - run: npm run test:flow
```

---

## G) Simulator Dashboard (B2)

### G1. Components

| Component | Type | Purpose |
|-----------|------|---------|
| Scenario Selector | dropdown | Choose fixture file |
| Time Display | text | Current simulated time |
| Time Controls | buttons | Start/Stop/Step/Reset |
| Speed Slider | slider | 1x - 100x time factor |
| State Panel | table | Current mock states |
| Decision Log | list | Chronological decisions |
| Command Output | list | Captured HA commands |
| Assertion Status | indicators | Pass/Fail per scenario |

### G2. Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Simulator Tab                           │
├─────────────┬─────────────┬─────────────┬─────────────────┤
│  Controls   │  State      │  Decision   │  Commands       │
│             │  Viewer     │  Log        │  Output         │
│ [Scenario▼] │             │             │                 │
│ [▶][⏸][⏭][↺]│  p1: 1.5kW │  02:01 EV..│  ev.turn_on     │
│ Speed: [==] │  pv: 4.2kW │  02:01 Boi.│  amps: 12       │
│ Time: 02:01 │  ev: 129   │             │                 │
└─────────────┴─────────────┴─────────────┴─────────────────┘
```

### G3. Fixture Format
```json
{
  "name": "winter_super_offpeak_full_load",
  "description": "All devices competing for power at 02:00",
  "timeline": [
    {
      "time": "2024-01-15T02:00:00Z",
      "states": {
        "p1Power": 0.2,
        "pvPower": 0,
        "evState": 129,
        "boilerPower": 2400,
        "poolSeason": "off"
      }
    },
    {
      "time": "2024-01-15T02:05:00Z",
      "states": {
        "p1Power": 5.5
      }
    }
  ],
  "assertions": [
    { "at": "02:00", "expect": { "ev": "on" } },
    { "at": "02:05", "expect": { "ev": "adjust", "amps": "<= 10" } }
  ]
}
```

---

## H) Questions Before Starting

Before implementation, please confirm:

1. **Node-RED Location:** Where is Node-RED installed? (e.g., `/config/node-red/`, Docker path?)
2. **Module Loading:** Can Node-RED function nodes use `require()` with custom paths?
3. **Test Runtime:** Do you have Node.js available for running Jest tests?
4. **Parallel States:** Is replacing 30 serial nodes with parallel gather acceptable?
5. **Breaking Changes:** Can we modify entity IDs or must they remain exact?

---

## I) Success Criteria

After refactoring:

- [ ] `npm test` runs 30+ unit tests in <5 seconds
- [ ] `npm run test:flow` runs 10+ flow scenarios
- [ ] All tests pass in CI on every commit
- [ ] Simulator UI can replay any fixture
- [ ] Logic changes require only JS file edits (no flow redeploy for logic)
- [ ] New scenarios can be added as JSON files
- [ ] Zero regressions vs current production behavior
