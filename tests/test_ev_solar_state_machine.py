"""Tests for Story 1.4 — `_handle_ev` solar state machine pinning.

Pins the solar branches of `_handle_ev` in app/decision_engine.py (lines
905-1074) so the start-vs-continue asymmetry, solar-mode override, and the
START/ADJUST/PAUSE transitions can't drift silently under future refactors.
Closes the "_handle_ev solar" half of CODE_REVIEW_PASS2 §5 row 11
(the `is_boiler_full` and `PowerBuffer` halves are tracked separately).

Each test pins both the state change (decision/action) AND a positive
witness (a plan entry or DEBUG record). Absence-only assertions can pass
vacuously and have bitten this surface before (Story 1.2 lesson).

Production code is not modified by this story (AC #11). Where an AC describes
behavior the code does not currently exhibit, the test is marked xfail and the
discrepancy is logged in deferred-work.md.
"""

import logging
from dataclasses import replace
from datetime import datetime

import pytest

from app.decision_engine import calculate_decisions
from app.models import EVState


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def summer_noon():
    """14:00 weekday July — off-peak. Tariff branch doesn't dominate solar."""
    return datetime(2024, 7, 15, 14, 0, 0)


@pytest.fixture
def super_off_peak_night():
    """03:00 weekday July — super-off-peak. Used for the tariff-skip seal."""
    return datetime(2024, 7, 15, 3, 0, 0)


def _solar_inputs(base_inputs, **kw):
    """All four solar START gates met by default. Tests override one knob.

    Baseline produces:
      - smooth_pv = 3000 (> 1500)
      - bat_has_buffer = True (soe 50 >= 15)
      - battery_charging_enough = True (battery_power -1500 < -1000)
      - smooth_is_exporting = True (p1_return 500 > p1 -500)
      - ev_ready = True, ev_charging = False, ev_plugged = True, ev_done = False
    """
    defaults = dict(
        ovr_ev='',           # parses to 'auto'
        pv_power=3000,
        p1_power=-500,
        p1_return=500,
        battery_power=-1500,
        battery_soe=50.0,
        ev_state=EVState.READY,
        ev_switch='off',
        ev_power=0,
        ev_limit=6,
    )
    defaults.update(kw)
    return replace(base_inputs, **defaults)


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
    inputs = _solar_inputs(base_inputs, ovr_ev='off')
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'off', \
        f"Override should set action='off'; got {result.decisions.ev.action}"
    assert any('OVERRIDE OFF' in entry for entry in result.plan), \
        f"Expected 'OVERRIDE OFF' in plan; got: {result.plan}"
    # Solar branch must NOT have fired any of its actions.
    forbidden = ('SOLAR START', 'PAUSE (insufficient solar)', 'PAUSE solar mode',
                 'waiting for solar', 'adjust to')
    for marker in forbidden:
        assert not any(marker in entry for entry in result.plan), \
            f"Solar branch leaked '{marker}' into plan: {result.plan}"


def test_override_on_does_not_emit_competing_solar_action(
    base_inputs, config, device_state, summer_noon
):
    """ovr_ev='on' → _apply_manual_overrides emits the EV decision and the
    solar branch early-returns without overwriting it.

    Pin the contract: with override='on', the OVERRIDE ON plan entry is the
    sole source of `decisions.ev.action` / `amps`. The solar branch leaves
    those values intact (no 'SOLAR START' / 'adjust' / 'PAUSE' leakage).
    """
    inputs = _solar_inputs(base_inputs, ovr_ev='on')
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
    assert any('OVERRIDE ON' in entry for entry in result.plan), \
        f"Expected 'OVERRIDE ON' in plan; got: {result.plan}"
    forbidden = ('SOLAR START', 'PAUSE (insufficient solar)', 'PAUSE solar mode',
                 'adjust to')
    for marker in forbidden:
        assert not any(marker in entry for entry in result.plan), \
            f"Solar branch leaked '{marker}' into plan: {result.plan}"


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
    inputs = _solar_inputs(
        base_inputs, ev_state=EVState.FULL, bmw_i5_battery=80,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'none', \
        f"FULL state should leave action='none'; got {result.decisions.ev.action}"


def test_unplugged_returns_none(
    base_inputs, config, device_state, summer_noon
):
    """ev_state=NO_CAR → solar branch early-returns, action stays 'none'."""
    inputs = _solar_inputs(base_inputs, ev_state=EVState.NO_CAR)
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
    inputs = _solar_inputs(base_inputs)  # READY + generous solar
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'on'
    assert result.decisions.ev.amps == config.ev.min_amps, \
        f"Expected start at min_amps={config.ev.min_amps}A; got {result.decisions.ev.amps}A"
    assert any('SOLAR START' in entry for entry in result.plan), \
        f"Expected 'SOLAR START' in plan; got: {result.plan}"


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
    inputs = _solar_inputs(
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
    assert any('adjust to 7A' in entry for entry in result.plan), \
        f"Expected 'adjust to 7A' plan witness; got: {result.plan}"


def test_solar_adjust_ramps_down_one_amp_per_cycle(
    base_inputs, config, device_state, summer_noon
):
    """ev_limit=10, modest solar (target ≤8A) → action='adjust', amps=9
    (clamped to current-1).

    Proves the ±1A-per-cycle clamp on ramp-down.
    """
    inputs = _solar_inputs(
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
    assert any('adjust to 9A' in entry for entry in result.plan), \
        f"Expected 'adjust to 9A' plan witness; got: {result.plan}"


def test_solar_pause_when_target_below_min_amps(
    base_inputs, config, device_state, summer_noon
):
    """ev_state=CHARGING, ev_limit=6, very low PV → action='pause' with
    'PAUSE (insufficient solar)' plan witness. Pins the pre-clamp pause that
    fires when available_amps falls below min_amps while already charging.
    """
    # Seed past min_on_time to bypass Story 1.7's cold-start lock.
    device_state.ev.on = True
    device_state.ev.last_change = summer_noon.timestamp() * 1000 - 400_000

    inputs = _solar_inputs(
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
    assert any('PAUSE (insufficient solar)' in e for e in result.plan), \
        f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}"


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
    inputs = _solar_inputs(
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
    assert any('batt not charging' in m for m in witnesses), \
        f"Expected 'batt not charging' in DEBUG witnesses; got: {witnesses}"


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
    inputs = _solar_inputs(
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
    inputs = _solar_inputs(
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
    assert any('PAUSE solar mode' in e for e in result.plan), \
        f"Expected 'PAUSE solar mode' in plan; got: {result.plan}"
    assert any('battery too low' in e for e in result.plan), \
        f"Expected 'battery too low' reason in plan; got: {result.plan}"


def test_solar_mode_pause_low_pv(
    base_inputs, config, device_state, summer_noon
):
    """ovr_ev='solar' + charging + PV below 1500W → pause with 'PV too low'."""
    inputs = _solar_inputs(
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
    assert any('PAUSE solar mode' in e for e in result.plan), \
        f"Expected 'PAUSE solar mode' in plan; got: {result.plan}"
    assert any('PV too low' in e for e in result.plan), \
        f"Expected 'PV too low' reason in plan; got: {result.plan}"


def test_solar_mode_waiting_when_not_charging(
    base_inputs, config, device_state, summer_noon
):
    """ovr_ev='solar' + plugged + not charging + no surplus → action stays
    'none' (no override path applies) and plan contains 'waiting for solar'.
    """
    inputs = _solar_inputs(
        base_inputs,
        ovr_ev='solar',
        ev_state=EVState.READY,
        pv_power=500,           # below 1500 so solar branch doesn't fire
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'none', \
        f"Expected 'none' while waiting for solar; got {result.decisions.ev.action}"
    assert any('waiting for solar' in e for e in result.plan), \
        f"Expected 'waiting for solar' in plan; got: {result.plan}"


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
    inputs = _solar_inputs(
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
    assert any('PAUSE solar mode' in e for e in result.plan), \
        f"Expected 'PAUSE solar mode'; got: {result.plan}"


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
    inputs = _solar_inputs(
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
    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_soe=None,       # unknown
    )

    with caplog.at_level(logging.DEBUG, logger="app.decision_engine"):
        result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action != 'on', \
        f"EV should not start when battery SOE unknown; got {result.decisions.ev.action}"
    witnesses = _engine_debug_messages_starting(caplog, "EV solar: wait")
    assert any('batt unknown' in m for m in witnesses), \
        f"Expected 'batt unknown' DEBUG witness; got: {witnesses}"


def test_battery_power_none_does_not_crash(
    base_inputs, config, device_state, summer_noon
):
    """battery_power=None with a known battery_soe must NOT crash
    calculate_decisions. The status-line block is skipped (both bat_soe AND
    bat_power must be non-None to render it) and downstream _handle_ev keeps
    its own None-safe handling. Action stays 'none' because solar START
    requires battery actively charging ≥1kW, which None can't satisfy.
    """
    inputs = _solar_inputs(
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


# ===========================================================================
# Story 1.5 — Boundary tests for pre-clamp pause and None-safe status line
# ===========================================================================


def test_solar_pause_with_higher_ev_limit(
    base_inputs, config, device_state, summer_noon
):
    """Already charging at ev_limit=10 with collapsed PV → available_amps < 6
    fires the pre-clamp pause. Complements test_solar_pause_when_target_below_min_amps
    (ev_limit=6) by proving the pause path is independent of the current limit.

    Trace: available_power = 1000 - 3500 - 0 = -2500;
    current_ev_watts = max(4000, 10*692=6920) = 6920;
    total_for_ev = -2500 + 6920 - 300 = 4120; available_amps = int(4120/692) = 5.
    5 < 6 (min_amps) → pause.
    """
    # Seed past min_on_time to bypass Story 1.7's cold-start lock.
    device_state.ev.on = True
    device_state.ev.last_change = summer_noon.timestamp() * 1000 - 400_000

    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=4000,
        ev_limit=10,
        pv_power=1600,
        p1_power=3500,
        p1_return=0,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'pause', \
        f"Expected pause; got {result.decisions.ev.action} (plan: {result.plan})"
    assert any('PAUSE (insufficient solar)' in e for e in result.plan), \
        f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}"


def test_solar_adjust_at_min_amps_boundary(
    base_inputs, config, device_state, summer_noon
):
    """available_amps == min_amps (6) exactly → adjust path, NOT pause. The
    pre-clamp guard uses strict `<`, so the inclusive boundary stays in adjust.

    Trace: current_ev_watts = max(4000, 7*692=4844) = 4844; with p1_power=900,
    p1_return=0, battery_power=-1500: available_power = 1000-900-0 = 100;
    total_for_ev = 100 + 4844 - 300 = 4644; available_amps = int(4644/692) = 6.
    target_amps = max(6, min(6, 16)) = 6; ramp-down clamped_amps = max(6, 7-1) = 6.
    """
    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=4000,
        ev_limit=7,
        pv_power=2000,
        p1_power=900,
        p1_return=0,
        battery_power=-1500,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'adjust', \
        f"Expected adjust at boundary (available_amps==min_amps); got {result.decisions.ev.action} (plan: {result.plan})"
    assert result.decisions.ev.amps == 6, \
        f"Expected ramp-down to 6A; got {result.decisions.ev.amps}A"
    assert any('adjust to 6A' in e for e in result.plan), \
        f"Expected 'adjust to 6A' plan witness; got: {result.plan}"


def test_battery_power_and_soe_both_none_does_not_crash(
    base_inputs, config, device_state, summer_noon
):
    """battery_power=None AND battery_soe=None must not crash. Status-line
    block skipped (bat_soe guard); solar START blocked (no buffer + no
    charging signal); tariff branch at summer noon off-peak with ev_ready waits
    for super-off-peak → action stays 'none'.
    """
    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_power=None,
        battery_soe=None,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'none', (
        f"battery_power=None AND battery_soe=None should leave action='none'; "
        f"got {result.decisions.ev.action} (plan: {result.plan})"
    )


def test_battery_status_line_unknown_when_power_none(
    base_inputs, config, device_state, summer_noon
):
    """battery_power=None + battery_soe=50.0 → render `Bat: power unknown (50%)`.

    Story 1.8 trades Story 1.5's silent omission for a graceful fallback:
    when the HA battery-power sensor is transiently unavailable but SOE is
    still reporting, the operator retains SOE visibility on the dashboard.
    Charging/Discharging/Idle labels are mutually exclusive with the
    unknown-power label.
    """
    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_power=None,
        battery_soe=50.0,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert any('Bat: power unknown (50%)' in e for e in result.plan), \
        f"Expected 'Bat: power unknown (50%)' in plan; got: {result.plan}"
    assert not any(
        'Bat: Charging' in e
        or 'Bat: Discharging' in e
        or 'Bat: Idle' in e
        for e in result.plan
    ), f"Expected no other 'Bat: ' label alongside 'power unknown'; got: {result.plan}"


def test_battery_status_line_unknown_omits_reclaimable_suffix(
    base_inputs, config, device_state, summer_noon
):
    """battery_power=None + sustained solar export → status line shows
    'Bat: power unknown ({soe}%)' WITHOUT the '[+X reclaimable]' suffix.

    `get_solar_battery_charge` at decision_engine.py:48-50 returns 0.0
    when battery_power is None, so battery_charge=0 and the suffix-append
    branch at line ~462 is skipped naturally. This test pins that the
    suffix doesn't sneak in via some other code path.
    """
    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_power=None,
        battery_soe=50.0,
        pv_power=3000,
        p1_power=-500,
        p1_return=500,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert any('Bat: power unknown (50%)' in e for e in result.plan), \
        f"Expected 'Bat: power unknown (50%)' in plan; got: {result.plan}"
    assert not any('reclaimable' in e for e in result.plan), \
        f"Expected no '[+X reclaimable]' suffix when bat_power=None; got: {result.plan}"


def test_battery_status_line_unknown_via_battery_status_field(
    base_inputs, config, device_state, summer_noon
):
    """Production-path: ha_client.py:493 coerces unavailable bat_power to
    0.0 (via `... or 0.0`), so the dataclass never sees None in real HA
    data. Story 1.8 CR DN1 patch consults `inputs.battery_status` as the
    tie-break: when bat_power == 0.0 AND battery_status reports the sensor
    is unknown/unavailable, render "Bat: power unknown" instead of the
    misleading "Bat: Idle".

    With bat_power=None (test path), the unknown branch also fires — but
    this test pins the production-realistic case explicitly.
    """
    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_power=0.0,
        battery_soe=50.0,
        battery_status='unavailable',
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert any('Bat: power unknown (50%)' in e for e in result.plan), (
        f"Expected 'Bat: power unknown (50%)' in plan when battery_power=0 "
        f"AND battery_status='unavailable'; got: {result.plan}"
    )
    assert not any('Bat: Idle' in e for e in result.plan), \
        f"Expected no 'Bat: Idle' alongside 'power unknown'; got: {result.plan}"


# ===========================================================================
# Story 1.6 — Hysteresis-gated pre-clamp pause
# ===========================================================================
#
# The pre-clamp pause added by Story 1.5 at decision_engine.py:1044-1048 is
# now gated on `can_switch('ev', False)` to honor `min_on_time=300s` hysteresis,
# mirroring the discipline of pause sites at lines 1138/1143/1169. These three
# tests seed `device_state.ev.last_change` directly — the first tests in the
# project to do so (Story 1.4 peer-review flagged this as an uncovered surface).


def test_solar_pause_blocked_by_hysteresis_lock(
    base_inputs, config, device_state, summer_noon
):
    """ev_on 100s ago + canonical PAUSE inputs → no pause (hysteresis lock).

    With `device_state.ev.on=True, last_change=now_ts - 100_000` (elapsed 100s
    < min_on_time*1000 = 300_000ms), `can_switch_device` returns False for
    the OFF transition. Control falls through to the ramp-clamp logic; with
    `ev_limit=6` and `target_amps=6` the ramp also no-ops (amp_diff=0), so
    `action` stays at its default `'none'`.

    Positive witness: action in ('none', 'adjust') AND plan lacks the pause
    entry. Negative: action != 'pause'.
    """
    now_ts = summer_noon.timestamp() * 1000
    device_state.ev.on = True
    device_state.ev.last_change = now_ts - 100_000

    inputs = _solar_inputs(
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

    assert result.decisions.ev.action != 'pause', (
        f"Expected pause to be hysteresis-blocked; got "
        f"{result.decisions.ev.action} (plan: {result.plan})"
    )
    assert not any('PAUSE (insufficient solar)' in e for e in result.plan), \
        f"Expected no 'PAUSE (insufficient solar)' plan entry; got: {result.plan}"
    assert result.decisions.ev.action in ('none', 'adjust'), (
        f"Expected legal fall-through outcome (none/adjust); got "
        f"{result.decisions.ev.action}"
    )
    # Pin the DN2 observability witness from the locked branch.
    assert any('pause held off by hysteresis' in e for e in result.plan), \
        f"Expected hysteresis-held witness in plan; got: {result.plan}"


def test_solar_pause_locked_with_higher_ev_limit_clamps_to_min(
    base_inputs, config, device_state, summer_noon
):
    """ev_on 100s ago + ev_limit=10 + collapsed solar → clamp to 6A directly.

    DN1 from Story 1.6 CR: when hysteresis blocks the pause AND
    `ev_limit > min_amps`, the locked branch emits
    `decisions.ev.action='adjust', amps=min_amps` directly (instead of falling
    through to the 1A/cycle ramp-down) so grid draw during the lock window is
    minimized: the EV drops to 6A in one cycle instead of staying at
    9A → 8A → 7A → 6A over ~2 min.

    Trace: with ev_limit=10, current_ev_watts = max(0, 10*692=6920) = 6920.
    With p1_power=3500, available_power = 1000-3500-0 = -2500;
    total_for_ev = -2500+6920-300 = 4120; available_amps = int(4120/692) = 5.
    5 < 6 → wrap's locked branch reached. ev_limit (10) > min_amps (6) → clamp.
    """
    now_ts = summer_noon.timestamp() * 1000
    device_state.ev.on = True
    device_state.ev.last_change = now_ts - 100_000

    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=0,
        ev_limit=10,
        pv_power=1600,
        p1_power=3500,
        p1_return=0,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert result.decisions.ev.action == 'adjust', (
        f"Expected adjust under lock with ev_limit>min_amps; got "
        f"{result.decisions.ev.action} (plan: {result.plan})"
    )
    assert result.decisions.ev.amps == config.ev.min_amps, (
        f"Expected clamp to min_amps ({config.ev.min_amps}A); got "
        f"{result.decisions.ev.amps}A"
    )
    # Witness from DN2 patch (same locked branch emits it regardless of ev_limit).
    assert any('pause held off by hysteresis' in e for e in result.plan), \
        f"Expected hysteresis-held witness in plan; got: {result.plan}"


def test_solar_pause_fires_after_hysteresis_clears(
    base_inputs, config, device_state, summer_noon
):
    """ev_on 400s ago + canonical PAUSE inputs → pause fires.

    With elapsed 400s ≥ min_on_time*1000 = 300_000ms, `can_switch_device`
    returns True and the pre-clamp pause emits normally.
    """
    now_ts = summer_noon.timestamp() * 1000
    device_state.ev.on = True
    device_state.ev.last_change = now_ts - 400_000

    inputs = _solar_inputs(
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

    assert result.decisions.ev.action == 'pause', (
        f"Expected pause after hysteresis clears; got "
        f"{result.decisions.ev.action} (plan: {result.plan})"
    )
    assert any('PAUSE (insufficient solar)' in e for e in result.plan), \
        f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}"


def test_solar_pause_at_hysteresis_boundary(
    base_inputs, config, device_state, summer_noon
):
    """elapsed == min_on_time*1000 exactly → pause fires (inclusive `>=`).

    `can_switch_device` at decision_engine.py:136 uses `elapsed >= (min_on_time
    * 1000)` — the boundary is inclusive. This test pins that semantics so a
    future refactor that accidentally writes `>` (exclusive) fails immediately.
    """
    now_ts = summer_noon.timestamp() * 1000
    device_state.ev.on = True
    device_state.ev.last_change = now_ts - 300_000

    inputs = _solar_inputs(
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

    assert result.decisions.ev.action == 'pause', (
        f"Expected pause at inclusive boundary (elapsed == min_on_time*1000); "
        f"got {result.decisions.ev.action} (plan: {result.plan})"
    )
    assert any('PAUSE (insufficient solar)' in e for e in result.plan), \
        f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}"


# ===========================================================================
# Story 1.7 — Cold-start hysteresis safety
# ===========================================================================
#
# When `device_state.ev.last_change == 0` (fresh AllDeviceStates after add-on
# restart) AND the sensor reports an in-progress charging session
# (`ctx['ev_charging'] == True`), _handle_ev seeds device_state.ev so the
# Story 1.6 hysteresis wrap is not silently bypassed by the
# `can_switch_device` line-129 short-circuit on the first decision cycle.


def test_cold_start_seeds_state_with_cleared_hysteresis(
    base_inputs, config, device_state, summer_noon
):
    """Cold-start + sensor-says-charging → seed state-tracking AND clear
    hysteresis so all in-cycle pauses fire immediately.

    Story 1.7 (post-CR-patch) seeding strategy:
    - Sets `device_state.ev.on=True` for state tracking (future off→on
      transitions correctly trigger min_off_time).
    - Sets `device_state.ev.last_change = now_ts - (min_on_time+1)*1000`
      so `can_switch_device` returns True immediately for any same-cycle
      pause check. Matches the boiler's "tariff transitions should be
      immediate" policy at decision_engine.py:781.

    With canonical PAUSE inputs (CHARGING + low PV), the Story 1.6 wrap
    fires `pause` on this very first cycle — no hysteresis lock, no
    delayed grid draw. From cycle 2 onward, main.py's update_state path
    correctly engages hysteresis for any real state changes.
    """
    expected_now_ts = summer_noon.timestamp() * 1000
    expected_seed_offset = (config.timing.min_on_time + 1) * 1000

    inputs = _solar_inputs(
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

    # State tracking: ev.on flipped to True, last_change seeded past min_on_time.
    assert device_state.ev.on is True, \
        f"Expected device_state.ev.on=True after seeding; got {device_state.ev.on}"
    assert device_state.ev.last_change == expected_now_ts - expected_seed_offset, (
        f"Expected device_state.ev.last_change to be seeded "
        f"{expected_seed_offset}ms in the past (={expected_now_ts - expected_seed_offset}); "
        f"got {device_state.ev.last_change}"
    )
    # Behavior: pause fires immediately (hysteresis is cleared, not locked).
    assert result.decisions.ev.action == 'pause', (
        f"Expected pause to fire immediately on cold-start; got "
        f"{result.decisions.ev.action} (plan: {result.plan})"
    )
    assert any('PAUSE (insufficient solar)' in e for e in result.plan), \
        f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}"
    # Negative witness: the Story 1.6 DN2 "pause held off" message must NOT
    # appear (the locked branch is not reached because hysteresis is cleared).
    assert not any('pause held off by hysteresis' in e for e in result.plan), \
        f"Expected no hysteresis-held witness on cold-start; got: {result.plan}"


def test_cold_start_peak_tariff_pause_fires_immediately(
    base_inputs, config, device_state, summer_noon
):
    """Cold-start at peak hours + EV charging → peak-tariff pause fires
    immediately (regression test for the seed-strategy fix from CR DN1).

    With the original Story 1.7 seed strategy (`last_change=now_ts`), this
    scenario would have BLOCKED the peak-tariff pause at line 1204 for 5
    minutes, causing sustained grid draw at peak rates. Post-CR-patch
    seeds in the past so the boiler's "tariff transitions immediate"
    policy applies to the EV's tariff pauses too.
    """
    # Peak hours: weekday 09:00 (peak per CLAUDE.md schedule).
    from datetime import datetime
    peak_morning = datetime(2024, 1, 15, 9, 0, 0)

    inputs = _solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=4000,
        ev_limit=6,
        pv_power=0,           # no solar to trigger the solar branch
        p1_power=2000,
        p1_return=0,
        battery_soe=10.0,     # below buffer threshold, blocks solar branch
        battery_power=0,
    )
    result = calculate_decisions(inputs, config, device_state, peak_morning)

    assert result.decisions.ev.action == 'pause', (
        f"Expected immediate peak-tariff pause on cold-start; got "
        f"{result.decisions.ev.action} (plan: {result.plan})"
    )
    assert any('PAUSE (peak tariff)' in e for e in result.plan), \
        f"Expected 'PAUSE (peak tariff)' in plan; got: {result.plan}"


def test_cold_start_not_charging_does_not_seed(
    base_inputs, config, device_state, summer_noon
):
    """Cold-start + sensor-says-not-charging → no seeding, no spurious behavior.

    Default device_state fixture, baseline `_solar_inputs(...)` with
    `ev_state=READY` (not charging). The `last_change == 0 AND ev_charging`
    guard fails → seeding skipped → device_state.ev stays untouched. No
    spurious 'pause held off by hysteresis' plan entry should appear.
    """
    inputs = _solar_inputs(base_inputs, ev_state=EVState.READY)
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert device_state.ev.last_change == 0, (
        f"Expected device_state.ev.last_change=0 (no seeding when not charging); "
        f"got {device_state.ev.last_change}"
    )
    assert device_state.ev.on is False, \
        f"Expected device_state.ev.on=False (unchanged); got {device_state.ev.on}"
    assert not any('pause held off by hysteresis' in e for e in result.plan), \
        f"Expected no hysteresis-held witness in plan; got: {result.plan}"
