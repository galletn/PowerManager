# Power Manager - Code Review Remediation Plan

## Overview

This document tracks all issues identified in the comprehensive code review and their remediation status.

---

## Critical Issues (Fix Immediately)

### 5.1 - Token Potentially Logged
- **File:** `app/main.py:74`
- **Issue:** Exception logged on connection failure may include URL with auth token
- **Fix:** Sanitize exceptions before logging - only log exception type, not full message
- **Status:** [x] COMPLETED

### 4.1 - Silent Failure in execute_decisions
- **File:** `app/main.py:196-252`
- **Issue:** All device control wrapped in single try/except - partial execution leaves inconsistent states
- **Fix:** Implement per-device error handling with retry logic
- **Status:** [x] COMPLETED

### 5.2 - No Input Validation on API Endpoints
- **File:** `app/main.py:554-594`
- **Issue:** `/api/limits` accepts any integer values without bounds checking
- **Fix:** Add FastAPI Query validation with ge/le constraints
- **Status:** [x] COMPLETED

### 9.1 - No Config Validation
- **File:** `app/config.py:228-249`
- **Issue:** `load_config()` doesn't validate required fields or value ranges
- **Fix:** Add validation for token, power limits, and other critical values
- **Status:** [x] COMPLETED

---

## High Priority Issues

### 2.1 - God Function: _apply_winter_logic
- **File:** `app/decision_engine.py:344-530`
- **Issue:** Function is 186 lines with 4+ nesting levels
- **Fix:** Split into `_handle_boiler_winter`, `_handle_ev_winter`, `_handle_heater_winter`
- **Status:** [ ] Pending

### 2.2 - Global State Anti-Pattern
- **File:** `app/main.py:35-47`
- **Issue:** 9 global variables for state management
- **Fix:** Encapsulate in AppState dataclass
- **Status:** [ ] Pending

### 3.1 - Race Condition in Device State Update
- **File:** `app/main.py:255-273`
- **Issue:** device_state updated after decisions, causing timing issues
- **Fix:** Update based on actual HA response, not predicted state
- **Status:** [ ] Pending

### 4.2 - No HA Disconnect Detection
- **File:** `app/ha_client.py:50-64`
- **Issue:** Stale aiohttp session on disconnect
- **Fix:** Add `ensure_connected()` method with session health check
- **Status:** [ ] Pending

### 6.1 - No Tests for Dishwasher/Washer/Dryer Logic
- **File:** `tests/`
- **Issue:** `_apply_dishwasher_logic` has no unit tests
- **Fix:** Create `test_appliances.py` with comprehensive scenarios
- **Status:** [x] COMPLETED

---

## Medium Priority Issues

### 1.1 - Magic Numbers in Decision Engine
- **File:** `app/decision_engine.py:393, 560`
- **Issue:** Magic numbers without constants
- **Fix:** Add constants at top of file: `MIN_EXPORT_FOR_BOILER`, `DW_EXPECTED_POWER`, etc.
- **Status:** [x] COMPLETED

### 1.2 - Missing dishwasher override parsing
- **File:** `app/ha_client.py:248`
- **Issue:** `ovr_dishwasher` not parsed in `parse_inputs()`
- **Fix:** Add `ovr_dishwasher=get_str(e.ovr_dishwasher, "")` to parse_inputs
- **Status:** [x] COMPLETED

### 2.3 - Context Dict Anti-Pattern
- **File:** `app/decision_engine.py:211-241`
- **Issue:** Large dicts passed instead of typed objects
- **Fix:** Create `DecisionContext` dataclass
- **Status:** [ ] Pending

### 3.3 - Weekend Tariff Edge Case at Midnight/DST
- **File:** `app/tariff.py:94-130`
- **Issue:** DST transitions not handled
- **Fix:** Use timezone-aware datetime, add DST edge case tests
- **Status:** [ ] Pending

### 3.4 - Boiler "Full" Detection May Be Incorrect
- **File:** `app/decision_engine.py:127-128`
- **Issue:** Sensor glitches could trigger false "full" detection
- **Fix:** Add time-based confirmation (must be low power for X minutes)
- **Status:** [ ] Pending

### 4.3 - Unbounded Alert Cooldown Dict
- **File:** `app/main.py:46`
- **Issue:** `alert_cooldowns` never cleaned up - minor memory leak
- **Fix:** Add periodic cleanup of entries older than 1 hour
- **Status:** [ ] Pending

### 4.4 - Notification Service Name Extraction Fragile
- **File:** `app/ha_client.py:132-140`
- **Issue:** Assumes `mobile_app_` prefix for notifications
- **Fix:** Add validation and handle different entity formats
- **Status:** [ ] Pending

### 5.3 - SSL Verification Disabled by Default
- **File:** `app/config.py:16`
- **Issue:** No warning when SSL verification disabled
- **Fix:** Log warning on startup when verify_ssl=False
- **Status:** [x] COMPLETED

### 6.2 - No Integration Tests for HA Client
- **File:** `tests/`
- **Issue:** HAClient has no tests
- **Fix:** Create `test_ha_client.py` with mocked aiohttp responses
- **Status:** [ ] Pending

### 6.3 - No Tests for Scheduler Module
- **File:** `tests/`
- **Issue:** scheduler.py has zero test coverage
- **Fix:** Create `test_scheduler.py` with slot allocation tests
- **Status:** [x] COMPLETED

### 7.1 - Duplicate HA API Call in Status Endpoint
- **File:** `app/main.py:297, 365`
- **Issue:** `_get_consumers_data()` makes redundant API call
- **Fix:** Pass already-fetched states or use short TTL cache
- **Status:** [x] COMPLETED

### 7.3 - Schedule Generation on Every Status Call
- **File:** `app/main.py:349`
- **Issue:** CPU-intensive schedule generation on every request
- **Fix:** Cache schedule with 5-minute TTL
- **Status:** [x] COMPLETED

### 8.1 - CLAUDE.md Entity Names Outdated
- **File:** `CLAUDE.md`
- **Issue:** Some entity names don't match current code
- **Fix:** Update to match config.py entity names
- **Status:** [x] COMPLETED

### 10.2 - No Error Display for Failed Overrides
- **File:** `dashboard/static/dashboard.js:564-577`
- **Issue:** Failed override only shows alert(), no visual feedback
- **Fix:** Add visual feedback on buttons (shake animation, color change)
- **Status:** [x] COMPLETED

### 10.3 - Accessibility Issues
- **File:** `dashboard/templates/dashboard.html`, `dashboard/static/style.css`
- **Issue:** No ARIA labels, color-only indicators, small touch targets
- **Fix:** Add ARIA labels, text alternatives, increase button sizes to 44px
- **Status:** [x] COMPLETED

---

## Low Priority Issues

### 1.3 - Inconsistent Error Message Formatting
- **File:** `app/main.py:251-252`
- **Issue:** Some exceptions logged with `exc_info=True`, others without
- **Fix:** Standardize to always include `exc_info=True` for error-level logs
- **Status:** [ ] Pending

### 3.2 - EV Amp Calculation Potential Division by Zero
- **File:** `app/decision_engine.py:435`
- **Issue:** `watts_per_amp` could theoretically be 0
- **Fix:** Add guard check before division
- **Status:** [ ] Pending

### 5.4 - No CORS Configuration
- **File:** `app/main.py:99-104`
- **Issue:** No CORS headers configured
- **Fix:** Add CORSMiddleware restricting to localhost and HA domain
- **Status:** [x] COMPLETED

### 6.4 - Fixture at Wrong Time for Test
- **File:** `tests/conftest.py:88-91`
- **Issue:** `winter_peak` fixture is at 14:00 (off-peak), not peak
- **Fix:** Change to 09:00 or 18:00 for actual peak period
- **Status:** [x] COMPLETED

### 7.2 - Dashboard Refreshes Every 5 Seconds
- **File:** `dashboard/static/dashboard.js:6`
- **Issue:** Excessive polling
- **Fix:** Increase to 10-15 seconds or implement SSE/WebSocket
- **Status:** [x] COMPLETED

### 8.2 - No API Documentation
- **File:** `app/main.py`
- **Issue:** No OpenAPI documentation on endpoints
- **Fix:** Add response_model and description to FastAPI endpoints
- **Status:** [x] COMPLETED

### 8.3 - Missing Docstrings on Critical Functions
- **File:** `app/decision_engine.py:344`, `app/scheduler.py:387`
- **Issue:** Complex functions lack detailed docstrings
- **Fix:** Add comprehensive docstrings explaining logic
- **Status:** [ ] Pending

### 9.2 - Hardcoded Port in main()
- **File:** `app/main.py:647`
- **Issue:** Port 8081 hardcoded
- **Fix:** Add port to Config or use environment variable
- **Status:** [ ] Pending

### 10.1 - No Loading States
- **File:** `dashboard/templates/dashboard.html`
- **Issue:** Initial load shows plain "Loading..." text
- **Fix:** Add skeleton screens for better UX
- **Status:** [x] COMPLETED (CSS added)

---

## Implementation Order

### Phase 1: Critical Security & Stability
1. Fix token logging (5.1)
2. Add config validation (9.1)
3. Add API input validation (5.2)
4. Fix execute_decisions error handling (4.1)

### Phase 2: Core Logic Improvements
1. Split god functions (2.1)
2. Fix dishwasher override parsing (1.2)
3. Add magic number constants (1.1)
4. Fix device state race condition (3.1)
5. Add HA disconnect detection (4.2)

### Phase 3: Testing
1. Add dishwasher/appliance tests (6.1)
2. Add HA client tests (6.2)
3. Add scheduler tests (6.3)
4. Fix test fixtures (6.4)

### Phase 4: Performance & Polish
1. Fix duplicate API calls (7.1)
2. Add schedule caching (7.3)
3. Improve dashboard accessibility (10.3)
4. Add CORS configuration (5.4)
5. Update documentation (8.1, 8.2, 8.3)

---

## Notes

- All changes should maintain backward compatibility
- Run existing tests after each change: `pytest tests/ -v`
- Deploy to server after Phase 1 and Phase 2 complete
