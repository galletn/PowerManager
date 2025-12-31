"""Belgian electricity tariff calculations."""

from datetime import datetime, date, timedelta
from typing import Tuple, List

# Belgian public holidays (fixed dates)
FIXED_HOLIDAYS = [
    (1, 1),   # New Year's Day
    (5, 1),   # Labour Day
    (7, 21),  # National Day
    (8, 15),  # Assumption
    (11, 1),  # All Saints
    (11, 11), # Armistice
    (12, 25), # Christmas
]


def easter_date(year: int) -> date:
    """Calculate Easter Sunday using Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_belgian_holidays(year: int) -> set[date]:
    """Get all Belgian public holidays for a year."""
    holidays = set()

    # Fixed holidays
    for month, day in FIXED_HOLIDAYS:
        holidays.add(date(year, month, day))

    # Easter-based holidays
    easter = easter_date(year)
    holidays.add(easter)  # Easter Sunday
    holidays.add(date.fromordinal(easter.toordinal() + 1))   # Easter Monday
    holidays.add(date.fromordinal(easter.toordinal() + 39))  # Ascension
    holidays.add(date.fromordinal(easter.toordinal() + 50))  # Whit Monday

    return holidays


def is_summer(dt: datetime) -> bool:
    """Check if date is in summer period (April-September)."""
    return 4 <= dt.month <= 9


def get_tariff(dt: datetime) -> Tuple[str, dict]:
    """
    Determine Belgian electricity tariff based on time.

    Returns:
        Tuple of (tariff_name, tariff_info)
        tariff_name: 'peak', 'off-peak', 'super-off-peak'
        tariff_info: dict with hours info

    Weekday schedule:
        22:00 - 01:00: Off-peak
        01:00 - 07:00: Super off-peak
        07:00 - 11:00: Peak
        11:00 - 17:00: Off-peak
        17:00 - 22:00: Peak

    Weekend/holiday schedule:
        00:00 - 01:00: Off-peak
        01:00 - 07:00: Super off-peak
        07:00 - 11:00: Off-peak
        11:00 - 17:00: Super off-peak
        17:00 - 00:00: Off-peak
    """
    current_date = dt.date()
    holidays = get_belgian_holidays(dt.year)
    weekday = dt.weekday()  # 0=Monday, 6=Sunday
    hour = dt.hour

    is_weekend = weekday >= 5
    is_holiday = current_date in holidays

    if is_weekend or is_holiday:
        # Weekend/holiday schedule
        if hour < 1:
            # 00:00-01:00: off-peak
            return "off-peak", {"reason": "weekend night", "next_change": 1}
        elif hour < 7:
            # 01:00-07:00: super-off-peak
            return "super-off-peak", {"reason": "weekend night", "next_change": 7}
        elif hour < 11:
            # 07:00-11:00: off-peak
            return "off-peak", {"reason": "weekend morning", "next_change": 11}
        elif hour < 17:
            # 11:00-17:00: super-off-peak
            return "super-off-peak", {"reason": "weekend midday", "next_change": 17}
        else:
            # 17:00-00:00: off-peak
            return "off-peak", {"reason": "weekend evening", "next_change": 24}
    else:
        # Weekday schedule
        if hour < 1:
            # 00:00-01:00: off-peak (continuation from 22:00)
            return "off-peak", {"reason": "night", "next_change": 1}
        elif hour < 7:
            # 01:00-07:00: super-off-peak
            return "super-off-peak", {"reason": "night", "next_change": 7}
        elif hour < 11:
            # 07:00-11:00: peak (morning)
            return "peak", {"reason": "morning peak", "next_change": 11}
        elif hour < 17:
            # 11:00-17:00: off-peak (midday)
            return "off-peak", {"reason": "midday", "next_change": 17}
        elif hour < 22:
            # 17:00-22:00: peak (evening)
            return "peak", {"reason": "evening peak", "next_change": 22}
        else:
            # 22:00-00:00: off-peak
            return "off-peak", {"reason": "evening", "next_change": 24}


def get_max_import(tariff: str, config) -> int:
    """Get maximum import power for tariff."""
    if tariff == "super-off-peak":
        return config.max_import.super_off_peak
    elif tariff == "off-peak":
        return config.max_import.off_peak
    else:
        return config.max_import.peak


def get_ev_status_text(ev_state: int) -> str:
    """Get human-readable EV charger status."""
    from .models import EVState

    if ev_state == EVState.NO_CAR:
        return "No car"
    elif ev_state == EVState.READY:
        return "Plugged (ready)"
    elif ev_state == EVState.FULL:
        return "Full"
    elif ev_state == EVState.CHARGING:
        return "Charging"
    else:
        return f"Unknown ({ev_state})"


def generate_24h_schedule(now: datetime, config, inputs=None) -> dict:
    """
    Generate a 24-hour schedule showing tariff periods and planned device actions.

    Returns a structured schedule with:
    - Timeline of tariff periods
    - Planned EV charging windows
    - Planned boiler heating windows
    - Any special events (frost protection, car battery alerts)
    """
    summer = is_summer(now)
    schedule = {
        'generated_at': now.isoformat(),
        'season': 'summer' if summer else 'winter',
        'tariff_periods': [],
        'ev_plan': [],
        'boiler_plan': [],
        'alerts_schedule': [],
        'summary': []
    }

    # Generate tariff timeline for next 24 hours
    current = now.replace(minute=0, second=0, microsecond=0)
    end_time = current + timedelta(hours=24)

    last_tariff = None
    period_start = current

    while current < end_time:
        tariff, info = get_tariff(current)

        if tariff != last_tariff:
            if last_tariff is not None:
                duration = int((current - period_start).total_seconds() // 3600)
                schedule['tariff_periods'].append({
                    'tariff': last_tariff,
                    'start': period_start.strftime('%H:%M'),
                    'end': current.strftime('%H:%M'),
                    'duration_hours': max(1, duration)  # Ensure at least 1 hour
                })
            period_start = current
            last_tariff = tariff

        current += timedelta(hours=1)

    # Add final period
    if last_tariff:
        duration = int((end_time - period_start).total_seconds() // 3600)
        schedule['tariff_periods'].append({
            'tariff': last_tariff,
            'start': period_start.strftime('%H:%M'),
            'end': end_time.strftime('%H:%M'),
            'duration_hours': max(1, duration)
        })

    # Generate EV charging plan with clear windows
    if not summer:
        # Winter: charge during off-peak/super-off-peak
        schedule['ev_plan'] = [
            {
                'action': 'charge',
                'window': '22:00-01:00',
                'tariff': 'off-peak',
                'reason': 'Off-peak night (5kW limit)'
            },
            {
                'action': 'charge',
                'window': '01:00-07:00',
                'tariff': 'super-off-peak',
                'reason': 'Super-off-peak night (8kW limit)'
            },
            {
                'action': 'charge',
                'window': '11:00-17:00',
                'tariff': 'off-peak',
                'reason': 'Off-peak midday (5kW limit)'
            }
        ]
    else:
        # Summer: charge from solar
        schedule['ev_plan'].append({
            'action': 'solar_charge',
            'window': '10:00-16:00',
            'reason': 'Peak solar production window'
        })

    # Generate boiler plan
    deadline = config.boiler.deadline_winter if not summer else config.boiler.deadline_summer
    deadline_str = f"{int(deadline)}:{int((deadline % 1) * 60):02d}"

    if not summer:
        # Winter: heat during off-peak/super-off-peak before deadline
        heating_windows = []

        # Evening off-peak: 22:00-01:00
        heating_windows.append({
            'action': 'heat',
            'window': '22:00-01:00',
            'priority': 'normal',
            'reason': 'Off-peak night'
        })

        # Night super-off-peak: 01:00-07:00
        heating_windows.append({
            'action': 'heat',
            'window': '01:00-07:00',
            'priority': 'high',
            'reason': f'Super-off-peak, hot water by {deadline_str}'
        })

        schedule['boiler_plan'] = heating_windows
    else:
        # Summer: heat from solar
        schedule['boiler_plan'].append({
            'action': 'solar_heat',
            'window': '10:00-16:00',
            'reason': 'Use solar surplus'
        })

    # Build summary
    now_tariff, _ = get_tariff(now)
    schedule['summary'].append(f"Now: {now_tariff.upper()} tariff")

    # Find next tariff change
    next_change = None
    for period in schedule['tariff_periods']:
        start_h = int(period['start'].split(':')[0])
        if start_h > now.hour and period['tariff'] != now_tariff:
            next_change = period
            break

    if next_change:
        schedule['summary'].append(f"Next: {next_change['tariff'].upper()} at {next_change['start']}")

    # Add EV and boiler status
    if inputs:
        from .models import EVState
        if inputs.ev_state == EVState.NO_CAR:
            schedule['summary'].append("EV: No car connected")
        elif inputs.ev_state == EVState.READY:
            schedule['summary'].append("EV: Plugged in, waiting for cheap rate" if not summer else "EV: Plugged in, waiting for solar")
        elif inputs.ev_state == EVState.CHARGING:
            schedule['summary'].append(f"EV: Charging at {inputs.ev_limit}A")
        elif inputs.ev_state == EVState.FULL:
            schedule['summary'].append("EV: Fully charged")

        if inputs.boiler_switch == 'on' and inputs.boiler_power > 100:
            schedule['summary'].append(f"Boiler: Heating ({inputs.boiler_power:.0f}W)")
        elif inputs.boiler_switch == 'on':
            schedule['summary'].append("Boiler: Hot (maintaining)")
        else:
            schedule['summary'].append("Boiler: Off")

    # Frost protection notes if cold
    if inputs and inputs.pool_ambient_temp is not None:
        if inputs.pool_ambient_temp <= config.frost_protection.temp_threshold:
            schedule['alerts_schedule'].append({
                'type': 'frost_protection',
                'message': f"Pool pump running for frost protection ({inputs.pool_ambient_temp:.1f}°C)",
                'active': True
            })

    return schedule


def format_24h_plan_text(schedule: dict) -> List[str]:
    """Format the 24-hour schedule as text lines for display."""
    lines = []

    # Header
    lines.append("=" * 50)
    lines.append(f"24-HOUR PLAN ({schedule['season'].upper()})")
    lines.append("=" * 50)

    # Summary
    lines.append("")
    lines.append("STATUS:")
    for item in schedule['summary']:
        lines.append(f"  • {item}")

    # Tariff timeline
    lines.append("")
    lines.append("TARIFF SCHEDULE:")
    for period in schedule['tariff_periods']:
        tariff_icon = {
            'peak': '🔴',
            'off-peak': '🟡',
            'super-off-peak': '🟢'
        }.get(period['tariff'], '⚪')
        lines.append(f"  {period['start']}-{period['end']}: {tariff_icon} {period['tariff'].upper()}")

    # EV plan
    if schedule['ev_plan']:
        lines.append("")
        lines.append("EV CHARGING PLAN:")
        for plan in schedule['ev_plan']:
            lines.append(f"  ⚡ {plan['window']}: {plan['reason']}")

    # Boiler plan
    if schedule['boiler_plan']:
        lines.append("")
        lines.append("BOILER HEATING PLAN:")
        for plan in schedule['boiler_plan']:
            priority_icon = "🔥" if plan.get('priority') == 'high' else "♨️"
            lines.append(f"  {priority_icon} {plan['window']}: {plan['reason']}")

    # Alerts
    if schedule['alerts_schedule']:
        lines.append("")
        lines.append("ACTIVE ALERTS:")
        for alert in schedule['alerts_schedule']:
            lines.append(f"  ⚠️ {alert['message']}")

    lines.append("")
    lines.append("=" * 50)

    return lines
