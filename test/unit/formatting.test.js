/**
 * Formatting module unit tests
 */

'use strict';

const {
    fmtW,
    fmtTime,
    fmtTemp,
    buildStatusLine,
    gridIndicator,
    joinPlan
} = require('../../src/logic/formatting');

describe('fmtW', () => {
    test('formats small values in watts', () => {
        expect(fmtW(500)).toBe('500W');
        expect(fmtW(0)).toBe('0W');
        expect(fmtW(999)).toBe('999W');
    });

    test('formats large values in kilowatts', () => {
        expect(fmtW(1000)).toBe('1.0kW');
        expect(fmtW(1500)).toBe('1.5kW');
        expect(fmtW(2500)).toBe('2.5kW');
        expect(fmtW(10000)).toBe('10.0kW');
    });

    test('handles negative values', () => {
        expect(fmtW(-500)).toBe('-500W');
        expect(fmtW(-2500)).toBe('-2.5kW');
    });

    test('rounds small values', () => {
        expect(fmtW(123.7)).toBe('124W');
        expect(fmtW(123.2)).toBe('123W');
    });

    test('formats kW with one decimal', () => {
        expect(fmtW(1234)).toBe('1.2kW');
        expect(fmtW(1256)).toBe('1.3kW');
    });
});

describe('fmtTime', () => {
    test('formats whole hours', () => {
        expect(fmtTime(0)).toBe('00:00');
        expect(fmtTime(6)).toBe('06:00');
        expect(fmtTime(12)).toBe('12:00');
        expect(fmtTime(23)).toBe('23:00');
    });

    test('formats partial hours', () => {
        expect(fmtTime(6.5)).toBe('06:30');
        expect(fmtTime(14.25)).toBe('14:15');
        expect(fmtTime(8.75)).toBe('08:45');
    });

    test('pads single digits', () => {
        expect(fmtTime(1)).toBe('01:00');
        expect(fmtTime(1.5)).toBe('01:30');
    });
});

describe('fmtTemp', () => {
    test('formats temperature with default decimals', () => {
        expect(fmtTemp(21.5)).toBe('21.5C');
        expect(fmtTemp(20)).toBe('20.0C');
    });

    test('formats with custom decimals', () => {
        expect(fmtTemp(21.567, 2)).toBe('21.57C');
        expect(fmtTemp(21.567, 0)).toBe('22C');
    });
});

describe('buildStatusLine', () => {
    test('builds complete status line', () => {
        const result = buildStatusLine({
            tariff: 'peak',
            p1: 1500,
            pv: 2000,
            available: 1000
        });

        expect(result).toBe('PEAK | 1.5kW | PV 2.0kW | 1.0kW avail');
    });

    test('handles off-peak tariff', () => {
        const result = buildStatusLine({
            tariff: 'off-peak',
            p1: 500,
            pv: 0,
            available: 4500
        });

        expect(result).toBe('OFF PEAK | 500W | PV 0W | 4.5kW avail');
    });

    test('handles super off-peak tariff', () => {
        const result = buildStatusLine({
            tariff: 'super-off-peak',
            p1: 0,
            pv: 0,
            available: 8000
        });

        expect(result).toBe('SUPER OFF PEAK | 0W | PV 0W | 8.0kW avail');
    });
});

describe('gridIndicator', () => {
    test('returns export indicator when negative', () => {
        expect(gridIndicator(-500, 2500)).toBe('(exp)');
        expect(gridIndicator(-1, 2500)).toBe('(exp)');
    });

    test('returns warning when near limit', () => {
        expect(gridIndicator(2200, 2500)).toBe('(!)'); // > 80%
        expect(gridIndicator(2400, 2500)).toBe('(!)');
        expect(gridIndicator(2500, 2500)).toBe('(!)');
    });

    test('returns empty when normal', () => {
        expect(gridIndicator(1500, 2500)).toBe('');
        expect(gridIndicator(0, 2500)).toBe('');
        expect(gridIndicator(1999, 2500)).toBe(''); // exactly 80% is not warning
    });
});

describe('joinPlan', () => {
    test('joins plan entries with separator', () => {
        const plan = ['Entry 1', 'Entry 2', 'Entry 3'];
        expect(joinPlan(plan)).toBe('Entry 1 | Entry 2 | Entry 3');
    });

    test('uses custom separator', () => {
        const plan = ['A', 'B', 'C'];
        expect(joinPlan(plan, ' - ')).toBe('A - B - C');
    });

    test('truncates to max length', () => {
        const plan = ['A very long entry', 'Another long entry'];
        const result = joinPlan(plan, ' | ', 20);
        expect(result.length).toBeLessThanOrEqual(20);
    });

    test('handles empty plan', () => {
        expect(joinPlan([])).toBe('');
    });

    test('handles single entry', () => {
        expect(joinPlan(['Single'])).toBe('Single');
    });
});
