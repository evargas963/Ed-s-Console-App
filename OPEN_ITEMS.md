# Open items — horizon, stack, UI consistency

**Rule:** Items stay **open** until there is a merged/code-verified resolution (not just “planned”).  
**Last reviewed:** 2026-05-18 — All work bound by **SCHWAB FULL REPO DIRECTIVE** in [`CLAUDE.md`](CLAUDE.md) (entire codebase; Canopy→Trunk→Branch→Leaf; Read, not scan). No file out of scope. Closure inadmissible until three-PR gate (governance pin → CI diff-emission gate → full-tree scanner regen) per V4 § Scope.

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
- G4-3: scheduler fail-open behavior at `ml_scheduler.py:1701-1707` and `ml_scheduler.py:2133-2135` allows exit 0 with incomplete artifacts.
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
- [ ] **Pilot 1 Schwab walk — deferred FINDs (2026-05-19, chunks 3-N)** — Disclosed in chunk-1 walks of `order_flow_engine.py` (`dfa1f82`) and `liquidity_value_engine.py` (`73bb17f`); not blocking but eligible for future paired-fix chunks. Cross-linked from `governance/PILOT_1_SCHWAB_WALK_AND_AUTHORITY_UX_STAGING.md` closure section.
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
  - [x] FIND-CE9 — `call_readiness` exception → `log.warning` (surfaces in standard logs).
  - [x] FIND-OF8 — `_of_sign(0.0)→None`; verdict agreement no longer casts zero cum_delta as neutral (chunk-4b / math_exposure).
  - [x] STYLE-LVE2 — tag matching `in tags` vs `in str(tags)`; **accepted disclosure** (intentional substring match for VWAP_* tags; no code change).
  - [x] Magic-threshold disclosures — POC 0.002, VWAP-vs-POC 0.001, new_value_area 0.005, zone-edge 0.995/0.998/1.002; **accepted disclosure** (documented tuning constants; no code change).
- [ ] **Layer 5 features sweep — deferred FINDs**
  - [ ] FIND-PSS1 — uniform-triplet `dominant="up"` tiebreak when `confidence_score==0`; disclose-only pending production telemetry (LOW–MEDIUM).
  - [ ] FIND-PSS2 — success record omits `error` key; asymmetric with `empty_parallel_output` (INFO; accepted disclosure).
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
  - [ ] OBS-FPC1 — `fusion_payload_to_policy_columns` `json.dumps` failure → `cm_json = "[]"` (audit metadata only; not policy prob authority).
  - [ ] OBS-FPC2 — `fused_stack_status_*` uses `dom`/`fconf` `"?"` when fusion attrs missing (audit string; accepted disclosure).
- [ ] **Action 12.7+ — Layer 5 remaining unread surface** (wide-grep re-pass on audited files; `call_engine.py` full body) — `call_engine.py` full body; `ml_predict`/`ml_scheduler`/`ml_train`; `features/*` (11 files); `calibration/*`; `arch_competition/*`; `lstm_*`/`transformer_*`; `v2_decision/a2_option_expression.py`; `realized_contract_eval.py`; `training_cache.py`; re-read `server.py`/`market_state.py`; `signals.py` L91-102 + ML fallback namespaces.
- [ ] **Stack foundation sign-off (post–Layer 4/5 sweep, pre–G2/G3)** — Operator request: after Actions 11–12.x + 12.7+ are closed, run a structured final review so the signal/stack layer is solid before model-lifecycle work. **Not** another ad-hoc patch pass; explicit sign-off or filed actions only. Passes: (1) **Contract inventory** — Schwab-leaf → derived → fusion → UI/calibration; every unavailable path is `None`/withheld, documented. (2) **Consumer grep** — no downstream re-fabrication (pattern: producer fixed, consumer still emits 0.33/`"flat"`/`"wait"`). (3) **Live vs replay** — `compute_signals`, calibration backfill/audit CLIs, and replay paths behave consistently on missing inputs. (4) **UI / operator truth** — `static/index.html` and diagnostics do not re-label null as flat/neutral. (5) **Residual allowlist** — any remaining defaults are named, tested, justified (not accidental). (6) **Smoke** — one trusted ticker/session: thin `price_bars_1m` → withhold; full bars → unchanged where data exists. Deliverable: findings table + OPEN_ITEMS actions for anything still warranted; optional short written report if operator asks. **Trigger:** operator says `go on stack foundation sign-off` after 12.7+ queue is drained. **Ownership split:** operator calibration batch in parallel; assistant `call_engine.py` E2E + any filed vertical slices.
- [x] **Action 11.8 — signals.py MC + fusion attributes fail-closed** — `signals.py:719,720,725,727,728,740,756,758,760` fabricated 0/`"neutral"`/`"unknown"` when mc_out/fusion attributes absent; return None and skip downstream label emit. Schwab-leaf path: `pricehistory.candles[].close` → MC; chain greeks → fusion. SHA: `a0b161b`
- [x] **Action 11.9 — call_engine.py fail-closed on missing index quotes + fusion posteriors** — 11 high-priority sites + 5 lower-priority deferred; fusion posterior gate semantic: **block** trade when posterior is None (fail-closed). Schwab-leaf paths: `quotes.{SPY,QQQ,IWM}.netChange`, chain delta, fusion engine output. SHA: `4a64a69`
- [x] **Action 11.9b — call_engine.py lower-priority fail-open** — bundled in Action 12.0 batch 1.
- [x] **Day 2 — Order flow + spread** — DFR-019, PQ-002, PQ-005, PQ-007, PQ-008, PQ-011, PQ-012, PQ-013, OP-015, OP-017. Files: `order_flow_engine.py`, `server.py` VWAP + accumulator + fast-quote spread. RVOL unavailable not 1.0; spread units split; per-bar volume source. SHA: `92b85ff`
- [x] **Day 3 — ML feature provenance** — DFR-012, DFR-013, MT-002, MT-003, MT-005, MT-008, MT-012. Files: `features/inference_snapshot.py`, `features/fusion_model_input.py`, `features/lstm_sequence_input.py`, `ml_data_common.py`, `calibration/v2_advisory_backfill.py`, `tests/test_ml_feature_provenance.py`. Per-field lineage; fusion `unknown`; LSTM masks; `m5_source_timeframe`. SHA: `c527b82`
- [ ] ~~**Day 4 — ML training imputation**~~ — superseded by Section 10
- [ ] ~~**Day 5 — Calibration + replay**~~ — superseded by Section 11
- [ ] ~~**Day 6 — Trader-visible A2 + UI remnants**~~ — superseded by Section 17
- [ ] ~~**Day 7 — Market context + remaining PQ**~~ — superseded by Sections 2–3
- [ ] ~~**Day 8 — Final repo-wide zero-OPEN sweep**~~ — superseded by section closure cert (Section 17)

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

**Reality:** operator runs from local launch folder; GitHub is backup only (no other puller).

| Location | Branch | Tip | Status |
|---|---|---|---|
| Local `C:\Users\evarg\Documents\Trading\EdWebConsole` | `feature/institutional-key-levels` | latest local | Source of truth |
| origin/feature/institutional-key-levels | (same branch on GitHub) | sometimes behind by unpushed commits | Backup target |
| origin/main | `main` | `4b8ba2d` (frozen) | Stale by 82+ commits |

**Action items:**
- [ ] **Backup sync** — keep `origin/feature/institutional-key-levels` exactly equal to local after each commit. Operator can `git push origin feature/institutional-key-levels` from launch folder.
- [ ] **Main merge (deferred)** — when audit is complete (Layer 3+ done, all Action 10.x closed), open PR `feature → main` so main becomes canonical. No urgency since no other puller; durability concern only.

**Rule going forward:** every commit on this branch should be pushed to origin same day. Local-only commits = single point of failure.

---

## Resolved (archive)

_Move rows here with date + short note when closed._

_(None yet from this list.)_
