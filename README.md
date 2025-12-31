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
- **Web Dashboard**: Embeddable in Home Assistant via iframe

## Quick Start

### Option 1: Run Directly on Linux (Recommended)

```bash
# Clone and install
git clone https://github.com/galletn/PowerManager.git
cd PowerManager
pip install -r requirements.txt

# Configure
cp config.yaml.example config.yaml
nano config.yaml  # Add your HA token

# Run
python -m app.main
```

### Option 2: Systemd Service

Create `/etc/systemd/system/power-manager.service`:

```ini
[Unit]
Description=Power Manager
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/PowerManager
ExecStart=/usr/bin/python3 -m app.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable power-manager
sudo systemctl start power-manager
```

### Option 3: Docker

```bash
docker build -t power-manager .
docker run -d -p 8080:8080 -v ./config.yaml:/app/config.yaml power-manager
```

## Configuration

Edit `config.yaml`:

```yaml
home_assistant:
  url: "https://your-ha-instance:8123"
  token: "your-long-lived-access-token"
  verify_ssl: false

polling_interval: 30  # seconds

max_import:
  peak: 2500       # Watts
  off_peak: 5000
  super_off_peak: 8000

frost_protection:
  enabled: true
  temp_threshold: 5      # Start protection below this temp
  notify_entity: "mobile_app_your_phone"

bmw_low_battery:
  enabled: true
  battery_threshold: 50  # Warn below this %
  check_hours: [20, 21, 22]
```

## Home Assistant Setup

### 1. Create Override Helpers

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

### 2. Embed Dashboard

Add to `configuration.yaml`:

```yaml
panel_iframe:
  power_manager:
    title: "Power Manager"
    icon: mdi:flash
    url: "http://your-linux-server:8080"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/api/status` | GET | Current power status (JSON) |
| `/api/override/{device}` | POST | Set manual override |
| `/api/health` | GET | Health check |

## Project Structure

```
PowerManager/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration
│   ├── models.py            # Data models
│   ├── ha_client.py         # HA REST API client
│   ├── decision_engine.py   # Core decision logic
│   └── tariff.py            # Belgian tariff calculations
├── dashboard/
│   ├── templates/dashboard.html
│   └── static/{style.css, dashboard.js}
├── tests/                   # 56 pytest tests
├── homeassistant/
│   └── helpers/helpers.yaml # HA override entities
├── config.yaml
├── requirements.txt
└── Dockerfile
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
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
