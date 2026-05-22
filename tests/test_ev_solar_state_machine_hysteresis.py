"""Tests for the hysteresis-mechanism layer around `_handle_ev` solar.

Covers Stories 1.5 (boundary tests for pre-clamp pause and None-safe status
line), 1.6 (hysteresis-gated pre-clamp pause), 1.7 (cold-start hysteresis
safety), and 1.10 (cold-start ON/start direction). Companion file to
test_ev_solar_state_machine_acs.py, which pins Story 1.4 ACs #1-9.
"""

import logging
from datetime import datetime

from app.decision_engine import calculate_decisions
from app.models import EVState
from tests._plan_helpers import assert_plan_contains, assert_plan_no_match
from tests.conftest import solar_inputs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_debug_messages_starting(caplog, prefix):
    """DEBUG-level messages from app.decision_engine starting with `prefix`."""
    return [
        r.message for r in caplog.records
        if r.name == 'app.decision_engine'
        and r.levelno == logging.DEBUG
        and r.message.startswith(prefix)
    ]


# ===========================================================================
# Story 1.5 — Boundary tests for pre-clamp pause and None-safe status line
# ===========================================================================


def test_solar_pause_with_higher_ev_limit(
    base_inputs, config, device_state, summer_noon, ev_state_just_cleared_on
):
    """Already charging at ev_limit=10 with collapsed PV → available_amps < 6
    fires the pre-clamp pause. Complements test_solar_pause_when_target_below_min_amps
    (ev_limit=6) by proving the pause path is independent of the current limit.

    Trace: available_power = 1000 - 3500 - 0 = -2500;
    current_ev_watts = max(4000, 10*692=6920) = 6920;
    total_for_ev = -2500 + 6920 - 300 = 4120; available_amps = int(4120/692) = 5.
    5 < 6 (min_amps) → pause.
    """
    inputs = solar_inputs(
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
    assert_plan_contains(result.plan, 'PAUSE (insufficient solar)', msg=f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}")


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
    inputs = solar_inputs(
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
    assert_plan_contains(result.plan, 'adjust to 6A', msg=f"Expected 'adjust to 6A' plan witness; got: {result.plan}")


def test_battery_power_and_soe_both_none_does_not_crash(
    base_inputs, config, device_state, summer_noon
):
    """battery_power=None AND battery_soe=None must not crash. Status-line
    block skipped (bat_soe guard); solar START blocked (no buffer + no
    charging signal); tariff branch at summer noon off-peak with ev_ready waits
    for super-off-peak → action stays 'none'.
    """
    inputs = solar_inputs(
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
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_power=None,
        battery_soe=50.0,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert_plan_contains(result.plan, 'Bat: power unknown (50%)', msg=f"Expected 'Bat: power unknown (50%)' in plan; got: {result.plan}")
    for label in ('Bat: Charging', 'Bat: Discharging', 'Bat: Idle'):
        assert_plan_no_match(result.plan, label,
            msg="No other 'Bat: ' label allowed alongside 'power unknown'")


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
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_power=None,
        battery_soe=50.0,
        pv_power=3000,
        p1_power=-500,
        p1_return=500,
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert_plan_contains(result.plan, 'Bat: power unknown (50%)', msg=f"Expected 'Bat: power unknown (50%)' in plan; got: {result.plan}")
    assert_plan_no_match(result.plan, 'reclaimable', msg=f"Expected no '[+X reclaimable]' suffix when bat_power=None; got: {result.plan}")


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
    inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.READY,
        battery_power=0.0,
        battery_soe=50.0,
        battery_status='unavailable',
    )
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    assert_plan_contains(result.plan, 'Bat: power unknown (50%)'), (
        f"Expected 'Bat: power unknown (50%)' in plan when battery_power=0 "
        f"AND battery_status='unavailable'; got: {result.plan}"
    )
    assert_plan_no_match(result.plan, 'Bat: Idle', msg=f"Expected no 'Bat: Idle' alongside 'power unknown'; got: {result.plan}")


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
    base_inputs, config, device_state, summer_noon, ev_state_locked_on
):
    """ev_on inside the min_on_time lock (`ev_state_locked_on` fixture) +
    canonical PAUSE inputs → no pause (hysteresis lock blocks the transition).

    With `device_state.ev.on=True, last_change=now_ts - 100_000` (elapsed 100s
    < min_on_time*1000 = 300_000ms), `can_switch_device` returns False for
    the OFF transition. Control falls through to the ramp-clamp logic; with
    `ev_limit=6` and `target_amps=6` the ramp also no-ops (amp_diff=0), so
    `action` stays at its default `'none'`.

    Positive witness: action in ('none', 'adjust') AND plan lacks the pause
    entry. Negative: action != 'pause'.
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

    assert result.decisions.ev.action != 'pause', (
        f"Expected pause to be hysteresis-blocked; got "
        f"{result.decisions.ev.action} (plan: {result.plan})"
    )
    assert_plan_no_match(result.plan, 'PAUSE (insufficient solar)', msg=f"Expected no 'PAUSE (insufficient solar)' plan entry; got: {result.plan}")
    assert result.decisions.ev.action in ('none', 'adjust'), (
        f"Expected legal fall-through outcome (none/adjust); got "
        f"{result.decisions.ev.action}"
    )
    # Pin the DN2 observability witness from the locked branch.
    assert_plan_contains(result.plan, 'pause held off by hysteresis', msg=f"Expected hysteresis-held witness in plan; got: {result.plan}")


def test_solar_pause_locked_with_higher_ev_limit_clamps_to_min(
    base_inputs, config, device_state, summer_noon, ev_state_locked_on
):
    """ev_on inside the min_on_time lock (`ev_state_locked_on` fixture) +
    ev_limit=10 + collapsed solar → clamp to 6A directly.

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
    inputs = solar_inputs(
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
    assert_plan_contains(result.plan, 'pause held off by hysteresis', msg=f"Expected hysteresis-held witness in plan; got: {result.plan}")


def test_solar_pause_fires_after_hysteresis_clears(
    base_inputs, config, device_state, summer_noon, ev_state_just_cleared_on
):
    """ev_on just past the min_on_time lock (`ev_state_just_cleared_on`
    fixture) + canonical PAUSE inputs → pause fires.

    With elapsed past `min_on_time`, `can_switch_device` returns True and
    the pre-clamp pause emits normally.
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

    assert result.decisions.ev.action == 'pause', (
        f"Expected pause after hysteresis clears; got "
        f"{result.decisions.ev.action} (plan: {result.plan})"
    )
    assert_plan_contains(result.plan, 'PAUSE (insufficient solar)', msg=f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}")


def test_solar_pause_at_hysteresis_boundary(
    base_inputs, config, device_state, summer_noon
):
    """elapsed == min_on_time*1000 exactly → pause fires (inclusive `>=`).

    `can_switch_device` at decision_engine.py:136 uses `elapsed >= (min_on_time
    * 1000)` — the boundary is inclusive. This test pins that semantics so a
    future refactor that accidentally writes `>` (exclusive) fails immediately.
    """
    # Boundary case: elapsed == min_on_time*1000 exactly. Kept inline so
    # the boundary is explicit; offset derived from config, not a magic ms.
    now_ts = summer_noon.timestamp() * 1000
    device_state.ev.on = True
    device_state.ev.last_change = now_ts - config.timing.min_on_time * 1000

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

    assert result.decisions.ev.action == 'pause', (
        f"Expected pause at inclusive boundary (elapsed == min_on_time*1000); "
        f"got {result.decisions.ev.action} (plan: {result.plan})"
    )
    assert_plan_contains(result.plan, 'PAUSE (insufficient solar)', msg=f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}")


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
    assert_plan_contains(result.plan, 'PAUSE (insufficient solar)', msg=f"Expected 'PAUSE (insufficient solar)' in plan; got: {result.plan}")
    # Negative witness: the Story 1.6 DN2 "pause held off" message must NOT
    # appear (the locked branch is not reached because hysteresis is cleared).
    assert_plan_no_match(result.plan, 'pause held off by hysteresis', msg=f"Expected no hysteresis-held witness on cold-start; got: {result.plan}")


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

    inputs = solar_inputs(
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
    assert_plan_contains(result.plan, 'PAUSE (peak tariff)', msg=f"Expected 'PAUSE (peak tariff)' in plan; got: {result.plan}")


def test_cold_start_plugged_not_charging_seeds_with_cleared_off_hysteresis(
    base_inputs, config, device_state, summer_noon
):
    """Cold-start + sensor-says-plugged-not-charging → Story 1.10 seed fires
    (on=False, last_change = now - (min_off_time+1)*1000).

    Supersedes Story 1.7 AC #2 ("no seeding for not-charging"). The
    `last_change == 0` outer guard now applies to BOTH branches; the
    `ctx['ev_charging']` predicate selects between Story 1.7 (on=True,
    cleared ON hysteresis) and Story 1.10 (on=False, cleared OFF
    hysteresis). The line-129 short-circuit in can_switch_device is no
    longer reachable from _handle_ev for tracked sessions (plugged +
    not-done) — the seed establishes the `last_change > 0` invariant.

    Pinned here: the SEED contract (state.on, last_change). The end-to-end
    behavior (START fires, witness present) is pinned by
    test_cold_start_plugged_solar_start_fires_immediately.
    """
    expected_now_ts = summer_noon.timestamp() * 1000
    expected_seed_offset = (config.timing.min_off_time + 1) * 1000

    inputs = solar_inputs(base_inputs, ev_state=EVState.READY)
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    # Story 1.10: seed fires for plugged-not-charging cold-start.
    assert device_state.ev.last_change == expected_now_ts - expected_seed_offset, (
        f"Expected device_state.ev.last_change to be seeded "
        f"{expected_seed_offset}ms in the past "
        f"(={expected_now_ts - expected_seed_offset}); "
        f"got {device_state.ev.last_change}"
    )
    assert device_state.ev.on is False, (
        f"Expected device_state.ev.on=False after Story 1.10 seed; "
        f"got {device_state.ev.on}"
    )
    assert_plan_no_match(result.plan, 'pause held off by hysteresis', msg=f"Expected no hysteresis-held witness when not charging; got: {result.plan}")


def test_cold_start_plugged_solar_start_fires_immediately(
    base_inputs, config, device_state, summer_noon
):
    """Cold-start + sensor-says-READY + good solar → START fires immediately
    via the Story 1.10 cleared-OFF-hysteresis seed (NOT the line-129
    short-circuit).

    Pins the symmetric counterpart to
    test_cold_start_seeds_state_with_cleared_hysteresis (Story 1.7):
    - That test pinned cold-start + CHARGING → pause fires immediately
      via cleared-ON hysteresis.
    - This test pins cold-start + READY → START fires immediately via
      cleared-OFF hysteresis.

    Closes the open peer-review item carried across Stories 1.4, 1.6,
    AND 1.7 deferred-work: "ON/start direction cold-start bypass via
    last_change==0 short-circuit".
    """
    expected_now_ts = summer_noon.timestamp() * 1000
    expected_seed_offset = (config.timing.min_off_time + 1) * 1000

    inputs = solar_inputs(base_inputs)  # default: ev_state=READY, good solar
    result = calculate_decisions(inputs, config, device_state, summer_noon)

    # State tracking: ev.on stays False, last_change seeded past min_off_time.
    assert device_state.ev.on is False, \
        f"Expected device_state.ev.on=False (still off) after seeding; got {device_state.ev.on}"
    assert device_state.ev.last_change == expected_now_ts - expected_seed_offset, (
        f"Expected device_state.ev.last_change to be seeded "
        f"{expected_seed_offset}ms in the past "
        f"(={expected_now_ts - expected_seed_offset}); "
        f"got {device_state.ev.last_change}"
    )

    # Behavior: START fires immediately (cleared OFF hysteresis).
    assert result.decisions.ev.action == 'on', (
        f"Expected START to fire immediately on cold-start with good solar; "
        f"got {result.decisions.ev.action} (plan: {result.plan})"
    )
    assert result.decisions.ev.amps == config.ev.min_amps, (
        f"Expected START at min_amps ({config.ev.min_amps}A); "
        f"got {result.decisions.ev.amps}"
    )
    assert_plan_contains(result.plan, 'SOLAR START', msg=f"Expected 'SOLAR START' in plan; got: {result.plan}")

    # Negative witness: pause branch not entered.
    assert_plan_no_match(result.plan, 'pause held off by hysteresis', msg=f"Expected no hysteresis-held witness on START path; got: {result.plan}")


def test_cold_start_seed_skipped_when_now_local_is_zero(
    base_inputs, config, device_state, summer_noon
):
    """AC #4 defensive guard: when `ctx['now'] == 0` (e.g., a future refactor
    drops the `now_ts` injection from calculate_decisions's ctx builder),
    the seed MUST be skipped for BOTH the Story 1.7 (charging) and Story
    1.10 (not-charging) branches. Without this guard, a missing `now`
    silently re-enables the can_switch_device line-129 short-circuit and
    Stories 1.7 + 1.10 are no longer load-bearing.

    Injects `now == 0` by passing a datetime subclass whose `.timestamp()`
    returns 0.0 — exercises the guard directly without depending on local
    timezone offsets.
    """
    class _ZeroTimestampDatetime(datetime):
        def timestamp(self):
            return 0.0

    zero_now = _ZeroTimestampDatetime(
        summer_noon.year, summer_noon.month, summer_noon.day,
        summer_noon.hour, summer_noon.minute, summer_noon.second,
    )

    # Branch A: ev_charging=True (Story 1.7) — seed MUST skip.
    charging_inputs = solar_inputs(
        base_inputs,
        ev_state=EVState.CHARGING,
        ev_switch='on',
        ev_power=4000,
    )
    calculate_decisions(charging_inputs, config, device_state, zero_now)
    assert device_state.ev.last_change == 0, (
        f"Story 1.7 (charging) branch must NOT seed when now_local == 0; "
        f"got last_change={device_state.ev.last_change}"
    )
    assert device_state.ev.on is False, (
        f"Story 1.7 (charging) branch must NOT flip ev.on when now_local == 0; "
        f"got ev.on={device_state.ev.on}"
    )

    # Branch B: ev_charging=False (Story 1.10) — seed MUST skip.
    not_charging_inputs = solar_inputs(base_inputs, ev_state=EVState.READY)
    calculate_decisions(not_charging_inputs, config, device_state, zero_now)
    assert device_state.ev.last_change == 0, (
        f"Story 1.10 (not-charging) branch must NOT seed when now_local == 0; "
        f"got last_change={device_state.ev.last_change}"
    )
    assert device_state.ev.on is False, (
        f"Story 1.10 (not-charging) branch must NOT flip ev.on when now_local == 0; "
        f"got ev.on={device_state.ev.on}"
    )
