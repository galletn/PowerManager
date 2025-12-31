/**
 * Default Power Manager Configuration
 *
 * This configuration can be customized via the CONFIG node in Node-RED
 * or by environment variables.
 *
 * @module config
 */

'use strict';

const defaultConfig = {
    // === UNIT CONVERSIONS ===
    // Multiply raw sensor values by these factors
    units: {
        p1: 1000,      // P1 meter: kW → W
        pv: 1,         // SolarEdge: already in W
        boiler: 1,
        poolHeat: 1,
        ev: 1,
        acLiving: 1,
        acBureau: 1
    },

    // === GRID LIMITS ===
    maxImport: {
        peak: 2500,
        offPeak: 5000,
        superOffPeak: 8000
    },

    // === TIMING (seconds) ===
    hysteresis: 300,        // Power buffer before switching
    minOnTime: 300,         // Minimum on-time before allowing off
    minOffTime: 180,        // Minimum off-time before allowing on
    evAmpChangeThreshold: 2, // Min amp change to avoid flapping

    // === EV CHARGER ===
    ev: {
        minAmps: 6,
        maxAmps: 16,
        wattsPerAmp: 692,
        // State codes from ABB Terra AC
        states: {
            NO_CAR: 128,
            READY: 129,
            FULL: 130,
            CHARGING: 132
        }
    },

    // === BOILER ===
    boiler: {
        power: 2500,
        idleThreshold: 50,      // Below this = fully heated
        deadlineWinter: 6.5,    // 06:30 - must be hot by this time
        deadlineSummer: 8.0     // 08:00
    },

    // === POOL HEAT PUMP ===
    pool: {
        idlePower: 100,
        activePower: 2000
    },

    // === FROST PROTECTION ===
    frostProtection: {
        enabled: true,
        tempThreshold: 5,           // Start protection below this temp (°C)
        criticalThreshold: 2,       // Critical alert threshold (°C)
        pumpMinPower: 100,          // Min power (W) to consider pump actually running
        pumpOffAlertDelay: 300,     // Alert if pump off for this long (seconds)
        notifyEntity: 'mobile_app_iphone_van_nicolas_2'
    },

    // === BMW CARS LOW BATTERY WARNING ===
    bmwLowBattery: {
        enabled: true,
        batteryThreshold: 50,       // Warn if below this % at check time
        checkHours: [20, 21, 22],   // Hours to check (20:00, 21:00, 22:00)
        notifyEntity: 'mobile_app_iphone_van_nicolas_2',
        cars: {
            i5: {
                name: 'BMW i5',
                batteryEntity: 'sensor.i5_edrive40_battery_hv_state_of_charge',
                rangeEntity: 'sensor.i5_edrive40_range_ev_remaining_range',
                locationEntity: 'device_tracker.i5_edrive40_location'
            },
            ix1: {
                name: 'BMW iX1',
                batteryEntity: 'sensor.ix1_edrive20_battery_hv_state_of_charge',
                rangeEntity: 'sensor.ix1_edrive20_range_ev_remaining_range',
                locationEntity: 'device_tracker.ix1_edrive20_location'
            }
        }
    },

    // === HEATERS ===
    heaters: {
        right: { power: 2500 },
        table: { power: 4100 }
    },

    // === AC UNITS ===
    ac: {
        living:   { power: 1500, winterSetpoint: 21 },
        mancave:  { power: 1000, winterSetpoint: 17 },
        office:   { power: 1000, winterSetpoint: 22 },
        bedroom:  { power: 1000, winterSetpoint: 22 }
    },

    // === TEMPERATURE ===
    summerCoolThreshold: 25,
    summerTargetTemp: 22,

    // === ENTITIES ===
    // Centralized entity registry - change here, not in handlers
    entities: {
        p1: 'sensor.electricity_currently_delivered',           // Import power (faster updates)
        p1Return: 'sensor.electricity_currently_returned',      // Export power
        pv: 'sensor.solaredge_i1_ac_power',
        ev: {
            switch: 'switch.abb_terra_ac_charging',
            power: 'sensor.abb_terra_ac_active_power',
            limit: 'number.abb_terra_ac_current_limit',
            state: 'sensor.abb_terra_ac_charging_state'
        },
        boiler: {
            switch: 'switch.storage_boiler',
            power: 'sensor.storage_boiler_power',
            force: 'input_boolean.force_heat_boiler'
        },
        pool: {
            climate: 'climate.98d8639f920c',
            power: 'sensor.pool_heating_current_consumption',
            season: 'input_boolean.pool_season',
            pump: 'switch.poolhouse_pool_pump',
            pumpPower: 'sensor.poolhouse_pool_pump_power',
            ambientTemp: 'sensor.98d8639f920c_ambient_temp_t05',
            inletTemp: 'sensor.98d8639f920c_inlet_water_temp_t02',
            outletTemp: 'sensor.98d8639f920c_outlet_water_temp_t03'
        },
        heaters: {
            right: 'switch.livingroom_right_heater',
            table: 'switch.livingroom_table_heater_state'
        },
        ac: {
            living: 'climate.living',
            mancave: 'climate.mancave',
            office: 'climate.bureau',
            bedroom: 'climate.slaapkamer'
        },
        acPower: {
            living: 'sensor.living_current_power',
            office: 'sensor.bureau_current_power'
        },
        temp: {
            living: 'sensor.livingroom_temperature_temperature',
            bedroom: 'sensor.bedroom_temperature_temperature',
            mancave: 'sensor.mancave_inside_temperature'
        },
        overrides: {
            acLiving: 'input_select.pm_override_ac_living',
            acBedroom: 'input_select.pm_override_ac_slaapkamer',
            acOffice: 'input_select.pm_override_ac_bureau',
            acMancave: 'input_select.pm_override_ac_mancave',
            pool: 'input_select.pm_override_pool',
            boiler: 'input_select.pm_override_boiler',
            ev: 'input_select.pm_override_ev'
        },
        status: {
            status: 'input_text.power_manager_status',
            plan: 'input_text.power_manager_plan',
            actions: 'input_text.power_manager_actions'
        },
        bmw: {
            i5: {
                battery: 'sensor.i5_edrive40_battery_hv_state_of_charge',
                range: 'sensor.i5_edrive40_range_ev_remaining_range',
                location: 'device_tracker.i5_edrive40_location'
            },
            ix1: {
                battery: 'sensor.ix1_edrive20_battery_hv_state_of_charge',
                range: 'sensor.ix1_edrive20_range_ev_remaining_range',
                location: 'device_tracker.ix1_edrive20_location'
            }
        }
    },

    // === OPTIONS ===
    enableNotifications: true,
    locale: 'en-GB',
    debug: false
};

/**
 * Deep merge configuration with defaults
 *
 * @param {Object} custom - Custom configuration
 * @param {Object} [base] - Base configuration (defaults to defaultConfig)
 * @returns {Object} Merged configuration
 */
function mergeConfig(custom, base = defaultConfig) {
    const result = { ...base };

    for (const key of Object.keys(custom)) {
        if (custom[key] && typeof custom[key] === 'object' && !Array.isArray(custom[key])) {
            result[key] = mergeConfig(custom[key], base[key] || {});
        } else {
            result[key] = custom[key];
        }
    }

    return result;
}

/**
 * Validate configuration
 *
 * @param {Object} config - Configuration to validate
 * @returns {{ valid: boolean, errors: string[] }}
 */
function validateConfig(config) {
    const errors = [];

    // Check required fields
    if (!config.maxImport?.peak) errors.push('maxImport.peak is required');
    if (!config.ev?.minAmps) errors.push('ev.minAmps is required');
    if (!config.ev?.maxAmps) errors.push('ev.maxAmps is required');
    if (config.ev?.minAmps >= config.ev?.maxAmps) {
        errors.push('ev.minAmps must be less than ev.maxAmps');
    }

    // Check timing values
    if (config.hysteresis < 0) errors.push('hysteresis must be positive');
    if (config.minOnTime < 0) errors.push('minOnTime must be positive');
    if (config.minOffTime < 0) errors.push('minOffTime must be positive');

    return {
        valid: errors.length === 0,
        errors
    };
}

module.exports = {
    defaultConfig,
    mergeConfig,
    validateConfig
};
