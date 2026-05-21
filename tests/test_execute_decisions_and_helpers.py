"""Regression tests for Story 1.11 — the 4 silent bugs from the v1.0.67
quality audit:

- B-1: `_update_ha_status_helpers` imported a non-existent `get_current_tariff`
  from tariff.py, causing an ImportError silently swallowed by the broad
  except at decision_loop's call site. HA status helpers had been stuck.
- B-2: `logger.info` lines in `execute_decisions` fired unconditionally on
  `turn_on`/`turn_off`, producing observably-wrong logs ("Boiler: ON") even
  when HA returned False.
- B-3: The outer `except Exception` wrapping the entire 160-line
  `execute_decisions` body meant one device's failure aborted the rest of
  the cycle and corrupted `confirmed_states`.
- B-4: `_update_ha_status_helpers` double-multiplied p1 values
  (`(inputs.p1_power or 0) * 1000`) — `parse_inputs` already applies
  `units_p1=1000`. Latent because B-1's ImportError hid it; would have
  produced 1000x-too-large kW status text the moment B-1 was fixed.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import (
    _update_ha_status_helpers,
    app_state,
    execute_decisions,
)
from app.models import Decisions, PowerInputs, EVState
from app.config import Config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def restore_app_state():
    """Snapshot/restore app_state (it's a module global)."""
    saved_config = app_state.config
    saved_decisions = app_state.last_decisions
    saved_pending = dict(app_state.pending_commands)
    saved_client = app_state.ha_client
    try:
        yield
    finally:
        app_state.config = saved_config
        app_state.last_decisions = saved_decisions
        app_state.pending_commands = saved_pending
        app_state.ha_client = saved_client


@pytest.fixture
def fresh_state():
    """Wire app_state with a Config and a mocked HA client.

    Default mocks: turn_on/turn_off return True (success); set_climate,
    set_number, set_fan_mode, set_input_text are AsyncMocks.
    """
    config = Config()
    app_state.config = config
    app_state.ha_client = MagicMock()
    app_state.ha_client.turn_on = AsyncMock(return_value=True)
    app_state.ha_client.turn_off = AsyncMock(return_value=True)
    app_state.ha_client.set_climate = AsyncMock(return_value=True)
    app_state.ha_client.set_number = AsyncMock(return_value=True)
    app_state.ha_client.set_fan_mode = AsyncMock(return_value=True)
    app_state.ha_client.set_input_text = AsyncMock(return_value=True)
    app_state.ha_client.send_notification = AsyncMock(return_value=True)
    app_state.pending_commands = {}
    app_state.last_decisions = Decisions()
    return config


def _default_inputs(**overrides) -> PowerInputs:
    """Build a minimal PowerInputs with all current states 'off' so any
    device decision that wants 'on' fires."""
    defaults = dict(
        p1_power=0.0,
        p1_return=0.0,
        pv_power=0.0,
        boiler_switch='off',
        boiler_power=0,
        boiler_force='off',
        pool_season='off',
        pool_power=0,
        pool_climate='off',
        pool_pump_switch='off',
        pool_pump_power=0,
        pool_ambient_temp=10,
        ev_state=EVState.NO_CAR,
        ev_switch='off',
        ev_power=0,
        ev_limit=6,
        heater_right_switch='off',
        heater_table_switch='off',
        ac_living_state='off',
        ac_mancave_state='off',
        ac_office_state='off',
        ac_bedroom_state='off',
        ac_living_power=0,
        ac_office_power=0,
        temp_living=20,
        temp_bedroom=20,
        temp_mancave=20,
        ovr_ac_living='',
        ovr_ac_bedroom='',
        ovr_ac_office='',
        ovr_ac_mancave='',
        ovr_pool='',
        ovr_boiler='',
        ovr_ev='',
        bmw_i5_battery=40,
        bmw_i5_range=124,
        bmw_i5_location='home',
        bmw_ix1_battery=83,
        bmw_ix1_range=254,
        bmw_ix1_location='not_home',
    )
    defaults.update(overrides)
    return PowerInputs(**defaults)


# ---------------------------------------------------------------------------
# Test 1 — B-1 + B-4: _update_ha_status_helpers writes correct kW value
#                     with the peak-tariff label (no ImportError, no
#                     double-multiplication).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_ha_status_helpers_writes_tariff_label_with_correct_kw_value(
    fresh_state, monkeypatch
):
    """B-1 (ImportError fix) AND B-4 (no kW/W double-multiplication).

    Force PEAK tariff via get_tariff monkeypatch. Build inputs with
    p1_power=2500W (post-parse W, as parse_inputs would produce).
    Assert the status text contains 'PIEK' (peak label) AND '2.5kW'
    (net = p1 - p1r = 2500W → displayed as 2500/1000 = 2.5kW),
    and NOT '2500.0kW' (which would mean B-4 regressed).
    """
    # Force peak tariff regardless of wall clock.
    # NOTE: this patch only works because `get_tariff` is imported at the
    # top of app/main.py (`from .tariff import get_tariff`). If a future
    # refactor moves it back to a local `from .tariff import get_tariff`
    # inside `_update_ha_status_helpers`, this patch becomes a silent
    # no-op AND B-1 regresses. Keep the import at module level.
    monkeypatch.setattr(
        'app.main.get_tariff',
        lambda now: ('peak', {}),
    )

    inputs = _default_inputs(
        p1_power=2500.0,   # W (post-parse_inputs)
        p1_return=0.0,
        pv_power=1000.0,
    )
    result = MagicMock()
    result.plan = []
    result.headroom = 3000

    await _update_ha_status_helpers(inputs, result)

    set_text = app_state.ha_client.set_input_text
    assert set_text.call_count >= 1, (
        f"Expected set_input_text to be called at least once (post B-1 fix); "
        f"got call_count={set_text.call_count}"
    )

    # First call's positional args: (entity_id, status_string).
    first_call_args = set_text.call_args_list[0].args
    status_str = first_call_args[1]

    assert 'PIEK' in status_str, (
        f"Expected 'PIEK' (peak tariff label, B-1 closure) in status text; "
        f"got: {status_str!r}"
    )
    assert '2.5kW' in status_str, (
        f"Expected '2.5kW' in status text (net = 2500W → 2.5kW, B-4 closure); "
        f"got: {status_str!r}"
    )
    assert '2500.0kW' not in status_str, (
        f"Expected NO '2500.0kW' in status text (B-4 regression witness — "
        f"would mean p1 was double-multiplied); got: {status_str!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — B-2: logger.info gated by success=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_decisions_logger_info_gated_by_success_true(
    fresh_state, caplog
):
    """B-2 closure (success-path direction).

    Mock turn_on to return False for the boiler. Build decisions wanting
    boiler ON with current state off. Assert: no INFO log claims success,
    a WARNING log says turn_on returned False, and confirmed_states does
    NOT include boiler=True.
    """
    app_state.ha_client.turn_on = AsyncMock(return_value=False)

    decisions = Decisions()
    decisions.boiler.action = 'on'
    inputs = _default_inputs(boiler_switch='off')

    with caplog.at_level(logging.WARNING, logger='app.main'):
        confirmed_states = await execute_decisions(decisions, inputs)

    # No INFO record should claim "Boiler: ON" (turn_on failed).
    info_boiler_on = [
        r for r in caplog.records
        if r.levelname == 'INFO' and 'Boiler: ON' in r.message
    ]
    assert not info_boiler_on, (
        f"Expected NO 'Boiler: ON' INFO log when turn_on returned False; "
        f"got {[r.message for r in info_boiler_on]}"
    )

    # A WARNING record should explain the rejection.
    warn_boiler = [
        r for r in caplog.records
        if r.levelname == 'WARNING' and 'Boiler: turn_on returned False' in r.message
    ]
    assert warn_boiler, (
        f"Expected a WARNING 'Boiler: turn_on returned False' log; "
        f"got records: {[(r.levelname, r.message) for r in caplog.records]}"
    )

    # confirmed_states must not lie about boiler being on. On failure the
    # key MUST be absent (CR-2 tightening — `not in` rules out the
    # silent-regression where someone writes False on failure).
    assert 'boiler' not in confirmed_states, (
        f"Expected 'boiler' NOT in confirmed_states (HA call failed, key "
        f"must be absent so _update_device_state falls back to input "
        f"state); got confirmed_states={confirmed_states}"
    )


# ---------------------------------------------------------------------------
# Test 3 — B-3: one device's failure does not abort other devices.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_decisions_one_device_failure_does_not_abort_other_devices(
    fresh_state, caplog
):
    """B-3 closure.

    Mock turn_on to RAISE for the boiler entity, return True for all
    others. Build decisions wanting boiler ON AND table heater ON. Assert
    that an ERROR log captured the boiler exception AND the table heater
    dispatch still ran AND confirmed_states includes heater_table=True.
    """
    config = fresh_state
    boiler_entity = config.entities.boiler_switch
    heater_entity = config.entities.heater_table

    async def turn_on_side_effect(entity_id):
        if entity_id == boiler_entity:
            raise RuntimeError("HA timeout simulating transient failure")
        return True

    app_state.ha_client.turn_on = AsyncMock(side_effect=turn_on_side_effect)

    decisions = Decisions()
    decisions.boiler.action = 'on'
    decisions.heater_table.action = 'on'
    inputs = _default_inputs(
        boiler_switch='off',
        heater_table_switch='off',
    )

    with caplog.at_level(logging.ERROR, logger='app.main'):
        confirmed_states = await execute_decisions(decisions, inputs)

    # An ERROR record must capture the boiler exception.
    err_boiler = [
        r for r in caplog.records
        if r.levelname == 'ERROR' and 'Boiler: execute failed' in r.message
        and 'HA timeout' in r.message
    ]
    assert err_boiler, (
        f"Expected ERROR 'Boiler: execute failed: ... HA timeout' log; "
        f"got: {[(r.levelname, r.message) for r in caplog.records]}"
    )

    # Table heater's turn_on must have been called (cycle did NOT abort).
    called_entities = [
        c.args[0] for c in app_state.ha_client.turn_on.call_args_list
    ]
    assert boiler_entity in called_entities, \
        f"Expected boiler turn_on attempted; called: {called_entities}"
    assert heater_entity in called_entities, (
        f"Expected table heater turn_on called even after boiler failure "
        f"(B-3 isolation); called: {called_entities}"
    )

    # Heater succeeded; boiler did not write confirmed_states.
    assert confirmed_states.get('heater_table') is True, (
        f"Expected heater_table=True in confirmed_states (its dispatch ran "
        f"and succeeded); got: {confirmed_states}"
    )
    assert 'boiler' not in confirmed_states, (
        f"Expected 'boiler' NOT in confirmed_states (its dispatch raised "
        f"before writing); got: {confirmed_states}"
    )


# ---------------------------------------------------------------------------
# Test 4 — B-2 second-direction: turn_off failure on dishwasher.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_decisions_logger_warning_on_turn_off_false_dishwasher(
    fresh_state, caplog
):
    """B-2 closure (failure-path direction, dishwasher OFF).

    Mock turn_off to return False for the dishwasher. Build decisions
    wanting dishwasher OFF with current state on. Assert: no INFO log
    claims 'Dishwasher: PAUSED', a WARNING log says turn_off returned
    False, and confirmed_states does NOT include dishwasher=False.
    """
    app_state.ha_client.turn_off = AsyncMock(return_value=False)

    decisions = Decisions()
    decisions.dishwasher.action = 'off'
    decisions.dishwasher.reason = 'test reason'
    inputs = _default_inputs(dishwasher_switch='on')

    with caplog.at_level(logging.WARNING, logger='app.main'):
        confirmed_states = await execute_decisions(decisions, inputs)

    info_paused = [
        r for r in caplog.records
        if r.levelname == 'INFO' and 'Dishwasher: PAUSED' in r.message
    ]
    assert not info_paused, (
        f"Expected NO 'Dishwasher: PAUSED' INFO log when turn_off returned "
        f"False; got: {[r.message for r in info_paused]}"
    )

    warn_dishwasher = [
        r for r in caplog.records
        if r.levelname == 'WARNING'
        and 'Dishwasher: turn_off returned False' in r.message
    ]
    assert warn_dishwasher, (
        f"Expected WARNING 'Dishwasher: turn_off returned False' log; "
        f"got: {[(r.levelname, r.message) for r in caplog.records]}"
    )

    assert 'dishwasher' not in confirmed_states, (
        f"Expected 'dishwasher' NOT in confirmed_states (HA call failed, "
        f"key must be absent); got: {confirmed_states}"
    )
