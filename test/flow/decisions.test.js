/**
 * Decision engine integration tests
 *
 * Tests the full decision flow using fixtures.
 */

'use strict';

const { fixtures, loadAllFixtures } = require('../fixtures');
const { runDecisionEngine, expectDecision, expectPlanContains } = require('./helpers');
const { defaultConfig } = require('../../src/config/default-config');

describe('Decision Engine', () => {
    describe('Winter scenarios', () => {
        test('winter off-peak EV charging starts', () => {
            const fixture = fixtures.winterOffpeakEv;
            const result = runDecisionEngine(fixture);

            // EV should start charging
            expect(result.decisions.ev.action).toBe('on');
            // Amps depends on available headroom (p1=0.5kW, limit=8kW, so ~10A)
            expect(result.decisions.ev.amps).toBeGreaterThanOrEqual(6);
            expect(result.decisions.ev.amps).toBeLessThanOrEqual(16);

            // Boiler should start (super off-peak, not full)
            expect(result.decisions.boiler.action).toBe('on');

            // Plan should mention super off-peak
            expectPlanContains(result, ['SUPER OFF PEAK']);
        });

        test('winter peak tariff blocks heaters', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-15T08:30:00Z', // Peak hour
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    ev_state: 128 // No car
                }
            };

            const result = runDecisionEngine(fixture);

            // Heaters should wait for off-peak
            expect(result.decisions.heaterTable.action).toBe('none');
            expect(result.decisions.heaterRight.action).toBe('none');

            // Plan should show waiting message
            expectPlanContains(result, ['Waiting for off-peak']);
        });

        test('winter boiler deadline triggers urgent', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-15T05:00:00Z', // Before 06:30 deadline
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    boiler_switch: 'off',
                    boiler_power: 100, // Not full (>50W threshold)
                    ev_state: 128 // No car
                }
            };

            const result = runDecisionEngine(fixture);

            // Boiler should turn on urgently
            expect(result.decisions.boiler.action).toBe('on');
            expectPlanContains(result, ['URGENT']);
        });
    });

    describe('Summer scenarios', () => {
        test('summer export starts cooling', () => {
            const fixture = fixtures.summerExportCool;
            const result = runDecisionEngine(fixture);

            // Pool should start heating
            expect(result.decisions.pool.action).toBe('heat');

            // AC living should cool (temp > 25C, exporting)
            expect(result.decisions.acLiving.action).toBe('cool');

            // Plan should show export indicator
            expectPlanContains(result, ['(exp)', 'Summer']);
        });

        test('summer not exporting stops cooling', () => {
            const fixture = {
                ...fixtures.summerExportCool,
                inputs: {
                    ...fixtures.summerExportCool.inputs,
                    p1_power: 1.5, // Importing, not exporting
                    ac_living_state: 'cool' // Currently cooling
                }
            };

            const result = runDecisionEngine(fixture);

            // AC should turn off (not exporting)
            expect(result.decisions.acLiving.action).toBe('off');
            expectPlanContains(result, ['Waiting for export']);
        });

        test('summer pool gets priority', () => {
            const fixture = {
                ...fixtures.summerExportCool,
                inputs: {
                    ...fixtures.summerExportCool.inputs,
                    pool_power: 50 // Not heating yet
                }
            };

            const result = runDecisionEngine(fixture);

            // Pool should start before other devices
            expect(result.decisions.pool.action).toBe('heat');
        });
    });

    describe('Override scenarios', () => {
        test('manual override forces AC cooling', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    ovr_ac_living: 'Cool',
                    ac_living_state: 'off'
                }
            };

            const result = runDecisionEngine(fixture);

            // AC should cool despite winter
            expect(result.decisions.acLiving.action).toBe('cool');
            expectPlanContains(result, ['MANUAL COOL']);
        });

        test('manual override forces EV off', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    ovr_ev: 'Off',
                    ev_state: 132, // Charging
                    ev_switch: 'on'
                }
            };

            const result = runDecisionEngine(fixture);

            // EV should turn off
            expect(result.decisions.ev.action).toBe('off');
            expectPlanContains(result, ['MANUAL OFF']);
        });

        test('force boiler ignores tariff', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-15T10:00:00Z', // Peak
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    boiler_force: 'on',
                    boiler_power: 100 // Not full
                }
            };

            const result = runDecisionEngine(fixture);

            // Boiler should turn on despite peak
            expect(result.decisions.boiler.action).toBe('on');
            expectPlanContains(result, ['FORCE ON']);
        });
    });

    describe('Sensor unavailable scenarios', () => {
        test('handles unavailable P1 sensor', () => {
            const fixture = fixtures.sensorUnavailable;
            const result = runDecisionEngine(fixture);

            // Should still produce decisions without crashing
            expect(result.decisions).toBeDefined();
            expect(result.plan).toBeDefined();
            expect(result.plan.length).toBeGreaterThan(0);
        });

        test('defaults to safe values', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                inputs: {
                    p1_power: 'unavailable',
                    pv_power: 'unknown',
                    ev_state: 'unavailable',
                    pool_season: 'off'
                }
            };

            const result = runDecisionEngine(fixture);

            // Should not crash, should use defaults
            expect(result.meta.p1).toBe(0); // Defaults to 0
            expect(result.decisions).toBeDefined();
        });
    });

    describe('EV state scenarios', () => {
        test('EV no car means skip EV decisions', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    ev_state: 128 // No car
                }
            };

            const result = runDecisionEngine(fixture);

            // EV should have no action
            expect(result.decisions.ev.action).toBe('none');
        });

        test('EV full means skip charging', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    ev_state: 130 // Full
                }
            };

            const result = runDecisionEngine(fixture);

            expect(result.decisions.ev.action).toBe('none');
            expectPlanContains(result, ['EV: Full']);
        });

        test('EV ready in peak waits', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-15T09:00:00Z', // Peak
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    ev_state: 129 // Ready
                }
            };

            const result = runDecisionEngine(fixture);

            expect(result.decisions.ev.action).toBe('none');
            expectPlanContains(result, ['Waiting for off-peak']);
        });
    });

    describe('Power budget scenarios', () => {
        test('limited headroom limits EV amps', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    p1_power: 4.0 // 4kW import, leaves ~4kW for EV at super off-peak
                }
            };

            const result = runDecisionEngine(fixture);

            // EV should start with limited amps
            if (result.decisions.ev.action === 'on') {
                expect(result.decisions.ev.amps).toBeLessThan(16);
            }
        });

        test('overload triggers load shedding', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-15T09:00:00Z', // Peak (2.5kW limit)
                inputs: {
                    ...fixtures.winterOffpeakEv.inputs,
                    p1_power: 3.5, // Significantly over limit (3.5kW vs 2.5kW max)
                    ac_living_state: 'heat' // Currently on
                }
            };

            const result = runDecisionEngine(fixture);

            // AC should be shed due to overload
            expect(result.decisions.acLiving.action).toBe('off');
            expectPlanContains(result, ['Load shed']);
        });
    });

    describe('Tariff detection', () => {
        test('correctly identifies peak tariff', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-15T09:00:00Z' // Peak
            };

            const result = runDecisionEngine(fixture);
            expect(result.meta.tariff).toBe('peak');
        });

        test('correctly identifies off-peak tariff', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-15T12:00:00Z' // Off-peak
            };

            const result = runDecisionEngine(fixture);
            expect(result.meta.tariff).toBe('off-peak');
        });

        test('correctly identifies super off-peak tariff', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-15T03:00:00Z' // Super off-peak
            };

            const result = runDecisionEngine(fixture);
            expect(result.meta.tariff).toBe('super-off-peak');
        });

        test('weekend has different tariffs', () => {
            const fixture = {
                ...fixtures.winterOffpeakEv,
                timestamp: '2024-01-14T09:00:00Z' // Sunday 09:00
            };

            const result = runDecisionEngine(fixture);
            // Sunday morning is off-peak, not peak
            expect(result.meta.tariff).toBe('off-peak');
        });
    });
});

describe('All fixtures validation', () => {
    const allFixtures = loadAllFixtures();

    test.each(allFixtures.map(f => [f.name, f]))(
        'fixture %s runs without errors',
        (name, fixture) => {
            expect(() => runDecisionEngine(fixture)).not.toThrow();
        }
    );

    test.each(allFixtures.map(f => [f.name, f]))(
        'fixture %s produces valid output',
        (name, fixture) => {
            const result = runDecisionEngine(fixture);

            expect(result.decisions).toBeDefined();
            expect(result.plan).toBeDefined();
            expect(Array.isArray(result.plan)).toBe(true);
            expect(result.headroom).toBeDefined();
            expect(typeof result.headroom).toBe('number');
        }
    );
});
