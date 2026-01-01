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
| Dashboard Port | `8080` |

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
- `switch.abb_terra_ac_charging` - EV charger on/off
- `number.abb_terra_ac_current_limit` - EV charger amps (6-16A)
- `switch.poolhouse_pool_pump` - Pool pump (frost protection)
- `switch.livingroom_table_heater_state` - Table heater (4.1kW)

**Override Helpers** (set via HA UI or API):
- `input_select.pm_override_boiler` - Auto/On/Off
- `input_select.pm_override_ev` - Auto/On/Off
- `input_select.pm_override_pool` - Auto/On/Off
- `input_select.pm_override_table_heater` - Auto/On/Off

## Power Limits (Belgian Tariffs)

| Tariff | Hours | Max Import |
|--------|-------|------------|
| Peak | 07:00-22:00 (weekdays) | 2500W |
| Off-Peak | 22:00-07:00 + weekends | 5000W |
| Super Off-Peak | 01:00-05:00 | 8000W |

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
│       └── dashboard.js
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

- **Local**: http://localhost:8080
- **Server**: http://192.168.68.78:8080
- **HA Iframe**: Embedded in Home Assistant sidebar

## Notes

- The application uses no database - all state comes from Home Assistant
- Decisions are made every 30 seconds (configurable via `polling_interval`)
- Priority order: Frost Protection > Boiler > EV Charger > Table Heater
- During off-peak: EV only charges if boiler is not needed
- During super-off-peak: Both boiler and EV can run together
