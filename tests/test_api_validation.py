"""Tests for Story 1.3 — Pydantic validation on /api/limits and /api/override.

Closes PASS2 §5 row 14 (PASS1 §7.1 / §7.2): both write-side endpoints now
take a Pydantic JSON body. Bounds for power limits are [500, 12000] watts;
unknown JSON keys raise 422 via `extra="forbid"`.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient that surfaces server-side errors as response codes rather
    than re-raising. Same idiom as `tests/test_override_solar_mode.py`."""
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _loc_tail_set(errors):
    """Return the set of last-segment loc names from a Pydantic 422 body."""
    return {e["loc"][-1] for e in errors if "loc" in e and e["loc"]}


def _types_for_field(errors, field):
    """Return the error types for a given field (last loc segment)."""
    return {
        e["type"] for e in errors
        if e.get("loc") and e["loc"][-1] == field
    }


# ---------------------------------------------------------------------------
# /api/limits — bounds (AC #1, #6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["peak", "off_peak", "super_off_peak"])
def test_limits_field_below_min_returns_422(client, field):
    """Anything < 500 is rejected per-field with the offender named in loc."""
    response = client.post("/api/limits", json={field: 100})
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert field in _loc_tail_set(errors), (
        f"Expected '{field}' in error loc; got: {errors}"
    )
    assert any("greater_than" in t for t in _types_for_field(errors, field)), (
        f"Expected a greater-than-or-equal error for '{field}'; got: {errors}"
    )


@pytest.mark.parametrize("field", ["peak", "off_peak", "super_off_peak"])
def test_limits_field_above_max_returns_422(client, field):
    """Anything > 12000 is rejected per-field with the offender named in loc."""
    response = client.post("/api/limits", json={field: 99999999})
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert field in _loc_tail_set(errors), (
        f"Expected '{field}' in error loc; got: {errors}"
    )
    assert any("less_than" in t for t in _types_for_field(errors, field)), (
        f"Expected a less-than-or-equal error for '{field}'; got: {errors}"
    )


def test_limits_boundary_500_accepted(client):
    """The lower bound is inclusive — 500 must validate.

    Test env: `app_state.config is None`, so `set_limits` returns
    503 + `{"error": "Not initialized"}`. We pin both: (a) Pydantic
    accepted the body (else we'd see 422), and (b) we hit the known
    not-initialized path (else we'd see a different 500 — a real
    regression indicator).
    """
    response = client.post("/api/limits", json={"peak": 500})
    assert response.status_code == 503, (
        f"Expected 503 (validation passed → hit Not-initialized path); "
        f"got {response.status_code}: {response.text}"
    )
    assert "Not initialized" in response.text, (
        f"Expected 503 body to say 'Not initialized'; got: {response.text}"
    )


def test_limits_boundary_12000_accepted(client):
    """The upper bound is inclusive — 12000 must validate."""
    response = client.post("/api/limits", json={"peak": 12000})
    assert response.status_code == 503, (
        f"Expected 503 (validation passed → hit Not-initialized path); "
        f"got {response.status_code}: {response.text}"
    )
    assert "Not initialized" in response.text, (
        f"Expected 503 body to say 'Not initialized'; got: {response.text}"
    )


def test_limits_empty_body_accepted(client):
    """Empty body is a no-op update; all fields are optional."""
    response = client.post("/api/limits", json={})
    assert response.status_code == 503, (
        f"Expected 503 (validation passed → hit Not-initialized path); "
        f"got {response.status_code}: {response.text}"
    )
    assert "Not initialized" in response.text, (
        f"Expected 503 body to say 'Not initialized'; got: {response.text}"
    )


def test_limits_unknown_field_returns_422(client):
    """extra='forbid' rejects unknown keys; the offender's name appears in loc."""
    response = client.post("/api/limits", json={"peak_winter": 5000})
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert "peak_winter" in _loc_tail_set(errors), (
        f"Expected 'peak_winter' in error loc; got: {errors}"
    )


def test_limits_mixed_valid_invalid_still_422(client):
    """A valid + invalid mix still 422s, naming the offender."""
    response = client.post(
        "/api/limits", json={"peak": 100, "off_peak": 5000}
    )
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert "peak" in _loc_tail_set(errors)
    assert "off_peak" not in _loc_tail_set(errors)


# ---------------------------------------------------------------------------
# /api/override — body required (AC #2, #6)
# ---------------------------------------------------------------------------


def test_override_missing_mode_returns_422(client):
    """Empty body to /api/override is rejected; `mode` named in loc."""
    response = client.post("/api/override/boiler", json={})
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert "mode" in _loc_tail_set(errors), (
        f"Expected 'mode' in error loc; got: {errors}"
    )


def test_override_unknown_field_returns_422(client):
    """extra='forbid' on OverrideRequest: 'foo' rejected with name in loc."""
    response = client.post(
        "/api/override/boiler", json={"mode": "auto", "foo": "bar"}
    )
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert "foo" in _loc_tail_set(errors), (
        f"Expected 'foo' in error loc; got: {errors}"
    )


@pytest.mark.parametrize("mode", ["", "   ", "\t"])
def test_override_empty_or_whitespace_mode_returns_400(client, mode):
    """Empty / whitespace `mode` passes Pydantic (it's a valid str) but
    the handler's per-device allowlist rejects it with 400.

    Pinning this prevents a future `min_length=1` on `OverrideRequest.mode`
    from silently flipping the contract from 400 → 422 without a test alert.
    """
    response = client.post(
        "/api/override/boiler", json={"mode": mode}
    )
    assert response.status_code == 400, (
        f"Expected 400 (handler rejects empty/whitespace mode via "
        f"valid_modes); got {response.status_code}: {response.text}"
    )
    # The handler's error message names the device + lists valid modes.
    detail = response.json().get("detail", "")
    assert "Invalid mode for 'boiler'" in detail, (
        f"Expected handler error naming the device; got: {detail!r}"
    )


@pytest.mark.parametrize(
    "device",
    ["ac_living", "ac_bedroom", "ac_office", "ac_mancave"],
)
def test_ac_device_with_empty_body_returns_422(client, device):
    """`POST /api/override/ac_*` with `{}` now returns 422 (Pydantic
    missing-mode) before the handler's per-device 400 check fires.

    The migrated `test_ac_device_rejected_with_400` covers the
    `json={"mode": "on"}` path (→ 400). This test pins the new
    `json={}` path (→ 422) so the AC-removed contract is fully
    enumerated post-Pydantic migration. PASS2 N2 — Story 1.3 CR.
    """
    response = client.post(f"/api/override/{device}", json={})
    assert response.status_code == 422, (
        f"Expected 422 (Pydantic missing-mode fires before handler); "
        f"got {response.status_code}: {response.text}"
    )
    errors = response.json()["detail"]
    assert any(
        e.get("loc") and e["loc"][-1] == "mode" for e in errors
    ), f"Expected 'mode' in error loc; got: {errors}"


def test_override_known_pair_passes_validation(client):
    """A known (device, mode) pair via JSON body passes the validation gate.

    Test env: `app_state.config is None`, so accessing `config.entities`
    inside the handler raises AttributeError → 500. We pin == 500 so a
    regression where validation fails (422) or where the route flows to
    a different 500 source is distinguishable.
    """
    response = client.post(
        "/api/override/boiler", json={"mode": "auto"}
    )
    assert response.status_code == 500, (
        f"Expected 500 (validation passed → AttributeError on config); "
        f"got {response.status_code}: {response.text}"
    )
