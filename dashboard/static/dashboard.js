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

    const periods = schedule.tariff_periods;
    const totalHours = 24;

    // Build segments with better time display
    let html = '<div class="timeline-wrapper" style="position:relative;display:flex;width:100%;height:32px;border-radius:4px;overflow:hidden;">';

    periods.forEach((period, idx) => {
        const duration = period.duration_hours || 1;
        const widthPercent = (duration / totalHours) * 100;

        // Only show time if segment is wide enough (>8%)
        const showTime = widthPercent > 8;
        const timeLabel = showTime ? period.start : '';

        html += `<div class="timeline-segment ${period.tariff}" style="width:${widthPercent}%" title="${period.start} - ${period.end}: ${period.tariff.replace('-', ' ').toUpperCase()} (${duration}h)">${timeLabel}</div>`;
    });

    // NOW marker at position 0 (start of timeline = now)
    html += `<div class="timeline-now-marker" style="left:0%"></div>`;
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

// Build device activity timelines
function buildDeviceTimelines(timetable, limits) {
    if (!timetable || !timetable.hourly) return;

    // Get device powers from API (with fallbacks)
    const evPowerKw = timetable.ev_estimate?.charging_power_kw || 7.5;
    const devicePowers = timetable.device_powers || {};
    const scheduledHours = timetable.scheduled_hours || {};

    const devices = {
        'ev': { bar: document.getElementById('ev-timeline'), label: document.getElementById('ev-power-label'), power: evPowerKw * 1000 },
        'boiler': { bar: document.getElementById('boiler-timeline'), label: document.getElementById('boiler-power-label'), power: devicePowers.boiler || 2500 },
        'table_heater': { bar: document.getElementById('heater-timeline'), label: document.getElementById('heater-power-label'), power: devicePowers.table_heater || 4100 },
        'pool_pump': { bar: document.getElementById('pool-timeline'), label: document.getElementById('pool-power-label'), power: devicePowers.pool_pump || 100 },
        'dishwasher': { bar: document.getElementById('dishwasher-timeline'), label: document.getElementById('dishwasher-power-label'), power: devicePowers.dishwasher || 1900 },
        'washing_machine': { bar: document.getElementById('washing-machine-timeline'), label: document.getElementById('washing-machine-power-label'), power: 2000 },
        'tumble_dryer': { bar: document.getElementById('tumble-dryer-timeline'), label: document.getElementById('tumble-dryer-power-label'), power: 2500 }
    };

    const hours = timetable.hourly.slice(0, 24);
    const totalHours = 24;

    // Update power labels with kWh estimates
    Object.keys(devices).forEach(deviceKey => {
        const device = devices[deviceKey];
        if (device.label) {
            const hrs = scheduledHours[deviceKey] || 0;
            const kwh = (device.power / 1000) * hrs;
            if (hrs > 0) {
                device.label.textContent = `${kwh.toFixed(1)}kWh`;
                device.label.title = `${hrs}h × ${(device.power/1000).toFixed(1)}kW`;
            } else {
                device.label.textContent = '-';
                device.label.title = 'Not scheduled';
            }
        }
    });

    // Build activity array for each device
    Object.keys(devices).forEach(deviceKey => {
        const device = devices[deviceKey];
        if (!device.bar) return;

        let html = '';
        hours.forEach((entry, idx) => {
            const isActive = entry.devices && entry.devices[deviceKey];
            const widthPercent = (1 / totalHours) * 100;
            const activeClass = isActive ? 'active' : 'inactive';
            html += `<div class="device-bar-segment ${deviceKey} ${activeClass}" style="width:${widthPercent}%"></div>`;
        });

        // Fill remaining hours if less than 24
        for (let i = hours.length; i < 24; i++) {
            const widthPercent = (1 / totalHours) * 100;
            html += `<div class="device-bar-segment ${deviceKey} inactive" style="width:${widthPercent}%"></div>`;
        }

        device.bar.innerHTML = html;
    });

    // Build total power row showing if we exceed limits
    const totalBar = document.getElementById('total-timeline');
    const totalLabel = document.getElementById('total-power-label');
    if (totalBar) {
        let html = '';
        let maxPower = 0;

        hours.forEach((entry, idx) => {
            const totalPower = entry.total_power || 0;
            const limit = entry.limit || 8000;
            const widthPercent = (1 / totalHours) * 100;

            // Color based on utilization
            let colorClass = 'ok';
            if (totalPower > limit) {
                colorClass = 'over-limit';
            } else if (totalPower > limit * 0.8) {
                colorClass = 'warning';
            } else if (totalPower > 0) {
                colorClass = 'ok';
            } else {
                colorClass = 'inactive';
            }

            maxPower = Math.max(maxPower, totalPower);
            const title = `${entry.hour}: ${(totalPower/1000).toFixed(1)}kW / ${(limit/1000).toFixed(0)}kW limit`;
            html += `<div class="device-bar-segment total ${colorClass}" style="width:${widthPercent}%" title="${title}"></div>`;
        });

        // Fill remaining hours
        for (let i = hours.length; i < 24; i++) {
            const widthPercent = (1 / totalHours) * 100;
            html += `<div class="device-bar-segment total inactive" style="width:${widthPercent}%"></div>`;
        }

        totalBar.innerHTML = html;
        if (totalLabel) {
            totalLabel.textContent = maxPower > 0 ? `${(maxPower/1000).toFixed(1)}kW` : '';
        }
    }
}

// Update timetable with estimates
function updateTimetable(timetable) {
    if (!timetable) return;

    // Build device activity timelines
    buildDeviceTimelines(timetable);

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
                if (entry.devices.dishwasher) deviceIcons.push('🍽️');
                if (entry.devices.washing_machine) deviceIcons.push('🧺');
                if (entry.devices.tumble_dryer) deviceIcons.push('👕');
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

// Update consumers section
function updateConsumers(consumers) {
    if (!consumers) return;

    // Update summary totals
    const trackedEl = document.getElementById('consumers-tracked');
    const untrackedEl = document.getElementById('consumers-untracked');
    const importEl = document.getElementById('consumers-import');

    if (trackedEl) trackedEl.textContent = formatWatts(consumers.total_tracked);
    if (untrackedEl) untrackedEl.textContent = formatWatts(consumers.untracked);
    if (importEl) importEl.textContent = formatWatts(consumers.total_home);

    // Update grid with individual consumers
    const grid = document.getElementById('consumers-grid');
    if (!grid || !consumers.items) return;

    // Sort by power (highest first), filter out zero values for cleaner display
    const activeConsumers = consumers.items
        .filter(c => c.power > 0)
        .sort((a, b) => b.power - a.power);

    const inactiveConsumers = consumers.items
        .filter(c => c.power <= 0)
        .sort((a, b) => a.name.localeCompare(b.name));

    let html = '';

    // Active consumers first
    activeConsumers.forEach(consumer => {
        html += `
            <div class="consumer-item active">
                <span class="consumer-icon">${consumer.icon}</span>
                <span class="consumer-name">${consumer.name}</span>
                <span class="consumer-power">${formatWatts(consumer.power)}</span>
            </div>
        `;
    });

    // Inactive consumers (collapsed by default)
    if (inactiveConsumers.length > 0) {
        html += `<div class="consumer-inactive-group">`;
        inactiveConsumers.forEach(consumer => {
            html += `
                <div class="consumer-item inactive">
                    <span class="consumer-icon">${consumer.icon}</span>
                    <span class="consumer-name">${consumer.name}</span>
                    <span class="consumer-power">0W</span>
                </div>
            `;
        });
        html += `</div>`;
    }

    grid.innerHTML = html;
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

    // Power bar - use current tariff's limit
    let maxImport = 2500; // Default peak limit
    if (data.limits && data.schedule_24h?.summary?.[0]) {
        const tariffNow = data.schedule_24h.summary[0].toLowerCase();
        if (tariffNow.includes('super')) {
            maxImport = data.limits.super_off_peak || 8000;
        } else if (tariffNow.includes('off-peak') || tariffNow.includes('off peak')) {
            maxImport = data.limits.off_peak || 5000;
        } else {
            maxImport = data.limits.peak || 2500;
        }
    }
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
    document.getElementById('power-limit').textContent = `/ ${formatWatts(maxImport)} limit`;

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

    // Update consumers
    if (data.consumers) {
        updateConsumers(data.consumers);
    }

    // Alerts - always clear first, then build list
    const alertsSection = document.getElementById('alerts-section');
    const alertsList = document.getElementById('alerts-list');
    let alertsHtml = '';

    // Add decision engine alerts
    if (data.alerts && data.alerts.length > 0) {
        alertsHtml += data.alerts.map(alert =>
            `<div class="alert-item ${alert.level}">${alert.message}</div>`
        ).join('');
    }

    // Add active schedule alerts (deduplicated)
    if (data.schedule_24h && data.schedule_24h.alerts_schedule && data.schedule_24h.alerts_schedule.length > 0) {
        alertsHtml += data.schedule_24h.alerts_schedule.map(alert =>
            `<div class="alert-item warning">${alert.message}</div>`
        ).join('');
    }

    // Update DOM
    alertsList.innerHTML = alertsHtml;
    alertsSection.style.display = alertsHtml ? 'block' : 'none';

    // Last update
    if (data.last_update) {
        const date = new Date(data.last_update);
        document.getElementById('last-update').textContent = date.toLocaleTimeString();
    }

    // Status indicator
    const statusIndicator = document.getElementById('status-indicator');
    statusIndicator.classList.remove('disconnected');

    // Update power limits in settings
    if (data.limits) {
        updateLimits(data.limits);
    }
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

// Toggle settings panel
function toggleSettings() {
    const content = document.getElementById('settings-content');
    const toggle = document.getElementById('settings-toggle');
    if (content.style.display === 'none') {
        content.style.display = 'block';
        toggle.textContent = '-';
    } else {
        content.style.display = 'none';
        toggle.textContent = '+';
    }
}

// Update limit inputs from data
function updateLimits(limits) {
    if (!limits) return;

    const peakInput = document.getElementById('limit-peak');
    const offPeakInput = document.getElementById('limit-off-peak');
    const superOffPeakInput = document.getElementById('limit-super-off-peak');

    if (peakInput && limits.peak) peakInput.value = limits.peak;
    if (offPeakInput && limits.off_peak) offPeakInput.value = limits.off_peak;
    if (superOffPeakInput && limits.super_off_peak) superOffPeakInput.value = limits.super_off_peak;
}

// Save power limits
async function saveLimits() {
    const peak = parseInt(document.getElementById('limit-peak').value);
    const offPeak = parseInt(document.getElementById('limit-off-peak').value);
    const superOffPeak = parseInt(document.getElementById('limit-super-off-peak').value);
    const statusEl = document.getElementById('save-status');

    try {
        const params = new URLSearchParams();
        params.append('peak', peak);
        params.append('off_peak', offPeak);
        params.append('super_off_peak', superOffPeak);

        const response = await fetch(`/api/limits?${params.toString()}`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        statusEl.textContent = 'Saved!';
        statusEl.className = 'save-status';
        setTimeout(() => { statusEl.textContent = ''; }, 3000);

        // Refresh to show updated values
        fetchStatus();
    } catch (error) {
        console.error('Failed to save limits:', error);
        statusEl.textContent = 'Failed to save';
        statusEl.className = 'save-status error';
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    fetchStatus();
    setInterval(fetchStatus, REFRESH_INTERVAL);
});
