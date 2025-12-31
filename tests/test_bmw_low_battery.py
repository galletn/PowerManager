"""Tests for BMW low battery warning logic."""

import pytest
from datetime import datetime
from dataclasses import replace

from app.config import Config
from app.models import PowerInputs, AllDeviceStates, EVState
from app.decision_engine import check_bmw_low_battery, calculate_decisions


class TestCheckBmwLowBattery:
    """Test BMW low battery check function."""

    def test_does_nothing_when_disabled(self, base_inputs, config):
        """No action when BMW check is disabled."""
        config.bmw_low_battery.enabled = False
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = check_bmw_low_battery(base_inputs, config, now)

        assert len(result['alerts']) == 0
        assert len(result['plan_entries']) == 0

    def test_does_nothing_outside_check_hours(self, base_inputs, config):
        """No action outside configured check hours."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20, 21, 22]
        now = datetime(2024, 1, 15, 15, 0, 0)  # 15:00 - outside check hours

        result = check_bmw_low_battery(base_inputs, config, now)

        assert len(result['alerts']) == 0
        assert len(result['plan_entries']) == 0

    def test_alerts_when_i5_low_at_home_not_plugged(self, base_inputs, config):
        """Alerts when i5 battery low, at home, and not plugged in."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20, 21, 22]
        config.bmw_low_battery.battery_threshold = 50

        inputs = replace(
            base_inputs,
            bmw_i5_battery=40,
            bmw_i5_range=124,
            bmw_i5_location='home',
            ev_state=EVState.NO_CAR  # Not plugged in
        )
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = check_bmw_low_battery(inputs, config, now)

        assert len(result['alerts']) == 1
        assert result['alerts'][0].level == 'warning'
        assert 'BMW i5' in result['alerts'][0].message
        assert '40' in result['alerts'][0].message
        assert '124' in result['alerts'][0].message
        assert 'not plugged in' in result['alerts'][0].message

    def test_no_alert_when_battery_above_threshold(self, base_inputs, config):
        """No alert when battery is above threshold."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20]
        config.bmw_low_battery.battery_threshold = 50

        inputs = replace(
            base_inputs,
            bmw_i5_battery=60,  # Above threshold
            bmw_i5_location='home',
            ev_state=EVState.NO_CAR
        )
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = check_bmw_low_battery(inputs, config, now)

        assert len(result['alerts']) == 0
        assert len(result['plan_entries']) > 0
        assert any('60' in entry and 'OK' in entry for entry in result['plan_entries'])

    def test_no_alert_when_car_not_at_home(self, base_inputs, config):
        """No alert when car is not at home."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20]
        config.bmw_low_battery.battery_threshold = 50

        inputs = replace(
            base_inputs,
            bmw_i5_battery=30,
            bmw_i5_location='not_home',  # Not at home
            ev_state=EVState.NO_CAR
        )
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = check_bmw_low_battery(inputs, config, now)

        assert len(result['alerts']) == 0

    def test_no_alert_when_car_plugged_in(self, base_inputs, config):
        """No alert when car is plugged in."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20]
        config.bmw_low_battery.battery_threshold = 50

        inputs = replace(
            base_inputs,
            bmw_i5_battery=30,
            bmw_i5_location='home',
            ev_state=EVState.READY  # Plugged in
        )
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = check_bmw_low_battery(inputs, config, now)

        assert len(result['alerts']) == 0
        assert any('plugged in' in entry for entry in result['plan_entries'])

    def test_no_alert_when_car_charging(self, base_inputs, config):
        """No alert when car is charging."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20]
        config.bmw_low_battery.battery_threshold = 50

        inputs = replace(
            base_inputs,
            bmw_i5_battery=30,
            bmw_i5_location='home',
            ev_state=EVState.CHARGING  # Charging
        )
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = check_bmw_low_battery(inputs, config, now)

        assert len(result['alerts']) == 0
        assert any('plugged in' in entry for entry in result['plan_entries'])

    def test_alerts_for_both_cars_when_both_low(self, base_inputs, config):
        """Alerts for both cars when both are low and not plugged in."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20]
        config.bmw_low_battery.battery_threshold = 50

        inputs = replace(
            base_inputs,
            bmw_i5_battery=30,
            bmw_i5_range=100,
            bmw_i5_location='home',
            bmw_ix1_battery=40,
            bmw_ix1_range=150,
            bmw_ix1_location='home',
            ev_state=EVState.NO_CAR
        )
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = check_bmw_low_battery(inputs, config, now)

        assert len(result['alerts']) == 2
        assert any('BMW i5' in a.message for a in result['alerts'])
        assert any('BMW iX1' in a.message for a in result['alerts'])

    def test_handles_null_battery(self, base_inputs, config):
        """Handles null battery gracefully."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20]

        inputs = replace(
            base_inputs,
            bmw_i5_battery=None,
            bmw_i5_location='home',
            ev_state=EVState.NO_CAR
        )
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = check_bmw_low_battery(inputs, config, now)

        assert len(result['alerts']) == 0


class TestBmwIntegration:
    """Test BMW check in full decision engine."""

    def test_bmw_alerts_in_decisions(self, base_inputs, config, device_state):
        """BMW alerts appear in decision result."""
        config.bmw_low_battery.enabled = True
        config.bmw_low_battery.check_hours = [20]
        config.bmw_low_battery.battery_threshold = 50

        inputs = replace(
            base_inputs,
            bmw_i5_battery=30,
            bmw_i5_range=100,
            bmw_i5_location='home',
            ev_state=EVState.NO_CAR
        )
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = calculate_decisions(inputs, config, device_state, now)

        assert any('BMW i5' in a.message for a in result.alerts)
        assert any('BMW i5' in entry for entry in result.plan)
