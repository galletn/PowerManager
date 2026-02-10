# Power Manager

Intelligent home energy management for Home Assistant. Optimizes power consumption by automatically controlling devices based on solar production, grid tariffs, and consumption patterns.

## Features

- **Smart EV Charging**: Charges during off-peak hours in winter, uses solar surplus in summer
- **Boiler Control**: Heats water during off-peak/solar surplus, ensures hot water by deadline
- **Pool Heat Pump**: Manages pool heating based on season and available power
- **Frost Protection**: Monitors pool pump during freezing temperatures with alerts
- **BMW Low Battery Warnings**: Evening alerts if car battery is low and not plugged in
- **Belgian Tariff Support**: Peak, off-peak, and super-off-peak rate optimization
- **Manual Overrides**: Force devices on/off via Home Assistant
- **Web Dashboard**: Accessible from HA sidebar (locally and remotely via ingress)

## Installation (HA Add-on)

1. In Home Assistant: **Settings > Add-ons > Add-on Store**
2. Click three dots > **Repositories**
3. Add: `https://github.com/galletn/PowerManager`
4. Find **Power Manager** and click **Install**
5. Enable **Start on boot** and click **Start**
6. Toggle **Show in sidebar** to add the dashboard to your menu

The add-on connects to HA automatically via the Supervisor API - no token configuration needed.

## Configuration

The add-on works with default settings out of the box. For custom power limits or other settings, create `/config/power-manager/config.yaml` on your HA instance:

```yaml
polling_interval: 30  # seconds

max_import:
  peak: 2500       # Watts
  off_peak: 5000
  super_off_peak: 8000

frost_protection:
  enabled: true
  temp_threshold: 5
  notify_entity: "mobile_app_your_phone"

bmw_low_battery:
  enabled: true
  battery_threshold: 50
  check_hours: [20, 21, 22]
```

## Home Assistant Setup

### Override Helpers

Add to `configuration.yaml` or create via UI:

```yaml
input_select:
  pm_override_boiler:
    name: "PM Boiler Override"
    options: ["Auto", "On", "Off"]
    initial: "Auto"
  pm_override_ev:
    name: "PM EV Override"
    options: ["Auto", "On", "Off"]
    initial: "Auto"
  pm_override_pool:
    name: "PM Pool Override"
    options: ["Auto", "On", "Off"]
    initial: "Auto"
```

See [homeassistant/helpers/helpers.yaml](homeassistant/helpers/helpers.yaml) for full list.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/api/status` | GET | Current power status (JSON) |
| `/api/override/{device}` | POST | Set manual override |
| `/api/health` | GET | Health check |
| `/api/limits` | GET/POST | View/update power limits |
| `/api/schedule` | GET | 24-hour schedule |

## Project Structure

```
PowerManager/
├── app/
│   ├── main.py              # FastAPI application + decision loop
│   ├── config.py            # Configuration dataclasses
│   ├── models.py            # Data models
│   ├── ha_client.py         # HA REST API client
│   ├── decision_engine.py   # Core decision logic
│   ├── scheduler.py         # 24-hour schedule generator
│   └── tariff.py            # Belgian tariff calculations
├── dashboard/
│   ├── templates/dashboard.html
│   └── static/{style.css, dashboard.js}
├── power-manager-addon/     # HA add-on packaging
│   ├── config.yaml          # Add-on manifest
│   ├── Dockerfile
│   ├── run.sh
│   └── dashboard-ingress.html
├── repository.yaml          # HA add-on repository metadata
├── tests/                   # Pytest tests
├── homeassistant/
│   └── helpers/helpers.yaml # HA override entities
└── requirements.txt
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Create config for local dev
cp config.yaml.example config.yaml
# Edit config.yaml with HA token

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run locally
python -m app.main
```

## Controlled Devices

| Device | Power | Control |
|--------|-------|---------|
| EV Charger (ABB Terra AC) | 4-11 kW | On/Off + Amps |
| Water Heater (Boiler) | 2.5 kW | On/Off |
| Pool Heat Pump | 2 kW | Climate mode |
| Pool Pump | 0.5 kW | On/Off (frost) |

## License

MIT
