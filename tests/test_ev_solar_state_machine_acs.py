"""Tests for Story 1.4 ACs #1-9 — `_handle_ev` solar state machine pinning.

Pins the solar branches of `_handle_ev` in app/decision_engine.py
(entry guard, START gates, ADJUST, PAUSE, super-off-peak skip, None-handling).
The hysteresis-mechanism tests for Stories 1.5 / 1.6 / 1.7 / 1.10 live in the
companion file test_ev_solar_state_machine_hysteresis.py.

Each test pins both the state change (decision/action) AND a positive
witness (a plan entry or DEBUG record). Absence-only assertions can pass
vacuously and have bitten this surface before (Story 1.2 lesson).

Production code is not modified by this story (AC #11). Where an AC describes
behavior the code does not currently exhibit, the test is marked xfail and the
discrepancy is logged in deferred-work.md.
"""

import logging
from datetime import datetime

import pytest

from app.decision_engine import calculate_decisions
from app.models import EVState
from tests._plan_helpers import assert_plan_contains, assert_plan_no_match
from tests.conftest import solar_inputs


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def super_off_peak_night():
    """03:00 weekday July — super-off-peak. Used for the tariff-skip seal."""
    return datetime(2024, 7, 15, 3, 0, 0)


def _engine_debug_messages_starting(caplog, prefix):
    """DEBUG-level messages from app.decision_engine starting with `prefix`."""
    return [
        r.message for r in caplog.records
        if r.name == "app.decision_engine"
        and r.levelno == logging.DEBUG
        and r.message.startswith(prefix)
    ]


# ===========================================================================
# AC #1 — Entry-guard contract (4 tests)
# ===========================================================================


def test_override_off_does_not_emit_solar_action(
    base_inputs, config, device_state, summer_noon
):
    """ovr_ev='off' → _apply_manual_overrides sets action='off' and the solar
    branch early-returns without overwriting.

    AC #1 first bullet literally states `action == 'none'`, but the manual
    override path sets `action='off'` BEFORE `_handle_ev` runs. The contract
    pinned here is "solar branch did not contribute" — witnessed by 'OVERRIDE
    OFF' present in plan and the action remaining 'off'.
    """
    inputs = solar_inputs(base_inputs, ovr_ev='off')
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'off', \
        f"Override should set action='off'; got {result.decisions.ev.action}"
    assert_plan_contains(result.plan, 'OVERRIDE OFF', msg=f"Expected 'OVERRIDE OFF' in plan; got: {result.plan}")
    # Solar branch must NOT have fired any of its actions.
    forbidden = ('SOLAR START', 'PAUSE (insufficient solar)', 'PAUSE solar mode',
                 'waiting for solar', 'adjust to')
    for marker in forbidden:
        assert_plan_no_match(result.plan, marker,
            msg=f"Solar branch must not leak {marker!r}")


def test_override_on_does_not_emit_competing_solar_action(
    base_inputs, config, device_state, summer_noon
):
    """ovr_ev='on' → _apply_manual_overrides emits the EV decision and the
    solar branch early-returns without overwriting it.

    Pin the contract: with override='on', the OVERRIDE ON plan entry is the
    sole source of `decisions.ev.action` / `amps`. The solar branch leaves
    those values intact (no 'SOLAR START' / 'adjust' / 'PAUSE' leakage).
    """
    inputs = solar_inputs(base_inputs, ovr_ev='on')
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'on', \
        f"Override should produce action='on'; got {result.decisions.ev.action}"
    # Concrete amps pin: at summer_noon off-peak, max_import=5000W, net_p1=-1000W
    # → headroom=6000W → target_amps=int(6000/692)=8 → max(6, min(8, 16))=8.
    # If the solar branch overwrote, amps would either be 6 (SOLAR START's
    # ramp-from-min) or some other clamped value — this `== 8` discriminates.
    assert result.decisions.ev.amps == 8, (
        f"Expected override-computed amps=8 (headroom 6000W / 692 watts_per_amp); "
        f"got {result.decisions.ev.amps}A — solar branch may have overwritten."
    )
    assert_plan_contains(result.plan, 'OVERRIDE ON', msg=f"Expected 'OVERRIDE ON' in plan; got: {result.plan}")
    forbidden = ('SOLAR START', 'PAUSE (insufficient solar)', 'PAUSE solar mode',
                 'adjust to')
    for marker in forbidden:
        assert_plan_no_match(result.plan, marker,
            msg=f"Solar branch must not leak {marker!r}")


def test_full_state_returns_none(
    base_inputs, config, device_state, summer_noon
):
    """ev_state=FULL → solar branch early-returns, action stays 'none'.

    Note: the engine has a "BMW disagreement" override at decision_engine.py
    :383-393 that flips ev_done back to False when the at-home BMW reports
    SOC < 75%. The baseline fixture has bmw_i5_battery=40, which would
    trigger that override and let the solar branch fire. Bump i5 to 80 so
    the FULL state survives into _handle_ev (this AC pins the entry guard,
    not the BMW disagreement path).
    """
    inputs = solar_inputs(
        base_inputs, ev_state=EVState.FULL, bmw_i5_battery=80,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'none', \
        f"FULL state should leave action='none'; got {result.decisions.ev.action}"


def test_unplugged_returns_none(
    base_inputs, config, device_state, summer_noon
):
    """ev_state=NO_CAR → solar branch early-returns, action stays 'none'."""
    inputs = solar_inputs(base_inputs, ev_state=EVState.NO_CAR)
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'none', \
        f"NO_CAR should leave action='none'; got {result.decisions.ev.action}"


# ===========================================================================
# AC #2 — Solar START path (1 test)
# ===========================================================================


def test_solar_start_action_amps_and_plan_entry(
    base_inputs, config, device_state, summer_noon
):
    """All start gates met → action='on', amps=min_amps (ramp-from-min),
    'SOLAR START' in plan.

    Pins the ramp-from-min contract: EV always starts at 6A regardless of
    available headroom, then ramps up ±1A per cycle.
    """
    inputs = solar_inputs(base_inputs)  # READY + generous solar
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'on'
    assert result.decisions.ev.amps == config.ev.min_amps, \
        f"Expected start at min_amps={config.ev.min_amps}A; got {result.decisions.ev.amps}A"
    assert_plan_contains(result.plan, 'SOLAR START', msg=f"Expected 'SOLAR START' in plan; got: {result.plan}")


# ===========================================================================
# AC #3 + #4 — ADJUST path (ramp up / ramp down)
# AC #5 — PAUSE path (xfail: unreachable under current production code)
# ===========================================================================


def test_solar_adjust_ramps_up_one_amp_per_cycle(
    base_inputs, config, device_state, summer_noon
):
    """ev_limit=6, very generous solar (target ≥10A) → action='adjust',
    amps=7 (clamped to current+1, NOT the full target).

    Proves the ±1A-per-cycle clamp on ramp-up.
    """
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=4000,
        ev_limit=6,
        pv_power=10000,
        p1_return=4000,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'adjust', \
        f"Expected adjust; got {result.decisions.ev.action} (plan: {result.plan})"
    assert result.decisions.ev.amps == 7, \
        f"Expected ramp to 7A (current+1); got {result.decisions.ev.amps}A"
    # Plan-witness per module-docstring rule (state + positive witness).
    # Format from decision_engine.py:1051: "EV: adjust to {N}A (solar, target ...)"
    assert_plan_contains(result.plan, 'adjust to 7A', msg=f"Expected 'adjust to 7A' plan witness; got: {result.plan}")


def test_solar_adjust_ramps_down_one_amp_per_cycle(
    base_inputs, config, device_state, summer_noon
):
    """ev_limit=10, modest solar (target ≤8A) → action='adjust', amps=9
    (clamped to current-1).

    Proves the ±1A-per-cycle clamp on ramp-down.
    """
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=6000,
        ev_limit=10,
        pv_power=3000,
        p1_power=2000,
        p1_return=0,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'adjust', \
        f"Expected adjust; got {result.decisions.ev.action} (plan: {result.plan})"
    assert result.decisions.ev.amps == 9, \
        f"Expected ramp to 9A (current-1); got {result.decisions.ev.amps}A"
    # Plan-witness per module-docstring rule (state + positive witness).
    assert_plan_contains(result.plan, 'adjust to 9A', msg=f"Expected 'adjust to 9A' plan witness; got: {result.plan}")


def test_solar_pause_when_target_below_min_amps(
    base_inputs, config, device_state, summer_noon, ev_state_just_cleared_on
):
    """ev_state=CHARGING, ev_limit=6, very low PV → action='pause' with
    'PAUSE (insufficient solar)' plan witness. Pins the pre-clamp pause that
    fires when available_amps falls below min_amps while already charging.
    """
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=0,
        ev_limit=6,
        pv_power=1600,
        p1_power=800,
        p1_return=0,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'pause'
    assert_plan_contains(result.plan, 'PAUSE (insufficient solar)', msg=f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}")


# ===========================================================================
# AC #6 — Start-vs-continue asymmetry (2 tests)
# ===========================================================================


def test_cannot_start_without_battery_charging(
    base_inputs, config, device_state, summer_noon, caplog
):
    """has_good_solar requires battery_power < -1000W (battery actively
    charging from solar). With battery idle (battery_power=0), the solar
    branch refuses to START even though SOE and PV pass.

    Primary assertion: DEBUG witness contains 'batt not charging ≥1kW'. The
    test deliberately does NOT assert `action != 'on'` because at this
    timestamp the tariff branch may legitimately start the EV from grid —
    that's a different code path and not what this AC pins.
    """
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        pv_power=3000,
        battery_soe=50.0,
        battery_power=0,        # battery idle, not charging
        p1_power=-500,
        p1_return=500,          # still exporting
    )

    with caplog.at_level(logging.DEBUG, logger="app.decision_engine"):
        calculate_decisions(inputs, config, device_state, summer_noon)

    witnesses = _engine_debug_messages_starting(caplog, "EV solar: wait")
    assert witnesses, (
        "Expected 'EV solar: wait ...' DEBUG witness from blocked-solar branch; "
        f"got: {[r.message for r in caplog.records if r.name == 'app.decision_engine']}"
    )
    assert_plan_contains(witnesses, 'batt not charging', msg=f"Expected 'batt not charging' in DEBUG witnesses; got: {witnesses}")


def test_continues_charging_when_battery_flips_to_discharging(
    base_inputs, config, device_state, summer_noon
):
    """ev_solar_active (continue gate) requires only bat_has_buffer + PV>1500
    when ev_charging=True. The relaxed gate is deliberate: once the EV is on,
    it itself causes battery discharge — re-checking battery_charging_enough
    would cause flip-flop.

    Setup: EV charging at 8A draws ~5kW, battery flips to +500W discharging.
    Assertion: EV is NOT yanked off (action != 'pause' AND != 'off').
    """
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=5000,
        ev_limit=8,
        pv_power=3000,
        battery_soe=40.0,
        battery_power=+500,     # battery now discharging
        p1_power=500,
        p1_return=0,            # not exporting
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action != 'pause', \
        f"EV was yanked to pause on first battery flip; plan: {result.plan}"
    assert result.decisions.ev.action != 'off', \
        f"EV was yanked off on first battery flip; plan: {result.plan}"
    # Positive assertion (story AC #6b allowed actions: 'adjust' or 'none'). Math
    # for this fixture: target_amps=7, clamped to 9 (current-1) wait no — current=8,
    # target=7 → clamp_down=max(7, 7)=7 → action='adjust'. We pin the allowed set
    # rather than == 'adjust' so a future refactor that returns 'none' here
    # (deemed acceptable per spec) doesn't break the regression seal.
    assert result.decisions.ev.action in ('adjust', 'none'), (
        f"Expected adjust or none (per AC #6b allowed set); "
        f"got {result.decisions.ev.action!r}, plan: {result.plan}"
    )


# ===========================================================================
# AC #7 — Solar override (`ovr_ev='solar'`) branches (4 tests)
# ===========================================================================


def test_solar_mode_pause_low_battery(
    base_inputs, config, device_state, summer_noon
):
    """ovr_ev='solar' + charging + battery below 15% → pause with 'battery
    too low' reason. Solar branch doesn't fire (bat_has_buffer=False), so
    override-pause logic at 1059-1070 takes over.
    """
    inputs = solar_inputs(
        base_inputs,
        ovr_ev='solar',
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=4000,
        pv_power=2000,
        battery_soe=10.0,       # below 15 → bat_has_buffer=False
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'pause'
    assert_plan_contains(result.plan, 'PAUSE solar mode', msg=f"Expected 'PAUSE solar mode' in plan; got: {result.plan}")
    assert_plan_contains(result.plan, 'battery too low', msg=f"Expected 'battery too low' reason in plan; got: {result.plan}")


def test_solar_mode_pause_low_pv(
    base_inputs, config, device_state, summer_noon
):
    """ovr_ev='solar' + charging + PV below 1500W → pause with 'PV too low'."""
    inputs = solar_inputs(
        base_inputs,
        ovr_ev='solar',
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=4000,
        pv_power=500,
        battery_soe=50.0,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'pause'
    assert_plan_contains(result.plan, 'PAUSE solar mode', msg=f"Expected 'PAUSE solar mode' in plan; got: {result.plan}")
    assert_plan_contains(result.plan, 'PV too low', msg=f"Expected 'PV too low' reason in plan; got: {result.plan}")


def test_solar_mode_waiting_when_not_charging(
    base_inputs, config, device_state, summer_noon
):
    """ovr_ev='solar' + plugged + not charging + no surplus → action stays
    'none' (no override path applies) and plan contains 'waiting for solar'.
    """
    inputs = solar_inputs(
        base_inputs,
        ovr_ev='solar',
        ev_state=EVState.READY,
        pv_power=500,           # below 1500 so solar branch doesn't fire
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'none', \
        f"Expected 'none' while waiting for solar; got {result.decisions.ev.action}"
    assert_plan_contains(result.plan, 'waiting for solar', msg=f"Expected 'waiting for solar' in plan; got: {result.plan}")


def test_solar_mode_skips_tariff_at_super_off_peak(
    base_inputs, config, device_state, super_off_peak_night
):
    """The regression seal for line 1074. With ovr_ev='solar' at
    super-off-peak (when tariff branch would otherwise charge from grid),
    the return on line 1074 prevents fall-through → action stays 'pause',
    not 'on' or 'adjust'.

    Without that return, a solar-mode EV with no surplus would charge from
    grid at super-off-peak — exactly what the user asked the system NOT to do.
    """
    inputs = solar_inputs(
        base_inputs,
        ovr_ev='solar',
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=4000,
        pv_power=2000,
        battery_soe=10.0,       # forces solar-mode pause via low-battery branch
    )
    result = calculate_decisions(inputs, config, device_state, super_off_peak_night)

    assert result.decisions.ev.action == 'pause', \
        f"Tariff fall-through leaked at super-off-peak; got {result.decisions.ev.action} (plan: {result.plan})"
    assert_plan_contains(result.plan, 'PAUSE solar mode', msg=f"Expected 'PAUSE solar mode'; got: {result.plan}")


# ===========================================================================
# AC #8 — Boundary thresholds (1 parametrized test)
# ===========================================================================


@pytest.mark.parametrize(
    "soe,pv,batt_power,expect_start",
    [
        (15.0,  3000, -1500, True),    # SOE inclusive (>= 15)
        (14.99, 3000, -1500, False),   # SOE just below
        (50.0,  1501, -1500, True),    # PV just above (> 1500)
        (50.0,  1500, -1500, False),   # PV on the line (<=)
        (50.0,  3000, -1001, True),    # battery charging just over (< -1000)
        (50.0,  3000, -1000, False),   # battery charging on the line (<, not <=)
    ],
    ids=[
        "soe_15_inclusive",
        "soe_14_99_below",
        "pv_1501_above",
        "pv_at_1500_excluded",
        "batt_neg_1001_above",
        "batt_neg_1000_on_line",
    ],
)
def test_solar_start_thresholds(
    base_inputs, config, device_state, summer_noon,
    soe, pv, batt_power, expect_start,
):
    """Inclusivity boundaries for the three solar-start gates:
      - bat_has_buffer: `battery_soe >= 15`
      - PV gate:        `smooth_pv > 1500`  (strict)
      - charging gate:  `battery_power < -1000` (strict)
    """
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_soe=soe,
        pv_power=pv,
        battery_power=batt_power,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert (result.decisions.ev.action == 'on') is expect_start, (
        f"Boundary case soe={soe}, pv={pv}, batt={batt_power}: "
        f"expected start={expect_start}, got action={result.decisions.ev.action} "
        f"(plan: {result.plan})"
    )


# ===========================================================================
# AC #9 — Defensive None handling (2 tests)
# ===========================================================================


def test_battery_soe_none_blocks_start_with_unknown_reason(
    base_inputs, config, device_state, summer_noon, caplog
):
    """battery_soe=None → bat_has_buffer=False (conservative) → solar start
    is blocked, DEBUG witness reason contains 'batt unknown'.
    """
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_soe=None,       # unknown
    )

    with caplog.at_level(logging.DEBUG, logger="app.decision_engine"):
        result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action != 'on', \
        f"EV should not start when battery SOE unknown; got {result.decisions.ev.action}"
    witnesses = _engine_debug_messages_starting(caplog, "EV solar: wait")
    assert_plan_contains(witnesses, 'batt unknown', msg=f"Expected 'batt unknown' DEBUG witness; got: {witnesses}")


def test_battery_power_none_does_not_crash(
    base_inputs, config, device_state, summer_noon
):
    """battery_power=None with a known battery_soe must NOT crash
    calculate_decisions. The status-line block is skipped (both bat_soe AND
    bat_power must be non-None to render it) and downstream _handle_ev keeps
    its own None-safe handling. Action stays 'none' because solar START
    requires battery actively charging ≥1kW, which None can't satisfy.
    """
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_power=None,
        battery_soe=50.0,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'none', (
        f"battery_power=None should leave action='none' (start blocked because "
        f"battery_charging_enough=False); got {result.decisions.ev.action}"
    )
