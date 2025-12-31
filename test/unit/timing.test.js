/**
 * Timing module unit tests
 */

'use strict';

const {
    canSwitch,
    shouldAdjustEvAmps,
    createDeviceState,
    updateDeviceState,
    createInitialDeviceStates,
    timeUntilSwitch,
    hasSufficientPower,
    shouldShedLoad,
    DEFAULT_TIMING
} = require('../../src/logic/timing');

describe('canSwitch', () => {
    const now = Date.now();

    test('allows switch with no state history', () => {
        expect(canSwitch(null, true, now)).toBe(true);
        expect(canSwitch({}, true, now)).toBe(true);
        expect(canSwitch({ on: true, lastChange: 0 }, false, now)).toBe(true);
    });

    describe('turning on (checking minOffTime)', () => {
        test('blocks if off time too short', () => {
            const state = { on: false, lastChange: now - 60000 }; // 60s ago
            expect(canSwitch(state, true, now)).toBe(false);
        });

        test('allows if off time sufficient', () => {
            const state = { on: false, lastChange: now - 200000 }; // 200s ago
            expect(canSwitch(state, true, now)).toBe(true);
        });

        test('uses custom minOffTime', () => {
            const state = { on: false, lastChange: now - 60000 }; // 60s ago
            expect(canSwitch(state, true, now, { minOffTime: 30 })).toBe(true);
            expect(canSwitch(state, true, now, { minOffTime: 120 })).toBe(false);
        });
    });

    describe('turning off (checking minOnTime)', () => {
        test('blocks if on time too short', () => {
            const state = { on: true, lastChange: now - 60000 }; // 60s ago
            expect(canSwitch(state, false, now)).toBe(false);
        });

        test('allows if on time sufficient', () => {
            const state = { on: true, lastChange: now - 400000 }; // 400s ago
            expect(canSwitch(state, false, now)).toBe(true);
        });

        test('uses custom minOnTime', () => {
            const state = { on: true, lastChange: now - 60000 };
            expect(canSwitch(state, false, now, { minOnTime: 30 })).toBe(true);
            expect(canSwitch(state, false, now, { minOnTime: 120 })).toBe(false);
        });
    });

    test('uses default timing values', () => {
        expect(DEFAULT_TIMING.minOnTime).toBe(300);
        expect(DEFAULT_TIMING.minOffTime).toBe(180);
    });
});

describe('shouldAdjustEvAmps', () => {
    test('returns true when difference meets threshold', () => {
        expect(shouldAdjustEvAmps(10, 12, 2)).toBe(true);
        expect(shouldAdjustEvAmps(10, 8, 2)).toBe(true);
        expect(shouldAdjustEvAmps(6, 16, 2)).toBe(true);
    });

    test('returns false when difference below threshold', () => {
        expect(shouldAdjustEvAmps(10, 11, 2)).toBe(false);
        expect(shouldAdjustEvAmps(10, 9, 2)).toBe(false);
        expect(shouldAdjustEvAmps(10, 10, 2)).toBe(false);
    });

    test('uses default threshold of 2', () => {
        expect(shouldAdjustEvAmps(10, 12)).toBe(true);
        expect(shouldAdjustEvAmps(10, 11)).toBe(false);
    });
});

describe('createDeviceState', () => {
    test('creates state with defaults', () => {
        const state = createDeviceState();
        expect(state.on).toBe(false);
        expect(state.lastChange).toBe(0);
    });

    test('creates state with initial on', () => {
        const now = Date.now();
        const state = createDeviceState(true, now);
        expect(state.on).toBe(true);
        expect(state.lastChange).toBe(now);
    });
});

describe('updateDeviceState', () => {
    test('updates lastChange when state changes', () => {
        const now = Date.now();
        const oldState = { on: false, lastChange: 0 };
        const newState = updateDeviceState(oldState, true, now);

        expect(newState.on).toBe(true);
        expect(newState.lastChange).toBe(now);
    });

    test('preserves lastChange when state unchanged', () => {
        const oldTime = Date.now() - 10000;
        const now = Date.now();
        const oldState = { on: true, lastChange: oldTime };
        const newState = updateDeviceState(oldState, true, now);

        expect(newState.on).toBe(true);
        expect(newState.lastChange).toBe(oldTime);
    });

    test('merges extra properties', () => {
        const now = Date.now();
        const oldState = { on: false, lastChange: 0 };
        const newState = updateDeviceState(oldState, true, now, { amps: 12 });

        expect(newState.amps).toBe(12);
    });

    test('does not mutate original state', () => {
        const oldState = { on: false, lastChange: 0 };
        updateDeviceState(oldState, true, Date.now());

        expect(oldState.on).toBe(false);
    });
});

describe('createInitialDeviceStates', () => {
    test('creates all device states', () => {
        const states = createInitialDeviceStates();

        expect(states.ev).toBeDefined();
        expect(states.boiler).toBeDefined();
        expect(states.pool).toBeDefined();
        expect(states.heaterRight).toBeDefined();
        expect(states.heaterTable).toBeDefined();
        expect(states.acLiving).toBeDefined();
        expect(states.acMancave).toBeDefined();
        expect(states.acOffice).toBeDefined();
        expect(states.acBedroom).toBeDefined();
    });

    test('all devices start off', () => {
        const states = createInitialDeviceStates();

        for (const device of Object.values(states)) {
            expect(device.on).toBe(false);
            expect(device.lastChange).toBe(0);
        }
    });

    test('EV state includes amps', () => {
        const states = createInitialDeviceStates();
        expect(states.ev.amps).toBe(0);
    });
});

describe('timeUntilSwitch', () => {
    const now = Date.now();

    test('returns 0 with no state history', () => {
        expect(timeUntilSwitch(null, true, now)).toBe(0);
        expect(timeUntilSwitch({}, true, now)).toBe(0);
    });

    test('calculates remaining time for turn on', () => {
        const state = { on: false, lastChange: now - 60000 }; // 60s ago
        const remaining = timeUntilSwitch(state, true, now);
        expect(remaining).toBe(120); // 180 - 60 = 120s
    });

    test('calculates remaining time for turn off', () => {
        const state = { on: true, lastChange: now - 100000 }; // 100s ago
        const remaining = timeUntilSwitch(state, false, now);
        expect(remaining).toBe(200); // 300 - 100 = 200s
    });

    test('returns 0 when can switch immediately', () => {
        const state = { on: false, lastChange: now - 200000 };
        expect(timeUntilSwitch(state, true, now)).toBe(0);
    });
});

describe('hasSufficientPower', () => {
    test('returns true when power exceeds requirement', () => {
        expect(hasSufficientPower(3000, 2500, 300)).toBe(true);
    });

    test('returns true with hysteresis buffer', () => {
        expect(hasSufficientPower(2200, 2500, 300)).toBe(true); // 2200 >= 2500 - 300
    });

    test('returns false when power insufficient', () => {
        expect(hasSufficientPower(2000, 2500, 300)).toBe(false);
    });

    test('uses default hysteresis', () => {
        expect(hasSufficientPower(2200, 2500)).toBe(true);
        expect(hasSufficientPower(2100, 2500)).toBe(false);
    });
});

describe('shouldShedLoad', () => {
    test('returns true when headroom significantly negative', () => {
        expect(shouldShedLoad(-500, 300)).toBe(true);
        expect(shouldShedLoad(-1000, 300)).toBe(true);
    });

    test('returns false when headroom within hysteresis', () => {
        expect(shouldShedLoad(-200, 300)).toBe(false);
        expect(shouldShedLoad(0, 300)).toBe(false);
        expect(shouldShedLoad(500, 300)).toBe(false);
    });

    test('uses default hysteresis', () => {
        expect(shouldShedLoad(-400)).toBe(true);
        expect(shouldShedLoad(-200)).toBe(false);
    });
});
