#!/usr/bin/env node
/**
 * Updates the Node-RED flow with BMW low battery warning support
 */

const fs = require('fs');
const path = require('path');

const flowPath = path.join(__dirname, '../node-red/flows.json');
const flow = JSON.parse(fs.readFileSync(flowPath, 'utf8'));

// Find and update CONFIG node
const configNode = flow.find(n => n.id === 'config_node');
if (configNode) {
    // Add BMW low battery config
    const oldHeatersConfig = `// === HEATERS ===
    heaters: {
        right: { power: 2500 },
        table: { power: 4100 }
    },`;

    const newHeatersConfig = `// === BMW CARS LOW BATTERY WARNING ===
    bmwLowBattery: {
        enabled: true,
        batteryThreshold: 50,       // Warn if below this % at check time
        checkHours: [20, 21, 22],   // Hours to check (20:00, 21:00, 22:00)
        notifyEntity: 'mobile_app_iphone_van_nicolas_2'
    },

    // === HEATERS ===
    heaters: {
        right: { power: 2500 },
        table: { power: 4100 }
    },`;

    configNode.func = configNode.func.replace(oldHeatersConfig, newHeatersConfig);

    // Add BMW entities
    const oldStatusEntities = `status: {
            status: 'input_text.power_manager_status',
            plan: 'input_text.power_manager_plan',
            actions: 'input_text.power_manager_actions'
        }
    },`;

    const newStatusEntities = `status: {
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
    },`;

    configNode.func = configNode.func.replace(oldStatusEntities, newStatusEntities);

    // Update version
    configNode.func = configNode.func.replace("Config v6.1 (Frost)", "Config v6.2 (BMW)");
    console.log('✓ Updated CONFIG node with BMW config');
}

// Find the last EV sensor node to insert BMW sensors after
const evLimitNode = flow.find(n => n.id === 'get_ev_limit');

// Add new sensor nodes for BMW cars
const newNodes = [
    {
        id: "get_bmw_i5_battery",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "i5 Bat",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "sensor.i5_edrive40_battery_hv_state_of_charge",
        state_type: "num",
        blockInputOverrides: false,
        outputProperties: [{property: "bmw_i5_battery", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 90,
        y: 460,
        wires: [["get_bmw_i5_range"]]
    },
    {
        id: "get_bmw_i5_range",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "i5 Range",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "sensor.i5_edrive40_range_ev_remaining_range",
        state_type: "num",
        blockInputOverrides: false,
        outputProperties: [{property: "bmw_i5_range", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 190,
        y: 460,
        wires: [["get_bmw_i5_location"]]
    },
    {
        id: "get_bmw_i5_location",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "i5 Loc",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "device_tracker.i5_edrive40_location",
        state_type: "str",
        blockInputOverrides: false,
        outputProperties: [{property: "bmw_i5_location", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 290,
        y: 460,
        wires: [["get_bmw_ix1_battery"]]
    },
    {
        id: "get_bmw_ix1_battery",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "iX1 Bat",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "sensor.ix1_edrive20_battery_hv_state_of_charge",
        state_type: "num",
        blockInputOverrides: false,
        outputProperties: [{property: "bmw_ix1_battery", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 390,
        y: 460,
        wires: [["get_bmw_ix1_range"]]
    },
    {
        id: "get_bmw_ix1_range",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "iX1 Range",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "sensor.ix1_edrive20_range_ev_remaining_range",
        state_type: "num",
        blockInputOverrides: false,
        outputProperties: [{property: "bmw_ix1_range", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 490,
        y: 460,
        wires: [["get_bmw_ix1_location"]]
    },
    {
        id: "get_bmw_ix1_location",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "iX1 Loc",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "device_tracker.ix1_edrive20_location",
        state_type: "str",
        blockInputOverrides: false,
        outputProperties: [{property: "bmw_ix1_location", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 590,
        y: 460,
        wires: [["get_heater_right"]]
    }
];

// Check if BMW nodes already exist
const existingBmwBattery = flow.find(n => n.id === 'get_bmw_i5_battery');
if (!existingBmwBattery) {
    // Update EV limit to wire to BMW i5 battery instead of heater
    if (evLimitNode) {
        evLimitNode.wires = [["get_bmw_i5_battery"]];
        console.log('✓ Rewired EV limit node to BMW sensors');
    }

    // Insert new nodes
    const evLimitIdx = flow.findIndex(n => n.id === 'get_ev_limit');
    if (evLimitIdx >= 0) {
        flow.splice(evLimitIdx + 1, 0, ...newNodes);
        console.log('✓ Added BMW sensor nodes');
    }
}

// Find and update the Power Manager main logic to include BMW check
const pmNode = flow.find(n => n.id === 'power_manager');
if (pmNode && !pmNode.func.includes('checkBmwLowBattery')) {
    // Add BMW low battery check function
    const bmwCheckCode = `
// === BMW LOW BATTERY CHECK ===
function checkBmwLowBattery() {
    const alerts = [];
    const planEntries = [];
    const bmwConfig = config.bmwLowBattery;

    if (!bmwConfig?.enabled) return { alerts, planEntries };

    const currentHour = d.getHours();
    const checkHours = bmwConfig.checkHours || [20, 21, 22];

    if (!checkHours.includes(currentHour)) return { alerts, planEntries };

    const threshold = bmwConfig.batteryThreshold || 50;
    const evPluggedIn = evState === EV_STATES.READY || evState === EV_STATES.CHARGING;

    // Check i5
    const i5Battery = v.bmwI5Battery;
    const i5Range = v.bmwI5Range;
    const i5Location = v.bmwI5Location;

    if (i5Battery !== null && i5Battery < threshold && i5Location === 'home' && !evPluggedIn) {
        const msg = \`BMW i5 at \${i5Battery}%, \${i5Range || '?'}km range - not plugged in!\`;
        alerts.push({ level: 'warning', message: msg, entity: bmwConfig.notifyEntity });
        planEntries.push(\`BMW i5: LOW \${i5Battery}% (\${i5Range}km) - not charging\`);
    } else if (i5Battery !== null && i5Location === 'home') {
        if (evPluggedIn) {
            planEntries.push(\`BMW i5: \${i5Battery}% (plugged in)\`);
        } else if (i5Battery >= threshold) {
            planEntries.push(\`BMW i5: \${i5Battery}% OK\`);
        }
    }

    // Check iX1
    const ix1Battery = v.bmwIx1Battery;
    const ix1Range = v.bmwIx1Range;
    const ix1Location = v.bmwIx1Location;

    if (ix1Battery !== null && ix1Battery < threshold && ix1Location === 'home' && !evPluggedIn) {
        const msg = \`BMW iX1 at \${ix1Battery}%, \${ix1Range || '?'}km range - not plugged in!\`;
        alerts.push({ level: 'warning', message: msg, entity: bmwConfig.notifyEntity });
        planEntries.push(\`BMW iX1: LOW \${ix1Battery}% (\${ix1Range}km) - not charging\`);
    } else if (ix1Battery !== null && ix1Location === 'home') {
        if (evPluggedIn) {
            planEntries.push(\`BMW iX1: \${ix1Battery}% (plugged in)\`);
        } else if (ix1Battery >= threshold) {
            planEntries.push(\`BMW iX1: \${ix1Battery}% OK\`);
        }
    }

    return { alerts, planEntries };
}

const bmwResult = checkBmwLowBattery();
plan.push(...bmwResult.planEntries);

// Send BMW alerts
if (bmwResult.alerts?.length > 0) {
    for (const alert of bmwResult.alerts) {
        outputs[11] = { payload: { title: 'Power Manager - BMW Alert', message: alert.message } };
    }
}

`;

    // Insert BMW check after frost check
    const insertPoint = `// Send frost alerts
if (frostResult.alerts?.length > 0) {
    for (const alert of frostResult.alerts) {
        const alertMsg = { payload: { title: 'Power Manager - Frost Alert', message: alert.message } };
        outputs[11] = alertMsg;
    }
}

outputs[9]`;

    const newInsertPoint = `// Send frost alerts
if (frostResult.alerts?.length > 0) {
    for (const alert of frostResult.alerts) {
        const alertMsg = { payload: { title: 'Power Manager - Frost Alert', message: alert.message } };
        outputs[11] = alertMsg;
    }
}
${bmwCheckCode}
outputs[9]`;

    pmNode.func = pmNode.func.replace(insertPoint, newInsertPoint);
    console.log('✓ Added BMW low battery check to Power Manager logic');
}

// Write updated flow
fs.writeFileSync(flowPath, JSON.stringify(flow, null, 4));
console.log('\n✓ Flow updated with BMW sensors and low battery warning!');
console.log('  Import the updated flows.json into Node-RED');
