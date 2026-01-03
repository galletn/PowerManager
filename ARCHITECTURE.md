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
  url: "https://gallet.duckdns.org:8123"
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
  entity: "mobile_app_iphone_van_nicolas_2"
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
