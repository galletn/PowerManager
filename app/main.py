"""
Power Manager - FastAPI Application

Main entry point for the Power Manager service.
Provides REST API, dashboard, and scheduled decision loop.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Config, load_config
from .ha_client import HAClient
from .decision_engine import calculate_decisions
from .models import PowerInputs, AllDeviceStates, Decisions
from .tariff import generate_24h_schedule, format_24h_plan_text, get_max_import
from .scheduler import generate_schedule, format_timetable_text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
ALERT_COOLDOWN_MINUTES = 30  # Don't repeat same alert for 30 minutes
ALERT_COOLDOWN_CLEANUP_MINUTES = 60  # Clean up cooldown entries older than 1 hour

# Retry backoff intervals in seconds: 1min, 5min, 15min, 30min, 60min
RETRY_BACKOFF_SECONDS = [60, 300, 900, 1800, 3600]


@dataclass
class PendingCommand:
    """Tracks a command waiting for state verification."""
    entity_id: str
    expected_state: str  # 'on' or 'off'
    command_time: datetime
    last_retry: datetime
    retry_count: int = 0


@dataclass
class AppState:
    """Encapsulates all application state for the Power Manager service.

    This dataclass consolidates what were previously 9+ global variables into
    a single cohesive state object. This improves testability, makes state
    dependencies explicit, and eliminates the global state anti-pattern.

    Attributes:
        config: Application configuration loaded from config.yaml.
        ha_client: Home Assistant REST API client for device control.
        device_state: Tracks device on/off states and last change times
            for hysteresis control (preventing rapid switching).
        last_inputs: Most recent power readings from Home Assistant sensors.
        last_decisions: Most recent device control decisions from the engine.
        last_plan: List of human-readable decision explanations for dashboard.
        last_alerts: List of alert dicts (level, message) for dashboard.
        last_update: Timestamp of last successful decision loop iteration.
        last_ha_states: Cached dict of all HA entity states for API endpoints.
        running: Flag to control the decision loop lifecycle.
        alert_cooldowns: Maps alert keys to timestamps to prevent spam.
    """
    config: Optional[Config] = None
    ha_client: Optional[HAClient] = None
    device_state: AllDeviceStates = field(default_factory=AllDeviceStates)
    last_inputs: Optional[PowerInputs] = None
    last_decisions: Optional[Decisions] = None
    last_plan: list[str] = field(default_factory=list)
    last_alerts: list[dict] = field(default_factory=list)
    last_update: Optional[datetime] = None
    last_ha_states: Optional[dict] = None
    running: bool = False
    alert_cooldowns: dict[str, datetime] = field(default_factory=dict)
    pending_commands: dict[str, PendingCommand] = field(default_factory=dict)

    def cleanup_alert_cooldowns(self) -> None:
        """Remove alert cooldown entries older than ALERT_COOLDOWN_CLEANUP_MINUTES."""
        now = datetime.now()
        cutoff_seconds = ALERT_COOLDOWN_CLEANUP_MINUTES * 60

        # Build list of keys to remove (avoid modifying dict during iteration)
        keys_to_remove = [
            key for key, timestamp in self.alert_cooldowns.items()
            if (now - timestamp).total_seconds() > cutoff_seconds
        ]

        for key in keys_to_remove:
            del self.alert_cooldowns[key]

        if keys_to_remove:
            logger.debug(
                f"Cleaned up {len(keys_to_remove)} expired alert cooldown entries"
            )


# Single application state instance
app_state = AppState()


def get_entity_state(states: dict, entity_id: str) -> Optional[str]:
    """Get current state of an entity from HA states dict."""
    entity_data = states.get(entity_id, {})
    return entity_data.get("state")


async def verify_and_retry_pending_commands(states: dict) -> None:
    """Verify pending commands succeeded and retry with exponential backoff if not.

    This function checks each pending command to see if the device reached
    the expected state. If not, and enough time has passed since the last
    retry, it will retry the command with exponential backoff.

    Backoff schedule: 1min, 5min, 15min, 30min, 60min (then repeats 60min)
    """
    now = datetime.now()
    config = app_state.config
    ha_client = app_state.ha_client
    commands_to_remove = []

    for entity_id, cmd in app_state.pending_commands.items():
        current_state = get_entity_state(states, entity_id)

        # Normalize state comparison (HA uses various formats)
        if current_state:
            current_state = current_state.lower()

        state_matches = current_state == cmd.expected_state

        if state_matches:
            # Command succeeded - remove from pending
            elapsed = (now - cmd.command_time).total_seconds()
            if cmd.retry_count > 0:
                logger.info(
                    f"Command verified after {cmd.retry_count} retries: "
                    f"{entity_id} is now {current_state} "
                    f"(took {elapsed:.0f}s total)"
                )
            commands_to_remove.append(entity_id)
            continue

        # State doesn't match - check if we should retry
        backoff_index = min(cmd.retry_count, len(RETRY_BACKOFF_SECONDS) - 1)
        backoff_seconds = RETRY_BACKOFF_SECONDS[backoff_index]
        time_since_retry = (now - cmd.last_retry).total_seconds()

        if time_since_retry >= backoff_seconds:
            # Time to retry
            cmd.retry_count += 1
            cmd.last_retry = now

            # Get friendly device name from entity_id
            device_name = entity_id.split(".")[-1].replace("_", " ").title()

            logger.warning(
                f"State verification failed for {entity_id}: "
                f"expected '{cmd.expected_state}', got '{current_state}'. "
                f"Retry {cmd.retry_count} (next in {RETRY_BACKOFF_SECONDS[min(cmd.retry_count, len(RETRY_BACKOFF_SECONDS) - 1)]}s)"
            )

            # Send notification on first retry to alert user
            if cmd.retry_count == 1 and config:
                try:
                    await ha_client.send_notification(
                        config.frost_protection.notify_entity,
                        "Power Manager: Command Failed",
                        f"{device_name} failed to turn {cmd.expected_state}. Retrying..."
                    )
                except Exception as e:
                    logger.error(f"Failed to send retry notification: {e}")

            try:
                if cmd.expected_state == 'on':
                    await ha_client.turn_on(entity_id)
                else:
                    await ha_client.turn_off(entity_id)
                logger.info(f"Retry command sent: {entity_id} -> {cmd.expected_state}")
            except Exception as e:
                logger.error(f"Retry failed for {entity_id}: {e}")

        # Check for stale commands (over 2 hours old)
        total_elapsed = (now - cmd.command_time).total_seconds()
        if total_elapsed > 7200:  # 2 hours
            device_name = entity_id.split(".")[-1].replace("_", " ").title()
            logger.error(
                f"Giving up on {entity_id} after {total_elapsed:.0f}s and "
                f"{cmd.retry_count} retries"
            )
            # Send critical notification when giving up
            if config:
                try:
                    await ha_client.send_notification(
                        config.frost_protection.notify_entity,
                        "Power Manager: CRITICAL",
                        f"FAILED to turn {cmd.expected_state} {device_name} after {cmd.retry_count} retries over 2 hours!"
                    )
                except Exception as e:
                    logger.error(f"Failed to send give-up notification: {e}")
            commands_to_remove.append(entity_id)

    # Clean up completed/stale commands
    for entity_id in commands_to_remove:
        del app_state.pending_commands[entity_id]


def add_pending_command(entity_id: str, expected_state: str) -> None:
    """Add a command to pending verification queue."""
    now = datetime.now()
    app_state.pending_commands[entity_id] = PendingCommand(
        entity_id=entity_id,
        expected_state=expected_state,
        command_time=now,
        last_retry=now,
        retry_count=0
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Power Manager...")
    app_state.config = load_config()

    if not app_state.config.home_assistant.verify_ssl:
        logger.warning(
            "SSL verification is DISABLED for Home Assistant connection. "
            "This is acceptable for self-signed certificates but reduces security."
        )

    if app_state.config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    app_state.ha_client = HAClient(app_state.config)

    # Wait for Home Assistant to be ready (retry with backoff)
    max_retries = 30  # 5 minutes max wait
    retry_delay = 10  # seconds
    for attempt in range(max_retries):
        try:
            await app_state.ha_client.connect()
            # Test connection
            await app_state.ha_client.get_all_states()
            logger.info("Connected to Home Assistant")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"HA not ready (attempt {attempt + 1}/{max_retries}): "
                    f"{type(e).__name__}"
                )
                logger.info(f"Retrying in {retry_delay}s...")
                if app_state.ha_client._session:
                    await app_state.ha_client.close()
                await asyncio.sleep(retry_delay)
            else:
                logger.error(
                    "Failed to connect to Home Assistant after all retries"
                )
                raise

    app_state.running = True
    asyncio.create_task(decision_loop())

    logger.info(
        f"Power Manager started, polling every "
        f"{app_state.config.polling_interval}s"
    )

    yield

    # Shutdown
    app_state.running = False
    if app_state.ha_client:
        await app_state.ha_client.close()
    logger.info("Power Manager stopped")


app = FastAPI(
    title="Power Manager",
    description="Home energy management system",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for iframe embedding in HA app
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Middleware to allow iframe embedding (for HA companion app)
@app.middleware("http")
async def add_iframe_headers(request: Request, call_next):
    response = await call_next(request)
    # Allow embedding in iframes from any origin
    response.headers["X-Frame-Options"] = "ALLOWALL"
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return response

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
    consecutive_errors = 0
    max_consecutive_errors = 5

    while app_state.running:
        try:
            # Fetch all states from HA and cache them
            states = await app_state.ha_client.get_all_states()
            app_state.last_ha_states = states  # Store for use in /api/status
            inputs = app_state.ha_client.parse_inputs(states)
            app_state.last_inputs = inputs

            # Verify pending commands and retry if failed
            await verify_and_retry_pending_commands(states)

            # Calculate decisions
            result = calculate_decisions(
                inputs, app_state.config, app_state.device_state
            )
            app_state.last_decisions = result.decisions
            app_state.last_plan = result.plan
            app_state.last_alerts = [
                {'level': a.level, 'message': a.message} for a in result.alerts
            ]
            app_state.last_update = datetime.now()

            # Execute decisions and get confirmed states from HA API responses
            confirmed_states = await execute_decisions(result.decisions, inputs)

            # Send alerts (with cooldown to prevent spam)
            for alert in result.alerts:
                if alert.notify_entity:
                    # Create a key for this alert type
                    alert_key = f"{alert.level}:{alert.notify_entity}"
                    now_time = datetime.now()

                    # Check cooldown
                    last_sent = app_state.alert_cooldowns.get(alert_key)
                    if last_sent:
                        minutes_since = (now_time - last_sent).total_seconds() / 60
                        if minutes_since < ALERT_COOLDOWN_MINUTES:
                            logger.debug(
                                f"Alert suppressed (cooldown): {alert_key}"
                            )
                            continue

                    try:
                        await app_state.ha_client.send_notification(
                            alert.notify_entity,
                            "Power Manager Alert",
                            alert.message
                        )
                        # Update cooldown
                        app_state.alert_cooldowns[alert_key] = now_time
                        logger.info(f"Alert sent: {alert.message}")
                    except Exception as e:
                        logger.error(
                            f"Failed to send notification: {e}", exc_info=True
                        )

            # Update device state using confirmed states from HA API
            _update_device_state(inputs, confirmed_states)

            if app_state.config.debug:
                logger.debug(f"Plan: {result.plan}")

            # Clean up old alert cooldown entries to prevent memory leak
            app_state.cleanup_alert_cooldowns()

            # Reset error counter on success
            consecutive_errors = 0

        except Exception as e:
            consecutive_errors += 1
            logger.error(
                f"Decision loop error ({consecutive_errors}/"
                f"{max_consecutive_errors}): {e}",
                exc_info=True
            )

            if consecutive_errors >= max_consecutive_errors:
                logger.warning(
                    "Too many consecutive errors, reconnecting to HA..."
                )
                try:
                    await app_state.ha_client.close()
                    await app_state.ha_client.connect()
                    consecutive_errors = 0
                    logger.info("Reconnected to Home Assistant")
                except Exception as reconnect_error:
                    logger.error(
                        f"Failed to reconnect: {reconnect_error}", exc_info=True
                    )

        await asyncio.sleep(app_state.config.polling_interval)


async def execute_decisions(
    decisions: Decisions, inputs: PowerInputs
) -> dict[str, bool]:
    """Execute device decisions via HA API.

    Returns a dict mapping device names to their confirmed state (True=on,
    False=off). Only includes devices where a state change was attempted
    and confirmed by HA API response.
    """
    confirmed_states = {}
    config = app_state.config
    ha_client = app_state.ha_client

    try:
        # EV Charger
        if decisions.ev.action == 'on':
            await ha_client.set_number(
                config.entities.ev_limit, decisions.ev.amps
            )
            success = await ha_client.turn_on(config.entities.ev_switch)
            if success:
                confirmed_states['ev'] = True
                add_pending_command(config.entities.ev_switch, 'on')
            logger.info(f"EV: Started at {decisions.ev.amps}A")
        elif decisions.ev.action == 'off':
            success = await ha_client.turn_off(config.entities.ev_switch)
            if success:
                confirmed_states['ev'] = False
                add_pending_command(config.entities.ev_switch, 'off')
            logger.info("EV: Stopped")
        elif decisions.ev.action == 'adjust':
            await ha_client.set_number(
                config.entities.ev_limit, decisions.ev.amps
            )
            logger.info(f"EV: Adjusted to {decisions.ev.amps}A")

        # Boiler
        if decisions.boiler.action == 'on':
            success = await ha_client.turn_on(config.entities.boiler_switch)
            if success:
                confirmed_states['boiler'] = True
                add_pending_command(config.entities.boiler_switch, 'on')
            logger.info("Boiler: ON")
        elif decisions.boiler.action == 'off':
            success = await ha_client.turn_off(config.entities.boiler_switch)
            if success:
                confirmed_states['boiler'] = False
                add_pending_command(config.entities.boiler_switch, 'off')
            logger.info("Boiler: OFF")

        # Pool Pump (frost protection)
        if decisions.pool_pump.action == 'on':
            success = await ha_client.turn_on(config.entities.pool_pump)
            if success:
                confirmed_states['pool_pump'] = True
                add_pending_command(config.entities.pool_pump, 'on')
            logger.info("Pool Pump: ON (frost protection)")
        elif decisions.pool_pump.action == 'off':
            success = await ha_client.turn_off(config.entities.pool_pump)
            if success:
                confirmed_states['pool_pump'] = False
                add_pending_command(config.entities.pool_pump, 'off')
            logger.info("Pool Pump: OFF")

        # Pool Heat Pump
        if decisions.pool.action == 'on':
            success = await ha_client.set_climate(
                config.entities.pool_climate, 'heat'
            )
            if success:
                confirmed_states['pool'] = True
                add_pending_command(config.entities.pool_climate, 'heat')
            logger.info("Pool Heat: ON")
        elif decisions.pool.action == 'off':
            success = await ha_client.set_climate(
                config.entities.pool_climate, 'off'
            )
            if success:
                confirmed_states['pool'] = False
                add_pending_command(config.entities.pool_climate, 'off')
            logger.info("Pool Heat: OFF")

        # Table Heater
        if decisions.heater_table.action == 'on':
            success = await ha_client.turn_on(config.entities.heater_table)
            if success:
                confirmed_states['heater_table'] = True
                add_pending_command(config.entities.heater_table, 'on')
            logger.info("Table Heater: ON")
        elif decisions.heater_table.action == 'off':
            success = await ha_client.turn_off(config.entities.heater_table)
            if success:
                confirmed_states['heater_table'] = False
                add_pending_command(config.entities.heater_table, 'off')
            logger.info("Table Heater: OFF")

        # Right Heater (solar surplus only)
        if decisions.heater_right.action == 'on':
            success = await ha_client.turn_on(config.entities.heater_right)
            if success:
                confirmed_states['heater_right'] = True
                add_pending_command(config.entities.heater_right, 'on')
            logger.info("Right Heater: ON")
        elif decisions.heater_right.action == 'off':
            success = await ha_client.turn_off(config.entities.heater_right)
            if success:
                confirmed_states['heater_right'] = False
                add_pending_command(config.entities.heater_right, 'off')
            logger.info("Right Heater: OFF")

        # Dishwasher (smart scheduling)
        if decisions.dishwasher.action == 'on':
            success = await ha_client.turn_on(config.entities.dishwasher_switch)
            if success:
                confirmed_states['dishwasher'] = True
                add_pending_command(config.entities.dishwasher_switch, 'on')
            logger.info(f"Dishwasher: ON ({decisions.dishwasher.reason})")
        elif decisions.dishwasher.action == 'off':
            success = await ha_client.turn_off(config.entities.dishwasher_switch)
            if success:
                confirmed_states['dishwasher'] = False
                add_pending_command(config.entities.dishwasher_switch, 'off')
            logger.info(f"Dishwasher: PAUSED ({decisions.dishwasher.reason})")

    except Exception as e:
        logger.error(f"Failed to execute decisions: {e}", exc_info=True)

    return confirmed_states


def _update_device_state(inputs: PowerInputs, confirmed_states: dict[str, bool]):
    """Update device state tracking for hysteresis.

    Uses confirmed states from HA API responses when available, otherwise
    falls back to current input states. This fixes the race condition where
    we were updating state based on predicted decisions instead of actual
    HA response.

    Args:
        inputs: Current power inputs from HA
        confirmed_states: Dict of device name -> confirmed on/off state from
            HA API calls
    """
    now = datetime.now().timestamp() * 1000
    device_state = app_state.device_state

    def update_state(name: str, current_is_on: bool):
        """Update device state, using confirmed state if available."""
        state = getattr(device_state, name)
        # Use confirmed state from HA API if we made a change, else current input
        if name in confirmed_states:
            new_on = confirmed_states[name]
        else:
            new_on = current_is_on

        if state.on != new_on:
            state.on = new_on
            state.last_change = now

    # Update each device using confirmed states or fallback to current inputs
    update_state('ev', inputs.ev_state == 132)
    update_state('boiler', inputs.boiler_switch == 'on')
    update_state('pool_pump', inputs.pool_pump_switch == 'on')
    update_state('heater_table', inputs.heater_table_switch == 'on')
    update_state('dishwasher', inputs.dishwasher_switch == 'on')


# === API Routes ===

@app.get("/", response_class=HTMLResponse,
         summary="Dashboard",
         description="Serves the main Power Manager dashboard HTML page with real-time power monitoring and device control")
async def dashboard(request: Request):
    """Serve the dashboard page."""
    if templates is None:
        return HTMLResponse("<h1>Dashboard not configured</h1><p>Templates directory not found.</p>")

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "title": "Power Manager"
    })


@app.get("/power", response_class=HTMLResponse,
         summary="Power Flow Dashboard",
         description="Compact dashboard showing only power flow (solar/home/grid)")
async def dashboard_power(request: Request):
    """Serve the compact power flow dashboard for small displays."""
    if templates is None:
        return HTMLResponse("<h1>Dashboard not configured</h1>")

    return templates.TemplateResponse("dashboard-power.html", {
        "request": request,
        "title": "Power Flow"
    })


@app.get("/timeline", response_class=HTMLResponse,
         summary="Timeline Dashboard",
         description="Compact dashboard showing timeline and decision plan")
async def dashboard_timeline(request: Request):
    """Serve the compact timeline dashboard for small displays."""
    if templates is None:
        return HTMLResponse("<h1>Dashboard not configured</h1>")

    return templates.TemplateResponse("dashboard-timeline.html", {
        "request": request,
        "title": "Timeline & Plan"
    })


@app.get("/api/status",
         summary="Get current power status",
         description="Returns current power readings, device states, 24-hour "
                     "schedule, timetable, power limits, and alerts.")
async def get_status():
    """Get current power status for dashboard."""
    last_inputs = app_state.last_inputs
    last_decisions = app_state.last_decisions
    config = app_state.config

    if last_inputs is None:
        return JSONResponse({"error": "No data yet"}, status_code=503)

    # Get consumer power values
    consumers = await _get_consumers_data()

    # Calculate table heater power
    table_heater_power = 0
    if last_inputs.heater_table_switch == 'on' and config:
        table_heater_power = config.heaters.table_power

    # Handle None values during HA startup
    p1_power = last_inputs.p1_power if last_inputs.p1_power is not None else 0
    p1_return = last_inputs.p1_return if last_inputs.p1_return is not None else 0
    pv_power = last_inputs.pv_power if last_inputs.pv_power is not None else 0

    # Get last_changed timestamps from raw HA states
    ha_states = app_state.last_ha_states or {}
    ev_state_data = ha_states.get(config.entities.ev_state, {})
    boiler_state_data = ha_states.get(config.entities.boiler_switch, {})

    # EV: last_charged is when it reached state 130 (Full)
    ev_last_charged = None
    if last_inputs.ev_state == 130:  # Currently full
        ev_last_charged = ev_state_data.get("last_changed")

    # Boiler: last_heated is when it was turned off (after being on)
    boiler_last_heated = None
    if last_inputs.boiler_switch == "off":
        boiler_last_heated = boiler_state_data.get("last_changed")

    # Net power: positive = importing, negative = exporting
    net_power = p1_power - p1_return
    # is_exporting: true when export > import (net is negative)
    is_exporting = p1_return > p1_power

    return {
        "grid_import": p1_power,
        "grid_export": p1_return,
        "pv_production": pv_power,
        "net_power": net_power,
        "is_exporting": is_exporting,
        "devices": {
            "boiler": {
                "state": last_inputs.boiler_switch,
                "power": last_inputs.boiler_power,
                "decision": (
                    last_decisions.boiler.action if last_decisions else "none"
                ),
                "last_heated": boiler_last_heated
            },
            "ev": {
                "state": last_inputs.ev_state,
                "power": last_inputs.ev_power,
                "amps": last_inputs.ev_limit,
                "decision": (
                    last_decisions.ev.action if last_decisions else "none"
                ),
                "last_charged": ev_last_charged,
                "override": last_inputs.ovr_ev
            },
            "pool_pump": {
                "state": last_inputs.pool_pump_switch,
                "power": last_inputs.pool_pump_power,
                "ambient_temp": last_inputs.pool_ambient_temp,
                "decision": (
                    last_decisions.pool_pump.action if last_decisions else "none"
                )
            },
            "bmw_i5": {
                "battery": last_inputs.bmw_i5_battery,
                "range": last_inputs.bmw_i5_range,
                "location": last_inputs.bmw_i5_location,
                "charging_state": last_inputs.bmw_i5_charging_state,
                "charging_power": last_inputs.bmw_i5_charging_power,
                "plug_state": last_inputs.bmw_i5_plug_state,
                "target_soc": last_inputs.bmw_i5_target_soc,
                "mileage": last_inputs.bmw_i5_mileage,
                "time_to_full": last_inputs.bmw_i5_time_to_full
            },
            "bmw_ix1": {
                "battery": last_inputs.bmw_ix1_battery,
                "range": last_inputs.bmw_ix1_range,
                "location": last_inputs.bmw_ix1_location,
                "charging_state": last_inputs.bmw_ix1_charging_state,
                "charging_power": last_inputs.bmw_ix1_charging_power,
                "plug_state": last_inputs.bmw_ix1_plug_state,
                "target_soc": last_inputs.bmw_ix1_target_soc,
                "mileage": last_inputs.bmw_ix1_mileage,
                "time_to_full": last_inputs.bmw_ix1_time_to_full
            },
            "table_heater": {
                "state": last_inputs.heater_table_switch,
                "power": table_heater_power,
                "decision": (
                    last_decisions.heater_table.action
                    if last_decisions else "none"
                )
            },
            "dishwasher": {
                "state": last_inputs.dishwasher_switch,
                "power": last_inputs.dishwasher_power,
                "decision": (
                    last_decisions.dishwasher.action
                    if last_decisions else "none"
                ),
                "reason": (
                    last_decisions.dishwasher.reason if last_decisions else ""
                )
            }
        },
        "consumers": consumers,
        "plan": app_state.last_plan,
        "alerts": app_state.last_alerts,
        "last_update": (
            app_state.last_update.isoformat()
            if app_state.last_update else None
        ),
        "schedule_24h": generate_24h_schedule(datetime.now(), config, last_inputs),
        "timetable": _get_timetable_data(),
        "limits": {
            "peak": get_max_import("peak", config),
            "off_peak": get_max_import("off-peak", config),
            "super_off_peak": get_max_import("super-off-peak", config)
        },
        "environment": _get_environment_data()
    }


def _get_environment_data():
    """Get sun, weather, and solar forecast data for dashboard icons."""
    config = app_state.config
    ha_states = app_state.last_ha_states

    if config is None or ha_states is None:
        return None

    try:
        entities = config.entities

        # Sun state
        sun_state = ha_states.get(entities.sun, {})
        sun_is_up = sun_state.get("state") == "above_horizon"
        sun_elevation = sun_state.get("attributes", {}).get("elevation", 0)

        # Weather state
        weather_state = ha_states.get(entities.weather, {})
        weather_condition = weather_state.get("state", "unknown")
        cloud_coverage = weather_state.get("attributes", {}).get("cloud_coverage", 0)

        # Solar forecast
        forecast_state = ha_states.get(entities.solar_forecast, {})
        forecast_val = forecast_state.get("state")
        try:
            solar_forecast_kwh = float(forecast_val) if forecast_val else 0
        except (ValueError, TypeError):
            solar_forecast_kwh = 0

        # Calculate moon phase (0-29 day cycle)
        from datetime import date
        today = date.today()
        # Known new moon: Jan 6, 2000
        reference = date(2000, 1, 6)
        days_since = (today - reference).days
        moon_age = days_since % 29.53  # Synodic month
        moon_phase = int((moon_age / 29.53) * 8)  # 0-7 phases

        return {
            "sun_is_up": sun_is_up,
            "sun_elevation": sun_elevation,
            "weather_condition": weather_condition,
            "cloud_coverage": cloud_coverage,
            "solar_forecast_kwh": solar_forecast_kwh,
            "moon_phase": moon_phase  # 0=new, 2=first quarter, 4=full, 6=last quarter
        }
    except Exception as e:
        logger.error(f"Failed to get environment data: {e}", exc_info=True)
        return None


async def _get_consumers_data():
    """Get power consumption data for all tracked consumers."""
    config = app_state.config
    ha_client = app_state.ha_client
    last_inputs = app_state.last_inputs

    if config is None or ha_client is None:
        return None

    try:
        states = await ha_client.get_all_states()

        def get_power(entity_id):
            state = states.get(entity_id, {})
            val = state.get("state")
            if val in (None, "unavailable", "unknown", ""):
                return 0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0

        entities = config.entities

        # Define all consumers with display names and emoji icons
        consumers = [
            {"id": "boiler", "name": "Boiler", "icon": "🔥",
             "power": get_power(entities.boiler_power)},
            {"id": "ev", "name": "EV Charger", "icon": "🚗",
             "power": get_power(entities.ev_power)},
            {"id": "pool_pump", "name": "Pool Pump", "icon": "💧",
             "power": get_power(entities.pool_pump_power)},
            {"id": "pool_heater", "name": "Pool Heater", "icon": "♨️",
             "power": get_power(entities.pool_heater_power)},
            {"id": "table_heater", "name": "Table Heater", "icon": "🪑",
             "power": get_power(entities.table_heater_power)},
            {"id": "ac_living", "name": "AC Living", "icon": "❄️",
             "power": get_power(entities.ac_living_power)},
            {"id": "ac_office", "name": "AC Office", "icon": "❄️",
             "power": get_power(entities.ac_office_power)},
            {"id": "media", "name": "Media", "icon": "📺",
             "power": get_power(entities.media_power)},
            {"id": "server", "name": "Server", "icon": "🖥️",
             "power": get_power(entities.server_power)},
            {"id": "desk", "name": "Desk", "icon": "💻",
             "power": get_power(entities.desk_power)},
            {"id": "storage_fridge", "name": "Fridge (Storage)", "icon": "🧊",
             "power": get_power(entities.storage_fridge_power)},
            {"id": "kitchen_fridge", "name": "Fridge (Kitchen)", "icon": "🧊",
             "power": get_power(entities.kitchen_fridge_power)},
            {"id": "washing_machine", "name": "Washing Machine", "icon": "🧺",
             "power": get_power(entities.washing_machine_power)},
            {"id": "dishwasher", "name": "Dishwasher", "icon": "🍽️",
             "power": get_power(entities.dishwasher_power)},
            {"id": "tumble_dryer", "name": "Tumble Dryer", "icon": "👕",
             "power": get_power(entities.tumble_dryer_power)},
            {"id": "serverroom_storage", "name": "Serverroom Storage",
             "icon": "💾", "power": get_power(entities.serverroom_storage_power)},
            {"id": "chargers", "name": "Chargers", "icon": "🔌",
             "power": get_power(entities.chargers_power)},
        ]

        # Calculate totals
        # Home consumption = grid import + solar production
        total_tracked = sum(c["power"] for c in consumers)
        total_home = 0
        if last_inputs:
            total_home = last_inputs.p1_power + last_inputs.pv_power
        untracked = max(0, total_home - total_tracked)

        return {
            "items": consumers,
            "total_tracked": total_tracked,
            "total_home": total_home,
            "untracked": untracked
        }
    except Exception as e:
        logger.error(f"Failed to get consumers data: {e}", exc_info=True)
        return None


def _get_timetable_data():
    """Generate timetable data for dashboard."""
    config = app_state.config
    last_inputs = app_state.last_inputs

    if config is None or last_inputs is None:
        return None
    try:
        now = datetime.now()
        timetable = generate_schedule(now, config, last_inputs)
        # Use actual device powers where available
        if last_inputs.pool_pump_power > 0:
            pool_pump_power = int(last_inputs.pool_pump_power)
        else:
            pool_pump_power = config.frost_protection.pump_min_power
        return {
            "ev_estimate": timetable.ev_estimate,
            "boiler_estimate": timetable.boiler_estimate,
            "warnings": timetable.warnings,
            "hourly": timetable.timetable,
            "scheduled_hours": timetable.scheduled_hours or {},
            "device_powers": {
                "boiler": config.boiler.power,
                "table_heater": config.heaters.table_power,
                "pool_pump": pool_pump_power
            }
        }
    except Exception as e:
        logger.error(f"Failed to generate timetable: {e}", exc_info=True)
        return None


@app.post("/api/override/{device}",
          summary="Set device override",
          description="Set manual override mode for a device.")
async def set_override(device: str, mode: str):
    """Set manual override for a device."""
    config = app_state.config
    ha_client = app_state.ha_client

    valid_devices = ['ev', 'boiler', 'pool', 'table_heater', 'dishwasher',
                     'ac_living', 'ac_bedroom', 'ac_office', 'ac_mancave']
    valid_modes = ['auto', 'on', 'off']

    if device not in valid_devices:
        raise HTTPException(
            400, f"Invalid device. Must be one of: {valid_devices}"
        )
    if mode not in valid_modes:
        raise HTTPException(
            400, f"Invalid mode. Must be one of: {valid_modes}"
        )

    # Set the override in HA
    entities = config.entities
    entity_map = {
        'ev': entities.ovr_ev,
        'boiler': entities.ovr_boiler,
        'pool': entities.ovr_pool,
        'table_heater': entities.ovr_table_heater,
        'dishwasher': entities.ovr_dishwasher,
        'ac_living': entities.ovr_ac_living,
        'ac_bedroom': entities.ovr_ac_bedroom,
        'ac_office': entities.ovr_ac_office,
        'ac_mancave': entities.ovr_ac_mancave,
    }

    # Map API mode to HA input_select option (Dutch labels with emojis)
    mode_map = {
        'ev': {'auto': '🤖 Auto', 'on': '⚡ Laden', 'off': '⏹️ Uit'},
        'boiler': {'auto': '🤖 Auto', 'on': '🔥 Aan', 'off': '⏹️ Uit'},
        'pool': {'auto': '🤖 Auto', 'on': '🔥 Aan', 'off': '⏹️ Uit'},
        'table_heater': {'auto': '🤖 Auto', 'on': '🔥 Aan', 'off': '⏹️ Uit'},
        'dishwasher': {'auto': '🤖 Auto', 'on': '▶️ Start', 'off': '⏹️ Uit'},
        'ac_living': {'auto': '🤖 Auto', 'on': '🔥 Aan', 'off': '⏹️ Uit'},
        'ac_bedroom': {'auto': '🤖 Auto', 'on': '🔥 Aan', 'off': '⏹️ Uit'},
        'ac_office': {'auto': '🤖 Auto', 'on': '🔥 Aan', 'off': '⏹️ Uit'},
        'ac_mancave': {'auto': '🤖 Auto', 'on': '🔥 Aan', 'off': '⏹️ Uit'},
    }

    ha_mode = mode_map.get(device, {}).get(mode, mode.capitalize())

    try:
        await ha_client.call_service(
            "input_select", "select_option",
            entity_map[device],
            option=ha_mode
        )
        return {
            "status": "ok", "device": device, "mode": mode, "ha_mode": ha_mode
        }
    except Exception as e:
        logger.error(
            f"Failed to set override {device}={mode}: {e}", exc_info=True
        )
        raise HTTPException(500, str(e))


@app.get("/api/health",
         summary="Health check",
         description="Returns the health status of the Power Manager service.")
async def health():
    """Health check endpoint."""
    last_update = app_state.last_update
    return {
        "status": "ok",
        "running": app_state.running,
        "last_update": last_update.isoformat() if last_update else None
    }


@app.get("/api/limits",
         summary="Get power limits",
         description="Returns current power import limits for each tariff.")
async def get_limits():
    """Get current power limits."""
    config = app_state.config
    ha_client = app_state.ha_client

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
        entities = config.entities

        peak_state = states.get(entities.limit_peak, {})
        if peak_state.get("state") not in (None, "unavailable", "unknown"):
            limits["peak"] = int(float(peak_state["state"]))

        off_peak_state = states.get(entities.limit_off_peak, {})
        if off_peak_state.get("state") not in (None, "unavailable", "unknown"):
            limits["off_peak"] = int(float(off_peak_state["state"]))

        super_state = states.get(entities.limit_super_off_peak, {})
        if super_state.get("state") not in (None, "unavailable", "unknown"):
            limits["super_off_peak"] = int(float(super_state["state"]))
    except Exception as e:
        logger.warning(f"Could not read limits from HA: {e}")

    return limits


@app.post("/api/limits")
async def set_limits(
    peak: int = None,
    off_peak: int = None,
    super_off_peak: int = None
):
    """Set power limits via HA input_numbers."""
    config = app_state.config
    ha_client = app_state.ha_client

    if config is None:
        return JSONResponse({"error": "Not initialized"}, status_code=503)

    results = {}
    entities = config.entities

    try:
        if peak is not None:
            await ha_client.call_service(
                "input_number", "set_value",
                entities.limit_peak,
                value=peak
            )
            config.max_import.peak = peak
            results["peak"] = peak

        if off_peak is not None:
            await ha_client.call_service(
                "input_number", "set_value",
                entities.limit_off_peak,
                value=off_peak
            )
            config.max_import.off_peak = off_peak
            results["off_peak"] = off_peak

        if super_off_peak is not None:
            await ha_client.call_service(
                "input_number", "set_value",
                entities.limit_super_off_peak,
                value=super_off_peak
            )
            config.max_import.super_off_peak = super_off_peak
            results["super_off_peak"] = super_off_peak

        return {"status": "ok", "updated": results}
    except Exception as e:
        logger.error(f"Failed to set limits: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@app.get("/api/schedule")
async def get_schedule():
    """Get 24-hour schedule/plan with timetable."""
    config = app_state.config
    last_inputs = app_state.last_inputs

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
    """Run the server with HTTPS."""
    import uvicorn
    from pathlib import Path

    # Load config to get port setting
    startup_config = load_config()
    port = startup_config.port

    # SSL certificate paths (Let's Encrypt format)
    ssl_dir = Path(__file__).parent.parent / "ssl"
    ssl_keyfile = ssl_dir / "privkey.pem"
    ssl_certfile = ssl_dir / "fullchain.pem"

    # Use HTTPS if certificates exist, otherwise fall back to HTTP
    ssl_config = {}
    if ssl_keyfile.exists() and ssl_certfile.exists():
        ssl_config = {
            "ssl_keyfile": str(ssl_keyfile),
            "ssl_certfile": str(ssl_certfile),
        }
        logger.info(f"Starting with HTTPS (certificates from {ssl_dir})")
    else:
        logger.warning("SSL certificates not found, starting with HTTP")

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        **ssl_config
    )


if __name__ == "__main__":
    main()
