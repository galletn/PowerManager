/**
 * Power Manager Dashboard JavaScript
 * Home Assistant themed dashboard with 24-hour schedule
 *
 * STANDALONE MODE: To use this dashboard from HA's www folder or another host,
 * set window.POWER_MANAGER_API before loading this script:
 *   <script>window.POWER_MANAGER_API = 'https://192.168.68.78:8081';</script>
 *   <script src="dashboard.js"></script>
 */

// API base URL - empty for relative URLs (when served by Power Manager),
// or set window.POWER_MANAGER_API for standalone deployments
const API_BASE_URL = window.POWER_MANAGER_API || '';

const REFRESH_INTERVAL = 10000; // 10 seconds - matches well with 30s decision loop

// Moon phase emojis (8 phases)
const MOON_PHASES = ['🌑', '🌒', '🌓', '🌔', '🌕', '🌖', '🌗', '🌘'];

// Get solar icon based on environment data
function getSolarIcon(env) {
    if (!env) return '☀️';

    // Night time - show moon with correct phase
    if (!env.sun_is_up) {
        return MOON_PHASES[env.moon_phase] || '🌙';
    }

    // Day time - show sun with weather conditions
    const condition = (env.weather_condition || '').toLowerCase();
    const clouds = env.cloud_coverage || 0;

    // Rain conditions
    if (condition.includes('rain') || condition.includes('shower')) {
        return '🌧️';
    }
    if (condition.includes('thunder') || condition.includes('storm')) {
        return '⛈️';
    }
    if (condition.includes('snow')) {
        return '🌨️';
    }

    // Cloud conditions
    if (clouds > 80 || condition.includes('cloudy') || condition.includes('overcast')) {
        return '☁️';
    }
    if (clouds > 50 || condition.includes('partly')) {
        return '⛅';
    }
    if (clouds > 20) {
        return '🌤️';
    }

    // Clear/sunny
    return '☀️';
}

// Format watts for display
function formatWatts(watts) {
    if (watts === null || watts === undefined) return '--';
    const absWatts = Math.abs(watts);
    if (absWatts >= 1000) {
        return `${(watts / 1000).toFixed(1)}kW`;
    }
    return `${Math.round(watts)}W`;
}

// Format ISO timestamp to relative time (e.g., "2h ago", "yesterday at 15:47")
function formatRelativeTime(isoString) {
    if (!isoString) return null;

    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return `yesterday ${timeStr}`;
    if (diffDays < 7) return `${diffDays}d ago`;

    return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ` ${timeStr}`;
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

// Update car card with BMW data
function updateCarCard(carId, carData) {
    const prefix = carId === 'i5' ? 'bmw-i5' : 'bmw-ix1';

    // Location badge
    const locationBadge = document.getElementById(`${carId}-location-badge`);
    const locationEl = document.getElementById(`${prefix}-location`);
    const isHome = carData.location === 'home';
    if (locationEl) locationEl.textContent = isHome ? 'Home' : 'Away';
    if (locationBadge) {
        locationBadge.classList.remove('home', 'away');
        locationBadge.classList.add(isHome ? 'home' : 'away');
    }

    // Battery percentage and fill
    const battery = carData.battery;
    const batteryPercent = battery !== null ? Math.round(battery) : null;
    setTextIfExists(`${prefix}-battery`, batteryPercent !== null ? `${batteryPercent}%` : '--%');

    const batteryFill = document.getElementById(`${carId}-battery-fill`);
    if (batteryFill && batteryPercent !== null) {
        batteryFill.style.width = `${batteryPercent}%`;
        // Update color based on level
        batteryFill.classList.remove('low', 'medium', 'charging');
        if (carData.charging_state === 'CHARGING') {
            batteryFill.classList.add('charging');
        } else if (batteryPercent < 20) {
            batteryFill.classList.add('low');
        } else if (batteryPercent < 40) {
            batteryFill.classList.add('medium');
        }
    }

    // Target SOC
    const targetSoc = carData.target_soc;
    setTextIfExists(`${prefix}-target-soc`, targetSoc !== null ? `${targetSoc}%` : '--%');
    const batteryTarget = document.getElementById(`${carId}-battery-target`);
    if (batteryTarget && targetSoc !== null) {
        batteryTarget.style.left = `${targetSoc}%`;
    }

    // Range
    const range = carData.range;
    setTextIfExists(`${prefix}-range`, range !== null ? Math.round(range) : '--');

    // Mileage
    const mileage = carData.mileage;
    setTextIfExists(`${prefix}-mileage`, mileage !== null ? `${mileage.toLocaleString()} km` : '-- km');

    // Charging state and plug
    const chargingState = carData.charging_state || 'unknown';
    const plugState = carData.plug_state || 'unknown';
    const isCharging = chargingState === 'CHARGING';
    const isPlugged = plugState === 'CONNECTED' || isCharging;

    // Update plug icon
    const plugIcon = document.getElementById(`${carId}-plug-icon`);
    if (plugIcon) {
        plugIcon.classList.remove('connected', 'charging');
        if (isCharging) {
            plugIcon.classList.add('charging');
            plugIcon.textContent = '⚡';
        } else if (isPlugged) {
            plugIcon.classList.add('connected');
            plugIcon.textContent = '🔌';
        } else {
            plugIcon.textContent = '🔌';
        }
    }

    // Update charging text
    const chargingTextEl = document.getElementById(`${prefix}-charging-state`);
    if (chargingTextEl) {
        let chargingText = 'Not plugged';
        if (isCharging) {
            chargingText = 'Charging';
            chargingTextEl.classList.add('active');
        } else if (isPlugged) {
            chargingText = 'Plugged in';
            chargingTextEl.classList.remove('active');
        } else {
            chargingTextEl.classList.remove('active');
        }
        chargingTextEl.textContent = chargingText;
    }

    // Charging power section
    const powerSection = document.getElementById(`${carId}-charging-power-section`);
    if (powerSection) {
        if (isCharging && carData.charging_power) {
            powerSection.style.display = 'flex';
            const powerKw = (carData.charging_power / 1000).toFixed(1);
            setTextIfExists(`${prefix}-charging-power`, powerKw);

            // Time to full
            const timeToFull = carData.time_to_full;
            const timeEl = document.getElementById(`${prefix}-time-to-full`);
            if (timeEl && timeToFull !== null && timeToFull > 0) {
                const hours = Math.floor(timeToFull / 60);
                const mins = Math.round(timeToFull % 60);
                if (hours > 0) {
                    timeEl.textContent = `${hours}h ${mins}m left`;
                } else {
                    timeEl.textContent = `${mins}m left`;
                }
            } else if (timeEl) {
                timeEl.textContent = '';
            }
        } else {
            powerSection.style.display = 'none';
        }
    }
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
    const evPowerKw = (timetable.ev_estimate && timetable.ev_estimate.charging_power_kw) || 7.5;
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

// Update status dots in the 24h schedule to show current device on/off state
function updateScheduleStatusDots(devices, consumers) {
    if (!devices) return;

    // Helper to get consumer power by id
    function getConsumerPower(id) {
        if (!consumers || !consumers.items) return 0;
        const item = consumers.items.find(c => c.id === id);
        return item ? item.power : 0;
    }

    // EV - check if charging (state 132)
    const evDot = document.getElementById('schedule-ev-dot');
    if (evDot && devices.ev) {
        const isCharging = devices.ev.state === 132;
        evDot.className = 'schedule-status-dot' + (isCharging ? ' on charging' : '');
    }

    // Boiler
    const boilerDot = document.getElementById('schedule-boiler-dot');
    if (boilerDot && devices.boiler) {
        const isOn = devices.boiler.state === 'on';
        boilerDot.className = 'schedule-status-dot' + (isOn ? ' on' : '');
    }

    // Table Heater
    const heaterDot = document.getElementById('schedule-heater-dot');
    if (heaterDot && devices.table_heater) {
        const isOn = devices.table_heater.state === 'on';
        heaterDot.className = 'schedule-status-dot' + (isOn ? ' on' : '');
    }

    // Pool Pump
    const poolDot = document.getElementById('schedule-pool-dot');
    if (poolDot && devices.pool_pump) {
        const isOn = devices.pool_pump.state === 'on';
        poolDot.className = 'schedule-status-dot' + (isOn ? ' on' : '');
    }

    // Dishwasher
    const dishwasherDot = document.getElementById('schedule-dishwasher-dot');
    if (dishwasherDot && devices.dishwasher) {
        const isOn = devices.dishwasher.state === 'on';
        dishwasherDot.className = 'schedule-status-dot' + (isOn ? ' on' : '');
    }

    // Washing machine (check by power > threshold since it's not a switch)
    const washingDot = document.getElementById('schedule-washing-dot');
    if (washingDot) {
        const washingPower = getConsumerPower('washing_machine');
        const isOn = washingPower > 10;
        washingDot.className = 'schedule-status-dot' + (isOn ? ' on' : '');
    }

    // Tumble dryer (check by power > threshold)
    const dryerDot = document.getElementById('schedule-dryer-dot');
    if (dryerDot) {
        const dryerPower = getConsumerPower('tumble_dryer');
        const isOn = dryerPower > 10;
        dryerDot.className = 'schedule-status-dot' + (isOn ? ' on' : '');
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
function updateConsumers(consumers, gridImport) {
    if (!consumers) return;

    // Update summary totals
    const trackedEl = document.getElementById('consumers-tracked');
    const untrackedEl = document.getElementById('consumers-untracked');
    const importEl = document.getElementById('consumers-import');

    if (trackedEl) trackedEl.textContent = formatWatts(consumers.total_tracked);
    if (untrackedEl) untrackedEl.textContent = formatWatts(consumers.untracked);
    if (importEl) importEl.textContent = formatWatts(gridImport || 0);

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

// Safely set text content on element if it exists
function setTextIfExists(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

// Update the dashboard with new data
function updateDashboard(data) {
    // Power flow - use net_power (negative = exporting, positive = importing)
    // Fall back to grid_import - grid_export if net_power not available
    const gridPower = data.net_power !== undefined ? data.net_power :
                      (data.grid_import || 0) - (data.grid_export || 0);
    const pvPower = data.pv_production || 0;
    const isExporting = gridPower < 0 || data.is_exporting;

    // Display absolute value for power reading
    setTextIfExists('grid-power', formatWatts(Math.abs(gridPower)));
    setTextIfExists('pv-power', formatWatts(pvPower));
    setTextIfExists('net-power', formatWatts(Math.abs(gridPower)));

    // Grid direction and styling - support both full and compact dashboard class names
    const gridNode = document.querySelector('.power-node.grid') || document.querySelector('.power-node-large.grid');
    const gridLabel = document.getElementById('grid-direction');
    const gridArrow = document.getElementById('arrow-grid');
    const solarArrow = document.getElementById('arrow-solar');

    if (gridLabel) {
        if (isExporting) {
            gridLabel.textContent = 'Export';
            if (gridNode) gridNode.classList.add('exporting');
        } else {
            gridLabel.textContent = 'Import';
            if (gridNode) gridNode.classList.remove('exporting');
        }
    }

    // Update grid arrow direction and animation
    if (gridArrow) {
        if (isExporting) {
            gridArrow.textContent = '→';
            gridArrow.classList.add('flow-right');
            gridArrow.classList.remove('flow-left');
        } else if (gridPower > 50) {
            gridArrow.textContent = '←';
            gridArrow.classList.add('flow-left');
            gridArrow.classList.remove('flow-right');
        } else {
            gridArrow.textContent = '↔';
            gridArrow.classList.remove('flow-left', 'flow-right');
        }
    }

    // Update solar arrow animation (flows when producing)
    if (solarArrow) {
        if (pvPower > 50) {
            solarArrow.classList.add('flow-right');
        } else {
            solarArrow.classList.remove('flow-right');
        }
    }

    // Power bar - use current tariff's limit
    let maxImport = 2500; // Default peak limit
    if (data.limits && data.schedule_24h && data.schedule_24h.summary && data.schedule_24h.summary[0]) {
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
    setTextIfExists('power-used', formatWatts(usage));
    setTextIfExists('power-limit', `/ ${formatWatts(maxImport)} limit`);

    // Devices - handle missing elements gracefully for compact dashboards
    if (data.devices) {
        // Boiler
        if (data.devices.boiler) {
            const boilerState = document.getElementById('boiler-state');
            const boilerDot = document.getElementById('boiler-dot');
            const isOn = data.devices.boiler.state === 'on';
            if (boilerState) boilerState.textContent = isOn ? 'ON' : 'OFF';
            if (boilerDot) boilerDot.className = 'status-dot' + (isOn ? ' on' : '');
            setTextIfExists('boiler-power', formatWatts(data.devices.boiler.power));

            // Show last heated time
            const lastHeated = formatRelativeTime(data.devices.boiler.last_heated);
            setTextIfExists('boiler-last-heated', lastHeated ? `Heated ${lastHeated}` : '');

            const boilerDevice = document.getElementById('device-boiler');
            if (boilerDevice) boilerDevice.classList.toggle('active', isOn);
        }

        // EV Charger
        if (data.devices.ev) {
            const evState = document.getElementById('ev-state');
            const evDot = document.getElementById('ev-dot');
            const stateText = getEvStateText(data.devices.ev.state);
            const isCharging = data.devices.ev.state === 132;
            if (evState) evState.textContent = stateText;
            if (evDot) evDot.className = 'status-dot' + (isCharging ? ' charging' : (data.devices.ev.state === 129 ? ' on' : ''));
            setTextIfExists('ev-power', formatWatts(data.devices.ev.power));
            setTextIfExists('ev-amps', `(${data.devices.ev.amps}A)`);

            // Show last charged time (only when EV is full)
            const lastCharged = formatRelativeTime(data.devices.ev.last_charged);
            setTextIfExists('ev-last-charged', lastCharged ? `Charged ${lastCharged}` : '');

            const evDevice = document.getElementById('device-ev');
            if (evDevice) evDevice.classList.toggle('active', isCharging);
        }

        // Pool Pump
        if (data.devices.pool_pump) {
            const poolState = document.getElementById('pool-pump-state');
            const poolDot = document.getElementById('pool-dot');
            const isOn = data.devices.pool_pump.state === 'on';
            if (poolState) poolState.textContent = isOn ? 'ON' : 'OFF';
            if (poolDot) poolDot.className = 'status-dot' + (isOn ? ' on' : '');
            setTextIfExists('pool-pump-power', formatWatts(data.devices.pool_pump.power));

            const temp = data.devices.pool_pump.ambient_temp;
            const tempEl = document.getElementById('pool-ambient-temp');
            if (tempEl && temp !== null) {
                tempEl.textContent = `${temp.toFixed(1)}°C`;
                tempEl.className = 'temp' + (temp <= 5 ? ' warning' : '');
            }

            const poolDevice = document.getElementById('device-pool');
            if (poolDevice) poolDevice.classList.toggle('active', isOn);
        }

        // Table Heater
        if (data.devices.table_heater) {
            const tableHeaterState = document.getElementById('table-heater-state');
            const tableHeaterDot = document.getElementById('table-heater-dot');
            const isOn = data.devices.table_heater.state === 'on';
            if (tableHeaterState) tableHeaterState.textContent = isOn ? 'ON' : 'OFF';
            if (tableHeaterDot) tableHeaterDot.className = 'status-dot' + (isOn ? ' on' : '');
            setTextIfExists('table-heater-power', formatWatts(data.devices.table_heater.power));

            const tableHeaterDevice = document.getElementById('device-table-heater');
            if (tableHeaterDevice) tableHeaterDevice.classList.toggle('active', isOn);
        }

        // BMW i5
        if (data.devices.bmw_i5) {
            updateCarCard('i5', data.devices.bmw_i5);
        }

        // BMW iX1
        if (data.devices.bmw_ix1) {
            updateCarCard('ix1', data.devices.bmw_ix1);
        }

        // Update schedule status dots (shows current on/off state in 24h schedule)
        updateScheduleStatusDots(data.devices, data.consumers);
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
        updateConsumers(data.consumers, data.grid_import);
    }

    // Alerts - always clear first, then build list
    const alertsSection = document.getElementById('alerts-section');
    const alertsList = document.getElementById('alerts-list');
    if (alertsList) {
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
        if (alertsSection) alertsSection.style.display = alertsHtml ? 'block' : 'none';
    }

    // Update environment-based icons (sun/moon, weather)
    if (data.environment) {
        const env = data.environment;
        const solarIcon = getSolarIcon(env);

        // Update solar node icons (both dashboard versions)
        const solarNodes = document.querySelectorAll('.power-node.solar .node-icon, .power-node-large.solar .node-icon');
        solarNodes.forEach(node => {
            node.textContent = solarIcon;
        });

        // Update solar label with forecast if night or low production
        const solarLabel = document.querySelector('.power-node.solar .node-label, .power-node-large.solar .node-label');
        if (solarLabel && env.solar_forecast_kwh > 0) {
            const pvPower = data.pv_production || 0;
            if (!env.sun_is_up || pvPower < 100) {
                solarLabel.textContent = `Solar (${env.solar_forecast_kwh.toFixed(1)}kWh left)`;
            } else {
                solarLabel.textContent = 'Solar';
            }
        }
    }

    // Last update
    if (data.last_update) {
        const date = new Date(data.last_update);
        setTextIfExists('last-update', date.toLocaleTimeString());
    }

    // Status indicator
    const statusIndicator = document.getElementById('status-indicator');
    if (statusIndicator) statusIndicator.classList.remove('disconnected');

    // Update power limits in settings
    if (data.limits) {
        updateLimits(data.limits);
    }
}

// Fetch status from API
async function fetchStatus() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/status`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        updateDashboard(data);
    } catch (error) {
        console.error('Failed to fetch status:', error);
        const statusIndicator = document.getElementById('status-indicator');
        if (statusIndicator) statusIndicator.classList.add('disconnected');
    }
}

// Set override
async function setOverride(device, mode) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/override/${device}?mode=${mode}`, {
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

        const response = await fetch(`${API_BASE_URL}/api/limits?${params.toString()}`, {
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
let refreshInterval = null;

function startPolling() {
    // Clear any existing interval
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    // Fetch immediately and start polling
    fetchStatus();
    refreshInterval = setInterval(fetchStatus, REFRESH_INTERVAL);
}

document.addEventListener('DOMContentLoaded', () => {
    startPolling();

    // Handle visibility change (for iOS/mobile apps that suspend JS in background)
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            // Page became visible again - restart polling
            startPolling();
        }
    });

    // Also handle focus for iframe scenarios
    window.addEventListener('focus', () => {
        startPolling();
    });
});
