/**
 * Decision engine module
 *
 * Core logic for determining which devices to turn on/off/adjust
 * based on power availability, tariff, season, and user overrides.
 *
 * @module decisions
 */

'use strict';

const { getTariffInfo, getNextNonPeak } = require('./tariff');
const { parseOverride, getEvStatusText } = require('./validation');
const { canSwitch, shouldAdjustEvAmps, hasSufficientPower, shouldShedLoad } = require('./timing');
const { fmtW, fmtTime, gridIndicator } = require('./formatting');

/**
 * @typedef {Object} Config
 * @property {Object} units - Unit conversion factors
 * @property {Object} maxImport - Power limits per tariff
 * @property {number} hysteresis - Power buffer (W)
 * @property {number} minOnTime - Min on-time (s)
 * @property {number} minOffTime - Min off-time (s)
 * @property {number} evAmpChangeThreshold - Min amp change
 * @property {Object} ev - EV configuration
 * @property {Object} boiler - Boiler configuration
 * @property {Object} pool - Pool configuration
 * @property {Object} heaters - Heater configurations
 * @property {Object} ac - AC unit configurations
 * @property {number} summerCoolThreshold - Temp to start cooling
 */

/**
 * @typedef {Object} DeviceDecision
 * @property {'none'|'on'|'off'|'adjust'|'heat'|'cool'} action
 * @property {number} [amps] - For EV
 * @property {string} [mode] - For AC/climate
 * @property {number} [temp] - Setpoint
 */

/**
 * @typedef {Object} DecisionResult
 * @property {Object<string, DeviceDecision>} decisions - Per-device decisions
 * @property {string[]} plan - Plan entries for display
 * @property {number} headroom - Remaining available power
 * @property {Object} meta - Additional metadata
 */

const EV_STATES = {
    NO_CAR: 128,
    READY: 129,
    FULL: 130,
    CHARGING: 132
};

/**
 * @typedef {Object} FrostAlert
 * @property {'warning'|'critical'} level
 * @property {string} message
 * @property {string} [notifyEntity] - Mobile app entity to notify
 */

/**
 * Calculate device decisions based on current state
 *
 * Main entry point for the decision engine. Takes validated inputs,
 * configuration, and device states, returns decisions for each device.
 *
 * @param {Object} inputs - Validated sensor readings
 * @param {Config} config - System configuration
 * @param {Object} deviceState - Current device states with timestamps
 * @param {number} now - Current timestamp (injectable for testing)
 * @returns {DecisionResult} Decisions and plan
 */
function calculateDecisions(inputs, config, deviceState, now) {
    const date = new Date(now);
    const tariffInfo = getTariffInfo(date, config.maxImport);
    const tariff = tariffInfo.tariff;
    const maxImport = tariffInfo.max;

    const units = config.units || {};
    const hyst = config.hysteresis || 300;

    // Apply unit conversions
    const p1 = inputs.p1Power * (units.p1 || 1);
    const pv = inputs.pvPower * (units.pv || 1);

    // Season and grid state
    const isSummer = inputs.poolSeason === 'on';
    const isExporting = p1 < 0;

    // Available power = how much we can add before hitting limit
    let avail = -p1 + maxImport;
    let headroom = avail;

    // Parse all overrides
    const ovr = {
        acLiving: parseOverride(inputs.ovrAcLiving),
        acBedroom: parseOverride(inputs.ovrAcBedroom),
        acOffice: parseOverride(inputs.ovrAcOffice),
        acMancave: parseOverride(inputs.ovrAcMancave),
        pool: parseOverride(inputs.ovrPool),
        boiler: parseOverride(inputs.ovrBoiler),
        ev: parseOverride(inputs.ovrEv)
    };

    // Parse device states
    const evState = inputs.evState;
    const evPlugged = evState !== EV_STATES.NO_CAR;
    const evCharging = evState === EV_STATES.CHARGING;
    const evReady = evState === EV_STATES.READY;
    const evDone = evState === EV_STATES.FULL;
    const evStatusText = getEvStatusText(evState);

    const boilerOn = inputs.boilerSwitch === 'on';
    const boilerForce = inputs.boilerForce === 'on';
    const boilerW = inputs.boilerPower * (units.boiler || 1);
    const boilerFull = boilerW < (config.boiler?.idleThreshold || 50);

    const poolW = inputs.poolPower * (units.poolHeat || 1);
    const poolHeating = poolW > (config.pool?.idlePower || 100);

    const hrOn = inputs.heaterRightSwitch === 'on';
    const htOn = inputs.heaterTableSwitch === 'on';
    const evOn = inputs.evSwitch === 'on';
    const evW = inputs.evPower * (units.ev || 1);
    const evLimit = inputs.evLimit;

    const acStates = {
        acLiving: inputs.acLivingState !== 'off',
        acBedroom: inputs.acBedroomState !== 'off',
        acOffice: inputs.acOfficeState !== 'off',
        acMancave: inputs.acMancaveState !== 'off'
    };

    const temps = {
        acLiving: inputs.tempLiving,
        acBedroom: inputs.tempBedroom,
        acOffice: inputs.tempLiving, // Uses living room sensor
        acMancave: inputs.tempMancave
    };

    const coolThreshold = config.summerCoolThreshold || 25;

    // Initialize decisions
    const decisions = {
        ev: { action: 'none', amps: evLimit },
        boiler: { action: 'none' },
        pool: { action: 'none' },
        poolPump: { action: 'none' },
        heaterRight: { action: 'none' },
        heaterTable: { action: 'none' },
        acLiving: { action: 'none', mode: 'off', temp: 22 },
        acMancave: { action: 'none', mode: 'off', temp: 17 },
        acOffice: { action: 'none', mode: 'off', temp: 22 },
        acBedroom: { action: 'none', mode: 'off', temp: 22 }
    };

    // Alerts for notifications
    const alerts = [];

    // Build plan
    const plan = [];
    const tariffLabel = tariff.toUpperCase().replace(/-/g, ' ');
    const gridIcon = gridIndicator(p1, maxImport);

    plan.push(`${tariffLabel} ${gridIcon} | Grid: ${fmtW(p1)} | PV: ${fmtW(pv)} | Avail: ${fmtW(avail)}`);
    plan.push(`${isSummer ? 'Summer' : 'Winter'} | EV: ${evStatusText}`);

    // Timing config
    const timingConfig = {
        minOnTime: config.minOnTime || 300,
        minOffTime: config.minOffTime || 180
    };

    // Helper for switch check
    const canSwitchDev = (device, target) =>
        canSwitch(deviceState[device], target, now, timingConfig);

    // === MANUAL OVERRIDES FIRST ===
    applyManualOverrides(decisions, plan, ovr, {
        poolHeating, boilerOn, evPlugged, evCharging, evDone,
        acStates, config
    });

    // Force boiler
    if (boilerForce && !boilerFull && ovr.boiler === 'auto') {
        decisions.boiler.action = 'on';
        plan.push('Boiler: FORCE ON');
    }

    // === FROST PROTECTION (critical - runs before seasonal logic) ===
    const frostResult = checkFrostProtection(inputs, config, deviceState, now);
    if (frostResult.poolPumpDecision.action !== 'none') {
        decisions.poolPump = frostResult.poolPumpDecision;
    }
    plan.push(...frostResult.planEntries);
    alerts.push(...frostResult.alerts);

    // === BMW LOW BATTERY CHECK (evening hours only) ===
    const bmwResult = checkBmwLowBattery(inputs, config, now);
    plan.push(...bmwResult.planEntries);
    alerts.push(...bmwResult.alerts);

    // === SEASONAL LOGIC ===
    if (!isSummer) {
        applyWinterLogic(decisions, plan, {
            ovr, evDone, evPlugged, evReady, evCharging, evLimit,
            boilerOn, boilerFull, hrOn, htOn, acStates, temps,
            headroom, hyst, tariff, tariffInfo, date, config,
            canSwitchDev, deviceState, now
        });
    } else {
        applySummerLogic(decisions, plan, {
            ovr, evDone, evPlugged, evReady, evCharging, evLimit,
            boilerOn, boilerFull, poolHeating, acStates, temps,
            headroom, hyst, tariff, isExporting, coolThreshold,
            config, canSwitchDev, deviceState, now
        });
    }

    // Recalculate final headroom
    headroom = calculateFinalHeadroom(avail, decisions, config, {
        evLimit, boilerOn, poolHeating, hrOn, htOn, acStates
    });

    plan.push(`Available: ${fmtW(headroom)}`);

    return {
        decisions,
        plan,
        headroom,
        alerts,
        meta: {
            tariff,
            p1,
            pv,
            avail,
            isSummer,
            isExporting,
            ovr,
            poolAmbientTemp: inputs.poolAmbientTemp
        }
    };
}

/**
 * Apply manual override decisions
 */
function applyManualOverrides(decisions, plan, ovr, ctx) {
    const { poolHeating, boilerOn, evPlugged, evCharging, evDone, acStates, config } = ctx;

    // Pool override
    if (ovr.pool === 'heat' && !poolHeating) {
        decisions.pool.action = 'heat';
        plan.push('Pool: MANUAL ON');
    } else if (ovr.pool === 'off' && poolHeating) {
        decisions.pool.action = 'off';
        plan.push('Pool: MANUAL OFF');
    }

    // Boiler override
    if (ovr.boiler === 'heat' && !boilerOn) {
        decisions.boiler.action = 'on';
        plan.push('Boiler: MANUAL ON');
    } else if (ovr.boiler === 'off' && boilerOn) {
        decisions.boiler.action = 'off';
        plan.push('Boiler: MANUAL OFF');
    }

    // EV override
    if (ovr.ev === 'heat' && evPlugged && !evCharging && !evDone) {
        decisions.ev = { action: 'on', amps: config.ev?.maxAmps || 16 };
        plan.push('EV: MANUAL CHARGE');
    } else if (ovr.ev === 'off' && evCharging) {
        decisions.ev = { action: 'off', amps: 0 };
        plan.push('EV: MANUAL OFF');
    }

    // AC overrides
    const acUnits = ['acLiving', 'acBedroom', 'acOffice', 'acMancave'];
    const acNames = { acLiving: 'Living', acBedroom: 'Bedroom', acOffice: 'Office', acMancave: 'Mancave' };
    const acTemps = { acLiving: 22, acBedroom: 22, acOffice: 22, acMancave: 17 };

    for (const ac of acUnits) {
        const o = ovr[ac];
        const isOn = acStates[ac];
        const temp = acTemps[ac];

        if (o === 'cool') {
            decisions[ac] = { action: 'cool', mode: 'cool', temp };
            if (!isOn) plan.push(`AC ${acNames[ac]}: MANUAL COOL`);
        } else if (o === 'heat') {
            decisions[ac] = { action: 'heat', mode: 'heat', temp };
            if (!isOn) plan.push(`AC ${acNames[ac]}: MANUAL HEAT`);
        } else if (o === 'off' && isOn) {
            decisions[ac] = { action: 'off', mode: 'off', temp };
            plan.push(`AC ${acNames[ac]}: MANUAL OFF`);
        }
    }
}

/**
 * Apply winter season logic
 */
function applyWinterLogic(decisions, plan, ctx) {
    let { headroom } = ctx;
    const {
        ovr, evDone, evPlugged, evReady, evCharging, evLimit,
        boilerOn, boilerFull, hrOn, htOn, acStates, temps,
        hyst, tariff, tariffInfo, date, config, canSwitchDev
    } = ctx;

    // EV
    if (ovr.ev === 'auto' && decisions.ev.action === 'none') {
        const result = decideEv(evDone, evPlugged, evReady, evCharging, evLimit, headroom, hyst, tariff, tariffInfo, config, canSwitchDev);
        decisions.ev = result.decision;
        plan.push(...result.planEntries);
        headroom = result.newHeadroom;
    }

    // Boiler
    if (ovr.boiler === 'auto' && decisions.boiler.action === 'none') {
        const result = decideBoiler(boilerOn, boilerFull, headroom, hyst, tariff, date, config, canSwitchDev, true);
        decisions.boiler = result.decision;
        plan.push(...result.planEntries);
        headroom = result.newHeadroom;
    }

    // AC Living (heating)
    if (ovr.acLiving === 'auto' && decisions.acLiving.action === 'none') {
        const result = decideAcHeating('acLiving', 'Living', acStates.acLiving, temps.acLiving, 21, headroom, hyst, tariff, tariffInfo, config, canSwitchDev);
        decisions.acLiving = result.decision;
        plan.push(...result.planEntries);
        headroom = result.newHeadroom;
    }

    // AC Mancave (heating)
    if (ovr.acMancave === 'auto' && decisions.acMancave.action === 'none') {
        const result = decideAcHeating('acMancave', 'Mancave', acStates.acMancave, temps.acMancave, 17, headroom, hyst, tariff, tariffInfo, config, canSwitchDev);
        decisions.acMancave = result.decision;
        plan.push(...result.planEntries);
        headroom = result.newHeadroom;
    }

    // Heater Table
    const htResult = decideHeater('heaterTable', 'Heater Table', htOn, config.heaters?.table?.power || 4100, headroom, hyst, tariff, tariffInfo, canSwitchDev);
    decisions.heaterTable = htResult.decision;
    plan.push(...htResult.planEntries);
    headroom = htResult.newHeadroom;

    // Heater Right
    const hrResult = decideHeater('heaterRight', 'Heater Right', hrOn, config.heaters?.right?.power || 2500, headroom, hyst, tariff, tariffInfo, canSwitchDev);
    decisions.heaterRight = hrResult.decision;
    plan.push(...hrResult.planEntries);
    headroom = hrResult.newHeadroom;

    ctx.headroom = headroom;
}

/**
 * Apply summer season logic
 */
function applySummerLogic(decisions, plan, ctx) {
    let { headroom } = ctx;
    const {
        ovr, evDone, evPlugged, evReady, evCharging, evLimit,
        boilerOn, boilerFull, poolHeating, acStates, temps,
        hyst, tariff, isExporting, coolThreshold, config, canSwitchDev
    } = ctx;

    // Pool
    if (ovr.pool === 'auto' && decisions.pool.action === 'none') {
        const pw = config.pool?.activePower || 2000;
        if (poolHeating) {
            if (shouldShedLoad(headroom, hyst) && canSwitchDev('pool', false)) {
                decisions.pool.action = 'off';
                plan.push('Pool: Pausing');
            } else {
                plan.push('Pool: Heating');
            }
        } else if (hasSufficientPower(headroom, pw, hyst) && canSwitchDev('pool', true)) {
            decisions.pool.action = 'heat';
            plan.push('Pool: Starting (low fan)');
            headroom -= pw;
        } else {
            plan.push(`Pool: Waiting for ${fmtW(pw)} (now ${fmtW(headroom)})`);
        }
    }

    // Boiler
    if (ovr.boiler === 'auto' && decisions.boiler.action === 'none') {
        const result = decideBoiler(boilerOn, boilerFull, headroom, hyst, tariff, new Date(), config, canSwitchDev, false);
        decisions.boiler = result.decision;
        plan.push(...result.planEntries);
        headroom = result.newHeadroom;
    }

    // EV
    if (ovr.ev === 'auto' && decisions.ev.action === 'none') {
        const result = decideEvSummer(evDone, evPlugged, evReady, evCharging, evLimit, headroom, hyst, tariff, config, canSwitchDev);
        decisions.ev = result.decision;
        plan.push(...result.planEntries);
        headroom = result.newHeadroom;
    }

    // Cooling (only when exporting)
    if (isExporting) {
        const coolOrder = ['acLiving', 'acBedroom', 'acOffice', 'acMancave'];
        const acNames = { acLiving: 'Living', acBedroom: 'Bedroom', acOffice: 'Office', acMancave: 'Mancave' };
        const powers = { acLiving: 1500, acBedroom: 1000, acOffice: 1000, acMancave: 1000 };

        for (const ac of coolOrder) {
            if (ovr[ac] !== 'auto') continue;
            if (decisions[ac].action !== 'none') continue;

            const pw = config.ac?.[ac.replace('ac', '').toLowerCase()]?.power || powers[ac];
            const temp = temps[ac];
            const isOn = acStates[ac];

            if (temp > coolThreshold && headroom >= pw) {
                if (!isOn && canSwitchDev(ac, true)) {
                    decisions[ac] = { action: 'cool', mode: 'cool', temp: 22 };
                    plan.push(`AC ${acNames[ac]}: Cooling (${temp.toFixed(1)}C)`);
                    headroom -= pw;
                } else if (isOn) {
                    plan.push(`AC ${acNames[ac]}: Cooling (${temp.toFixed(1)}C)`);
                }
            } else if (isOn && shouldShedLoad(headroom, hyst) && canSwitchDev(ac, false)) {
                decisions[ac] = { action: 'off', mode: 'off', temp: 22 };
            }
        }
    } else {
        // Not exporting - turn off cooling
        const acUnits = ['acLiving', 'acBedroom', 'acOffice', 'acMancave'];
        for (const ac of acUnits) {
            if (ovr[ac] !== 'auto') continue;
            if (acStates[ac] && canSwitchDev(ac, false)) {
                decisions[ac] = { action: 'off', mode: 'off', temp: 22 };
            }
        }
        plan.push('Cooling: Waiting for export');
    }

    ctx.headroom = headroom;
}

/**
 * Decide EV charging (winter)
 */
function decideEv(evDone, evPlugged, evReady, evCharging, evLimit, headroom, hyst, tariff, tariffInfo, config, canSwitchDev) {
    const planEntries = [];
    const wpa = config.ev?.wattsPerAmp || 692;
    const minA = config.ev?.minAmps || 6;
    const maxA = config.ev?.maxAmps || 16;
    const minEvW = minA * wpa;
    const threshold = config.evAmpChangeThreshold || 2;

    let decision = { action: 'none', amps: evLimit };
    let newHeadroom = headroom;

    if (evDone) {
        planEntries.push('EV: Full');
    } else if (evPlugged) {
        let targetA = Math.floor(headroom / wpa);
        targetA = Math.max(minA, Math.min(maxA, targetA));

        if (evCharging) {
            if (headroom < minEvW - hyst && canSwitchDev('ev', false)) {
                decision = { action: 'off', amps: 0 };
                planEntries.push(`EV: Pausing (${fmtW(headroom)} < ${fmtW(minEvW)})`);
            } else if (shouldAdjustEvAmps(evLimit, targetA, threshold)) {
                decision = { action: 'adjust', amps: targetA };
                planEntries.push(`EV: Adjusting to ${targetA}A`);
            } else {
                planEntries.push(`EV: Charging @ ${evLimit}A`);
            }
        } else if (evReady) {
            if (tariff === 'peak') {
                planEntries.push(`EV: Waiting for off-peak (${tariffInfo.nextTime})`);
            } else if (headroom >= minEvW && canSwitchDev('ev', true)) {
                decision = { action: 'on', amps: targetA };
                planEntries.push(`EV: Starting @ ${targetA}A`);
                newHeadroom -= targetA * wpa;
            } else {
                planEntries.push(`EV: Waiting for ${fmtW(minEvW)} (now ${fmtW(headroom)})`);
            }
        }
    }

    return { decision, planEntries, newHeadroom };
}

/**
 * Decide EV charging (summer - simpler)
 */
function decideEvSummer(evDone, evPlugged, evReady, evCharging, evLimit, headroom, hyst, tariff, config, canSwitchDev) {
    const planEntries = [];
    const wpa = config.ev?.wattsPerAmp || 692;
    const minA = config.ev?.minAmps || 6;
    const maxA = config.ev?.maxAmps || 16;
    const minEvW = minA * wpa;

    let decision = { action: 'none', amps: evLimit };
    let newHeadroom = headroom;

    if (evDone) {
        planEntries.push('EV: Full');
    } else if (evPlugged) {
        let targetA = Math.floor(headroom / wpa);
        targetA = Math.max(minA, Math.min(maxA, targetA));

        if (evCharging) {
            planEntries.push(`EV: Charging @ ${evLimit}A`);
        } else if (evReady && headroom >= minEvW && tariff !== 'peak' && canSwitchDev('ev', true)) {
            decision = { action: 'on', amps: targetA };
            planEntries.push(`EV: Starting @ ${targetA}A`);
            newHeadroom -= targetA * wpa;
        } else if (tariff === 'peak') {
            planEntries.push('EV: Waiting for off-peak');
        } else {
            planEntries.push(`EV: Waiting for ${fmtW(minEvW)}`);
        }
    }

    return { decision, planEntries, newHeadroom };
}

/**
 * Decide boiler
 */
function decideBoiler(boilerOn, boilerFull, headroom, hyst, tariff, date, config, canSwitchDev, isWinter) {
    const planEntries = [];
    const bw = config.boiler?.power || 2500;
    const time = date.getHours() + date.getMinutes() / 60;
    const deadline = isWinter ? (config.boiler?.deadlineWinter || 6.5) : (config.boiler?.deadlineSummer || 8.0);

    let decision = { action: 'none' };
    let newHeadroom = headroom;

    if (boilerFull) {
        planEntries.push('Boiler: Full');
    } else if (boilerOn) {
        planEntries.push('Boiler: Heating');
    } else if (isWinter) {
        const urgent = time < deadline && tariff === 'super-off-peak';
        if (urgent) {
            decision.action = 'on';
            planEntries.push(`Boiler: URGENT (deadline ${fmtTime(deadline)})`);
            newHeadroom -= bw;
        } else if (tariff !== 'super-off-peak') {
            planEntries.push('Boiler: Waiting for super off-peak (01:00)');
        } else if (hasSufficientPower(headroom, bw, hyst) && canSwitchDev('boiler', true)) {
            decision.action = 'on';
            planEntries.push('Boiler: Starting');
            newHeadroom -= bw;
        } else {
            planEntries.push(`Boiler: Waiting for ${fmtW(bw)} (now ${fmtW(headroom)})`);
        }
    } else {
        // Summer - less strict
        if (hasSufficientPower(headroom, bw, hyst) && canSwitchDev('boiler', true)) {
            decision.action = 'on';
            planEntries.push('Boiler: Starting');
            newHeadroom -= bw;
        } else {
            planEntries.push(`Boiler: Waiting for ${fmtW(bw)}`);
        }
    }

    return { decision, planEntries, newHeadroom };
}

/**
 * Decide AC heating
 */
function decideAcHeating(device, name, isOn, temp, setpoint, headroom, hyst, tariff, tariffInfo, config, canSwitchDev) {
    const planEntries = [];
    const pw = config.ac?.[device.replace('ac', '').toLowerCase()]?.power || 1000;

    let decision = { action: 'none', mode: 'off', temp: setpoint };
    let newHeadroom = headroom;

    if (isOn) {
        if (tariff === 'peak' && shouldShedLoad(headroom, hyst) && canSwitchDev(device, false)) {
            decision = { action: 'off', mode: 'off', temp: setpoint };
            planEntries.push(`AC ${name}: Load shed (peak)`);
        } else {
            planEntries.push(`AC ${name}: Heating (${temp.toFixed(1)}C)`);
        }
    } else {
        if (tariff === 'peak') {
            planEntries.push(`AC ${name}: Waiting for off-peak (${tariffInfo.nextTime})`);
        } else if (hasSufficientPower(headroom, pw, hyst) && canSwitchDev(device, true)) {
            decision = { action: 'heat', mode: 'heat', temp: setpoint };
            planEntries.push(`AC ${name}: Starting`);
            newHeadroom -= pw;
        } else {
            planEntries.push(`AC ${name}: Waiting for ${fmtW(pw)} (now ${fmtW(headroom)})`);
        }
    }

    return { decision, planEntries, newHeadroom };
}

/**
 * Decide heater
 */
function decideHeater(device, name, isOn, power, headroom, hyst, tariff, tariffInfo, canSwitchDev) {
    const planEntries = [];
    let decision = { action: 'none' };
    let newHeadroom = headroom;

    if (isOn) {
        if (shouldShedLoad(headroom, hyst) && canSwitchDev(device, false)) {
            decision.action = 'off';
            planEntries.push(`${name}: Turning off (overload)`);
        } else {
            planEntries.push(`${name}: On (${fmtW(power)})`);
        }
    } else {
        if (tariff === 'peak') {
            planEntries.push(`${name}: Waiting for off-peak (${tariffInfo.nextTime})`);
        } else if (!hasSufficientPower(headroom, power, hyst)) {
            planEntries.push(`${name}: Waiting for ${fmtW(power)} (now ${fmtW(headroom)})`);
        } else if (!canSwitchDev(device, true)) {
            planEntries.push(`${name}: Waiting (min time)`);
        } else {
            decision.action = 'on';
            planEntries.push(`${name}: Starting`);
            newHeadroom -= power;
        }
    }

    return { decision, planEntries, newHeadroom };
}

/**
 * Check frost protection status
 *
 * @param {Object} inputs - Validated inputs
 * @param {Object} config - System configuration
 * @param {Object} deviceState - Device states with timestamps
 * @param {number} now - Current timestamp
 * @returns {{ alerts: FrostAlert[], poolPumpDecision: Object, planEntries: string[] }}
 */
function checkFrostProtection(inputs, config, deviceState, now) {
    const alerts = [];
    const planEntries = [];
    let poolPumpDecision = { action: 'none' };

    const fp = config.frostProtection;
    if (!fp?.enabled) {
        return { alerts, poolPumpDecision, planEntries };
    }

    const ambientTemp = inputs.poolAmbientTemp;
    const pumpSwitchOn = inputs.poolPumpSwitch === 'on';
    const pumpPower = inputs.poolPumpPower;
    const minPumpPower = fp.pumpMinPower ?? 100;

    // Pump is only truly running if switch is on AND drawing power
    const pumpActuallyRunning = pumpSwitchOn && pumpPower >= minPumpPower;

    // No temperature reading available
    if (ambientTemp === null) {
        planEntries.push('Frost: No temp sensor');
        return { alerts, poolPumpDecision, planEntries };
    }

    const tempThreshold = fp.tempThreshold ?? 5;
    const criticalThreshold = fp.criticalThreshold ?? 2;
    const alertDelay = (fp.pumpOffAlertDelay ?? 300) * 1000; // convert to ms

    // Check if it's cold
    if (ambientTemp <= tempThreshold) {
        const isCritical = ambientTemp <= criticalThreshold;

        if (!pumpActuallyRunning) {
            // Pump is off or not drawing power during cold temps - dangerous!
            const pumpOffSince = deviceState.poolPump?.lastChange || now;
            const pumpOffDuration = now - pumpOffSince;

            // Force pump on
            poolPumpDecision = { action: 'on' };

            // Build descriptive message
            let reason = '';
            if (!pumpSwitchOn) {
                reason = 'switch OFF';
            } else if (pumpPower < minPumpPower) {
                reason = `only ${pumpPower.toFixed(0)}W (min ${minPumpPower}W)`;
            }
            planEntries.push(`Frost: PUMP ON - ${reason} (${ambientTemp.toFixed(1)}°C)`);

            // Check if we should alert
            if (pumpOffDuration >= alertDelay) {
                const level = isCritical ? 'critical' : 'warning';
                const message = isCritical
                    ? `CRITICAL: Pool pump not running at ${ambientTemp.toFixed(1)}°C! ${reason}. Freeze risk!`
                    : `Warning: Pool pump not running during cold weather (${ambientTemp.toFixed(1)}°C). ${reason}`;

                alerts.push({
                    level,
                    message,
                    notifyEntity: fp.notifyEntity
                });
            }
        } else {
            // Pump is running and drawing power, good
            if (isCritical) {
                planEntries.push(`Frost: OK, pump ${pumpPower.toFixed(0)}W (${ambientTemp.toFixed(1)}°C CRITICAL)`);
            } else {
                planEntries.push(`Frost: OK, pump ${pumpPower.toFixed(0)}W (${ambientTemp.toFixed(1)}°C)`);
            }
        }
    }

    return { alerts, poolPumpDecision, planEntries };
}

/**
 * @typedef {Object} BmwLowBatteryAlert
 * @property {'warning'} level
 * @property {string} message
 * @property {string} carName - Name of the car
 * @property {number} battery - Battery percentage
 * @property {number} range - Remaining range in km
 * @property {string} [notifyEntity] - Mobile app entity to notify
 */

/**
 * Check BMW cars for low battery at evening hours
 *
 * Sends notification if:
 * - It's between 20:00-22:00
 * - Car battery is below threshold (default 50%)
 * - Car is at home
 * - Car is NOT plugged in to ABB charger (evState != 129)
 *
 * @param {Object} inputs - Validated inputs
 * @param {Object} config - System configuration
 * @param {number} now - Current timestamp
 * @returns {{ alerts: BmwLowBatteryAlert[], planEntries: string[] }}
 */
function checkBmwLowBattery(inputs, config, now) {
    const alerts = [];
    const planEntries = [];

    const bmwConfig = config.bmwLowBattery;
    if (!bmwConfig?.enabled) {
        return { alerts, planEntries };
    }

    const date = new Date(now);
    const currentHour = date.getHours();
    const checkHours = bmwConfig.checkHours || [20, 21, 22];

    // Only check during configured hours
    if (!checkHours.includes(currentHour)) {
        return { alerts, planEntries };
    }

    const threshold = bmwConfig.batteryThreshold || 50;
    const evState = inputs.evState;
    const evPluggedIn = evState === EV_STATES.READY || evState === EV_STATES.CHARGING;

    // Check BMW i5
    const i5Battery = inputs.bmwI5Battery;
    const i5Range = inputs.bmwI5Range;
    const i5Location = inputs.bmwI5Location;

    if (i5Battery !== null && i5Battery < threshold && i5Location === 'home' && !evPluggedIn) {
        const message = `BMW i5 at ${i5Battery}%, ${i5Range || '?'}km range - not plugged in!`;
        alerts.push({
            level: 'warning',
            message,
            carName: 'BMW i5',
            battery: i5Battery,
            range: i5Range || 0,
            notifyEntity: bmwConfig.notifyEntity
        });
        planEntries.push(`BMW i5: LOW ${i5Battery}% (${i5Range}km) - not charging`);
    } else if (i5Battery !== null && i5Location === 'home') {
        if (evPluggedIn) {
            planEntries.push(`BMW i5: ${i5Battery}% (plugged in)`);
        } else if (i5Battery >= threshold) {
            planEntries.push(`BMW i5: ${i5Battery}% OK`);
        }
    }

    // Check BMW iX1
    const ix1Battery = inputs.bmwIx1Battery;
    const ix1Range = inputs.bmwIx1Range;
    const ix1Location = inputs.bmwIx1Location;

    if (ix1Battery !== null && ix1Battery < threshold && ix1Location === 'home' && !evPluggedIn) {
        const message = `BMW iX1 at ${ix1Battery}%, ${ix1Range || '?'}km range - not plugged in!`;
        alerts.push({
            level: 'warning',
            message,
            carName: 'BMW iX1',
            battery: ix1Battery,
            range: ix1Range || 0,
            notifyEntity: bmwConfig.notifyEntity
        });
        planEntries.push(`BMW iX1: LOW ${ix1Battery}% (${ix1Range}km) - not charging`);
    } else if (ix1Battery !== null && ix1Location === 'home') {
        if (evPluggedIn) {
            planEntries.push(`BMW iX1: ${ix1Battery}% (plugged in)`);
        } else if (ix1Battery >= threshold) {
            planEntries.push(`BMW iX1: ${ix1Battery}% OK`);
        }
    }

    return { alerts, planEntries };
}

/**
 * Calculate final headroom after all decisions
 */
function calculateFinalHeadroom(avail, decisions, config, currentStates) {
    let headroom = avail;

    // Subtract power for devices that will be/are on
    if (decisions.ev.action === 'on' || decisions.ev.action === 'adjust') {
        headroom -= decisions.ev.amps * (config.ev?.wattsPerAmp || 692);
    }
    if (decisions.boiler.action === 'on' || currentStates.boilerOn) {
        headroom -= config.boiler?.power || 2500;
    }
    // ... etc

    return headroom;
}

module.exports = {
    calculateDecisions,
    checkFrostProtection,
    checkBmwLowBattery,
    EV_STATES
};
