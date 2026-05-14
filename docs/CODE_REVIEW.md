# Power Manager — Code Review

**Date:** 2026-05-14
**Reviewer:** Claude (Opus 4.7)
**Scope:** Full repository audit — `app/`, `tests/`, `dashboard/`, `power-manager-addon/`, configs, deployment.
**Baseline:** v1.0.59 / commit `ebab7da`
**Goal:** Identify problems, opportunities, test gaps, and noisy logging — platinum-grade target.

> **BMAD note:** BMAD is **not** installed in this folder. There is no `.bmad/`, `bmad-config*`, or related tooling under the project root or `.claude/`. Plan to install BMAD before the second pass, or treat this document as a flat checklist.

Findings are categorised by severity. Each finding is tagged so a second-pass agent (BMAD or otherwise) can grep and ingest them.

| Tag | Meaning |
|---|---|
| `[BUG]` | Concrete defect that can produce wrong behaviour today |
| `[SEC]` | Security / secret-handling concern |
| `[DESIGN]` | Architectural / structural improvement |
| `[PERF]` | Performance or resource concern |
| `[LOG]` | Log noise / clarity |
| `[TEST]` | Missing or weak test coverage |
| `[NIT]` | Style, cleanup, documentation |

---

## 1. Executive Summary

The project is in solid shape overall. Decision logic is reasoned, separation of concerns is good (`config` / `models` / `ha_client` / `decision_engine` / `scheduler` / `tariff`), and operational hardening (hysteresis, grace periods, smoothing buffer, pending-command retry) shows maturity.

However, the code is **not platinum-grade yet**:

1. **`decision_engine.py` (1,920 lines, 66 `plan.append` sites)** has become a god module. Cyclomatic complexity in `_handle_boiler`, `_handle_ev`, and `_handle_heaters` is high enough that several latent bugs slip through (summer EV decides power before boiler does; pool/heater branches mix smoothed and raw values; stale comments referencing removed `_handle_ev_winter`).
2. **Test coverage is unbalanced.** Tariff/frost/BMW/scheduler are well covered. `decision_engine` core paths (boiler full detection, solar surplus + grace period, EV solar mode, pool heating, table heater, dishwasher headroom check), `PowerBuffer`, `verify_and_retry_pending_commands`, and FastAPI routes have effectively **no tests**.
3. **Logging is over-eager.** `decision_engine._handle_ev` emits `logger.info("EV solar: …")` **every cycle** (2 880 lines/day), plus duplicated paused/waiting `info` lines. Combined with 26 `logger.info` action lines in `main.execute_decisions`, the add-on log fills up fast.
4. **A few real bugs**: a stale-state race for `last_change`, `mode_map` not handling `'solar'` for non-EV devices in `/api/override`, sensor defaults of `20.0 °C` masking dead temp sensors, the EV/boiler ordering inversion in summer, `_handle_heaters` referencing an `ovr['right_heater']` key that is never populated.
5. **Secrets posture is OK but fragile.** Real HA token sits in `config.yaml` (correctly gitignored), in `MEMORY.md`, and the deploy flow requires temporarily making the GitHub repo public — that window leaks history if the token ever lands in a commit.

Top 10 actionable items are at the end (§11).

---

## 2. Critical / High-Severity Findings

### 2.1 `[BUG]` Summer EV is decided *before* the boiler, with `boiler_will_use=0`
**File:** [app/decision_engine.py:1583-1612](../app/decision_engine.py#L1583-L1612)

```python
def _apply_summer_logic(...):
    ...
    # === EV CHARGING (reuse full EV logic - nighttime + solar) ===
    boiler_will_use = 0  # Will be updated after boiler logic   <-- never updated
    effective_headroom = _handle_ev(
        decisions, plan, ctx, effective_headroom, boiler_will_use
    )

    # === BOILER (reuse full boiler logic - nighttime heating + solar surplus) ===
    boiler_will_use, effective_headroom = _handle_boiler(...)
```

The off-peak branch in `_handle_ev` (line 1124) does `if must_start_now and boiler_will_use == 0 and not ctx['boiler_on']`. In summer this is *always* true because the value is hard-coded to 0 before the boiler is considered. Winter (`_apply_winter_logic`) gets this right — boiler first, then EV.

**Impact:** During summer off-peak nights, the EV may start at full amps while the boiler also wants to heat, briefly violating the 5 kW off-peak limit before the next decision cycle corrects it.

**Fix:** Mirror the winter order in summer (boiler → EV → pool → heaters → dishwasher), OR perform a two-pass solve.

---

### 2.2 `[BUG]` `/api/override` accepts `solar` mode for every device, but `mode_map` only has it for `ev`
**File:** [app/main.py:1088-1148](../app/main.py#L1088-L1148)

`valid_modes = ['auto', 'on', 'off', 'solar']` lets the caller send `solar` for any device. But `mode_map` only has a `'solar'` entry under `'ev'`. For `boiler`, `pool`, `dishwasher`, etc. the lookup falls back to `mode.capitalize()` → `"Solar"`, which is then passed to `input_select.select_option`. HA will return 400/422 because that option doesn't exist on those `input_select` helpers.

**Fix:** Either build `valid_modes` per-device (preferred), or reject `solar` for non-EV devices with HTTP 400 up front.

---

### 2.3 `[BUG]` `_handle_heaters` reads `ovr['right_heater']` which is never set
**File:** [app/decision_engine.py:1397](../app/decision_engine.py#L1397)

```python
if ovr.get('right_heater', 'auto') == 'auto':   # always 'auto' → branch always runs
```

`ovr` is populated in [`calculate_decisions`](../app/decision_engine.py#L340-L350) from `inputs.ovr_*`. There is no `ovr_right_heater` field on `PowerInputs` and no `right_heater` key in the `ovr` dict, so the conditional is dead code disguised as a feature flag.

**Fix:** Either implement the override (add `ovr_right_heater` to `PowerInputs`, add entity to `EntitiesConfig.ovr_right_heater`, parse in `ha_client.parse_inputs`), or delete the conditional.

---

### 2.4 `[BUG]` Temperature sensors silently default to 20.0 °C when unavailable
**File:** [app/ha_client.py:382-390](../app/ha_client.py#L382-L390) + [app/models.py:85-87](../app/models.py#L85-L87)

`get_num` returns the supplied default whenever the entity is missing/`unavailable`/`unknown`. For `temp_living`, `temp_bedroom`, `temp_mancave`, that default is `20.0`. If the Zigbee/Z-Wave/etc. temperature sensor dies, the decision engine cheerfully believes the room is at 20 °C — which feeds AC decision logic in the (currently undeveloped) summer-cool branch.

**Fix:** Make temps `Optional[float]` (like `pool_ambient_temp`) and have downstream code treat `None` as "sensor missing, do nothing".

---

### 2.5 `[BUG]` Race between predicted state and confirmed state in `_update_device_state`
**File:** [app/main.py:631-666](../app/main.py#L631-L666)

`_update_device_state` updates `state.last_change` whenever `state.on != new_on`. Falling back to `current_is_on` for non-confirmed devices means `last_change` gets bumped any time the *device itself* changes state (e.g., boiler thermostat trips off when it reaches setpoint). That timestamp then feeds `can_switch_device` hysteresis, so an opportunistic thermostat trip can lock the manager out of the device for `min_on_time/min_off_time` even when we have not commanded a change. The same applies to `ev_state == 132` flipping naturally with the IEC/ABB firmware (e.g., 132 ↔ 4).

**Fix:** Only update `last_change` when we issue a service call. Track external state separately for display.

---

### 2.6 `[BUG]` Inconsistent smoothed vs raw values inside `_handle_pool_heating`
**File:** [app/decision_engine.py:1227-1232](../app/decision_engine.py#L1227-L1232)

```python
effective_surplus = p1_return + bat_charge                  # p1_return is smoothed
net_p1 = ctx.get('smooth_net_p1', ctx.get('net_p1', 0))     # smoothed
virtual_surplus = -net_p1 + (pool_power_now if pool_on else 0)   # raw pool_power_now
has_solar = (is_exporting and effective_surplus > MIN_EXPORT_FOR_POOL) or \
            (pool_on and virtual_surplus > MIN_EXPORT_FOR_POOL)
```

Mixing smoothed grid readings with raw `pool_power_now` introduces flap risk if pool power surges/dips (e.g., compressor cycling) between buffer refreshes. Either smooth `pool_power` too, or use raw consistently.

---

### 2.7 `[BUG]` `decisions.ev.amps` is initialised from `ev_limit` and partial code paths don't reset it
**File:** [app/decision_engine.py:443](../app/decision_engine.py#L443)

`decisions.ev.amps = ev_limit` runs unconditionally before any branch. Several branches that set `action='pause'` or `action='off'` do not reset `amps`. The executor in `main.py` then ignores `amps` for `pause` and `off` (good), but `set_number` is still called in some branches (e.g., `action='adjust'`) without re-checking that the value is reasonable when the underlying logic was a "do nothing". Audit the early-return paths and assert that `amps` is only meaningful when `action in ('on','adjust','pause')`.

---

### 2.8 `[BUG]` `verify_and_retry_pending_commands` may double-resend on slow HA
**File:** [app/main.py:125-221](../app/main.py#L125-L221)

If a command succeeds *after* `backoff_seconds` elapse but *before* the next status snapshot is fetched, the loop will resend the command. For an EV charger, that triggers a fresh Modbus `START_CHARGING` (the very behaviour you mention working around for EV `turn_on` in `execute_decisions`).

**Fix:** Inside the retry branch, re-fetch the current state for that single entity (`get_state`) before resending, or attach a "command sent at" sequence ID and require the HA `last_changed` to be after that timestamp.

---

### 2.9 `[BUG]` `_handle_boiler` solar-surplus tracking only resets `boiler_importing_since` after `has_solar_surplus`, not when the boiler is force-off'd by tariff
**File:** [app/decision_engine.py:786-794](../app/decision_engine.py#L786-L794)

When `tariff == 'peak'` and the boiler is on, the function returns early without resetting `device_state.boiler_importing_since` and `boiler_solar_surplus_since`. Next time boiler turns back on (e.g., off-peak), these stale timers can mis-fire the grace period logic.

---

## 3. Medium-Severity Findings

### 3.1 `[DESIGN]` `decision_engine.py` is a 1,920-line god module
- 16 top-level functions, 66 `plan.append` sites, deep `ctx` dicts that act like ad-hoc structs.
- Refactor proposal:
  - `decision_engine/` package: one module per controllable device (`boiler.py`, `ev.py`, `pool.py`, `heaters.py`, `dishwasher.py`, `frost.py`, `bmw.py`).
  - Replace `ctx: dict` with a typed `DecisionContext` dataclass (`@dataclass(slots=True)`).
  - The orchestrator in `__init__.py` (or `engine.py`) becomes ~150 lines: gather inputs, build context, fan out to handlers, compute headroom, return result.

### 3.2 `[DESIGN]` `main.execute_decisions` is duplicate boilerplate per device
[main.py:453-628](../app/main.py#L453-L628) repeats the same `if action == 'on' and switch != 'on': await turn_on(); confirmed[..]=True; add_pending; logger.info(...)` pattern ~10 times. Extract a single helper:

```python
async def _apply_switch_decision(name, decision, current_state, switch_entity, log_label):
    if decision.action == 'on' and current_state != 'on':
        if await ha_client.turn_on(switch_entity):
            confirmed_states[name] = True
            add_pending_command(switch_entity, 'on')
            logger.info(f"{log_label}: ON")
    elif decision.action == 'off' and current_state != 'off':
        if await ha_client.turn_off(switch_entity):
            confirmed_states[name] = False
            add_pending_command(switch_entity, 'off')
            logger.info(f"{log_label}: OFF")
```

### 3.3 `[DESIGN]` `app_state` is a process-global with no locking around mutation
[main.py:115-116](../app/main.py#L115). The decision loop writes `last_inputs`, `last_decisions`, `last_alerts`, `last_ha_states` while HTTP handlers read them concurrently. CPython's GIL prevents tearing of single attribute reads, but compound reads (`if app_state.last_inputs is None` then `app_state.last_inputs.p1_power`) and dict iteration in `verify_and_retry_pending_commands` can see partial updates. Either keep `app_state` strictly write-once-per-loop with a single replace at the end, or use an `asyncio.Lock` around the loop's mutation section.

### 3.4 `[DESIGN]` `HAClient._request_with_retry` returns the response object — caller is responsible for releasing it
[ha_client.py:117-208](../app/ha_client.py#L117-L208). All current callers use `async with resp:` correctly, but the implicit contract is fragile. Either:
- have the helper accept a callback that consumes the response and closes it, or
- have it return `(status, json_payload, headers)` and own the lifecycle itself.

This will also let `_request_with_retry` retry on 5xx (currently it only retries on transport-level errors).

### 3.5 `[DESIGN]` BMW car selection logic is duplicated 3+ times
- [decision_engine.py:71-80](../app/decision_engine.py#L71-L80) (`calculate_ev_hours_needed`)
- [decision_engine.py:391-401](../app/decision_engine.py#L391-L401) (FULL override)
- [decision_engine.py:1815-1888](../app/decision_engine.py#L1815-L1888) (`check_bmw_low_battery`)
- [scheduler.py:213-253](../app/scheduler.py#L213-L253) (plugged-car heuristic)

Introduce a `pick_active_car(inputs) -> CarSnapshot` returning `(name, battery, range, capacity, target_soc, plug_state, charging_state, location)` and use that everywhere. Also kills several bugs lurking in the divergent `is plugged` definitions.

### 3.6 `[PERF]` `pending_commands` dict can grow unbounded
[main.py:92](../app/main.py#L92). Stale commands are cleaned at 2 hours, but if HA goes flaky for a long time you keep adding entries faster than they age out. Cap with `max_pending_commands` and drop oldest, or use `OrderedDict`.

### 3.7 `[PERF]` Hourly `location.reload()` in dashboard.js to "reclaim memory"
[dashboard.js:1156](../dashboard/static/dashboard.js#L1156). This is a workaround for a leak that is no longer obvious in the code (DOM nodes are reused in `buildDeviceTimelines` and `updateTimetable`). Profile first; the reload is user-visible (loses scroll position, blanks UI for ~500 ms). Either justify with a comment that links to the leak observed, or remove and watch.

### 3.8 `[BUG]` Hourly reload in dashboard.js never re-arms
The `setTimeout(... AUTO_RELOAD_MS)` only fires once because `location.reload()` happens before any second timeout. Not a problem per se, but if you really want hourly reloads under load, the first reload must reach `DOMContentLoaded` again — which it does, so the cycle is self-perpetuating. Still, document this.

### 3.9 `[BUG]` `_get_battery_str` doesn't filter the empty string
[main.py:797-802](../app/main.py#L797-L802) handles `None`, `"unavailable"`, `"unknown"` but not `""`. `get_str` in `ha_client.parse_inputs` does. Inconsistency.

### 3.10 `[BUG]` Stale comment in `_handle_heaters`
[decision_engine.py:1315](../app/decision_engine.py#L1315): "effective_headroom already accounts for EV power decided by `_handle_ev_winter`" — no such function. It is `_handle_ev`. The function was renamed but the comment was not.

### 3.11 `[BUG]` `decision_engine.py:1147` magic number `25.0`
```python
hours_until_super = max(0, 1.0 - current_hour) if current_hour < 1 else (25.0 - current_hour)
```
Reads like a typo. It's `24 - current_hour + 1.0` (hours until 01:00 tomorrow), but `25.0` is opaque. Replace with `(24 - current_hour) + 1.0` and a comment.

### 3.12 `[BUG]` Moon-phase computation lacks anchor citation
[main.py:939-945](../app/main.py#L939-L945). Reference date is "Jan 6, 2000" which is the new moon of that year. Anchor an explicit URL or astronomical reference; the formula isn't obvious from the constant.

### 3.13 `[DESIGN]` Dutch / English / emoji override labels are scattered
[main.py:1121-1131](../app/main.py#L1121-L1131) (mode_map), [decision_engine.py:144-168](../app/decision_engine.py#L144-L168) (`parse_override`), [run.sh:33-35](../power-manager-addon/run.sh#L33-L35) (creates EV `input_select` options).

If you ever localise or change an emoji, all three must move together. Define one canonical Python module (`overrides.py`) that exports `LABELS`, `parse(label) -> mode`, `format(mode, device) -> label` and import from everywhere — including a single source of truth for `set_options`.

### 3.14 `[DESIGN]` `config.py` `_apply_config` is partial — many sections silently ignored
Only `home_assistant`, `polling_interval`, `port`, `max_import`, `tariff_prices`, `frost_protection`, `bmw_low_battery`, `debug` are applied from YAML. **`ev`, `boiler`, `pool`, `heaters`, `ac`, `entities`, `timing`, `summer_cool_threshold`, etc. cannot be overridden from `config.yaml`** despite the user-facing `config.yaml.example` likely promising otherwise.

Either:
- generalise with a recursive merge (`pydantic-settings` would let you delete most of this file), or
- explicitly document which sections are file-overridable and reject others up front.

### 3.15 `[SEC]` Add-on rebuild requires temporarily making the GitHub repo public
Documented in `CLAUDE.md` and `MEMORY.md`. The window between `gh repo edit --visibility public` and `--visibility private` is a real exposure surface — any token, key, or credential that ever lands in commit history becomes world-readable for that window. Mitigations:
- Build the image yourself, push to GHCR, point the add-on at the registry image instead of cloning at build time.
- Or use a deploy key + a private repo URL the add-on supervisor can use (HA add-on framework allows custom Docker registries).

### 3.16 `[SEC]` Real long-lived HA token in `MEMORY.md`
`MEMORY.md` lives under `C:\Users\galletn\.claude\projects\…`. That folder is not under your git tree so it won't be pushed, but it is plain text, world-readable on Windows by default for any user with read access to your profile. The token's `exp` is ~63 years out. Treat memory files as secrets; rotate the token periodically and avoid storing the value verbatim in memory.

---

## 4. Logging — Noise, Clarity, Severity

### 4.1 `[LOG]` `EV solar: …` logs every cycle, even when EV is doing nothing
[decision_engine.py:1010](../app/decision_engine.py#L1010):
```python
logger.info(f"EV solar: {reason}")
```
This runs on every call to `_handle_ev` (every 30 s), regardless of whether anything is changing or even whether the EV is plugged in. With `2 880` cycles/day this single line dominates the log. Same for [decision_engine.py:1076 and :1079](../app/decision_engine.py#L1076-L1079) (`EV: PAUSING …`, `EV: solar mode, waiting for conditions`).

**Recommendations:**
1. Demote to `logger.debug` (decisions are visible in `plan` which is exposed via the dashboard and `status_text` helper).
2. Only emit `logger.info` when the decision *changes* (i.e., differs from the previous cycle's decision for this device).
3. Drop the `logger.info` "Pool fan: corrected" if it fires repeatedly when the heat pump's auto-fan keeps flipping back.

### 4.2 `[LOG]` `execute_decisions` writes 1-2 INFO lines per device-state-change
[main.py:483-623](../app/main.py#L483-L623) is correct in that these only fire when a state *changes*. But many lines duplicate what's already in `result.plan`. Consider:
- Drop the per-device `logger.info` and instead log one INFO line per cycle summarising changes (`"Cycle: boiler ON, EV adjust 10A, pool fan low"`).
- Keep INFO for: connect/reconnect to HA, successful retries, alerts sent, errors, lifecycle messages.
- Move per-device transitions to DEBUG.

### 4.3 `[LOG]` `plan.append("Table: raw=… rem=… sig=… enough=… bat=… draining=…")`
[decision_engine.py:1356-1358](../app/decision_engine.py#L1356-L1358). This debug-style line is appended to the user-facing plan every cycle. Move to `logger.debug` and replace the user-facing line with the human-readable summary that's already produced when the decision changes. The plan is what surfaces on the dashboard timeline; it should read like a status, not telemetry.

### 4.4 `[LOG]` `"BMW i5: 40% (plugged in)"` is appended to plan every cycle 20:00-22:00
These are useful once per evening, not 120 times. De-duplicate (compare against last emitted) or only append when state changes.

### 4.5 `[LOG]` Module-level `logging.basicConfig` in `main.py:31-35`
`basicConfig` is a one-time global mutation. If anything else in the import graph configures logging first, this silently no-ops. Either:
- Move to a `configure_logging()` function called from `lifespan()`, or
- Use `logging.config.dictConfig` with an explicit handler/formatter declaration.

Also: levels are not configurable via `config.yaml` (only the boolean `debug`). Add `log_level: INFO` and accept standard `DEBUG/INFO/WARNING/ERROR`.

### 4.6 `[LOG]` `logger.warning(f"Could not read limits from HA: {e}")` runs every status request when HA is missing input_numbers
[main.py:1197](../app/main.py#L1197). If the user hasn't created the `input_number.pm_limit_*` helpers (they're optional), this warning fires on every dashboard refresh. Either downgrade to `debug` once recognised, or rate-limit it.

### 4.7 `[LOG]` Plan strings mix English and Dutch
`"Boiler: HEATING"`, `"Boiler: ON"` (English) vs the override labels (`"⚡ Laden"`, `"☀️ Solar"`, `"🤖 Auto"`, Dutch). Pick one user language for the plan output and put translations in one place (relates to §3.13).

### 4.8 `[LOG]` Several `logger.error(... exc_info=True)` are appropriate; one to check
[main.py:420](../app/main.py#L420): `logger.debug(f"Failed to update status helpers: {e}")` — a failure to update is probably worth INFO not DEBUG. If it persists (HA helper missing) it should warn once and stop.

---

## 5. Tests — Coverage Gaps and Quality

### 5.1 `[TEST]` Current footprint

| Area | File | Status |
|---|---|---|
| Tariff calculation | `test_tariff.py` | Good (covers weekday/weekend, holidays, edges) |
| Frost protection | `test_frost_protection.py` | Good |
| BMW low battery | `test_bmw_low_battery.py` | Good |
| Dishwasher logic | `test_appliances.py` | OK — covers basics; misses solar+other devices interaction |
| Scheduler | `test_scheduler.py` | OK — power-limit verification could go deeper |
| HA client | `test_ha_client.py` | Strong — mocked endpoints, error paths |
| Decision engine core | `test_decisions.py` | **Weak** — 9 tests, mostly smoke |

### 5.2 `[TEST]` Missing entirely

**No tests for:**
- `PowerBuffer` smoothing behaviour (does `min/max/avg` actually filter the documented transient spike?).
- `is_boiler_full` time-based confirmation (boundary at exactly `confirm_seconds`).
- `get_solar_battery_charge` (zero-PV night case, partial PV, fully covering).
- `calculate_available_amps` (zero divisor, fractional W).
- `calculate_ev_hours_needed` (no car, both cars, ≥80 % SoC).
- `check_boiler_deadline` (warning window, critical window, night rollover at midnight).
- `_handle_boiler` solar-surplus grace period (turn on, stay on with intermittent surplus, turn off after 5 min sustained import).
- `_handle_ev` solar mode (battery SOE thresholds, smoothed vs instantaneous start/stop, amp ramp 1 A/cycle clamp).
- `_handle_pool_heating` (pool season gate, virtual surplus, grace period).
- `_handle_heaters` (battery protection at 80 % SoE, table vs right priority, summer "on" override behaviour).
- `_apply_dishwasher_logic` solar surplus + headroom edge cases.
- `_calculate_final_headroom` (avoid double-counting).
- `verify_and_retry_pending_commands` (success after first retry, give-up after 2 h, notification sent on first retry).
- FastAPI routes (`/api/status`, `/api/override`, `/api/limits`, `/api/health`).
- `_extract_notify_service_name` (the parser is non-trivial — covers 4 prefixes — but has no tests).

### 5.3 `[TEST]` `test_scheduler.py:148` has a probable bug
```python
if slot.start.day > inputs.bmw_i5_battery:  # Different day check
```
`bmw_i5_battery` is a percent value (e.g., 40). `slot.start.day > 40` is always false. The assert inside is never executed. Replace with a real "next day" check against `winter_offpeak.day`.

### 5.4 `[TEST]` `test_decisions.py:122` asserts a tautology
```python
assert result.decisions.ev.amps >= config.ev.min_amps
```
`decisions.ev.amps` is initialised to `ev_limit = 6` which equals `config.ev.min_amps = 6` by default. The assertion passes even if the override branch did nothing. Bind `amps` to a non-trivial expected value.

### 5.5 `[TEST]` No async event-loop integration test
The decision loop is the heart of the program but has no test. Even a small one with `asyncio.gather` would be valuable: spin up a fake `HAClient` returning canned states, advance fake time, assert that the right service calls were issued in the right order.

### 5.6 `[TEST]` No `pytest.ini` / `pyproject.toml` test config
Add:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
filterwarnings = ["error::DeprecationWarning"]
```
…so warnings actually surface during CI.

### 5.7 `[TEST]` No CI configuration in repo
No `.github/workflows/`, no `Makefile`, no `tox.ini`. `pytest` and `ruff` are installed but never run automatically. Add a minimal workflow that runs `ruff check`, `pytest -v`, and `mypy app/` on push to main.

### 5.8 `[TEST]` Coverage reporting available but never used
`pytest-cov` is in requirements but no `coverage.cfg`/`pyproject.toml` settings. Add `pytest --cov=app --cov-report=term-missing --cov-fail-under=70` to CI.

---

## 6. Security & Configuration

### 6.1 `[SEC]` CORS is wide open
[main.py:307](../app/main.py#L307):
```python
allow_origins=["*"], allow_credentials=True
```
A browser will reject `*` + credentials per spec, but FastAPI allows the config. Tighten to `[ha_url, "https://gallet.duckdns.org:8123"]` or `[".*\\.gallet\\.duckdns\\.org"]` once you know which origins you need.

### 6.2 `[SEC]` `X-Frame-Options: ALLOWALL` / CSP `frame-ancestors *`
[main.py:317-319](../app/main.py#L317-L319). Necessary for HA companion app iframe, but means any site can embed the dashboard. Since the dashboard exposes power data + control buttons, narrow this with an explicit origin allowlist (`frame-ancestors 'self' https://homeassistant.local https://gallet.duckdns.org`).

### 6.3 `[SEC]` `/api/override` and `/api/limits` accept POST with no auth
The add-on sits behind HA ingress which adds auth, so locally this is fine. But the server also binds `0.0.0.0` on port `8081` in non-ingress mode and accepts unauthenticated control writes. If you ever expose this on a non-ingress port, anyone on the LAN can turn the EV charger on/off.

**Fix:** Add a shared-secret header check (`X-PM-Token`) that defaults to a generated value when running outside the add-on context. Skip it when `SUPERVISOR_TOKEN` is present (i.e., behind ingress).

### 6.4 `[SEC]` Config validation is incomplete
[config.py:289-301](../app/config.py#L289-L301). Validates token presence and that limits are > 0, but not:
- `polling_interval > 0` (a misconfigured `0` busy-loops the event loop).
- `min_amps <= max_amps` and both > 0.
- `min_on_time, min_off_time >= 0`.
- `notify_entity` plausibly non-empty (currently defaults to `"mobile_app_your_phone"` which won't exist).

### 6.5 `[NIT]` `pool_hist.json` is in the working tree but not tracked or used
`git status` shows it untracked. Either commit it (with a header explaining the format) or add it to `.gitignore`. If nothing reads it, delete it.

### 6.6 `[NIT]` Repo metadata leaks paths
`MEMORY.md` lists IPs, hostnames, the sudo password (`1234`) on `delaware`. These are in *your* memory file and won't push to git, but worth noting: the password should be rotated; a stronger one wouldn't be misplaced.

### 6.7 `[SEC]` `verify_ssl: false` shipped in `config.yaml` because the HA cert is self-signed
That's fine for the LAN URL but the file uses `https://gallet.duckdns.org:8123` which goes through DuckDNS (public). Make sure that public hostname resolves to a private IP only reachable from the add-on host, not the public internet.

---

## 7. API & FastAPI Specific

### 7.1 `[DESIGN]` `/api/override/{device}` uses a query parameter for `mode`
[main.py:1085-1088](../app/main.py#L1085-L1088):
```python
@app.post("/api/override/{device}")
async def set_override(device: str, mode: str):
```
`mode` is a query param. The HTTP-idiomatic alternative is a JSON body or a `mode` path component. Either:
```python
@app.post("/api/override/{device}/{mode}")
```
or:
```python
@app.post("/api/override/{device}")
async def set_override(device: str, payload: OverrideRequest):
```
With Pydantic `OverrideRequest` you get validation on the device-mode pair for free.

### 7.2 `[DESIGN]` `/api/limits` POST uses query params and lets unknown fields silently pass
[main.py:1202-1206](../app/main.py#L1202-L1206). Use a Pydantic model with explicit field bounds (`Field(ge=500, le=12000)`). Today nothing prevents `POST /api/limits?peak=99999999`.

### 7.3 `[DESIGN]` `/api/status` payload is huge and partially `Optional` chains
The handler at [main.py:739-906](../app/main.py#L739-L906) builds a deeply nested dict by hand. Switch to a Pydantic response model so the schema is auto-documented in `/docs` and any field rename is caught at startup, not at runtime.

### 7.4 `[BUG]` `/api/status` returns 503 with `{"error": "No data yet"}` but body type is `JSONResponse(..., status_code=503)`
Healthy and harmless, just inconsistent with other endpoints that raise `HTTPException`. Pick one.

### 7.5 `[NIT]` Three dashboard routes (`/`, `/power`, `/timeline`) duplicate the "templates may be None" guard
Extract a `render_or_503(name, **ctx)` helper.

---

## 8. Models / Data

### 8.1 `[DESIGN]` `PowerInputs` has 90+ flat fields
[models.py:35-130](../app/models.py#L35-L130). Group into subobjects (`InputsBoiler`, `InputsEV`, `InputsBMW`, `InputsBattery`, `InputsAC`, `InputsOverrides`) — the call sites would become `inputs.boiler.power` etc. which reads better and lets you add docstrings per group.

### 8.2 `[DESIGN]` `AllDeviceStates` mixes "per-device state" with global timers (`boiler_low_power_since`, `boiler_heating_tonight_seconds`, …)
Move boiler-specific tracking into `boiler.state: BoilerRuntimeState` to match the future modular layout.

### 8.3 `[BUG]` `EVState` enum mixes IEC and ABB codes — both meaning "charging"
[models.py:10-32](../app/models.py#L10-L32). The mitigation (treating `IEC_CHARGING_C2` and `CHARGING` as the same logical state) is correct but spread across ~6 files. Add helpers on the enum:
```python
@classmethod
def is_charging(cls, code) -> bool: ...
@classmethod
def is_plugged(cls, code) -> bool: ...
@classmethod
def is_ready(cls, code) -> bool: ...
```
…and use them everywhere instead of repeating the `set` literal.

### 8.4 `[BUG]` `EVState.IEC_OTHER = 5` is undefined behaviour for the rest of the code
None of the predicate sets include `IEC_OTHER` as "charging" or "plugged". A car that lands in IEC state 5 will be treated as "no car". Either delete `IEC_OTHER` or document the intended treatment.

### 8.5 `[NIT]` `Decisions` defaults wire heater `ACDecision(temp=17)` for mancave only
Other rooms use 22 by default. If the AC summer/winter logic is going to materialise, lift these into a `WINTER_SETPOINTS` map in config (already partially modelled in `ACConfig`).

---

## 9. Dashboard / JS

### 9.1 `[DESIGN]` `dashboard.js` is 1,157 lines in one file
Modularise (`api.js`, `flow.js`, `timeline.js`, `consumers.js`, `bms.js`) and `<script type="module">`. Most browsers in HA's WebView support ES modules.

### 9.2 `[BUG]` `setTimeout(() => location.reload(), AUTO_RELOAD_MS)` is set at DOMContentLoaded — `consecutiveErrors` and pending overrides are not preserved
The reload nukes any in-flight override the user just clicked. Either:
- restart the timer when a click happens (extend the lease), or
- skip the reload when `Object.keys(pendingOverrides).length > 0`.

### 9.3 `[BUG]` `consecutiveErrors > 2` permanently slows polling — never resets on success in the backoff branch
[dashboard.js:986-991](../dashboard/static/dashboard.js#L986-L991). On success the code resets `consecutiveErrors = 0` but does **not** restore `refreshInterval` to `REFRESH_INTERVAL`. So one stretch of HA flakiness leaves the dashboard polling every 2 minutes forever. Re-`setInterval` to the normal value when `consecutiveErrors` flips back to 0.

### 9.4 `[NIT]` `alert()` for failed overrides
[dashboard.js:1017](../dashboard/static/dashboard.js#L1017). Replace with an inline error banner — modal alerts in an embedded HA panel are jarring.

### 9.5 `[NIT]` `window._batDebugCount` left in production
[dashboard.js:716-719](../dashboard/static/dashboard.js#L716-L719). Logs the first 3 battery payloads. Delete or gate behind `?debug=1`.

### 9.6 `[NIT]` Inline `style="…"` in `buildTimeline` and others
Move to CSS classes for `timeline-segment` widths via `--width: var(...)` custom properties. Reduces XSS surface.

---

## 10. Deployment / Add-on

### 10.1 `[DESIGN]` Dockerfile clones from GitHub at build time
[power-manager-addon/Dockerfile:8](../power-manager-addon/Dockerfile#L8). The cache-bust mechanism + temporary repo-public dance is brittle and costs an interactive step every release.

**Better:** Multi-stage build that COPYs the source from the user's local clone, then publish the image to GHCR. The add-on `config.yaml` can point at the image. Releases become `docker push` instead of `git clone @ build-time`.

### 10.2 `[NIT]` `run.sh` writes Python source inline to a heredoc to set EV `input_select` options
[run.sh:28-45](../power-manager-addon/run.sh#L28-L45). Move into a small `scripts/setup_ha_options.py` file and call it from `run.sh` — easier to review, test, and lint.

### 10.3 `[NIT]` `power-manager.service` exists at the repo root but the deployment doc only mentions HA add-on
If the service is unused, delete it. If it's an alternative deployment, document it.

### 10.4 `[NIT]` `ha-standalone/` directory exists but isn't documented in README/ARCHITECTURE
Either document or drop.

### 10.5 `[NIT]` `repository.yaml` is 93 bytes and minimal — fine, just confirm it points at the right add-on slug
Quick verify on next pass.

### 10.6 `[DESIGN]` Dependencies are unpinned (`>=`)
[requirements.txt](../requirements.txt). Pin in a `requirements.lock` (or use `uv pip compile`) so a fresh add-on rebuild a year from now gives the same image. Aiohttp/FastAPI/Uvicorn evolve; you'll want to control that yourself.

---

## 11. Top 10 Actionable Items (recommended order)

Rank by *risk × ease*:

1. **Fix `mode_map` for `/api/override` solar mode** (2.2) — half a screen of code, prevents silent 422s. `[BUG][SEC-]`
2. **Remove the `_handle_heaters` dead `right_heater` override branch, or wire it up** (2.3) — clarity & honesty.
3. **Stop `last_change` getting bumped on external state flips** (2.5) — silent hysteresis lockouts in production today.
4. **Reverse EV vs boiler order in `_apply_summer_logic`** (2.1) — restores priority invariant.
5. **Demote per-cycle `EV solar: …` info logs to debug, log on state change only** (4.1, 4.2) — single biggest log-noise reduction.
6. **Add tests for `PowerBuffer`, `is_boiler_full`, `_handle_ev` solar mode, `verify_and_retry_pending_commands`** (5.2, 5.5) — protect the riskiest surfaces.
7. **Pydantic-validate `/api/override` and `/api/limits` payloads** (7.1, 7.2, 6.3) — catch bad input at the edge, simplify handlers.
8. **Add minimal CI: `ruff check`, `pytest`, coverage gate** (5.7, 5.8) — every other fix gets safer after this lands.
9. **Switch add-on deploy to GHCR (or pinned commit SHA + private clone)** (10.1, 3.15) — removes the "make repo public" exposure window.
10. **Refactor `decision_engine.py` into `decision_engine/` package, one file per device** (3.1) — large refactor, but everything else gets easier afterwards. Do last.

---

## 12. Quick "platinum-grade" checklist for the second pass

| Item | Status today | Target |
|---|---|---|
| CI on every push | ❌ none | GitHub Actions: ruff + pytest + mypy + coverage ≥80 % |
| Lockfile / pinned deps | ❌ unpinned | `requirements.lock` (uv or pip-tools) |
| `mypy --strict` clean | ❌ never run | Strict mode passes on `app/` |
| `ruff check` clean | likely ❌ | Zero warnings; `ruff format` applied |
| Per-PR coverage diff | ❌ | `pytest-cov` with `--cov-fail-under` |
| Pydantic v2 models for I/O | ❌ raw dicts / dataclasses | All API in & out is Pydantic |
| Structured logging | ❌ text | `structlog` or JSON formatter, request ID per cycle |
| Metrics endpoint | ❌ | `/metrics` Prometheus (cycle duration, decision counts, alert counts) |
| Smoke test against a fake HA | ❌ | One pytest spinning up a stub HA returning canned states |
| Single source of truth for override labels | ❌ scattered | `overrides.py` module |
| Add-on image published to GHCR | ❌ rebuilds from public-repo clone | Versioned image tag |
| Test runtime | unknown | `<5 s` for full suite |

When you can tick every row of that table, "platinum grade" is a fair label.

---

*End of review.*
