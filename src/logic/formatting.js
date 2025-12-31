/**
 * Output formatting module
 *
 * Provides consistent formatting for power values, times, and status messages.
 *
 * @module formatting
 */

'use strict';

/**
 * Format power value with appropriate unit (W or kW)
 *
 * @param {number} watts - Power in watts
 * @returns {string} Formatted string with unit
 *
 * @example
 * fmtW(500)     // => '500W'
 * fmtW(1500)    // => '1.5kW'
 * fmtW(-2500)   // => '-2.5kW'
 * fmtW(0)       // => '0W'
 */
function fmtW(watts) {
    if (Math.abs(watts) >= 1000) {
        return (watts / 1000).toFixed(1) + 'kW';
    }
    return Math.round(watts) + 'W';
}

/**
 * Format decimal hours to HH:MM
 *
 * @param {number} hours - Time as decimal hours (e.g., 6.5 = 06:30)
 * @returns {string} Formatted time string
 *
 * @example
 * fmtTime(6.5)    // => '06:30'
 * fmtTime(14.25)  // => '14:15'
 * fmtTime(0)      // => '00:00'
 */
function fmtTime(hours) {
    const h = Math.floor(hours);
    const m = Math.round((hours % 1) * 60);
    return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
}

/**
 * Format timestamp to locale time string
 *
 * @param {Date|number} timestamp - Date or timestamp
 * @param {string} [locale='en-GB'] - Locale for formatting
 * @returns {string} Formatted time (HH:MM)
 *
 * @example
 * fmtTimestamp(new Date('2024-01-15T14:30:00'))  // => '14:30'
 */
function fmtTimestamp(timestamp, locale = 'en-GB') {
    const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
    return date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
}

/**
 * Format temperature with unit
 *
 * @param {number} temp - Temperature in Celsius
 * @param {number} [decimals=1] - Decimal places
 * @returns {string} Formatted temperature
 *
 * @example
 * fmtTemp(21.5)    // => '21.5C'
 * fmtTemp(21.567)  // => '21.6C'
 */
function fmtTemp(temp, decimals = 1) {
    return temp.toFixed(decimals) + 'C';
}

/**
 * Build status line for display
 *
 * @param {Object} params - Status parameters
 * @param {string} params.tariff - Current tariff
 * @param {number} params.p1 - Grid power (W)
 * @param {number} params.pv - PV power (W)
 * @param {number} params.available - Available power (W)
 * @returns {string} Formatted status line
 *
 * @example
 * buildStatusLine({ tariff: 'peak', p1: 1500, pv: 2000, available: 1000 })
 * // => 'PEAK | 1.5kW | PV 2kW | 1kW avail'
 */
function buildStatusLine({ tariff, p1, pv, available }) {
    const tariffLabel = tariff.toUpperCase().replace(/-/g, ' ');
    return `${tariffLabel} | ${fmtW(p1)} | PV ${fmtW(pv)} | ${fmtW(available)} avail`;
}

/**
 * Build grid status indicator
 *
 * @param {number} p1 - Grid power (W), negative = exporting
 * @param {number} maxImport - Maximum allowed import (W)
 * @returns {string} Status indicator
 *
 * @example
 * gridIndicator(-500, 2500)   // => '(exp)'
 * gridIndicator(2200, 2500)   // => '(!)'
 * gridIndicator(1000, 2500)   // => ''
 */
function gridIndicator(p1, maxImport) {
    if (p1 < 0) return '(exp)';
    if (p1 > maxImport * 0.8) return '(!)';
    return '';
}

/**
 * Join plan entries for display
 *
 * @param {string[]} plan - Array of plan entries
 * @param {string} [separator=' | '] - Join separator
 * @param {number} [maxLength=250] - Maximum output length
 * @returns {string} Joined plan string
 */
function joinPlan(plan, separator = ' | ', maxLength = 250) {
    const joined = plan.join(separator);
    return joined.substring(0, maxLength);
}

/**
 * Format action log entry
 *
 * @param {string} action - Action description
 * @param {Date|number} [timestamp] - Optional timestamp
 * @param {string} [locale='en-GB'] - Locale for time formatting
 * @returns {string} Formatted log entry
 *
 * @example
 * formatLogEntry('EV ON @ 12A', new Date())  // => '14:30 EV ON @ 12A'
 */
function formatLogEntry(action, timestamp = new Date(), locale = 'en-GB') {
    const ts = fmtTimestamp(timestamp, locale);
    return `${ts} ${action}`;
}

module.exports = {
    fmtW,
    fmtTime,
    fmtTimestamp,
    fmtTemp,
    buildStatusLine,
    gridIndicator,
    joinPlan,
    formatLogEntry
};
