/**
 * Frost Protection Tests
 *
 * Tests for pool pump frost protection logic.
 */

'use strict';

const { checkFrostProtection, calculateDecisions } = require('../../src/logic/decisions');
const { defaultConfig } = require('../../src/config/default-config');
const { createInitialDeviceStates } = require('../../src/logic/timing');

describe('Frost Protection', () => {
    const baseInputs = {
        p1Power: 1000,
        pvPower: 0,
        boilerSwitch: 'off',
        boilerPower: 0,
        boilerForce: 'off',
        poolSeason: 'off',
        poolPower: 0,
        poolClimate: 'off',
        poolPumpSwitch: 'on',
        poolPumpPower: 120,  // Normal pump power consumption
        poolAmbientTemp: 10,
        evState: 128,
        evSwitch: 'off',
        evPower: 0,
        evLimit: 6,
        heaterRightSwitch: 'off',
        heaterTableSwitch: 'off',
        acLivingState: 'off',
        acMancaveState: 'off',
        acOfficeState: 'off',
        acBedroomState: 'off',
        acLivingPower: 0,
        acOfficePower: 0,
        tempLiving: 20,
        tempBedroom: 20,
        tempMancave: 20,
        ovrAcLiving: '',
        ovrAcBedroom: '',
        ovrAcOffice: '',
        ovrAcMancave: '',
        ovrPool: '',
        ovrBoiler: '',
        ovrEv: ''
    };

    const now = Date.now();

    describe('checkFrostProtection', () => {
        it('does nothing when disabled', () => {
            const config = { ...defaultConfig, frostProtection: { enabled: false } };
            const inputs = { ...baseInputs, poolAmbientTemp: 0, poolPumpSwitch: 'off' };
            const deviceState = createInitialDeviceStates();

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.alerts).toHaveLength(0);
            expect(result.poolPumpDecision.action).toBe('none');
            expect(result.planEntries).toHaveLength(0);
        });

        it('does nothing when temperature above threshold', () => {
            const config = { ...defaultConfig, frostProtection: { enabled: true, tempThreshold: 5 } };
            const inputs = { ...baseInputs, poolAmbientTemp: 10, poolPumpSwitch: 'off' };
            const deviceState = createInitialDeviceStates();

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.alerts).toHaveLength(0);
            expect(result.poolPumpDecision.action).toBe('none');
        });

        it('turns on pump when cold and pump off', () => {
            const config = { ...defaultConfig, frostProtection: { enabled: true, tempThreshold: 5 } };
            const inputs = { ...baseInputs, poolAmbientTemp: 3, poolPumpSwitch: 'off', poolPumpPower: 0 };
            const deviceState = createInitialDeviceStates();

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.poolPumpDecision.action).toBe('on');
            expect(result.planEntries[0]).toContain('Frost: PUMP ON');
            expect(result.planEntries[0]).toContain('3.0°C');
        });

        it('alerts when pump switch on but no power consumption', () => {
            const config = {
                ...defaultConfig,
                frostProtection: {
                    enabled: true,
                    tempThreshold: 5,
                    pumpMinPower: 100,
                    pumpOffAlertDelay: 0
                }
            };
            // Pump switch is ON but only drawing 20W (not actually pumping)
            const inputs = { ...baseInputs, poolAmbientTemp: 3, poolPumpSwitch: 'on', poolPumpPower: 20 };
            const deviceState = createInitialDeviceStates();

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.poolPumpDecision.action).toBe('on');
            expect(result.planEntries[0]).toContain('only 20W');
            expect(result.planEntries[0]).toContain('min 100W');
            expect(result.alerts).toHaveLength(1);
            expect(result.alerts[0].message).toContain('only 20W');
        });

        it('logs OK when pump running and consuming power during cold weather', () => {
            const config = { ...defaultConfig, frostProtection: { enabled: true, tempThreshold: 5, pumpMinPower: 100 } };
            // Pump is ON and drawing 120W - actually running
            const inputs = { ...baseInputs, poolAmbientTemp: 3, poolPumpSwitch: 'on', poolPumpPower: 120 };
            const deviceState = createInitialDeviceStates();

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.poolPumpDecision.action).toBe('none');
            expect(result.planEntries[0]).toContain('Frost: OK');
            expect(result.planEntries[0]).toContain('pump');
            expect(result.planEntries[0]).toContain('120W');
        });

        it('marks critical when below critical threshold', () => {
            const config = {
                ...defaultConfig,
                frostProtection: { enabled: true, tempThreshold: 5, criticalThreshold: 2, pumpMinPower: 100 }
            };
            const inputs = { ...baseInputs, poolAmbientTemp: 1, poolPumpSwitch: 'on', poolPumpPower: 120 };
            const deviceState = createInitialDeviceStates();

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.planEntries[0]).toContain('CRITICAL');
        });

        it('generates warning alert when pump off too long', () => {
            const config = {
                ...defaultConfig,
                frostProtection: {
                    enabled: true,
                    tempThreshold: 5,
                    pumpOffAlertDelay: 300,
                    notifyEntity: 'mobile_app_test'
                }
            };
            const inputs = { ...baseInputs, poolAmbientTemp: 4, poolPumpSwitch: 'off' };
            const deviceState = createInitialDeviceStates();
            // Simulate pump being off for 10 minutes (600 seconds)
            deviceState.poolPump = { on: false, lastChange: now - 600000 };

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.alerts).toHaveLength(1);
            expect(result.alerts[0].level).toBe('warning');
            expect(result.alerts[0].message).toContain('Pool pump not running');
            expect(result.alerts[0].notifyEntity).toBe('mobile_app_test');
        });

        it('generates critical alert when pump off during freezing temps', () => {
            const config = {
                ...defaultConfig,
                frostProtection: {
                    enabled: true,
                    tempThreshold: 5,
                    criticalThreshold: 2,
                    pumpOffAlertDelay: 300,
                    notifyEntity: 'mobile_app_test'
                }
            };
            const inputs = { ...baseInputs, poolAmbientTemp: 1, poolPumpSwitch: 'off' };
            const deviceState = createInitialDeviceStates();
            deviceState.poolPump = { on: false, lastChange: now - 600000 };

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.alerts).toHaveLength(1);
            expect(result.alerts[0].level).toBe('critical');
            expect(result.alerts[0].message).toContain('CRITICAL');
            expect(result.alerts[0].message).toContain('Freeze risk');
        });

        it('handles missing temperature sensor', () => {
            const config = { ...defaultConfig, frostProtection: { enabled: true } };
            const inputs = { ...baseInputs, poolAmbientTemp: null, poolPumpSwitch: 'off' };
            const deviceState = createInitialDeviceStates();

            const result = checkFrostProtection(inputs, config, deviceState, now);

            expect(result.alerts).toHaveLength(0);
            expect(result.poolPumpDecision.action).toBe('none');
            expect(result.planEntries[0]).toContain('No temp sensor');
        });

        it('no alert if pump just recently turned off', () => {
            const config = {
                ...defaultConfig,
                frostProtection: {
                    enabled: true,
                    tempThreshold: 5,
                    pumpOffAlertDelay: 300
                }
            };
            const inputs = { ...baseInputs, poolAmbientTemp: 3, poolPumpSwitch: 'off' };
            const deviceState = createInitialDeviceStates();
            // Pump just turned off 1 minute ago
            deviceState.poolPump = { on: false, lastChange: now - 60000 };

            const result = checkFrostProtection(inputs, config, deviceState, now);

            // Should still want to turn pump on
            expect(result.poolPumpDecision.action).toBe('on');
            // But no alert yet (under 5 minutes)
            expect(result.alerts).toHaveLength(0);
        });
    });

    describe('calculateDecisions with frost protection', () => {
        it('includes poolPump decision when frost protection triggers', () => {
            const config = { ...defaultConfig, frostProtection: { enabled: true, tempThreshold: 5 } };
            const inputs = { ...baseInputs, poolAmbientTemp: 2, poolPumpSwitch: 'off' };
            const deviceState = createInitialDeviceStates();

            const result = calculateDecisions(inputs, config, deviceState, now);

            expect(result.decisions.poolPump.action).toBe('on');
            expect(result.plan.some(p => p.includes('Frost'))).toBe(true);
        });

        it('includes alerts in result', () => {
            const config = {
                ...defaultConfig,
                frostProtection: {
                    enabled: true,
                    tempThreshold: 5,
                    pumpOffAlertDelay: 0 // immediate alert
                }
            };
            const inputs = { ...baseInputs, poolAmbientTemp: 2, poolPumpSwitch: 'off' };
            const deviceState = createInitialDeviceStates();

            const result = calculateDecisions(inputs, config, deviceState, now);

            expect(result.alerts).toBeDefined();
            expect(result.alerts.length).toBeGreaterThan(0);
        });

        it('includes poolAmbientTemp in meta', () => {
            const config = defaultConfig;
            const inputs = { ...baseInputs, poolAmbientTemp: 15 };
            const deviceState = createInitialDeviceStates();

            const result = calculateDecisions(inputs, config, deviceState, now);

            expect(result.meta.poolAmbientTemp).toBe(15);
        });
    });
});
