"""
Power Manager Decision Engine

Core decision logic ported from JavaScript (src/logic/decisions.js).
Determines optimal device states based on power availability and tariffs.
"""

from datetime import datetime
from typing import Optional

from .config import Config
from .models import (
    PowerInputs, Decisions, DecisionResult, Alert,
    DeviceDecision, EVDecision, ACDecision,
    AllDeviceStates, DeviceState, EVState
)
from .tariff import get_tariff, get_max_import, is_summer, get_ev_status_text

# Power thresholds (Watts)
MIN_EXPORT_FOR_BOILER = 500
DW_EXPECTED_POWER = 1900
MIN_SOLAR_SURPLUS = 500
MAX_GRID_IMPORT_FOR_EV = 1000
DW_RUNNING_THRESHOLD = 50


def fmt_w(watts: float) -> str:
    """Format watts for display."""
    if abs(watts) >= 1000:
        return f"{watts / 1000:.1f}kW"
    return f"{watts:.0f}W"


def grid_indicator(p1: float, max_import: int) -> str:
    """Get grid usage indicator."""
    if p1 < 0:
        return "[<<<]"  # Exporting
    ratio = p1 / max_import if max_import > 0 else 0
    if ratio < 0.5:
        return "[---]"  # Low usage
    elif ratio < 0.8:
        return "[==-]"  # Medium usage
    elif ratio < 1.0:
        return "[==|]"  # High usage
    else:
        return "[!!!]"  # Over limit


def can_switch_device(
    device_state: DeviceState,
    target_on: bool,
    now: float,
    min_on_time: int,
    min_off_time: int
) -> bool:
    """Check if device can be switched (respecting hysteresis)."""
    if device_state.last_change == 0:
        return True

    elapsed = now - device_state.last_change

    if device_state.on and not target_on:
        # Turning off - must have been on for min_on_time
        return elapsed >= (min_on_time * 1000)
    elif not device_state.on and target_on:
        # Turning on - must have been off for min_off_time
        return elapsed >= (min_off_time * 1000)

    return True


def parse_override(value: str) -> str:
    """Parse override value to standard format."""
    if not value or value.lower() in ('', 'auto', 'automatic'):
        return 'auto'
    if value.lower() in ('on', 'aan', 'force_on', 'force on'):
        return 'on'
    if value.lower() in ('off', 'uit', 'force_off', 'force off'):
        return 'off'
    return 'auto'


def calculate_available_amps(total_watts: float, watts_per_amp: int) -> int:
    """Calculate available amps from watts, with division by zero guard.

    Args:
        total_watts: Total power available in watts.
        watts_per_amp: Power consumption per amp (must be > 0 for valid result).

    Returns:
        Available amps as integer. Returns 0 if watts_per_amp is 0 or negative.
    """
    if watts_per_amp <= 0:
        return 0
    return int(total_watts / watts_per_amp)


def is_boiler_full(
    boiler_on: bool,
    boiler_power: float,
    idle_threshold: int,
    device_state: AllDeviceStates,
    now_ts: float,
    confirm_seconds: int
) -> bool:
    """
    Determine if boiler is "full" (reached temperature and stopped heating).

    Uses time-based confirmation to avoid false positives from sensor glitches.
    Power must be below idle_threshold for confirm_seconds to be considered "full".

    Args:
        boiler_on: Whether boiler switch is on
        boiler_power: Current power draw in watts
        idle_threshold: Power threshold below which boiler is considered idle
        device_state: All device states for tracking timing
        now_ts: Current timestamp in milliseconds
        confirm_seconds: Seconds power must be low to confirm "full"

    Returns:
        True if boiler is confirmed full, False otherwise
    """
    if not boiler_on:
        # Boiler is off, reset tracking and return not full
        device_state.boiler_low_power_since = 0.0
        return False

    power_is_low = boiler_power < idle_threshold

    if power_is_low:
        # Power is low - check if we've been tracking this
        if device_state.boiler_low_power_since == 0.0:
            # Just dropped below threshold, start tracking
            device_state.boiler_low_power_since = now_ts
            return False
        else:
            # Already tracking - check if confirmation time has passed
            elapsed_ms = now_ts - device_state.boiler_low_power_since
            elapsed_seconds = elapsed_ms / 1000
            if elapsed_seconds >= confirm_seconds:
                return True
            else:
                # Still waiting for confirmation
                return False
    else:
        # Power is above threshold - reset tracking
        device_state.boiler_low_power_since = 0.0
        return False


def calculate_decisions(
    inputs: PowerInputs,
    config: Config,
    device_state: AllDeviceStates,
    now: Optional[datetime] = None
) -> DecisionResult:
    """Calculate optimal device states based on current power conditions.

    This is the main entry point for the Power Manager decision engine. It
    analyzes current power consumption, solar production, tariff period, and
    device states to determine the optimal action for each controllable device.

    The function orchestrates the entire decision-making flow:
    1. Gather current state (tariff, power, device states, overrides)
    2. Apply manual overrides (force on/off from Home Assistant helpers)
    3. Check frost protection for pool pump
    4. Check BMW battery levels for evening alerts
    5. Apply seasonal logic (winter heating vs summer solar optimization)
    6. Calculate final power headroom

    Args:
        inputs: PowerInputs containing all sensor readings from Home Assistant:
            - p1_power: Grid import/export from P1 meter (W, negative = export)
            - pv_power: Solar PV production (W)
            - Device states (boiler, EV, heaters, etc.)
            - Override helper states (ovr_boiler, ovr_ev, etc.)
            - Temperature sensors and BMW car data
        config: Config object with power limits, device ratings, and timing:
            - max_import: Power limits per tariff period
            - ev: EV charger settings (amps, watts_per_amp)
            - boiler: Boiler power and deadlines
            - timing: Hysteresis and min on/off times
        device_state: AllDeviceStates tracking when each device last changed,
            used to enforce minimum on/off times and prevent rapid cycling.
        now: Optional datetime for testing. Defaults to current time.

    Returns:
        DecisionResult containing:
            - decisions: Decisions object with action for each device
              ('on', 'off', 'adjust', 'none')
            - plan: List of human-readable strings explaining each decision
            - headroom: Remaining power capacity in watts after decisions
            - alerts: List of Alert objects for notifications (frost, low battery)
            - meta: Dict with tariff info, power readings, season, etc.

    Example:
        >>> inputs = PowerInputs(p1_power=500, pv_power=2000, ...)
        >>> config = load_config()
        >>> device_state = AllDeviceStates()
        >>> result = calculate_decisions(inputs, config, device_state)
        >>> if result.decisions.boiler.action == 'on':
        ...     ha_client.turn_on('switch.storage_boiler')
    """
    if now is None:
        now = datetime.now()

    now_ts = now.timestamp() * 1000  # Convert to milliseconds for JS compatibility

    # Get tariff info
    tariff, tariff_info = get_tariff(now)
    max_import = get_max_import(tariff, config)
    summer = is_summer(now)

    # Calculate power values (default to 0 if None during HA startup)
    p1 = inputs.p1_power if inputs.p1_power is not None else 0  # Grid import (W)
    pv = inputs.pv_power if inputs.pv_power is not None else 0  # Solar production (W)

    # Available power = max_import - current_import + solar
    # But we calculate based on actual consumption
    avail = max_import - p1

    is_exporting = p1 < 0
    hyst = config.timing.hysteresis

    # Parse overrides
    ovr = {
        'ev': parse_override(inputs.ovr_ev),
        'boiler': parse_override(inputs.ovr_boiler),
        'pool': parse_override(inputs.ovr_pool),
        'table_heater': parse_override(inputs.ovr_table_heater),
        'ac_living': parse_override(inputs.ovr_ac_living),
        'ac_bedroom': parse_override(inputs.ovr_ac_bedroom),
        'ac_office': parse_override(inputs.ovr_ac_office),
        'ac_mancave': parse_override(inputs.ovr_ac_mancave),
        'dishwasher': parse_override(inputs.ovr_dishwasher),
    }

    # Device current states
    ev_state = inputs.ev_state
    ev_limit = inputs.ev_limit
    boiler_on = inputs.boiler_switch == 'on'
    boiler_power = inputs.boiler_power
    boiler_force = inputs.boiler_force == 'on'
    # Use time-based confirmation to avoid false "full" detection from sensor glitches
    boiler_full = is_boiler_full(
        boiler_on=boiler_on,
        boiler_power=boiler_power,
        idle_threshold=config.boiler.idle_threshold,
        device_state=device_state,
        now_ts=now_ts,
        confirm_seconds=config.boiler.full_confirm_seconds
    )

    # EV states
    ev_plugged = ev_state in (EVState.READY, EVState.CHARGING, EVState.FULL)
    ev_ready = ev_state == EVState.READY
    ev_charging = ev_state == EVState.CHARGING
    ev_done = ev_state == EVState.FULL
    ev_status_text = get_ev_status_text(ev_state)

    # Heaters and AC
    hr_on = inputs.heater_right_switch == 'on'
    ht_on = inputs.heater_table_switch == 'on'

    # Dishwasher
    dw_switch_on = inputs.dishwasher_switch == 'on'
    dw_power = inputs.dishwasher_power
    dw_running = dw_power > DW_RUNNING_THRESHOLD  # Actually running a cycle (drawing power)
    dw_waiting = dw_switch_on and dw_power < DW_RUNNING_THRESHOLD  # Switch on but not running yet

    ac_states = {
        'living': inputs.ac_living_state,
        'mancave': inputs.ac_mancave_state,
        'office': inputs.ac_office_state,
        'bedroom': inputs.ac_bedroom_state,
    }

    temps = {
        'living': inputs.temp_living,
        'bedroom': inputs.temp_bedroom,
        'mancave': inputs.temp_mancave,
    }

    # Helper for timing checks
    def can_switch(name: str, target_on: bool) -> bool:
        state = getattr(device_state, name.replace('-', '_'))
        return can_switch_device(
            state, target_on, now_ts,
            config.timing.min_on_time,
            config.timing.min_off_time
        )

    # Initialize decisions
    decisions = Decisions()
    decisions.ev.amps = ev_limit

    # Alerts and plan
    alerts: list[Alert] = []
    plan: list[str] = []

    # Build status line
    tariff_label = tariff.upper().replace('-', ' ')
    grid_icon = grid_indicator(p1, max_import)
    plan.append(f"{tariff_label} {grid_icon} | Grid: {fmt_w(p1)} | PV: {fmt_w(pv)} | Avail: {fmt_w(avail)}")
    plan.append(f"{'Summer' if summer else 'Winter'} | EV: {ev_status_text}")

    # Track available headroom
    headroom = avail

    # === MANUAL OVERRIDES ===
    _apply_manual_overrides(decisions, plan, ovr, {
        'ev_plugged': ev_plugged,
        'ev_limit': ev_limit,
        'boiler_on': boiler_on,
        'config': config,
    })

    # Force boiler
    if boiler_force and not boiler_full and ovr['boiler'] == 'auto':
        decisions.boiler.action = 'on'
        plan.append('Boiler: FORCE ON')

    # === FROST PROTECTION ===
    frost_result = check_frost_protection(inputs, config, device_state, now_ts)
    if frost_result['pool_pump_decision'].action != 'none':
        decisions.pool_pump = frost_result['pool_pump_decision']
    plan.extend(frost_result['plan_entries'])
    alerts.extend(frost_result['alerts'])

    # === BMW LOW BATTERY CHECK ===
    bmw_result = check_bmw_low_battery(inputs, config, now)
    plan.extend(bmw_result['plan_entries'])
    alerts.extend(bmw_result['alerts'])

    # === SEASONAL LOGIC ===
    if not summer:
        _apply_winter_logic(decisions, plan, {
            'ovr': ovr,
            'ev_done': ev_done,
            'ev_plugged': ev_plugged,
            'ev_ready': ev_ready,
            'ev_charging': ev_charging,
            'ev_limit': ev_limit,
            'boiler_on': boiler_on,
            'boiler_full': boiler_full,
            'boiler_force': boiler_force,
            'hr_on': hr_on,
            'ht_on': ht_on,
            'dw_switch_on': dw_switch_on,
            'dw_power': dw_power,
            'dw_running': dw_running,
            'dw_waiting': dw_waiting,
            'ac_states': ac_states,
            'temps': temps,
            'headroom': headroom,
            'hyst': hyst,
            'tariff': tariff,
            'tariff_info': tariff_info,
            'date': now,
            'config': config,
            'can_switch': can_switch,
            'device_state': device_state,
            'now': now_ts,
            'is_exporting': is_exporting,
            'pv': pv,
            'p1': p1,
        })
    else:
        _apply_summer_logic(decisions, plan, {
            'ovr': ovr,
            'ev_done': ev_done,
            'ev_plugged': ev_plugged,
            'ev_ready': ev_ready,
            'ev_charging': ev_charging,
            'ev_limit': ev_limit,
            'boiler_on': boiler_on,
            'boiler_full': boiler_full,
            'dw_switch_on': dw_switch_on,
            'dw_power': dw_power,
            'dw_running': dw_running,
            'dw_waiting': dw_waiting,
            'ac_states': ac_states,
            'temps': temps,
            'headroom': headroom,
            'hyst': hyst,
            'tariff': tariff,
            'tariff_info': tariff_info,
            'config': config,
            'can_switch': can_switch,
            'device_state': device_state,
            'now': now_ts,
            'is_exporting': is_exporting,
            'pv': pv,
            'p1': p1,
        })

    # Calculate final headroom
    headroom = _calculate_final_headroom(avail, decisions, config, {
        'boiler_on': boiler_on,
        'ev_charging': ev_charging,
        'ev_limit': ev_limit,
        'ht_on': ht_on,
    })

    plan.append(f"Available: {fmt_w(headroom)}")

    return DecisionResult(
        decisions=decisions,
        plan=plan,
        headroom=headroom,
        alerts=alerts,
        meta={
            'tariff': tariff,
            'p1': p1,
            'pv': pv,
            'avail': avail,
            'is_summer': summer,
            'is_exporting': is_exporting,
            'ovr': ovr,
            'pool_ambient_temp': inputs.pool_ambient_temp,
        }
    )


def _apply_manual_overrides(decisions: Decisions, plan: list, ovr: dict, ctx: dict):
    """Apply manual override decisions."""
    # EV override
    if ovr['ev'] == 'on' and ctx['ev_plugged']:
        decisions.ev.action = 'on'
        decisions.ev.amps = ctx['config'].ev.max_amps
        plan.append(f"EV: OVERRIDE ON ({decisions.ev.amps}A)")
    elif ovr['ev'] == 'off':
        decisions.ev.action = 'off'
        plan.append("EV: OVERRIDE OFF")

    # Boiler override
    if ovr['boiler'] == 'on':
        decisions.boiler.action = 'on'
        plan.append("Boiler: OVERRIDE ON")
    elif ovr['boiler'] == 'off':
        decisions.boiler.action = 'off'
        plan.append("Boiler: OVERRIDE OFF")

    # Pool override
    if ovr['pool'] == 'on':
        decisions.pool.action = 'on'
        plan.append("Pool: OVERRIDE ON")
    elif ovr['pool'] == 'off':
        decisions.pool.action = 'off'
        plan.append("Pool: OVERRIDE OFF")

    # Table heater override
    if ovr['table_heater'] == 'on':
        decisions.heater_table.action = 'on'
        plan.append("Table heater: OVERRIDE ON")
    elif ovr['table_heater'] == 'off':
        decisions.heater_table.action = 'off'
        plan.append("Table heater: OVERRIDE OFF")

    # Dishwasher override
    if ovr.get('dishwasher') == 'on':
        decisions.dishwasher.action = 'on'
        plan.append("Dishwasher: OVERRIDE ON")
    elif ovr.get('dishwasher') == 'off':
        decisions.dishwasher.action = 'off'
        plan.append("Dishwasher: OVERRIDE OFF")


def _handle_boiler_winter(
    decisions: Decisions,
    plan: list,
    ctx: dict,
    effective_headroom: float
) -> tuple[float, float]:
    """Handle boiler logic for winter mode.

    Determines whether to turn the boiler on/off based on tariff, solar surplus,
    force heat mode, and deadline approaching. The boiler has priority 2 (after
    frost protection) because hot water is essential.

    Args:
        decisions: Decisions object to update with boiler action.
        plan: List of strings to append decision rationale.
        ctx: Context dictionary with ovr, config, can_switch, tariff, etc.
        effective_headroom: Current available power capacity in watts.

    Returns:
        Tuple of (boiler_will_use, updated_effective_headroom) where
        boiler_will_use is the power reserved for the boiler.
    """
    ovr = ctx['ovr']
    hyst = ctx['hyst']
    config = ctx['config']
    can_switch = ctx['can_switch']
    tariff = ctx['tariff']

    boiler_will_use = 0
    hour = ctx['date'].hour + ctx['date'].minute / 60
    deadline = config.boiler.deadline_winter
    boiler_force = ctx.get('boiler_force', False)
    is_exporting = ctx.get('is_exporting', False)

    if ovr['boiler'] != 'auto':
        return boiler_will_use, effective_headroom

    # Force heat overrides everything - heat anytime
    if boiler_force and not ctx['boiler_full']:
        if not ctx['boiler_on']:
            if can_switch('boiler', True):
                decisions.boiler.action = 'on'
                boiler_will_use = config.boiler.power
                effective_headroom -= boiler_will_use
                plan.append("Boiler: ON (force heat)")
        else:
            boiler_will_use = config.boiler.power
            effective_headroom -= boiler_will_use
        return boiler_will_use, effective_headroom

    if tariff == 'peak' and ctx['boiler_on'] and not boiler_force:
        # Turn off during peak (unless force heat)
        if hour > deadline and can_switch('boiler', False):
            decisions.boiler.action = 'off'
            plan.append("Boiler: OFF (peak tariff)")
        return boiler_will_use, effective_headroom

    if not ctx['boiler_full']:
        # Determine if we should heat
        approaching_deadline = hour >= (deadline - 2) and hour < deadline
        enough_power = effective_headroom > config.boiler.power + hyst

        # Solar surplus logic: if exporting significant power, use boiler
        p1 = ctx.get('p1', 0)
        export_power = abs(p1) if is_exporting else 0
        has_solar_surplus = is_exporting and export_power > MIN_EXPORT_FOR_BOILER

        # Only heat during:
        # 1. Super off-peak (cheapest rate, 01:00-07:00)
        # 2. Solar surplus (better to use than sell)
        # 3. Approaching deadline (need hot water by morning)
        should_heat = False
        reason = ""

        if tariff == 'super-off-peak' and enough_power:
            should_heat = True
            reason = "super-off-peak"
        elif has_solar_surplus:
            should_heat = True
            reason = f"solar ({int(export_power)}W export)"
        elif approaching_deadline and tariff in ('off-peak', 'super-off-peak'):
            should_heat = True
            reason = "approaching deadline"

        if should_heat and not ctx['boiler_on']:
            if can_switch('boiler', True):
                decisions.boiler.action = 'on'
                boiler_will_use = config.boiler.power
                effective_headroom -= boiler_will_use
                plan.append(f"Boiler: ON ({reason})")
        elif ctx['boiler_on']:
            # Boiler already on, reserve its power
            boiler_will_use = config.boiler.power
            effective_headroom -= boiler_will_use

    return boiler_will_use, effective_headroom


def _handle_ev_winter(
    decisions: Decisions,
    plan: list,
    ctx: dict,
    effective_headroom: float,
    boiler_will_use: float
) -> float:
    """Handle EV charging logic for winter mode.

    Manages EV charging based on tariff periods and available capacity.
    During super-off-peak, EV can charge alongside boiler. During off-peak,
    EV only charges if boiler is idle. Charging stops during peak tariff.

    Args:
        decisions: Decisions object to update with EV action.
        plan: List of strings to append decision rationale.
        ctx: Context dictionary with ev states, config, can_switch, etc.
        effective_headroom: Current available power capacity in watts.
        boiler_will_use: Power reserved for boiler (affects off-peak logic).

    Returns:
        Updated effective_headroom after accounting for EV charging.
    """
    ovr = ctx['ovr']
    hyst = ctx['hyst']
    config = ctx['config']
    can_switch = ctx['can_switch']
    tariff = ctx['tariff']

    if ovr['ev'] != 'auto' or not ctx['ev_plugged'] or ctx['ev_done']:
        return effective_headroom

    # When EV is already charging, its power is included in p1.
    # To calculate target amps, we need TOTAL power available for EV.
    current_ev_watts = ctx['ev_limit'] * config.ev.watts_per_amp if ctx['ev_charging'] else 0

    if tariff == 'super-off-peak':
        # Super off-peak (8kW limit) - plenty of room for EV
        total_for_ev = effective_headroom + current_ev_watts - hyst
        available_amps = calculate_available_amps(total_for_ev, config.ev.watts_per_amp)
        target_amps = max(config.ev.min_amps, min(available_amps, config.ev.max_amps))

        if ctx['ev_charging']:
            amp_diff = abs(target_amps - ctx['ev_limit'])
            if amp_diff >= config.ev.amp_change_threshold:
                decisions.ev.action = 'adjust'
                decisions.ev.amps = target_amps
                plan.append(f"EV: adjust to {target_amps}A")
        elif ctx['ev_ready'] and target_amps >= config.ev.min_amps:
            if can_switch('ev', True):
                decisions.ev.action = 'on'
                decisions.ev.amps = target_amps
                effective_headroom -= target_amps * config.ev.watts_per_amp
                plan.append(f"EV: START at {target_amps}A (super-off-peak)")

    elif tariff == 'off-peak':
        # Off-peak (5kW limit) - only charge if boiler not needed
        if boiler_will_use == 0 and not ctx['boiler_on']:
            total_for_ev = effective_headroom + current_ev_watts - hyst
            available_amps = calculate_available_amps(total_for_ev, config.ev.watts_per_amp)
            target_amps = max(config.ev.min_amps, min(available_amps, config.ev.max_amps))

            if ctx['ev_charging']:
                amp_diff = abs(target_amps - ctx['ev_limit'])
                if amp_diff >= config.ev.amp_change_threshold:
                    decisions.ev.action = 'adjust'
                    decisions.ev.amps = target_amps
                    plan.append(f"EV: adjust to {target_amps}A")
            elif ctx['ev_ready'] and target_amps >= config.ev.min_amps:
                if can_switch('ev', True):
                    decisions.ev.action = 'on'
                    decisions.ev.amps = target_amps
                    effective_headroom -= target_amps * config.ev.watts_per_amp
                    plan.append(f"EV: START at {target_amps}A (off-peak, boiler idle)")
        elif ctx['ev_charging']:
            # EV already charging but boiler needs power - reduce or stop EV
            if can_switch('ev', False):
                decisions.ev.action = 'off'
                plan.append("EV: PAUSE (boiler priority)")

    elif tariff == 'peak' and ctx['ev_charging']:
        # Stop charging during peak
        if can_switch('ev', False):
            decisions.ev.action = 'off'
            plan.append("EV: STOP (peak tariff)")

    return effective_headroom


def _handle_heater_winter(
    decisions: Decisions,
    plan: list,
    ctx: dict,
    effective_headroom: float
) -> None:
    """Handle table heater logic for winter mode.

    The table heater has the lowest priority (4) and uses remaining capacity
    after boiler and EV. Prefers super-off-peak but may use off-peak if EV
    needs the super-off-peak capacity.

    Args:
        decisions: Decisions object to update with heater action.
        plan: List of strings to append decision rationale.
        ctx: Context dictionary with heater states, config, can_switch, etc.
        effective_headroom: Current available power capacity in watts.
    """
    ovr = ctx['ovr']
    hyst = ctx['hyst']
    config = ctx['config']
    can_switch = ctx['can_switch']
    tariff = ctx['tariff']

    if ovr['table_heater'] != 'auto':
        return

    table_power = config.heaters.table_power
    ht_on = ctx['ht_on']

    # Calculate remaining capacity
    remaining = effective_headroom
    if ctx['ev_charging'] and decisions.ev.action == 'none':
        remaining -= ctx['ev_limit'] * config.ev.watts_per_amp
    enough_power = remaining > table_power + hyst

    # Check if EV will use most of super-off-peak capacity
    ev_needs_capacity = ctx['ev_plugged'] and not ctx['ev_done']

    if tariff == 'super-off-peak':
        if not ht_on and enough_power:
            if can_switch('heater_table', True):
                decisions.heater_table.action = 'on'
                plan.append("Table heater: ON (super-off-peak)")
        elif ht_on and remaining < table_power - hyst:
            if can_switch('heater_table', False):
                decisions.heater_table.action = 'off'
                plan.append("Table heater: OFF (capacity needed)")

    elif tariff == 'off-peak':
        # Use off-peak if EV will need the super-off-peak capacity
        if ev_needs_capacity and enough_power:
            if not ht_on:
                if can_switch('heater_table', True):
                    decisions.heater_table.action = 'on'
                    plan.append("Table heater: ON (off-peak, EV needs super-off-peak)")
        elif ht_on and not ev_needs_capacity:
            # No EV charging needed, save for super-off-peak
            if can_switch('heater_table', False):
                decisions.heater_table.action = 'off'
                plan.append("Table heater: OFF (save for super-off-peak)")

    elif tariff == 'peak' and ht_on:
        if can_switch('heater_table', False):
            decisions.heater_table.action = 'off'
            plan.append("Table heater: OFF (peak tariff)")


def _apply_winter_logic(decisions: Decisions, plan: list, ctx: dict):
    """Apply winter heating and charging logic based on tariff periods.

    This function orchestrates the decision-making for winter months by
    delegating to specialized handler functions for each device type.
    It manages device scheduling to minimize electricity costs while
    ensuring essential needs (hot water, vehicle charging) are met.

    Priority Order:
        1. Frost Protection - Handled separately before this function
        2. Boiler (hot water) - Essential, runs during super-off-peak or solar
        3. EV Charging - Uses remaining capacity after boiler
        4. Table Heater - Comfort device, lowest priority
        5. Dishwasher - Smart scheduled via separate logic

    Key Logic Branches:
        - Super-off-peak (01:00-07:00): Both boiler and EV can run together
          with 8kW limit. Table heater uses any remaining capacity.
        - Off-peak (varies): EV only charges if boiler is idle. 5kW limit.
        - Peak (07:00-11:00, 17:00-22:00): Devices turned off to avoid high
          tariff, except for force overrides and deadline approaching.
        - Solar surplus: Boiler runs even during peak if exporting >500W.

    Args:
        decisions: Decisions object to populate with device actions.
        plan: List of strings describing the decision rationale.
        ctx: Context dictionary containing current state and configuration.
    """
    headroom = ctx['headroom']

    # Track effective headroom as we make decisions
    effective_headroom = headroom

    # === BOILER FIRST (Priority 2 - hot water is essential!) ===
    boiler_will_use, effective_headroom = _handle_boiler_winter(
        decisions, plan, ctx, effective_headroom
    )

    # === EV CHARGING (Priority 3 - use remaining capacity) ===
    effective_headroom = _handle_ev_winter(
        decisions, plan, ctx, effective_headroom, boiler_will_use
    )

    # === TABLE HEATER (Priority 4 - lowest, use remaining capacity) ===
    _handle_heater_winter(decisions, plan, ctx, effective_headroom)

    # === DISHWASHER (Priority 5 - smart scheduling) ===
    # Never interrupt running cycles, optimize start time for tariffs/solar
    _apply_dishwasher_logic(decisions, plan, ctx)


def _apply_dishwasher_logic(decisions: Decisions, plan: list, ctx: dict):
    """
    Apply dishwasher smart scheduling logic.

    Rules:
    - NEVER interrupt a running cycle (power > 50W)
    - Check available headroom before allowing run
    - If solar surplus: allow run (free power)
    - If off-peak or super-off-peak: allow run (cheap)
    - If peak, no solar, off-peak soon: hold until cheap rate
    """
    ovr = ctx.get('ovr', {})
    if ovr.get('dishwasher') != 'auto':
        return  # Override already handled

    dw_running = ctx.get('dw_running', False)
    dw_waiting = ctx.get('dw_waiting', False)
    dw_switch_on = ctx.get('dw_switch_on', False)
    dw_power = ctx.get('dw_power', 0)
    is_exporting = ctx.get('is_exporting', False)
    tariff = ctx.get('tariff', 'peak')
    tariff_info = ctx.get('tariff_info', {})
    p1 = ctx.get('p1', 0)
    headroom = ctx.get('headroom', 0)
    hyst = ctx.get('hyst', 100)

    # Dishwasher power consumption (peak during heating phases)
    # DW_EXPECTED_POWER = ~1850W peak, use 1900 for safety margin

    # Minimum solar export to consider "solar surplus"
    # MIN_SOLAR_SURPLUS = 500W export = good solar

    # If dishwasher is running (drawing power), NEVER interrupt
    if dw_running:
        plan.append(f"Dishwasher: RUNNING ({dw_power:.0f}W)")
        return

    # If dishwasher is not active at all, nothing to do
    if not dw_switch_on:
        return

    # Dishwasher is waiting to run (switch on, but not yet drawing power)
    # This happens when the user has loaded the dishwasher and turned it on,
    # waiting for the smart scheduling to release it

    if dw_waiting:
        has_solar_surplus = is_exporting and abs(p1) > MIN_SOLAR_SURPLUS
        is_cheap_tariff = tariff in ('off-peak', 'super-off-peak')

        # Check if we have enough headroom for the dishwasher
        # Account for already running devices
        available_power = headroom - hyst
        has_enough_power = available_power > DW_EXPECTED_POWER

        # Determine when next cheap rate starts (for display)
        next_change = tariff_info.get('next_change', 0)
        date = ctx.get('date')
        current_hour = date.hour if date else 0

        if has_solar_surplus:
            # Solar surplus - allow run, free power!
            # Solar covers the consumption, no grid limit concern
            decisions.dishwasher.action = 'on'
            decisions.dishwasher.reason = 'solar surplus'
            plan.append(f"Dishwasher: RUN (solar surplus {abs(p1):.0f}W)")
        elif is_cheap_tariff and has_enough_power:
            # Off-peak or super-off-peak with enough headroom - allow run
            decisions.dishwasher.action = 'on'
            decisions.dishwasher.reason = tariff
            plan.append(f"Dishwasher: RUN ({tariff}, {available_power:.0f}W avail)")
        elif is_cheap_tariff and not has_enough_power:
            # Cheap tariff but not enough power - wait for other devices to finish
            # Don't turn off the switch - user may be selecting a program
            decisions.dishwasher.action = 'none'
            decisions.dishwasher.reason = 'waiting for headroom'
            plan.append(f"Dishwasher: WAITING (need {DW_EXPECTED_POWER}W, have {available_power:.0f}W)")
        else:
            # Peak rate, no solar - hold until cheap rate
            # Don't turn off the switch - user may be selecting a program
            decisions.dishwasher.action = 'none'
            decisions.dishwasher.reason = 'waiting for cheap rate'

            # Calculate wait time for display
            if next_change > current_hour:
                wait_hours = next_change - current_hour
            else:
                wait_hours = (24 - current_hour) + next_change

            plan.append(f"Dishwasher: WAITING (off-peak in {wait_hours}h)")


def _apply_summer_logic(decisions: Decisions, plan: list, ctx: dict):
    """Apply summer solar optimization logic."""
    ovr = ctx['ovr']
    headroom = ctx['headroom']
    hyst = ctx['hyst']
    config = ctx['config']
    can_switch = ctx['can_switch']
    is_exporting = ctx['is_exporting']
    pv = ctx['pv']

    # EV Charging - solar-assisted charging
    # Allow up to 1kW grid import when solar is good (better than exporting all)
    p1 = ctx.get('p1', 0)

    if ovr['ev'] == 'auto' and ctx['ev_plugged'] and not ctx['ev_done']:
        # Good solar: either exporting, or importing less than threshold
        has_good_solar = pv > 1500 and (is_exporting or p1 < MAX_GRID_IMPORT_FOR_EV)

        if has_good_solar:
            # Calculate available power for EV
            # If exporting: we can use export + allowed import
            # If importing < threshold: we can use (threshold - current import)
            if is_exporting:
                # Exporting = can use all export + allowed import buffer
                available_power = abs(p1) + MAX_GRID_IMPORT_FOR_EV
            else:
                # Already importing, but under threshold
                available_power = MAX_GRID_IMPORT_FOR_EV - p1

            # When EV is already charging, add back its consumption
            current_ev_watts = ctx['ev_limit'] * config.ev.watts_per_amp if ctx['ev_charging'] else 0
            total_for_ev = available_power + current_ev_watts - hyst

            available_amps = calculate_available_amps(total_for_ev, config.ev.watts_per_amp)
            target_amps = max(config.ev.min_amps, min(available_amps, config.ev.max_amps))

            if ctx['ev_ready'] and target_amps >= config.ev.min_amps:
                if can_switch('ev', True):
                    decisions.ev.action = 'on'
                    decisions.ev.amps = target_amps
                    solar_pct = int((pv / (target_amps * config.ev.watts_per_amp)) * 100)
                    plan.append(f"EV: SOLAR START {target_amps}A (~{solar_pct}% solar)")
            elif ctx['ev_charging']:
                amp_diff = abs(target_amps - ctx['ev_limit'])
                if amp_diff >= config.ev.amp_change_threshold:
                    if target_amps >= config.ev.min_amps:
                        decisions.ev.action = 'adjust'
                        decisions.ev.amps = target_amps
                        plan.append(f"EV: adjust to {target_amps}A (solar)")
                    else:
                        decisions.ev.action = 'off'
                        plan.append("EV: STOP (insufficient solar)")
        elif ctx['ev_charging'] and p1 > MAX_GRID_IMPORT_FOR_EV:
            # Importing too much from grid, stop or reduce
            if can_switch('ev', False):
                decisions.ev.action = 'off'
                plan.append("EV: STOP (grid import too high)")

    # Boiler - use solar surplus
    if ovr['boiler'] == 'auto' and not ctx['boiler_full']:
        if is_exporting and pv > config.boiler.power:
            if not ctx['boiler_on'] and can_switch('boiler', True):
                decisions.boiler.action = 'on'
                plan.append("Boiler: ON (solar surplus)")
        elif ctx['boiler_on'] and not is_exporting:
            if can_switch('boiler', False):
                decisions.boiler.action = 'off'
                plan.append("Boiler: OFF (no surplus)")

    # === DISHWASHER (smart scheduling) ===
    # Same logic as winter - optimize for solar/cheap tariffs
    _apply_dishwasher_logic(decisions, plan, ctx)


def check_frost_protection(
    inputs: PowerInputs,
    config: Config,
    device_state: AllDeviceStates,
    now: float
) -> dict:
    """Check frost protection status for pool pump."""
    alerts: list[Alert] = []
    plan_entries: list[str] = []
    pool_pump_decision = DeviceDecision()

    fp = config.frost_protection
    if not fp.enabled:
        return {'alerts': alerts, 'pool_pump_decision': pool_pump_decision, 'plan_entries': plan_entries}

    ambient_temp = inputs.pool_ambient_temp
    pump_switch_on = inputs.pool_pump_switch == 'on'
    pump_power = inputs.pool_pump_power
    min_pump_power = fp.pump_min_power

    # Pump is only truly running if switch is on AND drawing power
    pump_actually_running = pump_switch_on and pump_power >= min_pump_power

    # No temperature reading available
    if ambient_temp is None:
        plan_entries.append('Frost: No temp sensor')
        return {'alerts': alerts, 'pool_pump_decision': pool_pump_decision, 'plan_entries': plan_entries}

    temp_threshold = fp.temp_threshold
    critical_threshold = fp.critical_threshold
    alert_delay = fp.pump_off_alert_delay * 1000  # convert to ms

    # Check if it's cold
    if ambient_temp <= temp_threshold:
        is_critical = ambient_temp <= critical_threshold

        if not pump_actually_running:
            # Pump is off or not drawing power during cold temps - dangerous!
            pump_off_since = device_state.pool_pump.last_change or now
            pump_off_duration = now - pump_off_since

            # Force pump on
            pool_pump_decision.action = 'on'

            # Build descriptive message
            if not pump_switch_on:
                reason = 'switch OFF'
            elif pump_power < min_pump_power:
                reason = f'only {pump_power:.0f}W (min {min_pump_power}W)'
            else:
                reason = 'unknown'

            plan_entries.append(f"Frost: PUMP ON - {reason} ({ambient_temp:.1f}C)")

            # Check if we should alert
            if pump_off_duration >= alert_delay:
                level = 'critical' if is_critical else 'warning'
                if is_critical:
                    message = f"CRITICAL: Pool pump not running at {ambient_temp:.1f}C! {reason}. Freeze risk!"
                else:
                    message = f"Warning: Pool pump not running during cold weather ({ambient_temp:.1f}C). {reason}"

                alerts.append(Alert(
                    level=level,
                    message=message,
                    notify_entity=fp.notify_entity
                ))
        else:
            # Pump is running and drawing power, good
            if is_critical:
                plan_entries.append(f"Frost: OK, pump {pump_power:.0f}W ({ambient_temp:.1f}C CRITICAL)")
            else:
                plan_entries.append(f"Frost: OK, pump {pump_power:.0f}W ({ambient_temp:.1f}C)")

    return {'alerts': alerts, 'pool_pump_decision': pool_pump_decision, 'plan_entries': plan_entries}


def check_bmw_low_battery(
    inputs: PowerInputs,
    config: Config,
    now: datetime
) -> dict:
    """Check BMW cars for low battery at evening hours."""
    alerts: list[Alert] = []
    plan_entries: list[str] = []

    bmw_config = config.bmw_low_battery
    if not bmw_config.enabled:
        return {'alerts': alerts, 'plan_entries': plan_entries}

    current_hour = now.hour
    check_hours = bmw_config.check_hours

    # Only check during configured hours
    if current_hour not in check_hours:
        return {'alerts': alerts, 'plan_entries': plan_entries}

    threshold = bmw_config.battery_threshold
    ev_state = inputs.ev_state
    ev_plugged_in = ev_state in (EVState.READY, EVState.CHARGING)

    # Check BMW i5
    i5_battery = inputs.bmw_i5_battery
    i5_range = inputs.bmw_i5_range
    i5_location = inputs.bmw_i5_location

    if i5_battery is not None and i5_battery < threshold and i5_location == 'home' and not ev_plugged_in:
        message = f"BMW i5 at {i5_battery:.0f}%, {i5_range or '?'}km range - not plugged in!"
        alerts.append(Alert(
            level='warning',
            message=message,
            car_name='BMW i5',
            battery=i5_battery,
            range_km=i5_range or 0,
            notify_entity=bmw_config.notify_entity
        ))
        plan_entries.append(f"BMW i5: LOW {i5_battery:.0f}% ({i5_range}km) - not charging")
    elif i5_battery is not None and i5_location == 'home':
        if ev_plugged_in:
            plan_entries.append(f"BMW i5: {i5_battery:.0f}% (plugged in)")
        elif i5_battery >= threshold:
            plan_entries.append(f"BMW i5: {i5_battery:.0f}% OK")

    # Check BMW iX1
    ix1_battery = inputs.bmw_ix1_battery
    ix1_range = inputs.bmw_ix1_range
    ix1_location = inputs.bmw_ix1_location

    if ix1_battery is not None and ix1_battery < threshold and ix1_location == 'home' and not ev_plugged_in:
        message = f"BMW iX1 at {ix1_battery:.0f}%, {ix1_range or '?'}km range - not plugged in!"
        alerts.append(Alert(
            level='warning',
            message=message,
            car_name='BMW iX1',
            battery=ix1_battery,
            range_km=ix1_range or 0,
            notify_entity=bmw_config.notify_entity
        ))
        plan_entries.append(f"BMW iX1: LOW {ix1_battery:.0f}% ({ix1_range}km) - not charging")
    elif ix1_battery is not None and ix1_location == 'home':
        if ev_plugged_in:
            plan_entries.append(f"BMW iX1: {ix1_battery:.0f}% (plugged in)")
        elif ix1_battery >= threshold:
            plan_entries.append(f"BMW iX1: {ix1_battery:.0f}% OK")

    return {'alerts': alerts, 'plan_entries': plan_entries}


def _calculate_final_headroom(
    avail: float,
    decisions: Decisions,
    config: Config,
    current_states: dict
) -> float:
    """Calculate final headroom after all decisions."""
    headroom = avail

    # Subtract power for devices that will be/are on
    if decisions.ev.action in ('on', 'adjust'):
        headroom -= decisions.ev.amps * config.ev.watts_per_amp
    elif current_states.get('ev_charging'):
        headroom -= current_states['ev_limit'] * config.ev.watts_per_amp

    if decisions.boiler.action == 'on' or (
        decisions.boiler.action == 'none' and current_states.get('boiler_on')
    ):
        headroom -= config.boiler.power

    # Table heater
    if decisions.heater_table.action == 'on' or (
        decisions.heater_table.action == 'none' and current_states.get('ht_on')
    ):
        headroom -= config.heaters.table_power

    return headroom
