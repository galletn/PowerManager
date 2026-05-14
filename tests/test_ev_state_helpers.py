"""Tests for EVState predicate helpers.

These helpers encode the *meaning* of each EV state code so that the rest of
the codebase doesn't need to repeat set-literals. ABB firmware reports either
IEC 61851-1 standard codes (0-5) or ABB custom codes (128+) — both formats are
covered.
"""

import pytest

from app.models import EVState


# All state codes the enum knows about, by name (for table-driven testing).
ALL_STATES = [
    EVState.IEC_IDLE,
    EVState.IEC_CONNECTED_B1,
    EVState.IEC_CONNECTED_B2,
    EVState.IEC_READY_C1,
    EVState.IEC_CHARGING_C2,
    EVState.IEC_OTHER,
    EVState.NO_CAR,
    EVState.READY,
    EVState.FULL,
    EVState.CHARGING,
    EVState.PAUSED,
]


class TestIsCharging:
    """is_charging is True iff the charger is actively delivering current."""

    @pytest.mark.parametrize("state", [EVState.IEC_CHARGING_C2, EVState.CHARGING])
    def test_charging_states_are_charging(self, state):
        assert EVState.is_charging(state) is True

    @pytest.mark.parametrize(
        "state",
        [s for s in ALL_STATES if s not in (EVState.IEC_CHARGING_C2, EVState.CHARGING)],
    )
    def test_other_states_are_not_charging(self, state):
        assert EVState.is_charging(state) is False

    def test_accepts_raw_int(self):
        """Callers (e.g. main.py update_state) often hold the raw int from HA."""
        assert EVState.is_charging(132) is True
        assert EVState.is_charging(4) is True
        assert EVState.is_charging(133) is False  # the v1.0.52 soft-pause state
        assert EVState.is_charging(128) is False


class TestIsPlugged:
    """is_plugged is True if a car is physically connected to the charger.

    Includes FULL — a fully charged car is still plugged in. Excludes IDLE,
    OTHER, and NO_CAR which all mean "no car / unusable state".
    """

    @pytest.mark.parametrize(
        "state",
        [
            EVState.IEC_CONNECTED_B1,
            EVState.IEC_CONNECTED_B2,
            EVState.IEC_READY_C1,
            EVState.IEC_CHARGING_C2,
            EVState.READY,
            EVState.CHARGING,
            EVState.FULL,
            EVState.PAUSED,
        ],
    )
    def test_plugged_states(self, state):
        assert EVState.is_plugged(state) is True

    @pytest.mark.parametrize(
        "state",
        [EVState.IEC_IDLE, EVState.IEC_OTHER, EVState.NO_CAR],
    )
    def test_unplugged_states(self, state):
        assert EVState.is_plugged(state) is False


class TestIsActiveSession:
    """is_active_session is is_plugged minus FULL.

    Used by the scheduler and BMW low-battery alert to mean "the car needs
    charging time / could be alerted about" — FULL cars don't qualify.
    """

    @pytest.mark.parametrize(
        "state",
        [
            EVState.IEC_CONNECTED_B1,
            EVState.IEC_CONNECTED_B2,
            EVState.IEC_READY_C1,
            EVState.IEC_CHARGING_C2,
            EVState.READY,
            EVState.CHARGING,
            EVState.PAUSED,
        ],
    )
    def test_active_session_states(self, state):
        assert EVState.is_active_session(state) is True

    @pytest.mark.parametrize(
        "state",
        [EVState.IEC_IDLE, EVState.IEC_OTHER, EVState.NO_CAR, EVState.FULL],
    )
    def test_non_active_session_states(self, state):
        assert EVState.is_active_session(state) is False


class TestIsDone:
    @pytest.mark.parametrize("state", [EVState.FULL])
    def test_full_is_done(self, state):
        assert EVState.is_done(state) is True

    @pytest.mark.parametrize(
        "state",
        [s for s in ALL_STATES if s != EVState.FULL],
    )
    def test_other_is_not_done(self, state):
        assert EVState.is_done(state) is False


class TestRegression_v1_0_52_SoftPause:
    """The v1.0.52 soft-pause (set amps=5) makes the ABB charger sit at state
    133 (PAUSED) for the duration of the pause. Before the helper migration,
    main.py:661 used `inputs.ev_state == 132` for hysteresis tracking — which
    meant the charger oscillating 132 <-> 133 between cycles bumped
    `state.last_change` every cycle and locked hysteresis open. This test pins
    that PAUSED is NOT considered "charging" but IS considered "plugged" so
    the new predicate is stable across the soft-pause."""

    def test_paused_is_not_charging(self):
        assert EVState.is_charging(EVState.PAUSED) is False

    def test_paused_is_plugged(self):
        assert EVState.is_plugged(EVState.PAUSED) is True

    def test_paused_is_active_session(self):
        assert EVState.is_active_session(EVState.PAUSED) is True
