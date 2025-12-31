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


def calculate_decisions(
    inputs: PowerInputs,
    config: Config,
    device_state: AllDeviceStates,
    now: Optional[datetime] = None
) -> DecisionResult:
    """
    Calculate device decisions based on current state.

    Main entry point for the decision engine.
    """
    if now is None:
        now = datetime.now()

    now_ts = now.timestamp() * 1000  # Convert to milliseconds for JS compatibility

    # Get tariff info
    tariff, tariff_info = get_tariff(now)
    max_import = get_max_import(tariff, config)
    summer = is_summer(now)

    # Calculate power values
    p1 = inputs.p1_power      # Grid import (W)
    pv = inputs.pv_power      # Solar production (W)

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
    }

    # Device current states
    ev_state = inputs.ev_state
    ev_limit = inputs.ev_limit
    boiler_on = inputs.boiler_switch == 'on'
    boiler_power = inputs.boiler_power
    boiler_force = inputs.boiler_force == 'on'
    boiler_full = boiler_on and boiler_power < config.boiler.idle_threshold

    # EV states
    ev_plugged = ev_state in (EVState.READY, EVState.CHARGING, EVState.FULL)
    ev_ready = ev_state == EVState.READY
    ev_charging = ev_state == EVState.CHARGING
    ev_done = ev_state == EVState.FULL
    ev_status_text = get_ev_status_text(ev_state)

    # Heaters and AC
    hr_on = inputs.heater_right_switch == 'on'
    ht_on = inputs.heater_table_switch == 'on'

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
            'hr_on': hr_on,
            'ht_on': ht_on,
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
            'ac_states': ac_states,
            'temps': temps,
            'headroom': headroom,
            'hyst': hyst,
            'tariff': tariff,
            'config': config,
            'can_switch': can_switch,
            'device_state': device_state,
            'now': now_ts,
            'is_exporting': is_exporting,
            'pv': pv,
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


def _apply_winter_logic(decisions: Decisions, plan: list, ctx: dict):
    """Apply winter heating/charging logic."""
    ovr = ctx['ovr']
    headroom = ctx['headroom']
    hyst = ctx['hyst']
    config = ctx['config']
    can_switch = ctx['can_switch']
    tariff = ctx['tariff']

    # Track effective headroom as we make decisions
    effective_headroom = headroom

    # === BOILER FIRST (Priority 2 - hot water is essential!) ===
    boiler_will_use = 0
    if ovr['boiler'] == 'auto' and not ctx['boiler_full']:
        hour = ctx['date'].hour + ctx['date'].minute / 60
        deadline = config.boiler.deadline_winter

        if tariff in ('off-peak', 'super-off-peak'):
            approaching_deadline = hour >= (deadline - 2) and hour < deadline
            enough_power = effective_headroom > config.boiler.power + hyst

            if not ctx['boiler_on'] and (enough_power or approaching_deadline):
                if can_switch('boiler', True):
                    decisions.boiler.action = 'on'
                    boiler_will_use = config.boiler.power
                    effective_headroom -= boiler_will_use
                    reason = "approaching deadline" if approaching_deadline else "off-peak"
                    plan.append(f"Boiler: ON ({reason})")
            elif ctx['boiler_on']:
                # Boiler already on, reserve its power
                boiler_will_use = config.boiler.power
                effective_headroom -= boiler_will_use
        elif tariff == 'peak' and ctx['boiler_on']:
            # Turn off during peak unless near deadline
            if hour > deadline and can_switch('boiler', False):
                decisions.boiler.action = 'off'
                plan.append("Boiler: OFF (peak tariff)")

    # === EV CHARGING (Priority 3 - use remaining capacity) ===
    if ovr['ev'] == 'auto' and ctx['ev_plugged'] and not ctx['ev_done']:
        if tariff == 'super-off-peak':
            # Super off-peak (8kW limit) - plenty of room for EV
            available_watts = effective_headroom - hyst
            available_amps = int(available_watts / config.ev.watts_per_amp)
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
                # Boiler not running and not needed, can use capacity for EV
                available_watts = effective_headroom - hyst
                available_amps = int(available_watts / config.ev.watts_per_amp)
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

    # === TABLE HEATER (Priority 4 - lowest, use remaining capacity) ===
    if ovr['table_heater'] == 'auto':
        table_power = config.heaters.table_power
        ht_on = ctx['ht_on']

        if tariff in ('off-peak', 'super-off-peak'):
            # Use effective_headroom which already accounts for boiler and EV
            # But also account for EV if it was already charging
            remaining = effective_headroom
            if ctx['ev_charging'] and decisions.ev.action == 'none':
                remaining -= ctx['ev_limit'] * config.ev.watts_per_amp

            enough_power = remaining > table_power + hyst

            if not ht_on and enough_power:
                if can_switch('heater_table', True):
                    decisions.heater_table.action = 'on'
                    plan.append("Table heater: ON (off-peak, spare capacity)")
            elif ht_on and remaining < table_power - hyst:
                # Not enough power, turn off to make room for priority devices
                if can_switch('heater_table', False):
                    decisions.heater_table.action = 'off'
                    plan.append("Table heater: OFF (capacity needed)")
        elif tariff == 'peak' and ht_on:
            # Turn off during peak - save money
            if can_switch('heater_table', False):
                decisions.heater_table.action = 'off'
                plan.append("Table heater: OFF (peak tariff)")


def _apply_summer_logic(decisions: Decisions, plan: list, ctx: dict):
    """Apply summer solar optimization logic."""
    ovr = ctx['ovr']
    headroom = ctx['headroom']
    hyst = ctx['hyst']
    config = ctx['config']
    can_switch = ctx['can_switch']
    is_exporting = ctx['is_exporting']
    pv = ctx['pv']

    # EV Charging - solar surplus charging
    if ovr['ev'] == 'auto' and ctx['ev_plugged'] and not ctx['ev_done']:
        if is_exporting and pv > 1000:  # Good solar production
            # Calculate amps from surplus
            surplus = -headroom + hyst  # headroom is negative when exporting
            available_amps = int(surplus / config.ev.watts_per_amp)
            target_amps = max(config.ev.min_amps, min(available_amps, config.ev.max_amps))

            if ctx['ev_ready'] and target_amps >= config.ev.min_amps:
                if can_switch('ev', True):
                    decisions.ev.action = 'on'
                    decisions.ev.amps = target_amps
                    plan.append(f"EV: SOLAR START at {target_amps}A")
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
        elif ctx['ev_charging'] and not is_exporting:
            # No longer exporting, stop charging
            if can_switch('ev', False):
                decisions.ev.action = 'off'
                plan.append("EV: STOP (no surplus)")

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
