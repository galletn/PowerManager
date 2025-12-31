/**
 * Validation module unit tests
 */

'use strict';

const {
    safeNum,
    safeStr,
    parseOverride,
    validateInputs,
    checkCriticalSensors,
    getEvStatusText
} = require('../../src/logic/validation');

describe('safeNum', () => {
    test('parses valid numbers', () => {
        expect(safeNum(123)).toBe(123);
        expect(safeNum('456.78')).toBe(456.78);
        expect(safeNum(0)).toBe(0);
        expect(safeNum(-100)).toBe(-100);
    });

    test('returns fallback for null/undefined', () => {
        expect(safeNum(null)).toBe(0);
        expect(safeNum(undefined)).toBe(0);
        expect(safeNum(null, 100)).toBe(100);
    });

    test('returns fallback for unavailable/unknown', () => {
        expect(safeNum('unavailable')).toBe(0);
        expect(safeNum('unknown')).toBe(0);
        expect(safeNum('unavailable', 50)).toBe(50);
    });

    test('returns fallback for NaN', () => {
        expect(safeNum(NaN)).toBe(0);
        expect(safeNum('not a number')).toBe(0);
        expect(safeNum('abc', 99)).toBe(99);
    });

    test('handles edge cases', () => {
        expect(safeNum('0')).toBe(0);
        expect(safeNum('')).toBe(0);
        expect(safeNum('  123  ')).toBe(123);
    });
});

describe('safeStr', () => {
    test('returns string values', () => {
        expect(safeStr('on')).toBe('on');
        expect(safeStr('off')).toBe('off');
        expect(safeStr('')).toBe('');
    });

    test('converts non-strings', () => {
        expect(safeStr(123)).toBe('123');
        expect(safeStr(true)).toBe('true');
    });

    test('returns fallback for null/undefined', () => {
        expect(safeStr(null)).toBe('');
        expect(safeStr(undefined)).toBe('');
        expect(safeStr(null, 'default')).toBe('default');
    });

    test('returns fallback for unavailable/unknown', () => {
        expect(safeStr('unavailable')).toBe('');
        expect(safeStr('unknown')).toBe('');
        expect(safeStr('unavailable', 'off')).toBe('off');
    });
});

describe('parseOverride', () => {
    describe('auto detection', () => {
        test('detects auto variants', () => {
            expect(parseOverride('Auto')).toBe('auto');
            expect(parseOverride('auto')).toBe('auto');
            expect(parseOverride('AUTO')).toBe('auto');
            expect(parseOverride('Automatisch')).toBe('auto');
        });

        test('returns auto for empty/null', () => {
            expect(parseOverride('')).toBe('auto');
            expect(parseOverride(null)).toBe('auto');
            expect(parseOverride(undefined)).toBe('auto');
        });
    });

    describe('cool detection', () => {
        test('detects English cool', () => {
            expect(parseOverride('Cool')).toBe('cool');
            expect(parseOverride('cool')).toBe('cool');
            expect(parseOverride('Cooling')).toBe('cool');
        });

        test('detects Dutch cool (koelen)', () => {
            expect(parseOverride('Koelen')).toBe('cool');
            expect(parseOverride('koelen')).toBe('cool');
        });
    });

    describe('heat detection', () => {
        test('detects English heat/on', () => {
            expect(parseOverride('Heat')).toBe('heat');
            expect(parseOverride('heat')).toBe('heat');
            expect(parseOverride('On')).toBe('heat');
            expect(parseOverride('Charge')).toBe('heat');
        });

        test('detects Dutch heat (verwarmen/aan/laden)', () => {
            expect(parseOverride('Verwarmen')).toBe('heat');
            expect(parseOverride('Aan')).toBe('heat');
            expect(parseOverride('Laden')).toBe('heat');
        });
    });

    describe('off detection', () => {
        test('detects English off', () => {
            expect(parseOverride('Off')).toBe('off');
            expect(parseOverride('off')).toBe('off');
        });

        test('detects Dutch off (uit)', () => {
            expect(parseOverride('Uit')).toBe('off');
            expect(parseOverride('uit')).toBe('off');
        });
    });
});

describe('validateInputs', () => {
    test('validates complete input set', () => {
        const raw = {
            p1_power: 1.5,
            pv_power: 2000,
            boiler_switch: 'on',
            boiler_power: 2400,
            boiler_force: 'off',
            pool_season: 'on',
            pool_power: 100,
            pool_climate: 'heat',
            ev_state: 132,
            ev_switch: 'on',
            ev_power: 6000,
            ev_limit: 10,
            heater_right_switch: 'off',
            heater_table_switch: 'off',
            ac_living_state: 'heat',
            ac_mancave_state: 'off',
            ac_office_state: 'off',
            ac_bedroom_state: 'cool',
            ac_living_power: 500,
            ac_office_power: 0,
            temp_living: 21.5,
            temp_bedroom: 20.0,
            temp_mancave: 18.5,
            ovr_ac_living: 'Auto',
            ovr_ac_bedroom: 'Cool',
            ovr_ac_office: 'Auto',
            ovr_ac_mancave: 'Auto',
            ovr_pool: 'Heat',
            ovr_boiler: 'Auto',
            ovr_ev: 'Charge'
        };

        const result = validateInputs(raw);

        expect(result.p1Power).toBe(1.5);
        expect(result.pvPower).toBe(2000);
        expect(result.boilerSwitch).toBe('on');
        expect(result.evState).toBe(132);
        expect(result.tempLiving).toBe(21.5);
        expect(result.ovrPool).toBe('Heat');
    });

    test('handles missing fields with defaults', () => {
        const raw = {};
        const result = validateInputs(raw);

        expect(result.p1Power).toBe(0);
        expect(result.pvPower).toBe(0);
        expect(result.boilerSwitch).toBe('unknown');
        expect(result.evState).toBe(128); // No car
        expect(result.tempLiving).toBe(20);
    });

    test('handles unavailable sensors', () => {
        const raw = {
            p1_power: 'unavailable',
            pv_power: 'unknown',
            ev_state: 'unavailable'
        };
        const result = validateInputs(raw);

        expect(result.p1Power).toBe(0);
        expect(result.pvPower).toBe(0);
        expect(result.evState).toBe(128);
    });
});

describe('checkCriticalSensors', () => {
    test('returns empty array when sensors available', () => {
        const raw = {
            p1_power: 1.5,
            pv_power: 2000
        };
        expect(checkCriticalSensors(raw)).toEqual([]);
    });

    test('returns warnings for unavailable sensors', () => {
        const raw = {
            p1_power: 'unavailable',
            pv_power: 'unavailable'
        };
        const warnings = checkCriticalSensors(raw);

        expect(warnings).toContain('P1 meter unavailable');
        expect(warnings).toContain('PV sensor unavailable');
    });

    test('returns partial warnings', () => {
        const raw = {
            p1_power: 1.5,
            pv_power: 'unavailable'
        };
        const warnings = checkCriticalSensors(raw);

        expect(warnings).not.toContain('P1 meter unavailable');
        expect(warnings).toContain('PV sensor unavailable');
    });
});

describe('getEvStatusText', () => {
    test('returns correct status for known codes', () => {
        expect(getEvStatusText(128)).toBe('No car');
        expect(getEvStatusText(129)).toBe('Ready');
        expect(getEvStatusText(130)).toBe('Full');
        expect(getEvStatusText(132)).toBe('Charging');
    });

    test('returns code for unknown values', () => {
        expect(getEvStatusText(999)).toBe('Code 999');
        expect(getEvStatusText(0)).toBe('Code 0');
    });

    test('accepts custom state codes', () => {
        const customCodes = { 200: 'Custom State' };
        expect(getEvStatusText(200, customCodes)).toBe('Custom State');
    });
});
