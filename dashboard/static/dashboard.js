/**
 * Power Manager Dashboard JavaScript
 * Home Assistant themed dashboard with 24-hour schedule
 */

const REFRESH_INTERVAL = 5000;

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
    return states[state] || `Unknown`;
}

// Build the 24-hour tariff timeline
function buildTimeline(schedule) {
    const timeline = document.getElementById('tariff-timeline');
    if (!timeline || !schedule || !schedule.tariff_periods) return;

    // Clear existing
    timeline.innerHTML = '';

    // Calculate total hours and build segments
    let html = '<div class="timeline-wrapper" style="position:relative;display:flex;height:24px;border-radius:4px;overflow:hidden;">';

    const periods = schedule.tariff_periods;
    const totalHours = 24;

    periods.forEach(period => {
        const duration = period.duration_hours || 1;
        const widthPercent = (duration / totalHours) * 100;
        const tariffClass = period.tariff.replace('-', '-');

        html += `<div class="timeline-segment ${period.tariff}" style="width:${widthPercent}%" title="${period.start}-${period.end}: ${period.tariff.toUpperCase()}">${period.start}</div>`;
    });

    // Add now marker - calculate position based on current time
    const now = new Date();
    const currentHour = now.getHours() + now.getMinutes() / 60;
    const nowPosition = (currentHour / totalHours) * 100;

    html += `<div class="timeline-now-marker" style="left:${nowPosition}%"></div>`;
    html += '</div>';

    timeline.innerHTML = html;
}

// Update schedule section
function updateSchedule(schedule) {
    if (!schedule) return;

    // Update season badge
    const seasonBadge = document.getElementById('season-badge');
    if (seasonBadge) {
        seasonBadge.textContent = schedule.season.toUpperCase();
    }

    // Update tariff badge
    const tariffBadge = document.getElementById('tariff-badge');
    if (tariffBadge && schedule.summary && schedule.summary.length > 0) {
        const nowTariff = schedule.summary[0].replace('Now: ', '').replace(' tariff', '');
        tariffBadge.textContent = nowTariff;
        tariffBadge.className = 'tariff-badge ' + nowTariff.toLowerCase().replace(' ', '-');
    }

    // Update next tariff
    const nextTariff = document.getElementById('next-tariff');
    if (nextTariff && schedule.summary && schedule.summary.length > 1) {
        nextTariff.textContent = schedule.summary[1];
    }

    // Build timeline
    buildTimeline(schedule);

    // Update EV schedule
    const evSchedule = document.getElementById('ev-schedule-list');
    if (evSchedule && schedule.ev_plan) {
        if (schedule.ev_plan.length > 0) {
            evSchedule.innerHTML = schedule.ev_plan.map(plan =>
                `<div class="schedule-item">
                    <span class="schedule-time">${plan.window}</span>
                    <span class="schedule-reason">${plan.reason}</span>
                </div>`
            ).join('');
        } else {
            evSchedule.innerHTML = '<div class="schedule-item">No charging planned</div>';
        }
    }

    // Update Boiler schedule
    const boilerSchedule = document.getElementById('boiler-schedule-list');
    if (boilerSchedule && schedule.boiler_plan) {
        if (schedule.boiler_plan.length > 0) {
            boilerSchedule.innerHTML = schedule.boiler_plan.map(plan =>
                `<div class="schedule-item">
                    <span class="schedule-time">${plan.window}</span>
                    <span class="schedule-reason">${plan.reason}</span>
                </div>`
            ).join('');
        } else {
            boilerSchedule.innerHTML = '<div class="schedule-item">No heating planned</div>';
        }
    }

    // Update status summary
    const statusSummary = document.getElementById('status-summary');
    if (statusSummary && schedule.summary) {
        statusSummary.innerHTML = schedule.summary.slice(2).map(item =>
            `<div class="summary-item">${item}</div>`
        ).join('');
    }
}

// Update timetable with estimates
function updateTimetable(timetable) {
    if (!timetable) return;

    // Update EV estimate
    const evEstimateEl = document.getElementById('ev-estimate');
    if (evEstimateEl && timetable.ev_estimate) {
        const ev = timetable.ev_estimate;
        let text;
        if (ev.needed) {
            text = `EV: <span class="needed">${ev.current_percent}% → ${ev.target_percent}%</span> (${ev.kwh_needed}kWh, ~${ev.hours_needed}h)`;
        } else {
            text = `EV: <span class="ok">No charging needed</span>`;
        }
        evEstimateEl.querySelector('.estimate-text').innerHTML = text;
    }

    // Update Boiler estimate
    const boilerEstimateEl = document.getElementById('boiler-estimate');
    if (boilerEstimateEl && timetable.boiler_estimate) {
        const boiler = timetable.boiler_estimate;
        let text;
        if (boiler.needed) {
            text = `Boiler: <span class="needed">Needs ~${boiler.hours_needed}h heating</span>`;
        } else {
            text = `Boiler: <span class="ok">Already hot</span>`;
        }
        boilerEstimateEl.querySelector('.estimate-text').innerHTML = text;
    }

    // Update hourly timetable grid
    const timetableGrid = document.getElementById('timetable-grid');
    if (timetableGrid && timetable.hourly) {
        // Show first 24 hours in a grid
        let html = '';
        const hours = timetable.hourly.slice(0, 24);

        hours.forEach(entry => {
            const hasDevices = Object.keys(entry.devices || {}).length > 0;
            const deviceIcons = [];
            if (entry.devices) {
                if (entry.devices.ev) deviceIcons.push('⚡');
                if (entry.devices.boiler) deviceIcons.push('🔥');
                if (entry.devices.table_heater) deviceIcons.push('🪑');
                if (entry.devices.pool_pump) deviceIcons.push('🌊');
            }

            html += `<div class="timetable-hour ${entry.tariff}${hasDevices ? ' has-devices' : ''}">
                <div class="hour-label">${entry.hour}</div>
                <div class="hour-devices">${deviceIcons.join('') || '-'}</div>
            </div>`;
        });

        timetableGrid.innerHTML = html;
    }

    // Show warnings
    const timetableSection = document.getElementById('timetable-section');
    if (timetable.warnings && timetable.warnings.length > 0) {
        let warningsHtml = '<div class="timetable-warnings">';
        warningsHtml += timetable.warnings.map(w => `⚠️ ${w}`).join('<br>');
        warningsHtml += '</div>';

        const existingWarnings = timetableSection.querySelector('.timetable-warnings');
        if (existingWarnings) {
            existingWarnings.outerHTML = warningsHtml;
        } else {
            timetableSection.insertAdjacentHTML('beforeend', warningsHtml);
        }
    }
}

// Update the dashboard with new data
function updateDashboard(data) {
    // Power flow
    const gridPower = data.grid_import || 0;
    const pvPower = data.pv_production || 0;
    const netPower = gridPower + pvPower;

    document.getElementById('grid-power').textContent = formatWatts(Math.abs(gridPower));
    document.getElementById('pv-power').textContent = formatWatts(pvPower);
    document.getElementById('net-power').textContent = formatWatts(netPower);

    // Grid direction and styling
    const gridNode = document.querySelector('.power-node.grid');
    const gridLabel = document.getElementById('grid-direction');
    if (gridPower < 0 || data.is_exporting) {
        gridLabel.textContent = 'Export';
        gridNode.classList.add('exporting');
    } else {
        gridLabel.textContent = 'Import';
        gridNode.classList.remove('exporting');
    }

    // Power bar
    const maxImport = 2500; // Default peak limit
    const usage = Math.max(0, gridPower);
    const usagePercent = Math.min(100, (usage / maxImport) * 100);
    const powerBarFill = document.getElementById('power-bar-fill');
    if (powerBarFill) {
        powerBarFill.style.width = `${usagePercent}%`;
        powerBarFill.classList.remove('warning', 'critical');
        if (usagePercent > 90) {
            powerBarFill.classList.add('critical');
        } else if (usagePercent > 70) {
            powerBarFill.classList.add('warning');
        }
    }
    document.getElementById('power-used').textContent = formatWatts(usage);

    // Devices
    if (data.devices) {
        // Boiler
        if (data.devices.boiler) {
            const boilerState = document.getElementById('boiler-state');
            const boilerDot = document.getElementById('boiler-dot');
            const isOn = data.devices.boiler.state === 'on';
            boilerState.textContent = isOn ? 'ON' : 'OFF';
            boilerDot.className = 'status-dot' + (isOn ? ' on' : '');
            document.getElementById('boiler-power').textContent = formatWatts(data.devices.boiler.power);

            const boilerDevice = document.getElementById('device-boiler');
            boilerDevice.classList.toggle('active', isOn);
        }

        // EV Charger
        if (data.devices.ev) {
            const evState = document.getElementById('ev-state');
            const evDot = document.getElementById('ev-dot');
            const stateText = getEvStateText(data.devices.ev.state);
            const isCharging = data.devices.ev.state === 132;
            evState.textContent = stateText;
            evDot.className = 'status-dot' + (isCharging ? ' charging' : (data.devices.ev.state === 129 ? ' on' : ''));
            document.getElementById('ev-power').textContent = formatWatts(data.devices.ev.power);
            document.getElementById('ev-amps').textContent = `(${data.devices.ev.amps}A)`;

            const evDevice = document.getElementById('device-ev');
            evDevice.classList.toggle('active', isCharging);
        }

        // Pool Pump
        if (data.devices.pool_pump) {
            const poolState = document.getElementById('pool-pump-state');
            const poolDot = document.getElementById('pool-dot');
            const isOn = data.devices.pool_pump.state === 'on';
            poolState.textContent = isOn ? 'ON' : 'OFF';
            poolDot.className = 'status-dot' + (isOn ? ' on' : '');
            document.getElementById('pool-pump-power').textContent = formatWatts(data.devices.pool_pump.power);

            const temp = data.devices.pool_pump.ambient_temp;
            const tempEl = document.getElementById('pool-ambient-temp');
            if (temp !== null) {
                tempEl.textContent = `${temp.toFixed(1)}°C`;
                tempEl.className = 'temp' + (temp <= 5 ? ' warning' : '');
            }

            const poolDevice = document.getElementById('device-pool');
            poolDevice.classList.toggle('active', isOn);
        }

        // Table Heater
        if (data.devices.table_heater) {
            const tableHeaterState = document.getElementById('table-heater-state');
            const tableHeaterDot = document.getElementById('table-heater-dot');
            const isOn = data.devices.table_heater.state === 'on';
            tableHeaterState.textContent = isOn ? 'ON' : 'OFF';
            tableHeaterDot.className = 'status-dot' + (isOn ? ' on' : '');
            document.getElementById('table-heater-power').textContent = formatWatts(data.devices.table_heater.power);

            const tableHeaterDevice = document.getElementById('device-table-heater');
            tableHeaterDevice.classList.toggle('active', isOn);
        }

        // BMW i5
        if (data.devices.bmw_i5) {
            const i5Location = document.getElementById('bmw-i5-location');
            i5Location.textContent = data.devices.bmw_i5.location === 'home' ? 'Home' : 'Away';
            document.getElementById('bmw-i5-battery').textContent = data.devices.bmw_i5.battery !== null ? `${Math.round(data.devices.bmw_i5.battery)}%` : '--%';
            document.getElementById('bmw-i5-range').textContent = data.devices.bmw_i5.range !== null ? `${Math.round(data.devices.bmw_i5.range)}km` : '--km';
        }

        // BMW iX1
        if (data.devices.bmw_ix1) {
            const ix1Location = document.getElementById('bmw-ix1-location');
            ix1Location.textContent = data.devices.bmw_ix1.location === 'home' ? 'Home' : 'Away';
            document.getElementById('bmw-ix1-battery').textContent = data.devices.bmw_ix1.battery !== null ? `${Math.round(data.devices.bmw_ix1.battery)}%` : '--%';
            document.getElementById('bmw-ix1-range').textContent = data.devices.bmw_ix1.range !== null ? `${Math.round(data.devices.bmw_ix1.range)}km` : '--km';
        }
    }

    // Update 24-hour schedule
    if (data.schedule_24h) {
        updateSchedule(data.schedule_24h);
    }

    // Update timetable with estimates
    if (data.timetable) {
        updateTimetable(data.timetable);
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

    // Active schedule alerts
    if (data.schedule_24h && data.schedule_24h.alerts_schedule && data.schedule_24h.alerts_schedule.length > 0) {
        alertsSection.style.display = 'block';
        const scheduleAlerts = data.schedule_24h.alerts_schedule.map(alert =>
            `<div class="alert-item warning">${alert.message}</div>`
        ).join('');
        alertsList.innerHTML += scheduleAlerts;
    }

    // Last update
    if (data.last_update) {
        const date = new Date(data.last_update);
        document.getElementById('last-update').textContent = date.toLocaleTimeString();
    }

    // Status indicator
    const statusIndicator = document.getElementById('status-indicator');
    statusIndicator.classList.remove('disconnected');
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
        statusIndicator.classList.add('disconnected');
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
        fetchStatus();
    } catch (error) {
        console.error('Failed to set override:', error);
        alert(`Failed to set ${device} to ${mode}: ${error.message}`);
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    fetchStatus();
    setInterval(fetchStatus, REFRESH_INTERVAL);
});
