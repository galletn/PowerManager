/**
 * Mock Home Assistant Adapter
 *
 * Simulates Home Assistant state reading and service calls for testing.
 * Captures all service calls for assertion.
 *
 * @module mock-adapter
 */

'use strict';

/**
 * @typedef {Object} ServiceCall
 * @property {string} domain - Service domain (e.g., 'switch', 'climate')
 * @property {string} service - Service name (e.g., 'turn_on', 'set_hvac_mode')
 * @property {Object} data - Service call data
 * @property {number} timestamp - When the call was made
 */

/**
 * @typedef {Object} StateChange
 * @property {string} entityId - Entity that changed
 * @property {*} oldState - Previous state
 * @property {*} newState - New state
 * @property {number} timestamp - When the change occurred
 */

/**
 * Mock Home Assistant adapter for testing
 */
class MockHAAdapter {
    /**
     * Create a new mock adapter
     *
     * @param {Object} [initialStates] - Initial entity states
     */
    constructor(initialStates = {}) {
        this.states = { ...initialStates };
        this.attributes = {};
        this.commands = [];
        this.stateHistory = [];
        this.time = Date.now();
    }

    /**
     * Set the current simulated time
     *
     * @param {number|Date} time - Timestamp or Date object
     */
    setTime(time) {
        this.time = time instanceof Date ? time.getTime() : time;
    }

    /**
     * Advance simulated time
     *
     * @param {number} ms - Milliseconds to advance
     */
    advanceTime(ms) {
        this.time += ms;
    }

    /**
     * Get current simulated time
     *
     * @returns {number} Current timestamp
     */
    now() {
        return this.time;
    }

    /**
     * Set entity state
     *
     * @param {string} entityId - Entity ID
     * @param {*} state - State value
     * @param {Object} [attributes] - Entity attributes
     */
    setState(entityId, state, attributes = {}) {
        const oldState = this.states[entityId];
        this.states[entityId] = state;
        this.attributes[entityId] = { ...this.attributes[entityId], ...attributes };

        if (oldState !== state) {
            this.stateHistory.push({
                entityId,
                oldState,
                newState: state,
                timestamp: this.time
            });
        }
    }

    /**
     * Set multiple entity states at once
     *
     * @param {Object} states - Map of entityId to state
     */
    setStates(states) {
        for (const [entityId, state] of Object.entries(states)) {
            this.setState(entityId, state);
        }
    }

    /**
     * Get entity state
     *
     * @param {string} entityId - Entity ID
     * @returns {*} State value or 'unavailable'
     */
    getState(entityId) {
        return this.states[entityId] ?? 'unavailable';
    }

    /**
     * Get entity attributes
     *
     * @param {string} entityId - Entity ID
     * @returns {Object} Entity attributes
     */
    getAttributes(entityId) {
        return this.attributes[entityId] || {};
    }

    /**
     * Get all states as a map
     *
     * @returns {Object} All entity states
     */
    getAllStates() {
        return { ...this.states };
    }

    /**
     * Call a Home Assistant service
     *
     * Records the call for later assertion.
     *
     * @param {string} domain - Service domain
     * @param {string} service - Service name
     * @param {Object} data - Service data
     */
    callService(domain, service, data) {
        const call = {
            domain,
            service,
            data: { ...data },
            timestamp: this.time
        };
        this.commands.push(call);

        // Simulate state changes based on service calls
        this._simulateServiceEffect(domain, service, data);
    }

    /**
     * Simulate the effect of a service call on entity states
     *
     * @private
     */
    _simulateServiceEffect(domain, service, data) {
        const entityId = data.entity_id;
        if (!entityId) return;

        if (domain === 'switch') {
            if (service === 'turn_on') {
                this.setState(entityId, 'on');
            } else if (service === 'turn_off') {
                this.setState(entityId, 'off');
            }
        } else if (domain === 'climate') {
            if (service === 'set_hvac_mode') {
                this.setState(entityId, data.hvac_mode);
            } else if (service === 'set_fan_mode') {
                this.attributes[entityId] = {
                    ...this.attributes[entityId],
                    fan_mode: data.fan_mode
                };
            }
        } else if (domain === 'number') {
            if (service === 'set_value') {
                this.setState(entityId, data.value);
            }
        } else if (domain === 'input_text') {
            if (service === 'set_value') {
                this.setState(entityId, data.value);
            }
        }
    }

    /**
     * Get all recorded service calls
     *
     * @returns {ServiceCall[]} All service calls
     */
    getCommands() {
        return [...this.commands];
    }

    /**
     * Get service calls filtered by domain
     *
     * @param {string} domain - Domain to filter by
     * @returns {ServiceCall[]} Matching service calls
     */
    getCommandsByDomain(domain) {
        return this.commands.filter(c => c.domain === domain);
    }

    /**
     * Get service calls for a specific entity
     *
     * @param {string} entityId - Entity ID to filter by
     * @returns {ServiceCall[]} Matching service calls
     */
    getCommandsForEntity(entityId) {
        return this.commands.filter(c => c.data.entity_id === entityId);
    }

    /**
     * Get the last service call
     *
     * @returns {ServiceCall|undefined} Last service call or undefined
     */
    getLastCommand() {
        return this.commands[this.commands.length - 1];
    }

    /**
     * Get state change history
     *
     * @returns {StateChange[]} All state changes
     */
    getStateHistory() {
        return [...this.stateHistory];
    }

    /**
     * Check if a specific service was called
     *
     * @param {string} domain - Service domain
     * @param {string} service - Service name
     * @param {Object} [dataMatch] - Optional data to match
     * @returns {boolean} True if matching call was made
     */
    wasServiceCalled(domain, service, dataMatch = {}) {
        return this.commands.some(c => {
            if (c.domain !== domain || c.service !== service) return false;
            for (const [key, value] of Object.entries(dataMatch)) {
                if (c.data[key] !== value) return false;
            }
            return true;
        });
    }

    /**
     * Reset all state and recorded calls
     */
    reset() {
        this.states = {};
        this.attributes = {};
        this.commands = [];
        this.stateHistory = [];
        this.time = Date.now();
    }

    /**
     * Reset only recorded calls (keep states)
     */
    resetCommands() {
        this.commands = [];
    }

    /**
     * Create a snapshot of current state for comparison
     *
     * @returns {Object} State snapshot
     */
    snapshot() {
        return {
            states: { ...this.states },
            commands: this.commands.length,
            time: this.time
        };
    }
}

/**
 * Create a pre-configured mock adapter with typical Power Manager entities
 *
 * @param {Object} [overrides] - State overrides
 * @returns {MockHAAdapter} Configured mock adapter
 */
function createDefaultMock(overrides = {}) {
    const defaults = {
        // Power sensors
        'sensor.electricity_meter_power_consumption': 0.5,
        'sensor.solaredge_i1_ac_power': 0,

        // Switches
        'switch.storage_boiler': 'off',
        'switch.abb_terra_ac_charging': 'off',
        'switch.livingroom_right_heater': 'off',
        'switch.livingroom_table_heater_state': 'off',

        // Power sensors
        'sensor.storage_boiler_power': 0,
        'sensor.abb_terra_ac_active_power': 0,
        'sensor.pool_heating_current_consumption': 0,
        'sensor.living_current_power': 0,
        'sensor.bureau_current_power': 0,

        // EV
        'sensor.abb_terra_ac_charging_state': 128, // No car
        'number.abb_terra_ac_current_limit': 6,

        // Climate
        'climate.98d8639f920c': 'off',
        'climate.living': 'off',
        'climate.mancave': 'off',
        'climate.bureau': 'off',
        'climate.slaapkamer': 'off',

        // Booleans
        'input_boolean.force_heat_boiler': 'off',
        'input_boolean.pool_season': 'off',

        // Temperatures
        'sensor.livingroom_temperature_temperature': 20,
        'sensor.bedroom_temperature_temperature': 20,
        'sensor.mancave_inside_temperature': 18,

        // Overrides
        'input_select.pm_override_ac_living': 'Auto',
        'input_select.pm_override_ac_slaapkamer': 'Auto',
        'input_select.pm_override_ac_bureau': 'Auto',
        'input_select.pm_override_ac_mancave': 'Auto',
        'input_select.pm_override_pool': 'Auto',
        'input_select.pm_override_boiler': 'Auto',
        'input_select.pm_override_ev': 'Auto',

        // Status
        'input_text.power_manager_status': '',
        'input_text.power_manager_plan': '',
        'input_text.power_manager_actions': ''
    };

    return new MockHAAdapter({ ...defaults, ...overrides });
}

/**
 * Convert mock adapter states to flow message format
 *
 * @param {MockHAAdapter} adapter - Mock adapter
 * @returns {Object} Message with all state properties
 */
function statesToMessage(adapter) {
    return {
        p1_power: adapter.getState('sensor.electricity_meter_power_consumption'),
        pv_power: adapter.getState('sensor.solaredge_i1_ac_power'),
        boiler_switch: adapter.getState('switch.storage_boiler'),
        boiler_power: adapter.getState('sensor.storage_boiler_power'),
        boiler_force: adapter.getState('input_boolean.force_heat_boiler'),
        pool_season: adapter.getState('input_boolean.pool_season'),
        pool_power: adapter.getState('sensor.pool_heating_current_consumption'),
        pool_climate: adapter.getState('climate.98d8639f920c'),
        ev_state: adapter.getState('sensor.abb_terra_ac_charging_state'),
        ev_switch: adapter.getState('switch.abb_terra_ac_charging'),
        ev_power: adapter.getState('sensor.abb_terra_ac_active_power'),
        ev_limit: adapter.getState('number.abb_terra_ac_current_limit'),
        heater_right_switch: adapter.getState('switch.livingroom_right_heater'),
        heater_table_switch: adapter.getState('switch.livingroom_table_heater_state'),
        ac_living_state: adapter.getState('climate.living'),
        ac_mancave_state: adapter.getState('climate.mancave'),
        ac_office_state: adapter.getState('climate.bureau'),
        ac_bedroom_state: adapter.getState('climate.slaapkamer'),
        ac_living_power: adapter.getState('sensor.living_current_power'),
        ac_office_power: adapter.getState('sensor.bureau_current_power'),
        temp_living: adapter.getState('sensor.livingroom_temperature_temperature'),
        temp_bedroom: adapter.getState('sensor.bedroom_temperature_temperature'),
        temp_mancave: adapter.getState('sensor.mancave_inside_temperature'),
        ovr_ac_living: adapter.getState('input_select.pm_override_ac_living'),
        ovr_ac_bedroom: adapter.getState('input_select.pm_override_ac_slaapkamer'),
        ovr_ac_office: adapter.getState('input_select.pm_override_ac_bureau'),
        ovr_ac_mancave: adapter.getState('input_select.pm_override_ac_mancave'),
        ovr_pool: adapter.getState('input_select.pm_override_pool'),
        ovr_boiler: adapter.getState('input_select.pm_override_boiler'),
        ovr_ev: adapter.getState('input_select.pm_override_ev')
    };
}

module.exports = {
    MockHAAdapter,
    createDefaultMock,
    statesToMessage
};
