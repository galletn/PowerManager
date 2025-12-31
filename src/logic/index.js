/**
 * Power Manager Logic Module
 *
 * Re-exports all logic modules for convenient importing.
 *
 * @module logic
 */

'use strict';

const tariff = require('./tariff');
const validation = require('./validation');
const formatting = require('./formatting');
const timing = require('./timing');
const decisions = require('./decisions');

module.exports = {
    // Tariff functions
    getTariffInfo: tariff.getTariffInfo,
    getNextNonPeak: tariff.getNextNonPeak,
    isPeakTariff: tariff.isPeakTariff,
    isSuperOffPeak: tariff.isSuperOffPeak,
    formatTariffName: tariff.formatTariffName,

    // Validation functions
    safeNum: validation.safeNum,
    safeStr: validation.safeStr,
    parseOverride: validation.parseOverride,
    validateInputs: validation.validateInputs,
    checkCriticalSensors: validation.checkCriticalSensors,
    getEvStatusText: validation.getEvStatusText,

    // Formatting functions
    fmtW: formatting.fmtW,
    fmtTime: formatting.fmtTime,
    fmtTimestamp: formatting.fmtTimestamp,
    fmtTemp: formatting.fmtTemp,
    buildStatusLine: formatting.buildStatusLine,
    gridIndicator: formatting.gridIndicator,
    joinPlan: formatting.joinPlan,
    formatLogEntry: formatting.formatLogEntry,

    // Timing functions
    canSwitch: timing.canSwitch,
    shouldAdjustEvAmps: timing.shouldAdjustEvAmps,
    createDeviceState: timing.createDeviceState,
    updateDeviceState: timing.updateDeviceState,
    createInitialDeviceStates: timing.createInitialDeviceStates,
    timeUntilSwitch: timing.timeUntilSwitch,
    hasSufficientPower: timing.hasSufficientPower,
    shouldShedLoad: timing.shouldShedLoad,

    // Decision engine
    calculateDecisions: decisions.calculateDecisions,
    EV_STATES: decisions.EV_STATES,

    // Constants
    DEFAULT_TIMING: timing.DEFAULT_TIMING,
    DEFAULT_LIMITS: tariff.DEFAULT_LIMITS
};
