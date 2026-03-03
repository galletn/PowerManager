# CLAUDE.md - Project Context for AI Assistants

## Project Overview

Power Manager is an intelligent home energy management system for Home Assistant. It optimizes power consumption by controlling devices based on solar production, Belgian electricity tariffs, and consumption patterns.

## Deployment

Power Manager runs as a **Home Assistant add-on** with ingress support. The dashboard is accessible from the HA sidebar (locally and remotely).

| Property | Value |
|----------|-------|
| Add-on slug | `power_manager` |
| Ingress port | `8099` |
| HA URL | Set via environment/config |
| HA API | Via Supervisor internal API (`http://supervisor/core`) |
| Token | Automatic via `SUPERVISOR_TOKEN` |

### Updating the Add-on

The add-on Dockerfile clones from GitHub at build time. To deploy changes:

1. Push changes to `https://github.com/galletn/PowerManager.git` (private repo - temporarily make public for builds)
2. In HA: Settings > Add-ons > Power Manager > Rebuild
3. Set repo back to private after rebuild

### Add-on Logs

View in HA UI: Settings > Add-ons > Power Manager > Log tab

## Git Repository

- **Repository**: https://github.com/galletn/PowerManager.git (private)
- **Branch**: `main`
- **Visibility**: Private - must be temporarily set public for HA add-on rebuilds

## Home Assistant Connection

The add-on connects to HA via the Supervisor internal API. No manual token configuration needed.

### Key Entities

**Power Sensors**:
- `sensor.electricity_currently_delivered` - P1 meter import (kW)
- `sensor.electricity_currently_returned` - P1 meter export (kW)
- `sensor.solaredge_i1_ac_power` - Solar PV production (W)

**Controlled Devices**:
- `switch.storage_boiler` - Water heater (2.5kW)
- `sensor.storage_boiler_power` - Boiler power consumption
- `switch.abb_terra_ac_charging` - EV charger on/off
- `sensor.abb_terra_ac_active_power` - EV charger power consumption
- `number.abb_terra_ac_current_limit` - EV charger amps (6-16A)
- `sensor.abb_terra_ac_charging_state` - EV charger state
- `switch.poolhouse_pool_pump` - Pool pump (frost protection)
- `sensor.poolhouse_pool_pump_power` - Pool pump power consumption
- `switch.livingroom_table_heater_state` - Table heater (4.1kW)
- `sensor.livingroom_table_heater_power` - Table heater power consumption

**Appliances** (smart scheduling and power tracking):
- `switch.kitchen_dishwasher` - Dishwasher on/off (smart scheduled)
- `sensor.kitchen_dishwasher_power` - Dishwasher power consumption
- `sensor.garage_washing_machine_power` - Washing machine power (informational)
- `sensor.garage_tumble_dryer_power` - Tumble dryer power (informational)

**Override Helpers** (set via HA UI or API):
- `input_select.pm_override_boiler` - Auto/On/Off
- `input_select.pm_override_ev` - Auto/On/Off
- `input_select.pm_override_pool` - Auto/On/Off
- `input_select.pm_override_ac_living` - Auto/On/Off
- `input_select.pm_override_ac_slaapkamer` - Auto/On/Off
- `input_select.pm_override_ac_bureau` - Auto/On/Off
- `input_select.pm_override_ac_mancave` - Auto/On/Off

## Power Limits (Belgian Tariffs)

**Weekday Schedule**:

| Tariff         | Hours                                  | Max Import |
|----------------|----------------------------------------|------------|
| Peak           | 07:00-11:00, 17:00-22:00               | 2500W      |
| Off-Peak       | 00:00-01:00, 11:00-17:00, 22:00-24:00  | 5000W      |
| Super Off-Peak | 01:00-07:00                            | 8000W      |

**Weekend Schedule**:

| Tariff         | Hours                                  | Max Import |
|----------------|----------------------------------------|------------|
| Off-Peak       | 00:00-01:00, 07:00-11:00, 17:00-24:00  | 5000W      |
| Super Off-Peak | 01:00-07:00, 11:00-17:00               | 8000W      |

## Project Structure

```
PowerManager/
├── app/
│   ├── main.py              # FastAPI application + decision loop
│   ├── config.py            # Configuration dataclasses
│   ├── models.py            # Pydantic models
│   ├── ha_client.py         # Home Assistant REST API client
│   ├── decision_engine.py   # Core decision logic (winter/summer)
│   ├── scheduler.py         # 24-hour schedule generator
│   └── tariff.py            # Belgian tariff calculations
├── dashboard/
│   ├── templates/dashboard.html
│   └── static/
│       ├── style.css
│       └── dashboard.js     # Supports standalone mode via window.POWER_MANAGER_API
├── power-manager-addon/     # HA add-on packaging
│   ├── config.yaml          # Add-on manifest (ingress, panel config)
│   ├── Dockerfile           # Builds from python:3.12-alpine, clones repo
│   ├── build.yaml           # Base image per architecture
│   ├── run.sh               # Entry point (sets HA_URL, HA_TOKEN, PORT)
│   └── dashboard-ingress.html # Dashboard with relative URLs for ingress
├── repository.yaml          # HA add-on repository metadata
├── tests/                   # Pytest tests
├── homeassistant/
│   └── helpers/helpers.yaml # HA input_select entities
└── requirements.txt
```

## Running Locally (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Create config
cp config.yaml.example config.yaml
# Edit config.yaml with HA token

# Run tests
pytest tests/ -v

# Run application
python -m app.main
```

## Dashboard Access

- **HA Sidebar**: Power Manager panel (ingress, works remotely)
- **Local dev**: http://localhost:8081

## Solar Surplus & Ping-Pong Protection

Devices can turn ON opportunistically when there's solar surplus (exporting to grid). To prevent rapid ON/OFF cycling when solar output fluctuates, the system implements multiple protection mechanisms.

### Solar Surplus Detection

A device is eligible for solar surplus activation when:
- Grid is exporting power (`p1_return > 0`)
- Export exceeds device-specific threshold (e.g., `MIN_EXPORT_FOR_BOILER = 500W`)

### Grace Period (Turning OFF)

When a device is ON due to solar surplus and the surplus disappears:
- System starts tracking import time (`*_importing_since` timestamp)
- Device stays ON for a **5-minute grace period** (`SOLAR_SURPLUS_GRACE_PERIOD = 300`)
- If solar surplus returns within grace period, the timer resets
- After 5 minutes of sustained import, device turns OFF
- Dashboard shows countdown: `"Boiler: HEATING (2000W, grace 180s)"`

### Hysteresis (Rapid Cycling Prevention)

Additional protection via `config.yaml` hysteresis settings:

| Setting | Value | Description |
|---------|-------|-------------|
| `min_on_time` | 300s (5 min) | Device must stay ON before it can turn OFF |
| `min_off_time` | 180s (3 min) | Device must stay OFF before it can turn ON |

### Combined Protection Table

| Transition | Protection | Duration |
|------------|------------|----------|
| ON → OFF | Grace period | 5 minutes of sustained import |
| OFF → ON | Hysteresis | 3 minutes minimum off time |
| Stay ON | Hysteresis | 5 minutes minimum on time |

### State Tracking Fields

In `app/models.py`, `AllDeviceStates` tracks:
```python
# When device turned ON due to solar surplus
boiler_solar_surplus_since: float = 0.0
dishwasher_solar_surplus_since: float = 0.0
heater_right_solar_surplus_since: float = 0.0
heater_table_solar_surplus_since: float = 0.0

# When device started importing (no surplus) while ON
boiler_importing_since: float = 0.0
dishwasher_importing_since: float = 0.0
heater_right_importing_since: float = 0.0
heater_table_importing_since: float = 0.0
```

## Notes

- The application uses no database - all state comes from Home Assistant
- Decisions are made every 30 seconds (configurable via `polling_interval`)
- Priority order: Frost Protection > Boiler > EV Charger > Table Heater
- During off-peak: EV only charges if boiler is not needed
- During super-off-peak: Both boiler and EV can run together
