/**
 * Flow test helpers
 *
 * Utilities for testing Node-RED flows with node-red-node-test-helper.
 */

'use strict';

const { validateInputs } = require('../../src/logic/validation');
const { calculateDecisions } = require('../../src/logic/decisions');
const { createInitialDeviceStates } = require('../../src/logic/timing');
const { defaultConfig } = require('../../src/config/default-config');

/**
 * Run the decision engine with fixture inputs
 *
 * This bypasses Node-RED and tests the pure decision logic directly.
 *
 * @param {Object} fixture - Test fixture with inputs and timestamp
 * @param {Object} [config] - Optional custom config
 * @param {Object} [deviceState] - Optional device state
 * @returns {Object} Decision result
 */
function runDecisionEngine(fixture, config = defaultConfig, deviceState = null) {
    const validated = validateInputs(fixture.inputs);
    const states = deviceState || createInitialDeviceStates();
    const timestamp = new Date(fixture.timestamp).getTime();

    return calculateDecisions(validated, config, states, timestamp);
}

/**
 * Assert that a decision matches expected
 *
 * @param {Object} result - Decision result
 * @param {string} device - Device name
 * @param {Object} expected - Expected decision properties
 */
function expectDecision(result, device, expected) {
    const decision = result.decisions[device];
    if (!decision) {
        throw new Error(`No decision found for device: ${device}`);
    }

    for (const [key, value] of Object.entries(expected)) {
        if (decision[key] !== value) {
            throw new Error(
                `Decision mismatch for ${device}.${key}: ` +
                `expected ${value}, got ${decision[key]}`
            );
        }
    }
}

/**
 * Assert that plan contains expected strings
 *
 * @param {Object} result - Decision result
 * @param {string[]} expected - Strings that should appear in plan
 */
function expectPlanContains(result, expected) {
    const planText = result.plan.join(' ');

    for (const str of expected) {
        if (!planText.includes(str)) {
            throw new Error(
                `Plan does not contain "${str}". ` +
                `Plan: ${planText.substring(0, 200)}...`
            );
        }
    }
}

/**
 * Create a mock message with validated inputs
 *
 * @param {Object} rawInputs - Raw input values
 * @returns {Object} Message object with validated property
 */
function createMockMessage(rawInputs) {
    return {
        validated: validateInputs(rawInputs),
        _msgid: 'test-' + Date.now()
    };
}

/**
 * Create test context with flow.get/set simulation
 *
 * @returns {Object} Mock flow context
 */
function createMockFlowContext() {
    const storage = new Map();

    return {
        get: (key) => storage.get(key),
        set: (key, value) => storage.set(key, value),
        keys: () => Array.from(storage.keys()),
        clear: () => storage.clear()
    };
}

/**
 * Create test node context
 *
 * @returns {Object} Mock node context
 */
function createMockNodeContext() {
    const statuses = [];
    const warnings = [];

    return {
        status: (status) => statuses.push(status),
        warn: (msg) => warnings.push(msg),
        getStatuses: () => statuses,
        getWarnings: () => warnings
    };
}

module.exports = {
    runDecisionEngine,
    expectDecision,
    expectPlanContains,
    createMockMessage,
    createMockFlowContext,
    createMockNodeContext
};
