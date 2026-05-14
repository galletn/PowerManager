"""Integration regression for CR-P2 (review of v1.0.61, decision DN1=A).

The v1.0.52 EV "soft-pause" sets amps to 5A, which lands the ABB charger at
state 133 (PAUSED). Across a single charging session the charger oscillates
between 132 (actively charging) and 133 (soft-paused) every few cycles.

The Work A fix replaced the literal `inputs.ev_state == 132` predicate with
`EVState.is_charging(...)` — but `is_charging` also excludes 133, so the
oscillation 132 <-> 133 still flips `state.on` every cycle and bumps
`last_change`, defeating hysteresis.

The DN1=A fix: use `EVState.is_active_session(...)` for the EV update_state
call. is_active_session covers IEC connected + ready + charging + ABB ready
+ charging + paused — so both 132 and 133 register as "engaged" and the
oscillation no longer bumps last_change.
"""

import time

import pytest

from app.main import _update_device_state, app_state
from app.models import AllDeviceStates, EVState, PowerInputs


@pytest.fixture(autouse=True)
def fresh_device_state():
    """Swap app_state.device_state with a fresh instance per test, restore after."""
    saved = app_state.device_state
    app_state.device_state = AllDeviceStates()
    try:
        yield app_state.device_state
    finally:
        app_state.device_state = saved


def _ev_inputs(ev_state: int) -> PowerInputs:
    """Minimal PowerInputs with a given EV state code."""
    return PowerInputs(ev_state=ev_state)


def test_soft_pause_oscillation_does_not_bump_last_change(fresh_device_state):
    """Cycle 1: charger at 132 (charging). Cycle 2: charger at 133 (soft-paused).
    Cycle 3: back to 132. last_change must NOT change across these flips."""
    # Cycle 1 — start a charging session
    _update_device_state(_ev_inputs(EVState.CHARGING), {})
    assert fresh_device_state.ev.on is True
    first_change = fresh_device_state.ev.last_change
    assert first_change > 0, "first transition should set last_change"

    # Brief wait so any spurious second bump shows a distinct timestamp
    time.sleep(0.001)

    # Cycle 2 — soft-pause kicks in (amps=5 -> ABB reports 133)
    _update_device_state(_ev_inputs(EVState.PAUSED), {})
    second_change = fresh_device_state.ev.last_change

    time.sleep(0.001)

    # Cycle 3 — charger flips back to 132
    _update_device_state(_ev_inputs(EVState.CHARGING), {})
    third_change = fresh_device_state.ev.last_change

    assert second_change == first_change, (
        "soft-pause (132 -> 133) must not bump last_change; "
        f"first={first_change}, second={second_change}"
    )
    assert third_change == first_change, (
        "return-to-charging (133 -> 132) must not bump last_change; "
        f"first={first_change}, third={third_change}"
    )


def test_state_on_stays_true_across_soft_pause(fresh_device_state):
    """state.on must NOT flip during the 132 <-> 133 oscillation."""
    _update_device_state(_ev_inputs(EVState.CHARGING), {})
    _update_device_state(_ev_inputs(EVState.PAUSED), {})
    assert fresh_device_state.ev.on is True, (
        "state.on must remain True during soft-pause; otherwise hysteresis "
        "min_on/min_off windows fire spuriously"
    )


def test_unplug_does_flip_state(fresh_device_state):
    """Real unplug (any plugged state -> NO_CAR) must still flip on -> off."""
    _update_device_state(_ev_inputs(EVState.CHARGING), {})
    pre_change = fresh_device_state.ev.last_change
    time.sleep(0.001)
    _update_device_state(_ev_inputs(EVState.NO_CAR), {})
    assert fresh_device_state.ev.on is False
    assert fresh_device_state.ev.last_change > pre_change


def test_full_does_flip_state_off(fresh_device_state):
    """FULL (130) is NOT an active session — flip to False so hysteresis sees
    the natural end-of-charge transition."""
    _update_device_state(_ev_inputs(EVState.CHARGING), {})
    _update_device_state(_ev_inputs(EVState.FULL), {})
    assert fresh_device_state.ev.on is False


def _heater_right_inputs(switch: str) -> PowerInputs:
    """PowerInputs with heater_right_switch set; defaults elsewhere."""
    return PowerInputs(heater_right_switch=switch)


def test_heater_right_tracking_off_to_on(fresh_device_state):
    """CR-P9: heater_right.last_change must bump when the right heater
    transitions off->on. Pre-Work-A, `_update_device_state` skipped
    heater_right entirely so hysteresis was permanently disabled
    (last_change=0 → can_switch_device returns True every time)."""
    assert fresh_device_state.heater_right.on is False
    assert fresh_device_state.heater_right.last_change == 0.0

    _update_device_state(_heater_right_inputs('on'), {})

    assert fresh_device_state.heater_right.on is True
    assert fresh_device_state.heater_right.last_change > 0.0


def test_heater_right_tracking_on_to_off(fresh_device_state):
    """heater_right must transition on->off as well, with a fresh
    last_change so the min_off_time window starts ticking."""
    _update_device_state(_heater_right_inputs('on'), {})
    first_change = fresh_device_state.heater_right.last_change
    time.sleep(0.001)

    _update_device_state(_heater_right_inputs('off'), {})

    assert fresh_device_state.heater_right.on is False
    assert fresh_device_state.heater_right.last_change > first_change


def test_heater_right_no_bump_when_state_unchanged(fresh_device_state):
    """Repeated 'on' inputs must NOT bump last_change — only transitions do."""
    _update_device_state(_heater_right_inputs('on'), {})
    first_change = fresh_device_state.heater_right.last_change
    time.sleep(0.001)

    _update_device_state(_heater_right_inputs('on'), {})

    assert fresh_device_state.heater_right.last_change == first_change
