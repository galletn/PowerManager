"""Tests for Story 1.2 — _handle_ev log-level contract.

Story 1.2 (PASS2 §5 #10 / §4.1): _handle_ev must not emit INFO log records
per cycle. INFO-level transition logging lives in app.main.execute_decisions
where it's gated by actual state changes. The decision engine itself stays
silent at INFO and uses DEBUG for telemetry.

Each test pins two things per branch:
  1. No INFO records from app.decision_engine (the demotion happened).
  2. A specific DEBUG record exists from the expected branch (the line wasn't
     deleted and the inputs actually hit the branch we mean to exercise).

This combination defends against (a) a revert of the demotion, (b) a
silent deletion of the demoted line, and (c) future predicate drift that
quietly moves a test into a different code path.
"""

import logging
from dataclasses import replace
from datetime import datetime

import pytest

from app.decision_engine import calculate_decisions
from app.models import EVState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_info_records(caplog):
    """Records at INFO or above emitted by app.decision_engine."""
    return [
        r for r in caplog.records
        if r.name == "app.decision_engine" and r.levelno >= logging.INFO
    ]


def _engine_debug_messages_starting(caplog, prefix):
    """DEBUG-level messages from app.decision_engine starting with `prefix`.

    Used as a positive witness that the targeted branch actually executed
    and the demoted line is still present (just at DEBUG).
    """
    return [
        r.message for r in caplog.records
        if r.name == "app.decision_engine"
        and r.levelno == logging.DEBUG
        and r.message.startswith(prefix)
    ]


@pytest.fixture
def summer_noon():
    """Off-peak weekday noon — keeps tariff logic simple."""
    return datetime(2024, 7, 15, 14, 0, 0)


def _assert_no_engine_info(caplog):
    info_records = _engine_info_records(caplog)
    assert not info_records, (
        "decision_engine emitted INFO records per cycle: "
        f"{[r.message for r in info_records]}"
    )


# ---------------------------------------------------------------------------
# 1. Solar surplus active (auto override, conditions met)
# ---------------------------------------------------------------------------


def test_solar_active_emits_no_info_and_debug_present(
    base_inputs, config, device_state, summer_noon, caplog
):
    """Solar happy path: large PV, battery charging, exporting.

    Pins: no INFO from app.decision_engine, AND a DEBUG record matching
    `EV solar: OK ` (the human-readable reason for the active branch) so
    a deletion of decision_engine.py:1003 would fail this test.
    """
    inputs = replace(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch="on",
        ev_power=4000,
        ev_limit=8,
        ovr_ev="",
        pv_power=5000,
        p1_power=-500,
        p1_return=500,
        battery_power=-1500,
        battery_soe=50.0,
    )

    with caplog.at_level(logging.DEBUG, logger="app.decision_engine"):
        calculate_decisions(inputs, config, device_state, summer_noon)

    _assert_no_engine_info(caplog)
    # Use "EV solar: OK " (with trailing space) to exclude "EV solar raw:".
    witnesses = _engine_debug_messages_starting(caplog, "EV solar: OK ")
    assert witnesses, (
        "Expected DEBUG witness 'EV solar: OK ...' from solar-active branch; "
        f"got DEBUG messages: "
        f"{[r.message for r in caplog.records if r.name == 'app.decision_engine']}"
    )


# ---------------------------------------------------------------------------
# 2. Solar surplus blocked (auto override, conditions fail)
# ---------------------------------------------------------------------------


def test_solar_blocked_emits_no_info_and_debug_present(
    base_inputs, config, device_state, summer_noon, caplog
):
    """Solar blocked: low battery SOE — `wait — batt X% < 15%` branch.

    Pins: no INFO, AND a DEBUG record matching `EV solar: wait `.
    """
    inputs = replace(
        base_inputs,
        ev_state=EVState.IEC_CONNECTED_B2,
        ev_switch="off",
        ev_power=0,
        ovr_ev="",
        pv_power=2000,
        p1_power=200,
        p1_return=0,
        battery_power=0,
        battery_soe=10.0,
    )

    with caplog.at_level(logging.DEBUG, logger="app.decision_engine"):
        calculate_decisions(inputs, config, device_state, summer_noon)

    _assert_no_engine_info(caplog)
    witnesses = _engine_debug_messages_starting(caplog, "EV solar: wait")
    assert witnesses, (
        "Expected DEBUG witness 'EV solar: wait ...' from solar-blocked "
        "branch; got DEBUG messages: "
        f"{[r.message for r in caplog.records if r.name == 'app.decision_engine']}"
    )


# ---------------------------------------------------------------------------
# 3. Solar override + charging + conditions blocked (§1069 branch)
# ---------------------------------------------------------------------------


def test_solar_override_pause_emits_no_info_and_debug_present(
    base_inputs, config, device_state, summer_noon, caplog
):
    """ovr_ev='solar' + already charging + no surplus → §1069 PAUSING line.

    Pins: no INFO, AND a DEBUG record matching the §1069 PAUSING string so
    a deletion of decision_engine.py:1069 would fail this test.
    """
    inputs = replace(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch="on",
        ev_power=4000,
        ev_limit=6,
        ovr_ev="solar",
        pv_power=500,
        p1_power=2000,
        p1_return=0,
        battery_power=500,
        battery_soe=20.0,
    )

    with caplog.at_level(logging.DEBUG, logger="app.decision_engine"):
        calculate_decisions(inputs, config, device_state, summer_noon)

    _assert_no_engine_info(caplog)
    witnesses = _engine_debug_messages_starting(
        caplog, "EV: PAUSING - solar mode but"
    )
    assert witnesses, (
        "Expected DEBUG witness 'EV: PAUSING - solar mode but ...' from the "
        "override-pause branch; got DEBUG messages: "
        f"{[r.message for r in caplog.records if r.name == 'app.decision_engine']}"
    )


# ---------------------------------------------------------------------------
# 4. Solar override + plugged-but-not-charging (§1072 branch)
# ---------------------------------------------------------------------------


def test_solar_override_waiting_emits_no_info_and_debug_present(
    base_inputs, config, device_state, summer_noon, caplog
):
    """ovr_ev='solar' + plugged + not charging + no surplus → §1072 waiting.

    Pins: no INFO, AND a DEBUG record matching the §1072 waiting string so
    a deletion of decision_engine.py:1072 would fail this test.
    """
    inputs = replace(
        base_inputs,
        ev_state=EVState.IEC_CONNECTED_B2,
        ev_switch="off",
        ev_power=0,
        ovr_ev="solar",
        pv_power=300,
        p1_power=1500,
        p1_return=0,
        battery_power=200,
        battery_soe=20.0,
    )

    with caplog.at_level(logging.DEBUG, logger="app.decision_engine"):
        calculate_decisions(inputs, config, device_state, summer_noon)

    _assert_no_engine_info(caplog)
    witnesses = _engine_debug_messages_starting(
        caplog, "EV: solar mode, waiting"
    )
    assert witnesses, (
        "Expected DEBUG witness 'EV: solar mode, waiting ...' from the "
        "override-waiting branch; got DEBUG messages: "
        f"{[r.message for r in caplog.records if r.name == 'app.decision_engine']}"
    )
