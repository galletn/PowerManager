# CLAUDE.md - Project Context for AI Assistants

## Project Overview

Power Manager is an intelligent home energy management system for Home Assistant. It optimizes power consumption by controlling devices based on solar production, Belgian electricity tariffs, and consumption patterns.

## Git Repository

- **Repository**: https://github.com/galletn/PowerManager.git
- **Branch**: `main`
- **Clone**: `git clone https://github.com/galletn/PowerManager.git`

## Server Deployment

### Connection Details

| Property | Value |
|----------|-------|
| Server IP | `192.168.68.78` |
| User | `nicolas` |
| App Path | `/opt/PowerManager` |
| Service | `power-manager.service` |
| Dashboard Port | `8081` |

**Note**: The default port is 8081. To change the port, modify the `port` parameter in `app/main.py` in the `uvicorn.run()` call.

### SSH Authentication

The server uses SSH key authentication with passwordless sudo for service management:

```bash
# SSH key location (Windows)
C:\Users\galletn\.ssh\id_ed25519

# Connect to server
ssh nicolas@192.168.68.78

# Deploy latest changes and restart (passwordless)
ssh nicolas@192.168.68.78 "cd /opt/PowerManager && git pull && sudo systemctl restart power-manager"

# Check service status
ssh nicolas@192.168.68.78 "systemctl status power-manager"

# View logs
ssh nicolas@192.168.68.78 "journalctl -u power-manager -f"
```

### Sudoers Configuration

Passwordless sudo is configured for power-manager service commands in `/etc/sudoers.d/power-manager`:

```text
nicolas ALL=(ALL) NOPASSWD: /bin/systemctl restart power-manager, /bin/systemctl stop power-manager, /bin/systemctl start power-manager, /bin/systemctl status power-manager
```

To set this up on a new server:

```bash
sudo bash -c 'echo "nicolas ALL=(ALL) NOPASSWD: /bin/systemctl restart power-manager, /bin/systemctl stop power-manager, /bin/systemctl start power-manager, /bin/systemctl status power-manager" > /etc/sudoers.d/power-manager && chmod 440 /etc/sudoers.d/power-manager'
```

## Home Assistant Integration

### Connection Details

| Property | Value |
|----------|-------|
| URL | `https://gallet.duckdns.org:8123` |
| API Endpoint | `https://gallet.duckdns.org:8123/api/states/` |
| SSL Verification | Disabled (self-signed cert) |
| Token | Stored in `config.yaml` on server |

### API Usage

```bash
# Get entity state
curl -s -k -H "Authorization: Bearer $TOKEN" \
  "https://gallet.duckdns.org:8123/api/states/sensor.electricity_currently_delivered"

# Call service
curl -s -k -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "switch.storage_boiler"}' \
  "https://gallet.duckdns.org:8123/api/services/switch/turn_on"
```

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
- `input_select.pm_override_table_heater` - Auto/On/Off
- `input_select.pm_override_dishwasher` - Auto/Run/Off

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
├── ha-standalone/           # Files for HA www folder deployment
│   ├── dashboard.html       # HTML with API URL config
│   └── README.txt           # Deployment instructions
├── tests/                   # Pytest tests
├── homeassistant/
│   └── helpers/helpers.yaml # HA input_select entities
├── config.yaml              # Local config (not in git)
└── requirements.txt
```

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Create config (copy from example)
cp config.yaml.example config.yaml
# Edit config.yaml with HA token

# Run tests
pytest tests/ -v

# Run application
python -m app.main
```

## Common Commands

```bash
# Local development
pytest tests/ -v --cov=app        # Run tests with coverage
python -m app.main                 # Start server locally

# Server operations
ssh nicolas@192.168.68.78         # Connect to server
cd /opt/PowerManager && git pull  # Update code on server
sudo systemctl restart power-manager  # Restart service
journalctl -u power-manager -f    # Follow logs
```

## Dashboard Access

- **Local**: http://localhost:8081
- **Server**: http://192.168.68.78:8081
- **HA Iframe**: Embedded in Home Assistant sidebar

## Standalone Dashboard (HA www folder)

The dashboard can be hosted in Home Assistant's www folder for embedding in HA apps without SSL certificate issues.

**How it works**: `dashboard.js` detects `window.POWER_MANAGER_API` - if set, it uses that URL; otherwise uses relative URLs (for when served by Power Manager itself). This means there's only ONE dashboard.js to maintain.

**Deployment**:

```bash
# On HA server, create folder and copy files:
mkdir -p /config/www/power-manager
cp ha-standalone/dashboard.html /config/www/power-manager/
cp dashboard/static/dashboard.js /config/www/power-manager/
cp dashboard/static/style.css /config/www/power-manager/
```

**Configuration**: Edit `dashboard.html` and set the API URL:

```javascript
window.POWER_MANAGER_API = 'https://192.168.68.78:8081';
```

**Access**: `https://gallet.duckdns.org:8123/local/power-manager/dashboard.html`

**Maintenance**: When updating `dashboard/static/dashboard.js`, copy it to HA's www folder again.

## Notes

- The application uses no database - all state comes from Home Assistant
- Decisions are made every 30 seconds (configurable via `polling_interval`)
- Priority order: Frost Protection > Boiler > EV Charger > Table Heater
- During off-peak: EV only charges if boiler is not needed
- During super-off-peak: Both boiler and EV can run together
