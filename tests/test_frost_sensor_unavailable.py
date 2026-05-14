"""Regression tests for CODE_REVIEW_PASS2.md N1.

When the pool ambient temperature sensor returns None (unavailable / unknown /
battery dead), frost protection previously just plan-appended "Frost: No temp
sensor" and did nothing. That fails closed during heating season — if a Zigbee
sensor dies on a January morning, the pool pump can freeze with no warning.

The fix: during heating season (Nov-Mar) when the sensor is unavailable,
force the pump on and raise a warning alert. Outside heating season the
quiet behaviour is preserved (no spurious alerts).
"""

from dataclasses import replace
from datetime import datetime

from app.decision_engine import check_frost_protection


# now_ts is milliseconds (see decision_engine.py:296 and 488)
def _ts(dt: datetime) -> float:
    return dt.timestamp() * 1000


class TestSensorUnavailableInHeatingSeason:
    """Heating season = November, December, January, February, March."""

    def test_january_failsafe_turns_pump_on(self, base_inputs, config, device_state):
        config.frost_protection.enabled = True
        inputs = replace(base_inputs, pool_ambient_temp=None, pool_pump_switch='off', pool_pump_power=0)
        now = _ts(datetime(2026, 1, 15, 6, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'on'
        assert any('NO SENSOR' in e for e in result['plan_entries'])

    def test_january_raises_warning_alert(self, base_inputs, config, device_state):
        config.frost_protection.enabled = True
        inputs = replace(base_inputs, pool_ambient_temp=None, pool_pump_switch='off', pool_pump_power=0)
        now = _ts(datetime(2026, 1, 15, 6, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert len(result['alerts']) == 1
        alert = result['alerts'][0]
        assert alert.level == 'warning'
        assert 'sensor' in alert.message.lower()

    def test_november_also_failsafe(self, base_inputs, config, device_state):
        config.frost_protection.enabled = True
        inputs = replace(base_inputs, pool_ambient_temp=None, pool_pump_switch='off', pool_pump_power=0)
        now = _ts(datetime(2026, 11, 5, 8, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'on'
        assert len(result['alerts']) == 1

    def test_march_also_failsafe(self, base_inputs, config, device_state):
        config.frost_protection.enabled = True
        inputs = replace(base_inputs, pool_ambient_temp=None, pool_pump_switch='off', pool_pump_power=0)
        now = _ts(datetime(2026, 3, 10, 8, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'on'
        assert len(result['alerts']) == 1

    def test_april_failsafe_for_ice_saints(self, base_inputs, config, device_state):
        """CR-P4: Belgian 'Ijsheiligen' (Ice Saints) mid-May is folklore but
        April frost is common. Sensor failure in April must still fail-safe."""
        config.frost_protection.enabled = True
        inputs = replace(base_inputs, pool_ambient_temp=None, pool_pump_switch='off', pool_pump_power=0)
        now = _ts(datetime(2026, 4, 5, 6, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'on'
        assert len(result['alerts']) == 1

    def test_october_failsafe_early_winter(self, base_inputs, config, device_state):
        """CR-P4: First October frosts are real in Belgium. Failsafe in Oct too."""
        config.frost_protection.enabled = True
        inputs = replace(base_inputs, pool_ambient_temp=None, pool_pump_switch='off', pool_pump_power=0)
        now = _ts(datetime(2026, 10, 25, 6, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'on'
        assert len(result['alerts']) == 1

    def test_failsafe_when_pump_already_on(self, base_inputs, config, device_state):
        """Don't override a running pump — but still alert about the dead sensor."""
        config.frost_protection.enabled = True
        inputs = replace(
            base_inputs,
            pool_ambient_temp=None,
            pool_pump_switch='on',
            pool_pump_power=120,
        )
        now = _ts(datetime(2026, 1, 15, 6, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        # Pump is already running, no need to issue 'on' — but warn the user.
        assert result['pool_pump_decision'].action == 'none'
        assert len(result['alerts']) == 1
        assert result['alerts'][0].level == 'warning'


class TestSensorUnavailableOutsideHeatingSeason:
    """May through September — quiet operation, no spurious alerts.
    April and October are inside heating season (CR-P4)."""

    def test_july_no_action_no_alert(self, base_inputs, config, device_state):
        config.frost_protection.enabled = True
        inputs = replace(base_inputs, pool_ambient_temp=None, pool_pump_switch='off')
        now = _ts(datetime(2026, 7, 15, 12, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'none'
        assert len(result['alerts']) == 0
        assert any('No temp sensor' in e for e in result['plan_entries'])

    def test_may_no_action(self, base_inputs, config, device_state):
        """Mid-May is past Ice Saints — no spurious alerts."""
        config.frost_protection.enabled = True
        inputs = replace(base_inputs, pool_ambient_temp=None)
        now = _ts(datetime(2026, 5, 20, 12, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'none'
        assert len(result['alerts']) == 0

    def test_disabled_overrides_failsafe(self, base_inputs, config, device_state):
        """If frost_protection.enabled is False, do nothing even in winter."""
        config.frost_protection.enabled = False
        inputs = replace(base_inputs, pool_ambient_temp=None)
        now = _ts(datetime(2026, 1, 15, 6, 0, 0))

        result = check_frost_protection(inputs, config, device_state, now)

        assert result['pool_pump_decision'].action == 'none'
        assert len(result['alerts']) == 0
