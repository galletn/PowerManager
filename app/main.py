"""
Power Manager - FastAPI Application

Main entry point for the Power Manager service.
Provides REST API, dashboard, and scheduled decision loop.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Config, load_config
from .ha_client import HAClient
from .decision_engine import calculate_decisions
from .models import PowerInputs, AllDeviceStates, PowerStatus, Decisions
from .tariff import generate_24h_schedule, format_24h_plan_text
from .scheduler import generate_schedule, format_timetable_text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global state
config: Optional[Config] = None
ha_client: Optional[HAClient] = None
device_state: AllDeviceStates = AllDeviceStates()
last_inputs: Optional[PowerInputs] = None
last_decisions: Optional[Decisions] = None
last_plan: list[str] = []
last_alerts: list[dict] = []
last_update: Optional[datetime] = None
running = False

# Alert cooldown tracking (alert_key -> last_sent_timestamp)
alert_cooldowns: dict[str, datetime] = {}
ALERT_COOLDOWN_MINUTES = 30  # Don't repeat same alert for 30 minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global config, ha_client, running

    # Startup
    logger.info("Starting Power Manager...")
    config = load_config()

    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    ha_client = HAClient(config)

    # Wait for Home Assistant to be ready (retry with backoff)
    max_retries = 30  # 5 minutes max wait
    retry_delay = 10  # seconds
    for attempt in range(max_retries):
        try:
            await ha_client.connect()
            # Test connection
            await ha_client.get_all_states()
            logger.info("Connected to Home Assistant")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"HA not ready (attempt {attempt + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {retry_delay}s...")
                if ha_client._session:
                    await ha_client.close()
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Failed to connect to Home Assistant after all retries")
                raise

    running = True
    asyncio.create_task(decision_loop())

    logger.info(f"Power Manager started, polling every {config.polling_interval}s")

    yield

    # Shutdown
    running = False
    if ha_client:
        await ha_client.close()
    logger.info("Power Manager stopped")


app = FastAPI(
    title="Power Manager",
    description="Home energy management system",
    version="1.0.0",
    lifespan=lifespan
)

# Setup templates
templates_dir = Path(__file__).parent.parent / "dashboard" / "templates"
if templates_dir.exists():
    templates = Jinja2Templates(directory=str(templates_dir))
else:
    templates = None

# Setup static files
static_dir = Path(__file__).parent.parent / "dashboard" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


async def decision_loop():
    """Main decision loop - runs every polling_interval seconds."""
    global last_inputs, last_decisions, last_plan, last_alerts, last_update, device_state

    consecutive_errors = 0
    max_consecutive_errors = 5

    while running:
        try:
            # Fetch all states from HA
            states = await ha_client.get_all_states()
            inputs = ha_client.parse_inputs(states)
            last_inputs = inputs

            # Calculate decisions
            result = calculate_decisions(inputs, config, device_state)
            last_decisions = result.decisions
            last_plan = result.plan
            last_alerts = [{'level': a.level, 'message': a.message} for a in result.alerts]
            last_update = datetime.now()

            # Execute decisions
            await execute_decisions(result.decisions, inputs)

            # Send alerts (with cooldown to prevent spam)
            for alert in result.alerts:
                if alert.notify_entity:
                    # Create a key for this alert type
                    alert_key = f"{alert.level}:{alert.notify_entity}"
                    now_time = datetime.now()

                    # Check cooldown
                    last_sent = alert_cooldowns.get(alert_key)
                    if last_sent:
                        minutes_since = (now_time - last_sent).total_seconds() / 60
                        if minutes_since < ALERT_COOLDOWN_MINUTES:
                            logger.debug(f"Alert suppressed (cooldown): {alert_key}")
                            continue

                    try:
                        await ha_client.send_notification(
                            alert.notify_entity,
                            "Power Manager Alert",
                            alert.message
                        )
                        # Update cooldown
                        alert_cooldowns[alert_key] = now_time
                        logger.info(f"Alert sent: {alert.message}")
                    except Exception as e:
                        logger.error(f"Failed to send notification: {e}")

            # Update device state for timing
            _update_device_state(inputs, result.decisions)

            if config.debug:
                logger.debug(f"Plan: {result.plan}")

            # Reset error counter on success
            consecutive_errors = 0

        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Decision loop error ({consecutive_errors}/{max_consecutive_errors}): {e}")

            if consecutive_errors >= max_consecutive_errors:
                logger.warning("Too many consecutive errors, reconnecting to HA...")
                try:
                    await ha_client.close()
                    await ha_client.connect()
                    consecutive_errors = 0
                    logger.info("Reconnected to Home Assistant")
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect: {reconnect_error}")

        await asyncio.sleep(config.polling_interval)


async def execute_decisions(decisions: Decisions, inputs: PowerInputs):
    """Execute device decisions via HA API."""
    try:
        # EV Charger
        if decisions.ev.action == 'on':
            await ha_client.set_number(config.entities.ev_limit, decisions.ev.amps)
            await ha_client.turn_on(config.entities.ev_switch)
            logger.info(f"EV: Started at {decisions.ev.amps}A")
        elif decisions.ev.action == 'off':
            await ha_client.turn_off(config.entities.ev_switch)
            logger.info("EV: Stopped")
        elif decisions.ev.action == 'adjust':
            await ha_client.set_number(config.entities.ev_limit, decisions.ev.amps)
            logger.info(f"EV: Adjusted to {decisions.ev.amps}A")

        # Boiler
        if decisions.boiler.action == 'on':
            await ha_client.turn_on(config.entities.boiler_switch)
            logger.info("Boiler: ON")
        elif decisions.boiler.action == 'off':
            await ha_client.turn_off(config.entities.boiler_switch)
            logger.info("Boiler: OFF")

        # Pool Pump (frost protection)
        if decisions.pool_pump.action == 'on':
            await ha_client.turn_on(config.entities.pool_pump)
            logger.info("Pool Pump: ON (frost protection)")
        elif decisions.pool_pump.action == 'off':
            await ha_client.turn_off(config.entities.pool_pump)
            logger.info("Pool Pump: OFF")

        # Pool Heat Pump
        if decisions.pool.action == 'on':
            await ha_client.set_climate(config.entities.pool_climate, 'heat')
            logger.info("Pool Heat: ON")
        elif decisions.pool.action == 'off':
            await ha_client.set_climate(config.entities.pool_climate, 'off')
            logger.info("Pool Heat: OFF")

        # Table Heater
        if decisions.heater_table.action == 'on':
            await ha_client.turn_on(config.entities.heater_table)
            logger.info("Table Heater: ON")
        elif decisions.heater_table.action == 'off':
            await ha_client.turn_off(config.entities.heater_table)
            logger.info("Table Heater: OFF")

    except Exception as e:
        logger.error(f"Failed to execute decisions: {e}", exc_info=True)


def _update_device_state(inputs: PowerInputs, decisions: Decisions):
    """Update device state tracking for hysteresis."""
    global device_state
    now = datetime.now().timestamp() * 1000

    # Update based on actual states and decisions
    def update_state(name: str, is_on: bool, decision_action: str):
        state = getattr(device_state, name)
        new_on = is_on if decision_action == 'none' else (decision_action == 'on')
        if state.on != new_on:
            state.on = new_on
            state.last_change = now

    update_state('ev', inputs.ev_state == 132, decisions.ev.action)
    update_state('boiler', inputs.boiler_switch == 'on', decisions.boiler.action)
    update_state('pool_pump', inputs.pool_pump_switch == 'on', decisions.pool_pump.action)
    update_state('heater_table', inputs.heater_table_switch == 'on',
                 decisions.heater_table.action)


# === API Routes ===

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the dashboard page."""
    if templates is None:
        return HTMLResponse("<h1>Dashboard not configured</h1><p>Templates directory not found.</p>")

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "title": "Power Manager"
    })


@app.get("/api/status")
async def get_status():
    """Get current power status for dashboard."""
    if last_inputs is None:
        return JSONResponse({"error": "No data yet"}, status_code=503)

    return {
        "grid_import": last_inputs.p1_power,
        "grid_export": last_inputs.p1_return,
        "pv_production": last_inputs.pv_power,
        "net_power": last_inputs.p1_power - last_inputs.p1_return,
        "is_exporting": last_inputs.p1_power < 0,
        "devices": {
            "boiler": {
                "state": last_inputs.boiler_switch,
                "power": last_inputs.boiler_power,
                "decision": last_decisions.boiler.action if last_decisions else "none"
            },
            "ev": {
                "state": last_inputs.ev_state,
                "power": last_inputs.ev_power,
                "amps": last_inputs.ev_limit,
                "decision": last_decisions.ev.action if last_decisions else "none"
            },
            "pool_pump": {
                "state": last_inputs.pool_pump_switch,
                "power": last_inputs.pool_pump_power,
                "ambient_temp": last_inputs.pool_ambient_temp,
                "decision": last_decisions.pool_pump.action if last_decisions else "none"
            },
            "bmw_i5": {
                "battery": last_inputs.bmw_i5_battery,
                "range": last_inputs.bmw_i5_range,
                "location": last_inputs.bmw_i5_location
            },
            "bmw_ix1": {
                "battery": last_inputs.bmw_ix1_battery,
                "range": last_inputs.bmw_ix1_range,
                "location": last_inputs.bmw_ix1_location
            },
            "table_heater": {
                "state": last_inputs.heater_table_switch,
                "power": config.heaters.table_power if last_inputs.heater_table_switch == 'on' else 0,
                "decision": last_decisions.heater_table.action if last_decisions else "none"
            }
        },
        "plan": last_plan,
        "alerts": last_alerts,
        "last_update": last_update.isoformat() if last_update else None,
        "schedule_24h": generate_24h_schedule(datetime.now(), config, last_inputs),
        "timetable": _get_timetable_data(),
        "limits": {
            "peak": config.max_import.peak,
            "off_peak": config.max_import.off_peak,
            "super_off_peak": config.max_import.super_off_peak
        }
    }


def _get_timetable_data():
    """Generate timetable data for dashboard."""
    if config is None or last_inputs is None:
        return None
    try:
        now = datetime.now()
        timetable = generate_schedule(now, config, last_inputs)
        return {
            "ev_estimate": timetable.ev_estimate,
            "boiler_estimate": timetable.boiler_estimate,
            "warnings": timetable.warnings,
            "hourly": timetable.timetable,
            "scheduled_hours": timetable.scheduled_hours or {}
        }
    except Exception as e:
        logger.error(f"Failed to generate timetable: {e}")
        return None


@app.post("/api/override/{device}")
async def set_override(device: str, mode: str):
    """Set manual override for a device."""
    valid_devices = ['ev', 'boiler', 'pool', 'table_heater',
                     'ac_living', 'ac_bedroom', 'ac_office', 'ac_mancave']
    valid_modes = ['auto', 'on', 'off']

    if device not in valid_devices:
        raise HTTPException(400, f"Invalid device. Must be one of: {valid_devices}")
    if mode not in valid_modes:
        raise HTTPException(400, f"Invalid mode. Must be one of: {valid_modes}")

    # Set the override in HA
    entity_map = {
        'ev': config.entities.ovr_ev,
        'boiler': config.entities.ovr_boiler,
        'pool': config.entities.ovr_pool,
        'table_heater': config.entities.ovr_table_heater,
        'ac_living': config.entities.ovr_ac_living,
        'ac_bedroom': config.entities.ovr_ac_bedroom,
        'ac_office': config.entities.ovr_ac_office,
        'ac_mancave': config.entities.ovr_ac_mancave,
    }

    # Map API mode to HA input_select option (capitalized, device-specific)
    # HA helpers use: "Auto", "On"/"Charge"/"Heat", "Off"
    mode_map = {
        'ev': {'auto': 'Auto', 'on': 'Charge', 'off': 'Off'},
        'boiler': {'auto': 'Auto', 'on': 'On', 'off': 'Off'},
        'pool': {'auto': 'Auto', 'on': 'Heat', 'off': 'Off'},
        'table_heater': {'auto': 'Auto', 'on': 'On', 'off': 'Off'},
        'ac_living': {'auto': 'Auto', 'on': 'Heat', 'off': 'Off'},
        'ac_bedroom': {'auto': 'Auto', 'on': 'Heat', 'off': 'Off'},
        'ac_office': {'auto': 'Auto', 'on': 'Heat', 'off': 'Off'},
        'ac_mancave': {'auto': 'Auto', 'on': 'Heat', 'off': 'Off'},
    }

    ha_mode = mode_map.get(device, {}).get(mode, mode.capitalize())

    try:
        await ha_client.call_service(
            "input_select", "select_option",
            entity_map[device],
            option=ha_mode
        )
        return {"status": "ok", "device": device, "mode": mode, "ha_mode": ha_mode}
    except Exception as e:
        logger.error(f"Failed to set override {device}={mode}: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "running": running,
        "last_update": last_update.isoformat() if last_update else None
    }


@app.get("/api/limits")
async def get_limits():
    """Get current power limits."""
    if config is None:
        return JSONResponse({"error": "Not initialized"}, status_code=503)

    # Try to read from HA input_numbers, fall back to config
    limits = {
        "peak": config.max_import.peak,
        "off_peak": config.max_import.off_peak,
        "super_off_peak": config.max_import.super_off_peak
    }

    try:
        states = await ha_client.get_all_states()

        peak_state = states.get(config.entities.limit_peak, {})
        if peak_state.get("state") not in (None, "unavailable", "unknown"):
            limits["peak"] = int(float(peak_state["state"]))

        off_peak_state = states.get(config.entities.limit_off_peak, {})
        if off_peak_state.get("state") not in (None, "unavailable", "unknown"):
            limits["off_peak"] = int(float(off_peak_state["state"]))

        super_state = states.get(config.entities.limit_super_off_peak, {})
        if super_state.get("state") not in (None, "unavailable", "unknown"):
            limits["super_off_peak"] = int(float(super_state["state"]))
    except Exception as e:
        logger.warning(f"Could not read limits from HA: {e}")

    return limits


@app.post("/api/limits")
async def set_limits(peak: int = None, off_peak: int = None,
                     super_off_peak: int = None):
    """Set power limits via HA input_numbers."""
    if config is None:
        return JSONResponse({"error": "Not initialized"}, status_code=503)

    results = {}

    try:
        if peak is not None:
            await ha_client.call_service(
                "input_number", "set_value",
                config.entities.limit_peak,
                value=peak
            )
            config.max_import.peak = peak
            results["peak"] = peak

        if off_peak is not None:
            await ha_client.call_service(
                "input_number", "set_value",
                config.entities.limit_off_peak,
                value=off_peak
            )
            config.max_import.off_peak = off_peak
            results["off_peak"] = off_peak

        if super_off_peak is not None:
            await ha_client.call_service(
                "input_number", "set_value",
                config.entities.limit_super_off_peak,
                value=super_off_peak
            )
            config.max_import.super_off_peak = super_off_peak
            results["super_off_peak"] = super_off_peak

        return {"status": "ok", "updated": results}
    except Exception as e:
        logger.error(f"Failed to set limits: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/schedule")
async def get_schedule():
    """Get 24-hour schedule/plan with timetable."""
    if config is None:
        return JSONResponse({"error": "Not initialized"}, status_code=503)

    now = datetime.now()
    schedule = generate_24h_schedule(now, config, last_inputs)

    # Generate optimized timetable with time estimates
    timetable = generate_schedule(now, config, last_inputs)

    return {
        "schedule": schedule,
        "text": format_24h_plan_text(schedule),
        "timetable": {
            "ev_estimate": timetable.ev_estimate,
            "boiler_estimate": timetable.boiler_estimate,
            "warnings": timetable.warnings,
            "hourly": timetable.timetable
        },
        "timetable_text": format_timetable_text(timetable)
    }


# CLI entry point
def main():
    """Run the server."""
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8081,
        reload=False
    )


if __name__ == "__main__":
    main()
