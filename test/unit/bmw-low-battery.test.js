/**
 * BMW Low Battery Warning Tests
 *
 * Tests for BMW i5 and iX1 low battery notification logic.
 */

'use strict';

const { checkBmwLowBattery, calculateDecisions } = require('../../src/logic/decisions');
const { defaultConfig } = require('../../src/config/default-config');
const { createInitialDeviceStates } = require('../../src/logic/timing');

describe('BMW Low Battery Warning', () => {
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
        poolPumpPower: 120,
        poolAmbientTemp: 10,
        evState: 128, // No car plugged in
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
        ovrEv: '',
        // BMW inputs
        bmwI5Battery: 40,
        bmwI5Range: 124,
        bmwI5Location: 'home',
        bmwIx1Battery: 83,
        bmwIx1Range: 254,
        bmwIx1Location: 'not_home'
    };

    describe('checkBmwLowBattery', () => {
        it('does nothing when disabled', () => {
            const config = { ...defaultConfig, bmwLowBattery: { enabled: false } };
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = checkBmwLowBattery(baseInputs, config, now);

            expect(result.alerts).toHaveLength(0);
            expect(result.planEntries).toHaveLength(0);
        });

        it('does nothing outside check hours', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20, 21, 22], batteryThreshold: 50 }
            };
            // 15:00 - outside check hours
            const now = new Date(2024, 0, 15, 15, 0, 0).getTime();

            const result = checkBmwLowBattery(baseInputs, config, now);

            expect(result.alerts).toHaveLength(0);
            expect(result.planEntries).toHaveLength(0);
        });

        it('alerts when i5 battery low, at home, and not plugged in', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: {
                    enabled: true,
                    checkHours: [20, 21, 22],
                    batteryThreshold: 50,
                    notifyEntity: 'mobile_app_test'
                }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 40,
                bmwI5Range: 124,
                bmwI5Location: 'home',
                evState: 128 // No car on charger
            };
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(1);
            expect(result.alerts[0].level).toBe('warning');
            expect(result.alerts[0].message).toContain('BMW i5');
            expect(result.alerts[0].message).toContain('40%');
            expect(result.alerts[0].message).toContain('124');
            expect(result.alerts[0].message).toContain('not plugged in');
            expect(result.alerts[0].notifyEntity).toBe('mobile_app_test');
            expect(result.planEntries[0]).toContain('BMW i5');
            expect(result.planEntries[0]).toContain('LOW');
        });

        it('does not alert when battery above threshold', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 60, // Above threshold
                bmwI5Location: 'home',
                evState: 128
            };
            // Use local time constructor to avoid timezone issues
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(0);
            // Check that plan entry exists and contains expected info
            expect(result.planEntries.length).toBeGreaterThan(0);
            expect(result.planEntries[0]).toContain('60%');
            expect(result.planEntries[0]).toContain('OK');
        });

        it('does not alert when car not at home', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 30,
                bmwI5Location: 'not_home', // Not at home
                evState: 128
            };
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(0);
        });

        it('does not alert when car is plugged in (evState 129)', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 30,
                bmwI5Location: 'home',
                evState: 129 // Car plugged in and ready
            };
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(0);
            expect(result.planEntries.length).toBeGreaterThan(0);
            expect(result.planEntries[0]).toContain('plugged in');
        });

        it('does not alert when car is charging (evState 132)', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 30,
                bmwI5Location: 'home',
                evState: 132 // Car charging
            };
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(0);
            expect(result.planEntries.length).toBeGreaterThan(0);
            expect(result.planEntries[0]).toContain('plugged in');
        });

        it('alerts for both cars when both low and not plugged in', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 30,
                bmwI5Range: 100,
                bmwI5Location: 'home',
                bmwIx1Battery: 40,
                bmwIx1Range: 150,
                bmwIx1Location: 'home',
                evState: 128 // No car on charger
            };
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(2);
            expect(result.alerts[0].message).toContain('BMW i5');
            expect(result.alerts[1].message).toContain('BMW iX1');
        });

        it('works at 21:00', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20, 21, 22], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 30,
                bmwI5Location: 'home',
                evState: 128
            };
            const now = new Date(2024, 0, 15, 21, 30, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(1);
        });

        it('works at 22:00', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20, 21, 22], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 30,
                bmwI5Location: 'home',
                evState: 128
            };
            const now = new Date(2024, 0, 15, 22, 15, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(1);
        });

        it('handles null battery gracefully', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: null,
                bmwI5Location: 'home',
                evState: 128
            };
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = checkBmwLowBattery(inputs, config, now);

            expect(result.alerts).toHaveLength(0);
        });
    });

    describe('calculateDecisions with BMW check', () => {
        it('includes BMW alerts in result during check hours', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 30,
                bmwI5Range: 100,
                bmwI5Location: 'home',
                evState: 128
            };
            const deviceState = createInitialDeviceStates();
            const now = new Date(2024, 0, 15, 20, 0, 0).getTime();

            const result = calculateDecisions(inputs, config, deviceState, now);

            expect(result.alerts.some(a => a.message.includes('BMW i5'))).toBe(true);
            expect(result.plan.some(p => p.includes('BMW i5'))).toBe(true);
        });

        it('does not include BMW alerts outside check hours', () => {
            const config = {
                ...defaultConfig,
                bmwLowBattery: { enabled: true, checkHours: [20], batteryThreshold: 50 }
            };
            const inputs = {
                ...baseInputs,
                bmwI5Battery: 30,
                bmwI5Location: 'home',
                evState: 128
            };
            const deviceState = createInitialDeviceStates();
            const now = new Date(2024, 0, 15, 15, 0, 0).getTime();

            const result = calculateDecisions(inputs, config, deviceState, now);

            expect(result.alerts.filter(a => a.message?.includes('BMW'))).toHaveLength(0);
        });
    });
});
