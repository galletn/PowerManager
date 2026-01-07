"""
Smart Scheduler for Power Manager

Creates an optimized timetable for the next 24 hours that:
- Stays within power limits for each tariff period
- Prioritizes EV charging to reach 80% by deadline
- Schedules boiler heating before hot water deadline
- Uses remaining capacity for table heater
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from .tariff import get_tariff, get_max_import, is_summer


@dataclass
class ScheduleSlot:
    """A 30-minute time slot in the schedule."""
    start: datetime
    end: datetime
    tariff: str
    power_limit: int
    devices: Dict[str, int] = field(default_factory=dict)  # device -> watts

    @property
    def total_power(self) -> int:
        return sum(self.devices.values())

    @property
    def remaining_capacity(self) -> int:
        return self.power_limit - self.total_power

    def can_add(self, device: str, power: int) -> bool:
        return self.remaining_capacity >= power

    def add_device(self, device: str, power: int) -> bool:
        if self.can_add(device, power):
            self.devices[device] = power
            return True
        return False


@dataclass
class DeviceNeed:
    """Represents a device's scheduling needs."""
    name: str
    power: int
    hours_needed: float
    priority: int  # 1=highest
    deadline: Optional[datetime] = None
    can_run_during_peak: bool = False
    start_now: bool = False  # If True, schedule from current time (not cheapest)


@dataclass
class ScheduleResult:
    """Result of the scheduling algorithm."""
    slots: List[ScheduleSlot]
    ev_estimate: Dict
    boiler_estimate: Dict
    warnings: List[str]
    timetable: List[Dict]  # Simplified timetable for display
    scheduled_hours: Dict[str, float] = None  # Hours scheduled per device


def calculate_ev_charging_needs(
    battery_percent: float,
    target_percent: float,
    battery_capacity_kwh: float,
    charging_power_kw: float
) -> Dict:
    """Calculate EV charging time needed."""
    if battery_percent >= target_percent:
        return {
            'needed': False,
            'current_percent': battery_percent,
            'target_percent': target_percent,
            'kwh_needed': 0,
            'hours_needed': 0,
            'charging_power_kw': charging_power_kw
        }

    kwh_needed = (target_percent - battery_percent) / 100 * battery_capacity_kwh
    hours_needed = kwh_needed / charging_power_kw

    return {
        'needed': True,
        'current_percent': battery_percent,
        'target_percent': target_percent,
        'kwh_needed': round(kwh_needed, 1),
        'hours_needed': round(hours_needed, 1),
        'charging_power_kw': charging_power_kw
    }


def calculate_boiler_needs(
    is_hot: bool,
    power_watts: int,
    typical_heat_hours: float = 2.5
) -> Dict:
    """Calculate boiler heating time needed."""
    return {
        'needed': not is_hot,
        'is_hot': is_hot,
        'power_kw': power_watts / 1000,
        'hours_needed': 0 if is_hot else typical_heat_hours
    }


def generate_schedule(
    now: datetime,
    config,
    inputs=None
) -> ScheduleResult:
    """Generate an optimized 24-hour power schedule for all controllable devices.

    Creates a forward-looking schedule that allocates power capacity across
    tariff periods to minimize electricity costs while meeting device needs.
    The schedule respects Belgian electricity tariff limits and prioritizes
    essential devices over comfort devices.

    The algorithm works by:
    1. Creating 30-minute slots for the next 24 hours with tariff/limit info
    2. Calculating each device's power needs (hours required, deadlines)
    3. Sorting devices by priority
    4. For each device, finding suitable slots (respecting tariffs/deadlines)
    5. Filling slots cheapest-first (super-off-peak before off-peak)
    6. Generating warnings if devices cannot meet their deadlines

    Args:
        now: Current datetime, used as the schedule start time.
        config: Config object containing:
            - max_import: Power limits per tariff (peak, off_peak, super_off_peak)
            - ev: EV settings (max_amps, watts_per_amp)
            - boiler: Boiler power and deadline hours
            - heaters: Heater power ratings
            - frost_protection: Pool pump settings
        inputs: Optional PowerInputs with current device states:
            - ev_state: Whether EV is connected/charging
            - bmw_i5_battery, bmw_ix1_battery: Current battery levels
            - boiler_switch, boiler_power: Boiler state
            - pool_pump_switch, pool_ambient_temp: Pool/frost info
            - dishwasher_switch, dishwasher_power: Dishwasher state
            If None, schedule uses default assumptions.

    Returns:
        ScheduleResult containing:
            - slots: List of ScheduleSlot objects (48 slots, 30 min each)
            - ev_estimate: Dict with EV charging needs (kwh_needed, hours_needed)
            - boiler_estimate: Dict with boiler heating needs
            - warnings: List of strings for devices that may not complete
            - timetable: Simplified hourly view for dashboard display
            - scheduled_hours: Dict mapping device name to hours allocated

    Priority Order:
        1. Pool pump - Frost protection, must run 24/7 if cold
        2. Boiler - Hot water essential, deadline before morning
        3. EV charging - Must reach 80% by 07:00
        4. Table heater - Comfort device, 4 hours target
        5. Dishwasher - Smart scheduled, 2 hour cycles
        6. Washing machine - Informational only (user-controlled)
        7. Tumble dryer - Informational only (user-controlled)

    Slot Allocation Strategy:
        - Devices with start_now=True are scheduled from current time
        - Other devices are scheduled cheapest-tariff-first:
          super-off-peak (01:00-07:00) > off-peak > peak
        - Peak slots only used for devices with can_run_during_peak=True
        - Deadline-constrained devices may use more expensive slots if needed

    Example:
        >>> from datetime import datetime
        >>> schedule = generate_schedule(datetime.now(), config, inputs)
        >>> print(f"EV needs {schedule.ev_estimate['hours_needed']}h charging")
        >>> for warning in schedule.warnings:
        ...     print(f"WARNING: {warning}")
    """
    warnings = []
    summer = is_summer(now)

    # Create 30-minute slots for next 24 hours
    slots: List[ScheduleSlot] = []
    current = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    end_time = current + timedelta(hours=24)

    while current < end_time:
        tariff, _ = get_tariff(current)
        limit = get_max_import(tariff, config, current)

        slots.append(ScheduleSlot(
            start=current,
            end=current + timedelta(minutes=30),
            tariff=tariff,
            power_limit=limit
        ))
        current += timedelta(minutes=30)

    # Calculate device needs
    ev_estimate = {'needed': False, 'hours_needed': 0}
    boiler_estimate = {'needed': False, 'hours_needed': 0}

    if inputs:
        # EV needs - check both OCPP and ABB custom states, plus power draw
        from .models import EVState
        ev_connected = (
            inputs.ev_state in (
                EVState.READY, EVState.CHARGING,
                EVState.OCPP_PREPARING, EVState.OCPP_CHARGING,
                EVState.OCPP_SUSPENDED_EV, EVState.OCPP_SUSPENDED_EVSE
            ) or inputs.ev_power > 500
        )
        if ev_connected:
            # Determine which car is plugged in by checking plug_state/charging_state
            # Priority: actually plugged in > actively charging > at home
            car_battery = None
            car_capacity = 84  # Default BMW i5
            car_target_soc = 80  # Default target

            i5_plugged = (inputs.bmw_i5_plug_state == 'CONNECTED' or
                          inputs.bmw_i5_charging_state == 'CHARGINGACTIVE')
            ix1_plugged = (inputs.bmw_ix1_plug_state == 'CONNECTED' or
                           inputs.bmw_ix1_charging_state == 'CHARGINGACTIVE')

            # Prefer the car that is actually plugged in
            if ix1_plugged and inputs.bmw_ix1_battery:
                car_battery = inputs.bmw_ix1_battery
                car_capacity = 65  # BMW iX1 eDrive20
                car_target_soc = inputs.bmw_ix1_target_soc or 80
            elif i5_plugged and inputs.bmw_i5_battery:
                car_battery = inputs.bmw_i5_battery
                car_capacity = 84  # BMW i5 eDrive40
                car_target_soc = inputs.bmw_i5_target_soc or 80
            # Fallback to location-based if no plug state detected
            elif inputs.bmw_i5_location == 'home' and inputs.bmw_i5_battery:
                car_battery = inputs.bmw_i5_battery
                car_capacity = 84  # BMW i5 eDrive40
                car_target_soc = inputs.bmw_i5_target_soc or 80
            elif inputs.bmw_ix1_location == 'home' and inputs.bmw_ix1_battery:
                car_battery = inputs.bmw_ix1_battery
                car_capacity = 65  # BMW iX1 eDrive20
                car_target_soc = inputs.bmw_ix1_target_soc or 80

            if car_battery is not None:
                # Use actual current charging power if actively charging,
                # otherwise estimate based on charger capability and grid limits
                if inputs.ev_power and inputs.ev_power > 500:
                    # Currently charging - use actual power for realistic estimate
                    effective_charging_kw = inputs.ev_power / 1000
                else:
                    # Not charging - estimate based on super-off-peak limits
                    charger_max_kw = config.ev.max_amps * config.ev.watts_per_amp / 1000
                    grid_limit_kw = get_max_import('super-off-peak', config, now) / 1000
                    base_load_buffer_kw = 0.5  # 500W for house base load
                    effective_charging_kw = min(charger_max_kw, grid_limit_kw - base_load_buffer_kw)

                ev_estimate = calculate_ev_charging_needs(
                    car_battery, car_target_soc, car_capacity, effective_charging_kw
                )

        # Boiler needs
        boiler_is_hot = (inputs.boiler_switch == 'on' and
                        inputs.boiler_power < config.boiler.idle_threshold)
        boiler_estimate = calculate_boiler_needs(boiler_is_hot, config.boiler.power)

    # Define device scheduling priorities
    devices = []

    # Pool pump scheduling
    # In winter (non-solar season), pool pump runs 24/7 for circulation/frost protection
    # In summer, only add if running (user controlled via pool_season)
    if inputs:
        pool_pump_running = inputs.pool_pump_switch == 'on'
        pump_power = int(inputs.pool_pump_power) if inputs.pool_pump_power > 0 else config.frost_protection.pump_min_power

        if not summer and pool_pump_running:
            # Winter: pool pump runs 24/7 for maintenance/frost protection
            devices.append(DeviceNeed(
                name='pool_pump',
                power=pump_power,
                hours_needed=24,
                priority=1,
                can_run_during_peak=True
            ))
        elif inputs.pool_ambient_temp and inputs.pool_ambient_temp <= config.frost_protection.temp_threshold:
            # Cold weather: force frost protection even in summer
            devices.append(DeviceNeed(
                name='pool_pump',
                power=pump_power,
                hours_needed=24,
                priority=1,
                can_run_during_peak=True
            ))

    # Boiler - HIGHEST priority after frost protection (no hot water = no shower!)
    # Check if boiler is currently heating (show immediately on timeline)
    boiler_currently_heating = (inputs and
                                inputs.boiler_switch == 'on' and
                                inputs.boiler_power >= config.boiler.idle_threshold)

    if boiler_currently_heating:
        # Boiler is actively heating NOW - show on timeline from current time
        # Estimate remaining heating time based on typical 2.5h total cycle
        devices.append(DeviceNeed(
            name='boiler',
            power=int(inputs.boiler_power),
            hours_needed=1.5,  # Assume ~1.5h remaining when actively heating
            priority=2,
            can_run_during_peak=True,  # If it's running now, let it continue
            start_now=True  # Show from current time
        ))
    elif boiler_estimate.get('needed'):
        # Boiler needs heating later - schedule during cheap tariff
        deadline_hour = int(config.boiler.deadline_winter if not summer else config.boiler.deadline_summer)
        deadline_min = int(((config.boiler.deadline_winter if not summer else config.boiler.deadline_summer) % 1) * 60)
        boiler_deadline = now.replace(hour=deadline_hour, minute=deadline_min, second=0)
        if now.hour >= deadline_hour:
            boiler_deadline += timedelta(days=1)

        devices.append(DeviceNeed(
            name='boiler',
            power=config.boiler.power,
            hours_needed=boiler_estimate['hours_needed'],
            priority=2,
            deadline=boiler_deadline,
            can_run_during_peak=False
        ))

    # EV charging - check if actively charging NOW or needs scheduling later
    ev_currently_charging = inputs and inputs.ev_power > 500

    if ev_currently_charging:
        # EV is actively charging NOW - show on timeline from current time
        # Estimate remaining hours based on battery level if available
        remaining_hours = ev_estimate.get('hours_needed', 2) if ev_estimate.get('needed') else 1
        devices.append(DeviceNeed(
            name='ev',
            power=int(inputs.ev_power),
            hours_needed=max(remaining_hours, 0.5),  # At least 30 min shown
            priority=3,
            can_run_during_peak=True,  # If it's running now, let it continue
            start_now=True  # Show from current time
        ))
    elif ev_estimate.get('needed'):
        # EV needs charging later - schedule during cheap tariff
        # Calculate EV power that can run alongside boiler (both start at 01:00)
        # This allows EV+boiler to run together during super-off-peak
        winter_limit = get_max_import('super-off-peak', config, now)
        boiler_power = config.boiler.power if boiler_estimate.get('needed') else 0
        buffer = 500  # 500W for base load
        # EV power when running alongside boiler
        ev_power_with_boiler = winter_limit - boiler_power - buffer
        # Clamp to charger limits (6A-16A)
        min_ev_power = config.ev.min_amps * config.ev.watts_per_amp
        max_ev_power = config.ev.max_amps * config.ev.watts_per_amp
        ev_power = max(min_ev_power, min(ev_power_with_boiler, max_ev_power))

        # Recalculate hours needed at this power
        kwh_needed = ev_estimate.get('kwh_needed', 30)
        hours_needed = kwh_needed / (ev_power / 1000) if ev_power > 0 else 6

        # Check if super-off-peak (6 hours) is enough, otherwise allow off-peak too
        super_off_peak_hours = 6.0
        needs_off_peak = hours_needed > super_off_peak_hours

        devices.append(DeviceNeed(
            name='ev',
            power=int(ev_power),
            hours_needed=hours_needed,
            priority=3,
            deadline=now.replace(hour=7, minute=0, second=0) + timedelta(days=1 if now.hour >= 7 else 0),
            # Allow off-peak charging if super-off-peak isn't enough
            can_run_during_peak=False,
            # Note: off-peak slots will be considered after super-off-peak due to tariff preference
        ))

    # Table heater - LOWEST priority, gets scheduled into leftover capacity
    # With priority 10, it will only fill slots after boiler (2) and EV (3)
    # The capacity algorithm will fit it where there's room:
    # - Alongside boiler (2.5kW + 4.1kW = 6.6kW < 9kW) ✓
    # - After EV finishes (if super-off-peak time remains)
    devices.append(DeviceNeed(
        name='table_heater',
        power=config.heaters.table_power,
        hours_needed=4,  # Target 4 hours
        priority=10,  # Very low - gets leftover capacity only
        can_run_during_peak=False
    ))

    # Dishwasher - only show when CURRENTLY running (power > 50W)
    # Don't try to predict "waiting" state - switch may stay on after cycle finishes
    if inputs and inputs.dishwasher_power > 50:
        devices.append(DeviceNeed(
            name='dishwasher',
            power=1900,
            hours_needed=2,
            priority=5,
            can_run_during_peak=True,
            start_now=True  # Show from current time when running
        ))

    # Washing machine - only show when CURRENTLY running (informational only)
    if inputs and inputs.washing_machine_power > 50:
        devices.append(DeviceNeed(
            name='washing_machine',
            power=2000,
            hours_needed=1.5,
            priority=6,
            can_run_during_peak=True,
            start_now=True  # Only show from current time when running
        ))

    # Tumble dryer - only show when CURRENTLY running (informational only)
    if inputs and inputs.tumble_dryer_power > 50:
        devices.append(DeviceNeed(
            name='tumble_dryer',
            power=2500,
            hours_needed=1.5,
            priority=7,
            can_run_during_peak=True,
            start_now=True  # Only show from current time when running
        ))

    # Sort by priority
    devices.sort(key=lambda d: d.priority)

    # Track scheduled hours per device
    scheduled_hours: Dict[str, float] = {}

    # Schedule devices into slots
    # Tariff preference order: super-off-peak (cheapest) > off-peak > peak (most expensive)
    TARIFF_PREFERENCE = {'super-off-peak': 0, 'off-peak': 1, 'peak': 2}

    for device in devices:
        hours_scheduled = 0

        # Sort slots by tariff preference (cheapest first), then by time
        # This ensures we fill super-off-peak slots before off-peak
        suitable_slots = []
        for slot in slots:
            # Check if device can run in this tariff
            if not device.can_run_during_peak and slot.tariff == 'peak':
                continue

            # Check deadline
            if device.deadline and slot.start >= device.deadline:
                continue

            # Check capacity
            if slot.can_add(device.name, device.power):
                suitable_slots.append(slot)

        # Sort slots:
        # - If start_now: sort by time (run NOW, regardless of tariff)
        # - Otherwise: sort by tariff preference (cheapest first), then by time
        if device.start_now:
            suitable_slots.sort(key=lambda s: s.start)
        else:
            suitable_slots.sort(key=lambda s: (TARIFF_PREFERENCE.get(s.tariff, 2), s.start))

        # Fill slots
        for slot in suitable_slots:
            if hours_scheduled >= device.hours_needed:
                break
            slot.add_device(device.name, device.power)
            hours_scheduled += 0.5

        # Store scheduled hours
        scheduled_hours[device.name] = hours_scheduled

        # Check if we scheduled enough
        if hours_scheduled < device.hours_needed:
            if device.priority <= 2:  # Critical devices
                warnings.append(
                    f"{device.name}: Only {hours_scheduled:.1f}h scheduled, "
                    f"need {device.hours_needed:.1f}h - may not complete!"
                )

    # Generate simplified timetable for display
    timetable = generate_timetable(slots)

    return ScheduleResult(
        slots=slots,
        ev_estimate=ev_estimate,
        boiler_estimate=boiler_estimate,
        warnings=warnings,
        timetable=timetable,
        scheduled_hours=scheduled_hours
    )


def generate_timetable(slots: List[ScheduleSlot]) -> List[Dict]:
    """Generate a simplified hourly timetable from 30-minute schedule slots.

    Converts the detailed 30-minute scheduling slots into an hourly summary
    suitable for dashboard display. Each hour shows which devices are scheduled
    to run, the applicable tariff, and power utilization.

    Args:
        slots: List of ScheduleSlot objects representing 30-minute time periods,
            each containing:
            - start/end: Datetime boundaries of the slot
            - tariff: 'peak', 'off-peak', or 'super-off-peak'
            - power_limit: Maximum allowed import in watts for this tariff
            - devices: Dict mapping device names to their power consumption

    Returns:
        List of hourly summary dictionaries, each containing:
            - hour: String formatted as "HH:00" (e.g., "03:00")
            - tariff: Tariff period name for this hour
            - limit: Power limit in watts for this tariff period
            - devices: Dict of device names to power consumption (merged from
              both 30-min slots within the hour)
            - total_power: Sum of all device power consumption in watts
            - utilization: Percentage of power limit used (0-100+)

    Example:
        >>> slots = [
        ...     ScheduleSlot(start=datetime(2024,1,1,3,0), ..., devices={'ev': 7500}),
        ...     ScheduleSlot(start=datetime(2024,1,1,3,30), ..., devices={'ev': 7500}),
        ... ]
        >>> timetable = generate_timetable(slots)
        >>> timetable[0]
        {'hour': '03:00', 'tariff': 'super-off-peak', 'limit': 8000,
         'devices': {'ev': 7500}, 'total_power': 7500, 'utilization': 94}

    Note:
        Devices scheduled in either half of an hour appear in that hour's
        summary. The power value shown is from the first slot where the
        device appears (assumes consistent power within the hour).
    """
    timetable = []

    # Group slots by hour and device activity
    current_hour = None
    current_entry = None

    for slot in slots:
        hour = slot.start.hour

        if hour != current_hour:
            if current_entry:
                timetable.append(current_entry)

            current_hour = hour
            current_entry = {
                'hour': f"{hour:02d}:00",
                'tariff': slot.tariff,
                'limit': slot.power_limit,
                'devices': {},
                'total_power': 0
            }

        # Merge device info
        for device, power in slot.devices.items():
            if device not in current_entry['devices']:
                current_entry['devices'][device] = power

    # Calculate totals
    for entry in timetable:
        entry['total_power'] = sum(entry['devices'].values())
        entry['utilization'] = round(entry['total_power'] / entry['limit'] * 100) if entry['limit'] > 0 else 0

    if current_entry:
        timetable.append(current_entry)

    return timetable


def format_timetable_text(schedule: ScheduleResult) -> List[str]:
    """Format timetable for text display."""
    lines = []
    lines.append("=" * 60)
    lines.append("24-HOUR POWER SCHEDULE")
    lines.append("=" * 60)

    # Estimates
    lines.append("")
    lines.append("ESTIMATES:")
    if schedule.ev_estimate.get('needed'):
        lines.append(f"  EV: {schedule.ev_estimate['current_percent']:.0f}% → 80% = "
                    f"{schedule.ev_estimate['kwh_needed']}kWh, ~{schedule.ev_estimate['hours_needed']}h charging")
    else:
        lines.append("  EV: No charging needed (≥80% or not connected)")

    if schedule.boiler_estimate.get('needed'):
        lines.append(f"  Boiler: Needs ~{schedule.boiler_estimate['hours_needed']}h heating")
    else:
        lines.append("  Boiler: Already hot")

    # Warnings
    if schedule.warnings:
        lines.append("")
        lines.append("⚠️ WARNINGS:")
        for warning in schedule.warnings:
            lines.append(f"  • {warning}")

    # Timetable
    lines.append("")
    lines.append("SCHEDULE:")
    lines.append("-" * 60)
    lines.append(f"{'Hour':<6} {'Tariff':<12} {'Devices':<30} {'Power':<10}")
    lines.append("-" * 60)

    tariff_colors = {
        'peak': '🔴',
        'off-peak': '🟡',
        'super-off-peak': '🟢'
    }

    for entry in schedule.timetable:
        tariff_icon = tariff_colors.get(entry['tariff'], '⚪')
        devices_str = ', '.join(entry['devices'].keys()) or '-'
        power_str = f"{entry['total_power']}W" if entry['total_power'] > 0 else '-'

        lines.append(f"{entry['hour']:<6} {tariff_icon} {entry['tariff']:<10} {devices_str:<30} {power_str:<10}")

    lines.append("-" * 60)
    lines.append("")

    return lines
