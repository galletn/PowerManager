# Power Manager - Python Service Architecture

## Overview

Standalone Python service that manages home power consumption by:
1. Polling Home Assistant API every 30 seconds
2. Making decisions based on solar production, grid consumption, and device states
3. Sending commands to control devices (boiler, EV charger, pool heat pump, etc.)
4. Serving an HTML dashboard embeddable in Home Assistant

## Architecture

```
+------------------+     REST API      +------------------+
|                  | <--------------> |                  |
|  Home Assistant  |   (92ms batch)   |  Power Manager   |
|                  |                  |  Python Service  |
+------------------+                  +------------------+
       |                                      |
       |                              +-------+-------+
       |                              |               |
       v                              v               v
  +----------+                  +---------+    +----------+
  | Devices  |                  | Decision|    | Dashboard|
  | - Boiler |                  | Engine  |    | (HTML)   |
  | - EV     |                  +---------+    +----------+
  | - Pool   |                        |              |
  | - AC     |                        v              |
  +----------+                  +---------+          |
                                | Config  |     iframe in HA
                                +---------+
```

## Project Structure

```
power-manager/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Configuration management
│   ├── ha_client.py         # Home Assistant API client
│   ├── decision_engine.py   # Core decision logic (ported from JS)
│   ├── models.py            # Pydantic models for type safety
│   └── scheduler.py         # APScheduler for 30s polling loop
│
├── dashboard/
│   ├── templates/
│   │   └── dashboard.html   # Main dashboard template
│   └── static/
│       ├── style.css
│       └── dashboard.js     # Auto-refresh, charts
│
├── tests/
│   ├── __init__.py
│   ├── test_decisions.py    # Port all 154 tests
│   ├── test_tariff.py
│   ├── test_frost.py
│   ├── test_bmw.py
│   └── conftest.py          # Pytest fixtures
│
├── config.yaml              # User configuration
├── requirements.txt
├── Dockerfile
└── README.md
```

## Components

### 1. FastAPI Application (`main.py`)

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Power Manager")

# Dashboard routes
@app.get("/")
async def dashboard():
    return templates.TemplateResponse("dashboard.html", {...})

@app.get("/api/status")
async def status():
    """Current power status for dashboard AJAX updates"""
    return {
        "grid_import": 2045,
        "grid_export": 0,
        "pv_production": 152,
        "devices": {...},
        "plan": [...],
        "last_update": "2024-12-31T15:17:00"
    }

@app.post("/api/override/{device}")
async def set_override(device: str, mode: str):
    """Manual override from dashboard"""
    pass
```

### 2. Home Assistant Client (`ha_client.py`)

```python
class HAClient:
    def __init__(self, url: str, token: str):
        self.url = url
        self.headers = {"Authorization": f"Bearer {token}"}

    async def get_all_states(self) -> dict:
        """Batch fetch all states (~92ms)"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.url}/api/states") as resp:
                return await resp.json()

    async def call_service(self, domain: str, service: str, entity_id: str):
        """Turn on/off devices"""
        pass

    async def set_number(self, entity_id: str, value: float):
        """Set EV charger amps"""
        pass
```

### 3. Decision Engine (`decision_engine.py`)

Direct port from `src/logic/decisions.js`:

```python
from dataclasses import dataclass
from enum import IntEnum

class EVState(IntEnum):
    NO_CAR = 128
    READY = 129
    FULL = 130
    CHARGING = 132

@dataclass
class PowerInputs:
    p1_power: float      # Grid import (W)
    p1_return: float     # Grid export (W)
    pv_power: float      # Solar production (W)
    boiler_switch: str   # 'on' | 'off'
    boiler_power: float
    ev_state: int
    ev_power: float
    ev_limit: int
    # ... all other inputs

@dataclass
class Decisions:
    ev: EVDecision
    boiler: DeviceDecision
    pool: DeviceDecision
    pool_pump: DeviceDecision
    # ... etc

def calculate_decisions(
    inputs: PowerInputs,
    config: Config,
    device_state: DeviceState,
    now: datetime
) -> tuple[Decisions, list[str], list[Alert]]:
    """Main decision function - direct port from JS"""
    pass
```

### 4. Dashboard (`dashboard.html`)

Modern, responsive dashboard showing:
- **Live power flow** (grid, solar, consumption)
- **Device status** with manual override buttons
- **Decision plan** (what the system is doing and why)
- **Alerts** (frost warnings, BMW low battery)
- **Charts** (24h power history from HA)

Features:
- Auto-refresh every 5 seconds via AJAX
- Embedded in HA via iframe panel
- Dark mode support
- Mobile responsive

### 5. Configuration (`config.yaml`)

```yaml
home_assistant:
  url: "https://your-ha-host:8123"
  token: "eyJ..."

polling_interval: 30  # seconds

grid:
  max_import:
    peak: 2500
    off_peak: 5000
    super_off_peak: 8000

devices:
  ev:
    min_amps: 6
    max_amps: 16
    watts_per_amp: 692
  boiler:
    power: 2500
    deadline_winter: 6.5
    deadline_summer: 8.0
  # ... etc

frost_protection:
  enabled: true
  temp_threshold: 5
  pump_min_power: 100

bmw_low_battery:
  enabled: true
  threshold: 50
  check_hours: [20, 21, 22]

notifications:
  entity: "mobile_app_your_phone"
```

## Deployment Options

### Option A: Docker on Linux server
```bash
docker run -d \
  -p 8080:8080 \
  -v ./config.yaml:/app/config.yaml \
  power-manager
```

### Option B: Systemd service
```ini
[Unit]
Description=Power Manager Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 -m app.main
WorkingDirectory=/opt/power-manager
Restart=always

[Install]
WantedBy=multi-user.target
```

### Option C: HA Add-on (future)
Package as Home Assistant add-on for easy installation.

## Home Assistant Integration

### Embedding Dashboard

Add to HA `configuration.yaml`:
```yaml
panel_iframe:
  power_manager:
    title: "Power Manager"
    icon: mdi:flash
    url: "http://localhost:8080"
```

### Helper Entities (optional)

The Python service can update HA helper entities for logging:
- `input_text.power_manager_status` - Current status text
- `input_text.power_manager_plan` - Decision plan
- `input_text.power_manager_actions` - Last actions taken

## Migration Plan

### Phase 1: Core Service
1. Create Python project structure
2. Port `decision_engine.py` from JS
3. Port tests (pytest)
4. Create HA client
5. Basic CLI to test decisions

### Phase 2: Dashboard
1. Create FastAPI web server
2. Build HTML dashboard
3. Add AJAX status endpoint
4. Add override controls

### Phase 3: Deployment
1. Create Docker setup
2. Test on Linux server
3. Add to Home Assistant as iframe

### Phase 4: Cleanup
1. Archive Node-RED flows
2. Remove node-red/ folder
3. Remove src/ (JS code)
4. Remove test/ (JS tests)
5. Update README

## Files to Remove (Legacy Cleanup)

After Python service is working:

```
DELETE:
├── node-red/           # Node-RED flows
├── src/                # JavaScript modules
├── test/               # JavaScript tests
├── scripts/            # JS update scripts
├── package.json        # Node.js deps
├── package-lock.json
├── jest.config.js
└── archive/            # Old v5 code

KEEP:
├── homeassistant/      # HA dashboard & helpers YAML
├── docs/               # Documentation
└── .github/            # CI (update for Python)
```

## API Performance (Validated)

From `test-ha-api.py`:
- **Batch fetch**: 92ms for 1356 entities
- **Individual fetch**: 54ms per entity
- **Template API**: 50ms
- **Command response**: 76ms

The HA API is fast enough for 30-second polling with plenty of margin.

---

## Decision Logic Reference

This section documents when each device is allowed to run, organized by tariff period and season.

---

## Detailed Decision Flow (`calculate_decisions()`)

This section documents the exact step-by-step execution flow of the decision engine, with all calculations and conditions.

### Step 1: Initialize Context

```python
# Get current time
now = datetime.now()
now_ts = now.timestamp() * 1000  # milliseconds for JS compatibility

# Determine tariff and limits
tariff, tariff_info = get_tariff(now)  # 'peak', 'off-peak', 'super-off-peak'
max_import = get_max_import(tariff, config, now)  # Uses winter/summer limits
summer = is_summer(now)  # True if month 3-10 (March-October)

# Calculate power values
p1 = inputs.p1_power or 0          # Grid import (W)
p1_return = inputs.p1_return or 0  # Grid export (W)
pv = inputs.pv_power or 0          # Solar production (W)

# Net power calculation
net_p1 = p1 - p1_return  # Positive = importing, negative = exporting
avail = max_import - net_p1  # Available headroom
is_exporting = p1_return > p1
```

### Step 2: Parse Device States

```python
# EV States
ev_state = inputs.ev_state
ev_limit = inputs.ev_limit  # Current amp limit
ev_power = inputs.ev_power

# EV plugged check (multiple states indicate plugged)
ev_plugged = ev_state in (
    READY=129, CHARGING=132, FULL=130,
    OCPP_PREPARING=2, OCPP_CHARGING=3,
    OCPP_SUSPENDED_EV=4, OCPP_SUSPENDED_EVSE=5, OCPP_FINISHING=6
)
ev_ready = ev_state in (READY=129, OCPP_PREPARING=2)
ev_charging = ev_state in (CHARGING=132, OCPP_CHARGING=3) OR ev_power > 500
ev_done = ev_state in (FULL=130, OCPP_FINISHING=6)

# Boiler state
boiler_on = inputs.boiler_switch == 'on'
boiler_power = inputs.boiler_power
boiler_force = inputs.boiler_force == 'on'

# Boiler full detection (requires sustained low power)
boiler_full = is_boiler_full(
    boiler_on=boiler_on,
    boiler_power=boiler_power,
    idle_threshold=50,  # config.boiler.idle_threshold
    confirm_seconds=120  # config.boiler.full_confirm_seconds
)

# Table heater state
ht_on = inputs.heater_table_switch == 'on'

# Dishwasher state
dw_switch_on = inputs.dishwasher_switch == 'on'
dw_power = inputs.dishwasher_power
dw_running = dw_power > 50  # Actually running a cycle
dw_waiting = dw_switch_on and dw_power < 50  # Switch on but waiting
```

### Step 3: Parse Overrides

```python
ovr = {
    'ev': parse_override(inputs.ovr_ev),        # 'auto', 'on', or 'off'
    'boiler': parse_override(inputs.ovr_boiler),
    'pool': parse_override(inputs.ovr_pool),
    'table_heater': parse_override(inputs.ovr_table_heater),
    'dishwasher': parse_override(inputs.ovr_dishwasher),
}

# parse_override() converts:
#   '', 'auto', 'automatic' -> 'auto'
#   'on', 'aan', 'force_on' -> 'on'
#   'off', 'uit', 'force_off' -> 'off'
```

### Step 4: Hysteresis Check Function

```python
def can_switch(device_name, target_on):
    """Check if device can be switched (respecting min on/off times)"""
    device_state = getattr(device_state, device_name)
    elapsed_ms = now_ts - device_state.last_change

    if device_state.on and not target_on:
        # Turning OFF: must have been on for min_on_time (300s = 5min)
        return elapsed_ms >= (300 * 1000)
    elif not device_state.on and target_on:
        # Turning ON: must have been off for min_off_time (180s = 3min)
        return elapsed_ms >= (180 * 1000)
    return True
```

### Step 5: Apply Manual Overrides (FIRST)

```python
# These override everything else!
if ovr['ev'] == 'on' and ev_plugged:
    decisions.ev.action = 'on'
    decisions.ev.amps = 16  # max_amps
elif ovr['ev'] == 'off':
    decisions.ev.action = 'off'

if ovr['boiler'] == 'on':
    decisions.boiler.action = 'on'
elif ovr['boiler'] == 'off':
    decisions.boiler.action = 'off'

if ovr['table_heater'] == 'on':
    decisions.heater_table.action = 'on'
elif ovr['table_heater'] == 'off':
    decisions.heater_table.action = 'off'

# Force boiler (via input_boolean.force_heat_boiler)
if boiler_force and not boiler_full and ovr['boiler'] == 'auto':
    decisions.boiler.action = 'on'
```

### Step 6: Check Frost Protection (Priority 1)

```python
if frost_protection.enabled and pool_ambient_temp is not None:
    if pool_ambient_temp <= 5.0:  # temp_threshold
        pump_actually_running = (pump_switch == 'on' and pump_power >= 100)

        if not pump_actually_running:
            # FORCE PUMP ON
            decisions.pool_pump.action = 'on'

            # Check if we should alert
            pump_off_duration = now_ts - device_state.pool_pump.last_change
            if pump_off_duration >= 300000:  # 5 min in ms
                if pool_ambient_temp <= 2.0:
                    # CRITICAL ALERT
                    alerts.append(Alert(level='critical', message='...'))
                else:
                    # WARNING ALERT
                    alerts.append(Alert(level='warning', message='...'))
```

### Step 7: Check BMW Low Battery

```python
if bmw_low_battery.enabled and now.hour in [20, 21, 22]:
    if bmw_i5_battery < 50 and bmw_i5_location == 'home' and not ev_plugged:
        alerts.append(Alert(level='warning', message=f'BMW i5 at {battery}%...'))

    # Same for iX1...
```

### Step 8: Check Boiler Deadline

```python
# Track heating time throughout the night (22:00 to deadline)
if is_heating:
    device_state.boiler_heating_tonight_seconds += 30  # polling_interval

heating_minutes = device_state.boiler_heating_tonight_seconds / 60
min_heating_minutes = 60  # Need at least 1 hour

# Warning: 1 hour before deadline (e.g., 05:30 for 06:30 deadline)
if current_hour >= (deadline - 1) and heating_minutes < 60:
    alerts.append(Alert(level='warning', message='...'))

# Critical: at/past deadline
if current_hour >= deadline and heating_minutes < 60:
    alerts.append(Alert(level='critical', message='...'))
```

### Step 9: Seasonal Logic Branch

```python
if not summer:
    _apply_winter_logic(...)
else:
    _apply_summer_logic(...)
```

---

## Winter Logic Detail (`_apply_winter_logic`)

### Step 9a: Handle Boiler (Priority 2)

```python
def _handle_boiler_winter(decisions, plan, ctx, effective_headroom):
    """
    Returns: (boiler_will_use, updated_headroom)
    """
    hour = now.hour + now.minute / 60
    deadline = 6.5  # config.boiler.deadline_winter

    # Skip if override already set
    if ovr['boiler'] != 'auto':
        return 0, effective_headroom

    # Force heat overrides tariff logic
    if boiler_force and not boiler_full:
        if not boiler_on:
            if can_switch('boiler', True):
                decisions.boiler.action = 'on'
                return 2500, effective_headroom - 2500
        else:
            return 2500, effective_headroom - 2500

    # Peak tariff: turn OFF (unless force heat or approaching deadline)
    if tariff == 'peak' and boiler_on and not boiler_force:
        if hour > deadline and can_switch('boiler', False):
            decisions.boiler.action = 'off'
        return 0, effective_headroom

    # Check if boiler should heat
    if not boiler_full:
        approaching_deadline = (hour >= deadline - 2) and (hour < deadline)
        enough_power = effective_headroom > 2500 + 300  # boiler.power + hyst
        has_solar_surplus = is_exporting and p1_return > 500  # MIN_EXPORT_FOR_BOILER

        wants_to_heat = False
        reason = ""

        if tariff == 'super-off-peak':
            wants_to_heat = True
            reason = "super-off-peak"
        elif has_solar_surplus:
            wants_to_heat = True
            reason = f"solar ({p1_return}W export)"
        elif approaching_deadline and tariff in ('off-peak', 'super-off-peak'):
            wants_to_heat = True
            reason = "approaching deadline"

        # BOILER HAS PRIORITY - turn on even if not enough headroom
        # (other devices will be shed later)
        if wants_to_heat and not boiler_on:
            if can_switch('boiler', True):
                decisions.boiler.action = 'on'
                if not enough_power:
                    plan.append(f"Boiler: ON ({reason}, shedding load)")
                else:
                    plan.append(f"Boiler: ON ({reason})")
                return 2500, effective_headroom - 2500
        elif boiler_on:
            return 2500, effective_headroom - 2500
    else:
        # Boiler is full
        plan.append("Boiler: FULL")

    return 0, effective_headroom
```

### Step 9b: Handle EV Charging (Priority 3)

```python
def _handle_ev_winter(decisions, plan, ctx, effective_headroom, boiler_will_use):
    """
    Returns: updated_effective_headroom
    """
    # Skip if override, not plugged, or already full
    if ovr['ev'] != 'auto' or not ev_plugged or ev_done:
        return effective_headroom

    # Current EV power (if charging)
    current_ev_watts = ev_limit * 692 if ev_charging else 0

    # === SUPER OFF-PEAK (01:00-07:00) ===
    if tariff == 'super-off-peak':
        # Calculate target amps
        total_for_ev = effective_headroom + current_ev_watts - 300  # hyst
        available_amps = int(total_for_ev / 692)  # watts_per_amp
        target_amps = max(6, min(available_amps, 16))  # clamp to 6-16A

        if ev_charging:
            # Adjust if amp difference >= 2
            if abs(target_amps - ev_limit) >= 2:
                decisions.ev.action = 'adjust'
                decisions.ev.amps = target_amps
        elif ev_ready and target_amps >= 6:
            if can_switch('ev', True):
                decisions.ev.action = 'on'
                decisions.ev.amps = target_amps
                effective_headroom -= target_amps * 692

    # === OFF-PEAK ===
    elif tariff == 'off-peak':
        current_hour = now.hour + now.minute / 60
        ev_hours_needed = ctx.get('ev_hours_needed', 0)  # From calculate_ev_hours_needed()
        super_off_peak_hours = 6.0  # 01:00 to 07:00

        # Only start during off-peak if we need MORE than 6 hours
        must_start_now = ev_hours_needed > super_off_peak_hours

        if ev_charging:
            if must_start_now and boiler_will_use == 0 and not boiler_on:
                # Continue charging (needs >6h, boiler not running)
                # ... adjust amps as above
            elif boiler_will_use > 0 or boiler_on:
                # STOP - boiler has priority
                if can_switch('ev', False):
                    decisions.ev.action = 'off'
                    plan.append("EV: PAUSE (boiler priority)")
            else:
                # STOP - wait for super-off-peak (cheaper!)
                if can_switch('ev', False):
                    decisions.ev.action = 'off'
                    plan.append("EV: STOP (wait for super-off-peak)")
        elif ev_ready and must_start_now and boiler_will_use == 0:
            # Start charging (needs >6h, boiler not running)
            if can_switch('ev', True):
                decisions.ev.action = 'on'
                decisions.ev.amps = calculated_amps
                effective_headroom -= calculated_amps * 692
        elif ev_ready:
            # Don't start - wait for super-off-peak
            plan.append("EV: WAIT for super-off-peak")

    # === PEAK ===
    elif tariff == 'peak' and ev_charging:
        if can_switch('ev', False):
            decisions.ev.action = 'off'
            plan.append("EV: STOP (peak tariff)")

    return effective_headroom
```

### Step 9c: Handle Table Heater (Priority 5)

```python
def _handle_heater_winter(decisions, plan, ctx, effective_headroom):
    # Skip if override
    if ovr['table_heater'] != 'auto':
        return

    table_power = 4100  # config.heaters.table_power

    # Calculate remaining capacity (subtract EV if charging)
    remaining = effective_headroom
    if ev_charging and decisions.ev.action == 'none':
        remaining -= ev_limit * 692

    enough_power = remaining > table_power + 300  # hyst

    # === SUPER OFF-PEAK ===
    if tariff == 'super-off-peak':
        if not ht_on and enough_power:
            if can_switch('heater_table', True):
                decisions.heater_table.action = 'on'
                plan.append("Table heater: ON (super-off-peak)")
        elif ht_on and remaining < table_power - 300:
            # Not enough capacity - turn OFF
            if can_switch('heater_table', False):
                decisions.heater_table.action = 'off'
                plan.append("Table heater: OFF (capacity needed)")

    # === OFF-PEAK ===
    elif tariff == 'off-peak':
        # ALWAYS turn OFF during off-peak - wait for super-off-peak
        if ht_on:
            if can_switch('heater_table', False):
                decisions.heater_table.action = 'off'
                plan.append("Table heater: OFF (wait for super-off-peak)")

    # === PEAK ===
    elif tariff == 'peak' and ht_on:
        if can_switch('heater_table', False):
            decisions.heater_table.action = 'off'
            plan.append("Table heater: OFF (peak tariff)")
```

### Step 9d: Handle Dishwasher (Priority 4)

```python
def _apply_dishwasher_logic(decisions, plan, ctx):
    # Skip if override
    if ovr.get('dishwasher') != 'auto':
        return

    # NEVER interrupt a running cycle!
    if dw_running:  # power > 50W
        plan.append(f"Dishwasher: RUNNING ({dw_power}W)")
        return

    # Nothing to do if not waiting
    if not dw_switch_on:
        return

    # Dishwasher is waiting to run
    if dw_waiting:
        has_solar_surplus = is_exporting and p1_return > 500
        is_cheap_tariff = tariff in ('off-peak', 'super-off-peak')
        available_power = headroom - 300  # hyst
        has_enough_power = available_power > 1900  # DW_EXPECTED_POWER

        if has_solar_surplus:
            decisions.dishwasher.action = 'on'
            plan.append(f"Dishwasher: RUN (solar surplus {p1_return}W)")
        elif is_cheap_tariff and has_enough_power:
            decisions.dishwasher.action = 'on'
            plan.append(f"Dishwasher: RUN ({tariff})")
        elif is_cheap_tariff and not has_enough_power:
            decisions.dishwasher.action = 'none'  # Keep waiting
            plan.append(f"Dishwasher: WAITING (need 1900W, have {available_power}W)")
        else:
            # Peak rate, no solar - wait
            decisions.dishwasher.action = 'none'
            plan.append(f"Dishwasher: WAITING (off-peak in Xh)")
```

---

## Summer Logic Detail (`_apply_summer_logic`)

### EV Solar Charging

```python
if ovr['ev'] == 'auto' and ev_plugged and not ev_done:
    # Good solar: exporting OR importing less than 1000W with PV > 1500W
    has_good_solar = pv > 1500 and (is_exporting or p1 < 1000)

    if has_good_solar:
        if is_exporting:
            # Use all export + 1000W import buffer
            available_power = p1_return + 1000
        else:
            # Already importing but under threshold
            available_power = 1000 - p1

        # Add back current EV consumption for calculation
        current_ev_watts = ev_limit * 692 if ev_charging else 0
        total_for_ev = available_power + current_ev_watts - 300

        available_amps = int(total_for_ev / 692)
        target_amps = max(6, min(available_amps, 16))

        if ev_ready and target_amps >= 6:
            if can_switch('ev', True):
                decisions.ev.action = 'on'
                decisions.ev.amps = target_amps
        elif ev_charging:
            if abs(target_amps - ev_limit) >= 2:
                if target_amps >= 6:
                    decisions.ev.action = 'adjust'
                    decisions.ev.amps = target_amps
                else:
                    decisions.ev.action = 'off'

    elif ev_charging and p1 > 1000:  # Importing too much
        if can_switch('ev', False):
            decisions.ev.action = 'off'
```

### Boiler Solar Heating

```python
if ovr['boiler'] == 'auto' and not boiler_full:
    if is_exporting and pv > 2500:  # boiler.power
        if not boiler_on and can_switch('boiler', True):
            decisions.boiler.action = 'on'
            plan.append("Boiler: ON (solar surplus)")
    elif boiler_on and not is_exporting:
        if can_switch('boiler', False):
            decisions.boiler.action = 'off'
            plan.append("Boiler: OFF (no surplus)")
```

---

## Step 10: Calculate Final Headroom

```python
def _calculate_final_headroom(avail, decisions, config, current_states):
    headroom = avail  # Start with available capacity

    # Subtract EV power
    if decisions.ev.action in ('on', 'adjust'):
        headroom -= decisions.ev.amps * 692
    elif current_states.get('ev_charging'):
        headroom -= current_states['ev_limit'] * 692

    # Subtract boiler power
    if decisions.boiler.action == 'on' or (
        decisions.boiler.action == 'none' and current_states.get('boiler_on')
    ):
        headroom -= 2500

    # Subtract table heater power
    if decisions.heater_table.action == 'on' or (
        decisions.heater_table.action == 'none' and current_states.get('ht_on')
    ):
        headroom -= 4100

    return headroom
```

---

## Boiler Full Detection Algorithm

```python
def is_boiler_full(boiler_on, boiler_power, idle_threshold, device_state, now_ts, confirm_seconds):
    """
    Boiler is "full" when power stays below idle_threshold for confirm_seconds.
    This prevents false positives from momentary sensor glitches.
    """
    if not boiler_on:
        device_state.boiler_low_power_since = 0.0
        return False

    power_is_low = boiler_power < idle_threshold  # 50W default

    if power_is_low:
        if device_state.boiler_low_power_since == 0.0:
            # Just dropped below threshold - start tracking
            device_state.boiler_low_power_since = now_ts
            return False
        else:
            # Already tracking - check duration
            elapsed_seconds = (now_ts - device_state.boiler_low_power_since) / 1000
            return elapsed_seconds >= confirm_seconds  # 120s default
    else:
        # Power above threshold - reset tracking
        device_state.boiler_low_power_since = 0.0
        return False
```

---

## EV Hours Needed Calculation

```python
def calculate_ev_hours_needed(inputs, config):
    """
    Calculate hours needed for EV to reach 80% SoC.
    Used to decide if EV should start during off-peak (needs >6h)
    or can wait for super-off-peak (needs ≤6h).
    """
    # Determine which car is at home
    if bmw_i5_location == 'home' and bmw_i5_battery is not None:
        car_battery = bmw_i5_battery
        car_capacity = 84  # kWh (BMW i5)
    elif bmw_ix1_location == 'home' and bmw_ix1_battery is not None:
        car_battery = bmw_ix1_battery
        car_capacity = 65  # kWh (BMW iX1)
    else:
        return 0.0

    if car_battery >= 80:
        return 0.0  # Already at target

    # kWh needed to reach 80%
    kwh_needed = (80 - car_battery) / 100 * car_capacity

    # Effective charging power (limited by grid)
    charger_max_kw = 16 * 692 / 1000  # max_amps * watts_per_amp
    grid_limit_kw = 9000 / 1000  # Winter super-off-peak limit
    effective_charging_kw = min(charger_max_kw, grid_limit_kw - 0.5)  # buffer

    hours_needed = kwh_needed / effective_charging_kw
    return round(hours_needed, 1)
```

---

### Tariff Periods (Belgian Electricity)

| Tariff | Weekday Hours | Weekend Hours | Power Limit (Summer) | Power Limit (Winter) |
|--------|---------------|---------------|----------------------|----------------------|
| **Peak** | 07:00-11:00, 17:00-22:00 | - | 2,500W | 2,500W |
| **Off-Peak** | 00:00-01:00, 11:00-17:00, 22:00-24:00 | 00:00-01:00, 07:00-11:00, 17:00-24:00 | 5,000W | 5,000W |
| **Super Off-Peak** | 01:00-07:00 | 01:00-07:00, 11:00-17:00 | 8,000W | **9,000W** |

> **Winter** = November through February (months 11, 12, 1, 2)
> **Summer** = March through October (months 3-10)

### Device Power Consumption

| Device | Power | Notes |
|--------|-------|-------|
| Boiler | 2,500W | Fixed when heating |
| EV Charger | 4,152W - 11,072W | 6A-16A × 692W per amp |
| Table Heater | 4,100W | Fixed |
| Pool Pump | ~100-200W | Must run for frost protection |
| Dishwasher | ~1,900W | Peak during heating |

### Device Priority Order

When capacity is limited, devices are controlled in this priority order:

1. **Frost Protection** (Pool Pump) - Safety critical, always runs when temp < 5°C
2. **Boiler** - Hot water needed by morning deadline
3. **EV Charger** - Charge to 80% by 07:00
4. **Dishwasher** - Runs during cheap rates when waiting
5. **Table Heater** - Lowest priority, uses leftover capacity

---

## Winter Decision Logic

### Boiler (Priority 1)

| Tariff | Condition | Action | Reason |
|--------|-----------|--------|--------|
| **Super Off-Peak** | Not full | **ON** | Cheapest rate, heat now |
| **Super Off-Peak** | Full (power < 50W for 2min) | OFF | Already hot |
| **Off-Peak** | Not full AND approaching deadline (within 2h) | **ON** | Need hot water |
| **Off-Peak** | Not full AND not approaching deadline | OFF | Wait for super-off-peak |
| **Peak** | Always | OFF | Too expensive |
| **Any** | Solar export > 500W | **ON** | Free solar power |
| **Any** | Override = 'on' | **ON** | Manual override |
| **Any** | Override = 'off' | OFF | Manual override |

**Boiler Full Detection**: Power must stay below 50W for 120 seconds continuously.

### EV Charger (Priority 2)

| Tariff | Condition | Action | Reason |
|--------|-----------|--------|--------|
| **Super Off-Peak** | Plugged, not full, headroom available | **ON** at calculated amps | Cheapest rate |
| **Super Off-Peak** | Charging, headroom changes | **ADJUST** amps | Optimize power usage |
| **Off-Peak** | Needs >6h to reach 80% | **ON** | Must start early |
| **Off-Peak** | Needs ≤6h to reach 80% | OFF | Wait for super-off-peak |
| **Off-Peak** | Charging but boiler needs power | **OFF** | Boiler priority |
| **Peak** | Charging | **OFF** | Too expensive |
| **Any** | Battery ≥80% or Full state | OFF | Target reached |
| **Any** | Override = 'on' | **ON** | Manual override |
| **Any** | Override = 'off' | OFF | Manual override |

**EV Amp Calculation**:
```
available_watts = grid_limit - current_import - hysteresis
amps = min(max_amps, max(min_amps, available_watts / 692))
```

**EV + Boiler Together** (Winter Super Off-Peak at 9kW):
```
EV power = 9000W - 2500W (boiler) - 500W (buffer) = 6000W ≈ 8-9A
```

### Table Heater (Priority 5)

| Tariff | Condition | Action | Reason |
|--------|-----------|--------|--------|
| **Super Off-Peak** | Headroom > 4,100W + hysteresis | **ON** | Cheap rate, capacity available |
| **Super Off-Peak** | Headroom < 4,100W - hysteresis | **OFF** | Need capacity for boiler/EV |
| **Off-Peak** | Always | **OFF** | Wait for super-off-peak |
| **Peak** | Always | **OFF** | Too expensive |
| **Any** | Override = 'on' | **ON** | Manual override |
| **Any** | Override = 'off' | OFF | Manual override |

### Dishwasher (Priority 4)

| Tariff | Condition | Action | Reason |
|--------|-----------|--------|--------|
| **Any** | Currently running (power > 50W) | **NEVER INTERRUPT** | Cycle in progress |
| **Super Off-Peak / Off-Peak** | Switch on, waiting, headroom > 1,900W | **ON** | Start cycle |
| **Super Off-Peak / Off-Peak** | Switch on, waiting, headroom < 1,900W | WAIT | Not enough capacity |
| **Peak** | Switch on, waiting | WAIT | Too expensive |
| **Any** | Solar export > 500W | **ON** | Free solar power |

---

## Summer Decision Logic

### Boiler

| Condition | Action | Reason |
|-----------|--------|--------|
| Solar export > 500W | **ON** | Use free solar |
| No solar, not full, approaching deadline | **ON** during off-peak | Need hot water |
| No solar, not approaching deadline | OFF | Wait for solar |

### EV Charger

| Condition | Action | Reason |
|-----------|--------|--------|
| PV > 1,500W AND (exporting OR import < 1,000W) | **ON** at calculated amps | Solar charging |
| PV < 1,500W | OFF | Not enough solar |
| Import > 1,000W while charging | **ADJUST** down or OFF | Minimize grid use |

### Table Heater

Not used in summer (heating not needed).

---

## Scheduling Algorithm (24-Hour Plan)

The scheduler creates a 24-hour plan showing when devices will run:

### Slot Creation
1. Create 30-minute slots for next 24 hours
2. Each slot has: tariff, power limit, devices list

### Device Scheduling Order
1. **Pool Pump** (priority 1) - Always running in winter
2. **Boiler** (priority 2) - Schedule 2.5 hours during super-off-peak
3. **EV** (priority 3) - Schedule based on kWh needed
4. **Table Heater** (priority 10) - Fill leftover capacity

### Capacity Check
```python
def can_add(slot, device_power):
    return slot.remaining_capacity >= device_power
```

### EV Power in Schedule
When EV and boiler both need scheduling:
```
ev_power = winter_limit - boiler_power - buffer
         = 9000W - 2500W - 500W = 6000W
```

This allows both to start at 01:00 together.

---

## Override Behavior

Overrides are set via Home Assistant input_select entities:

| Override Value | Behavior |
|---------------|----------|
| `Auto` / `` (empty) | Normal decision logic |
| `On` / `on` / `ON` | Force device ON, ignore tariff/capacity |
| `Off` / `off` / `OFF` | Force device OFF, ignore all conditions |

Override entities:
- `input_select.pm_override_boiler`
- `input_select.pm_override_ev`
- `input_select.pm_override_pool`
- `input_select.pm_override_table_heater`
- `input_select.pm_override_dishwasher`

---

## Hysteresis and Timing

To prevent rapid on/off cycling:

| Setting | Default | Purpose |
|---------|---------|---------|
| `timing.hysteresis` | 300W | Power buffer for decisions |
| `timing.min_on_time` | 300s (5min) | Minimum time device stays on |
| `timing.min_off_time` | 180s (3min) | Minimum time device stays off |
| `boiler.full_confirm_seconds` | 120s | Time at low power to confirm "full" |
| `ev.amp_change_threshold` | 2A | Minimum amp change to trigger adjust |

---

## Frost Protection

**Always Active** when `pool_ambient_temp < 5°C`:

| Condition | Action |
|-----------|--------|
| Temp < 5°C, pump off | **Turn pump ON** + Warning alert |
| Temp < 5°C, pump on but power < 100W | **Critical alert** (pump failure?) |
| Temp < 2°C | **Critical alert** (freeze risk) |
| Temp ≥ 5°C | Normal operation |

---

## Alerts

| Alert | Level | Condition |
|-------|-------|-----------|
| Frost Protection | Warning/Critical | Pool temp < 5°C |
| BMW Low Battery | Warning | Battery < 50%, at home, not plugged, evening hours |
| Boiler Deadline | Warning | <1h to deadline, <60min heating tonight |
| Boiler Deadline | Critical | Past deadline, <60min heating tonight |
| Command Retry Failed | Warning | Device command failed after retries |

---

## Common Issues Checklist

### Device running when it shouldn't

1. Check override in Home Assistant (`input_select.pm_override_*`)
2. Check current tariff (is it really off-peak or super-off-peak?)
3. Check power reading (is the device actually drawing power?)
4. Check hysteresis timing (recently changed state?)

### Device not running when it should

1. Check override (is it set to OFF?)
2. Check headroom (enough capacity available?)
3. Check device state (EV: is car plugged? Boiler: is it full?)
4. Check hysteresis (min_off_time not elapsed?)

### Schedule doesn't match reality

1. Schedule is a **plan**, real-time decisions may differ
2. Decision engine re-evaluates every 30 seconds
3. Actual conditions (power, state) override the schedule

### Power exceeds limit

1. Check if multiple high-power devices turned on simultaneously
2. Check hysteresis delays (devices may overlap briefly)
3. Check if boiler "full" detection is working
