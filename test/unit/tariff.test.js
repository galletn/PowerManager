/**
 * Tariff module unit tests
 */

'use strict';

const { getTariffInfo, getNextNonPeak, isPeakTariff, isSuperOffPeak } = require('../../src/logic/tariff');

describe('getTariffInfo', () => {
    describe('weekday tariffs', () => {
        test('super off-peak at 02:00', () => {
            const date = new Date('2024-01-15T02:00:00'); // Monday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('super-off-peak');
            expect(result.max).toBe(8000);
            expect(result.end).toBe(7);
            expect(result.next).toBe('peak');
            expect(result.nextTime).toBe('07:00');
        });

        test('peak at 08:00', () => {
            const date = new Date('2024-01-15T08:00:00'); // Monday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('peak');
            expect(result.max).toBe(2500);
            expect(result.end).toBe(11);
            expect(result.next).toBe('off-peak');
            expect(result.nextTime).toBe('11:00');
        });

        test('off-peak at 12:00', () => {
            const date = new Date('2024-01-15T12:00:00'); // Monday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('off-peak');
            expect(result.max).toBe(5000);
            expect(result.end).toBe(17);
            expect(result.next).toBe('peak');
            expect(result.nextTime).toBe('17:00');
        });

        test('peak at 18:00', () => {
            const date = new Date('2024-01-15T18:00:00'); // Monday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('peak');
            expect(result.max).toBe(2500);
            expect(result.end).toBe(22);
            expect(result.next).toBe('off-peak');
            expect(result.nextTime).toBe('22:00');
        });

        test('off-peak at 23:00', () => {
            const date = new Date('2024-01-15T23:00:00'); // Monday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('off-peak');
            expect(result.max).toBe(5000);
            expect(result.end).toBe(1);
            expect(result.next).toBe('super-off-peak');
            expect(result.nextTime).toBe('01:00');
        });
    });

    describe('weekend tariffs', () => {
        test('super off-peak at 03:00 Saturday', () => {
            const date = new Date('2024-01-13T03:00:00'); // Saturday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('super-off-peak');
            expect(result.max).toBe(8000);
        });

        test('off-peak at 08:00 Sunday', () => {
            const date = new Date('2024-01-14T08:00:00'); // Sunday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('off-peak');
            expect(result.max).toBe(5000);
        });

        test('super off-peak at 14:00 Saturday', () => {
            const date = new Date('2024-01-13T14:00:00'); // Saturday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('super-off-peak');
            expect(result.max).toBe(8000);
            expect(result.end).toBe(17);
        });

        test('off-peak at 20:00 Sunday', () => {
            const date = new Date('2024-01-14T20:00:00'); // Sunday
            const result = getTariffInfo(date);

            expect(result.tariff).toBe('off-peak');
            expect(result.max).toBe(5000);
        });
    });

    describe('boundary cases', () => {
        test('exactly 07:00 on weekday is peak', () => {
            const date = new Date('2024-01-15T07:00:00');
            expect(getTariffInfo(date).tariff).toBe('peak');
        });

        test('06:59 on weekday is still super off-peak', () => {
            const date = new Date('2024-01-15T06:59:00');
            expect(getTariffInfo(date).tariff).toBe('super-off-peak');
        });

        test('exactly 11:00 on weekday is off-peak', () => {
            const date = new Date('2024-01-15T11:00:00');
            expect(getTariffInfo(date).tariff).toBe('off-peak');
        });

        test('exactly 17:00 on weekday is peak', () => {
            const date = new Date('2024-01-15T17:00:00');
            expect(getTariffInfo(date).tariff).toBe('peak');
        });

        test('exactly 22:00 on weekday is off-peak', () => {
            const date = new Date('2024-01-15T22:00:00');
            expect(getTariffInfo(date).tariff).toBe('off-peak');
        });
    });

    describe('custom limits', () => {
        test('uses custom limits when provided', () => {
            const date = new Date('2024-01-15T08:00:00');
            const customLimits = { peak: 1000, offPeak: 3000, superOffPeak: 6000 };
            const result = getTariffInfo(date, customLimits);

            expect(result.max).toBe(1000);
        });
    });
});

describe('getNextNonPeak', () => {
    test('during morning peak returns 11:00', () => {
        const date = new Date('2024-01-15T09:00:00');
        const result = getNextNonPeak(date);

        expect(result.time).toBe('11:00');
        expect(result.tariff).toBe('off-peak');
    });

    test('during evening peak returns 22:00', () => {
        const date = new Date('2024-01-15T18:00:00');
        const result = getNextNonPeak(date);

        expect(result.time).toBe('22:00');
        expect(result.tariff).toBe('off-peak');
    });

    test('on weekend always returns 01:00 super off-peak', () => {
        const date = new Date('2024-01-14T10:00:00'); // Sunday
        const result = getNextNonPeak(date);

        expect(result.time).toBe('01:00');
        expect(result.tariff).toBe('super-off-peak');
    });
});

describe('isPeakTariff', () => {
    test('returns true during peak hours', () => {
        expect(isPeakTariff(new Date('2024-01-15T09:00:00'))).toBe(true);
        expect(isPeakTariff(new Date('2024-01-15T18:00:00'))).toBe(true);
    });

    test('returns false during non-peak hours', () => {
        expect(isPeakTariff(new Date('2024-01-15T02:00:00'))).toBe(false);
        expect(isPeakTariff(new Date('2024-01-15T12:00:00'))).toBe(false);
        expect(isPeakTariff(new Date('2024-01-15T23:00:00'))).toBe(false);
    });

    test('returns false on weekends', () => {
        expect(isPeakTariff(new Date('2024-01-14T09:00:00'))).toBe(false); // Sunday
    });
});

describe('isSuperOffPeak', () => {
    test('returns true during night hours', () => {
        expect(isSuperOffPeak(new Date('2024-01-15T02:00:00'))).toBe(true);
        expect(isSuperOffPeak(new Date('2024-01-15T05:00:00'))).toBe(true);
    });

    test('returns true during weekend midday', () => {
        expect(isSuperOffPeak(new Date('2024-01-14T14:00:00'))).toBe(true); // Sunday
    });

    test('returns false during peak', () => {
        expect(isSuperOffPeak(new Date('2024-01-15T09:00:00'))).toBe(false);
    });
});
