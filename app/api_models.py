"""Pydantic request bodies for the FastAPI write endpoints.

Lives in its own module so route handlers stay focused on flow control,
not validation rules. Bounds for power limits come from PASS2 §7.2:
residential power should be between 500W (below this no realistic device
runs) and 12000W (covers triple-phase 16A * 230V * 3 ~= 11kW headroom).

`extra="forbid"` rejects unknown JSON keys with 422 — the API analogue of
the config-side unknown-key check landed in Story 1.1.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LimitsRequest(BaseModel):
    """Body for POST /api/limits. All fields optional; only present fields update."""

    model_config = ConfigDict(extra="forbid")

    peak: Optional[int] = Field(default=None, ge=500, le=12000)
    off_peak: Optional[int] = Field(default=None, ge=500, le=12000)
    super_off_peak: Optional[int] = Field(default=None, ge=500, le=12000)


class OverrideRequest(BaseModel):
    """Body for POST /api/override/{device}. Mode is required.

    The (device, mode) allowlist check stays in the handler — it's
    per-device and depends on the `mode_map`, which would inflate this
    model. Pydantic validates that `mode` is a present string; the
    handler enforces the per-device allowlist with helpful detail bodies.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str
