"""Regression test for CODE_REVIEW_PASS2.md §2.1.

Summer logic must call _handle_boiler BEFORE _handle_ev so that the EV handler
receives the boiler's actual `boiler_will_use` instead of a hardcoded 0. With
the original ordering, the off-peak fast-path in _handle_ev fired even when
the boiler was about to consume the off-peak limit, briefly overshooting the
5 kW ceiling.
"""

from unittest.mock import patch

from app.decision_engine import _apply_summer_logic


def test_summer_runs_boiler_handler_before_ev_handler():
    """Boiler must commit its power decision before EV reads `boiler_will_use`."""
    call_order = []

    def fake_boiler(decisions, plan, ctx, headroom):
        call_order.append("boiler")
        # Pretend boiler decided to draw 2500W
        return 2500, headroom - 2500

    def fake_ev(decisions, plan, ctx, headroom, boiler_will_use):
        call_order.append("ev")
        # Pin the bug: if boiler ran first, boiler_will_use is 2500, not 0.
        assert boiler_will_use == 2500, (
            f"EV received stale boiler_will_use={boiler_will_use}; "
            "boiler must run before EV in summer (mirroring winter order)"
        )
        return headroom

    def fake_pool(decisions, plan, ctx, headroom):
        call_order.append("pool")
        return headroom

    def fake_dw(decisions, plan, ctx):
        call_order.append("dw")

    def fake_heaters(decisions, plan, ctx, headroom):
        call_order.append("heaters")

    ctx = {
        "ovr": {"table_heater": "auto"},
        "headroom": 5000,
        "hyst": None,
        "config": None,
        "can_switch": lambda *_args, **_kw: True,
        "is_exporting": False,
        "pv": 0,
    }

    with patch("app.decision_engine._handle_boiler", side_effect=fake_boiler), \
         patch("app.decision_engine._handle_ev", side_effect=fake_ev), \
         patch("app.decision_engine._handle_pool_heating", side_effect=fake_pool), \
         patch("app.decision_engine._apply_dishwasher_logic", side_effect=fake_dw), \
         patch("app.decision_engine._handle_heaters", side_effect=fake_heaters):
        _apply_summer_logic(decisions=None, plan=[], ctx=ctx)

    # Boiler must be called before EV
    boiler_idx = call_order.index("boiler")
    ev_idx = call_order.index("ev")
    assert boiler_idx < ev_idx, (
        f"Wrong call order: {call_order}. "
        "Boiler must run before EV so off-peak headroom respects boiler load."
    )
