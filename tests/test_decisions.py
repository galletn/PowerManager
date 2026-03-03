"""Tests for main decision engine."""

import pytest
from datetime import datetime
from dataclasses import replace

from app.config import Config
from app.models import PowerInputs, AllDeviceStates, EVState
from app.decision_engine import calculate_decisions, fmt_w, grid_indicator, parse_override


class TestFormatting:
    """Test formatting functions."""

    def test_fmt_w_small(self):
        assert fmt_w(500) == '500W'

    def test_fmt_w_kilowatts(self):
        assert fmt_w(2500) == '2.5kW'

    def test_fmt_w_negative(self):
        assert fmt_w(-1500) == '-1.5kW'


class TestGridIndicator:
    """Test grid indicator function."""

    def test_exporting(self):
        assert grid_indicator(-500, 2500) == '[<<<]'

    def test_low_usage(self):
        assert grid_indicator(500, 2500) == '[---]'

    def test_medium_usage(self):
        assert grid_indicator(1500, 2500) == '[==-]'

    def test_high_usage(self):
        assert grid_indicator(2200, 2500) == '[==|]'

    def test_over_limit(self):
        assert grid_indicator(3000, 2500) == '[!!!]'


class TestParseOverride:
    """Test override parsing."""

    def test_empty_is_auto(self):
        assert parse_override('') == 'auto'

    def test_auto_values(self):
        assert parse_override('auto') == 'auto'
        assert parse_override('Auto') == 'auto'
        assert parse_override('automatic') == 'auto'

    def test_on_values(self):
        assert parse_override('on') == 'on'
        assert parse_override('ON') == 'on'
        assert parse_override('aan') == 'on'
        assert parse_override('force_on') == 'on'

    def test_off_values(self):
        assert parse_override('off') == 'off'
        assert parse_override('OFF') == 'off'
        assert parse_override('uit') == 'off'
        assert parse_override('force_off') == 'off'


class TestCalculateDecisions:
    """Test main decision calculation."""

    def test_returns_decision_result(self, base_inputs, config, device_state, winter_evening):
        """Returns a valid DecisionResult."""
        result = calculate_decisions(base_inputs, config, device_state, winter_evening)

        assert result.decisions is not None
        assert result.plan is not None
        assert isinstance(result.plan, list)
        assert len(result.plan) > 0
        assert result.headroom is not None

    def test_includes_tariff_in_plan(self, base_inputs, config, device_state, winter_peak):
        """Plan includes tariff information."""
        result = calculate_decisions(base_inputs, config, device_state, winter_peak)

        assert any('PEAK' in entry for entry in result.plan)

    def test_includes_power_values_in_plan(self, base_inputs, config, device_state, winter_evening):
        """Plan includes power values."""
        inputs = replace(base_inputs, p1_power=1500, pv_power=200)
        result = calculate_decisions(inputs, config, device_state, winter_evening)

        # Status line shows Import/Export and PV
        assert any('Import' in entry or 'Export' in entry for entry in result.plan)
        assert any('PV' in entry for entry in result.plan)


class TestManualOverrides:
    """Test manual override behavior."""

    def test_boiler_override_on(self, base_inputs, config, device_state, winter_evening):
        """Boiler override ON forces boiler on."""
        inputs = replace(base_inputs, ovr_boiler='on')
        result = calculate_decisions(inputs, config, device_state, winter_evening)

        assert result.decisions.boiler.action == 'on'
        assert any('OVERRIDE ON' in entry for entry in result.plan)

    def test_boiler_override_off(self, base_inputs, config, device_state, winter_evening):
        """Boiler override OFF forces boiler off."""
        inputs = replace(base_inputs, ovr_boiler='off', boiler_switch='on')
        result = calculate_decisions(inputs, config, device_state, winter_evening)

        assert result.decisions.boiler.action == 'off'
        assert any('OVERRIDE OFF' in entry for entry in result.plan)

    def test_ev_override_on(self, base_inputs, config, device_state, winter_evening):
        """EV override ON starts charging (respects headroom)."""
        inputs = replace(base_inputs, ovr_ev='on', ev_state=EVState.READY)
        result = calculate_decisions(inputs, config, device_state, winter_evening)

        assert result.decisions.ev.action == 'on'
        assert result.decisions.ev.amps >= config.ev.min_amps


class TestEvCharging:
    """Test EV charging decisions."""

    def test_no_action_when_no_car(self, base_inputs, config, device_state, winter_offpeak):
        """No EV action when no car connected."""
        inputs = replace(base_inputs, ev_state=EVState.NO_CAR)
        result = calculate_decisions(inputs, config, device_state, winter_offpeak)

        assert result.decisions.ev.action == 'none'

    def test_no_action_when_full(self, base_inputs, config, device_state, winter_offpeak):
        """No EV action when car is full."""
        inputs = replace(base_inputs, ev_state=EVState.FULL)
        result = calculate_decisions(inputs, config, device_state, winter_offpeak)

        assert result.decisions.ev.action == 'none'


class TestSeasonalBehavior:
    """Test summer vs winter behavior."""

    def test_winter_mode_detected(self, base_inputs, config, device_state, winter_evening):
        """Winter mode is detected in January."""
        result = calculate_decisions(base_inputs, config, device_state, winter_evening)

        assert 'Winter' in ' '.join(result.plan)
        assert result.meta['is_summer'] is False

    def test_summer_mode_detected(self, base_inputs, config, device_state, summer_midday):
        """Summer mode is detected in July."""
        result = calculate_decisions(base_inputs, config, device_state, summer_midday)

        assert 'Summer' in ' '.join(result.plan)
        assert result.meta['is_summer'] is True
