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
        """CR-P7: assert the detail body names the device and excludes 'solar'
        from the allowlist — pinning the contract instead of using a permissive
        `solar not in detail OR ev in detail` boolean."""
        response = client.post(f"/api/override/{device}", json={"mode": "solar"})
        assert response.status_code == 400
        detail = response.json().get("detail", "")
        assert f"Invalid mode for '{device}'" in detail, (
            f"detail should name the rejected device; got: {detail!r}"
        )
        # The per-device allowlist must NOT contain 'solar' for non-EV devices.
        assert "'solar'" not in detail, (
            f"solar appears in non-EV allowlist: {detail!r}"
        )
        # Should list auto/on/off for switch-style devices
        assert "'auto'" in detail and "'on'" in detail and "'off'" in detail


class TestValidModesForEachDevice:
    """Each device exposes a tight per-device mode allowlist.

    These pairs must pass the validation gate. CR-P8: previous version
    asserted `status_code != 400`, which trivially passed on 500/422/anything-
    not-400. Tighten: status must be in {200, 500} where 500 indicates the
    test environment lacks a configured HA client (validation passed). 400
    means the validation gate wrongly rejected a known-valid pair."""

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
    def test_known_pair_passes_validation(self, client, device, mode):
        response = client.post(f"/api/override/{device}", json={"mode": mode})
        # 200 if HA was wired up; 500 if downstream HA call failed (test env).
        # Either way, the validation gate accepted (device, mode).
        assert response.status_code in (200, 500), (
            f"({device}, {mode}) returned {response.status_code}; expected "
            "200 (accepted + HA call ok) or 500 (accepted + HA call failed)"
        )
        # Critical: must NOT be 400 (validation rejection).
        assert response.status_code != 400


class TestUnknownModeRejected:
    """Truly unknown modes still produce 400."""

    def test_unknown_mode(self, client):
        response = client.post("/api/override/boiler", json={"mode": "bogus"})
        assert response.status_code == 400

    def test_empty_body(self, client):
        """Empty body now returns 422 (Pydantic 'mode' required), was 400."""
        response = client.post("/api/override/boiler", json={})
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(
            e.get("loc") and e["loc"][-1] == "mode" for e in errors
        ), f"Expected 'mode' in error loc; got: {errors}"
