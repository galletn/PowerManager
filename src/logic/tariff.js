/**
 * Tariff calculation module
 *
 * Determines electricity tariff based on time of day and day of week.
 * Belgian/Dutch tariff structure:
 * - Peak: Weekdays 07:00-11:00 and 17:00-22:00
 * - Off-peak: Other daytime hours
 * - Super off-peak: 01:00-07:00 daily, weekends 11:00-17:00
 *
 * @module tariff
 */

'use strict';

/**
 * @typedef {Object} TariffInfo
 * @property {'peak'|'off-peak'|'super-off-peak'} tariff - Current tariff name
 * @property {number} max - Maximum allowed import in watts
 * @property {number} end - Hour when this tariff ends
 * @property {'peak'|'off-peak'|'super-off-peak'} next - Next tariff name
 * @property {string} nextTime - Time when next tariff starts (HH:MM format)
 */

/**
 * @typedef {Object} TariffLimits
 * @property {number} peak - Max import during peak (default: 2500W)
 * @property {number} offPeak - Max import during off-peak (default: 5000W)
 * @property {number} superOffPeak - Max import during super off-peak (default: 8000W)
 */

const DEFAULT_LIMITS = {
    peak: 2500,
    offPeak: 5000,
    superOffPeak: 8000
};

/**
 * Get tariff information for a given date/time
 *
 * @param {Date} date - The timestamp to check
 * @param {TariffLimits} [limits] - Optional custom power limits
 * @returns {TariffInfo} Tariff information including name, max power, and next period
 *
 * @example
 * // Weekday morning peak
 * getTariffInfo(new Date('2024-01-15T08:30:00'));
 * // => { tariff: 'peak', max: 2500, end: 11, next: 'off-peak', nextTime: '11:00' }
 *
 * @example
 * // Weekend afternoon (super off-peak)
 * getTariffInfo(new Date('2024-01-14T14:00:00'));
 * // => { tariff: 'super-off-peak', max: 8000, end: 17, next: 'off-peak', nextTime: '17:00' }
 */
function getTariffInfo(date, limits = {}) {
    const time = date.getHours() + date.getMinutes() / 60;
    const isWeekend = date.getDay() === 0 || date.getDay() === 6;

    const max = {
        peak: limits.peak ?? DEFAULT_LIMITS.peak,
        offPeak: limits.offPeak ?? DEFAULT_LIMITS.offPeak,
        superOffPeak: limits.superOffPeak ?? DEFAULT_LIMITS.superOffPeak
    };

    if (isWeekend) {
        if (time >= 1 && time < 7) {
            return {
                tariff: 'super-off-peak',
                max: max.superOffPeak,
                end: 7,
                next: 'off-peak',
                nextTime: '07:00'
            };
        }
        if (time >= 7 && time < 11) {
            return {
                tariff: 'off-peak',
                max: max.offPeak,
                end: 11,
                next: 'super-off-peak',
                nextTime: '11:00'
            };
        }
        if (time >= 11 && time < 17) {
            return {
                tariff: 'super-off-peak',
                max: max.superOffPeak,
                end: 17,
                next: 'off-peak',
                nextTime: '17:00'
            };
        }
        return {
            tariff: 'off-peak',
            max: max.offPeak,
            end: 1,
            next: 'super-off-peak',
            nextTime: '01:00'
        };
    }

    // Weekday
    if (time >= 1 && time < 7) {
        return {
            tariff: 'super-off-peak',
            max: max.superOffPeak,
            end: 7,
            next: 'peak',
            nextTime: '07:00'
        };
    }
    if (time >= 7 && time < 11) {
        return {
            tariff: 'peak',
            max: max.peak,
            end: 11,
            next: 'off-peak',
            nextTime: '11:00'
        };
    }
    if (time >= 11 && time < 17) {
        return {
            tariff: 'off-peak',
            max: max.offPeak,
            end: 17,
            next: 'peak',
            nextTime: '17:00'
        };
    }
    if (time >= 17 && time < 22) {
        return {
            tariff: 'peak',
            max: max.peak,
            end: 22,
            next: 'off-peak',
            nextTime: '22:00'
        };
    }
    return {
        tariff: 'off-peak',
        max: max.offPeak,
        end: 1,
        next: 'super-off-peak',
        nextTime: '01:00'
    };
}

/**
 * Get the next non-peak tariff period
 *
 * Useful for planning when to start high-power devices that should
 * avoid peak tariff.
 *
 * @param {Date} date - Current timestamp
 * @param {TariffLimits} [limits] - Optional custom power limits
 * @returns {{ time: string, tariff: string, max: number }}
 *
 * @example
 * // During morning peak
 * getNextNonPeak(new Date('2024-01-15T09:00:00'));
 * // => { time: '11:00', tariff: 'off-peak', max: 5000 }
 */
function getNextNonPeak(date, limits = {}) {
    const time = date.getHours() + date.getMinutes() / 60;
    const isWeekend = date.getDay() === 0 || date.getDay() === 6;

    const max = {
        offPeak: limits.offPeak ?? DEFAULT_LIMITS.offPeak,
        superOffPeak: limits.superOffPeak ?? DEFAULT_LIMITS.superOffPeak
    };

    // Weekend is always non-peak or super off-peak
    if (isWeekend) {
        return { time: '01:00', tariff: 'super-off-peak', max: max.superOffPeak };
    }

    // Weekday peak periods: 07-11 and 17-22
    if (time >= 7 && time < 11) {
        return { time: '11:00', tariff: 'off-peak', max: max.offPeak };
    }
    if (time >= 17 && time < 22) {
        return { time: '22:00', tariff: 'off-peak', max: max.offPeak };
    }
    if (time >= 22 || time < 1) {
        return { time: '01:00', tariff: 'super-off-peak', max: max.superOffPeak };
    }

    // Already in non-peak, return next super off-peak
    return { time: '01:00', tariff: 'super-off-peak', max: max.superOffPeak };
}

/**
 * Check if currently in peak tariff
 *
 * @param {Date} date - Timestamp to check
 * @returns {boolean} True if currently peak tariff
 */
function isPeakTariff(date) {
    return getTariffInfo(date).tariff === 'peak';
}

/**
 * Check if currently in super off-peak tariff
 *
 * @param {Date} date - Timestamp to check
 * @returns {boolean} True if currently super off-peak
 */
function isSuperOffPeak(date) {
    return getTariffInfo(date).tariff === 'super-off-peak';
}

/**
 * Format tariff name for display
 *
 * @param {string} tariff - Tariff identifier
 * @returns {string} Human-readable tariff name
 */
function formatTariffName(tariff) {
    return tariff.toUpperCase().replace(/-/g, ' ');
}

module.exports = {
    getTariffInfo,
    getNextNonPeak,
    isPeakTariff,
    isSuperOffPeak,
    formatTariffName,
    DEFAULT_LIMITS
};
