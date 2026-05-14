# Power Manager — Code Review (Pass 2)

**Date:** 2026-05-14
**Baseline:** HEAD = `ebab7da` (v1.0.59) — same commit as Pass 1
**Method:** Multi-agent adversarial review coordinated by John (PM)
**Reviewers:**
- **Findings Validator** — cross-checked every Pass 1 finding against current code
- **Blind Hunter** — independent adversarial review, no visibility into Pass 1
- **Targeted edge-case walk** — focused pass on `tariff.py`, `scheduler.py`, `ha_client.py`, notify plumbing (Edge Case Hunter stalled; PM filled the gap)

Output supersedes nothing in [CODE_REVIEW.md](CODE_REVIEW.md) — it extends it. Both documents should be read together.

---

## 1. Executive summary

Pass 1 was substantively correct. Of ~60 numbered findings, the validator returned:

- **CONFIRMED:** ~55
- **PARTIAL:** 4 (§2.5, §2.7, §9.2, §9.3 — partial in interesting ways, see §3 below)
- **UNCLEAR:** 1 (§6.7 — `verify_ssl` ships under gitignore; can't audit from repo)
- **REFUTED:** 0
- **FIXED:** 0 (we haven't moved off `ebab7da` since Pass 1)

Pass 2 added **14 new findings + 6 bonus collateral findings**. The most material additions are:

1. **[BUG-CRITICAL] Frost protection silently disabled when temperature sensor is `unavailable`.** The single safety-critical feature returns `None`, plan-appends "Frost: No temp sensor", and does nothing — no alert, no fallback. ([decision_engine.py:1645-1647](../app/decision_engine.py#L1645-L1647))
2. **[BUG-HIGH] AC overrides accepted by `/api/override` and parsed in the engine, but never executed.** No AC branch in `execute_decisions`; `_apply_manual_overrides` doesn't read `ovr['ac_*']`. The dashboard lies. ([main.py:1093-1140](../app/main.py#L1093-L1140))
3. **[BUG-HIGH] Mobile-app notify-service name is stripped incorrectly.** `_extract_notify_service_name` strips the `mobile_app_` prefix, so a configured `mobile_app_iphone_van_nicolas_2` becomes `notify.iphone_van_nicolas_2` — but HA's mobile_app integration registers as `notify.mobile_app_<device>`. Notifications likely never arrive. NEEDS-INVESTIGATION. ([ha_client.py:335-358](../app/ha_client.py#L335-L358))
4. **[BUG-HIGH] `verify_and_retry_pending_commands` retries without re-checking the current decision.** A boiler-on command issued at 06:55 super-off-peak that takes a retry can fire at 07:01 in peak. ([main.py:125-221](../app/main.py#L125-L221))
5. **[BUG-HIGH] `_apply_config` silently drops `entities`, `ev`, `boiler`, `pool`, `heaters`, `ac`, `timing` from YAML.** A user editing `config.yaml` to change entity IDs sees no error and the engine ignores the value. ([config.py:306-364](../app/config.py#L306-L364))
6. **[BUG-HIGH] `generate_timetable` skips totals/utilization for the final hour.** The last hour of the 24-hour timetable always reports `total_power=0` and has no `utilization` key — the dashboard's over-limit visualisation will never warn for that hour. ([scheduler.py:585-591](../app/scheduler.py#L585-L591))
7. **[BUG-HIGH] `heater_right` decisions are executed but never tracked in `_update_device_state`.** Hysteresis (`min_on_time`, `min_off_time`) is completely disabled for the right heater — confirmed independently by both Validator (B7) and Blind Hunter (#4). ([main.py:631-666](../app/main.py#L631-L666))
8. **[BUG-HIGH] `update_state('ev', inputs.ev_state == 132)` only treats one EV code as "on".** With v1.0.51 introducing state 133 (PAUSED) and v1.0.52 using soft-pause at 5A, the charger now oscillates 132↔133 every cycle — `state.last_change` bumps constantly, locking the manager out via hysteresis. Confirmed by Validator B2 and Blind Hunter #3. ([main.py:661](../app/main.py#L661))
9. **[BUG-MEDIUM] Pool grace-timer reset missing on `pool_mode in {'off','on'}` early returns** ([decision_engine.py:1205-1212](../app/decision_engine.py#L1205-L1212)) — same family as §2.9 (boiler tariff force-off). Validator B6.
10. **[BUG-MEDIUM] `get_num` semantic inversion: `default if default != 0.0 else None`.** A caller passing `default=20.0` receives the literal 20.0 on sensor failure; a caller passing `default=0.0` receives `None`. Counterintuitive and is the root cause of §2.4 (temp defaults to 20°C). Validator B1. ([ha_client.py:382-390](../app/ha_client.py#L382-L390))
11. **[BUG-MEDIUM] Belgian holiday machinery is dead code.** `get_belgian_holidays`, `easter_date`, `FIXED_HOLIDAYS` are defined but `get_tariff` never references them. The comment at [tariff.py:91-92](../app/tariff.py#L91-L92) explains why (Belgian tariffs treat holidays as weekdays) — so the entire holiday module should be deleted or its purpose documented.
12. **[BUG-MEDIUM] `_request_with_retry` doesn't retry on 5xx HTTP.** Only transport-level errors retry; a HA 502 (Supervisor restarting) propagates unchanged via `raise_for_status()`. ([ha_client.py:168-208](../app/ha_client.py#L168-L208))
13. **[BUG-MEDIUM] BMW low-battery check uses EV charger state, not `bmw_*_plug_state`.** A car plugged elsewhere triggers false 21:00 alerts. Blind Hunter #18. ([decision_engine.py:1836-1842](../app/decision_engine.py#L1836-L1842))
14. **[BUG-MEDIUM] EV override='on' doesn't check `ev_done`.** A "Laden" override left on a fully-charged car restarts the OCPP session at peak tariff. Blind Hunter #10. ([decision_engine.py:651-672](../app/decision_engine.py#L651-L672))

The original Top-10 prioritisation needs reshuffling — see §5.

---

## 2. Pass 1 verdicts (summary)

Full per-finding verdicts are in the validator report; the table below is the verdict roll-up. Severity is the **revised** value (drops noted where it changed).

| § | Title (short) | Verdict | Severity (revised) |
|---|---|---|---|
| 2.1 | Summer EV decided before boiler | CONFIRMED | High |
| 2.2 | `/api/override` accepts `solar` for non-EV | CONFIRMED | High |
| 2.3 | `_handle_heaters` reads unset `ovr['right_heater']` | CONFIRMED | Medium |
| 2.4 | Temp sensors default to 20.0 °C | CONFIRMED | Medium |
| 2.5 | `_update_device_state` race on `last_change` | PARTIAL (worse than original) | Medium-High |
| 2.6 | Mixed smoothed/raw in `_handle_pool_heating` | CONFIRMED | Low (was implied medium) |
| 2.7 | `decisions.ev.amps` brittle init | PARTIAL (mostly harmless) | Low |
| 2.8 | Retry may double-resend | CONFIRMED | Medium |
| 2.9 | Boiler timers not reset on peak force-off | CONFIRMED | Medium |
| 3.1 | god module decision_engine.py | CONFIRMED | Medium |
| 3.2 | Per-device boilerplate in execute_decisions | CONFIRMED | Low |
| 3.3 | `app_state` global, no locking | CONFIRMED | Low |
| 3.4 | `_request_with_retry` lifecycle | CONFIRMED | Low |
| 3.5 | BMW car selection duplicated 4× | CONFIRMED (4 places, not 3) | Medium |
| 3.6 | `pending_commands` unbounded | **REFUTED-as-stated** — dict is keyed by entity_id, bounded by entity count | Nit |
| 3.7 | Hourly `location.reload()` workaround | CONFIRMED | Nit |
| 3.8 | Hourly reload re-arms via `DOMContentLoaded` | CONFIRMED | Nit |
| 3.9 | `_get_battery_str` doesn't filter `""` | CONFIRMED | Nit |
| 3.10 | Stale `_handle_ev_winter` comment | CONFIRMED | Nit |
| 3.11 | Magic `25.0` (duplicated at line 1166 too) | CONFIRMED | Nit |
| 3.12 | Moon-phase reference date | CONFIRMED | Nit |
| 3.13 | Override labels scattered (4 sources, not 3) | CONFIRMED | Medium |
| 3.14 | `_apply_config` partial — many sections ignored | CONFIRMED | Medium |
| 3.15 | Add-on rebuild needs temp-public repo | CONFIRMED | High |
| 3.16 | HA token in MEMORY.md | CONFIRMED | Medium |
| 4.1 | `EV solar: …` info log every cycle | CONFIRMED | Medium |
| 4.2 | per-device info lines duplicate plan | CONFIRMED | Low |
| 4.3 | Telemetry line in plan | CONFIRMED | Low |
| 4.4 | BMW lines every cycle 20-22h | CONFIRMED | Low |
| 4.5 | `logging.basicConfig` at import time | CONFIRMED | Low |
| 4.6 | "Could not read limits from HA" spam | CONFIRMED | Low |
| 4.7 | Plan strings mix English + Dutch | CONFIRMED | Nit |
| 4.8 | `Failed to update status helpers` at DEBUG | CONFIRMED | Nit |
| 5.1 | Test footprint inventory | CONFIRMED | n/a |
| 5.2 | Missing tests | CONFIRMED | High (coverage risk) |
| 5.3 | `test_scheduler.py:148` tautology | CONFIRMED | Low |
| 5.4 | `test_decisions.py:122` tautology | CONFIRMED | Low |
| 5.5 | No async event-loop integration test | CONFIRMED | Medium |
| 5.6 | No pytest config | CONFIRMED | Low |
| 5.7 | No CI workflow | CONFIRMED | Medium |
| 5.8 | Coverage reporting unused | CONFIRMED | Low |
| 6.1 | Wide-open CORS | CONFIRMED | Low (mitigated under ingress) |
| 6.2 | `frame-ancestors *` | CONFIRMED | Medium |
| 6.3 | `/api/override`+`/api/limits` unauth'd | CONFIRMED | Medium (CRITICAL outside ingress) |
| 6.4 | Config validation incomplete | CONFIRMED | Low |
| 6.5 | `pool_hist.json` untracked + unread | CONFIRMED | Nit |
| 6.6 | MEMORY.md leaks IPs/password | CONFIRMED | Nit |
| 6.7 | `verify_ssl: false` ships | UNCLEAR (file gitignored) | Low |
| 7.1 | `/api/override` query param `mode` | CONFIRMED | Low |
| 7.2 | `/api/limits` POST, no Pydantic | CONFIRMED | Medium |
| 7.3 | `/api/status` hand-built dict | CONFIRMED | Low |
| 7.4 | `/api/status` 503 via JSONResponse | CONFIRMED | Nit |
| 7.5 | 3 dashboard routes duplicate templates guard | CONFIRMED | Nit |
| 8.1 | `PowerInputs` flat fields | CONFIRMED | Low |
| 8.2 | `AllDeviceStates` mixes per-device + globals | CONFIRMED | Low |
| 8.3 | `EVState` needs helpers | CONFIRMED | Medium |
| 8.4 | `EVState.IEC_OTHER = 5` undefined | CONFIRMED | Low |
| 8.5 | `ACDecision(temp=17)` mancave default | CONFIRMED | Nit |
| 9.1 | `dashboard.js` 1,157 lines | CONFIRMED | Low |
| 9.2 | Auto-reload nukes pending overrides | PARTIAL (40s TTL shrinks window) | Low |
| 9.3 | `consecutiveErrors>2` permanent backoff | PARTIAL (worse — never resets to fast interval) | Medium |
| 9.4 | `alert()` for failed overrides | CONFIRMED | Nit |
| 9.5 | `_batDebugCount` in production | CONFIRMED | Nit |
| 9.6 | Inline `style="…"` in builders | CONFIRMED | Nit |
| 10.1 | Dockerfile clones at build time | CONFIRMED | Medium |
| 10.2 | `run.sh` heredoc Python | CONFIRMED | Nit |
| 10.3 | Orphaned `power-manager.service` | CONFIRMED | Nit |
| 10.4 | `ha-standalone/` undocumented | CONFIRMED | Nit |
| 10.5 | `repository.yaml` quick verify | CONFIRMED | Nit |
| 10.6 | Unpinned deps | CONFIRMED | Medium |

Only one **REFUTED-as-stated**: §3.6 (`pending_commands` unbounded) — the dict is keyed by `entity_id`, so it is bounded by the number of controlled entities (~10). Downgraded to Nit.

Three **PARTIAL** findings worth a closer look:

- **§2.5** is *worse* than Pass 1 implied — the literal `inputs.ev_state == 132` check at [main.py:661](../app/main.py#L661) means the v1.0.52 soft-pause (which makes the charger sit at state 133) bumps `state.last_change` every cycle. The right heater problem (B7) is a separate manifestation of the same anti-pattern.
- **§9.3** is also worse — neither `consecutiveErrors = 0` nor `setInterval(REFRESH_INTERVAL)` reset on the success branch; the dashboard slows permanently after any error burst until the tab is refocused.
- **§2.7** is *better* than Pass 1 implied — the executor doesn't read `decisions.ev.amps` for `pause`/`off`, so the brittleness is mostly latent.

---

## 3. New findings (Pass 2)

Grouped by severity. Source tag: **[BH]** = Blind Hunter, **[V]** = Validator bonus, **[EC]** = PM's edge-case walk.

### 3.1 Critical / High

#### N1 `[BUG-CRITICAL]` Frost protection fails closed when temp sensor is `unavailable` `[BH#5]`
**File:** [app/decision_engine.py:1645-1647](../app/decision_engine.py#L1645-L1647)
**Evidence:**
```python
if ambient_temp is None:
    plan_entries.append('Frost: No temp sensor')
    return {'alerts': alerts, 'pool_pump_decision': pool_pump_decision, 'plan_entries': plan_entries}
```
**Why it matters:** The single sensor gating the only safety-critical feature returns `None` silently in winter. PM responds by emitting a benign-looking plan line and doing nothing. No alert is raised, no fallback (HA weather, time-of-year, last-known-good) is consulted. ZigBee batteries die, mesh nodes drop — this *will* happen on a January morning and the pool pump will freeze.
**Fix sketch:** When `ambient_temp is None` AND `month in {11, 12, 1, 2, 3}`, raise a warning alert and fail-safe by leaving the pump on. Optionally consult an HA outdoor weather entity as fallback.

#### N2 `[BUG-HIGH]` AC overrides accepted by API and engine but never executed `[BH#14]`
**Files:** [main.py:1093-1140](../app/main.py#L1093-L1140), [decision_engine.py:345-348](../app/decision_engine.py#L345-L348), [models.py:163-166](../app/models.py#L163-L166)
**Evidence:** `valid_devices` includes `'ac_living', 'ac_bedroom', 'ac_office', 'ac_mancave'`; `parse_override` populates `ovr['ac_*']`; `_apply_manual_overrides` never reads them; nothing in the engine ever sets `decisions.ac_*.action`; `execute_decisions` has no AC branch.
**Why it matters:** User clicks AC override → 200 OK → input_select flips → nothing happens. Trust in the dashboard evaporates the moment the user notices.
**Fix sketch:** Either remove AC from the override API surface + dashboard (cheapest, honest), or wire up `set_climate` calls in `execute_decisions`. If the AC feature is "planned for summer-cool branch" — gate it behind a feature flag and hide the button until ready.

#### N3 `[BUG-HIGH]` Mobile-app notify-service stripping likely broken `[EC]`
**File:** [app/ha_client.py:335-358](../app/ha_client.py#L335-L358)
**Evidence:** `_extract_notify_service_name` strips the literal prefix `mobile_app_` from any entity_id starting with that string. The configured value `mobile_app_iphone_van_nicolas_2` therefore becomes `iphone_van_nicolas_2`, which is then called as `notify.iphone_van_nicolas_2`.
**Why it matters:** HA's mobile_app integration registers as `notify.mobile_app_<device>`, NOT `notify.<device>`. A `service_not_found` error in HA would be logged at line 332 and the function returns `False` — but `execute_decisions` does not surface that failure to the user. All "low battery" alerts would silently never reach the phone.
**Status:** NEEDS-INVESTIGATION — verify on a live HA whether `notify.iphone_van_nicolas_2` exists (it would only exist if the user has *also* defined a custom notify alias). If not, every mobile alert PM tries to send has been failing for months.
**Fix sketch:** If `entity_id` is bare `mobile_app_<name>`, call `notify.mobile_app_<name>` directly (no prefix strip). Only strip for explicit `notify.<name>` and `mobile_app.<name>` forms.

#### N4 `[BUG-HIGH]` `verify_and_retry_pending_commands` re-issues stale commands across tariff boundaries `[BH#9]`
**File:** [main.py:125-221](../app/main.py#L125-L221)
**Evidence:** When state still doesn't match after `backoff_seconds`, the loop unconditionally calls `turn_on`/`turn_off` for the stored `expected_state`. There is no re-check that the current decision still wants that state.
**Why it matters:** At 06:55 (last super-off-peak minute) PM decides boiler ON; a transient HA glitch swallows the call. At 07:01 (1-minute backoff), tariff is now peak and PM no longer wants the boiler on. The retry fires `turn_on(boiler_switch)` anyway, overriding the engine's current decision. Pending commands are a hidden side-channel that bypasses the decision loop.
**Fix sketch:** Before each retry, re-evaluate `app_state.last_decisions` for that entity. If the desired state has changed, drop the pending command.

#### N5 `[BUG-HIGH]` `_apply_config` silently drops most YAML sections `[BH#2]`
**File:** [app/config.py:306-364](../app/config.py#L306-L364)
**Evidence:** Only `home_assistant`, `polling_interval`, `port`, `max_import.{peak,off_peak,super_off_peak}`, `tariff_prices`, `frost_protection.{enabled,temp_threshold,critical_threshold,notify_entity}`, `bmw_low_battery`, `debug` are applied. Missing: `entities`, `ev`, `boiler`, `heaters`, `pool`, `ac`, `timing`, `summer_*`, `units_p1`, `units_pv`, `enable_notifications`, `frost_protection.{pump_min_power,pump_off_alert_delay}`, `max_import.super_off_peak_winter`.
**Why it matters:** Users editing `config.yaml` get no error and the running engine uses hardcoded defaults — silent misconfiguration. The platinum-grade contract is broken at the configuration boundary.
**Fix sketch:** Replace hand-rolled `_apply_config` with recursive merge (pydantic-settings, or a 20-line `_deep_merge` helper). At minimum, raise on unknown keys.

#### N6 `[BUG-HIGH]` `generate_timetable` drops totals/utilization for the final hour `[BH#6]`
**File:** [app/scheduler.py:585-591](../app/scheduler.py#L585-L591)
**Evidence:**
```python
for entry in timetable:                                  # current_entry NOT yet appended
    entry['total_power'] = sum(entry['devices'].values())
    entry['utilization'] = round(...)
if current_entry:
    timetable.append(current_entry)                      # appended AFTER the loop
```
**Why it matters:** The last hour of the 24-hour timetable always reports `total_power=0` and has no `utilization` key. `dashboard.js:412-423` reads `entry.total_power || 0` — silent zero. Over-limit visualisation will *never* warn for that hour.
**Fix sketch:** Append `current_entry` before the totals loop, or include it in the loop.

#### N7 `[BUG-HIGH]` `heater_right.last_change` never updated — hysteresis disabled `[V-B7, BH#4]`
**File:** [main.py:631-666](../app/main.py#L631-L666), executor at [main.py:594-608](../app/main.py#L594-L608)
**Evidence:** `execute_decisions` dispatches `turn_on(config.entities.heater_right)`, but `_update_device_state` updates only `ev, boiler, pool_pump, pool, heater_table, dishwasher`. `_handle_heaters` calls `can_switch('heater_right', True)`, reading a `last_change` that is permanently 0.0.
**Why it matters:** `can_switch_device` returns `True` whenever `last_change == 0` — so the 2.5 kW right heater has no hysteresis protection at all. Ping-pong is possible during marginal solar conditions.
**Fix sketch:** Add `update_state('heater_right', inputs.heater_right_switch == 'on')` to `_update_device_state`. Together with N8 below this is a one-pass cleanup.

#### N8 `[BUG-HIGH]` `update_state('ev', inputs.ev_state == 132)` ignores all IEC codes and the new PAUSED state `[V-B2, BH#3]`
**File:** [main.py:661](../app/main.py#L661)
**Evidence:** The decision engine treats `ev_charging = ev_state in (EVState.IEC_CHARGING_C2, EVState.CHARGING)` — but `_update_device_state` records `state.on = (ev_state == 132)`. With v1.0.51's `PAUSED=133` and v1.0.52's soft-pause (5A → state 133), the charger now sits at 133 during what PM considers "ON". Every cycle alternating ≥1 cycle of 132 with a cycle of 133 flips `state.on` and bumps `last_change` — the v1.0.52 soft-pause that was supposed to be invisible to hysteresis now triggers it continuously.
**Why it matters:** EV hysteresis is broken whenever soft-pause runs. Min-on / min-off windows fire spuriously.
**Fix sketch:** `update_state('ev', inputs.ev_state in (EVState.IEC_CHARGING_C2, EVState.CHARGING))` — matching `ev_charging`. Better: extract `EVState.is_charging()` classmethod and call it from both places (combines with §8.3 fix).

#### N9 `[BUG-HIGH]` Tariff is silent on holidays — Belgian holiday machinery is dead code `[EC]`
**File:** [app/tariff.py:7-52, 91-92](../app/tariff.py#L7-L52)
**Evidence:** `FIXED_HOLIDAYS`, `easter_date`, `get_belgian_holidays` are defined and tested but never invoked by `get_tariff`. The comment at line 91-92 explains why: *"Belgian electricity tariffs typically do NOT treat holidays as weekends — only actual weekends get the weekend schedule"*.
**Why it matters:** Two failure modes. (a) Dead code is a maintenance burden and a confidence trap for the next reviewer. (b) **If the comment is wrong** — i.e., your specific contract treats some holidays as weekend tariff — the engine silently overcharges by allocating peak limits on a public holiday.
**Severity:** High **if** the supplier contract treats holidays as weekend; Medium if confirmed weekday. NEEDS-INVESTIGATION — check your contract.
**Fix sketch:** Confirm contract terms. If holidays do get weekend treatment, wire `get_belgian_holidays` into `is_weekend`. Otherwise, delete the dead code.

### 3.2 Medium

#### N10 `[BUG]` `get_num` semantic inversion: missing-sensor return depends on default value `[V-B1]`
**File:** [app/ha_client.py:382-390](../app/ha_client.py#L382-L390)
**Evidence:** `return default if default != 0.0 else None` — a caller passing `default=20.0` receives `20.0` on sensor failure (silently faking a value); a caller passing `default=0.0` receives `None`. Garbage values (line 388-390 `try/except`) always return the literal default regardless. Caller cannot distinguish "no reading" from "garbage reading".
**Why it matters:** Root cause of §2.4 (temp defaults to 20°C). Latent risk across every `get_num` call site. Worst-case: `max_import` logic computes available headroom against a fake 0W import.
**Fix sketch:** Always return `None` for missing/unparseable; require callers to explicitly default. Audit all `get_num` callers as part of the fix.

#### N11 `[BUG]` `_request_with_retry` doesn't retry on 5xx HTTP `[EC]`
**File:** [app/ha_client.py:117-208](../app/ha_client.py#L117-L208)
**Evidence:** Retry branches only catch `ServerDisconnectedError`, `ClientConnectorError`, `TimeoutError`, `ClientError`. A successful HTTP response with status 5xx returns from line 166; callers then call `resp.raise_for_status()` which raises `ClientResponseError` — never retried.
**Why it matters:** HA Supervisor restarts produce a brief 502 window. PM treats those as fatal for the current operation, incrementing `consecutive_errors`. Five such events → full reconnect.
**Fix sketch:** Treat status `>=500` as retryable inside `_request_with_retry`. Don't read `response.status` for the success path until after retry consideration.

#### N12 `[BUG]` `asyncio.TimeoutError` branch doesn't reset `self._connected` `[EC]`
**File:** [app/ha_client.py:182-193](../app/ha_client.py#L182-L193)
**Evidence:** Sibling branches (`ServerDisconnectedError`, `ClientConnectorError`, `ClientError`) all set `self._connected = False`. The `TimeoutError` branch does not.
**Why it matters:** Latent footgun. Currently masked by the unconditional `await self.connect()` inside the next retry attempt. If `connect()` is ever made idempotent-by-state-check, this would break.
**Fix sketch:** Reset `self._connected = False` for consistency, or remove the resets from peers and let `connect()` own the lifecycle.

#### N13 `[BUG]` EV override='on' restarts a finished charge session `[BH#10]`
**File:** [app/decision_engine.py:651-672](../app/decision_engine.py#L651-L672)
**Evidence:** `if ovr['ev'] == 'on' and ctx['ev_plugged']:` — no check on `ctx['ev_done']`. A "Laden" override left on after the car reaches 80% (`ev_done=True`) still enters this branch and dispatches `action='on'`, forcing the OCPP/Modbus session back open.
**Why it matters:** Forces re-engagement of a finished session at peak tariff if the user forgot to clear the override.
**Fix sketch:** `if ovr['ev'] == 'on' and ctx['ev_plugged'] and not ctx['ev_done']:`.

#### N14 `[BUG]` `pool_pump.last_change == 0` defeats frost alert delay on boot `[BH#12]`
**File:** [app/decision_engine.py:1659-1660](../app/decision_engine.py#L1659-L1660)
**Evidence:**
```python
pump_off_since = device_state.pool_pump.last_change or now
pump_off_duration = now - pump_off_since
```
**Why it matters:** On fresh boot or after a reload, if the pump is off and it's cold, `pump_off_since = now`, so `pump_off_duration = 0` and the alert delay is reset. No alert during the most dangerous startup window. Worse, after a power-cycle PM has *no historical knowledge* of how long the pump has been off.
**Fix sketch:** Track an explicit `pool_pump_first_seen_off` timestamp separate from on/off transitions. Persist to disk if the boot-window matters.

#### N15 `[BUG]` BMW low-battery alert uses EV charger state instead of `bmw_*_plug_state` `[BH#18]`
**File:** [app/decision_engine.py:1836-1842](../app/decision_engine.py#L1836-L1842)
**Evidence:** `ev_plugged_in = ev_state in (...) or ev_power > 500` — relies on the ABB charger which only knows the currently-active session. A car plugged at a second wallbox (or with an OCPP-crashed session) is treated as "not plugged" → BMW low-battery alert fires.
**Why it matters:** False 21:00 alerts.
**Fix sketch:** Use `inputs.bmw_*_plug_state == 'CONNECTED'` as authoritative per-car plug detection. The scheduler already does this correctly (line 220-225).

#### N16 `[BUG]` `bmw_*_battery >= 80` hard-coded; ignores `bmw_*_target_soc` `[BH#26]`
**File:** [app/decision_engine.py:64-96](../app/decision_engine.py#L64-L96)
**Evidence:** `calculate_ev_hours_needed`:
```python
if car_battery is None or car_battery >= 80:
    return 0.0
kwh_needed = (80 - car_battery) / 100 * car_capacity
```
**Why it matters:** Scheduler reads `inputs.bmw_*_target_soc` (line 236, 244); engine ignores it. A user configuring target=70 for battery longevity still gets scheduled to 80% by the decision engine.
**Fix sketch:** Read `target_soc` consistently across both modules. Combine with §3.5 (BMW car selection deduplication).

#### N17 `[BUG]` Pool grace-timer reset missing on `pool_mode in {'off','on'}` early returns `[V-B6]`
**File:** [app/decision_engine.py:1205-1212](../app/decision_engine.py#L1205-L1212)
**Evidence:** Same family as §2.9 — when override forces pool off/on, the function returns early without resetting `pool_solar_surplus_since`/`pool_importing_since`. Stale timers cause immediate grace-period mis-fire when the override is later released.
**Fix sketch:** Always zero grace timers when a device is explicitly turned off (via tariff, override, or season change).

#### N18 `[BUG]` `cleanup_alert_cooldowns` runs every 30s with 60-minute horizon `[BH#23]`
**File:** [app/main.py:95-112, 423](../app/main.py#L95-L112)
**Evidence:** Logic is correct, but invoked from the decision loop every cycle. Iterates the entire dict to find entries older than 60 minutes.
**Why it matters:** Cheap with ~10 alert keys, wasteful with hundreds during a burst.
**Fix sketch:** Throttle to every N cycles (e.g. once per 5 minutes) via a counter.

#### N19 `[BUG]` Set-climate fan race: pool heat ON runs at high fan for one cycle `[BH#17]`
**File:** [app/main.py:543-576](../app/main.py#L543-L576)
**Evidence:** Pool heat ON is dispatched via `set_climate`; the fan correction runs as a separate statement on the *next* cycle (after HA reports `pool_fan_mode='auto'` post-heat-on).
**Why it matters:** The first 30 seconds of every heat-on session runs at auto fan — the very behaviour the v1.0.58 enforcement was added to prevent.
**Fix sketch:** Chain `set_climate` and `set_fan_mode` in the same dispatch step (await both unconditionally on transition).

#### N20 `[BUG]` `dishwasher_switch` toggled off + override='on' creates infinite re-turn-on loop `[BH#13]`
**File:** [app/main.py:612-617](../app/main.py#L612-L617), [decision_engine.py:1554-1559](../app/decision_engine.py#L1554-L1559)
**Evidence:** When override='on' is set and the user physically turns the dishwasher switch off, every cycle PM produces `decisions.dishwasher.action='on'` and the executor sees `inputs.dishwasher_switch != 'on'` → calls `turn_on`. Loop continues forever, also adding a `pending_command` entry per cycle.
**Why it matters:** Logical inversion of user intent + noisy log/pending queue.
**Fix sketch:** Dispatch dishwasher `turn_on` only when the engine's intent is "newly start", not when releasing a scheduling block.

#### N21 `[BUG]` Slot generation can include partial-past slots `[EC]`
**File:** [app/scheduler.py:184](../app/scheduler.py#L184)
**Evidence:** `current = now.replace(minute=0 if now.minute < 30 else 30, ...)`. If `now=14:25`, the first slot starts at 14:00 (before now).
**Why it matters:** Past slots are included in `deadline` filtering and capacity allocation. For "scheduled hours" estimates, half an hour can be wasted on time that already happened.
**Fix sketch:** Round forward, not backward: start at the *next* half-hour boundary.

#### N22 `[BUG]` `inputs.bmw_*_battery` truthiness check fails at 0% `[EC]`
**File:** [app/scheduler.py:229, 231, 237, 246, 250](../app/scheduler.py#L229)
**Evidence:** `if ix1_plugged and inputs.bmw_ix1_battery:` and similar — a literal `0` (fully discharged) evaluates to False and falls through to the next car.
**Why it matters:** A genuinely-empty car (which most needs charging!) is ignored for scheduling.
**Fix sketch:** `is not None` checks instead of truthiness.

#### N23 `[BUG]` Boiler deadline rollover off-by-minute `[EC]`
**File:** [app/scheduler.py:325-329](../app/scheduler.py#L325-L329)
**Evidence:**
```python
if now.hour >= deadline_hour:
    boiler_deadline += timedelta(days=1)
```
**Why it matters:** If `now=06:30` and `deadline=06:45`, the deadline rolls to tomorrow even though there are 15 minutes left today.
**Fix sketch:** Compare on full datetime, not hour: `if now >= boiler_deadline: ...`.

#### N24 `[SEC]` Standalone deployment exposes unauthenticated device control `[BH#1, BH#31]`
**Files:** [main.py:297-323](../app/main.py#L297-L323), [dashboard.js:7](../dashboard/static/dashboard.js#L7)
**Evidence:** With `allow_origins=["*"]`, `allow_credentials=True`, `X-Frame-Options=ALLOWALL`, `frame-ancestors *`, and no auth — when the standalone deployment is reachable (the dashboard references `gallet.duckdns.org:8081`), every endpoint can be hit cross-origin or via clickjacked iframe. Combined with no CSRF, any web page the user visits while reachable can POST `/api/override/boiler?mode=off` at -10°C.
**Why it matters:** Behind HA ingress this is fine. Outside ingress this is a remote control surface.
**Fix sketch:** Require a shared-secret header outside the ingress context. Strip `allow_origins=["*"]`; whitelist explicit origins. Set `frame-ancestors` to ingress host only.

#### N25 `[BUG]` Decision-loop exception net catches scheduling failures and counts them toward HA reconnect `[BH#16]`
**File:** [app/main.py:343-450](../app/main.py#L343-L450)
**Evidence:** `_get_timetable_data()` and `generate_24h_schedule` can throw on malformed inputs; they sit inside the broad outer `try` that counts against `max_consecutive_errors`. Five scheduling failures → full HA reconnect (5+ min startup delay).
**Why it matters:** A transient parsing bug masquerades as a connection problem.
**Fix sketch:** Wrap scheduling in its own try/except; only count true HA-comms failures toward reconnect.

### 3.3 Low / Nit

#### N26 `[NIT]` Dead config: `tariff_prices`, `enable_notifications`, `summer_cool_threshold`, `summer_target_temp` `[BH#35]`
[config.py:31-37, 258-262](../app/config.py#L31-L37) — loaded but never read.

#### N27 `[NIT]` Three versions to maintain manually `[BH#36]`
`FastAPI(version="1.0.0")` in [main.py:300](../app/main.py#L300), `version: 1.0.59` in [config.yaml](../power-manager-addon/config.yaml#L3), `v=1.0.54` cache-bust in dashboard HTML. Single source of truth in `app/__init__.py`.

#### N28 `[NIT]` Dead `PoolConfig.idle_power` and `active_power` `[BH#34]`
[config.py:60-64](../app/config.py#L60-L64) — zero usages.

#### N29 `[NIT]` `parse_override` substring greediness `[BH#7]`
A custom HA option label containing "aan", "laden", "start", "uit" gets classified as on/off regardless of context. Match canonical labels exactly.

#### N30 `[NIT]` `app_state` non-atomic read by API endpoints `[BH#11]`
The dashboard can read `last_inputs` from cycle N and `last_decisions` from cycle N+1. Snapshot all `last_*` into one dataclass and swap atomically.

#### N31 `[NIT]` `_handle_pool_heating` mixes smoothed/raw values (already §2.6) `[EC]` — same pattern leaks into `_handle_heaters` table-heater branch with `ht_actual_power` vs `pv`. Worth a single-pass cleanup.

#### N32 `[NIT]` `_apply_dishwasher_logic` dead read of `is_exporting` and `p1_return` `[BH#32]`
[decision_engine.py:1507, 1521](../app/decision_engine.py#L1507) — first assignment overwritten unused.

#### N33 `[NIT]` Duplicated `hours_until_super` formula `[V-B3]`
[decision_engine.py:1147 & 1166](../app/decision_engine.py#L1147). Extract a helper.

#### N34 `[NIT]` `entity_map` and `mode_map` rebuilt per `/api/override` request `[V-B4]`
[main.py:1118-1131](../app/main.py#L1118-L1131). Lift to module scope.

#### N35 `[NIT]` Dashboard JS `stateToMode` is a 4th source-of-truth for override labels `[V-B5]`
[dashboard.js:1027-1032](../dashboard/static/dashboard.js#L1027-L1032). Add to the canonical-source-of-truth refactor (§3.13).

#### N36 `[NIT]` `set_climate` discards `temperature` kwarg when `hvac_mode='off'` `[BH#19]`
[ha_client.py:283-297](../app/ha_client.py#L283-L297). Silent contract footgun.

#### N37 `[NIT]` `int = None` parameter typing in `/api/limits` `[BH#20]`
[main.py:1204-1207](../app/main.py#L1204-L1207). Pydantic v2 strict will reject this. Use `Optional[int] = None`.

#### N38 `[NIT]` `is_boiler_full` confirm timer reset by single off cycle `[BH#28]`
[decision_engine.py:186-236](../app/decision_engine.py#L186-L236). ZWave relay flicker resets the 120s confirmation. Require 2+ consecutive off cycles.

#### N39 `[NIT]` "Winter tariff" includes only Nov-Feb, excluding March `[BH#33]`
[tariff.py:55-61](../app/tariff.py#L55-L61). March is still heating season but uses the summer super-off-peak ceiling. If the user wants March in the higher-ceiling cohort, make the boundary configurable.

#### N40 `[NIT]` Dockerfile cache-bust string can drift from `config.yaml` version `[V-B9]`
The v1.0.28→v1.0.40 silent-rebuild incident documented in `MEMORY.md` is the canonical horror story. Add a shell-script gate that fails if `cache-bust-X.Y.Z` ≠ the version in `power-manager-addon/config.yaml`.

#### N41 `[NIT]` `_get_consumers_data` rebuilt per `/api/status` call `[BH#21]`
[main.py:909-1050](../app/main.py#L909-L1050). Cache alongside `last_schedule`.

#### N42 `[NIT]` `ev_solar_active` reason string assumes `bat_soe is not None` `[BH#24]`
[decision_engine.py:993, 1070](../app/decision_engine.py#L993). Reached only when the predicate guarantees `bat_soe is not None` — currently safe; document the invariant.

#### N43 `[NIT]` DST not handled by `datetime.now()` in `get_tariff` `[EC]`
Naive datetime; on the fall-back Sunday, 02:00 occurs twice. Both 02:00s land in super-off-peak by accident. Use timezone-aware datetimes for defensive correctness.

#### N44 `[NIT]` `generate_timetable` reports full-hour power for half-hour devices `[EC]`
A device active in only one of two 30-min slots in an hour shows full-hour power — energy estimates overstated by 2× in those hours.

---

## 4. NEEDS-INVESTIGATION queue

Carried forward from Blind Hunter + new items:

| # | Item | Source |
|---|---|---|
| I1 | Does `notify.mobile_app_<device>` work after the prefix-strip in `_extract_notify_service_name`? Check live HA logs for `service_not_found`. | [EC-N3] |
| I2 | Does the Belgian electricity contract treat any public holiday as weekend tariff? If so, dead-code holiday machinery becomes a real bug. | [EC-N9] |
| I3 | Does the BMW i5/iX1 firmware actually honour amps=5 (sub-IEC-min) as a pause? If not, "pause" still draws ~3.5 kW. | [BH#25] |
| I4 | After `aiohttp.ClientSession.close()` followed by immediate reconnect, can a mid-flight `_request_with_retry` on the half-closed session crash with `ClientConnectorError`? | [BH-N2] |
| I5 | `is_boiler_full` threshold (50W) — does `sensor.storage_boiler_power` actually report ≤50W when full, or does it noise-drift to 60W? Needs telemetry. | [BH-N3] |
| I6 | Does PM ever start `EV solar` in winter? Requires `battery_charging_enough` (battery charging ≥1 kW) which may never happen in winter "preserve" mode. | [BH-N4] |
| I7 | Under HA ingress: does the Supervisor strip the user's auth cookies before forwarding to PM? If so, §6.3/N24 are partially mitigated under ingress but remain critical for standalone. | [BH-N5] |
| I8 | `_apply_summer_logic` calls `_handle_ev` BEFORE `_handle_boiler` (line 1593-1602), inverting winter priority. Intentional or a refactor leftover? Same as §2.1 — confirm it's a bug not a deliberate trade-off. | [BH-N7] |

---

## 5. Updated Top action items

Pass 1's Top-10 still holds in spirit, but priority needs reshuffling given Pass 2 critical finds. Recommended ordering by **risk × ease**.

**Progress so far (as of 2026-05-14):** 8 of 15 landed across `b754322` (v1.0.60) → `2c27fe6` (v1.0.61) → `70825e5` (v1.0.62). All three commits pushed; not yet deployed. See §8 for the CR-1 review that drove the v1.0.62 follow-up fixes.

| # | Action | Refs | Status | Effort |
|---|---|---|---|---|
| 1 | **Fix frost protection sensor-unavailable failure mode** — raise alert + fail-safe pump-on in winter months | N1 | ✅ `b754322` + `70825e5` (Apr/Oct widen, CR-P4) | 1 hour |
| 2 | **Verify mobile notifications actually arrive** (check live HA logs for `service_not_found`). If broken, fix `_extract_notify_service_name`. | N3, I1 | ✅ `b754322` + `70825e5` (dotted-entity fallback, CR-P5) | 30 min check + 1 hr fix |
| 3 | **Remove AC override surface OR wire up AC executor** (decide one) — the dashboard currently lies to the user | N2 | ✅ `b754322` (removed surface). Full dead-code cleanup deferred (see §8.4) | 1-3 hours |
| 4 | **Reverse EV-vs-boiler order in `_apply_summer_logic`** (§2.1) — restores winter priority invariant | §2.1 | ✅ `b754322` | 5 lines |
| 5 | **Harmonise EV charging predicate everywhere** via `EVState.is_charging()` classmethod — closes N7, N8, §2.5, §8.3, §3.5 in one pass | N7, N8, §2.5, §8.3 | ✅ `b754322` + `70825e5` (DN1=A: `is_active_session`, type guard, CR-P2/P6). §3.5 BMW dedup deferred. | 1-2 hours |
| 6 | **Fix `mode_map` for `/api/override` solar mode** | §2.2 | ✅ `2c27fe6` + `70825e5` (tighter tests, CR-P7/P8) | half a screen |
| 7 | **Fix `_apply_config` partial-merge** (recursive merge or fail-on-unknown) | N5, §3.14 | ❌ open | 1-2 hours |
| 8 | **Make `verify_and_retry_pending_commands` re-check current decision before resending** | N4, §2.8 | ✅ `2c27fe6` + `70825e5` (pool mapping + `none`-drop, CR-P1/P3) | 30 min |
| 9 | **Fix `generate_timetable` last-hour bug** | N6 | ✅ `2c27fe6` | 3 lines |
| 10 | **Demote per-cycle `EV solar` info logs to DEBUG; log INFO only on transition** | §4.1, §4.2 | ❌ open | 1 hour |
| 11 | **Tests for the riskiest surfaces:** `_handle_ev` solar state machine, `verify_and_retry_pending_commands`, `is_boiler_full`, `PowerBuffer` | §5.2, §5.5 | ⚠️ partial — `verify_and_retry` covered (7 tests `2c27fe6` + 4 more `70825e5`). `_handle_ev` solar, `is_boiler_full`, `PowerBuffer` still open. | 1-2 days |
| 12 | **Minimal CI: `ruff check` + `pytest` + coverage gate + add-on cache-bust check** | §5.7, §5.8, N40 | ❌ open | 1 day |
| 13 | **Switch add-on deploy to GHCR** (kills the "make repo public" exposure) | §10.1, §3.15 | ❌ open | 1 day |
| 14 | **Pydantic-validate `/api/override` and `/api/limits` payloads** | §7.1, §7.2, §6.3 | ❌ open | 2 hours |
| 15 | **Refactor `decision_engine.py` into a package** (do last — everything else gets easier afterwards) | §3.1, N5 | ❌ open | several days |

Note: items 1-3 are now ahead of "fix mode_map for /api/override solar mode" — they're either safety-critical (frost), trust-critical (notifications, AC overrides), or both.

---

## 6. Updated platinum checklist

Pass 1's §12 still applies; add these rows. Status updated as of `70825e5` (v1.0.62).

| New row | Status | Target |
|---|---|---|
| All EV-charging predicates flow through `EVState` classmethods | ✅ `b754322` + `70825e5` — `is_charging`/`is_plugged`/`is_active_session`/`is_done`; `update_state('ev')` uses `is_active_session` | Single canonical check |
| Grace-period timers (`*_solar_surplus_since`, `*_importing_since`) reset on every device turn-off path | ❌ tariff and override paths leak (boiler §2.9, pool N17 still open) | Audit + assert per device |
| `get_num` callers default to `None` for missing sensors, except numeric configs with intentional defaults | ❌ current default semantics are inverted (N10) | Audit + standardise |
| Mobile-app notification path verified end-to-end with a non-throwing test | ⚠️ unit-test parser coverage in place (`b754322` + `70825e5`), live HA send not exercised in CI | Send a test alert in CI |
| Frost protection has tested fallback when sensor unavailable | ✅ `b754322` + `70825e5` — 10 tests covering Oct–Apr heating season, May–Sep quiet, disabled-override-failsafe | Unit test + alert path |
| AC overrides either executed or removed from API surface | ✅ `b754322` — removed from API + engine. Dead-code cleanup of `PowerInputs.ovr_ac_*` etc. deferred (§8.4) | Decision needed |
| Last-hour totals included in `generate_timetable` | ✅ `2c27fe6` — `current_entry` appended before totals loop | Off-by-one fix |
| Retry path re-checks current decision before resending | ✅ `2c27fe6` + `70825e5` — per-entity action map, `none`-drop, pool-climate `heat` mapping | Lookup + drop-stale |
| Add-on cache-bust gated by version-match check in CI | ❌ (Top-15 #12) | Shell gate |
| EV soft-pause oscillation (132↔133) does not bump `last_change` | ✅ `70825e5` — `is_active_session` covers PAUSED; integration test pins behaviour | DN1=A |
| `heater_right.last_change` actually tracked | ✅ `b754322` — added to `_update_device_state`; tests in `70825e5` | Hysteresis fix |

---

## 7. Methodology notes

- The **Edge Case Hunter** subagent stalled at the 10-minute watchdog after only loading orientation files. Its scope was filled by a targeted edge-case walk over `tariff.py`, `scheduler.py`, `ha_client.py`, and the notify plumbing — narrower than the original brief, so additional edge cases in `_handle_boiler`, `_handle_ev`, `_handle_heaters`, and dashboard polling may still be unmined. A follow-up Edge Case Hunter run with a per-module scoped brief (5 minutes max each) would close that gap if desired.
- Validator + Blind Hunter independently surfaced the same heater_right bug (V-B7 / BH#4) and the same `ev_state == 132` bug (V-B2 / BH#3). Independent cross-confirmation gives both findings extra weight.
- Pass 1 line numbers drifted by 0-1 in most places; significant drift in §3.14 (citation was the validation block at 289-301, the actual `_apply_config` body is at 306-364).

---

*End of Pass 2 review.*

---

## 8. Review of v1.0.60 + v1.0.61 fixes (CR-1)

**Date:** 2026-05-14
**Range:** `ebab7da..HEAD` (commits b754322 + 2c27fe6)
**Method:** Three adversarial layers in parallel — Blind Hunter (diff only), Edge Case Hunter (diff + project read), Acceptance Auditor (diff + this spec).

The diff implements 8 of the Top-15. The CR confirms 6 fixes match the spec cleanly (N1, N3, §2.1, §2.2 code, N4 code, N6) and surfaces 4 new defects introduced by the fixes themselves plus several test-quality gaps.

### 8.1 Deploy blockers (PATCH — must fix before v1.0.60/v1.0.61 ship)

- **[CR-P1] Pool-climate retries always dropped.** `add_pending_command(pool_climate, 'heat')` stores `expected_state='heat'`, but `decisions.pool.action` is always `'on'` or `'off'`, and `_ACTION_TO_STATE['on']='on'`. So `'on' != 'heat'` → `_pending_command_still_wanted` returns False → drops the pending command every cycle. Three-way convergence (BH#3 / Auditor / ECH #1). [`app/main.py:125-171`](../app/main.py#L125-L171)
- **[CR-P2] EVState soft-pause integration fails the regression it claims to fix.** `update_state('ev', EVState.is_charging(...))` returns True for state 132 and False for 133. Soft-pause oscillation 132↔133 still flips `state.on` every cycle and bumps `last_change`. The unit test `test_paused_is_not_charging` pins helper semantics correctly but no integration test catches the oscillation. (BH#7 / Auditor / ECH #5 indirectly.) [`app/main.py:725`](../app/main.py#L725)
- **[CR-P3] Dishwasher `action='none'` fights its own engine.** During peak, engine emits `action='none'` ("waiting for cheap rate"). `_ACTION_TO_STATE['none']=None` → helper returns `None` → retry loop keeps resending `turn_on`. The retry overrides the engine's waiting intent. (ECH #8.) [`app/main.py:165-171`](../app/main.py#L165-L171)
- **[CR-P4] Frost season excludes April.** `(11,12,1,2,3)` is too narrow — Belgian late frost is real ("Ice Saints" mid-May). April sensor failure leaves pump unprotected. (ECH #6.) [`app/decision_engine.py:1645`](../app/decision_engine.py#L1645)
- **[CR-P5] `_extract_notify_service_name` dropped the "unknown dotted entity" fallback.** Pre-fix code returned the last `.`-segment of any unknown dotted form. New code returns the literal value, which then becomes an invalid HA service name. Tests don't catch this case. (BH#5.) [`app/ha_client.py:335-372`](../app/ha_client.py#L335-L372)

### 8.2 Test quality (PATCH — fix before v1.0.61 ships)

- **[CR-P6] `EVState.is_charging("132")` silently returns False.** No type guard on the classmethods; non-int input is a silent footgun. (ECH #5.) [`app/models.py:34-55`](../app/models.py#L34-L55)
- **[CR-P7] `test_solar_rejected_for_non_ev_with_400` permissive `or` assertion.** `assert "solar" not in detail or "ev" in detail` passes for shapes that don't pin the contract. (Auditor.) [`tests/test_override_solar_mode.py:33`](../tests/test_override_solar_mode.py#L33)
- **[CR-P8] `test_known_pair_does_not_400_on_validation` asserts `!= 400`.** Passes on 500 (HA not wired in test); doesn't actually verify the (device,mode) is accepted. (Auditor.) [`tests/test_override_solar_mode.py:60-62`](../tests/test_override_solar_mode.py#L60)
- **[CR-P9] Heater_right tracking has no test.** N7 is unpinned at the call site. (Auditor.) [`app/main.py:725`](../app/main.py#L725)
- **[CR-P10] Soft-pause oscillation has no integration test.** Even if CR-P2 is fixed, no test pins "132↔133 across 2 cycles leaves `last_change` unchanged". (BH#7 / Auditor.) [`app/main.py:725`](../app/main.py#L725)
- **[CR-P11] Pool retry path has no test.** `_ACTION_TO_STATE['heat']` is unreached by any test. (ECH §3.1.) [`tests/test_retry_decision_check.py`](../tests/test_retry_decision_check.py)

### 8.3 Decisions needed (DN — Galletn input required)

- **[CR-DN1] `update_state` / hysteresis: narrow predicate or structural fix?** The soft-pause oscillation is a *symptom* of the broader §2.5 race (any external state change bumps `last_change` for any device — boiler thermostat trip, heater_right manual toggle, etc.). Two paths to fix CR-P2:
  - **(A) Narrow:** swap the EV predicate to `is_active_session` (or similar that includes PAUSED). Closes the soft-pause oscillation. Doesn't address other devices' external-flip races.
  - **(B) Structural:** only bump `last_change` when `name in confirmed_states` (i.e., PM issued the call). Fixes §2.5 for all devices in one shot. Bigger blast radius — could affect behaviour everywhere hysteresis is read.

### 8.4 Defer (real but out of scope for this batch)

- **§2.5 broader (boiler thermostat trip)** — same family as CR-DN1; only addressed if DN1 picks B.
- **§3.5 BMW car selection 4× dedup** — diff touched one of the four sites but didn't dedup. Follow-up story.
- **§2.8 retry double-send compliance race** — ECH #3 confirms my N4 fix only catches engine-flipped-against, not the original §2.8 case. Pre-existing.
- **N2 dashboard tile cleanup + AC dead code** — per Galletn's earlier "remove surface" choice. Full AC cleanup (PowerInputs.ovr_ac_*, Decisions.ac_*, EntitiesConfig.ovr_ac_*, ha_client AC reads, dashboard consumers list) is bigger. Auditor lists each location.
- **Timezone in `datetime.fromtimestamp`** — pre-existing pattern; HA add-on TZ usually CET so impact bounded.
- **§2.6 pool smoothed/raw mixing** — pre-existing; my summer-ordering swap exacerbates slightly but doesn't introduce.

### 8.5 Dismissed (noise / false positives)

- **BH#1** "datetime not imported" — verified imported at `decision_engine.py:2`. False positive.
- **BH#8** "summer ordering test tautological" — disagreed by Auditor; the `boiler_will_use == 2500` assertion would have failed pre-fix. Real bug-pin.
- **BH#10–12, 14, 15, 19, 22–26** — design preferences, redundant guards, over-engineering concerns.
- **ECH #4** "`'adjust'` mis-classification" — analyzed; the behaviour is actually correct (adjust → on; turn_off pending → drop is intended).
- **ECH #5 EV-charging detection inconsistency** — same defect as CR-P2; covered.

### 8.6 Summary

**6 deploy blockers (CR-P1 to CR-P5 plus one decision DN1), 6 test-quality items (CR-P6 to CR-P11), and several deferred follow-ups.**

The CR found that **2 of the 8 fixes have real defects the tests missed** — pool retry (CR-P1) and soft-pause integration (CR-P2). Both are regressions introduced by the fixes themselves. Worth running CR before deploying.

### 8.7 Resolution (v1.0.62 / commit `70825e5`)

DN1 decided: **(A) Narrow — EV uses `is_active_session`.** The broader §2.5 race for other devices stays open as a future story.

All 11 CR-P items addressed in v1.0.62:

| Item | Status | Notes |
|---|---|---|
| CR-P1 — Pool retry mapping | ✅ Resolved | Per-entity `_ACTION_TO_*_STATE` maps so pool 'heat' ≡ engine 'on'. Two regression tests added. |
| CR-P2 — EV soft-pause oscillation | ✅ Resolved | `update_state('ev', ...)` now uses `is_active_session` (covers PAUSED). Integration test in `test_ev_soft_pause_hysteresis.py`. |
| CR-P3 — Dishwasher `action='none'` retry loop | ✅ Resolved | Contract changed: `'none'` now drops pending command (was: keep retrying). Existing boiler-`none` test updated to match. |
| CR-P4 — Frost season too narrow | ✅ Resolved | Widened to {10,11,12,1,2,3,4}. April + October tests added. |
| CR-P5 — Notify resolver lost dotted fallback | ✅ Resolved | `entity_id.rsplit('.', 1)[-1]` fallback restored. Two tests added. |
| CR-P6 — `EVState` accepts string input | ✅ Resolved | `_coerce()` helper handles `"132"`, `None`, garbage. |
| CR-P7 — Permissive `or` assertion | ✅ Resolved | Replaced with explicit detail-body checks naming the device + auto/on/off allowlist. |
| CR-P8 — `!= 400` passes on 500 | ✅ Resolved | Tightened to `status in (200, 500)` so a real validation regression would surface. |
| CR-P9 — `heater_right` tracking has no test | ✅ Resolved | 3 tests pin off→on, on→off, no-bump-on-unchanged. |
| CR-P10 — Soft-pause integration test missing | ✅ Resolved | New test file `test_ev_soft_pause_hysteresis.py` with 4 oscillation/transition tests. |
| CR-P11 — Pool retry path no test | ✅ Resolved | Two tests in `test_retry_decision_check.py` (kept-when-on, dropped-when-off). |

**Test count:** 166 (pre-v1.0.60) → 228 (post-CR-1) → **235** (post-v1.0.62). +69 net.

---

*End of CR-1.*
