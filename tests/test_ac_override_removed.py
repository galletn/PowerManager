"""Regression tests for CODE_REVIEW_PASS2.md N2.

AC overrides used to be accepted by /api/override and parsed by the decision
engine, but no AC branch ever existed in `execute_decisions`. The dashboard
silently lied to the user. Per the agreed remediation: remove the surface
until the AC executor ships.

These tests pin:
- /api/override rejects every ac_* device with HTTP 400
- the engine's `ovr` dict no longer contains ac_* keys (so dead code that
  reads them is forced to surface during refactor)
"""

import pytest
from fastapi.testclient import TestClient

from app.decision_engine import calculate_decisions
from app.models import PowerInputs, AllDeviceStates


class TestAPIRejectsACOverrides:
    """The four ac_* devices must each get a 400, with a useful message."""

    @pytest.fixture
    def client(self):
        # Lazy import: main.py side-effect-loads config from disk on import,
        # so build the test client only when needed.
        from app.main import app
        return TestClient(app)

    @pytest.mark.parametrize(
        "device",
        ["ac_living", "ac_bedroom", "ac_office", "ac_mancave"],
    )
    def test_ac_device_rejected_with_400(self, client, device):
        response = client.post(f"/api/override/{device}?mode=on")
        assert response.status_code == 400
        # Surface the new device list to the caller in the error body.
        body = response.text.lower()
        assert "invalid device" in body
        # The removed device must NOT appear in the allowlist any more.
        assert device not in response.json().get("detail", "").lower()


class TestEngineNoLongerParsesACOverrides:
    """`ovr` dict in calculate_decisions should not carry ac_* entries.

    Anything in the engine that still reads `ovr['ac_*']` will KeyError —
    which is the intended behaviour so the dead path surfaces at test time
    rather than hiding behind `.get('ac_living', 'auto')` truthiness.
    """

    def test_ovr_has_no_ac_keys(self, base_inputs, config, device_state):
        # Reach inside via the same call path the engine uses, then sniff the
        # constructed ovr by intercepting `_apply_winter_logic`. Cheaper than
        # bringing the whole engine up.
        from unittest.mock import patch

        captured = {}

        def fake_winter(decisions, plan, ctx):
            captured["ovr"] = ctx["ovr"]

        def fake_summer(decisions, plan, ctx):
            captured["ovr"] = ctx["ovr"]

        from datetime import datetime
        with patch(
            "app.decision_engine._apply_winter_logic", side_effect=fake_winter
        ), patch(
            "app.decision_engine._apply_summer_logic", side_effect=fake_summer
        ):
            calculate_decisions(
                inputs=base_inputs,
                config=config,
                device_state=device_state,
                now=datetime(2024, 1, 15, 23, 0, 0),
            )

        assert "ovr" in captured, "engine did not invoke winter/summer logic"
        ovr = captured["ovr"]
        for ac_key in ("ac_living", "ac_bedroom", "ac_office", "ac_mancave"):
            assert ac_key not in ovr, (
                f"engine still parses {ac_key!r} — the AC surface was "
                "supposed to be removed until the executor ships"
            )
