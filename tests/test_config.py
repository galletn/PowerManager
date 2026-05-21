"""Tests for config loading and YAML merge behavior.

Covers Story 1.1 (PASS2 §5 #7 / N5): `_apply_config` must apply every
top-level dataclass section from YAML and raise on unknown keys.
"""

import logging
import textwrap

import pytest

from app.config import (
    Config,
    _apply_config,
    load_config,
)


# ---------------------------------------------------------------------------
# Recursive-merge behavior (AC #1, #2, #4)
# ---------------------------------------------------------------------------


def test_full_yaml_applied():
    """Every top-level section flows through to the runtime Config."""
    cfg = Config()
    data = {
        "polling_interval": 45,
        "port": 9000,
        "units_p1": 500,
        "units_pv": 2,
        "debug": True,
        "home_assistant": {
            "url": "https://example.local:8123",
            "verify_ssl": True,
        },
        "max_import": {
            "peak": 2600,
            "off_peak": 5100,
            "super_off_peak": 8100,
            "super_off_peak_winter": 9500,
        },
        "ev": {
            "min_amps": 8,
            "max_amps": 20,
            "watts_per_amp": 700,
            "amp_change_threshold": 3,
        },
        "boiler": {
            "power": 2700,
            "idle_threshold": 60,
            "deadline_winter": 7.0,
            "deadline_summer": 9.0,
            "full_confirm_seconds": 150,
        },
        "pool": {
            "idle_power": 150,
            "active_power": 2200,
        },
        "frost_protection": {
            "enabled": True,
            "temp_threshold": 4.5,
            "critical_threshold": 1.5,
            "pump_min_power": 120,
            "pump_off_alert_delay": 400,
            "notify_entity": "mobile_app_test",
        },
        "bmw_low_battery": {
            "enabled": False,
            "battery_threshold": 40,
            "check_hours": [21, 22],
            "notify_entity": "mobile_app_test",
        },
        "heaters": {
            "right_power": 3000,
            "table_power": 4200,
        },
        "ac": {
            "living": {"power": 2000, "winter_setpoint": 23},
        },
        "timing": {
            "hysteresis": 400,
            "min_on_time": 600,
            "min_off_time": 240,
        },
        "entities": {
            "boiler_switch": "switch.other_boiler",
            "ev_switch": "switch.other_ev",
        },
    }

    _apply_config(cfg, data)

    assert cfg.polling_interval == 45
    assert cfg.port == 9000
    assert cfg.units_p1 == 500
    assert cfg.units_pv == 2
    assert cfg.debug is True
    assert cfg.home_assistant.url == "https://example.local:8123"
    assert cfg.home_assistant.verify_ssl is True
    assert cfg.max_import.peak == 2600
    assert cfg.max_import.off_peak == 5100
    assert cfg.max_import.super_off_peak == 8100
    assert cfg.max_import.super_off_peak_winter == 9500
    assert cfg.ev.min_amps == 8
    assert cfg.ev.max_amps == 20
    assert cfg.ev.watts_per_amp == 700
    assert cfg.ev.amp_change_threshold == 3
    assert cfg.boiler.power == 2700
    assert cfg.boiler.idle_threshold == 60
    assert cfg.boiler.deadline_winter == 7.0
    assert cfg.boiler.deadline_summer == 9.0
    assert cfg.boiler.full_confirm_seconds == 150
    assert cfg.pool.idle_power == 150
    assert cfg.pool.active_power == 2200
    assert cfg.frost_protection.enabled is True
    assert cfg.frost_protection.temp_threshold == 4.5
    assert cfg.frost_protection.critical_threshold == 1.5
    assert cfg.frost_protection.pump_min_power == 120
    assert cfg.frost_protection.pump_off_alert_delay == 400
    assert cfg.frost_protection.notify_entity == "mobile_app_test"
    assert cfg.bmw_low_battery.enabled is False
    assert cfg.bmw_low_battery.battery_threshold == 40
    assert cfg.bmw_low_battery.check_hours == [21, 22]
    assert cfg.bmw_low_battery.notify_entity == "mobile_app_test"
    assert cfg.heaters.right_power == 3000
    assert cfg.heaters.table_power == 4200
    assert cfg.ac.living.power == 2000
    assert cfg.ac.living.winter_setpoint == 23
    assert cfg.timing.hysteresis == 400
    assert cfg.timing.min_on_time == 600
    assert cfg.timing.min_off_time == 240
    assert cfg.entities.boiler_switch == "switch.other_boiler"
    assert cfg.entities.ev_switch == "switch.other_ev"


def test_max_import_super_off_peak_winter_applied():
    """Regression for PASS2 N5: super_off_peak_winter was previously dropped."""
    cfg = Config()
    _apply_config(cfg, {"max_import": {"super_off_peak_winter": 9500}})
    assert cfg.max_import.super_off_peak_winter == 9500


def test_frost_pump_off_alert_delay_applied():
    """Regression for PASS2 N5: pump_off_alert_delay was previously dropped."""
    cfg = Config()
    _apply_config(cfg, {"frost_protection": {"pump_off_alert_delay": 600}})
    assert cfg.frost_protection.pump_off_alert_delay == 600


def test_frost_pump_min_power_applied():
    """Regression for PASS2 N5: pump_min_power was previously dropped."""
    cfg = Config()
    _apply_config(cfg, {"frost_protection": {"pump_min_power": 200}})
    assert cfg.frost_protection.pump_min_power == 200


def test_ac_nested_override_isolated():
    """Setting one AC unit must not disturb the others' defaults."""
    cfg = Config()
    living_default_power = cfg.ac.living.power
    mancave_default = cfg.ac.mancave.power
    office_default = cfg.ac.office.power
    bedroom_default = cfg.ac.bedroom.power

    _apply_config(cfg, {"ac": {"living": {"power": 2000}}})

    assert cfg.ac.living.power == 2000
    assert cfg.ac.living.power != living_default_power
    assert cfg.ac.mancave.power == mancave_default
    assert cfg.ac.office.power == office_default
    assert cfg.ac.bedroom.power == bedroom_default


def test_bmw_check_hours_replaces_list_wholesale():
    """List-typed fields are replaced, not merged element-wise."""
    cfg = Config()
    _apply_config(cfg, {"bmw_low_battery": {"check_hours": [21, 22]}})
    assert cfg.bmw_low_battery.check_hours == [21, 22]


# ---------------------------------------------------------------------------
# Unknown-key validation (AC #3)
# ---------------------------------------------------------------------------


def test_unknown_top_level_raises():
    """An unknown top-level key must raise ValueError naming the key."""
    cfg = Config()
    with pytest.raises(ValueError, match=r"^Unknown config key: bogus$"):
        _apply_config(cfg, {"bogus": 1})


def test_unknown_nested_raises_with_dotted_path():
    """An unknown nested key must raise ValueError with the dotted path."""
    cfg = Config()
    with pytest.raises(ValueError, match=r"max_import\.peak_winter"):
        _apply_config(cfg, {"max_import": {"peak_winter": 9000}})


def test_unknown_in_entities_raises():
    """Unknown entity field raises with `entities.<name>` in the message."""
    cfg = Config()
    with pytest.raises(ValueError, match=r"entities\.not_a_sensor"):
        _apply_config(cfg, {"entities": {"not_a_sensor": "sensor.x"}})


def test_unknown_in_ac_unit_raises():
    """Unknown field on a nested AC unit raises with the deep dotted path."""
    cfg = Config()
    with pytest.raises(ValueError, match=r"ac\.living\.bogus_field"):
        _apply_config(cfg, {"ac": {"living": {"bogus_field": 1}}})


# ---------------------------------------------------------------------------
# Currently-applied sections must keep working (AC #1 regression)
# ---------------------------------------------------------------------------


def test_currently_applied_sections_still_work():
    """Sections applied by the pre-fix code must round-trip identically."""
    cfg = Config()
    data = {
        "home_assistant": {
            "url": "https://x:8123",
            "token": "t",
            "verify_ssl": False,
        },
        "polling_interval": 60,
        "port": 8123,
        "max_import": {"peak": 2600, "off_peak": 5100, "super_off_peak": 8100},
        "frost_protection": {
            "enabled": True,
            "temp_threshold": 5.0,
            "critical_threshold": 2.0,
            "notify_entity": "mobile_app_test",
        },
        "bmw_low_battery": {
            "enabled": True,
            "battery_threshold": 50,
            "check_hours": [20, 21, 22],
            "notify_entity": "mobile_app_test",
        },
        "debug": True,
    }
    _apply_config(cfg, data)

    assert cfg.home_assistant.url == "https://x:8123"
    assert cfg.home_assistant.token == "t"
    assert cfg.home_assistant.verify_ssl is False
    assert cfg.polling_interval == 60
    assert cfg.port == 8123
    assert cfg.max_import.peak == 2600
    assert cfg.frost_protection.enabled is True
    assert cfg.bmw_low_battery.battery_threshold == 50
    assert cfg.debug is True


# ---------------------------------------------------------------------------
# `load_config()` boundary behavior (AC #5)
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path, body: str):
    """Write a config.yaml in tmp_path and return its path."""
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def test_env_var_overrides_yaml(tmp_path, monkeypatch):
    """HA_URL/HA_TOKEN/PORT env vars must override YAML values."""
    cfg_path = _write_yaml(
        tmp_path,
        """
        home_assistant:
          url: "https://from-yaml:8123"
          token: "yaml-token"
        port: 7000
        """,
    )
    monkeypatch.setenv("PM_CONFIG", str(cfg_path))
    monkeypatch.setenv("HA_URL", "https://from-env:8123")
    monkeypatch.setenv("HA_TOKEN", "env-token")
    monkeypatch.setenv("PORT", "9999")

    cfg = load_config()

    assert cfg.home_assistant.url == "https://from-env:8123"
    assert cfg.home_assistant.token == "env-token"
    assert cfg.port == 9999


def test_missing_yaml_uses_defaults(tmp_path, monkeypatch):
    """No YAML file → defaults survive; only the token must come from env."""
    monkeypatch.setenv("PM_CONFIG", str(tmp_path / "nonexistent.yaml"))
    monkeypatch.setenv("HA_TOKEN", "env-token")
    monkeypatch.delenv("HA_URL", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    cfg = load_config()

    assert cfg.home_assistant.token == "env-token"
    assert cfg.polling_interval == 30  # dataclass default
    assert cfg.max_import.peak == 2500  # dataclass default
    assert cfg.ev.min_amps == 6  # dataclass default


def test_missing_token_still_raises(tmp_path, monkeypatch):
    """Token-required validation must still trigger after the merge change."""
    cfg_path = _write_yaml(tmp_path, "polling_interval: 30\n")
    monkeypatch.setenv("PM_CONFIG", str(cfg_path))
    monkeypatch.delenv("HA_TOKEN", raising=False)

    with pytest.raises(ValueError, match=r"Home Assistant token is required"):
        load_config()


def test_max_import_peak_zero_still_raises(tmp_path, monkeypatch):
    """max_import.peak <= 0 validation must still trigger after merge change."""
    cfg_path = _write_yaml(
        tmp_path,
        """
        max_import:
          peak: 0
        """,
    )
    monkeypatch.setenv("PM_CONFIG", str(cfg_path))
    monkeypatch.setenv("HA_TOKEN", "t")

    with pytest.raises(ValueError, match=r"max_import\.peak must be greater than 0"):
        load_config()


def test_max_import_off_peak_zero_still_raises(tmp_path, monkeypatch):
    """max_import.off_peak <= 0 validation must still trigger."""
    cfg_path = _write_yaml(
        tmp_path,
        """
        max_import:
          off_peak: 0
        """,
    )
    monkeypatch.setenv("PM_CONFIG", str(cfg_path))
    monkeypatch.setenv("HA_TOKEN", "t")

    with pytest.raises(
        ValueError, match=r"max_import\.off_peak must be greater than 0"
    ):
        load_config()


def test_max_import_super_off_peak_zero_still_raises(tmp_path, monkeypatch):
    """max_import.super_off_peak <= 0 validation must still trigger."""
    cfg_path = _write_yaml(
        tmp_path,
        """
        max_import:
          super_off_peak: 0
        """,
    )
    monkeypatch.setenv("PM_CONFIG", str(cfg_path))
    monkeypatch.setenv("HA_TOKEN", "t")

    with pytest.raises(
        ValueError, match=r"max_import\.super_off_peak must be greater than 0"
    ):
        load_config()


def test_verify_ssl_false_logs_warning(tmp_path, monkeypatch, caplog):
    """verify_ssl: false must emit the existing WARNING log."""
    cfg_path = _write_yaml(
        tmp_path,
        """
        home_assistant:
          token: "t"
          verify_ssl: false
        """,
    )
    monkeypatch.setenv("PM_CONFIG", str(cfg_path))
    monkeypatch.delenv("HA_URL", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)

    with caplog.at_level(logging.WARNING, logger="app.config"):
        load_config()

    assert any(
        "SSL verification is disabled" in record.message
        for record in caplog.records
    ), f"Expected SSL-disabled warning, got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# Dataclass-where-scalar / null guard (regression for review fix P1)
# ---------------------------------------------------------------------------


def test_scalar_at_dataclass_field_raises():
    """A scalar value where a nested-dataclass section is expected must raise.

    Without this guard, `setattr(config, "max_import", 5000)` silently replaces
    the GridConfig instance and the downstream `config.max_import.peak`
    validation crashes with AttributeError instead of a named ValueError.
    """
    cfg = Config()
    with pytest.raises(
        ValueError, match=r"Expected mapping at max_import, got int"
    ):
        _apply_config(cfg, {"max_import": 5000})


def test_null_at_dataclass_field_raises():
    """YAML null at a nested-dataclass section must raise, not clobber."""
    cfg = Config()
    with pytest.raises(
        ValueError, match=r"Expected mapping at home_assistant, got NoneType"
    ):
        _apply_config(cfg, {"home_assistant": None})


def test_string_at_nested_dataclass_field_raises():
    """A string at a deeper nested-dataclass section must raise."""
    cfg = Config()
    with pytest.raises(
        ValueError, match=r"Expected mapping at ac\.living, got str"
    ):
        _apply_config(cfg, {"ac": {"living": "not-a-section"}})


def test_load_config_full_yaml_round_trip(tmp_path, monkeypatch):
    """End-to-end: YAML file with many sections lands in the runtime Config."""
    cfg_path = _write_yaml(
        tmp_path,
        """
        home_assistant:
          url: "https://x:8123"
          token: "yaml-token"
        polling_interval: 45
        ev:
          min_amps: 8
        boiler:
          deadline_winter: 7.0
        ac:
          living:
            power: 2000
        timing:
          min_on_time: 600
        entities:
          boiler_switch: "switch.other"
        """,
    )
    monkeypatch.setenv("PM_CONFIG", str(cfg_path))
    monkeypatch.delenv("HA_URL", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)

    cfg = load_config()

    assert cfg.home_assistant.token == "yaml-token"
    assert cfg.polling_interval == 45
    assert cfg.ev.min_amps == 8
    assert cfg.boiler.deadline_winter == 7.0
    assert cfg.ac.living.power == 2000
    assert cfg.timing.min_on_time == 600
    assert cfg.entities.boiler_switch == "switch.other"
