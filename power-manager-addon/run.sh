#!/bin/sh
set -e

# HA connection via Supervisor internal API (automatic in add-ons)
export HA_URL="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"

# Force port to match ingress_port in config.yaml
export PORT=8099

# Use custom config if user placed one in /config/power-manager/
if [ -f /config/power-manager/config.yaml ]; then
    echo "Using custom config from /config/power-manager/config.yaml"
    export PM_CONFIG="/config/power-manager/config.yaml"
else
    # Create minimal config (HA connection comes from env vars above)
    echo "No custom config found, using defaults"
    cat > /tmp/pm-config.yaml << 'EOF'
polling_interval: 30
EOF
    export PM_CONFIG="/tmp/pm-config.yaml"
fi

cd /opt/power-manager

# Ensure EV override has all options (including Solar) after HA reboot
echo "Setting up EV override options..."
python -c "
import urllib.request, json, ssl, os, time
time.sleep(5)
token = os.environ.get('SUPERVISOR_TOKEN', '')
url = 'http://supervisor/core/api/services/input_select/set_options'
data = json.dumps({
    'entity_id': 'input_select.pm_override_ev',
    'options': ['\U0001f916 Auto', '\u2600\ufe0f Solar', '\u26a1 Laden', '\u23f9\ufe0f Uit']
}).encode('utf-8')
req = urllib.request.Request(url, data=data, method='POST')
req.add_header('Authorization', f'Bearer {token}')
req.add_header('Content-Type', 'application/json; charset=utf-8')
try:
    resp = urllib.request.urlopen(req)
    print(f'EV override options set (status {resp.status})')
except Exception as e:
    print(f'Warning: could not set EV options: {e}')
" 2>&1 || echo "EV options setup skipped"

echo "Starting Power Manager add-on on port ${PORT}..."
exec python -m app.main
