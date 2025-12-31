"""Tests for frost protection logic."""

import pytest
from datetime import datetime
from dataclasses import replace

from app.config import Config
from app.models import PowerInputs, AllDeviceStates, EVState
from app.decision_engine import check_frost_protection, calculate_decisions


class TestCheckFrostProtection:
    """Test frost protection function."""

    def test_does_nothing_when_disabled(self, base_inputs, config, device_state):
        """No action when frost protection is disabled."""
        config.frost_protection.enabled = False
        now = datetime(2024, 1, 15, 20, 0, 0).timestamp() * 1000

        result = check_frost_protection(base_inputs, config, device_state, now)

        assert len(result['alerts']) == 0
        assert result['pool_pump_decision'].action == 'none'

    def test_does_nothing_when_warm(self, base_inputs, config, device_state):
        """No action when temperature is above threshold."""
        config.frost_protection.enabled = True
        config.frost_protection.temp_threshold = 5
        inputs = replace(base_inputs, pool_ambient_temp=15)
        now = datetime(2024, 1, 15, 20, 0, 0).timestamp() * 1000

        result = check_frost_protection(inputs, config, device_state, now)

        assert len(result['alerts']) == 0
        assert result['pool_pump_decision'].action == 'none'

    def test_turns_on_pump_when_cold_and_pump_off(self, base_inputs, config, device_state):
        """Turns on pump when cold and pump is off."""
        config.frost_protection.enabled = True
        config.frost_protection.temp_threshold = 5
        inputs = replace(base_inputs, pool_ambient_temp=3, pool_pump_switch='off', pool_pump_power=0)
        now = datetime(2024, 1, 15, 20, 0, 0).timestamp() * 1000

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'on'
        assert any('PUMP ON' in entry for entry in result['plan_entries'])
        assert any('3.0' in entry for entry in result['plan_entries'])

    def test_alerts_when_pump_on_but_no_power(self, base_inputs, config, device_state):
        """Alerts when pump switch is on but not drawing power."""
        config.frost_protection.enabled = True
        config.frost_protection.temp_threshold = 5
        config.frost_protection.pump_min_power = 100
        config.frost_protection.pump_off_alert_delay = 0  # Immediate alert

        inputs = replace(base_inputs, pool_ambient_temp=3, pool_pump_switch='on', pool_pump_power=20)
        now = datetime(2024, 1, 15, 20, 0, 0).timestamp() * 1000

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'on'
        assert any('only 20W' in entry for entry in result['plan_entries'])
        assert len(result['alerts']) == 1
        assert 'only 20W' in result['alerts'][0].message

    def test_ok_when_pump_running_during_cold(self, base_inputs, config, device_state):
        """Shows OK when pump is running properly during cold weather."""
        config.frost_protection.enabled = True
        config.frost_protection.temp_threshold = 5
        config.frost_protection.pump_min_power = 100

        inputs = replace(base_inputs, pool_ambient_temp=3, pool_pump_switch='on', pool_pump_power=120)
        now = datetime(2024, 1, 15, 20, 0, 0).timestamp() * 1000

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'none'
        assert any('Frost: OK' in entry for entry in result['plan_entries'])
        assert any('120W' in entry for entry in result['plan_entries'])

    def test_critical_alert_below_critical_threshold(self, base_inputs, config, device_state):
        """Shows CRITICAL when below critical temperature threshold."""
        config.frost_protection.enabled = True
        config.frost_protection.temp_threshold = 5
        config.frost_protection.critical_threshold = 2
        config.frost_protection.pump_min_power = 100

        inputs = replace(base_inputs, pool_ambient_temp=1, pool_pump_switch='on', pool_pump_power=120)
        now = datetime(2024, 1, 15, 20, 0, 0).timestamp() * 1000

        result = check_frost_protection(inputs, config, device_state, now)

        assert any('CRITICAL' in entry for entry in result['plan_entries'])


class TestFrostProtectionIntegration:
    """Test frost protection in full decision engine."""

    def test_frost_protection_in_decisions(self, base_inputs, config, device_state):
        """Frost protection integrates with main decisions."""
        config.frost_protection.enabled = True
        config.frost_protection.temp_threshold = 5

        inputs = replace(base_inputs, pool_ambient_temp=3, pool_pump_switch='off')
        now = datetime(2024, 1, 15, 20, 0, 0)

        result = calculate_decisions(inputs, config, device_state, now)

        assert result.decisions.pool_pump.action == 'on'
        assert any('Frost' in entry for entry in result.plan)
