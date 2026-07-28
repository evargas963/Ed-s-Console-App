# BRUTAL ADVERSARIAL AUDIT v6 — 2026-07-27 ~22:55 CT

**HEAD:** `618a3780` (RC-31) atop `163b1ed7` (RC-58/101) atop `2c214142`  
**Uncommitted (Claude mid-flight):** `static/index.html` + `tests/test_client_spot_single_faucet_v1.py` (RC-102 WIP — levels_stale + edLiveSpot→consoleSpot)  
**Verdict:** **SCOPED CREDIT on honest half-fixes · GLOBAL REJECT on “finished” · RC-31 CLOSE is FAKE_CLOSE (reopen)**

---

## Headline

Claude moved fast and was honest about RC-58 staying OPEN for re-validation and about thin coach sample. That is not “finished.” The RC-31 **CLOSED** stamp is the failure this audit exists to catch: the loader is gated, the TCN window seam is gated, but **HAR / Kalman / cross-asset / quantile still feed overnight gap returns into features** — the exact defect class the RC-31 row named.

**Independent confirm:** [RC-31/58 audit](d862febf-4296-432e-a5bd-bd2030e7740c) — same FAKE_CLOSE grade; adds full importer table (12+/14 paths lack boundary exclusion) and session-blind `_load_labeled_rows`.

Same-turn poison proof:

```
overnight_r2 = log(102.0/100.1)^2 ≈ 0.00035356
har_features(closes)[3,0] == overnight_r2   → True
```

`research/har_rv_eval_v1/runner.py::har_features` uses `np.diff` with **no** session-boundary exclusion. RC-31’s own text named HAR as affected. Closing after fixing only TCN `_build_xy` is a **scope bait-and-switch**.

---

## Same-turn evidence

| Check | Result |
|---|---|
| pytest `test_rc31_session_universe_v1` + `test_study_calendar_gates_v1` | **6 passed** |
| RC table OPEN | **RC-58 OPEN** (deliberate); **RC-55 REMEDIATED**; RC-31 marked **CLOSED** |
| HAR overnight in feature | **PROVEN** (`f[3,0] == overnight_r2`) |
| Kalman own `_build_xy` | **no** boundary exclude — filter runs on full RTH close series incl. gap jumps |
| Cross-asset `spy_rets = np.diff(...)` | **no** boundary exclude |
| RC-58 seven loaders | `is_trading_day_et` present (source lock + 2 behavioural tests) |
| RTH lock `_RTH_MARKET_READ` | still **no** `price_bars_1m` (blind class from Wave-2 W2-C8) |
| Coach artifact git-tracked | **True** (`reports/terrain_backtest_latest.json`) — RC-101 credit |
| `console_v2_shell.html` | still tracked (17.8 KB) |
| `verification/operator_trust_backtrack.py` | still present |
| `adaptive_shadow_v2_calibration.json` | still **1.84 MB** |
| `_build_section*_inventory.py` | **13** remain |
| Uncommitted RC-102 | levels_stale rendered; `edLiveSpot` → `consoleSpot(null)` — **partial** dual-door fix; not committed |

---

## Grades (this turn)

| Claim | Grade |
|---|---|
| RC-31 “overnight cannot enter a window” (TCN `_build_xy`) | **FIXED(verified)** for TCN path + seam test |
| RC-31 family CLOSED (HAR/Kalman/quantile/… + labels) | **FAKE_CLOSE** — reopen; only TCN `_build_xy` excludes gaps; `_load_labeled_rows` still session-blind |
| RC-58 loader gates | **PARTIAL** — gates landed; row correctly stays OPEN for re-validation |
| RC-101 coach committable | **FIXED(verified)** — relative exe + artifacts tracked |
| RC-102 levels_stale + spot door (WIP) | **PARTIAL / theater** — uncommitted; `edLiveSpot` delegates but multi-writers remain; `levels_stale` only on hidden `#terrain-view`, not visible `#cv2` trust/footer ([money-path faucets](22e753a5-43fb-4985-98ab-19c7fb7eb2da)) |
| Dead-code Wave A / landfill clear | **OUTSTANDING** — shell, verification JSON, 13 section inventories |
| Wave-1 money-path dual books / plane | **OUTSTANDING** (re-audit agents in flight) |
| Pristine / finished | **REJECT** |

---

## Hard findings

### F1 — RC-31 FAKE_CLOSE (blocking)
- Fixed: `_load_closes(session="rth")` + TCN `_build_xy` day-boundary exclude (incl. lo-1 seam).
- **Not fixed (importer audit):** HAR / Kalman / quantile / survival / cross-asset / har_micro / regime_har / vol_regime_har / interaction / abstention / cost_aware — all use HAR or own `np.diff` **without** boundary exclusion. “14 importers verified importing” ≠ feature-path fixed.
- `_load_labeled_rows` still session-blind (EH/holiday decision stamps can still score).
- Test suite only exercises TCN `_build_xy`.
- **Directive:** REOPEN RC-31. Ship one shared `session_safe_returns` / boundary helper used by every bar-path feature builder; gate labels too. Test must fail if HAR `mean_last(1)` equals a weekend gap r².

### F2 — RC-58 honest OPEN, lock still soft
- Seven loaders gated — credit.
- Remaining half (re-validate wall-hold / card conclusions) **not done** — do not cite those KPIs.
- `_RTH_MARKET_READ` still omits `price_bars_1m` → lock can stay green while the defect class lives (W2-C8).
- Pin studies still in `_RTH_GRANDFATHERED` with weekday-only history (RC-55 REMEDIATED theater).

### F3 — RC-102 WIP is rename theater (operator-visible still OUTSTANDING)
Independent confirm: [money-path faucets](22e753a5-43fb-4985-98ab-19c7fb7eb2da).
- Uncommitted: `edLiveSpot` → `consoleSpot(null)`; `#tv-trust` reads `levels_stale`.
- **Hidden surface:** `#terrain-view` is `display:none` in terrain mode; visible `#cv2-kl-trust` / footer still ignore staleness (`trusted = confidence === TRUSTED` only).
- Multi-writers still live: `paintSpotDisplays`, EdCv2 `cv2-hd-px`, `edPaintSpot` → `#tv-px`, `sb-spot` side paths; gamma bars still use raw `t.spot`.
- String tests cannot fail multi-writer paint. Do not accept as single-faucet FIXED.

### F3b — Wave-1 money-path CRITICAL still OUTSTANDING (re-proven this turn)
| # | Item | Evidence |
|---|---|---|
| 1 | Dual wall/flip books (expiry analytics vs full-chain terrain) | `server.py` analytics vs `_terrain_refresh_one` |
| 2 | Math spot ≠ display spot (`resolve_spot` then plane merge) | `_fetch_state` + `merge_into_state` |
| 3 | Auth-degraded carry-forward never `record_quote` into plane | `_stale_fast_quote_carried_forward` early returns |
| 4 | `merge_into_state` drops `quote_source_detail` | `live_market_plane.py` |
| 5 | ±5% TRUSTED span bar still weak | `GAMMA_FLIP_MIN_SPAN_PCT = 0.05` |

### F4 — Landfill still fat (independent confirm)
[dead-code bloat](bc0862ea-a50f-43ee-85f6-d971dc1b5b33): RC-100 Wave A deleted 8; **not** pristine.
- **DELETE-NOW:** `adaptive_shadow_v2_calibration.json` (1.84MB), ablation bak/dryrun (~3.9MB), `design_mockups/`, `console_v2_shell.html`, `operator_trust_backtrack.py`, `mutation_raw/*`, `tests/archive/legacy_section_audits_v1/`, `_pipeline_scripts/step3_benchmark_AAPL_5c_postFix.ps1`
- **13** `_build_section*_inventory.py` — 0 importers, all ledger-blocked by `snapshot_column_cull_ledger.json` — burn ledger + files together (not blind-delete)
- `verify_dead_code_orphans_v1.py` is **report-only** (always exit 0, unwired) — stop calling it a lock until it can fail CI

### F5 — Operator NOW ignored in Claude’s finish narrative
- `ACTIVE_PROGRAM.md` **LP-01** is NEXT (liquidity/value levels). Claude’s latest commits are lock-set / RC hygiene — fine if operator asked, but **not** LP-01 and **not** pristine.

---

## Credit (do not erase)

1. RC-31 TCN seam test (lo-1) — real engineering; caught a real bug class.
2. RC-58 kept OPEN for re-validation — correct honesty.
3. RC-101 fixed the credential-path self-own instead of fighting the hook.
4. RC-102 WIP finally reads `levels_stale` (Wave-1 F4 from v5).

---

## Claude fix directives (ordered)

1. **REOPEN RC-31** — shared `session_safe_returns(ends, closes)` used by HAR/Kalman/quantile/cross-asset; behavioural test that HAR feature ≠ overnight r².
2. **Extend `_RTH_MARKET_READ` to `price_bars_1m`** (or split measurement vs loader locks) — close W2-C8 blind green.
3. **Finish RC-102 for real:** wire `levels_stale` into **visible** `#cv2` trust/footer (not only hidden `#terrain-view`); collapse paint clocks to one writer; gamma bars must use `consoleSpot`; then commit.
4. **Landfill deletes** from F4 P0 list; burn 13 section inventories **with** cull-ledger rows; wire orphan verifier to non-zero exit or drop the “mechanism” claim.
5. **Do not claim finished** until OPEN = {RC-58 revalidation, LP-01, Wave-1 P0–P2} are addressed or explicitly deferred by operator.
6. **LP-01** remains operator NEXT for product work — lock hygiene is not a substitute.

---

## Parallel agents

- RC-31/58 deep slice — **merged** ([RC-31/58 audit](d862febf-4296-432e-a5bd-bd2030e7740c)): FAKE_CLOSE confirmed; pin weekday-only + `_RTH_MARKET_READ` blind reaffirmed  
- Money-path faucet slice — **merged** ([money-path faucets](22e753a5-43fb-4985-98ab-19c7fb7eb2da)): dual books / plane / auth strip OUTSTANDING; RC-102 = theater on visible console  
- Dead-code / bloat slice — **merged** ([dead-code bloat](bc0862ea-a50f-43ee-85f6-d971dc1b5b33)): Wave-2 delete list still fully present; orphan tool is measurement theater

---

## Verdict line

`CLAIM: RC-31 closed stamp is incomplete (HAR overnight poison proven) · DONE: v6 audit artifact · NEXT: Claude must reopen RC-31 + landfill · BLOCKER: global finished / pristine`
