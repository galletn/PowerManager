"""Belgian electricity tariff calculations."""

from datetime import datetime, date
from typing import Tuple

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
    """
    current_date = dt.date()
    holidays = get_belgian_holidays(dt.year)
    weekday = dt.weekday()  # 0=Monday, 6=Sunday
    hour = dt.hour

    is_weekend = weekday >= 5
    is_holiday = current_date in holidays

    # Weekend/holiday: always off-peak
    if is_weekend or is_holiday:
        return "off-peak", {
            "reason": "weekend" if is_weekend else "holiday",
            "next_change": None
        }

    # Weekday tariff schedule
    if hour < 6:
        # 00:00-06:00: super-off-peak
        return "super-off-peak", {
            "reason": "night",
            "next_change": 6
        }
    elif hour < 7:
        # 06:00-07:00: off-peak (transition)
        return "off-peak", {
            "reason": "early morning",
            "next_change": 7
        }
    elif hour < 22:
        # 07:00-22:00: peak
        return "peak", {
            "reason": "daytime",
            "next_change": 22
        }
    else:
        # 22:00-24:00: off-peak
        return "off-peak", {
            "reason": "evening",
            "next_change": 24
        }


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
