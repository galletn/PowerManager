/**
 * Timing and state management module
 *
 * Handles device switch timing, hysteresis, and state tracking
 * to prevent rapid on/off cycling (flapping).
 *
 * @module timing
 */

'use strict';

/**
 * @typedef {Object} DeviceState
 * @property {boolean} on - Whether device is currently on
 * @property {number} lastChange - Timestamp of last state change (ms)
 * @property {number} [amps] - Current amp setting (for EV)
 */

/**
 * @typedef {Object} TimingConfig
 * @property {number} minOnTime - Minimum on-time before turning off (seconds)
 * @property {number} minOffTime - Minimum off-time before turning on (seconds)
 * @property {number} hysteresis - Power buffer before switching (watts)
 * @property {number} [evAmpChangeThreshold] - Minimum amp change for EV (amps)
 */

const DEFAULT_TIMING = {
    minOnTime: 300,      // 5 minutes
    minOffTime: 180,     // 3 minutes
    hysteresis: 300,     // 300W buffer
    evAmpChangeThreshold: 2
};

/**
 * Check if a device can be switched to a new state
 *
 * Enforces minimum on/off times to prevent rapid cycling.
 *
 * @param {DeviceState} deviceState - Current device state
 * @param {boolean} targetState - Desired state (true = on)
 * @param {number} now - Current timestamp (ms)
 * @param {TimingConfig} [config] - Timing configuration
 * @returns {boolean} True if switch is allowed
 *
 * @example
 * // Device was turned on 2 minutes ago, cannot turn off yet
 * canSwitch({ on: true, lastChange: Date.now() - 120000 }, false, Date.now())
 * // => false (120s < 300s minOnTime)
 *
 * @example
 * // Device was turned off 5 minutes ago, can turn on
 * canSwitch({ on: false, lastChange: Date.now() - 300000 }, true, Date.now())
 * // => true (300s >= 180s minOffTime)
 */
function canSwitch(deviceState, targetState, now, config = {}) {
    if (!deviceState || !deviceState.lastChange) {
        return true; // No state history, allow switch
    }

    const elapsed = (now - deviceState.lastChange) / 1000; // Convert to seconds

    if (targetState) {
        // Turning on: check minOffTime
        const minTime = config.minOffTime ?? DEFAULT_TIMING.minOffTime;
        return elapsed >= minTime;
    } else {
        // Turning off: check minOnTime
        const minTime = config.minOnTime ?? DEFAULT_TIMING.minOnTime;
        return elapsed >= minTime;
    }
}

/**
 * Check if EV amp adjustment is significant enough
 *
 * Prevents small amp changes that cause flapping.
 *
 * @param {number} currentAmps - Current amp setting
 * @param {number} targetAmps - Desired amp setting
 * @param {number} [threshold] - Minimum change threshold
 * @returns {boolean} True if change is significant
 *
 * @example
 * shouldAdjustEvAmps(10, 12, 2)  // => true (diff = 2 >= threshold)
 * shouldAdjustEvAmps(10, 11, 2)  // => false (diff = 1 < threshold)
 */
function shouldAdjustEvAmps(currentAmps, targetAmps, threshold = DEFAULT_TIMING.evAmpChangeThreshold) {
    return Math.abs(targetAmps - currentAmps) >= threshold;
}

/**
 * Create a new device state object
 *
 * @param {boolean} on - Initial on/off state
 * @param {number} [now] - Timestamp for lastChange
 * @returns {DeviceState} New device state
 */
function createDeviceState(on = false, now = Date.now()) {
    return {
        on,
        lastChange: on ? now : 0
    };
}

/**
 * Update device state after a switch
 *
 * @param {DeviceState} state - Current state
 * @param {boolean} on - New on/off state
 * @param {number} now - Current timestamp
 * @param {Object} [extra] - Additional properties (e.g., amps)
 * @returns {DeviceState} Updated state (new object)
 */
function updateDeviceState(state, on, now, extra = {}) {
    return {
        ...state,
        on,
        lastChange: state.on !== on ? now : state.lastChange,
        ...extra
    };
}

/**
 * Initialize all device states
 *
 * @returns {Object} Initial device state map
 */
function createInitialDeviceStates() {
    return {
        ev: { on: false, lastChange: 0, amps: 0 },
        boiler: { on: false, lastChange: 0 },
        pool: { on: false, lastChange: 0 },
        poolPump: { on: false, lastChange: 0 },
        heaterRight: { on: false, lastChange: 0 },
        heaterTable: { on: false, lastChange: 0 },
        acLiving: { on: false, lastChange: 0 },
        acMancave: { on: false, lastChange: 0 },
        acOffice: { on: false, lastChange: 0 },
        acBedroom: { on: false, lastChange: 0 }
    };
}

/**
 * Calculate time remaining before switch is allowed
 *
 * @param {DeviceState} deviceState - Current device state
 * @param {boolean} targetState - Desired state
 * @param {number} now - Current timestamp (ms)
 * @param {TimingConfig} [config] - Timing configuration
 * @returns {number} Seconds remaining (0 if can switch now)
 */
function timeUntilSwitch(deviceState, targetState, now, config = {}) {
    if (!deviceState || !deviceState.lastChange) {
        return 0;
    }

    const elapsed = (now - deviceState.lastChange) / 1000;
    const minTime = targetState
        ? (config.minOffTime ?? DEFAULT_TIMING.minOffTime)
        : (config.minOnTime ?? DEFAULT_TIMING.minOnTime);

    return Math.max(0, minTime - elapsed);
}

/**
 * Check if power threshold is met with hysteresis
 *
 * @param {number} available - Available power (W)
 * @param {number} required - Required power (W)
 * @param {number} [hysteresis] - Hysteresis buffer (W)
 * @returns {boolean} True if power is sufficient
 */
function hasSufficientPower(available, required, hysteresis = DEFAULT_TIMING.hysteresis) {
    return available >= required - hysteresis;
}

/**
 * Check if device should shed load
 *
 * @param {number} headroom - Current headroom (W), negative = overload
 * @param {number} [hysteresis] - Hysteresis buffer (W)
 * @returns {boolean} True if should shed load
 */
function shouldShedLoad(headroom, hysteresis = DEFAULT_TIMING.hysteresis) {
    return headroom < -hysteresis;
}

module.exports = {
    canSwitch,
    shouldAdjustEvAmps,
    createDeviceState,
    updateDeviceState,
    createInitialDeviceStates,
    timeUntilSwitch,
    hasSufficientPower,
    shouldShedLoad,
    DEFAULT_TIMING
};
