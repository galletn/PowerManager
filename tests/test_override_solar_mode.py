"""Regression tests for CODE_REVIEW_PASS2.md sec.2.2.

`/api/override` previously accepted `mode=solar` for every device but only EV
has a `Solar` input_select option in HA. For boiler/pool/table_heater/
dishwasher the request silently called input_select.select_option with a
non-existent option, returning HA 4xx and confusing the dashboard.

Fix: build `valid_modes` per-device from mode_map.keys() so unknown
(device, mode) pairs surface as a 400 with a useful error.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient that surfaces server-side errors as response codes rather
    than re-raising — so a 400 (validation) vs 500 (downstream HA error) is
    distinguishable from the test assertions."""
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestSolarModeOnlyValidForEV:
    """Only EV has a Solar option in HA's input_select."""

    @pytest.mark.parametrize(
        "device",
        ["boiler", "pool", "table_heater", "dishwasher"],
    )
    def test_solar_rejected_for_non_ev_with_400(self, client, device):
        response = client.post(f"/api/override/{device}?mode=solar")
        assert response.status_code == 400
        # Message should mention valid modes for this device.
        body = response.text.lower()
        assert "invalid mode" in body or "mode" in body
        # Solar shouldn't appear in the per-device allowed list returned.
        detail = response.json().get("detail", "").lower()
        # The detail should list auto/on/off (device's actual options), NOT solar.
        assert "solar" not in detail or "ev" in detail


class TestValidModesForEachDevice:
    """Each device exposes a tight per-device mode allowlist."""

    @pytest.mark.parametrize(
        "device,mode",
        [
            ("ev", "solar"),       # EV: solar valid
            ("ev", "auto"),
            ("ev", "on"),
            ("ev", "off"),
            ("boiler", "auto"),
            ("boiler", "on"),
            ("boiler", "off"),
            ("pool", "auto"),
            ("table_heater", "on"),
            ("dishwasher", "auto"),
        ],
    )
    def test_known_pair_does_not_400_on_validation(self, client, device, mode):
        """These pairs must pass the validation gate (may still 500 later if
        app_state.config is None in tests, but it must NOT be a 400)."""
        response = client.post(f"/api/override/{device}?mode={mode}")
        assert response.status_code != 400, (
            f"({device}, {mode}) should be a valid combination"
        )


class TestUnknownModeRejected:
    """Truly unknown modes still produce 400."""

    def test_unknown_mode(self, client):
        response = client.post("/api/override/boiler?mode=bogus")
        assert response.status_code == 400

    def test_empty_mode(self, client):
        response = client.post("/api/override/boiler?mode=")
        assert response.status_code == 400
