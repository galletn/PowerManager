/**
 * Jest test setup
 *
 * This file is loaded before each test file.
 */

'use strict';

// Increase timeout for flow tests
jest.setTimeout(10000);

// Mock console.warn to capture warnings
global.capturedWarnings = [];
const originalWarn = console.warn;
console.warn = (...args) => {
    global.capturedWarnings.push(args.join(' '));
    originalWarn.apply(console, args);
};

// Reset captured warnings before each test
beforeEach(() => {
    global.capturedWarnings = [];
});

// Helper to create a fixed timestamp for testing
global.createTestTime = (isoString) => {
    return new Date(isoString).getTime();
};

// Common test timestamps
global.testTimes = {
    winterNight: createTestTime('2024-01-15T02:30:00Z'),     // Super off-peak
    winterMorningPeak: createTestTime('2024-01-15T08:30:00Z'), // Peak
    winterMidday: createTestTime('2024-01-15T13:00:00Z'),    // Off-peak
    winterEveningPeak: createTestTime('2024-01-15T18:30:00Z'), // Peak
    winterNight2: createTestTime('2024-01-15T23:30:00Z'),    // Off-peak

    summerMidday: createTestTime('2024-07-15T13:00:00Z'),    // Off-peak
    summerAfternoon: createTestTime('2024-07-15T15:00:00Z'), // Off-peak

    weekendMorning: createTestTime('2024-01-14T10:00:00Z'),  // Sunday off-peak
    weekendMidday: createTestTime('2024-01-14T14:00:00Z')    // Sunday super off-peak
};
