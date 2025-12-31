#!/usr/bin/env node
/**
 * Updates the Node-RED flow with frost protection support
 */

const fs = require('fs');
const path = require('path');

const flowPath = path.join(__dirname, '../node-red/flows.json');
const flow = JSON.parse(fs.readFileSync(flowPath, 'utf8'));

// Find and update CONFIG node
const configNode = flow.find(n => n.id === 'config_node');
if (configNode) {
    // Add frost protection to the config function
    const oldPoolEntities = `pool: {
            climate: 'climate.98d8639f920c',
            power: 'sensor.pool_heating_current_consumption',
            season: 'input_boolean.pool_season'
        }`;

    const newPoolEntities = `pool: {
            climate: 'climate.98d8639f920c',
            power: 'sensor.pool_heating_current_consumption',
            season: 'input_boolean.pool_season',
            pump: 'switch.poolhouse_pool_pump',
            pumpPower: 'sensor.poolhouse_pool_pump_power',
            ambientTemp: 'sensor.98d8639f920c_ambient_temp_t05'
        }`;

    configNode.func = configNode.func.replace(oldPoolEntities, newPoolEntities);

    // Add frost protection config after pool config
    const poolConfig = `// === POOL HEAT PUMP ===
    pool: {
        idlePower: 100,
        activePower: 2000
    },`;

    const frostConfig = `// === POOL HEAT PUMP ===
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
    },`;

    configNode.func = configNode.func.replace(poolConfig, frostConfig);

    // Update version
    configNode.func = configNode.func.replace("Config v6.0", "Config v6.1 (Frost)");
    console.log('✓ Updated CONFIG node');
}

// Find and update Init State node
const initNode = flow.find(n => n.id === 'init_state');
if (initNode) {
    const oldDeviceState = `flow.set('deviceState', {
    ev: { on: false, lastChange: 0, amps: 0 },
    boiler: { on: false, lastChange: 0 },
    pool: { on: false, lastChange: 0 },
    heaterRight: { on: false, lastChange: 0 },
    heaterTable: { on: false, lastChange: 0 },
    acLiving: { on: false, lastChange: 0 },
    acMancave: { on: false, lastChange: 0 },
    acOffice: { on: false, lastChange: 0 },
    acBedroom: { on: false, lastChange: 0 }
});`;

    const newDeviceState = `flow.set('deviceState', {
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
});`;

    initNode.func = initNode.func.replace(oldDeviceState, newDeviceState);
    console.log('✓ Updated Init State node');
}

// Find the last sensor gathering node to connect new nodes
const poolClimateNode = flow.find(n => n.id === 'get_pool_climate');
const validateNode = flow.find(n => n.name === 'Validate');

// Add new sensor nodes for pool pump, pump power, and ambient temp
const newNodes = [
    {
        id: "get_pool_pump_switch",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "Pump SW",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "switch.poolhouse_pool_pump",
        state_type: "str",
        blockInputOverrides: false,
        outputProperties: [{property: "pool_pump_switch", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 870,
        y: 340,
        wires: [["get_pool_pump_power"]]
    },
    {
        id: "get_pool_pump_power",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "Pump W",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "sensor.poolhouse_pool_pump_power",
        state_type: "num",
        blockInputOverrides: false,
        outputProperties: [{property: "pool_pump_power", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 970,
        y: 340,
        wires: [["get_pool_ambient_temp"]]
    },
    {
        id: "get_pool_ambient_temp",
        type: "api-current-state",
        z: "power_manager_tab",
        name: "Ambient",
        server: "7a1ecefa.85d54",
        version: 3,
        outputs: 1,
        halt_if: "",
        halt_if_type: "str",
        entity_id: "sensor.98d8639f920c_ambient_temp_t05",
        state_type: "num",
        blockInputOverrides: false,
        outputProperties: [{property: "pool_ambient_temp", propertyType: "msg", value: "", valueType: "entityState"}],
        for: "",
        forType: "num",
        x: 1070,
        y: 340,
        wires: [["get_ev_state"]]
    }
];

// Update pool_climate to wire to our new node instead of ev_state
if (poolClimateNode) {
    poolClimateNode.wires = [["get_pool_pump_switch"]];
    console.log('✓ Rewired pool climate node');
}

// Check if nodes already exist
const existingPumpSwitch = flow.find(n => n.id === 'get_pool_pump_switch');
if (!existingPumpSwitch) {
    // Insert new nodes after pool climate
    const poolClimateIdx = flow.findIndex(n => n.id === 'get_pool_climate');
    flow.splice(poolClimateIdx + 1, 0, ...newNodes);
    console.log('✓ Added pool pump sensor nodes');
}

// Add pool pump handler node
const poolPumpHandler = {
    id: "pool_pump_handler",
    type: "api-call-service",
    z: "power_manager_tab",
    name: "Pool Pump",
    server: "7a1ecefa.85d54",
    version: 7,
    debugenabled: false,
    action: "switch.{{payload}}",
    floorId: [],
    areaId: [],
    deviceId: [],
    entityId: ["switch.poolhouse_pool_pump"],
    labelId: [],
    data: "",
    dataType: "jsonata",
    mergeContext: "",
    mustacheAltTags: false,
    outputProperties: [],
    blockInputOverrides: false,
    x: 1440,
    y: 400,
    wires: [[]]
};

const existingPumpHandler = flow.find(n => n.id === 'pool_pump_handler');
if (!existingPumpHandler) {
    // Find position after pool handler
    const poolHandlerIdx = flow.findIndex(n => n.id === 'pool_handler');
    if (poolHandlerIdx >= 0) {
        flow.splice(poolHandlerIdx + 1, 0, poolPumpHandler);
        console.log('✓ Added pool pump handler node');
    }
}

// Find and update the Validate node to include new inputs
const validateNodeObj = flow.find(n => n.name === 'Validate');
if (validateNodeObj && validateNodeObj.func) {
    // Add pool pump inputs to validation
    const oldPoolValidation = `// Pool
        poolSeason: safeStr(msg.pool_season, 'off'),
        poolPower: safeNum(msg.pool_power, 0),
        poolClimate: safeStr(msg.pool_climate, 'off'),`;

    const newPoolValidation = `// Pool
        poolSeason: safeStr(msg.pool_season, 'off'),
        poolPower: safeNum(msg.pool_power, 0),
        poolClimate: safeStr(msg.pool_climate, 'off'),
        poolPumpSwitch: safeStr(msg.pool_pump_switch, 'unknown'),
        poolPumpPower: safeNum(msg.pool_pump_power, 0),
        poolAmbientTemp: safeNum(msg.pool_ambient_temp, null),`;

    validateNodeObj.func = validateNodeObj.func.replace(oldPoolValidation, newPoolValidation);
    console.log('✓ Updated Validate node');
}

// Update Power Manager main logic to include frost protection
const pmNode = flow.find(n => n.id === 'power_manager');
if (pmNode) {
    // Add frost protection check function and call
    const frostProtectionCode = `
// === FROST PROTECTION ===
function checkFrostProtection() {
    const alerts = [];
    const fp = config.frostProtection;
    if (!fp?.enabled) return { alerts, poolPumpAction: 'none', planEntry: null };

    const ambientTemp = v.poolAmbientTemp;
    const pumpSwitchOn = v.poolPumpSwitch === 'on';
    const pumpPower = v.poolPumpPower || 0;
    const minPumpPower = fp.pumpMinPower ?? 100;
    const pumpActuallyRunning = pumpSwitchOn && pumpPower >= minPumpPower;

    if (ambientTemp === null) {
        return { alerts, poolPumpAction: 'none', planEntry: 'Frost: No temp sensor' };
    }

    const tempThreshold = fp.tempThreshold ?? 5;
    const criticalThreshold = fp.criticalThreshold ?? 2;
    const alertDelay = (fp.pumpOffAlertDelay ?? 300) * 1000;

    if (ambientTemp <= tempThreshold) {
        const isCritical = ambientTemp <= criticalThreshold;

        if (!pumpActuallyRunning) {
            const pumpState = deviceState.poolPump || { lastChange: now };
            const pumpOffDuration = now - pumpState.lastChange;

            let reason = !pumpSwitchOn ? 'switch OFF' : \`only \${pumpPower.toFixed(0)}W (min \${minPumpPower}W)\`;

            if (pumpOffDuration >= alertDelay) {
                const level = isCritical ? 'critical' : 'warning';
                const msg = isCritical
                    ? \`CRITICAL: Pool pump not running at \${ambientTemp.toFixed(1)}°C! \${reason}. Freeze risk!\`
                    : \`Warning: Pool pump not running during cold weather (\${ambientTemp.toFixed(1)}°C). \${reason}\`;
                alerts.push({ level, message: msg, entity: fp.notifyEntity });
            }

            return {
                alerts,
                poolPumpAction: 'on',
                planEntry: \`Frost: PUMP ON - \${reason} (\${ambientTemp.toFixed(1)}°C)\`
            };
        } else {
            const status = isCritical ? 'CRITICAL' : 'OK';
            return {
                alerts,
                poolPumpAction: 'none',
                planEntry: \`Frost: \${status}, pump \${pumpPower.toFixed(0)}W (\${ambientTemp.toFixed(1)}°C)\`
            };
        }
    }

    return { alerts: [], poolPumpAction: 'none', planEntry: null };
}

const frostResult = checkFrostProtection();
if (frostResult.planEntry) plan.push(frostResult.planEntry);

// Add poolPump decision
decisions.poolPump = { action: frostResult.poolPumpAction };

`;

    // Insert frost protection code after decision object initialization
    const insertPoint = `acBedroom: { action: 'none', mode: 'off', temp: 22 }
};`;

    pmNode.func = pmNode.func.replace(insertPoint, insertPoint + frostProtectionCode);

    // Add pool pump output handling
    const oldOutputsLine = `const outputs = new Array(12).fill(null);`;
    const newOutputsLine = `const outputs = new Array(13).fill(null);`;
    pmNode.func = pmNode.func.replace(oldOutputsLine, newOutputsLine);

    // Add pool pump output logic before outputs[9]
    const beforeOutput9 = `outputs[9] = { payload: { plan, actionLog, tariff, p1, pv, avail, headroom, ovr, isSummer, isExporting } };`;
    const poolPumpOutput = `// Pool pump frost protection
if (decisions.poolPump?.action === 'on' && v.poolPumpSwitch !== 'on') {
    outputs[12] = { payload: 'turn_on' };
    updateState('poolPump', true);
    logAction('Pool Pump ON (frost)');
    executed.push('Pool pump on');
}

// Send frost alerts
if (frostResult.alerts?.length > 0) {
    for (const alert of frostResult.alerts) {
        const alertMsg = { payload: { title: 'Power Manager - Frost Alert', message: alert.message } };
        outputs[11] = alertMsg;
    }
}

` + beforeOutput9;

    pmNode.func = pmNode.func.replace(beforeOutput9, poolPumpOutput);

    // Update outputs count
    pmNode.outputs = 13;

    // Update wires to include pool pump handler
    pmNode.wires.push(["pool_pump_handler"]);

    console.log('✓ Updated Power Manager logic with frost protection');
}

// Write updated flow
fs.writeFileSync(flowPath, JSON.stringify(flow, null, 4));
console.log('\n✓ Flow updated successfully!');
console.log('  Import the updated flows.json into Node-RED');
