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
