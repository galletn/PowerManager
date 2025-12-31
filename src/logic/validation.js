/**
 * Input validation and sanitization module
 *
 * Handles conversion and validation of sensor values from Home Assistant.
 * Provides safe defaults for unavailable/unknown states.
 *
 * @module validation
 */

'use strict';

/**
 * @typedef {Object} ValidatedInputs
 * @property {number} p1Power - Grid power (W), positive = import
 * @property {number} pvPower - Solar production (W)
 * @property {string} boilerSwitch - 'on' | 'off' | 'unknown'
 * @property {number} boilerPower - Boiler consumption (W)
 * @property {string} boilerForce - 'on' | 'off'
 * @property {string} poolSeason - 'on' = summer, 'off' = winter
 * @property {number} poolPower - Pool heat pump consumption (W)
 * @property {string} poolClimate - Climate entity state
 * @property {string} poolPumpSwitch - 'on' | 'off' pool pump state
 * @property {number} poolPumpPower - Pool pump power consumption (W)
 * @property {number} poolAmbientTemp - Outside temperature at pool (C)
 * @property {number} evState - EV charger state code
 * @property {string} evSwitch - 'on' | 'off'
 * @property {number} evPower - EV charging power (W)
 * @property {number} evLimit - Current amp limit
 * @property {string} heaterRightSwitch - 'on' | 'off'
 * @property {string} heaterTableSwitch - 'on' | 'off'
 * @property {string} acLivingState - AC state
 * @property {string} acMancaveState - AC state
 * @property {string} acOfficeState - AC state
 * @property {string} acBedroomState - AC state
 * @property {number} acLivingPower - AC power consumption (W)
 * @property {number} acOfficePower - AC power consumption (W)
 * @property {number} tempLiving - Living room temperature (C)
 * @property {number} tempBedroom - Bedroom temperature (C)
 * @property {number} tempMancave - Mancave temperature (C)
 * @property {string} ovrAcLiving - Override setting
 * @property {string} ovrAcBedroom - Override setting
 * @property {string} ovrAcOffice - Override setting
 * @property {string} ovrAcMancave - Override setting
 * @property {string} ovrPool - Override setting
 * @property {string} ovrBoiler - Override setting
 * @property {string} ovrEv - Override setting
 * @property {number|null} bmwI5Battery - BMW i5 battery percentage
 * @property {number|null} bmwI5Range - BMW i5 remaining range (km)
 * @property {string} bmwI5Location - BMW i5 location ('home' | 'not_home')
 * @property {number|null} bmwIx1Battery - BMW iX1 battery percentage
 * @property {number|null} bmwIx1Range - BMW iX1 remaining range (km)
 * @property {string} bmwIx1Location - BMW iX1 location ('home' | 'not_home')
 */

/**
 * Safely parse a value as a number
 *
 * Handles HA unavailable/unknown states and invalid values.
 *
 * @param {*} val - Value to parse
 * @param {number} [fallback=0] - Default if value is invalid
 * @returns {number} Parsed number or fallback
 *
 * @example
 * safeNum('123.45')        // => 123.45
 * safeNum('unavailable')   // => 0
 * safeNum(null, 100)       // => 100
 * safeNum(NaN)             // => 0
 */
function safeNum(val, fallback = 0) {
    if (val === null || val === undefined) return fallback;
    if (val === 'unavailable' || val === 'unknown') return fallback;
    const num = parseFloat(val);
    return isNaN(num) ? fallback : num;
}

/**
 * Safely parse a value as a string
 *
 * @param {*} val - Value to parse
 * @param {string} [fallback=''] - Default if value is invalid
 * @returns {string} String value or fallback
 *
 * @example
 * safeStr('on')            // => 'on'
 * safeStr('unavailable')   // => ''
 * safeStr(null, 'off')     // => 'off'
 */
function safeStr(val, fallback = '') {
    if (val === null || val === undefined) return fallback;
    if (val === 'unavailable' || val === 'unknown') return fallback;
    return String(val);
}

/**
 * Parse override value to normalized action
 *
 * Handles both English and Dutch override labels.
 *
 * @param {string} val - Override input_select value
 * @returns {'auto'|'cool'|'heat'|'off'} Normalized override action
 *
 * @example
 * parseOverride('Auto')           // => 'auto'
 * parseOverride('Cool')           // => 'cool'
 * parseOverride('Koelen')         // => 'cool'  (Dutch)
 * parseOverride('Verwarmen')      // => 'heat'  (Dutch)
 * parseOverride('Laden')          // => 'heat'  (Dutch for EV charge)
 * parseOverride('Uit')            // => 'off'   (Dutch)
 */
function parseOverride(val) {
    if (!val) return 'auto';
    const v = val.toLowerCase();

    if (v.includes('auto')) return 'auto';
    if (v.includes('koel') || v.includes('cool')) return 'cool';
    if (v.includes('verwarm') || v.includes('heat') ||
        v.includes('aan') || v.includes('on') ||
        v.includes('lad') || v.includes('charg')) return 'heat';
    if (v.includes('uit') || v.includes('off')) return 'off';

    return 'auto';
}

/**
 * Validate all raw inputs and return sanitized object
 *
 * @param {Object} raw - Raw message properties from state gathering
 * @returns {ValidatedInputs} Validated and sanitized inputs
 *
 * @example
 * const validated = validateInputs({
 *   p1_power: 1.5,
 *   pv_power: 'unavailable',
 *   ev_state: '132'
 * });
 * // => { p1Power: 1.5, pvPower: 0, evState: 132, ... }
 */
function validateInputs(raw) {
    return {
        // Power readings
        p1Power: safeNum(raw.p1_power, 0),
        pvPower: safeNum(raw.pv_power, 0),

        // Boiler
        boilerSwitch: safeStr(raw.boiler_switch, 'unknown'),
        boilerPower: safeNum(raw.boiler_power, 0),
        boilerForce: safeStr(raw.boiler_force, 'off'),

        // Pool
        poolSeason: safeStr(raw.pool_season, 'off'),
        poolPower: safeNum(raw.pool_power, 0),
        poolClimate: safeStr(raw.pool_climate, 'off'),
        poolPumpSwitch: safeStr(raw.pool_pump_switch, 'unknown'),
        poolPumpPower: safeNum(raw.pool_pump_power, 0),
        poolAmbientTemp: safeNum(raw.pool_ambient_temp, null),

        // EV
        evState: safeNum(raw.ev_state, 128), // 128 = no car
        evSwitch: safeStr(raw.ev_switch, 'off'),
        evPower: safeNum(raw.ev_power, 0),
        evLimit: safeNum(raw.ev_limit, 6),

        // Heaters
        heaterRightSwitch: safeStr(raw.heater_right_switch, 'off'),
        heaterTableSwitch: safeStr(raw.heater_table_switch, 'off'),

        // AC states
        acLivingState: safeStr(raw.ac_living_state, 'off'),
        acMancaveState: safeStr(raw.ac_mancave_state, 'off'),
        acOfficeState: safeStr(raw.ac_office_state, 'off'),
        acBedroomState: safeStr(raw.ac_bedroom_state, 'off'),

        // AC power readings
        acLivingPower: safeNum(raw.ac_living_power, 0),
        acOfficePower: safeNum(raw.ac_office_power, 0),

        // Temperatures
        tempLiving: safeNum(raw.temp_living, 20),
        tempBedroom: safeNum(raw.temp_bedroom, 20),
        tempMancave: safeNum(raw.temp_mancave, 20),

        // Overrides
        ovrAcLiving: safeStr(raw.ovr_ac_living, ''),
        ovrAcBedroom: safeStr(raw.ovr_ac_bedroom, ''),
        ovrAcOffice: safeStr(raw.ovr_ac_office, ''),
        ovrAcMancave: safeStr(raw.ovr_ac_mancave, ''),
        ovrPool: safeStr(raw.ovr_pool, ''),
        ovrBoiler: safeStr(raw.ovr_boiler, ''),
        ovrEv: safeStr(raw.ovr_ev, ''),

        // BMW Cars
        bmwI5Battery: safeNum(raw.bmw_i5_battery, null),
        bmwI5Range: safeNum(raw.bmw_i5_range, null),
        bmwI5Location: safeStr(raw.bmw_i5_location, 'unknown'),
        bmwIx1Battery: safeNum(raw.bmw_ix1_battery, null),
        bmwIx1Range: safeNum(raw.bmw_ix1_range, null),
        bmwIx1Location: safeStr(raw.bmw_ix1_location, 'unknown')
    };
}

/**
 * Check for critical unavailable sensors
 *
 * @param {Object} raw - Raw message properties
 * @returns {string[]} Array of warning messages
 */
function checkCriticalSensors(raw) {
    const warnings = [];

    if (raw.p1_power === 'unavailable') {
        warnings.push('P1 meter unavailable');
    }
    if (raw.pv_power === 'unavailable') {
        warnings.push('PV sensor unavailable');
    }

    return warnings;
}

/**
 * Normalize EV state code to status string
 *
 * @param {number} stateCode - EV charger state code
 * @param {Object} [stateCodes] - Custom state code mapping
 * @returns {string} Human-readable status
 */
function getEvStatusText(stateCode, stateCodes = {}) {
    const codes = {
        128: 'No car',
        129: 'Ready',
        130: 'Full',
        132: 'Charging',
        ...stateCodes
    };

    return codes[stateCode] || `Code ${stateCode}`;
}

module.exports = {
    safeNum,
    safeStr,
    parseOverride,
    validateInputs,
    checkCriticalSensors,
    getEvStatusText
};
