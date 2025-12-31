/**
 * Power Manager Dashboard JavaScript
 * Auto-refreshes status every 5 seconds
 */

const REFRESH_INTERVAL = 5000; // 5 seconds

// Format watts for display
function formatWatts(watts) {
    if (watts === null || watts === undefined) return '--';
    const absWatts = Math.abs(watts);
    if (absWatts >= 1000) {
        return `${(watts / 1000).toFixed(1)}kW`;
    }
    return `${Math.round(watts)}W`;
}

// Get EV state text
function getEvStateText(state) {
    const states = {
        128: 'No car',
        129: 'Ready',
        130: 'Full',
        132: 'Charging'
    };
    return states[state] || `Unknown (${state})`;
}

// Update the dashboard with new data
function updateDashboard(data) {
    // Power flow
    const gridPower = data.grid_import;
    const pvPower = data.pv_production;
    const netPower = gridPower + pvPower; // Approximate consumption

    document.getElementById('grid-power').textContent = formatWatts(Math.abs(gridPower));
    document.getElementById('pv-power').textContent = formatWatts(pvPower);
    document.getElementById('net-power').textContent = formatWatts(netPower);

    // Grid direction
    const gridCard = document.querySelector('.power-card.grid');
    const gridDirection = document.getElementById('grid-direction');
    if (gridPower < 0 || data.is_exporting) {
        gridDirection.textContent = 'Exporting';
        gridCard.classList.add('exporting');
        gridCard.classList.remove('importing');
    } else {
        gridDirection.textContent = 'Importing';
        gridCard.classList.add('importing');
        gridCard.classList.remove('exporting');
    }

    // Devices
    if (data.devices) {
        // Boiler
        if (data.devices.boiler) {
            const boilerState = document.getElementById('boiler-state');
            boilerState.textContent = data.devices.boiler.state.toUpperCase();
            boilerState.className = `device-state ${data.devices.boiler.state}`;
            document.getElementById('boiler-power').textContent = formatWatts(data.devices.boiler.power);
            const boilerDecision = document.getElementById('boiler-decision');
            if (data.devices.boiler.decision !== 'none') {
                boilerDecision.textContent = data.devices.boiler.decision.toUpperCase();
                boilerDecision.className = `decision ${data.devices.boiler.decision}`;
            } else {
                boilerDecision.textContent = '';
            }
        }

        // EV Charger
        if (data.devices.ev) {
            const evState = document.getElementById('ev-state');
            const stateText = getEvStateText(data.devices.ev.state);
            evState.textContent = stateText;
            evState.className = `device-state ${data.devices.ev.state === 132 ? 'charging' : (data.devices.ev.state === 129 ? 'on' : 'off')}`;
            document.getElementById('ev-power').textContent = formatWatts(data.devices.ev.power);
            document.getElementById('ev-amps').textContent = `${data.devices.ev.amps}A`;
            const evDecision = document.getElementById('ev-decision');
            if (data.devices.ev.decision !== 'none') {
                evDecision.textContent = data.devices.ev.decision.toUpperCase();
                evDecision.className = `decision ${data.devices.ev.decision}`;
            } else {
                evDecision.textContent = '';
            }
        }

        // Pool Pump
        if (data.devices.pool_pump) {
            const poolState = document.getElementById('pool-pump-state');
            poolState.textContent = data.devices.pool_pump.state.toUpperCase();
            poolState.className = `device-state ${data.devices.pool_pump.state}`;
            document.getElementById('pool-pump-power').textContent = formatWatts(data.devices.pool_pump.power);
            const ambientTemp = data.devices.pool_pump.ambient_temp;
            document.getElementById('pool-ambient-temp').textContent = ambientTemp !== null ? `${ambientTemp.toFixed(1)}C` : '--';
        }

        // BMW i5
        if (data.devices.bmw_i5) {
            const i5Location = document.getElementById('bmw-i5-location');
            i5Location.textContent = data.devices.bmw_i5.location === 'home' ? 'Home' : 'Away';
            i5Location.className = `device-state ${data.devices.bmw_i5.location === 'home' ? 'home' : 'away'}`;
            document.getElementById('bmw-i5-battery').textContent = data.devices.bmw_i5.battery !== null ? `${Math.round(data.devices.bmw_i5.battery)}%` : '--%';
            document.getElementById('bmw-i5-range').textContent = data.devices.bmw_i5.range !== null ? `${Math.round(data.devices.bmw_i5.range)}km` : '--km';
        }

        // BMW iX1
        if (data.devices.bmw_ix1) {
            const ix1Location = document.getElementById('bmw-ix1-location');
            ix1Location.textContent = data.devices.bmw_ix1.location === 'home' ? 'Home' : 'Away';
            ix1Location.className = `device-state ${data.devices.bmw_ix1.location === 'home' ? 'home' : 'away'}`;
            document.getElementById('bmw-ix1-battery').textContent = data.devices.bmw_ix1.battery !== null ? `${Math.round(data.devices.bmw_ix1.battery)}%` : '--%';
            document.getElementById('bmw-ix1-range').textContent = data.devices.bmw_ix1.range !== null ? `${Math.round(data.devices.bmw_ix1.range)}km` : '--km';
        }
    }

    // Plan
    if (data.plan && data.plan.length > 0) {
        const planList = document.getElementById('plan-list');
        planList.innerHTML = data.plan.map(item => `<div class="plan-item">${item}</div>`).join('');
    }

    // Alerts
    const alertsSection = document.getElementById('alerts-section');
    const alertsList = document.getElementById('alerts-list');
    if (data.alerts && data.alerts.length > 0) {
        alertsSection.style.display = 'block';
        alertsList.innerHTML = data.alerts.map(alert =>
            `<div class="alert-item ${alert.level}">${alert.message}</div>`
        ).join('');
    } else {
        alertsSection.style.display = 'none';
    }

    // Last update
    if (data.last_update) {
        const date = new Date(data.last_update);
        document.getElementById('last-update').textContent = date.toLocaleTimeString();
    }

    // Status indicator
    const statusIndicator = document.getElementById('status-indicator');
    statusIndicator.textContent = 'Connected';
    statusIndicator.className = 'status-ok';
}

// Fetch status from API
async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        updateDashboard(data);
    } catch (error) {
        console.error('Failed to fetch status:', error);
        const statusIndicator = document.getElementById('status-indicator');
        statusIndicator.textContent = 'Disconnected';
        statusIndicator.className = 'status-ok status-error';
    }
}

// Set override
async function setOverride(device, mode) {
    try {
        const response = await fetch(`/api/override/${device}?mode=${mode}`, {
            method: 'POST'
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        // Refresh immediately
        fetchStatus();
    } catch (error) {
        console.error('Failed to set override:', error);
        alert(`Failed to set ${device} to ${mode}: ${error.message}`);
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Initial fetch
    fetchStatus();

    // Auto-refresh
    setInterval(fetchStatus, REFRESH_INTERVAL);
});
