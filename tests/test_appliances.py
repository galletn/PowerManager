"""Tests for appliance smart scheduling (dishwasher, washer, dryer)."""

import pytest
from datetime import datetime
from dataclasses import replace

from app.config import Config
from app.models import PowerInputs, AllDeviceStates, EVState
from app.decision_engine import calculate_decisions, _apply_dishwasher_logic


class TestDishwasherNeverInterrupted:
    """Test that running dishwasher is never interrupted."""

    def test_dishwasher_never_interrupted_when_running(self, base_inputs, config, device_state, winter_peak):
        """Dishwasher drawing power > 50W should never be turned off."""
        # Dishwasher is running (switch on and drawing power)
        inputs = replace(
            base_inputs,
            dishwasher_switch='on',
            dishwasher_power=1850,  # Running cycle
            ovr_dishwasher='auto'
        )

        result = calculate_decisions(inputs, config, device_state, winter_peak)

        # Should NOT turn off the dishwasher
        assert result.decisions.dishwasher.action != 'off'
        # Plan should indicate it's running
        assert any('RUNNING' in entry for entry in result.plan)

    def test_dishwasher_running_during_peak_not_turned_off(self, base_inputs, config, device_state, winter_peak):
        """Even during peak tariff, running dishwasher should not be interrupted."""
        inputs = replace(
            base_inputs,
            dishwasher_switch='on',
            dishwasher_power=1200,  # Running (any power > 50W)
            ovr_dishwasher='auto'
        )

        result = calculate_decisions(inputs, config, device_state, winter_peak)

        assert result.decisions.dishwasher.action != 'off'


class TestDishwasherWaitsDuringPeak:
    """Test that waiting dishwasher is held during peak tariff."""

    def test_dishwasher_waits_during_peak(self, base_inputs, config, device_state, winter_peak):
        """Waiting dishwasher (switch on, no power draw) should be held during peak tariff."""
        # Dishwasher switch is on but not yet running (user loaded and pressed start)
        inputs = replace(
            base_inputs,
            dishwasher_switch='on',
            dishwasher_power=5,  # Waiting (standby power < 50W)
            ovr_dishwasher='auto'
        )

        result = calculate_decisions(inputs, config, device_state, winter_peak)

        # Should not start during peak (action should remain 'none', not 'on')
        assert result.decisions.dishwasher.action == 'none'
        # Plan should indicate waiting
        assert any('WAITING' in entry for entry in result.plan)


class TestDishwasherRunsWithSolar:
    """Test that dishwasher runs when there's solar surplus."""

    def test_dishwasher_runs_with_solar_surplus(self, base_inputs, config, device_state, summer_midday):
        """Dishwasher should run when exporting power (solar surplus)."""
        inputs = replace(
            base_inputs,
            dishwasher_switch='on',
            dishwasher_power=10,  # Waiting to run
            p1_power=0,       # Not importing
            p1_return=2000,   # Exporting 2kW (solar surplus)
            pv_power=4000,    # Good solar production
            ovr_dishwasher='auto'
        )

        result = calculate_decisions(inputs, config, device_state, summer_midday)

        # Should allow run with solar surplus
        assert result.decisions.dishwasher.action == 'on'
        assert any('solar' in entry.lower() for entry in result.plan)


class TestDishwasherRunsDuringOffpeak:
    """Test that dishwasher runs during off-peak with enough headroom."""

    def test_dishwasher_runs_during_offpeak(self, base_inputs, config, device_state, winter_offpeak):
        """Dishwasher should run during off-peak when there's enough power headroom."""
        # Off-peak limit is 5000W, using 1000W, so plenty of headroom for 1900W dishwasher
        inputs = replace(
            base_inputs,
            dishwasher_switch='on',
            dishwasher_power=10,  # Waiting
            p1_power=1000,  # Only 1kW grid import
            ovr_dishwasher='auto'
        )

        result = calculate_decisions(inputs, config, device_state, winter_offpeak)

        # Should allow run during off-peak with headroom
        assert result.decisions.dishwasher.action == 'on'
        assert any('off-peak' in entry.lower() or 'RUN' in entry for entry in result.plan)


class TestDishwasherWaitsForHeadroom:
    """Test that dishwasher waits when not enough power available."""

    def test_dishwasher_waits_for_headroom(self, base_inputs, config, device_state, winter_offpeak):
        """Dishwasher should wait when not enough headroom even during off-peak."""
        # Off-peak limit is 5000W, already using 4500W, not enough for 1900W dishwasher
        inputs = replace(
            base_inputs,
            dishwasher_switch='on',
            dishwasher_power=10,  # Waiting
            p1_power=4500,  # Already near limit
            ovr_dishwasher='auto'
        )

        result = calculate_decisions(inputs, config, device_state, winter_offpeak)

        # Should wait for more headroom
        assert result.decisions.dishwasher.action == 'none'
        # Reason should mention waiting for headroom
        assert result.decisions.dishwasher.reason == 'waiting for headroom'


class TestDishwasherOverrides:
    """Test dishwasher override behavior."""

    def test_dishwasher_override_on(self, base_inputs, config, device_state, winter_peak):
        """Override ON should force dishwasher to run even during peak."""
        inputs = replace(
            base_inputs,
            dishwasher_switch='on',
            dishwasher_power=10,  # Waiting
            ovr_dishwasher='on'
        )

        result = calculate_decisions(inputs, config, device_state, winter_peak)

        # Override should force it on
        assert result.decisions.dishwasher.action == 'on'
        assert any('OVERRIDE ON' in entry for entry in result.plan)

    def test_dishwasher_override_off(self, base_inputs, config, device_state, winter_offpeak):
        """Override OFF should prevent dishwasher from running even during off-peak."""
        inputs = replace(
            base_inputs,
            dishwasher_switch='on',
            dishwasher_power=10,  # Waiting
            ovr_dishwasher='off'
        )

        result = calculate_decisions(inputs, config, device_state, winter_offpeak)

        # Override should force it off
        assert result.decisions.dishwasher.action == 'off'
        assert any('OVERRIDE OFF' in entry for entry in result.plan)
