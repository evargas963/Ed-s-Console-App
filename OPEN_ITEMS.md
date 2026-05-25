> **Classification:** Operational Ledger | **Scope:** Canonical open-work registry; closes require SHA.

# Open items — horizon, stack, UI consistency

**Rule:** Items stay **open** until there is a merged/code-verified resolution (not just “planned”).  
**Last reviewed:** 2026-05-25 — Schwab work bound by [`CLAUDE.md`](CLAUDE.md) (Schwab law) + [`AGENTS.md`](AGENTS.md) §Fix everything we touch / §Active agent posture (always-on agent rules). **D17 closure scope amended @ `25cb2e3`:** `unreviewed_count == 0` on the **scoped** register (gitignore-aware walk + `SCAN_SCOPE_EXCLUDE_PREFIXES`) — not the legacy full-disk walk. The prior three-PR gate (governance pin → CI diff-emission gate → full-tree scanner regen) is superseded for closure admissibility; CI diff-emission gate (`schwab-csv-first.yml`) remains in force for new market-fact sites per PR. Scoped register at local tip: `closure_admissible: true` (174,459 rows, 34 REPLACED, 0 UNREVIEWED, 0 bare GOVERNED_EXCEPTION) — wire-true REPLACED still concentrated in `market_context.py` (16) + `server.py` (18); other product files with Schwab wire reads await slice-line reconciliation.

---

## NEXT — after current project (operator priority #1)

**Gate:** Activate when Layer 5 / Pilot 1 Schwab walk + stack sign-off queue is closed (or operator says **go live-ui latency**). Do not defer behind new feature work.

**Active program (2026-05-24):** **Governance consolidation Phases 0–4 complete** @ `ed9f882` (Phase 3 gate closed, dual-agent re-audit). **Concurrent epic:** Training Pipeline PR5–PR7 (not started).

- [x] **GOVERNANCE-CONSOLIDATION — Phase 0** @ `dbb57c9` — Baseline snapshot, CI path inventory, do-not-rename list (114 paths), rule-source classification (38 rows / 35 memory files), memory gap read (`feedback_no_new_md_deliverables.md`). Auto-load tests documented pending post-1a. **Operator decisions:** defaults confirmed 2026-05-23.

- [x] **GOVERNANCE-CONSOLIDATION — Phase 1a** @ `6357c4b` — `AGENTS.md`, `ACTIVE_PROGRAM.md`, `.cursor/rules/00-always.mdc`, `tests/test_governance_consolidation.py` (8 passed). **Gate:** re-run `.mdc` always-apply test in fresh Cursor session.

- [x] **GOVERNANCE-CONSOLIDATION — Phase 1b** @ `8bc2bdb` — AGENT_SELF_GOVERNANCE 69 lines (grep-free #17/#20/#22); CLAUDE scope+V4 meta+gatekeeping rules; PROMOTION_POLICY historical; tests 14/14 on governance slice.

- [x] **GOVERNANCE-CONSOLIDATION — Phase 1c** @ `b9153f2` — thin `MEMORY.md`, 34 files in `governance/archive/2026-Q2/memory_archive/`, rule-number → topic-name rewrites, `tools/import_memory_archive_phase1c.py`, `test_memory_archive_has_all_source_files` (14/14 governance tests).

- [x] **GOVERNANCE-CONSOLIDATION — Phase 2** @ `8e79ea2` — 286 MDs classified; 250 scope headers added; `tools/build_phase2_md_classification.py`; spreadsheet `governance/consolidation/phase2/md_classification.csv`.

- [x] **GOVERNANCE-CONSOLIDATION — Phase 3 decision artifacts** @ `4018f41` — `governance/consolidation/phase3/` (baseline delta, duplicate MD report, protected py audit, worktree notes); token rotation note in TRAINING_AND_MAINTENANCE; schwab_field_inventory quarterly refresh note. **Not the Phase 3 execution gate** (see next row).

- [x] **GOVERNANCE-CONSOLIDATION — Phase 3 execution** @ `ed9f882` — **3b** 14 archives + stubs @ `10ca07d`; **3c** no-delete decisions; **3d** import-graph audit (no root `.py` moves, operator sign-off in `baseline_delta.json`); **3e** 9 Claude worktrees pruned (~2.43 GB freed); **3f** LFS shim audit. **Gate closed** 2026-05-24 (dual-agent re-audit).

- [x] **GOVERNANCE-CONSOLIDATION — Phase 4** @ `6246920` — `.pre-commit-config.yaml`, `tools/check_no_grep_subprocess.py`, governance tests **18/18** on slice.

- [ ] **GOVERNANCE-CONSOLIDATION — DRIFT-INCIDENT-RATE** — non-blocking quarterly metric; track agent rule violations post-consolidation.

- [x] **GOVERNANCE-CONSOLIDATION — PYTEST-TO-CI** @ `46a2f37` — `.github/workflows/pytest.yml` runs `npm run test:all` (Playwright E2E + full pytest) on push/PR; `requirements.txt` for CI runtime deps; pre-commit green on `--all-files` (forbidden-phrases drift, AGENTS/CLAUDE allowlist, prereg hash, FIND-LIVEUI-6 e2e SSE isolation).

- [ ] **TRAINING-HOST-PREFLIP-E2E** — Operator preflip harness verify on real candidate roots (not git-gated). **Host:** before `ED_SCHEDULER_AUTO_PROMOTE=1`.

- [ ] **TRAINING-HOST-LIVE-RELOAD** — Promote + `POST /api/internal/reload_models` → `live_reload.succeeded: true` on launch console URL.

**Training pipeline (background):** PR1–PR4.1 **pushed to origin** (see GitHub backup table). PR5–PR7 not started. **Host:** keep `ED_SCHEDULER_AUTO_PROMOTE=0` until preflip + live reload rows close.

- [x] **TRAINING-PIPELINE-PUSH-REVIEW** @ push 2026-05-21 — Full branch `1c0ec96..tip` pushed to `origin/feature/institutional-key-levels` (133 commits). **Verification at push:** pytest **2619 passed**; SPY/QQQ/IWM compliant; mega4 **821 rows / 88 files**; writer inventory post-PR4 refresh. **Held on host (not git):** `ED_SCHEDULER_AUTO_PROMOTE=1`, strict core freshness flip, preflip e2e on automation host.

- [x] **TRAINING-PIPELINE-PR1-PUSH-REVIEW** @ `5886ca0` — pushed with umbrella 2026-05-21.

- [x] **TRAINING-PIPELINE-PR2-PUSH-REVIEW** @ `4375c58` — pushed with umbrella 2026-05-21.

- [x] **TRAINING-PIPELINE-PR3-PUSH-REVIEW** @ `2d8208e` — pushed with umbrella 2026-05-21.

- [x] **TRAINING-PIPELINE-PR4-PUSH-REVIEW** @ `51e27ce` — pushed with umbrella 2026-05-21.

- [x] **TRAINING-PIPELINE-PR4.1-PUSH-REVIEW** @ `8feab6b` — pushed with umbrella 2026-05-21. **Host-enable still deferred:** preflip e2e + `live_reload.succeeded: true` before `ED_SCHEDULER_AUTO_PROMOTE=1`.

- [ ] **FEATURE-OHLCVA-AMOUNT** — Bar-level **dollar turnover** (Amount = locked price leg × volume; USD notional — distinct from point-distance fields in `db.py`). **Wire today:** Schwab `pricehistory.candles.*` is OHLCV only (no Amount leaf); both legs already persist — `price_bars_1m` (open/high/low/close/volume via `upsert_1m_bars` / `tools/historical_backfill_enrolled_1m_v1.py`) and snapshots (`spot`, `candle_open`…`candle_close`, `candle_volume`; typical-price pattern in `backfill_snapshot_derived.py`). **Not stored yet** — no `amount` / `amount_usd` column. **Sequence before training promotion:** (1) lock price leg (close vs OHLC typical vs bar VWAP), session scope (RTH vs extended), units, fail-closed NULL when volume or price missing; Schwab V4 disposition for derived field (single canonical derivation or operator O-NN); (2) persist + backfill script; (3) normalized modeling variants (rolling z-score, vs ADV-notional, session cumulative); (4) ablation under **STACK-WIRE-6-EDGE-MEASUREMENT-FRAMEWORK** vs raw volume, `anchor.vwap_*`, `liquidity.absorption_score` / `liquidity.continuation_score`; (5) promote to `features/canonical_contract.py` only if ablation shows lift — `[REAL-GATE: training-skew]` until retrain + preflip. **Revisit with:** Training PR5–PR7 + `go stack-wire-6-edge`.

- [ ] **FEATURE-PER-TICKER-GEX** — **Per-underlying dealer gamma exposure** from **that ticker's own Schwab options chain** (not a universal SPX column). **Live today (partial):** `math_exposure_core.compute_exposures_by_strike` → `aggregate_net_gex` / `gex_regime_label`; surfaced as `kl_net_gex`, `kl_net_gex_regime`, `kl_gamma_flip`, zone/DPI/hedging-flow — all keyed to the **selected trade ticker** chain in `server.py` (default SPY). **Training today:** `structure.net_gamma` in MVP only; full GEX family not persisted as snapshot columns nor in `features/canonical_contract.py`. **Design rule:** chain identity = snapshot ticker (SPY→SPY chain, AAPL→AAPL chain); index cross-asset GEX (e.g. `$SPX` context while trading SPY) is optional **second-layer** ablation, not the default. **Chain-quality gate:** fail-closed NULL when OI thin, greeks missing (`-999` sentinel), or truncated chain — omit illiquid names from training roster. **Candidate features (same primitive, per ticker):** `gex_level` (aggregate net GEX$), `gex_regime` (pos/neg/neutral), `gex_zero_distance` (spot vs gamma flip / pin). **Do not fork** — extend `math_exposure_core` / `math_levels` parameterized by chain identity; no parallel `compute_gex_features()` in `market_state.py`. **Dealer-sign convention** requires operator O-NN or contract note (customer OI × gamma assumption). **Sequence:** (1) lock expiry window (0DTE vs selected expiry), dollar GEX formula, NULL rules; (2) persist on snapshots + replay parity; (3) ablation vs existing zone / `structure.net_gamma` / key levels — strongest on **0DTE / short-DTE index ETFs** (SPY/QQQ/IWM), per-name where chain passes quality gate; (4) promote to canonical contract per horizon/product class only if lift — `[REAL-GATE: training-skew]`. **Revisit with:** Training PR5–PR7 + `go stack-wire-6-edge`.

- [x] **PROC-MISSED-FIX-S2A-MEMO-ONLY-DRIFT** @ `c53df01` — `governance/SCHWAB_V4_REVIEW_MEMOS/live_market_plane.py.md` S2a originally drafted as `code edit: proposed` + memo-only handoff (Class A bundling rule violation); caught by operator after handoff; fix landed @ `e147097` (`live_market_plane.py` BID/ASK fallback removal + paired test); memo appendix corrected @ this SHA (S2a closed @ `e147097` line replaces stale "flagged for follow-on"). **Prevention:** [AGENTS.md §Fix everything we touch](AGENTS.md#fix-everything-we-touch) + [§Self-governance quality loop](AGENTS.md#self-governance-quality-loop) + `tools/check_fix_everything_we_touch.py` (V4 memo with actionable code edit blocks staged-py absence; commit-msg guard blocks memo-only-without-code / audit-without-fix language). **Closed:** checker lock @ `c53df01`; memo appendix @ this SHA.

- [x] **PROC-MISSED-FIX-BIDSIZE-NON-CANONICAL-STREAM-KEY** @ `c53df01` — `order_flow_engine.py:251` `_latest_quote_snapshot` mixed canonical streaming leaves (`BID_SIZE` / `BID_PRICE` per `schwab_field_dictionary.csv` L2338–2339) with REST-style camelCase fallback `item.get("bidSize")` on streaming `content.*` items; caught by operator cone sweep; fix @ `c53df01` (canonical leaves only — `BID_SIZE` / `ASK_SIZE` / `BID_PRICE` / `ASK_PRICE`; paired test `tests/test_order_flow_schwab_first.py`). **Prevention:** [AGENTS.md §Fix everything we touch](AGENTS.md#fix-everything-we-touch) + `tools/check_fix_everything_we_touch.py`. **Cone sweep closed:** `live_market_plane.py`, `order_flow_live_state.py`, `order_flow_engine.py`, `order_flow_streaming.py` — full Read + gatekeeper verify; no REST-shape keys on streaming `content.*` (see **VERIFY-OF-STREAM-CONE** row).

- [x] **VERIFY-OF-STREAM-CONE** @ `d7d7ebf` — Follow-on from PROC-MISSED-FIX-BIDSIZE: full end-to-end Read of `live_market_plane.py`, `order_flow_live_state.py`, `order_flow_engine.py`, `order_flow_streaming.py`; streaming paths use canonical `BID_*`/`ASK_*`/`LAST_*` leaves only; REST camelCase (`bidSize`, `bidPrice`) confined to REST-shaped `quote`/`extended`/`underlying` dicts. **Closed:** verification + live_decision_bundle walk @ this SHA; gatekeeper tests `test_live_decision_bundle_memo_gatekeeper_section_passes`.

- [x] **PROC-MISSED-FIX-GATEKEEPER-CSV-SPOTCHECK** @ `977e706` — `bayesian_fusion.py` memo @ `a7d4622` signed off after hand-picked bid/ask keyword scan instead of full `schwab_field_dictionary.csv` AST cross-check; caught by operator challenge; independent cross-check found 11 lexical homonyms (high/low/volatility — confidence tiers + `__main__` mock), zero wire reads. **Prevention:** `tools/check_schwab_csv_first.py --gatekeeper-crosscheck` + mandatory memo `## Gatekeeper CSV cross-check` section; wired into `check_fix_everything_we_touch` pre-commit; retroactive `bayesian_fusion.py.md` appendix (count 11). **Closed:** checker lock + memo appendix @ `977e706`; tests `tests/test_check_schwab_csv_first.py::test_bayesian_fusion_memo_gatekeeper_section_passes`.

- [x] **PROC-MISSED-FIX-ACCESSIBLE-INVENTORY-ZERO-REF-CLAIM** @ `92955be` — Agent claimed `schwab_full_accessible_field_inventory.py` had zero repo references and was safe single-slice delete; operator enumerated **10 referrers** before destruction (4 active `tools/` allowlists including `track_a_module_docstring_nmd_pass.py`, 2 governance register mirrors, 3 historical audit JSONs, 1 archived memory). **Item 6 reclassified:** multi-file cone closure (file + 4 tools + 2 governance mirrors, same commit; audit JSON + archive exempt). **Safe-delete count: 0** until cone lands. **Prevention:** [AGENTS.md §File delete gatekeeper](AGENTS.md#file-delete-gatekeeper) + `tests/test_governance_consolidation.py::test_agents_file_delete_gatekeeper_section`. **Closed:** checker lock @ this SHA.

**Cadence (2026-05-20):** **AUDIT-CAND-SERVER-PY-FULL-READ** (in flight) → **STACK-WIRING-INTEGRITY** program (below, immediately after server.py lane closes). Individual LIVE-UI rows remain authoritative; umbrella program ensures nothing from reliability assessment is dropped.

- [x] **LIVE-UI-1 — Near-real-time decision cards vs operator expectation (WebSocket/SSE)** @ `f57c6a7` (inventory landed) + `413787a` + `e3742ac` (per-field withhold via FIND-LIVEUI-6)
  **Reported (2026-05-19):** UI cards showed directional "up" while tape was selling off; operator believed WebSocket path delivers updates **almost instantly**. Observed behavior includes **~30s REST polling** on parts of the stack — **not acceptable** for live trading awareness.
  **Closure:** `governance/STACK_WIRING_INTEGRITY_MAP.md` "Live-UI direction transports (LIVE-UI-1, Phase 2)" section — five-transport ledger (a-e), SLO budgets per surface class keyed to named server constants (`LIVE_QUOTE_SSE_INTERVAL_SEC`, `L1_HTTP_SERVE_MAX_AGE_SEC`, `L1_ORDER_FLOW_STALE_SEC`, `VIEWER_STATE_CACHE_TTL_SEC`, `TICK_COHERENT_MIN_SEC`), and an inventory row per direction-bearing field with producer / transport / client clock / withhold rule. `bundleDirectionWithheld` + `horizonDirectionWithheld` enforce the withhold per field; `_updateDirectionWithheldMarkers` applies the data-direction-withhold attribute on every refresh of `_updateLiveUiAe`; OF strip stays on its own clock.
  **Production SLO validation:** Tracked at FIND-LIVEUI-3 (separate observability row) — `_priceAheadOfBundle` prevalence and visible-paint timing measurement on a live trading session.
  **Files (closed scope):** inventory under `governance/STACK_WIRING_INTEGRITY_MAP.md`; consumer helpers in `static/index.html`; static guard `tests/test_find_liveui_6_v1.py`; behavioral spec `tests/e2e/find-liveui-6-direction-withhold.spec.js`.

- [x] **LIVE-UI-2 — Multi-transport coherence (should have been flagged during stack walks)** @ `5994aeb` (labeling) + `413787a` + `e3742ac` (per-field withhold via FIND-LIVEUI-6)  
  **Evidence in repo today (`static/index.html`):** (a) live quote SSE / `live_quote` path; (b) separate L1 `/api/analytics/light/stream`; (c) Tier C `/api/analytics/state` + 2s poll fallback when SSE stale; (d) fast-quote REST 2.5–12s; (e) liquidity map **60s** poll. **Closure:** `bundleDirectionWithheld` + `_updateDirectionWithheldMarkers` withhold direction-bearing surfaces when quote lane is ahead of Tier C bundle; price DOM stays live; OF strip stays on `order_flow_stale` clock. Tests: `tests/test_find_liveui_6_v1.py`, `tests/e2e/find-liveui-6-direction-withhold.spec.js`.

- [ ] **LIVE-UI-3 — Operator-visible “same moment” acceptance test**  
  Automated: after any tick/SSE, assert all signal surfaces share `decision_generation_id` (and spot direction not contradicting canonical without explicit “structural vs tape” label). Manual: 30m RTH tape vs logged snapshots replay (ties to calibration).

- [ ] **LIVE-UI-4 — UI honesty pass (beyond fail-closed numerics)**  
  Re-audit `static/index.html` for: mixed L1 overlay + Tier C merge (`_lastData`), horizon row vs Decision Command rail vs legacy Call/Put cards, withheld vs flat styling, transport badge vs actual field ages. Prior 12.9 UI work fixed fabrication; did **not** prove single-clock coherence.

- [x] **LIVE-UI-A — Canonical 1/3 triplet consumer audit** @ `bee995d`  
  **Closed end-to-end:** producer stamp (`market_state.build_market_state` dominant_prob gate @ `3313e1f`), call_engine L2b @ `beeb16e`, JS tradability gates @ `bc5705d`, JS regression locks @ `3313e1f`, vol unit contract @ `6db781d`, `CanonicalForecast.dominant_probability()` → `Optional[float]` with caller updates (`call_engine`, `prediction_engine`) + `tests/test_canonical_closeout_issue13.py::test_dominant_probability_returns_none_for_non_tradable_provenance`. Paired locks: `tests/test_action11_9_call_engine_fail_closed.py`, `tests/test_action12_7_market_state_fail_closed.py`, `tests/test_live_ui_integrity_v1.py`, `tests/test_stack_wire_4_cand_ui_fusion_gate.py`, `tests/e2e/stack-wire-4-cand-ui-fusion-gate.spec.js`. Charm quality-gate withhold downgraded to INFO @ `bee995d` (`math_exposure_core.charm_compute_unavailable_log_level`, `tests/test_action11_5_compute_net_charm_fail_closed.py::test_charm_unavailable_log_level_info_for_quality_gates`).

- [ ] **LIVE-UI-B — Degraded stack visibility**  
  `stack_integrity_v1` events in `ml_bundle` / `PredictiveCard.stack_integrity_v1` (signals.py degradation sites; signal_types.py ~L283). **Risk:** `authority_intact=False` while UI looks healthy. **Fix direction:** operator-visible degraded badge when `stack_integrity_events` non-empty or `degraded=True`. **Partial @ `beeb16e`:** `#dr-stack-integrity-degraded-chip` + `_updateStackIntegrityDegradedChip` when `stack_integrity_v1.degraded`; tests `tests/test_live_ui_integrity_v1.py`, `tests/test_stack_wire_3_ui_phase3_closure.py`.

- [ ] **LIVE-UI-C — Secondary horizon “skipped bundle” display**  
  `secondary_support_fusion_audit` skip path (signals.py ~L185–195, ~L1190–1200): `dominant_direction=None`, all probs None, `provenance="skipped_missing_active_bundle"`. **Risk:** blank / zero / stale-last-tick for missing secondaries. **Fix direction:** one withheld UX for “no active bundle.”

- [ ] **LIVE-UI-D — Tri-state None semantics on cards (priority candidate)**  
  Empirical `None` (MIN_SAMPLES), fusion withheld, and "no data yet" all arrive as `None` (signal_types.py ~L237–283; signals canonical path). **Fix direction:** distinct UI labels — withheld / unavailable / loading; map from provenance + component reason codes.
  **Progress (multi-slice):**
  - **Stack status column @ `f560bce`** — `parseFusedStackStatus` / `formatFusedStackStatusDisplay`; horizon Stack row discriminates `stack_failed|`, `fusion_unavailable|`, `fusion_ok|`.
  - **Empirical horizon Bias cell @ `7b22366`** — producer `prediction_engine._pack_horizon_row` stamps `withhold_reason ∈ {no_data, min_samples, data_quality}` when up/down/flat are None. UI `biasFromEmp` helper renders distinct labels: `WITHHELD` (min_samples / data_quality) / `NO DATA` (no_data) / `LOADING` (emp row missing) — each with hover-tooltip. Paired tests in `test_prediction_engine_chunk1_fail_closed.py` (4 producer cases) + `test_live_ui_integrity_v1.py` (2 JS guards).
  - **Horizon Confidence cell + map row @ `7b22366` (sibling-sweep audit catch-up)** — operator flagged the gatekeeping slip: Phase A originally closed only Bias, leaving sibling Horizon Confidence cell with same conflated `'—'` for missing-row vs present-but-null. This sub-slice extends Phase A's sweep to close that gap:
    - `static/index.html` Horizon Confidence cell now distinguishes missing-row (`row.missing` / `row_state='missing'`) from "present but null" via `confMHMeta` (`bias-withheld` class + tooltip naming `row_state`).
    - `governance/STACK_WIRING_INTEGRITY_MAP.md` new row "Decision Command per-horizon panel / withhold-reason discriminator" — was missing per §Closure § Map-row rule; gap caught by self-audit after operator question on slip pattern.
    - Paired test `test_live_ui_d_horizon_confidence_discriminates_missing_row` in `test_live_ui_integrity_v1.py` — 3 tooltip strings + `addKV(grid, 'Horizon Confidence', confMH, confMHMeta)` call-site threading.
    - **Sibling sweep verified clean:** Move P / Fused Confidence gated by `fusionActive` (LIVE-UI-A); Eligibility uses `row.call` discriminating `UNAVAILABLE` (mhap None fix @ beeb16e); Stack via `parseFusedStackStatus` @ f560bce. All 6 per-horizon panel cells now have tri-state discrimination.
  **Remaining (separate slices):** legacy Call/Put cards / per-card horizon prob bar surfaces outside the Decision Command rail — separate render path; PredictiveCard `up_prob_1c` / `down_prob_*` / `flat_prob_*` direct fields have zero JS consumers today (path-only verified) so risk is producer-internal only.

- [ ] **LIVE-UI-E — MH promotion without headline WHY (priority candidate)**  
  call_engine.py ~L1384–1407: MH can promote WAIT→directional (`_mh_promoted_directional`); conviction floored low (L1456–1457) but headline still LONG/SHORT. **Fix direction:** surface promotion + blocker in Decision Command / call reasoning text, not diag-only.

- [ ] **LIVE-UI-F — Live vs replay v2_advisory parity**  
  v2_advisory_backfill stamps missing stack blocks `reconstructed_from_snapshot` (~L118–126). **Risk:** `module_a_a1_decision` behavior differs replay vs live. **Fix direction:** measured parity test (live ms_dict vs reconstructed row); calibration docs state bounds.

- [ ] **LIVE-UI-G — Session boundary UX (mins_to_close)**  
  call_engine.py ~L1632–1655: ≤30m → WAIT; ≤120m → size down. **Risk:** sudden card flips at rolling boundaries without explanation. **Fix direction:** badge “trade window closing” / “boundary in N min” on affected cards.

- [ ] **LIVE-UI-H — StackDecisionPath not surfaced**  
  Six-stage path in signal_types.py ~L348–378; built in signals.py ~L739–892. **Risk:** Final Call shown without per-stage disagree trail. **Fix direction:** render stage trail or collapse with “N of 5 agree” summary.

**Coherence audit protocol (post-project; applies to all future Layer 5 briefs):**

1. **Per-file brief addendum:** after FIND/OBS, mandatory **“Cross-cutting risks (not paired in this slice)”** — any producer contract that depends on UI/downstream behaving correctly, named by file + consumer.
2. **Single-bundle invariant:** test that every card/route for one tick shares `decision_generation_id` (or add field if missing).
3. **Provenance-on-display:** each fail-closed sentinel (None, max-entropy, NOT_AVAILABLE) has a distinct visible label in `static/index.html`.
4. **Operator scenarios:** scripted checks — fast selloff, fast rip, expiry boundary, RTH→AH — bundle coherence during transients.

**Process note (2026-05-19):** Cross-cutting risks must be escalated when visible during any walked file, not only when on an audit checklist. Applies to Cursor and Claude. **Immediate-priority candidates if operator preempts gate:** LIVE-UI-D, LIVE-UI-E, LIVE-UI-B (say which to pair-fix before project close).

### COHERENCE-AUDIT — infrastructure / cross-file (operator 2026-05-19)

**Preempt gate:** Operator may say **go coherence tier-1** before further calibration widen. DST / production-assert / partial fusion snapshot cols affect live money and replay truth.

**TIER 1 — critical**

- [x] **COH-I-A — Single ET authority (`time_et.py`)** — Live `_fetch_state` already used `ZoneInfo`; **`db.now_et()` and `ml_scheduler` used fixed EST** (real DST bug for calibration timestamps / 16:15 scheduler). Closed @ `99ea0e0`: `time_et.now_et()`; `db` re-export; `server` `_eastern_now()`; dead EST constants removed; `test_time_et_authority.py`.

- [x] **COH-I-E — Horizon completeness under `python -O`** — Closed @ `99ea0e0`: `RuntimeError` if primary `fusion_by_hz` incomplete; `multi_horizon_ml_fusion_bundle` production checks (no `__debug__` asserts).

- [x] **COH-I-J — Partial `fusion_policy_snapshot_cols` on stack failure** — Closed @ `99ea0e0`: `fusion_policy_columns_horizon_failed()` → NULL cols + `stack_failed|{exc}` in `fused_stack_status_{hz}`.

**TIER 1.5 — single-authority (behavioral divergence today)**

- [x] **COH-SA-FLOAT — `numeric_contract.py`** @ `31c4f45` — `float_finite_or_none`, `float_positive_or_none`; redirected `v2_advisory_backfill`, `v2_live_logging`, `realized_contract_eval`. **Substantive fix (traceability):** `realized_contract_eval._f` → `float_finite_or_none` — commit message understated severity; pre-`31c4f45`, NaN/inf in snapshot fields could flow into contract PnL silently. `tests/test_numeric_contract_tier15.py`.
- [x] **COH-SA-1 — float wrapper consolidation** — COH-SA-1 ten + repo-wide guard caught six more (`market_context`, `liquidity_value_engine`, `backfill_flow_imbalance`, `a2_replay_labels`, `a1_conformal_*`); all `_*float_or_none` / `_positive_float_or_none` delegate to `numeric_contract`; `tests/test_coh_sa1_float_consolidation.py`.
- [x] **COH-SA-2 — ET ZoneInfo satellites → `time_et`** — production + research paths import `ET` / `now_et()` from `time_et.py`; `tests/test_coh_sa2_et_authority.py` rglob guards.
- [x] **COH-SA-3 — fusion-predicates → `fusion_contract.py`** — `fusion_is_authoritative`, `is_canonical_tradable` / `canonical_provenance_is_tradable`; redirected signals, call_engine, prediction_engine, mc_fusion_adjustment, fusion_policy_contract, market_state, multi_horizon_ml_bundle; `tests/test_fusion_contract.py` rglob guards (`getattr(_?fusion*, "available")` + `in NON_TRADABLE_CANONICAL_PROVENANCE`).
- [x] **COH-SA-4 / COH-I-K — replay max-hold bars → `replay_hold_bars.py`** — live setup prescription, strict context read, trade-type fallback; provenance in replay payload; `tests/test_replay_hold_bars.py`.
- [x] **FIND-STACK-DIR1 — Stack display direction** — operator decision **ALIGN**: `signals._model_stage` uses `direction_from_normalized_triplet` on finite probs only (no `dominant_class`); test `test_stack_model_stage_ignores_dominant_class_uses_triplet`.
- [x] **COH-SA-5 — regime size multipliers → `position_sizing_policy.py`** — `REGIME_SIZE_MULTIPLIERS` + `regime_size_multiplier` (base + confidence nudge); `compute_position_size` redirected; `tests/test_position_sizing_policy.py` rglob guard. Sibling inline thresholds in same function flagged for magic-thresholds slice.
- [x] **COH-SA-TRIPLET** @ `31c4f45` — `direction_from_triplet` / `direction_from_normalized_triplet`; subsumes COH-I-H. Tie-break: up → down → flat (docstring + tests).
- [x] **REPO_SWEEP #1 — error-propagation** — bare `except:` eliminated (4→0); Class-C fixes SWEEP-EP-1..5; baseline 42 silent passes + money-path zero-tolerance frozenset; audit JSON count reconciled; 5 tick-trigger fail-closed tests. Completion @ sweep-1-completion commit. Remaining silent passes: server/ml_scheduler (sweep #2).
- [x] **REPO_SWEEP #2 — error-propagation** @ `1599d75` — SWEEP-EP-6..20; money-path + `server.py` + `ml_scheduler.py` cleared; repo-wide baseline 27 residual silent passes; audit `repo_sweep_error_propagation_v2_20260518.json`.
- [x] **REPO_SWEEP #3 — error-propagation** — SWEEP-EP-21..47 (27 sites): residual `except Exception: pass` → `log.debug` + `exc_info=True` in adjacent/support modules (`levels.py`, `live_market_plane.py`, `schwab_client.py`, calibration/*, etc.); money-path roster re-read — 0 silent passes; baseline 0; audit `repo_sweep_error_propagation_v3_20260520.json`; guard tests in `tests/test_repo_sweep_error_propagation_v1.py`.
- [x] **REPO_SWEEP magic-thresholds** @ `ef42d67` + `27f4fdf` + `a7380a9` — SWEEP-MT-1..13 (lifecycle + greeks producer cone); SWEEP-MT-FULL-TREE (repo-wide `-999.0` → `MISSING_GREEK_SENTINEL` in `order_flow_engine.py`, `math_volatility.py`, `v2_decision/a2_option_expression.py`, `server.py`; `market_state.py` strike-score init → `float("-inf")` not greek sentinel); guard `test_no_inline_missing_greek_sentinel_literal_in_production_outside_authority` walks full production tree (sweep-3 shape).
- [x] **FP1/MT test-tool alignment** @ `d818649` — closes `test_v2_a2_option_expression` FP1 fixture gap (`canonical_provenance="bayesian_fusion"`); aligns `test_debug_charm_has_counters` + `tools/measure_post_fix_theta_v1.py` with `MISSING_GREEK_SENTINEL` authority. No production delta.
- [x] **SWEEP-1-COMPLETION** — audit `class_c_fixed_count` reconciled (5); `_CRITICAL_SILENT_PASS_FILES` expanded (11 money-path modules); EP-4 five coherence branches tested; `signals`/`signal_layer_v1` silent pass → log.debug; rules #22-27 in AGENT_SELF_GOVERNANCE.md.

**TIER 2 — architectural**

- [x] **COH-I-H — Argmax tie-break** — Closed via COH-SA-TRIPLET @ tier-1.5 (`numeric_contract.direction_from_triplet`, up-first on ties).

- [x] **COH-I-C / FIND-SSC1 — `shared_sequence_context` chronology fail-closed** — missing `ts_utc` on chron bounds → `snapshot_ts_utc_missing` (was silent pass); tests `test_build_shared_sequence_context_rejects_missing_ts_utc_*`. Under-fetch when transformer meta missing (~L138-139) remains OBS-SSC1 (accepted).

- [x] **COH-I-K — Replay max-hold bars authority** — `replay_hold_bars.py` (`for_setup` / `from_context` / `for_trade_type` + `resolve_replay_max_hold_bars_for_payload`); payload provenance fields in `build_replay_context_payload`; `tests/test_replay_hold_bars.py` rglob guard. **Historical data (eval bias):** pre-FIND-RCE-RESID3 `replay_context_json` rows may still carry baked-in `replay_max_hold_bars: 30` (trade-type fallback before live card provenance); forward path closed; optional DB backfill to re-resolve from setup — lower priority unless re-running old eval windows.

**TIER 3 — lower**

- [x] **COH-I-B — `trained_at_age_days` 1e9 sentinel** — closed this commit. Named `_TRAINED_AT_UNAVAILABLE_AGE_DAYS = 1e9` in `training_cache.py` replaces the bare magic; both branches (missing field + parse fail) emit distinct `log.debug` messages so the operator can tell them apart in diagnostics. Caller `full_skip_eligible` now returns the distinct reason `manifest_trained_at_unavailable` when the sentinel is hit (was conflated into `manifest_stale_age_1000000000.0d`). Numeric retrain gate behavior unchanged. Test `test_trained_at_age_days_unparseable_returns_same_sentinel_but_logs_distinct_reason` locks the diagnostic distinction.
- [x] **COH-I-G — `cm_json[:8000]` truncation** — code lands in the immediate follow-on commit (OPEN_ITEMS [x] mark was bundled into the prior `54602af` COH-I-B commit by mistake). Named constants in `features/fusion_policy_contract.py`: `FUSION_CONTRIBUTING_MODELS_JSON_MAX_CHARS = 8000` (replaces 3 bare `[:8000]` sites) + `FUSION_STACK_STATUS_MAX_CHARS = 500` (replaces 3 bare `[:500]` status truncations). Replay parser still needs to tolerate truncated JSON (semantic unchanged); the cap is now grep-discoverable and can be widened without churn. Guard test `test_coh_i_g_contributing_models_json_truncation_named` locks the constants + bans the bare numbers at usage sites.
- [x] **COH-I-D — Async calibration write ordering** — closed this commit (diagnostic-only). `calibration/writer.py:append_calibration_decision` now executes `SELECT MAX(decision_ts_utc) WHERE ticker = ?` before each insert and emits a `log.warning("calibration_decision_log logical-time inversion: ...")` when the incoming `decision_ts_utc` is older than the persisted maximum for that ticker — surfaces async-writer out-of-order events in production diagnostics. The insert itself proceeds either way (the UNIQUE+ON-CONFLICT-DO-NOTHING idempotency contract is preserved); only the diagnostic visibility changes. Inversion check is wrapped in its own try/except so a sqlite3 error on the SELECT does not block the INSERT.
- [x] **COH-I-F — `SharedSequenceContext` frozen but nested dicts mutable** — code lands in the immediate follow-on commit (OPEN_ITEMS [x] mark was bundled into the prior `54602af` COH-I-B commit by mistake). `build_shared_sequence_context` now wraps `meta` in `MappingProxyType` (read-only view); mutating `ctx.meta` raises `TypeError`. Dataclass field type narrowed to `Mapping[str, Any]`. Snapshot tuples (`chron_snapshots`, `lstm_merged_window`, `lstm_merged_days`) are left as tuples-of-dicts — per-row dict contents NOT frozen because snapshot dicts flow through other consumer code (mass-freezing here has too wide a blast radius); the tuple wrapper itself prevents row insertion/removal and that's the structural guarantee callers can rely on. Docstring updated to document the contract precisely. Guard test `test_coh_i_f_meta_is_read_only_mapping_view` asserts `MappingProxyType` + write raises `TypeError`.
- [x] **COH-I-I — MC None in sizing path silent skip** — closed this commit. `compute_position_size` in `call_engine.py` now detects "all four MC inputs (mc_eae, mc_efe, mc_containment, mc_expansion) None" — interpreted as "MC simulation unavailable for this tick" — and appends `"MC unavailable — sizing without MC risk validation"` to `reduction_reasons`. The numeric size is unaffected (mc_mult stays 1.0); the sizing summary now surfaces the skip to the operator instead of silent omission.
- [x] **COH-I-L — `dte_warn` reconstruction without `field_sources` stamp** — closed this commit. `ms_dict_from_snapshot_row` in `calibration/v2_advisory_backfill.py` now stamps `field_sources["dte_warn"] = RECONSTRUCTED_LIVE_MS_SOURCE` when it reconstructs the `dte_warn` string from the persisted `dte` field — matching the pattern used by every other reconstructed field in the function. Replay readers can now tell this value came from snapshot reconstruction (not live Tier C).
- [x] **COH-I-M — Unicode in `time_warning` strings** — code lands in the immediate follow-on commit (OPEN_ITEMS [x] mark was bundled into the prior `54602af` COH-I-B commit by mistake). Named constants in `call_engine.py`: `TIME_WARNING_PREFIX_STOP = "\U0001f6d1"` (🛑, no-new-entries ≤30 min) + `TIME_WARNING_PREFIX_ALERT = "⏰"` (reduce-size ≤120 min). The unicode symbols are now grep-discoverable and swappable in one place if a downstream consumer needs an ASCII-token replacement.
- [x] **OBS-CLUSTER-RANK-1** — closed this commit. `compare_clustering_modes.py` adds `CLUSTERING_RANK_NO_ZONES_FLOOR: int = -999` and replaces the bare `-999` in `_recommend_default_clustering`. Semantic distinction from `MISSING_GREEK_SENTINEL` (float, Schwab missing-greek) documented in the constant's docstring — the two are explicitly NOT aliased.

**SLVB minor (operator note, not blocking 3177fdd):** `meta.n_bars` non-numeric string → `int()` can abort loop (`backfill_signal_layer_v1_bundle.py` ~L84); wrap in try if hardened.

**Batch 1** @ `50405b8` — brief + operator sign-off (`99ea0e0`). **LIVE-UI-D stack column** @ `f560bce` (operator sign-off).

**Batch 2 — audit lanes @ `f560bce`:**

- [x] **B2-COH-I-E-REACH** — `state_error`/`state_error_detail` on `market_state` catch; `stack_integrity_events`; `stamp_decision_bundle` skip + `decision_tick_kind`; bg fail-counter wired in `_work()` (`_record_analytics_bg_failure` / `_reset_analytics_bg_fail_count`; `ED_ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES`, default 3).
- [x] **B2-TIER-RENDER-GUARDS** — `_renderCoherenceGuards`, `_updateErrorBarFromPayload`, analytical vs fast timestamp lanes in `static/index.html`.
- [x] **B2-FIND-TIER-A-BLOCKS-C** — Tier A commits `lastFastTs` only (`_commitTierAFastTimestamp`); `lastRenderTimestamp` + `decision_generation_id` gate analytical full render only; Tier B no longer writes `lastRenderTimestamp`; full render accepts newer `decision_generation_id` even when `_server_build_ts` regresses.
- [x] **B2 error-bar** — fires on `state_error || state_error_detail` (not both required).
- [x] **B2-FIND-CAL-TS** — audit @ `governance/audits/find_cal_ts_hour_resolution_v1_20260519.md`: day-bucket (`ts_et[:10]`) safe; **A** paths (live/`decision_time_ms`/`ts_utc` re-derive) open for widen; **B** paths (`rth_where_clause`, stored `market_session`, lifecycle `et_hour` fallback) gated until re-derive or backfill.

**LIVE-UI-A/E** @ `1b27d03` — transport badge, bundle age, lane-stale dim (signed off).

- [x] **LIVE-UI-A/E + LIVE-UI-2 + LIVE-UI-D extension (LIVE_UI_INTEGRITY_V1)** @ `5994aeb` — FIND-LIVEUI-1..5: `#coherence-headline`, `#dr-stack-mode-chip`, `#dr-lane-stale-chip` (`LANE STALE — QUOTE AHEAD` / `LANE STALE — CARDS PAINTING…`), `· PRICE AHEAD` on `#dr-freshness-pill`, `window._priceAheadOfBundle`; extends `_updateLiveUiAe` only; `#dr-trust-stack` compliance unchanged. Tests: `tests/test_live_ui_integrity_v1.py`.

- [x] **FIND-LIVEUI-6 — Phase 2 direction/fusion withhold** @ `413787a` (helpers + markers + lane-stale alignment + CSS) + `e3742ac` (Playwright behavioral spec) — `bundleDirectionWithheld(integrity, d)` + `horizonDirectionWithheld(integrity, d, hz)` in `static/index.html` enforce withhold on `quoteAhead || genStale || pending || _priceAheadOfBundle || slowStaleVsFast || analytics_pending_shell`; `_updateTierCLaneStaleMarkers` aligned to the same gate; price DOM stays live; OF strip stays on its own `order_flow_stale` clock. Tests: `tests/test_find_liveui_6_v1.py` (10 static guards), `tests/e2e/find-liveui-6-direction-withhold.spec.js` (10 behavioral cases).

- [ ] **FIND-LIVEUI-7 — L1 SSE diag counters on ops/governance UI** — expose `server.py` `_l1_sse_diag` (`l1_payload_identity_violation`, throttled, evicted, connections_peak) via `/ops` or `/governance` dashboard (supersedes OBS-LIVEUI-DIAG-1).

**FIND-CAL-TS-RDERIVE** (items 1–5) @ `83ca92b` — signed off.

**FIND-CAL-TS item-6** @ `1509c2d` (backfill engine + CLI) + tooling @ `39410ca`. Runbook: `docs/operations/backfill_et_clock_runbook.md`. **Operator:** execute backfill on live DB; then calibration widen resumes.

**Gate B (2026-05-20):** No consolidation slices until audit lane 1 closes. **SSC1 @ `bb4b6b8`** on feature. **SIG test:** identical feature vs hybrid. **Audit lane 1 @ tip:** `features/signal_layer_v1.py` — brief + paired fixes FIND-SLV1-1..3; operator sign-off pending. **Temp dirs:** all eight session `*_tmp` paths absent in worktree (cleanup N/A).

**Unread for coherence lens (post–batch 1 queue):** ~~`features/signal_layer_v1.py`~~ (lane 1 closed @ `eb933ea`), ~~`features/inference_snapshot.py`~~ (lane 2 paired-fix closed), ~~`features/monte_carlo_stack_input.py`~~ (lane 3 paired-fix closed), ~~`v2_decision/module_a_adapter.py`~~ (MADA closed @ `8ad00ba`), ~~`lifecycle_rule_core.py`~~ (LRC closed @ `951931b`, sign-off), ~~`multi_horizon_ml_bundle.py`~~ (MHMLB-NS1 @ `f14d655`). Remaining → **STACK-WIRE-2**: `multi_horizon_decision.py`, `market_state.py`, `signals.py` full re-read.

### Audit queue — surfaced by MADA producer-cone Read (not blockers for lifecycle)

- [x] **AUDIT-CAND-MS-FP1 — `canonical_provenance` gate allow-list** @ `7b23b70` + fixture follow-on `d818649` — FIND-FP1-1..4: `TRADABLE_CANONICAL_PROVENANCE` (`bayesian_fusion` only); `canonical_provenance_is_tradable` inverted fail-closed; closes `debug_override:*`, `""`, calibration-replay leaks. OBS-FP1-2: dataclass defaults safe post-fix (no change). Tests: `tests/test_fusion_contract.py`, `tests/test_v2_advisory_backfill.py::test_calibration_backfill_v2_advisory_rejects_legacy_empty_provenance_row`, `tests/test_v2_a2_option_expression.py` (`_sample_a1` provenance).
- [x] **AUDIT-CAND-FP1-FIXTURE-COMPLETENESS** @ `056d791` — FIND-FP1-FIX-1..6: stamp `provenance="bayesian_fusion"` on 6 planned sites (chunk2b×4, prediction_vote, time_warning) + 1 runtime catch (action11_9 L256); 4 files no-change; 2 verify-only green. Full FP1 fixture cone 101 passed @ SHA.
- [x] **OBS-MHMLB-NS1 — `fusion_available` name collision** @ `f14d655` — `HorizonMLFusionSnapshot.horizon_fusion_available` + `MultiHorizonMLFusionBundle.horizon_fusion_available(hz)`; consumers updated in `multi_horizon_decision.py`, `prediction_engine.py`. `MarketState.fusion_available` / `ms_dict["fusion_available"]` unchanged. Tests: `tests/test_mhmlb_namespace_v1.py`.
- [x] **AUDIT-CAND-SERVER-PY-FULL-READ** @ `05c48d8` — FIND-SERVERPY-1..19 (excl. demoted 10/16): IV rank/percentile `_ed_db` hoist (8), model health `json.loads` (14), debug prediction `get_zone_distribution` (19), spread_semantic (5), pressure_label fail-closed (9), r_units None (11), stack_mode authority + `signals_engine_failed` (15), L1 gen RuntimeError (7), constants RTH/PL/RECENT_CROSSES (1-4,6,13), liquidity_zone_tradeable_score authority (18), prediction empty direction 400 (17). Tests: `tests/test_audit_cand_server_py_full_read_v1.py` (21 passed). **Gate:** STACK-WIRING-INTEGRITY Phase 0 (STACK-WIRE-0) may proceed.

### STACK-WIRING-INTEGRITY — post–`server.py` full-read program (operator cadence)

**Trigger (Gate B alternation):** immediately after **AUDIT-CAND-SERVER-PY-FULL-READ** closes (brief + verify @ SHA). **Goal:** prove end-to-end that Schwab leaf → signal/stack → `ms_dict` / Tier payloads → `static/index.html` cards is wired correctly for RTH operator truth — not only fail-closed numerics and observability labels.

**Umbrella deliverable:** `governance/STACK_WIRING_INTEGRITY_MAP.md` (or JSON) — one table: **surface** (Decision Command rail, per-hz cards, Call/Put legacy, diagnostics strip) × **field** × **producer module** × **transport** (SSE `live_quote`, SSE Tier C JSON, L1 light, poll) × **client clock** (`lastFastTs`, `lastRenderTimestamp`, `decision_generation_id`, `l1_generation`) × **stale/when-withhold rule** × **test/fixture** × **OPEN_ITEMS id**. Sign-off only when map is complete and regression bar green.

**Phase 0 — ingest server.py audit (blocking)**
- [x] **STACK-WIRE-0** @ `054c873` — `governance/STACK_WIRING_INTEGRITY_MAP.md` seeded (17 FIND rows + 4 anchors + schema); `server.py` stale `pre_get_db`/`get_db` diag removed post FIND-8 hoist; tests `tests/test_stack_wire_0_v1.py`. **Phase 3 follow-ons filed (not implemented here):** `STACK-WIRE-3-UI-SPREAD-SEMANTIC`, `STACK-WIRE-3-UI-PRESSURE-UNAVAILABLE`, `STACK-WIRE-3-UI-R-UNITS-NONE`, `STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE`, `STACK-WIRE-3-UI-IV-RANK`. **Gate:** STACK-WIRE-1 unblocked.

- [x] **STACK-WIRE-3-UI-SPREAD-SEMANTIC** @ `be67e57` (+ render-path unification @ `bfd2bda`) — Single authority `computeSpreadGate(inp)` in `static/index.html`; render() now destructures `gateOk + label` directly from `computeSpreadGate(...)` — no duplicated inline dispatcher to drift. Dispatches on producer-stamped `d.spread_semantic` (`"fraction"` → unit-less gate `spread < 0.05`; `"dollar"` → dollar-width gate `spread < 0.05`; absent → legacy heuristic (slow-stale-vs-fast + fast-lane spread + spot)). **Cursor caught a real fraction-path bug in the first version** (fraction + valid spot was driving `_spdIsPxWidth=true` and the threshold to `0.05/spot=0.0005`, wrongly failing 2% spreads as bad) — fixed by forcing `_spdIsPxWidth=false` for fraction. Producer: FIND-SERVERPY-5 @ `05c48d8`. Tests: `tests/test_stack_wire_3_ui_phase3_closure.py::test_wire3_ui_spread_semantic_consumer_dispatch` (static guard) + `tests/e2e/stack-wire-3-ui-phase3-behavioral.spec.js::computeSpreadGate dispatches on producer-stamped spread_semantic` (behavioral: fraction OK / fraction BAD / dollar OK / heuristic OK / withheld em-dash).
- [x] **STACK-WIRE-3-UI-PRESSURE-UNAVAILABLE** — closed this commit (withhold-by-absence). Producer can emit `pressure_label="unavailable_no_dpi_or_hedging_flow_direction"` (`server.py:4291-4294`) when neither DPI nor hedging flow yields a direction. UI does NOT bind `pressure_label` to any DOM surface, so the sentinel value is trivially withheld. Guard test `tests/test_stack_wire_3_ui_phase3_closure.py::test_wire3_ui_pressure_label_unavailable_treated_as_withheld` locks the contract — if `pressure_label` is later re-introduced to UI, the guard fires until the consumer adds an explicit withhold check on the sentinel string. Producer: FIND-SERVERPY-9 @ `05c48d8`.
- [x] **STACK-WIRE-3-UI-R-UNITS-NONE** — closed this commit (withhold-by-absence). `signal_types.TheCall.r_units: Optional[float] = None` (FIND-WIRE1-1 @ `e65d2c2`); market_state sets None when prerequisites missing. UI does NOT bind `r_units` to any DOM surface — withhold trivially satisfied. Guard test `tests/test_stack_wire_3_ui_phase3_closure.py::test_wire3_ui_r_units_none_treated_as_withheld` locks the contract — if `r_units` is bound later, the guard fires until the consumer gates on null/undefined (NOT substitutes 0, since 0 r_units is a real "zero risk-units" value). Producer: FIND-SERVERPY-11 @ `05c48d8`.
- [x] **STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE** — closed this commit. Added dedicated chip `#dr-signals-engine-fail-chip` next to `#dr-stack-mode-chip`; new `_updateSignalsEngineFailChip(integrity)` function shows "SIGNALS ENGINE FAILED" when `stack_runtime.signals_engine_failed === true` (distinct from `stack_mode=INVALID` — a signals crash means upstream fields are partial/stale, not just fusion/MC missing). Wired into `_refreshLiveUiIntegrityDerivations` (new `signalsEngineFailed` integrity field) and `_updateLiveUiAe`. Producer: FIND-SERVERPY-15 @ `05c48d8` (server.py:5365-5368). Tests: static guard `test_wire3_ui_signals_engine_failed_badge_present` + Playwright behavioral `dr-signals-engine-fail-chip surfaces signals_engine_failed=true distinctly from stack INVALID` (covers chip visible+text+class on true; hidden when false even if stack_mode=INVALID).
- [x] **STACK-WIRE-3-UI-IV-RANK** — closed this commit. Added Volatility regime subsection in `renderContextLayer` with `#ctx-iv-rank` + `#ctx-iv-percentile` rows reading `d.iv_rank` / `d.iv_percentile`. Helper `_fmtIvBp(v)` renders `'—'` for null/NaN (withheld, never substitute 0); zero is a REAL value (lowest-on-record) and renders as `'0'`. Producer: FIND-SERVERPY-8 @ `05c48d8` (server.py:4998-4999 ms_dict stamp ← `math_volatility.compute_iv_rank` / `compute_iv_percentile`). Tests: static guard `test_wire3_ui_iv_rank_bound_with_withhold_semantic` + Playwright behavioral `renderContextLayer binds iv_rank / iv_percentile with em-dash withhold (not zero)` (covers null→em-dash, mixed null/valid, zero→'0' not '—', high band).

**Phase 1 — backend producer / payload cone (money path)**
- [x] **FIND-WIRE1-1-CALLCARD** @ `e65d2c2` — `signal_types.TheCall.r_units: Optional[float] = None` (completes FIND-WIRE1-1 / FIND-SERVERPY-11 producer chain at CallCard). Tests: `test_stack_wire_1_v1.py::test_r_units_none_propagates_end_to_end`, `test_action10_6_thecall_validation_defaults.py::test_thecall_r_units_defaults_none_not_zero`.
- [x] **STACK-WIRE-1** @ `251bf86` — FIND-WIRE1-1..6: completes FIND-SERVERPY-11 upstream (`r_units` None in `market_state.py`); mid-pipeline `stack_integrity_events` → `stack_integrity_v1` (FIND-WIRE1-2); `decision_generation_id` explicit None on signals_engine_failed (FIND-WIRE1-4); single `classify_stack_health` site in `server.py` (FIND-WIRE1-3); `STATE_ERROR_DETAIL_MAX_CHARS` (FIND-WIRE1-6). Map +11 Decision Command rows + Card cluster augmentations in `STACK_WIRING_INTEGRITY_MAP.md`. Tests: `tests/test_stack_wire_1_v1.py` (8 passed). **Precondition updates:** STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE now sees mid-pipeline events; STACK-WIRE-3-UI-R-UNITS-NONE receives None on wire. **Gate:** STACK-WIRE-2 unblocked.
- [x] **STACK-WIRE-2** @ `73c46bc` — FIND-WIRE2-1..5: `PRIMARY_DECISION_HORIZONS` derived at 4 sites (MHD + mhap rank); MHD named-constants block (~25, Phase 6 ablation surface); FIND-WIRE2-3 reconciled `TRADEABLE_DOM_MIN`/`TRADEABLE_MARGIN_MIN` @ same commit `4b3dce4`; `canonical_forecast_missing` fail-closed (FIND-WIRE2-5). Map +2 Card cluster augmentations. Tests: `tests/test_stack_wire_2_v1.py` (7 passed). **Gate:** STACK-WIRE-3 unblocked.
- [x] **STACK-WIRE-3** @ `4006b78` — FIND-WIRE3-1..7: `call_engine.py` + `prediction_engine.py` overlay (`60m` readiness key; `RTH_OPEN_MINS` time_et option b; `EXEC_MODES` derivation; `WAIT_BLOCKER_REASON_*`; ~60 + ~12 named constants; `probs_15c`/`probs_60c`); tests `tests/test_stack_wire_3_v1.py` (9/9). Action 12.7+ closure. Deploy: readiness_score movement expected (WIRE3-1). **Gate:** STACK-WIRE-4.
- [x] **STACK-WIRE-4** @ `e91bc9e` — FIND-WIRE4-1..4: verification slice (incl. v2_decision): NON_TRADABLE docstring diagnostic-only; `is_ms_dict_fusion_authoritative` leave-as-is; governed_stack_contract 5 constants; map `stack_mode` 4 UI sites; tests `test_stack_wire_4_v1.py` (5) + `test_fusion_contract` extension (9). **Gate:** STACK-WIRE-5 unblocked.
- [x] **STACK-WIRE-4-CAND-MS-DICT-ADOPTION** @ `ebf2609` — Primary fix: `server._attach_stack_runtime_and_governance` now keys `fusion_active` (and the `fusion_available` arg threaded into `classify_stack_health`) off `fusion_contract.is_ms_dict_fusion_authoritative(ms_dict)` instead of the bare `ms_dict["fusion_available"]` flag. Closes the Decision Command split-brain where `fusion_available=True` + `canonical_provenance="canonical_forecast_missing"` would surface `fusion_active=True` / non-INVALID stack_mode to the operator while v2 tradability was blocked. Regression test: `tests/test_stack_wire_1_v1.py::test_stack_runtime_fusion_active_uses_tradability_gate_not_bare_flag` (covers `canonical_forecast_missing`, empty-string provenance, and authoritative `bayesian_fusion` cases; also asserts source-level adoption of `is_ms_dict_fusion_authoritative`). Map row [`stack_runtime.fusion_active`](governance/STACK_WIRING_INTEGRITY_MAP.md) updated.
- [x] **STACK-WIRE-3-UI-FUSION-TRADABILITY-GATE** @ `db3f017` — Server-side rail (`stack_runtime.fusion_active`, `stack_mode`) was correct after `ebf2609`, but the operator-visible detail strip in `static/index.html` still keyed three sites off the bare `d.fusion_available` flag — Cursor's `ebf2609` re-audit caught this. Fix: introduced `isFusionAuthoritative(d)` UI helper that mirrors `fusion_contract.is_ms_dict_fusion_authoritative` semantics — primary read is `stack_runtime.fusion_active` (server-stamped truth after WIRE-4-CAND), legacy fallback is `fusion_available && canonical_provenance === "bayesian_fusion"` matching `TRADABLE_CANONICAL_PROVENANCE`. Adopted at the three flagged sites: `dr-stack-fusion` detail chip (active/inactive), `resolveSignalChain` FUSION step in the rail SVG, and `effectiveDirection` (WDS/Call fusion-band direction selector — no longer steers off `fusion_dominant_direction` for non-tradable payloads). Regression: 4 Python static-HTML guards (`tests/test_stack_wire_4_cand_ui_fusion_gate.py`) + 2 Playwright behavioral specs (`tests/e2e/stack-wire-4-cand-ui-fusion-gate.spec.js`) covering split-brain payload (false), bayesian_fusion fallback (true), empty provenance (false), and `rt.fusion_active=false` veto of bare-flag-true payload.
- [x] **ISSUE18-BEHAVIORAL-CARD-RENDER-COVERAGE** @ `e139046` — Replaces the static-HTML substring-only checks in `tests/test_issue18_ui_contract.py` (acceptable but weak per Cursor's audits) with real-browser DOM verification via `tests/e2e/issue18-card-render-behavioral.spec.js`. Coverage: (1) `tf-signal-<slug>` card class reflects mhap_rows direction (LONG → `tf-state-up`, SHORT → `tf-state-down`, UNAVAILABLE → `tf-state-dim`) AND confidence band (`tf-glow-1/2/3` based on 76/61 thresholds); (2) Decision Rail `dr-align-{1m,5m,15m,60m}` slots render `"<CALL> · <conf>"` from mhap_rows; (3) `dr-plan-{entry,stop,targets,invalidation}` come straight from payload display fields; (4) `dr-live-ready-chip` flips to `NOT_LIVE_READY` and `dr-blocking-reason` shows "stack INVALID (fusion/MC prerequisites)" + `dr-action-chip` shows `CONFIRMATION NEEDED` when split-brain payload (canonical_forecast_missing) produces stack_mode=INVALID. End-to-end behavioral verification of the WIRE-4-CAND chain through the operator-visible cards. The substring-only `test_issue18_ui_contract.py` guards stay as cheap regression for the source-level patterns; the behavioral spec is the authoritative contract test.
- [x] **MEGA4-INVENTORY-REAUDIT-ARCH-COMPETITION-SLICE** — closed this commit. Cursor's 2nd re-audit flagged ~474 mega4 entries using the boilerplate justification "Reads persisted snapshot SQLite rows, not Schwab wire JSON" as "lazy classifications" — many functions so labeled have no DB read at all. Slice 1 (arch_competition/ subdirectory): each of the 20 ALLOWLISTED entries verified by source read; **17 reclassified ALLOWLISTED → NONE** (pure validators / math / dict builders / filesystem operations with no DB read, no market-field derivation): `build_audit_record`, `_validate_probability_detail`, `_rollback_checkpoint_available`, `validate_parallel_cascade_manifest_lineage`, `persist_live_drift_monitoring`, `_validate_manifest_record_lineage`, `_snapshot_active_to_checkpoint`, `manual_promote_to_active_explicit`, `manual_rollback_to_checkpoint_explicit`, `expected_calibration_error_multiclass`, `reliability_bins_table`, `overconfidence_diagnostics`, `process_notification_deliveries`, `_delivery_record`, `build_operational_policy_payload`, `decide_promotion`, `build_arch_competition_summary_tick`, `_pack_full_metrics`, `_authority_block`. **3 stay ALLOWLISTED** with corrected (non-boilerplate) justification reflecting their actual role as DB orchestrators via ml_scheduler: `run_architecture_pair_evaluation`, `build_live_drift_monitoring_payload`, `run_stack_bundle_evaluation`. Tests `tests/test_mega4_traceable_audit.py` (9/9). **Remaining mega4 follow-on:** the same audit is needed for the other ~12 mega4 subdirectories (calibration/, bayesian_fusion.py, normalized_*, etc.) — tracked as `MEGA4-INVENTORY-REAUDIT-CALIBRATION-AND-REMAINDER` below.
- [x] **MEGA4-INVENTORY-REAUDIT-CALIBRATION-AND-REMAINDER** @ `424acd9` — multi-slice audit complete on the boilerplate-justification axis. **Boilerplate-ALLOWLISTED count: 474 (start of session) → 0 (this commit).** Every mega4 ALLOWLISTED row now carries a function-specific justification that names what reads SQLite (or notes the function is allowlisted for a Mega1 producer pass-through / filesystem fixture). Slice chain: `313194c` (calibration utility batch 1, 41 entries) → `6f15431` (calibration batch 2, 85) → `c870055` (ml_predict + train_all + normalized_training_sync, 30) → `fe63d71` (analyze_phase3 + partial phase4, 11) → `e74afa5` (anchor_audit + edge_discovery + edge_validation + canonical_enforcement + audit_phase1 + eval_movement_targets, 42) → `acf6866` (schema + writer + legacy_report + validate_* + signal_layer_discrimination + phase4 _inc cleanup, 19) → `9a8c690` (v2_a1_calibration + v2_advisory_backfill, 32) → `e5964d2` (ML model files: lstm_data + lstm_model + transformer_model + transformer_train + xgboost_model + ml_train, 44) → `d48d2a4` (ml_data_common + ml_horizon + smoke_predict_active + train_compare + training_cache + training_provenance, 30) → `ca629eb` (training_cache + ml_data_common remainders + ml_predict helpers + arch_competition leftover, 21) → `56f534a` (ml_scheduler, 20) → `8cdf087` (phase65_edge_isolation_v1 + phase6_edge_discovery_governed_v1, 38) → `424acd9` (final long-tail cleanup: backfill_outcomes + backfill_signal_layer_v1_bundle + build_trusted_anchor_proof_dataset + canonical_1m_grid_scan + movement_target_phase6_edge_v1 + repair_* + run_production_accumulation_validation + train_all preload + training_provenance + ml_predict + training_cache remnants, 35). Mega4 inventory tests pass on every commit (9/9). **Same-turn cascade fixes** caught + resolved within their batch commits whenever NONE conversion broke a DERIVED chain (e.g., signal_engineering 4 DERIVED→NONE in batch 2; analyze_phase4 _inc same-pattern cleanup; lstm_model + transformer_train forward-passes; transformer_model.predict producer_refs).
- [x] **STACK-WIRE-5-CAND-OF-RESIDUAL-MAGICS** — closed this commit. Named constants added to `order_flow_engine.py`: `OF_BOOK_DEPTH_TOP = 1`, `OF_BOOK_DEPTH_SHALLOW = 3`, `OF_BOOK_DEPTH_DEEP = 5` (replace bare `1/3/5` at `_compute_book_imbalance(data, …)` call sites — `_compute_institutional_flow_proxy` + `OrderFlowEngine.compute`); `OF_RVOL_NEUTRAL_CENTER = 1.0` (replaces bare `1.0` in `(rvol - 1.0)` inside `_compute_order_flow_score`); `OF_WEIGHTED_MEAN_DEFAULT_MIN_PRESENT = 2` (replaces bare `2` as the keyword-arg default on `_weighted_mean_present`). Static guard test `tests/test_stack_wire_5_v1.py::test_order_flow_engine_residual_magics_named` locks the named constants + bans the bare integers at the original sites.
- [x] **STACK-VERIFY-CAND-LOAD-TICKERS-RETURN-TYPE** — closed this commit. `scheduler_user_tickers.load_user_scheduler_tickers` now returns `Optional[list[str]]` — `None` on DB-bound load failure (distinct from `[]` "DB OK but nobody enrolled"). Added convenience wrapper `load_user_scheduler_tickers_or_empty()` that returns `load_user_scheduler_tickers() or []` for legacy callers that want the pre-fix list-or-empty semantic. All 6 production callers updated to use the convenience wrapper: `lstm_data.py:677,890`, `ml_scheduler.py:151`, `train_all.py:57`, `transformer_train.py:165`, `verify_active_models.py:46` — behavior preserved (None branch is silently coerced to []), but new callers can opt into the explicit None branch for distinct error visibility. Test mock at `tests/test_issue22_logging_universe.py:217-220` continues to return a list (still valid under the new Optional return). New guard test `tests/test_scheduler_user_tickers_return_type.py` (4 tests) locks: (a) typed function returns None on DB failure; (b) wrapper returns [] on DB failure; (c) signature is Optional[list[str]]; (d) no production caller uses the typed version directly without None handling.
- [x] **STACK-VERIFY-CAND-SILENT-FALLBACK-SWEEP** — closed for the two named sites; broader sweep across remaining TARGET_FILES tracked as separate row `STACK-SWEEP-NEXT-CAND-SILENT-FALLBACK` (below). Two concrete fixes landed: (a) `market_context.py:_sf` (inner helper at L821) — narrowed bare `except Exception:` to `except (TypeError, ValueError):` to match the actual float-coercion failure modes (a broad bare-except was hiding non-coercion bugs like AttributeError when `q` was a non-dict, KeyError, etc.). (b) `schwab_client.safe_get_price_history` enum→raw-kwargs nested fallback (L412-423) — both `except Exception:` branches now emit diagnostics: `log.debug` when the enum-API path fails (legacy fallback triggers), `log.warning` when BOTH paths fail (full silent-drop to None becomes visible).
- [ ] **STACK-SWEEP-NEXT-CAND-SILENT-FALLBACK** — broader silent-fallback sweep across remaining TARGET_FILES (post-STACK-VERIFY-CAND scope split out 2026-05-24 during Deferral Reconciliation). Active row, not gated; operator-triggered slice when wall time allows.
- [ ] **STACK-SWEEP-NEXT-CAND-LOGGER-NAME-AWARENESS** — follow-on (big-audit catch): future sweep tooling (sweep4+) must detect the file's existing logger name (`log` / `logger` / `_log`) before emitting log calls. sweep3 generator blindly emitted `log.debug` regardless, requiring followup commits like `4edeefc3` (ml_predict) and `61b60f1` (normalized_training_sync) to correct.
- [x] **STACK-WIRE-5** @ `fd2bb46` — FIND-WIRE5-1..3: `order_flow_live_state.is_rth_open` 4th `RTH_OPEN_MINS` consumer (FIND-WIRE5-1); OF composite 22 named constants (Phase 6 ablation surface) — weights sum 1.00, clip / rvol-term / direction / readiness ladders + tape windows + norm divisors (FIND-WIRE5-2); OF freshness vs Tier C independence — 2 map rows for order-flow strip + stack vote layer (FIND-WIRE5-3); tests `tests/test_stack_wire_5_v1.py` (5/5). **Gate:** STACK-WIRE-6 unblocked.
- [x] **STACK-WIRE-6a** @ `c0d1bb4` — FIND-WIRE6-1..2: replay hold bars single authority: `RTH_SESSION_MINUTES = RTH_END_MINS - RTH_OPEN_MINS` derived in `time_et.py` (FIND-WIRE6-1, 390 magic removed from `replay_max_hold_bars_from_context`); `TRADE_TYPE_HOLD_BARS` dict + `MICRO_REGIME_HOLD_BARS_COMPRESSION` shared between `for_setup` + `for_trade_type` paths — `trade_type="none"` returns 0 in BOTH (FIND-WIRE6-2 parity break fix; was 20 in fallback vs 0 in live); tests `tests/test_stack_wire_6_v1.py` (5) + `tests/test_replay_hold_bars.py` parity case extended. **Gate:** STACK-WIRE-6b independent (parallel-safe); STACK-WIRE-6 parent closes when 6b + live/replay parity validation also land.
- [x] **STACK-WIRE-6b** @ `38bb7ce` (+ O-54 retrofit @ `e20b4b8`) — FIND-WIRE6-3..7: Schwab-leaf adoption + magic-constant sweep: `_contract_multiplier` reads `chains.*.multiplier` per-row (FIND-WIRE6-3 — `OPTION_MULTIPLIER=100` removed; three-way semantics per **GOVERNED_EXCEPTION O-54**: leaf present + valid → Schwab int; leaf ABSENT → `LEGACY_CHAIN_MULTIPLIER_DEFAULT=100` (legacy pre-emission snapshots, ~50% of archived rows); leaf PRESENT but INVALID → fail-closed + "missing_multiplier" skip-reason); `STRIKE_MATCH_TOL_PENNY`/`STRIKE_MATCH_TOL_NICKEL` at 8 sites in `realized_contract_eval.py` (FIND-WIRE6-4); `REPLAY_BUNDLE_MIN_JSON_LENGTH=10` authority in `replay_bundle_coverage.py`, adopted by `realized_contract_eval.py` + `live_vs_replay_validation.py` + `tools/measure_post_fix_theta_v1.py` (FIND-WIRE6-5); `CHAIN_QUALITY_AUDIT_MAX_RECORDS=5000` / `CHAIN_DEBUG_MAX_RECORDS=200` (FIND-WIRE6-6); `TICK_REFRESH_SPOT_PCT_DEFAULT=0.0003` / `_ABS_DEFAULT=0.05` in `live_decision_bundle.py` (FIND-WIRE6-7); tests `tests/test_stack_wire_6b_v1.py` (6). **Gate:** STACK-WIRE-6 parent closes when live-vs-replay parity validation (component 3) also lands.
- [x] **STACK-WIRE-6c** @ `9d4c8a4` — FIND-WIRE6c-1..6: live-vs-replay parity validation: measured test that `calibration.v2_advisory_backfill.ms_dict_from_snapshot_row` reconstructs every aliased field, replay-context-propagated field, ET-clock derivation, and provenance stamp with parity to the live ms_dict shape. Includes pass-through preservation when key already present + fail-closed when replay_context_json missing (no fabricated defaults). Tests `tests/test_stack_wire_6c_v1.py` (8). **Gate:** STACK-WIRE-6 parent closed.
- [x] **STACK-WIRE-6** @ `9d4c8a4` — **Live vs replay parity** — parent item **LIVE-UI-F** — closed with 6a (`c0d1bb4`) + 6b (`38bb7ce`) + 6c (`9d4c8a4`). All three components: replay hold bars single authority, Schwab multiplier leaf adoption + named-constant sweep, and ms_dict reconstruction parity validation.
- [ ] **STACK-WIRE-7** — **Layer 5 remainder** — **Action 12.7+** queue (`ml_predict`, `ml_scheduler`, `features/*` not yet closed, `calibration/*` residual) — only modules that feed live card fields or `ms_dict` authority; file OBS or paired-fix per brief schema.

**Phase 2 — client transport + clocks (cards "same moment")**
- [x] **LIVE-UI-1** @ `f57c6a7` — Inventory landed in `governance/STACK_WIRING_INTEGRITY_MAP.md` (section "Live-UI direction transports (LIVE-UI-1, Phase 2)"): five-transport ledger (a-e), SLO budgets per surface class keyed to named server constants, and a row per direction-bearing field with producer / transport / client clock / withhold rule. SLO production validation lives at FIND-LIVEUI-3 (separate observability row).
- [x] **LIVE-UI-2** @ `413787a` + `e3742ac` — Per-field withhold landed via FIND-LIVEUI-6: direction surfaces enter WITHHOLD when behind fast lane while price DOM stays live; OF strip stays on its own clock. Labeling closed @ `5994aeb`, behavioral closure here.
- [ ] **LIVE-UI-3** — Automated + manual "same moment" acceptance (`decision_generation_id` + tape replay).
- [x] **FIND-LIVEUI-6** @ `413787a` + `e3742ac` — Phase 2 direction withhold: see closure row in COHERENCE-AUDIT section above for full deliverable list (helpers, marker applier, lane-stale alignment, CSS, static guards, behavioral spec).
- [ ] **FIND-LIVEUI-7** — Expose `server.py` `_l1_sse_diag` on `/ops` or `/governance` (identity violations, throttle, evicted, connections peak).
- [ ] **STACK-WIRE-8** — **`static/js/l1_sse_guards.js`** ↔ server L1 identity tuple contract test; no drift vs `l1_generation` / scope key at [server.py:295-296].
- [ ] **STACK-WIRE-9** — Preserve intentional asymmetry: `_renderCoherenceGuards` (newer `decision_generation_id` wins when `_server_build_ts` regresses), `_commitTierAFastTimestamp` vs `_commitAnalyticalRenderTimestampAndGen`, `_slowStaleVsFast` price-DOM guard — document in wiring map as **designed**, not bugs.

**Phase 3 — UI honesty / operator surfaces (cards + rail)**
- [ ] **LIVE-UI-4** — Full UI honesty pass: L1 overlay + Tier C merge (`_lastData`), horizon row vs Decision Command vs legacy Call/Put, withheld vs flat styling, transport badge vs field ages.
- (LIVE-UI-A duplicate removed during Deferral Reconciliation 2026-05-24 — canonical row lives above in the COHERENCE-AUDIT preempt-gate list as "LIVE-UI-A — Canonical 1/3 triplet consumer audit"; tracking that single row only.)
- [ ] **LIVE-UI-B** — `stack_integrity_v1` / `authority_intact=False` operator-visible degraded badge (not healthy-green while degraded).
- [ ] **LIVE-UI-C** — Secondary horizon “skipped bundle” withheld UX (`skipped_missing_active_bundle`).
- [ ] **LIVE-UI-D** — Tri-state None on cards (withheld / unavailable / loading); stack status column closed @ `f560bce`; **global `stack_mode` INVALID chip** closed @ `5994aeb` — remainder is card-level None semantics.
- [ ] **LIVE-UI-E** — MH promotion WAIT→directional: headline WHY / blocker visible (not diag-only).
- [ ] **LIVE-UI-G** — Session boundary UX (`mins_to_close` flips explained on card).
- [ ] **LIVE-UI-H** — `StackDecisionPath` stage trail or “N of 5 agree” summary on operator surface.
- [ ] **STACK-WIRE-10** — **`#dr-trust-stack`** remains **compliance only** (`active_compliant`); **`#dr-stack-mode-chip`** remains **`stack_runtime.stack_mode` only** — regression guard in wiring sign-off checklist.

**Phase 4 — regression bar + sign-off (closes umbrella)**
- [ ] **STACK-WIRE-11** — **Single-bundle invariant test** (coherence protocol #2): after any tick/SSE, all signal surfaces share `decision_generation_id` OR explicit stale badge per surface (automated).
- [ ] **STACK-WIRE-12** — **Provenance-on-display** (protocol #3): each fail-closed sentinel (None, max-entropy, NOT_AVAILABLE) has distinct visible label in `static/index.html` (grep + test).
- [ ] **STACK-WIRE-13** — **Operator scenarios** (protocol #4): fast selloff, fast rip, expiry boundary, RTH→AH — bundle coherence during transients; scripted checklist + log capture.
- [ ] **STACK-WIRE-14** — **Full money-path pytest** at sign-off SHA (broader than per-slice cones: FP1 + MADA + LRC + LIVE_UI + server-py regression tests); operator PowerShell report required per FP1 lesson.
- [ ] **STACK-WIRE-15** — **Consumer re-fabrication grep** — no downstream 0.33 / `"flat"` / `"wait"` when producer withheld (extends stack foundation pass #2).
- [x] **Stack foundation sign-off** — **merged into this program** @ L583: run passes (1)–(6) as part of Phase 4; trigger `go stack-wiring-integrity-signoff` when Phases 0–3 complete. **Do not** duplicate a separate ad-hoc pass. (No longer a standalone open item — the underlying Phase 4 sign-off passes track this; this row is cross-reference only.)

**Phase 5 — residual / lower priority (file if wiring audit surfaces impact)**
- [x] **COH-I-B, COH-I-D, COH-I-F, COH-I-G, COH-I-I, COH-I-L, COH-I-M** — all seven tier-3 COHERENCE-AUDIT rows closed in the COHERENCE-AUDIT TIER 3 list above (`54602af` + follow-ons). Promote-to-paired-fix path is unused — no live/card impact surfaced.
- [x] **OBS-CLUSTER-RANK-1** — closed in COHERENCE-AUDIT TIER 3 above (`CLUSTERING_RANK_NO_ZONES_FLOOR = -999` named constant in `compare_clustering_modes.py`); semantic distinction from `MISSING_GREEK_SENTINEL` documented.
- [x] **OBS-FPC1, OBS-FPC2** — accepted, no code change. OBS-FPC1 (`fusion_payload_to_policy_columns` `json.dumps` failure → `cm_json = "[]"`): audit metadata only; not policy prob authority. OBS-FPC2 (`fused_stack_status_*` uses `dom`/`fconf` `"?"` when fusion attrs missing): audit string; accepted disclosure. Replay-UI parse risk noted but bounded by the named truncation constants closed in **COH-I-G** above; revisit only if a wiring map slice touches the calibration replay UI.
- [x] **OBS-TC1/2/3** — accepted, no code change. OBS-TC1 (`load_lstm_feature_cache` metadata defaults empty or 0): structural dims already fail-closed via `_meta_required_positive_int`. OBS-TC2 (`_normalize_data_fp({})` returns `{}` vs 6-key shape for non-empty): conservative cache miss on legacy empty identity — accepted. OBS-TC3 (legacy `cache_exists` / `read_cache_meta` at file tail unused by scheduler): accepted. Re-verify only if server.py scheduler paths change in a future slice.
- [ ] **Action 12.7+** non-card modules — complete for repo hygiene; not blocking STACK-WIRING sign-off unless they feed live authority fields.

**Phase 6 — edge measurement framework (parking slot; no implementation until Phases 0–5 close and ablation justifies)**
- [ ] **STACK-WIRE-6-EDGE-MEASUREMENT-FRAMEWORK** — **Heart-of-system** measurement program: prove which **(component × horizon)** contributions carry real edge before expanding live surface or training scope. **Not the same row as STACK-WIRE-6** (live vs replay parity @ Phase 1).

  **Intent — per-horizon feature scoping:** Score and ablate features **per decision horizon** (1m / 5m / 15m / 60m product slugs), not one global feature bag. Each horizon’s live card + fusion path gets an explicit “what moved the needle?” ledger tied to `PRIMARY_DECISION_HORIZONS` authority.

  **Inventory gap:** ~**25 registered analytics** in repo/feature contracts vs **~10-field MVP** currently driving operator-facing cards — map the delta; anything not on a card path is a candidate for ablation inclusion or deliberate deferral (document why).

  **Unused / under-wired feature candidates (first ablation roster):**
  - **OHLCVA Amount (dollar turnover)** — see **FEATURE-OHLCVA-AMOUNT** (derive from existing bar/snapshot price + volume; ablation before canonical contract promotion)
  - **Per-ticker GEX (dealer gamma exposure)** — see **FEATURE-PER-TICKER-GEX** (local chain GEX for the traded underlying; extend existing `math_exposure_core` primitive; not universal SPX)
  - ETF **constituent-weighted confluence**
  - **Sector strength** aggregate
  - **IWM deep confluence**
  - **Charm** (net charm / charm-direction family — see `math_exposure_core`, model meta feature lists)

  **Cheapest first step — MC ablation toggle:** Reuse existing stack eval pattern (`fusion_without_mc` / dead `MonteCarloOutput` path in `arch_competition/stack_bundle_eval_v1.py` class of tooling). Toggle MC participation per horizon slice before touching new feature engineering. Establishes baseline “does MC earn its complexity?” on SPY/QQQ walk-forward slices.

  **Methodology — walk-forward purged CV:** Time-ordered evaluation only; **purged** train/test splits with embargo (AFML Ch. 7–12 class). No random k-fold on overlapping bars. Report log loss / Brier / calibration drift + stability across folds — not single in-sample peak.

  **Literature anchors (design vocabulary, not implementation mandates):**
  - **Numerai** — neutralized, per-era feature importance / stake-weighted validation discipline
  - **TFT** (Temporal Fusion Transformer) — static vs time-varying covariate split; horizon-specific decoder heads
  - **AFML** (*Advances in Financial Machine Learning*, López de Prado) — purged k-fold, meta-labeling, feature importance under leakage controls
  - **Kearns–Nevmyvaka** — market microstructure + ML evaluation rigor for sequential decision data

  **Gate rule:** **Nothing in Phase 6 ships to production** (new card fields, scheduler features, fusion weights) until ablation manifests show **justified lift** on held-out purged folds. STACK-WIRING Phases 0–5 must close first so producer→UI wiring is trustworthy before edge claims.

  **Trigger:** `go stack-wire-6-edge` after `go stack-wiring-integrity-signoff` + operator review of ablation backlog. **Deliverable (future):** `governance/EDGE_MEASUREMENT_FRAMEWORK.md` or extension rows in `STACK_WIRING_INTEGRITY_MAP.md` under a fifth anchor **Edge / ablation**.

**Already closed (do not re-open; verify in wiring map only)**
- Coherence tier-1/1.5: `time_et`, `fusion_contract`, `numeric_contract`, REPO_SWEEP EP/MT, MADA, LRC, FP1 + fixture completeness, MHMLB-NS1, LIVE_UI_INTEGRITY_V1 @ `5994aeb`, SWEEP-LRC-NAN, B2 render guards / tier-A blocks, COH-I-A/E/J, FIND-STACK-DIR1, etc. (see `[x]` rows above).

**Process (this program)**
1. One canonical commit per paired-fix slice; docs-only SHA pointer follow-up (LIVE_UI / LRC-NAN pattern).
2. Brief §5 cone non-empty; §6 tests at implementation SHA; server.py FINDs filed before UI behavior changes where transport is root cause.
3. **Schwab closure bar** — superseded `25cb2e3`: scoped register (gitignore + `SCAN_SCOPE_EXCLUDE_PREFIXES`) replaces the legacy three-PR gate (governance pin → CI diff-emission gate → full-tree scanner regen) for D17 admissibility. CI diff-emission (`schwab-csv-first.yml`) and per-PR meta pin still binding for new market-fact emission. STACK-WIRING remains **operator-truth** gate, not governance pin replacement.

### COHERENCE-AUDIT workstream (full Read — not “files already walked”)

**Operator decision (2026-05-19):** Default **Path A** unless overridden — pause calibration widen after `3177fdd`; TIER-1 paired fixes first; then ~30-file full-Read audit; calibration resumes on audited foundation. **Do not** backfill calibration widely while DST drift may taint `et_*` / session gates (~8 months/year).

**Brief schema (every file):** identity → FIND/OBS → **cross-cutting (mandatory)** → display contract → freshness contract. Batch (~5 files) → consolidate coherence map. End state: operator scenarios (ES dump/rip 2m, RTH→AH, DST boundary, vol spike) as regression bar.

| Lane | Files (full Read queue) |
|------|-------------------------|
| UI render | `static/index.html` (full), `static/*.js`, partials |
| UI routes | `server.py` (full), all `/api/*`, SSE/WS, cache/shaping |
| Time & session | `v2_decision/a2_eod_force_exit.py`, `timeframe_config.py`, session-bucket logic; trace all `et_*` producers |
| Decision authority | `v2_decision/*`, `build_module_a_a1_decision`, `expression_profile*`, `a2_*` |
| Signal recompute | `features/signal_layer_v1.py`, `inference_snapshot.py`, `monte_carlo_stack_input.py` |
| Fusion math | `bayesian_fusion.py`, `mc_fusion_adjustment.py`, `multi_horizon_ml_bundle.py` |
| Position sizing | `call_engine` sizing paths, `math_exposure.py`, `math_decay.py`, `math_levels.py` |
| Lifecycle / exits | `lifecycle_rule_core.py`, `realized_contract_eval` exit sim, same-bar policy |
| Market state | `market_state.py`, `recommend_option_expression`, ms_dict contract |
| Snapshot writer | snapshot INSERT path, schema / migrations |
| Setup readiness | `setup_readiness.py`, call/put readiness mirrors |
| Order flow | `order_flow_engine.py` (coherence re-read), OF → stack vote path |
| Inputs builder | `build_market_state`, `SignalInput` population |

**Path options**

| Path | When | Note |
|------|------|------|
| **A (recommended)** | Now | TIER-1 @ `99ea0e0` → TIER-1.5 (float + triplet) → COH-SA sweep → full audit → resume Layer 5 / calibration |
| **B** | Now | Interleaved audit + calibration (higher context cost) |
| **C** | After Pilot | Risks DST-tainted backfill + rework |

**TIER-1 pull-forward:** COH-I-A/E/J closed @ `99ea0e0` (+ `50405b8` OPEN_ITEMS). Optional same batch still open: LIVE-UI-D, LIVE-UI-E, LIVE-UI-B.

### COH-SA — single-authority audit lane (operator 2026-05-19)

**Framing:** Single-authority is **not** repo-wide today — it is case-by-case. COH-I-A (`time_et.py`) is the template: (1) inventory every derivation site, (2) group by concept, (3) one helper + module, (4) redirect callsites. Escalate when a **second** implementation of the same concept has **different semantics**, not only when one file is internally consistent.

**Already single-authority (verified / walked):**

| Concept | Single source |
|---------|----------------|
| `NON_TRADABLE_CANONICAL_PROVENANCE` | `signal_types.py` L195–203 — imported by call_engine, signals |
| `TRUSTED_PREDICATE_SQL` | `calibration/trust.py` — all four calibration tools |
| `ticker_storage_key()` | `instrument_identity.py` — FIND-BO1 backfill_outcomes |
| `enforce_calibration_decision_log_only_1m()` | `calibration/canonical_enforcement.py` |
| `CANONICAL_FEATURE_CONTRACT_VERSION` / timeframe | `features/canonical_contract.py` |
| `ADVISORY_V2_*` | `calibration/v2_advisory_backfill.py` — v2_live_logging imports |
| `CANONICAL_TIMEFRAME` | `timeframe_config.py` — `lstm_data` re-exports; `shared_sequence_context` imports via `lstm_data` (aliased, not a second definition) |

**Gap inventory (not single-authority — COH-SA sweep):**

| Concept | Multiple sites | Risk | Priority |
|---------|----------------|------|----------|
| **ET derivation** | server, db, ml_scheduler, v2 A2, ad-hoc ZoneInfo | DST / session drift | **Closed @ `99ea0e0` + COH-SA-2** (`time_et.py` sole `ZoneInfo("America/New_York")` + `now_et()`) |
| **Float validation** | 10+ duplicate `_float_or_none` (lifecycle, live_decision_bundle, v2_a1_*, …) | NaN/inf still accepted at non-redirected sites | **Partial @ `31c4f45`**; COH-SA sweep |
| **Direction from triplet** | stack display + argmax sites + fusion | Fourth inference path drift | **Closed @ FIND-STACK-DIR1** — stack uses `direction_from_triplet` only; rglob @ `d9a3f3c` |
| **Fusion availability** | signals, call_engine, prediction_engine, … | Drift on `available` gate | **Closed — COH-SA-3** (`fusion_contract.fusion_is_authoritative`) |
| **Tradability predicate** | frozenset in `signal_types`; membership inlined | Drift on placeholder provenance | **Closed — COH-SA-3** (`fusion_contract.is_canonical_tradable`) |
| **Replay max-hold bars** | was split across call_engine + realized_contract_eval | Live vs replay drift | **Closed — COH-I-K** (`replay_hold_bars.py`; historical 30-bar rows note in tier-2 item) |
| **Magic thresholds** | Per-module inlines (call_engine, signal_layer_discrimination, …) | Policy drift | COH-SA (document or config table) |
| **Regime multipliers** | was inline in `compute_position_size` | Policy drift on regime scale | **Closed — COH-SA-5** (`position_sizing_policy.regime_size_multiplier`) |

**COH-SA run order (additive to Path A):**

1. **TIER-1** — COH-I-A/E/J @ `99ea0e0` (done).
2. **TIER-1.5** — `numeric_finite.py` (or `calibration/numbers.py`): one `float_or_none` with explicit modes (`finite`, `positive`, `non_negative`); redirect four helpers; golden tests on edge inputs (NaN, inf, 0, −1).
3. **COH-SA full sweep** — remaining rows + repo-wide gap inventory for operator-visible state (brief schema: FIND/OBS + cross-cutting).
4. **Then** full ~30-file COHERENCE-AUDIT **or** resume calibration (operator choice).

**Deliverable for COH-SA close:** `governance/coherence_single_authority_inventory.json` (or markdown) — concept → canonical module → callsite list → closed/open.

**Calibration walk status:** `backfill_signal_layer_v1_bundle` signed @ `3177fdd`. **Paused** for path choice. **Not invalidated** — deprioritized until coherence gate.

---

## Current track (signed 2026-05-18)

**Full plan:** [`governance/PILOT_1_SCHWAB_WALK_AND_AUTHORITY_UX_STAGING.md`](governance/PILOT_1_SCHWAB_WALK_AND_AUTHORITY_UX_STAGING.md) — operator + Claude + Cursor aligned. **Motto:** honest, consistent, traceable UI from real data; edge proven separately.

| Track | Status | What |
|-------|--------|------|
| **TRACK 1 / NOW** | Active | Schwab V4 file-by-file walk (primary daily thread). Next spine files: `multi_horizon_decision.py` → `bayesian_fusion.py` → `signals.py` → `market_context.py`. Walk commits only — no Phase 2 UI mixed in. |
| **TRACK 2 / NEXT** | Gated | One PR: desk headline `final_confidence`, v2 adapter + Decision Command + hz breakdown. After TRACK 1 items above walked; operator says **go Track 2**. Includes `market_state.py` ~1420 `or 0.0` fix (I-01). |
| **TRACK 3 / LATER** | Planned | Pilot 1B A2 per blueprint. |
| **TRACK 4 / DEFERRED** | Gated | Four parallel horizon stacks + four Calls (L145/L147). After TRACK 2 + horizon honesty + retrain plan + go/no-go. |

**Trigger chunk 1:** `signed, go multi_horizon` on `multi_horizon_decision.py`.

---

## GOVERNANCE REBUILD STATUS

### Standard

V3.0 Institutional Standard is locked. See `governance/INSTITUTIONAL_STANDARD_V3.md` and `governance/V3_LOCK_RECORD.md`. The standard governs the entire system from the lock effective date forward. Amendments follow the V3.X / V4.0 path defined in the standard's Section 20.

### Research decision engine framework (pilot v1.1)

Research-path (non-production) specification for the replacement-core pilot: **`governance/Framework-ED-Decision-Engine-v1.1.md`**. It is **bound** to **`research/pilot_step3/prereg_v1.json`** using the prereg **`content_hash`** (must match the framework footer), **`framework_doc_id`**, and **`framework_doc_version`**. **`research/pilot_step3/pilot_config.load_prereg()`** enforces both body hash and framework binding via **`validate_prereg_integrity`** (hard-fail on mismatch). One-page rationale digest: **`governance/v1.1-rationale-summary.md`**.

### Conformance audit

Lock Condition 1 satisfied. See `governance/V3_CONFORMANCE_AUDIT.md`.

Result distribution across 32 evaluated rows:
- CONFORMS: 2
- DOES_NOT_CONFORM_TRACKED: 17
- DOES_NOT_CONFORM_NEW_GAP: 15

Four of the 15 new gaps are HIGH urgency and constitute a new infrastructure governance workstream (see below).

### Two workstreams (parallel, not sequential)

The rebuild work splits into two workstreams. They are orthogonal: different domains of risk, different failure modes, different validation paths. They run in parallel.

Governing rule: no infrastructure gap may be allowed to invalidate production claims. If an infrastructure invariant is not fully enforced, the corresponding production claim must be explicitly bounded or withdrawn. This is enforced by the V3 lock record's no-silent-non-conformance condition.

#### Workstream 1: Model Lifecycle

Goal: model correctness, feature integrity, statistical edge, training and evaluation discipline.

| Phase | Title | Status | Plan / Result |
|-------|-------|--------|---------------|
| G1 | Canonical contract draft | COMPLETE | `governance/G1_DIAGNOSIS.md`, `governance/G1_ADDENDUM_TRAINING_DEPENDENCY.md`, `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md` |
| G2 | Cascade alignment | PAUSED | `governance/G2_PLAN.md` (original; paused pending v2.0 framework decision) |
| G3 | Governed path contract unification | PENDING | depends on G2 |
| G4 | Direct-write quarantine | PENDING | depends on G3 |
| G5 | End-to-end proof | PENDING | depends on G2-G4 |

G2 pause state:
- G2 is paused pending the `Framework-ED-Decision-Engine-v2.0` decision.
- If the maximum-edge v2.0 architecture is rejected, the G2 plan as written remains valid for the existing parallel/cascade architecture and may resume.
- If the maximum-edge v2.0 architecture is adopted, rewrite G2 as `G2.v2` against the new artifact contracts before implementation.

Deferred to G4 within this workstream:
- G4-1: server-side active sync helper (`server.py:4426-4453`) bypasses governance during request handling. HIGH risk.
- G4-2: five tool scripts write directly to `models/active/` outside governance.
- G4-3: scheduler fail-open behavior at `ml_scheduler.py:1701-1707` and `ml_scheduler.py:2133-2135` allows exit 0 with incomplete artifacts. **Addressed PR2** (`4375c58`): `TrainingOutcome` enum, core exit aggregation, partial-bundle gate, governed `failed_closed` → `eval_failed`, cache-skip cap.
- G4-4: dormant scheduler auto-copy path at `ml_scheduler.py:1780-1783`.

G2 plan refinements (proposed during V3 standard development, not yet applied to `governance/G2_PLAN.md`):
- Architectural invariant statement (cascade meta MUST NOT read parallel paths)
- Runtime path validation in cascade meta block
- `validate_trained_candidate()` runtime contract enforcement (cascade and parallel symmetric)
- LSTM cache invariant note from `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md`
- `test_parallel_vs_cascade_artifact_equivalence` test
- Manifest as REQUIRED clarification
- New sub-phase G2.0 runtime trace (resolves residual UNKNOWN about `_model_dir_for_ticker` resolution)
- Reference to `governance/G1_ADDENDUM_TRAINING_DEPENDENCY.md` in plan's architectural reference section

These refinements remain attached to the paused G2 plan. Do not apply them while G2 is paused; resume them only if the existing parallel/cascade architecture remains the governed target.

##### G3 Reconciliation Queue

Classification: RECONCILIATION (not new gap). Items where two or more existing implementations disagree about a contract, identified during G1 investigation. To be resolved as part of G3 (governed path contract unification).

- **G3-R1: Active validator vs runtime fallback completeness mismatch.** `verify_active_models.py:100-152` enforces one definition of "complete active bundle" (strict, all artifacts required). `ml_predict.py:1291-1294` enforces a different definition (tolerates missing meta with fallback). The two checks disagree on what counts as a valid active model. Invariants violated: I-01 (no silent degradation), I-05 (train-serve feature identity), I-15 (tuple health before trade impact). Status: PENDING. Resolve in G3.

- **G3-R2: `promotion_decision` field is non-authoritative.** `training_cache.py:980, 1029` writes a `promotion_decision` field into candidate manifests. No code path consumes this field as binding for promotion decisions. The field exists, implies authority, but is informational only. Invariants violated: I-02 (single promotion authority), I-14 (attributable change). Status: PENDING. Resolve in G3 by either removing the field or wiring it as authoritative.

- **G3-R3: Lineage horizon mismatch blocks governed evaluation.** Governed evaluation pass fails with `EvaluationLineageError` when manifest horizon does not match expected horizon (observed: manifest `'1c'` vs expected `'5c'`). Source: `arch_competition/lineage.py:29-87` and `arch_competition/eval_runner.py:229-236`. Consequence: `models/arch_competition/` does not exist on this installation because the governed evaluation pass has never successfully produced output. This is why peer-competitor evaluation is not currently operational. Invariants violated: I-10 (reproducible training identity), I-11 (evaluation integrity). Status: PENDING, hard blocker for governed evaluation. Resolve in G3 — unblocks the entire downstream G3-G5 chain.

#### Workstream 2: Infrastructure Governance

Goal: runtime guarantees, system integrity controls, failure containment.

First-class governance gaps. Not secondary, not supporting work. Created from V3 conformance audit findings that did not fit into the model lifecycle phase plan.

| Item | Invariant | Audit row | Urgency | Status |
|------|-----------|-----------|---------|--------|
| INF-1 | I-17 deterministic inference | DOES_NOT_CONFORM_NEW_GAP | HIGH | PENDING |
| INF-2 | I-19 clock synchronization health | DOES_NOT_CONFORM_NEW_GAP | HIGH | PENDING |
| INF-3 | I-20 dependency pinning in serving path | DOES_NOT_CONFORM_NEW_GAP | HIGH | PENDING |
| INF-4 | §14.6 kill switch tri-level halt control | DOES_NOT_CONFORM_NEW_GAP | HIGH | PENDING |

Other 11 NEW_GAP rows (medium urgency) are listed in `governance/V3_CONFORMANCE_AUDIT.md` and will be folded into future phase planning outside Workstream 2 scope (see `governance/PHASE_PLAN_INFRASTRUCTURE.md` §14).

Workstream 2 phase plans: **ACTIVE** — `governance/PHASE_PLAN_INFRASTRUCTURE.md` (INF-1–INF-4 execution, proof, closure, governance events), `governance/PHASE_PLAN_TARGET_STATE.md` (strategic P0–P7 target state and gap map), and reviewer index `governance/INFRASTRUCTURE_GOVERNANCE_LOCK_PACKAGE.md`. Implementation in this workstream must follow those documents per the working discipline (no code without a phase plan).

### Tracked concerns (do not block either workstream)

Findings from G1 investigations recorded for future review. Each is bounded as not blocking, with citation.

- TC-1: Cascade LSTM `xgb_probs_list != ds.n_samples` fallback at `ml_scheduler.py:1010-1024` may silently degrade cascade-LSTM into parallel-LSTM behavior. Frequency unknown without runtime instrumentation. Source: `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md`. Not blocking G2.
- TC-2: `force_retrain` active compliance check at `ml_scheduler.py:1737-1741` runs only when `hz_sched == DEFAULT_ML_HORIZON_SLUG` (1c). Other primary horizons skip it. Promotion-related, not training-related. Source: `governance/G1_ADDENDUM_CACHE_CONSISTENCY.md`. Track for G3 review.

### Deferred items from lock record

- D-1: Regime awareness invariant. Reconciled at the vocabulary level in `governance/INSTITUTIONAL_STANDARD_V3.md` by defining `regime` as a controlled term. Any new regime-aware trade-impacting behavior still requires a governed framework/plan before implementation.
- D-2: Audience separation invariant. Deferred at V3.0 lock per `governance/V3_LOCK_RECORD.md`; reconsider in a future amendment cycle.

### Pre-existing technical debt

- Strict mode option (b) refactor: `ED_XGB_STRICT_ACTIVE_ONLY` defaults to `"1"` in `ml_predict.py:209`. Currently using option (d) wrapper in `ml_scheduler.py` for three candidate-inference sites (committed in 2524770). Coverage gap: `train_all.py:211/216/220`, `transformer_model.py:229`, `features/shared_sequence_context.py:46`, `arch_competition/stack_bundle_eval_v1.py:446`. Proper fix is option (b): thread explicit `strict_active_only` parameter through `_model_dir_for_ticker`, `_load_*`, `_predict_*`. Estimated 4-8 hours, ~140-260 LOC across ~8-12 files. To be addressed after model lifecycle workstream G4 completion.

### Tooling provenance

All commits in this rebuild authored via Cursor agent extension carry a `Made-with: Cursor` trailer in the commit message body. This is hardcoded in the Cursor application bundle (`cursor-agent/dist/main.js`) and cannot be disabled from this repository or from git config. The trailer is treated as known tooling provenance, not silent substitution. Future commits authored through Cursor will continue to carry the trailer.

## Horizon honesty + retirement program (adopted 2026-05-17)

Reference ticker for parametric tests: **SPY**.

| Phase | Scope | Status |
|-------|--------|--------|
| **A** | Decouple 4 primary M cards — `UNAVAILABLE` + `PRIMARY_HORIZON_DATA_MISSING` when native horizon data missing; no silent 3c/8c/13c substitution | **Done** (`c8a3b0b`) |
| **2** | `verify_active_models.py` — 4×3 slots for production tickers | **Done** (2026-05-17 run; see Universe model coverage below) |
| **B** | Stop producing 3c/8c/13c (signals payload, ml_predict loop, `SECONDARY_SUPPORT_HORIZONS = ()`) | **Done** (`eab7ff2`, `4010965`; schema/code residue cleared in **D**) |
| **C** | 4-primary regression vs legacy 7-horizon path | **Done** (`89e3ddc`; C1 `eab7ff2`, C2 `4010965`, C3 tier-contract gaps) |
| **D** | Schema drop `outcome_3c/8c/13c` (+ pts) after backup | **Done** — D1 `87bb131`, D1 amend `75aa9eb`, D2 `062f02a`, D3 **applied** on canonical DB 2026-05-18 (`ddl_column_delta: -69`, 198362 rows preserved); audit `governance/audits/snapshots_schema_drop_retired_horizons_v1_20260518_035734.json` |
| **E** | Residue cleanup: fail-closed `ml_predict`/`signals` (no silent 0.33), quarantine 7-horizon tools, `timeframe_config` trim, root demo + normalizer doc | **Done** — E(c) `83b02fb`, E(c.1) `22cd294`, E(a) `794862d`+`216b96b`, E(b) `95c07fc` |

## Universe model coverage (Phase 2 verify — 2026-05-17)

- [ ] **CRWD partial-bundle**: missing all 4 lstm + 60c transformer. Run `ml_scheduler.py --run-now --force-retrain` for CRWD. ~1–2h.
- [ ] **27-ticker NON-COMPLIANT backlog**: ASTS, GOOG, MET, MRVL, MU, NFLX, PCG, PLTR, RKLB, SMCI, TSL, $VIX, AEIS, BBIO, BE, CDE, CRDO, FN, KRE, KTOS, NXT, PSCI, SATS, STRL, WMT, XBI, XRT — never trained (bundle dirs missing). Universe-expansion workstream; not a Phase A/B/C/D/E blocker (Phase A UNAVAILABLE is honest).
- [x] **Production tickers (~13 inc. SPY/QQQ/$SPX)**: all 4×3 model slots present (verified Phase 2 run 2026-05-17 post-`c8a3b0b`).

## Critical — label vs presentation

- [ ] **`outcome_13c` vs product “15m”** — **Partial (2026-03-27):** → rolled into **Phase B–E** above `outcome_15c` / `pred_15c` columns + fill window + prediction/UI prefer **15×1m** with honest fallback to **13c** when sparse. **Still open:** retire 13c from training/UI after backfill + full retrain; **`outcome_filled` now requires 15c** — very old stuck rows may need one-time DB fix.
- [ ] **`60m` column semantics** — Primary product horizon is **`outcome_60c`** (60×1m). Still open: codify when 60m card uses MC/fusion vs empirical-only (no 8c/13c stand-ins after Phase D).
- [x] **8c (~8m) vs product set {1,5,15,60}** — **Retired** Phase D/E (`outcome_3c/8c/13c` schema drop 2026-05-18; governed horizons = 1c/5c/15c/60c only). Residual mentions: legacy tools/tests/audit only.
- [ ] **Prob grid fallback vs `prediction_engine`** — → **Phase A** (primary-only `horizon_prob_bars` keys) + **Phase 7** retrain UI fallback row and disclaimer can describe **8c** while engine path may **reuse 13c** for the “60m” slot when MC/fusion off. **Reconcile** so disclaimer, fallback, and `horizon_prob_bars` **always agree**.

## Stack / training / UI alignment

- [ ] **[TRACK 4 / DEFERRED] Four parallel stacks (1 / 5 / 15 / 60)** — → **Phase 7** (post-A/B) Implement **per-horizon** training targets, inference, and stack votes (not one head smeared across mismatched labels). **Retrain** after schema alignment. Gate: [`PILOT_1_SCHWAB_WALK_AND_AUTHORITY_UX_STAGING.md`](governance/PILOT_1_SCHWAB_WALK_AND_AUTHORITY_UX_STAGING.md) Phase 4.
- [ ] **Training horizons vs UI** — Add **`15c`** to `ml_train.HORIZONS` (and `audit_model_readiness` XGB pred columns) **when you retrain** so `rules_15c_*` match shipped model feature count; `pred_15c_*` is already persisted from the prediction card for training rows.
- [ ] **[TRACK 4 / DEFERRED] Four horizon-specific Call payloads** — Surface **one call per product horizon** (or primary + three secondaries) **after** probabilities/stack votes are **honest per H**. (Useful; depends on items above.)
- [ ] **Candidate inference strictness scope (Option D)** — `ml_scheduler.py` now uses a scoped context manager to set `ED_XGB_STRICT_ACTIVE_ONLY=0` only during candidate-model inference (parallel eval, cascade eval, parallel meta assembly), with guaranteed restore afterward. Keep live serving strict-active-only fail-closed by default; retire this scope helper if candidate prediction stops reusing `ml_predict` active-path resolution.

## MC / fusion behavior (clarity + policy)

- [ ] **Document when MC and fusion are off** — Codify: missing deps, config flag, insufficient samples, warm-up, explicit “empirical-only” mode, failure fallback. Ensure UI **shows mode** (not silent wrong horizon).
- [ ] **Decide default policy** — e.g. **prefer fusion/MC on** when healthy; **never** silently label fallback empirical bars as “60m” if they aren’t.

## Context / data

- [ ] **Index futures** — Env-based (`ED_FUTURES_*`) wired; confirm Schwab contract symbols per roll; optional: auto-roll or admin doc.

## Schwab V4 Universal Coverage (register pipeline)

**[TRACK 1 / NOW]** — Primary daily thread per [`PILOT_1_SCHWAB_WALK_AND_AUTHORITY_UX_STAGING.md`](governance/PILOT_1_SCHWAB_WALK_AND_AUTHORITY_UX_STAGING.md). Next spine walks: `multi_horizon_decision.py`, `bayesian_fusion.py`, `signals.py`, `market_context.py`.

**Canonical tracker for deferred Schwab register work.** (Scanner walk scope was tightened 2026-05; CI still pins a **partial** mock register — see `governance/artifacts/schwab_v4_register_build_meta.json` `scanner_flags`.)

- [ ] **Full pruned-tree rescan** — Run `python -m tools.schwab_universal_coverage_scanner_v3 --embedding-mode mock` with **no** `--max-files` once there is wall time; commit `governance/artifacts/schwab_v4_register_build_meta.json` + `governance/artifacts/schwab_v4_scoreboard.json` so pins match the **whole** repo under current walk excludes (`tools/schwab_universal_coverage_scanner_v3/paths.py`).
- [x] **`d17.replaced_count` vs perf_proof (14 vs 12 drift)** — Scanner fix SHA `3000fb9` (cross-pattern surface dedup + merge surface guard + cross_validate coverage). Post-regen: `replaced_count_d17=10`, `delta_replaced_count_d17=-4`, `server.py:4478` REPLACED=0. Register_id instability vs perf_proof bundles: resync via `tools/stream_revert_v4_register_and_sync_perf.py --sync-only` → `replacements_landed/with_perf_proof=10/10` (10 REPLACED rows, 4 bundles; market_state bundle 0 rows on partial scan). Perf_proof + meta + scoreboard pin SHA: `77b6991`. Register CSV gitignored.
- [ ] **Register CSV sunset** — Program-level: move D17 invariants off the universal line-register when a scoped static gate exists; until then CSV stays gitignored (see `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.md`).

### Repo hygiene / size reduction (deferred — after Schwab disposition walk + V4 gate)

**Sign-off (2026-05-18):** `static/index.html` disposition walk complete (chunks 1–7b, 512 slice rows + voice checkbox amend). Commit-range drift audit: no missing market canopies beyond voice fix. **Phase B authorized** — proceed with dead-code cleanup below.

**Do not start Phase B until sign-off above.** (Met.) **Not** during an open chunk or mid-register regen.

**Safe anytime before then (local only, no commit required):** delete scratch and backups that are not cited by an open ticket — `backups/db/*.db`, `caps_*.txt`, `dry_run_*.json`, `static/mockups/` if design compare is done.

| Phase | When | What to remove / trim |
|-------|------|----------------------|
| **A — working tree** | First cleanup commit after disposition gate opens | Untracked scratch (`caps_*`, `dry_run_*`, extra `governance/audits/*` not tied to closure); local **~4 GB** `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` if slice CSVs for finished chunks are committed (slices are the auditable export). |
| **B — dead code + tools** | After walk sign-off (2026-05-18) | **Landed in working tree** (`tools/_phase_b_index_html_cleanup.py`): ~1.5k lines removed from `static/index.html` — orphan `.call-card`/`.mh-*`/`.mhap-*`/`.wds-*`/`.of-*` CSS, acc-chart / cum-delta / `renderMultiHorizon`, `render()` Right Now→WTDS block, `renderCharmDriftRow` + `__renderCharmDriftRowLive`, fast-lane OF overlay to orphan DOM, override-btn listeners/CSS. **Operator:** SPY hard refresh + 4-anchor smoke. Commit when ready. |
| **C — post V4 closure** | After program closure / `O-XX` sign-off | Old scan artifacts, superseded governance drafts (only if nothing cites them), duplicate audit JSONs. |
| **D — git history** | Separate deliberate PR only if `.git` is huge from **committed** blobs | History rewrite (e.g. remove committed DBs/large files) — **not** the same as deleting local untracked files; requires operator sign-off and force-push policy review. |

**Deliverable:** one or more labeled cleanup commits (`chore: repo hygiene phase A`, …) with a short manifest in the commit body (paths removed, approximate size saved). **Do not** mix hygiene deletes with disposition/register commits.

---

## Schwab repo-wide replacement — post-KEY LEVELS sweep schedule

**SUPERSEDED 2026-05-16** — day-by-day plan replaced by section-by-section structure below. Completed day commits stay in the branch as a regression safety floor (see CAPS and per-day pattern gates). They do NOT count toward section closure — see 'Why prior commits do NOT count' below.

~~**Bound to:** `governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`. Each day below closes the cited register IDs with a real on-branch SHA.~~

- [x] **Day 1 — OHLCV / bar adapters** — DFR-009, DFR-011, MT-006, MT-007, PQ-009, PQ-010 + DFR-018 re-audit. Files: `market_data_adapter.py`, `snapshot_normalizer.py`, `liquidity_value_engine.py`. Kill zero-injection; reject incomplete Schwab candles; tag synthetic 1m bars. SHA: `03ca199`
- [x] **Day 1.5 — OHLCV pattern repo-wide** — DFR-009/011/018/MT-006/007/PQ-009/010 repo-wide. Files: `server.py`, `math_levels.py`, `math_exposure_core.py`, `math_probabilities.py`, `news_sentiment.py` + repo-wide grep test. `bucket_metric()` fail-closed; ALLOWLIST for manifest/counter paths. SHA: `17ccf30`
- [x] **Day 1.6 — silent-zero pattern family** — extends Day 1/1.5 to `.get(x) or 0`, `int(x or 0)` variants; `math_levels`/`math_exposure_core` bucket_metric completion; 30+ file allowlist. SHA: `c4825cc`
- [x] **CAPS — comprehensive anti-pattern sweep** — full silent-default family; `tools/anti_pattern_sweep.py`; register allowlist; `lstm_data` zone/vwap sentinels; Schwab chain fail-closed in `math_levels`. SHA: `cab3ef4`

### Layer 4 fail-closed — Action 11 (`feature/institutional-key-levels`)

- [x] **Action 11.1–11.4b (helpers)** — `math_levels`, `math_exposure`, `math_probabilities` fail-closed on missing chain/quote inputs. SHAs: `0d946f8`, `0edebc3`, `4eeba65`, `86750e7`, `1fc5ce7`, `a00e78e`
- [x] **Action 11.1d — `compute_beta` R² residual** — `r_sq` returns `None` when ticker variance `< 1e-12`. SHA: `4d262d6`
- [x] **Action 11.3 — `server.py` ms_dict consumers** — drop `.get(key, "neutral"|"negligible"|0.0)` fallbacks so snapshots persist NULL when helpers return None (includes `sector_risk_signal`, DPI, charm pre-init, IWM, smart money, flow). SHA: `bfe67fd`
- [x] **Action 11.3b — ms_dict EM/iv_skew/level_density/compliance + helpers** — 9 residual `.get` sites + `compute_em_progress` / `compute_iv_skew` / `compute_level_density` / `compute_iv_model_spread` / `compute_volume_oi_ratio` fail-closed when inputs absent. SHA: `a2cc6f7`
- [x] **Action 11.5 — `compute_net_charm` when contracts_used==0** — `math_exposure_core.py` returns `charm_direction`/`charm_magnitude`/`net_charm_daily` None when `contracts_used==0`; emits `charm_magnitude` band when contracts contribute. SHA: `723af2b`
- [x] **Action 11.6 — `server.py` vol_oi / iv_model_spread label defaults** — bundled in 11.3b with helper fail-closed (`compute_volume_oi_ratio`, `compute_iv_model_spread`). SHA: `a2cc6f7`
- [x] **Action 11.7 — hedging-flow charm normalization** — `server.py` passes `charm_normalized=None` when `_charm_net` is None so `compute_hedging_flow_score` partial-renorms without fabricating 0. SHA: `1a68229`
- [x] **Action 11.10 — bayesian_fusion.py FusionPayload + directional fabrications** — core in `1a68229`; tail: `_resolved_regime_label`, skip `evidence.get` neutral default, support attrs, `_model_dominant_class`, direct `posteriors[...]` emit. SHA: `f19168c`
- [x] **Action 11.11 — monte_carlo.py mc_feature_dict + regime inputs** — omit missing MC features (no `or 0.0`); `regime`/`regime_confidence` None passthrough to baseline sigma. SHA: `1a68229`
- [x] **Action 11.12 — regime_engine.py zero-evidence primary + zone_since_bars** — return `_unknown_regime()` when `max(scores)<=0`; breakout fresh-zone skip when zone bars unknown. SHA: `f19168c`
- [x] **Action 11.13 — mc_fusion_adjustment.py normalize_mc** — return `None` when any MC feature missing; skip post-fusion adjust when fusion triplet incomplete. **Residual:** `_triplet` uniform on degenerate input (internal renorm only). SHA: `1a68229`
- [x] **Action 12.0 — Layer 5 upstream fail-closed (batch 1)** — umbrella for 11.7 + 11.9b + 11.10/11.11/11.13 above + `signals.py` canonical_forecast/MC regime/fusion display (`fusion_confidence` None default at L828). SHA: `1a68229`
- [x] **Action 12.1 — prediction_engine.py fusion/empirical blend + narrative** — `_fusion_snap_triplet`; empirical fallback when fusion directional missing; narrative None-guards. SHA: `4d262d6`
- [x] **Action 12.2 — multi_horizon_decision.py probability fabrications** — `_norm_triplet`/`_safe_prob_optional`; no `mins_to_close`→180; canonical blend requires full triplet. SHA: `4d262d6`
- [x] **Action 12.3 — volatility_regime.py default policy fabrications** — no fabricated `vix_chg_abs`; default path `trade_permissive=False`. SHA: `4d262d6`
- [x] **Action 12.4 — rules_engine.py zone_since_bars** — None-guarded zone bar alerts. SHA: `4d262d6`
- [x] **Action 12.5 — news_sentiment.py timeout/unavailable fabrications** — unavailable→`None` flags/impact; timeout path not fake LOW. SHA: `4d262d6`
- [x] **Action 12.6 — micro_structure.py + liquidity_value_engine.py fail-closed** — removed `spot=500.0` defaults; sweep level None-skip; `_cluster_reference_price` (no `500.0` ref); `auction_interp`/`session_bias` no fabricated `"neutral"`; PDL/PDH guards without `or 0`. SHA: `5d74699`
- [x] **Action 12.1b — prediction_engine.py residuals** — `_pack_horizon_row` uses `_tri_probs` (no `0.33`/`0.34`); DB-missing card + `probs_5c is None` → `None` empirical fields; enrichment narrative guards incomplete triplets. SHA: `ab06072`
- [x] **Action 12.2b — multi_horizon `_infer_trade_mode` fail-closed** — `mins_to_close` missing/invalid → `None`; synthesis `mode="unknown"`; `_primary_order_for_mode` intraday default stack without fabricating mins. SHA: `ab06072`
- [x] **Action 12.7 — market_state.py signature fail-closed** — `et_hour`/`et_minute`/`mins_to_close`/`charm_*`/`iv_direction` defaults → `None`; no `confluence_total=4` getattr fallback; `SignalInput` time fields `None` default. SHA: `76a1359`
- [x] **Action 12.8 — features/fusion_policy_contract.py fail-closed** — `fusion_payload_to_policy_columns`: no `1/3` prob defaults or `or 0.0` on missing fusion (fabricates `fused_move_prob=1.0` when `prob_flat` is None); unavailable/incomplete fusion → `None` policy prob columns + audit status string. SHA: `141da15`
- [x] **Action 12.9 — static/index.html UI fail-closed consumers** — remove `iv_direction || 'flat'`, direction `'flat'` fallbacks, `confluence_total`→9, charm `|| 0` neutral fabrication; show `—`/withheld when producers emit null. SHA: `2f741e3`
- [x] **Action 12.10 — features/regime_mvp_context.py mvp_vwap_side fail-closed** — no fabricated `"above"` when `anchor.vwap_side` missing/invalid; `Optional[str]`; rules_engine range branch waits when None. SHA: `cafe8f0`
- [x] **Action 12.11 — features/parallel_stack_schema.py fail-closed** — `empty_parallel_output` no 0.33/0.34 triplet or `"flat"`/`0.0` confidence; `build_parallel_base_output` requires complete triplet; `ml_predict` parallel records None probs when unavailable. SHA: `aa13245`
- [x] **Action 12.12 — fusion_model_input similar_setup_filters None passthrough** — no `"unknown"` zone/vwap SQL keys; `db.get_similar_setups` skips to tier 4/5 when filters None. SHA: `9ed32af`
- [x] **Action 12.13 — features/signal_layer_v1.py fail-closed MTF + direction probs** — `mtf.trend_5m_from_1m_sign` / `mtf.bias_15m_from_1m_sign` / `mtf.alignment_state` → `None` when insufficient aggregated bars; `signal_layer_v1_to_direction_probs` → `None` when `meta.n_bars < 25` (no uniform 1/3); MTF terms skipped when missing; `layer_direction_policy` None-aware; `bayesian_fusion` skips blend when triplet is `None`; tests `test_action12_13_signal_layer_v1_fail_closed.py`. SHA: `47e7ccf`
- [x] **Action 12.14 — calibration/signal_layer_discrimination.py fail-closed fusion audit** — no uniform 1/3 on missing `fusion_json`/`prob_*`; `fusion_n_present`/`fusion_n_missing` counts; means/stds `None` when no valid triplets; `final_signal` None → `missing` bucket (not `"wait"`); tests `test_action12_14_signal_layer_discrimination_fail_closed.py`. SHA: `c66cd23`
- [x] **Pilot 1 Schwab walk — disclosed FINDs (2026-05-19, chunks 3-N)** — All concrete FINDs closed in chunk-3..N follow-on commits (see SHA cites on each [x] child below). Two remaining [ ] children are REAL-GATE: `FIND-PSS1` telemetry-gated (production data needed to validate uniform-triplet tiebreak prevalence); `FIND-PSS2` accepted-as-designed (informational, no code change). Reconciled 2026-05-24 as part of Deferral Reconciliation pass — title also normalized from "deferred FINDs" (label was self-referential) to "disclosed FINDs". Cross-linked from `governance/PILOT_1_SCHWAB_WALK_AND_AUTHORITY_UX_STAGING.md` closure section.
  - [x] FIND-OF3/OF4 — `_normalize(None)→0.0` silent neutral mass in `_compute_order_flow_score` (L768–791); fixed chunk-3: `_weighted_mean_present`, min 2 legs.
  - [x] FIND-OF5 — `_readiness(score, rvol)` uses `(rvol or 0) > 1.2` (L819); fixed chunk-3: explicit `rvol is None` → yellow when strong/moderate; `order_flow_readiness_rvol`.
  - [x] FIND-OF6 — exact-zero composite withheld from direction/labels (`_direction(0.0)→None`, `math_exposure._of_direction(0.0)→None`); weak deadband still `"neutral"`.
  - [x] FIND-OF7 — `compute_order_flow_verdict` exact-zero composite → `_verdict_unavailable()` after divide; ImportError path pre-closed 0edebc3 (Action 11.2).
  - [x] FIND-LVE1 — `cluster_price_levels_into_zones` ATR→percent fallback: chunk-2 `logger.info` when `clustering_mode="atr"` and `atr_value` unavailable (behavior unchanged).
  - [x] FIND-CE3 — `_validate_trade` 2c bare `except` now appends fusion posterior gate fail-closed reason (Layer 5 chunk-2B).
  - [x] FIND-CE4 — EAE gate `_stop_distance` uses `vol_regime.risk_multiplier` (matches sizing path).
  - [x] FIND-CE6 — `vol_regime is None` forces WAIT with labeled `wait_blocker` (Layer 5 chunk-2B).
  - [x] FIND-CE7/CE8 — `mins_to_close is None` → sizing NO_TRADE; time-warning guards + WAIT (no TypeError).
  - [x] FIND-CE1 — `_stop_distance` logs when `et_hour`/`et_minute` missing (mins_elapsed=0 default).
  - [x] FIND-CE2 — `_conviction_from_canonical_forecast` logs invalid confidence + `dominant_probability` fallback paths.
  - [x] FIND-CE9 — `call_readiness` and `put_readiness` exceptions → `log.warning` (surfaces in standard logs; put mirror landed post-9630bad).
  - [x] FIND-OF8 — `_of_sign(0.0)→None`; verdict agreement no longer casts zero cum_delta as neutral (chunk-4b / math_exposure).
  - [x] STYLE-LVE2 — tag matching `in tags` vs `in str(tags)`; **accepted disclosure** (intentional substring match for VWAP_* tags; no code change).
  - [x] Magic-threshold disclosures — POC 0.002, VWAP-vs-POC 0.001, new_value_area 0.005, zone-edge 0.995/0.998/1.002; **accepted disclosure** (documented tuning constants; no code change).
- [x] **Layer 5 features sweep — disclosed FINDs** — All concrete FINDs (FIND-MCF1/2, FIND-MVP1/2, FIND-XGB1/2, FIND-LSI2, FIND-MSC1, FIND-FMI1, FIND-SIG1, FIND-A2OE1/2/3, FIND-RCE1..4, FIND-TC1, FIND-TC-FP1/2/3, FIND-V2LL1, FIND-SLD1, FIND-V2AB1/2/3, FIND-BO1, FIND-SLVB1/2/3, FIND-SLV1-1/2/3, FIND-VR-1, FIND-MEC-1, FIND-ISNAP-1, FIND-MCSI-1/2/3, FIND-MHMLB-1/2/3, FIND-MHD-1..8, FIND-MS-1..10, FIND-BF-1..6, FIND-MADA-1..6, FIND-LRC-1..8) closed with SHA cites on each [x] child below. Remaining [ ] children are all REAL-GATE: telemetry-gated (FIND-PSS1, FIND-LSI1 training-skew), accepted disclosures (FIND-PSS2, OBS-CC1/2, OBS-DBA1, OBS-A2OE1/2/3, OBS-RCE2, OBS-TC1/2/3, OBS-FPC1/2, OBS-PNSC1, OBS-SSC1, OBS-CSC1/2). Reconciled 2026-05-24 as part of Deferral Reconciliation pass — title also normalized from "deferred FINDs" to "disclosed FINDs".
  - [ ] FIND-PSS1 — [REAL-GATE: telemetry] uniform-triplet `dominant="up"` tiebreak when `confidence_score==0`; disclose-only awaiting production telemetry (LOW–MEDIUM).
  - [ ] FIND-PSS2 — [REAL-GATE: accepted-as-designed] success record omits `error` key; asymmetric with `empty_parallel_output` (INFO; accepted disclosure).
  - [x] FIND-MCF1 — `mc_fusion_adjustment._triplet` L117–121 silent 1/3 on degenerate/non-finite; `_triplet→Optional`, callers passthrough/skip; `fuse_payload` finite/sum>0 guard.
  - [x] FIND-MCF2 — `prediction_engine._norm_triplet_floats` L159–164 same pattern; `Optional` + `_fusion_snap_triplet`/blend fallback.
  - [x] FIND-MVP1 — `mvp_zone` returned `"unknown"` sentinel when `structure.zone` missing; closed: returns `None` + transition gates in `rules_engine` / `prediction_engine` require `cur_z is not None`.
  - [x] FIND-MVP2 — `mvp_net_gamma` float-or-None coerce (mirrors `mvp_spot`; Layer 5 chunk-2 fix).
  - [x] FIND-XGB1 — silent `ticker=""` default; closed via envelope non-empty `ticker` check + `ml_predict._resolve_ml_inference_ticker` fail-closed.
  - [x] FIND-XGB2 — `as_of_ts` None omitted time keys; closed via envelope `as_of_ts` required + engineering snapshot always emits `ts_utc`/`et_hour`/`et_minute`.
  - [ ] FIND-LSI1 — `_patch_lstm_categoricals` unknown zone string defaults to pin_neutral code (L97); defer pending training-skew check.
  - [x] FIND-LSI2 — `_ts_close` 1e-3 epsilon documented on `_ts_close` + `build_lstm_merged_windows` (caller alignment expectation).
  - [ ] OBS-CC1 — signed-distance sign convention per spec (informational; validator allows any finite sign).
  - [ ] OBS-CC2 — `_MVP_SPECS` / `_MVP_FIELD_SEMANTICS` parallel dicts; maintenance hygiene (key-alignment test locked in Layer 5 chunk-1).
  - [x] FIND-MSC1 — non-Mapping parent silent-all-None laundering via `_contains_key` TypeError catch; closed via `_require_mapping` at all 4 coercion entry points.
  - [ ] OBS-DBA1 — `build_db_mvp_feature_row` does not call `validate_feature_contract_row`; downstream callers validate (accepted-as-designed).
  - [x] FIND-FMI1 — `similar_setup_filters_from_db_snapshot_row` non-Mapping `snapshot_row` leaked TypeError; closed via Mapping guard → `FusionModelInputError`.
  - [x] FIND-SIG1 — `canonical_forecast_from_fusion` uniform 1/3 placeholders: `fusion_directional_missing`/`fusion_directional_invalid` were not in trade gate; shared `NON_TRADABLE_CANONICAL_PROVENANCE` in `signal_types.py`; `prediction_engine` withholds forward probs on card; tests `test_signals_canonical_forecast_layer5.py`. ML fallback `_unavailable_model_namespace` already `prob_*=None` (no change).
  - [x] FIND-A2OE1 — `_hard_gates` required ms_dict expiry aliases while identity used Schwab `chain_row.expirationDate`; closed via shared `_resolve_selected_expiry`.
  - [x] FIND-A2OE2 — `liquidity_gate_pass` coerced missing `liq_ok` to `False`; closed via `_liq_ok_value` tri-state + `not_implemented` source.
  - [x] FIND-A2OE3 — bid/ask present but spread/mid uncomputable skipped O-21 spread gate; closed fail-closed to `missing_bid_or_ask`.
  - [ ] OBS-A2OE1 — `deferred_slice_5` replay/live parity gate (registered gap `a2_replay_live_parity_not_gating_runtime`).
  - [ ] OBS-A2OE2 — BS theta fallback disabled (`_A2_THETA_BS_FALLBACK_GOVERNED=False`); `theta_unavailable` hard gate when Schwab theta absent (accepted).
  - [ ] OBS-A2OE3 — `conformance_gaps` registry lists intentional not-implemented A2 surfaces (accepted).
  - [x] FIND-RCE1 — `evaluate_realized_contract_trades_for_rows` silently defaulted missing/invalid `replay_max_hold_bars` to 30; closed via `replay_max_hold_bars_from_context` + skip `missing_replay_max_hold_bars`.
  - [x] FIND-RCE2 — `_chain_selection_quality_row` used `row.get("strike", 0)`; closed skip when strike absent.
  - [x] FIND-RCE3 — exit path allowed `exit_bid <= 0` while entry required `ask > 0`; closed symmetric skip `missing_exit_bid`.
  - [x] FIND-RCE4 — `score_gap_vs_best` sorted with `float(score or 0)`; closed exclude None scores from best-score ladder. Follow-on `b87a24e`: sort key still used `x[1] or 0` — fixed in RCE4 follow-on commit (filter None pre-comparison).
  - [x] OBS-RCE1 — `replay_max_hold_bars_for_trade_type` / `build_replay_context_payload` trade-type fallback documented in payload metadata (`replay_max_hold_bars_source`, `_fallback`, `replay_time_expiry_policy`; closed @ COH-I-K).
  - [ ] OBS-RCE2 — `compare_parallel_cascade_trade_logs` uses `pnl_dollars or 0` for diff stats on valid rows only (accepted).
  - [x] FIND-TC1 — `compute_artifact_sha256_map` omitted missing files from saved `artifact_sha256` (operator inspection gap); closed via `MISSING:{path.resolve()}` marker (mirrors `xgb_meta_content_sha256`). Prior session: row_count/LSTM-dim/xgb-bind fixes in `da69147` (FIND-TC-FP1–FP3).
  - [x] FIND-TC-FP1 — `_normalize_data_fp` / cache keys treated missing `row_count` as `0`; closed `_fingerprint_row_count_part` + tri-state `row_count` (`da69147`).
  - [x] FIND-TC-FP2 — `load_lstm_feature_cache` defaulted missing `n_features_*` to 0; closed `_meta_required_positive_int` (`da69147`).
  - [x] FIND-TC-FP3 — `xgb_meta_content_sha256` returned `""` when meta missing; closed `MISSING:{resolved_path}` (`da69147`).
  - [x] FIND-V2LL1 — `_decision_ts_utc_from_payload` fell back to `default_decision_ts_utc()` (insert-time wall clock) when `refresh_ts_utc` missing/invalid; closed skip `v2_advisory_log_skipped_missing_decision_ts` (live v2 path only).
  - [x] FIND-SLD1 — `run_discrimination` `float(prob_*)` on present fusion keys could abort entire audit on non-numeric/NaN/inf values; closed count as `fusion_n_missing` (extends Action 12.14).
  - [x] FIND-V2AB1 — `_infer_fusion_fields` set `fusion_available=True` when any single `fusion_prob_*` present; closed require complete finite triplet or explicit dominant dir+prob pair.
  - [x] FIND-V2AB2 — partial triplet inferred direction/dominant_prob via max of present keys; closed infer from triplet only when `_fusion_triplet_complete`; `_float_or_none` rejects non-finite.
  - [x] FIND-V2AB3 — advisory payload `decision_ts_utc` used `ms_dict.get("ts_utc")` only; closed `setdefault("ts_utc")` + `_first_present` in `build_v2_advisory_snapshot`.
  - [x] FIND-BO1 — `backfill_outcomes` / `resolve_snapshot_for_backfill` joined snapshots on raw calibration `ticker` while writer/snapshots use `ticker_storage_key`; closed normalize at resolve + pending/resync loops.
  - [x] FIND-SLVB1 — `backfill_signal_layer_v1_bundle` skipped recompute when `meta.n_bars==0` but `meta.error is None` (treated empty layer as done); closed skip only when `meta.n_bars > 0`.
  - [x] FIND-SLVB2 — bundle backfill scanned all `calibration_decision_log` rows (including `legacy`); closed `TRUSTED_PREDICATE_SQL` on SELECT.
  - [x] FIND-SLVB3 — no `enforce_calibration_decision_log_only_1m` before writes; closed + `CalibrationCanonicalViolationError` exit 2 in `main`.
  - [x] **FIND-SLV1-1** — `_f` → `numeric_contract.float_finite_or_none` (audit lane 1 paired fix).
  - [x] **FIND-SLV1-2** — `meta_n_bars_int()`; `backfill_signal_layer_v1_bundle` + `signal_layer_v1_to_direction_probs` + `bayesian_fusion` use safe parse (audit lane 1).
  - [x] **FIND-SLV1-3** — `meta.error=missing_last_close` on early return when last close absent (audit lane 1).
  - [x] **OBS-SLV1-1** — `meta.vwap_source` records `inp` vs `roll` (audit lane 1 @ `eb933ea`).
  - [x] **FIND-VR-1** — `volatility_regime._f` → `float_finite_or_none`.
  - [x] **FIND-MEC-1** — `math_exposure_core._f` → `float_finite_or_none` (fix-as-we-find with VR-1).
  - [x] **COH-SA-1b** — repo-wide guards for module-level `def _f` / `def _num` → `float_finite_or_none` (`tests/test_coh_sa1_float_consolidation.py`).
  - [x] **FIND-ISNAP-1 (HIGH)** — `l1_equiv["spread_pts"]` matches `live_feature_adapter` reader; `tests/test_inference_snapshot_l1_equiv_contract.py` locks all six key pairs.
  - [x] **OBS-ISNAP-1** — `_dist_to_vwap_pts` magnitude-only contract documented in `inference_snapshot.py`.
  - [x] **OBS-ISNAP-2** — `test_build_inference_snapshot_v1_from_signal_input_does_not_fabricate_as_of_ts` verified; `price.spread_pts` asserted in adapter test.
  - [x] **FIND-MCSI-1** — non-canonical MC scalars via `float_finite_or_none` in `resolve_monte_carlo_stack_inputs` (audit lane 3 paired-fix).
  - [x] **FIND-MCSI-2** — canonical `price.spot` + lineage `inp.spot` via `float_positive_or_none` (audit lane 3 paired-fix).
  - [x] **FIND-MCSI-3** — `_spot_for_mc_fusion_adjustment` both read paths use `float_positive_or_none` (audit lane 3 paired-fix).
  - [x] **FIND-MHMLB-1** — `fusion_payload_to_horizon_snapshot` parses probs/fcs via `float_finite_or_none`; non-finite → unavailable row.
  - [x] **FIND-MHMLB-2** — `dominant_direction` from `direction_from_normalized_triplet`; upstream label discarded.
  - [x] **FIND-MHMLB-3** — `_safe_norm_triplet` logs raw_sum drift; `provenance=bayesian_fusion_renormalized` when `|sum-1|>0.01`.
  - [x] **FIND-MHD-1** — `_safe_prob_optional` routes through `float_finite_or_none` + range gate.
  - [x] **FIND-MHD-2** — canonical fallback blend uses `float_finite_or_none`; non-finite → skip blend + `_canonical_nonfinite` provenance.
  - [x] **FIND-MHD-3** — `_confidence_from_probs` direction via `direction_from_normalized_triplet`; margin gates overlay wait.
  - [x] **FIND-MHD-5** — malformed `ED_MH_FALLBACK_CANONICAL_BLEND` → `log.debug` + `wfb=0.0`.
  - [x] **FIND-MHD-6** — finalize target/stop via `_finite_price_optional`; NaN/inf → display "—".
  - [x] **FIND-MHD-7** — `_entry_state_machine` spot/zone/entry via `_finite_price_optional`.
  - [x] **FIND-MHD-8** — `_norm_triplet` rejects non-finite sum (`math.isfinite(s)`).
  - [x] **FIND-MS-1** — `spot_f = _f_ms(spot)`; non-finite spot → degraded cards (no signals).
  - [x] **FIND-MS-2** — `mc_iv_level` via `float_positive_or_none`.
  - [x] **FIND-MS-3** — `forward_prob_*` / `dominant_prob` via `float_finite_or_none`.
  - [x] **FIND-MS-4** — `_fusion_f` → `float_finite_or_none` (all fusion numeric fields).
  - [x] **FIND-MS-5** — `_pack_probs` legs via `float_finite_or_none`.
  - [x] **FIND-MS-6** — vol regime multipliers via `float_finite_or_none`.
  - [x] **FIND-MS-7** — `_ms_price_disp` on spot/bid/ask.
  - [x] **FIND-MS-8** — call entry/stop/target display via `_ms_price_disp`.
  - [x] **FIND-MS-9** — `final_confidence` via `float_finite_or_none`.
  - [x] **FIND-MS-10** — `rec_strike` via `float_finite_or_none`; non-finite → `is_no_trade`.
  - [x] **FIND-BF-1** — `_model_direction_triplet` via `float_finite_or_none` + `math.isfinite(tot)`.
  - [x] **FIND-BF-2** — `_model_dominant_class` triplet-only via `direction_from_normalized_triplet`.
  - [x] **FIND-BF-3** — `_optional_support` via `float_finite_or_none`.
  - [x] **FIND-BF-4** — `_bayesian_update` skips non-finite likelihoods.
  - [x] **FIND-BF-5** — `float_finite_or_none` imported from `numeric_contract`.
  - [x] **FIND-BF-6** — malformed `ED_SIGNAL_LAYER_FUSION_BLEND` → `log.debug` + default 0.38.
  - [x] **FIND-MADA-1** — `_direction` gates fusion on `is_ms_dict_fusion_authoritative` (`fusion_contract.py`).
  - [x] **FIND-MADA-2** — `dominant_probability` fusion prob uses same gate; no `final_confidence` cross-wire (fail-closed).
  - [x] **FIND-MADA-3** — `_desk_confidence_value` via `float_finite_or_none`.
  - [x] **FIND-MADA-4** — `_position_size_fraction` via `float_finite_or_none`.
  - [x] **FIND-MADA-5** — `_probability_candidate` finite + [0,1] bound.
  - [x] **FIND-MADA-6** — duplicate fusion gate → `is_ms_dict_fusion_authoritative` in `fusion_contract.py` (completion after `52737e9`).
  - [x] **FIND-LRC-1** — `apply_time_decay` NaN mins → 0 (no decay).
  - [x] **FIND-LRC-2** — `apply_vix_adjustment` + `derive_stop_distance_pct` `vix_unavailable` tag on non-finite VIX.
  - [x] **FIND-LRC-3** — `apply_risk_multiplier` NaN → 1.0; preserves `0.0` → 1.0 (`or` semantic).
  - [x] **FIND-LRC-4** — `_abs_or_none` via `float_finite_or_none`.
  - [x] **FIND-LRC-5** — `snap_target_to_structural` finite levels; `level is not None` (0.0 eligible).
  - [x] **FIND-LRC-6** — `derive_target_levels` finite entry/risk gate.
  - [x] **FIND-LRC-7** — `fire_exit` non-finite stop/target → `missing_stop_target_for_exit`.
  - [x] **FIND-LRC-8** — `_cap_target` finite inputs.
  - [x] **OBS-LRC-1** — magic `2.0` / `1.0` R-multiples → `T1_FALLBACK_R_MULTIPLE` / `T2_OFFSET_R_MULTIPLE` (`lifecycle_rule_core.py`); closed via REPO_SWEEP SWEEP-MT-1..2.
  - [x] **OBS-MP-2** — Schwab missing-greek `-999.0` sentinel → `MISSING_GREEK_SENTINEL` (authority `math_exposure_core.py`; full production tree promoted SWEEP-MT-FULL-TREE).
  - [x] **OBS-FP1-5** — symmetric grep guard `in TRADABLE_CANONICAL_PROVENANCE` outside authority; `test_no_inline_tradable_membership_outside_authority` in `tests/test_fusion_contract.py`.
  - [x] **SWEEP-LRC-NAN** @ `8e8a18a` — SWEEP-LRC-NAN-1..4: `fire_exit` max_hold_bars NaN guard; `apply_*` non-finite `distance_pct` seeds `STOP_BASE_PCT`; banned `return float(distance_pct)` pattern. Tests: `tests/test_repo_sweep_lrc_nan_guards_v1.py`. Closes OBS-LRC-3 + OBS-LRC-4.
  - [x] **OBS-LRC-3** — closed via SWEEP-LRC-NAN @ `8e8a18a`.
  - [x] **OBS-LRC-4** — closed via SWEEP-LRC-NAN @ `8e8a18a`.
  - [ ] OBS-TC1 — `load_lstm_feature_cache` metadata defaults (`tickers`/`days`/`n_days`/`n_tickers` empty or 0); accepted — structural dims fail-closed via `_meta_required_positive_int`.
  - [ ] OBS-TC2 — `_normalize_data_fp({})` returns `{}` vs 6-key shape for non-empty; accepted — conservative cache miss on legacy empty identity.
  - [ ] OBS-TC3 — Legacy `cache_exists` / `read_cache_meta` at file tail unused by scheduler (accepted).
  - [ ] OBS-FPC1 — `fusion_payload_to_policy_columns` `json.dumps` failure → `cm_json = "[]"` (audit metadata only; not policy prob authority).
  - [ ] OBS-FPC2 — `fused_stack_status_*` uses `dom`/`fconf` `"?"` when fusion attrs missing (audit string; accepted disclosure).
  - [ ] OBS-PNSC1 — `features/parallel_stack_contract.py` does not exist; parallel model output contract is `features/parallel_stack_schema.py` (Layer 5 walked c80d536). Degradation audit trail is `features/stack_integrity_v1.py` (Layer 5 walked as schema sibling).
  - [ ] OBS-SSC1 — `_max_transformer_seq_len_for_ticker` lazy-imports `ml_predict` (horizon slug + model dir scan); `ED_XGB_STRICT_ACTIVE_ONLY` scope tracked under model-lifecycle G4 (accepted).
  - [ ] OBS-CSC1 — `validate_cascade_inference_lineage` re-wraps `XgbInferenceInputError` (inherits XGB1/XGB2 envelope strictness); accepted challenger-only path.
  - [ ] OBS-CSC2 — cascade upstream tensor names (`xgb_prob_*`, `lstm_prob_*`) are stage-contract labels, not Schwab leaves; locked by assert len 3/6 vs `ml_predict` cascade extras.
- [ ] **Action 12.7+ — Layer 5 remaining unread surface** (wide-grep re-pass on audited files; `call_engine.py` full body) — `call_engine.py` full body; `ml_predict`/`ml_scheduler`/`ml_train`; `features/*` (11 files); `calibration/*` (~~`v2_live_logging.py`~~ FIND-V2LL1 closed; ~~`signal_layer_discrimination.py`~~ FIND-SLD1 closed; ~~`v2_advisory_backfill.py`~~ FIND-V2AB1–3 closed; ~~`backfill_outcomes.py`~~ FIND-BO1 closed; ~~`backfill_signal_layer_v1_bundle.py`~~ FIND-SLVB1–3 closed); `arch_competition/*`; `lstm_*`/`transformer_*`; ~~`v2_decision/a2_option_expression.py`~~ (FIND-A2OE1–3 closed); ~~`realized_contract_eval.py`~~ (FIND-RCE1–4 closed); ~~`training_cache.py`~~ (FIND-TC1–3 closed); re-read `server.py`/`market_state.py`; ~~`signals.py` L91-102 + ML fallback namespaces~~ (FIND-SIG1 closed).
- [x] **Stack foundation sign-off** — **Absorbed into STACK-WIRING-INTEGRITY** (Phase 4 / **STACK-WIRE-15**). Original six passes: (1) contract inventory → **STACK-WIRE-1** + map; (2) consumer grep → **STACK-WIRE-15**; (3) live vs replay → **STACK-WIRE-6** / **LIVE-UI-F**; (4) UI operator truth → Phase 3 LIVE-UI rows; (5) residual allowlist → Phase 4; (6) smoke → **STACK-WIRE-13**. **Trigger:** `go stack-wiring-integrity-signoff` after Phases 0–3 complete (not before **AUDIT-CAND-SERVER-PY-FULL-READ** closes). (Cross-reference only; not a standalone open item.)
- [x] **Action 11.8 — signals.py MC + fusion attributes fail-closed** — `signals.py:719,720,725,727,728,740,756,758,760` fabricated 0/`"neutral"`/`"unknown"` when mc_out/fusion attributes absent; return None and skip downstream label emit. Schwab-leaf path: `pricehistory.candles[].close` → MC; chain greeks → fusion. SHA: `a0b161b`
- [x] **Action 11.9 — call_engine.py fail-closed on missing index quotes + fusion posteriors** — 11 high-priority sites + 5 lower-priority deferred; fusion posterior gate semantic: **block** trade when posterior is None (fail-closed). Schwab-leaf paths: `quotes.{SPY,QQQ,IWM}.netChange`, chain delta, fusion engine output. SHA: `4a64a69`
- [x] **Action 11.9b — call_engine.py lower-priority fail-open** — bundled in Action 12.0 batch 1.
- [x] **Day 2 — Order flow + spread** — DFR-019, PQ-002, PQ-005, PQ-007, PQ-008, PQ-011, PQ-012, PQ-013, OP-015, OP-017. Files: `order_flow_engine.py`, `server.py` VWAP + accumulator + fast-quote spread. RVOL unavailable not 1.0; spread units split; per-bar volume source. SHA: `92b85ff`
- [x] **Day 3 — ML feature provenance** — DFR-012, DFR-013, MT-002, MT-003, MT-005, MT-008, MT-012. Files: `features/inference_snapshot.py`, `features/fusion_model_input.py`, `features/lstm_sequence_input.py`, `ml_data_common.py`, `calibration/v2_advisory_backfill.py`, `tests/test_ml_feature_provenance.py`. Per-field lineage; fusion `unknown`; LSTM masks; `m5_source_timeframe`. SHA: `c527b82`
- [x] ~~**Day 4 — ML training imputation**~~ — superseded by Section 10
- [x] ~~**Day 5 — Calibration + replay**~~ — superseded by Section 11
- [x] ~~**Day 6 — Trader-visible A2 + UI remnants**~~ — superseded by Section 17
- [x] ~~**Day 7 — Market context + remaining PQ**~~ — superseded by Sections 2–3
- [x] ~~**Day 8 — Final repo-wide zero-OPEN sweep**~~ — superseded by section closure cert (Section 17)

---

## Schwab repo-wide replacement — TraceableDerivation sweep (§A–§Q)

**Bound to:** `governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`.

**Step 1 accepted (`bd96a98`):** `governance/traceable_derivation.py` — structured `inputs` + validated `schwab_leaves` or `allowlist_id`; categorical `schwab_leaf` strings **rejected by construction**. Legacy §1–§16 categorical inventories archived under `governance/archive/legacy_categorical_inventories_v1/` (not closure evidence). Gap intel from rejected categorical resolver (`61358a6`, not active): `governance/CHAIN_OF_TRUST_GAP_INTEL_290.md` — remediation backlog for future TraceableDerivation chain-of-trust.

**CAPS (mandatory every commit):** `tests/test_anti_pattern_family_repo_wide.py` — zero unallowlisted production hits.

**Section rule:** Dependency-ordered walk (§A before §B, …). Each section: full AST scope, `TraceableDerivation` rows only, `assert_traceable_inventory_covers_all_functions`, producer→consumer graph must close before `[x]`. **One section = one commit.**

**KEY LEVELS — YES restored (`a9208de` / Mega 2 §D)** — Supersedes empirical-only `82615fa`. Basis: Mega 2 `TraceableDerivation` inventory (201 rows) + cross-mega `assert_mega_chain_closes` (e.g. `compute_max_pain` → `compute_exposures_by_strike` → `server.py:_fetch_state` → Schwab transport). Pattern-grep regressions remain floors only.

### Why prior §1–§16 `[x]` and categorical inventories do NOT count

Categorical inventories (`DerivationRecord` with free-text `schwab_leaf` like `"upstream ms_dict / SignalInput"`) are archived. They are reference-only for migration. Closure requires `TraceableDerivation` + structured producer links.

| Legacy § | Maps to | Status |
|---|---|---|
| §1–§16 | §A–§P | **RESET** — re-walk required |
| §17 | §Q | Not started |

### Mega 1 (§A + §B + §C — single inventory commit)

- [x] **Mega 1** — exactly **17 files** (Schwab transport + adapters + server + live state + market data + state). `governance/mega1_traceable_inventory.py` (**305** rows); `tests/test_mega1_traceable_audit.py`; `governance/CHAIN_OF_TRUST_ALLOWLIST.py`. Inventory + chain-of-trust only. SHA: `17419f4`

### Mega 2 (§D + §E — KEY LEVELS math + order flow)

- [x] **Mega 2** — exactly **10 files**: `math_exposure_core.py`, `math_exposure.py`, `math_levels.py`, `math_volatility.py`, `math_probabilities.py`, `levels.py`, `order_flow_engine.py`, `order_flow_live_state.py`, `order_flow_streaming.py`, `debug_flow_snapshot.py`. `governance/mega2_traceable_inventory.py` (**201** rows); `governance/mega_chain_of_trust.py` (cross-mega resolver with Mega 1); `tests/test_mega2_traceable_audit.py`. Inventory-only. SHA: `a9208de`

### Mega 3 (§F + §G — MC/regime + features)

- [x] **Mega 3** — exactly **26 files**: `monte_carlo.py`, `mc_fusion_adjustment.py`, `volatility_regime.py`, `regime_engine.py`, plus **22** `features/*.py` modules (excludes `features/__init__.py`). `governance/mega3_traceable_inventory.py` (**121** rows); `tests/test_mega3_traceable_audit.py` (Mega 1+2+3 `assert_mega_chain_closes`). Inventory-only. SHA: `19a9ecb`

### Mega 4 (§H + §I — ML training + calibration; NOT signals/decision)

- [ ] **Mega 4** — **82 files with AST defs** (schedule **85** module paths; excludes zero-def `calibration/__init__.py`, `arch_competition/__init__.py`, `arch_competition/exceptions.py`): **17** ML/training + **49** `calibration/*.py` + `bayesian_fusion.py` + `governed_stack_contract.py` + **13** `arch_competition/*.py`. Depends: Mega 3 features. **Mega 5** (later) = signals + decision (§J+§K in OPEN_ITEMS checklist). SHA: __________

- [ ] **§A Schwab client + adapters** — `schwab_client.py`, `reauth_schwab.py`, `websocket_adapter.py`, `polling_adapter.py`, `sse_adapter.py`, `market_data_adapter.py`, `snapshot_normalizer.py`, `snapshot_access.py`. Depends: —. SHA: __________
- [ ] **§B Server + live state** — `server.py`, `live_market_plane.py`, `live_decision_bundle.py`, `live_pipeline_diag.py`, `live_vs_replay_validation.py`. Depends: §A. SHA: __________
- [ ] **§C Market data + state** — `market_context.py`, `market_state.py`, `math_snapshot_derive.py`. Depends: §A, §B. SHA: __________
- [x] **§D Math / KEY LEVELS** — `math_exposure*.py`, `math_levels.py`, `math_volatility.py`, `math_probabilities.py`, `levels.py`. **Gate:** Mega 2 chain-of-trust closes. SHA: `a9208de` (supersedes `82615fa`)
- [ ] **§E Order flow** — `order_flow_engine.py`, `order_flow_live_state.py`, `order_flow_streaming.py`, `debug_flow_snapshot.py`. Depends: §C. SHA: __________
- [ ] **§F Signals + decision** — `signals.py`, `signal_helpers.py`, `signal_types.py`, `rules_engine.py`, `prediction_engine.py`, `call_engine.py`, `multi_horizon_decision.py`, `multi_horizon_ml_bundle.py`. Depends: §C, §D, §E. SHA: __________
- [ ] **§G V2 decision + A2 lifecycle** — `v2_decision/*.py`, `lifecycle_rule_core.py`. Depends: §F. SHA: __________
- [ ] **§H MC + regime + volatility** — `monte_carlo.py`, `mc_fusion_adjustment.py`, `volatility_regime.py`, `regime_engine.py`. Depends: §F. SHA: __________
- [ ] **§I Features (ML inputs)** — `features/*.py`. Depends: §C. SHA: __________
- [ ] **§J ML training + predict** — `ml_*.py`, `lstm_*.py`, `xgboost_model.py`, `transformer_*.py`, `train_*.py`, `training_*.py`, `normalized_training_sync.py`, `smoke_predict_active.py`. Depends: §I. SHA: __________
- [ ] **§K Calibration + fusion** — `calibration/*.py`, `bayesian_fusion.py`, `governed_stack_contract.py`, `arch_competition/*.py`. Depends: §J. SHA: __________
- [ ] **§L Liquidity** — `liquidity_models.py`, `liquidity_value_engine.py`, `print_liquidity_value_snapshot.py`, `run_liquidity_sample.py`. Depends: §A, §C. SHA: __________
- [ ] **§M Similarity** — `adaptive_similarity_engine.py`, `similarity_*.py`. Depends: §C, snapshots. SHA: __________
- [ ] **§N DB + backfill + repair** — `db*.py`, `clean_db.py`, `eval_metrics_store.py`, `backfill_*.py`, `bar_rehydration_*.py`, `pin_neutral_outcome_repair_v1.py`, `distance_option_a_backfill_v1.py`, `patch_active_artifact_provenance.py`, `replay_bundle_coverage.py`, `realized_contract_eval.py`. Depends: §A–§M. SHA: __________
- [ ] **§O Audit + verify + config + contracts** — `audit_*.py`, `verify_*.py`, `inspect_trading_data.py`, `config.py`, `setup_readiness.py`, `scheduler_user_tickers.py`, `ticker_*.py`, `production_universe.py`, `instrument_identity.py`, `timeframe_config.py`, `model_contract.py`, `feature_contract_*.py`, `horizon_outcomes.py`, `movement_target_threshold.py`, `institutional_behavior.py`, `canonical_distances.py`, `tier3_design.py`. Depends: §A–§N. SHA: __________
- [ ] **§P External signals** — `news_sentiment.py`, `api_pressure.py`, `event_risk.py`. Depends: — (parallel). SHA: __________
- [ ] **§Q Planes + research + UI + misc** — `planes/*.py`, `research/*.py`, `static/*`, `ops_runner.py`, `crash_trace.py`, `schwab_*_inventory*.py`, `schwab_field_dictionary_builder.py`, `micro_structure.py`, `adaptive_shadow_v2_calibration.py`, `print_*.py`, `compare_clustering_modes.py`. Depends: §B, §C. SHA: __________

---

## GitHub backup state — local-vs-remote-vs-main

**Reality:** operator runs from local launch folder; GitHub is backup only (no other puller). **What belongs in Git vs on disk:** [`docs/host/BACKUP_AND_MIRROR.md`](docs/host/BACKUP_AND_MIRROR.md). **Env template:** [`.env.example`](.env.example) → local `.env` (never commit).

| Location | Branch | Tip | Status |
|---|---|---|---|
| Local `C:\Users\evarg\Documents\Trading\EdWebConsole` | `feature/institutional-key-levels` | `e8512be` | Source of truth |
| origin/feature/institutional-key-levels | (same branch on GitHub) | `e8512be` — **in sync** (pushed 2026-05-21; bulk push `1c0ec96`..`d40e317`) | Backup synced |
| origin/main | `main` | `4b8ba2d` (frozen) | Stale by 82+ commits |

**Action items:**
- [x] **TRAINING-PIPELINE-PUSH-REVIEW** @ 2026-05-21 — see **NEXT** section.
- [x] **Backup sync** @ 2026-05-21 — `git push origin feature/institutional-key-levels` (133 commits).
- [ ] **Main merge (deferred)** — when audit is complete (Layer 3+ done, all Action 10.x closed), open PR `feature → main` so main becomes canonical. No urgency since no other puller; durability concern only.

**Rule going forward:** every commit on this branch should be pushed to origin same day. Local-only commits = single point of failure.

---

## Resolved (archive)

_Move rows here with date + short note when closed._

_(None yet from this list.)_
