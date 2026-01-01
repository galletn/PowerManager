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
from .tariff import get_tariff, is_summer


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
    """
    Generate optimized 24-hour schedule.

    Priority order:
    1. Pool pump (frost protection) - must run if cold
    2. EV charging - must reach 80% by morning
    3. Boiler - must be hot by deadline
    4. Table heater - comfort, use remaining capacity
    """
    warnings = []
    summer = is_summer(now)

    # Create 30-minute slots for next 24 hours
    slots: List[ScheduleSlot] = []
    current = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    end_time = current + timedelta(hours=24)

    while current < end_time:
        tariff, _ = get_tariff(current)
        if tariff == 'super-off-peak':
            limit = config.max_import.super_off_peak
        elif tariff == 'off-peak':
            limit = config.max_import.off_peak
        else:
            limit = config.max_import.peak

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
        # EV needs
        from .models import EVState
        if inputs.ev_state in (EVState.READY, EVState.CHARGING):
            # Determine which car is plugged in based on location
            car_battery = None
            car_capacity = 84  # Default BMW i5

            if inputs.bmw_i5_location == 'home' and inputs.bmw_i5_battery:
                car_battery = inputs.bmw_i5_battery
                car_capacity = 84  # BMW i5 eDrive40
            elif inputs.bmw_ix1_location == 'home' and inputs.bmw_ix1_battery:
                car_battery = inputs.bmw_ix1_battery
                car_capacity = 65  # BMW iX1 eDrive20

            if car_battery is not None:
                # Calculate realistic charging power based on:
                # 1. EV charger max power (max_amps × watts_per_amp)
                # 2. Grid limit during super-off-peak minus buffer for other loads
                charger_max_kw = config.ev.max_amps * config.ev.watts_per_amp / 1000
                grid_limit_kw = config.max_import.super_off_peak / 1000
                base_load_buffer_kw = 0.5  # 500W for house base load
                # Effective = min of charger capability and grid headroom
                # e.g., min(11kW, 8kW - 0.5kW) = 7.5kW
                effective_charging_kw = min(charger_max_kw, grid_limit_kw - base_load_buffer_kw)
                ev_estimate = calculate_ev_charging_needs(
                    car_battery, 80, car_capacity, effective_charging_kw
                )

        # Boiler needs
        boiler_is_hot = (inputs.boiler_switch == 'on' and
                        inputs.boiler_power < config.boiler.idle_threshold)
        boiler_estimate = calculate_boiler_needs(boiler_is_hot, config.boiler.power)

    # Define device scheduling priorities
    devices = []

    # Always add pool pump if cold (frost protection)
    # Use actual current pump power if available (user adjusts speed)
    if inputs and inputs.pool_ambient_temp and inputs.pool_ambient_temp <= config.frost_protection.temp_threshold:
        # Use current pump power, fallback to config minimum
        pump_power = int(inputs.pool_pump_power) if inputs.pool_pump_power > 0 else config.frost_protection.pump_min_power
        devices.append(DeviceNeed(
            name='pool_pump',
            power=pump_power,
            hours_needed=24,  # Run continuously when cold
            priority=1,
            can_run_during_peak=True  # Frost protection overrides cost
        ))

    # Boiler - HIGHEST priority after frost protection (no hot water = no shower!)
    if boiler_estimate.get('needed'):
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

    # EV charging - use effective power limited by grid, not max charger power
    if ev_estimate.get('needed'):
        # Use the same effective power calculation as the estimate
        ev_power = int(ev_estimate.get('charging_power_kw', 7.5) * 1000)
        devices.append(DeviceNeed(
            name='ev',
            power=ev_power,
            hours_needed=ev_estimate['hours_needed'],
            priority=3,
            deadline=now.replace(hour=7, minute=0, second=0) + timedelta(days=1 if now.hour >= 7 else 0),
            can_run_during_peak=False
        ))

    # Table heater - lower priority, comfort device
    devices.append(DeviceNeed(
        name='table_heater',
        power=config.heaters.table_power,
        hours_needed=4,  # Target 4 hours of heating
        priority=4,
        can_run_during_peak=False
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

        # Sort by tariff preference (cheapest first), then by time
        suitable_slots.sort(key=lambda s: (TARIFF_PREFERENCE.get(s.tariff, 2), s.start))

        # Fill cheapest slots first
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
    """Generate a simplified timetable showing hourly device status."""
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
