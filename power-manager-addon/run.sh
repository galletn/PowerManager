#!/usr/bin/env bash
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
echo "Starting Power Manager add-on on port ${PORT}..."
exec python -m app.main
