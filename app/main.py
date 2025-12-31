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
    await ha_client.connect()

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

            # Send alerts
            for alert in result.alerts:
                if alert.notify_entity:
                    try:
                        await ha_client.send_notification(
                            alert.notify_entity,
                            "Power Manager Alert",
                            alert.message
                        )
                    except Exception as e:
                        logger.error(f"Failed to send notification: {e}")

            # Update device state for timing
            _update_device_state(inputs, result.decisions)

            if config.debug:
                logger.debug(f"Plan: {result.plan}")

        except Exception as e:
            logger.error(f"Decision loop error: {e}", exc_info=True)

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
            }
        },
        "plan": last_plan,
        "alerts": last_alerts,
        "last_update": last_update.isoformat() if last_update else None
    }


@app.post("/api/override/{device}")
async def set_override(device: str, mode: str):
    """Set manual override for a device."""
    valid_devices = ['ev', 'boiler', 'pool', 'ac_living', 'ac_bedroom', 'ac_office', 'ac_mancave']
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
        'ac_living': config.entities.ovr_ac_living,
        'ac_bedroom': config.entities.ovr_ac_bedroom,
        'ac_office': config.entities.ovr_ac_office,
        'ac_mancave': config.entities.ovr_ac_mancave,
    }

    try:
        await ha_client.call_service(
            "input_select", "select_option",
            entity_map[device],
            option=mode
        )
        return {"status": "ok", "device": device, "mode": mode}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "running": running,
        "last_update": last_update.isoformat() if last_update else None
    }


# CLI entry point
def main():
    """Run the server."""
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=False
    )


if __name__ == "__main__":
    main()
