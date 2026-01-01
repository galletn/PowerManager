"""Tests for Belgian tariff calculations."""

import pytest
from datetime import datetime, date

from app.tariff import get_tariff, is_summer, get_belgian_holidays, easter_date


class TestEasterCalculation:
    """Test Easter date calculation."""

    def test_easter_2024(self):
        """Easter 2024 is March 31."""
        assert easter_date(2024) == date(2024, 3, 31)

    def test_easter_2025(self):
        """Easter 2025 is April 20."""
        assert easter_date(2025) == date(2025, 4, 20)


class TestBelgianHolidays:
    """Test Belgian holiday detection."""

    def test_christmas(self):
        """Christmas is a holiday."""
        holidays = get_belgian_holidays(2024)
        assert date(2024, 12, 25) in holidays

    def test_national_day(self):
        """July 21 is Belgian National Day."""
        holidays = get_belgian_holidays(2024)
        assert date(2024, 7, 21) in holidays

    def test_easter_monday(self):
        """Easter Monday is a holiday."""
        holidays = get_belgian_holidays(2024)
        # Easter 2024 is March 31, so Monday is April 1
        assert date(2024, 4, 1) in holidays


class TestIsSummer:
    """Test summer period detection."""

    def test_january_is_winter(self):
        assert not is_summer(datetime(2024, 1, 15, 12, 0))

    def test_march_is_summer(self):
        """March is now part of solar season (March-October)."""
        assert is_summer(datetime(2024, 3, 15, 12, 0))

    def test_april_is_summer(self):
        assert is_summer(datetime(2024, 4, 15, 12, 0))

    def test_july_is_summer(self):
        assert is_summer(datetime(2024, 7, 15, 12, 0))

    def test_september_is_summer(self):
        assert is_summer(datetime(2024, 9, 15, 12, 0))

    def test_october_is_summer(self):
        """October is now part of solar season (March-October)."""
        assert is_summer(datetime(2024, 10, 15, 12, 0))

    def test_november_is_winter(self):
        assert not is_summer(datetime(2024, 11, 15, 12, 0))


class TestGetTariff:
    """Test tariff determination."""

    def test_weekday_peak(self):
        """Weekday 09:00 is peak (morning peak 07:00-11:00)."""
        dt = datetime(2024, 1, 15, 9, 0)  # Monday
        tariff, info = get_tariff(dt)
        assert tariff == 'peak'
        assert info['reason'] == 'morning peak'

    def test_weekday_evening_peak(self):
        """Weekday 18:00 is peak (evening peak 17:00-22:00)."""
        dt = datetime(2024, 1, 15, 18, 0)  # Monday
        tariff, info = get_tariff(dt)
        assert tariff == 'peak'
        assert info['reason'] == 'evening peak'

    def test_weekday_offpeak_midday(self):
        """Weekday 14:00 is off-peak (midday 11:00-17:00)."""
        dt = datetime(2024, 1, 15, 14, 0)  # Monday
        tariff, info = get_tariff(dt)
        assert tariff == 'off-peak'
        assert info['reason'] == 'midday'

    def test_weekday_offpeak_evening(self):
        """Weekday 22:30 is off-peak."""
        dt = datetime(2024, 1, 15, 22, 30)  # Monday
        tariff, info = get_tariff(dt)
        assert tariff == 'off-peak'

    def test_weekday_super_offpeak_night(self):
        """Weekday 03:00 is super-off-peak."""
        dt = datetime(2024, 1, 15, 3, 0)  # Monday
        tariff, info = get_tariff(dt)
        assert tariff == 'super-off-peak'

    def test_weekday_super_offpeak_early_morning(self):
        """Weekday 06:30 is super-off-peak (01:00-07:00)."""
        dt = datetime(2024, 1, 15, 6, 30)  # Monday
        tariff, info = get_tariff(dt)
        assert tariff == 'super-off-peak'

    def test_saturday_midday_super_offpeak(self):
        """Saturday 14:00 is super-off-peak (weekend midday 11:00-17:00)."""
        dt = datetime(2024, 1, 13, 14, 0)  # Saturday
        tariff, info = get_tariff(dt)
        assert tariff == 'super-off-peak'
        assert info['reason'] == 'weekend midday'

    def test_saturday_morning_offpeak(self):
        """Saturday 09:00 is off-peak (weekend morning 07:00-11:00)."""
        dt = datetime(2024, 1, 13, 9, 0)  # Saturday
        tariff, info = get_tariff(dt)
        assert tariff == 'off-peak'
        assert info['reason'] == 'weekend morning'

    def test_sunday_is_offpeak(self):
        """Sunday any time is off-peak."""
        dt = datetime(2024, 1, 14, 10, 0)  # Sunday
        tariff, info = get_tariff(dt)
        assert tariff == 'off-peak'

    def test_holiday_follows_weekday_schedule(self):
        """Holidays follow weekday schedule (Belgian electricity tariffs don't treat holidays as weekends)."""
        dt = datetime(2024, 12, 25, 14, 0)  # Christmas (Wednesday) at 14:00
        tariff, info = get_tariff(dt)
        # 14:00 on a Wednesday is midday off-peak (11:00-17:00)
        assert tariff == 'off-peak'
        assert info['reason'] == 'midday'
