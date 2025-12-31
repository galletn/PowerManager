/**
 * Test fixtures loader
 *
 * Provides utilities for loading and using test fixtures.
 *
 * @module fixtures
 */

'use strict';

const path = require('path');
const fs = require('fs');

/**
 * @typedef {Object} Fixture
 * @property {string} name - Fixture name
 * @property {string} description - What this fixture tests
 * @property {string} timestamp - ISO timestamp for the test
 * @property {Object} inputs - Raw input values
 * @property {Object} expectedDecisions - Expected device decisions
 * @property {string[]} expectedPlanContains - Strings that should appear in plan
 * @property {Object[]} [invariants] - Conditions that must hold
 */

const fixturesDir = __dirname;

/**
 * Load a fixture by name
 *
 * @param {string} name - Fixture filename (without .json)
 * @returns {Fixture} Loaded fixture
 */
function loadFixture(name) {
    const filePath = path.join(fixturesDir, `${name}.json`);
    const content = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(content);
}

/**
 * Load all fixtures from the directory
 *
 * @returns {Fixture[]} Array of all fixtures
 */
function loadAllFixtures() {
    const files = fs.readdirSync(fixturesDir)
        .filter(f => f.endsWith('.json'));

    return files.map(f => {
        const content = fs.readFileSync(path.join(fixturesDir, f), 'utf8');
        return JSON.parse(content);
    });
}

/**
 * Get timestamp as Date from fixture
 *
 * @param {Fixture} fixture - The fixture
 * @returns {Date} Parsed date
 */
function getFixtureDate(fixture) {
    return new Date(fixture.timestamp);
}

/**
 * Get timestamp as milliseconds from fixture
 *
 * @param {Fixture} fixture - The fixture
 * @returns {number} Timestamp in ms
 */
function getFixtureTime(fixture) {
    return new Date(fixture.timestamp).getTime();
}

/**
 * Create a test case from a fixture
 *
 * @param {Fixture} fixture - The fixture
 * @param {Function} testFn - Test function to wrap
 * @returns {Function} Test case function
 */
function createTestCase(fixture, testFn) {
    return () => testFn(fixture);
}

/**
 * Validate fixture structure
 *
 * @param {Fixture} fixture - Fixture to validate
 * @returns {{ valid: boolean, errors: string[] }}
 */
function validateFixture(fixture) {
    const errors = [];

    if (!fixture.name) errors.push('Missing name');
    if (!fixture.timestamp) errors.push('Missing timestamp');
    if (!fixture.inputs) errors.push('Missing inputs');

    // Validate timestamp format
    if (fixture.timestamp) {
        const date = new Date(fixture.timestamp);
        if (isNaN(date.getTime())) {
            errors.push('Invalid timestamp format');
        }
    }

    return {
        valid: errors.length === 0,
        errors
    };
}

// Pre-load common fixtures
const fixtures = {
    winterOffpeakEv: loadFixture('winter-offpeak-ev'),
    summerExportCool: loadFixture('summer-export-cool'),
    sensorUnavailable: loadFixture('sensor-unavailable')
};

module.exports = {
    loadFixture,
    loadAllFixtures,
    getFixtureDate,
    getFixtureTime,
    createTestCase,
    validateFixture,
    fixtures,
    fixturesDir
};
