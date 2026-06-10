> **Classification:** Active Rule Source | **Scope:** Current epic, conflicts, deferred work, known risks.

# ACTIVE_PROGRAM.md — what we are doing now

**Updated:** 2026-05-27 (reaudit fixes @ `cb40b80`)  
**Branch:** `feature/institutional-key-levels` — consolidation Phases 0–4 complete; **2 commits ahead of origin** (see §Claude audit handoff)  
**Execution plan:** [`docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md`](docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md)

---

## Active program

**Institutional trading app — world-class bar** (operator 2026-05-27). Homegrown, but the finished product must **rival any institutional platform**. Every slice lands **application code + paired tests** (producer, consumer, or money-path fix). Quality gates in `AGENTS.md`: §World-class / institutional code gate (MIT professor + world's greatest coder) and §Universal code quality — simplicity and institutional pride (`check_universal_code_quality_contract()`; simple when simple wins). **Rule compliance — zero drift:** rules are law; banned/excuse phrases blocked at pre-commit (`check_fix_everything_we_touch.py`). Audit before sign-off: `python tools/enforce_all_rules.py --code-quality`.

**Non-negotiables (code-first):**
- **Train-success-live** — successful scheduler train → `models/active/` in the same run (auto-promote default ON).
- **Full parallel stack** — live + offline parallel eval score a row only when XGB + LSTM + Transformer all produce valid triplets (no 0.333 meta filler, no XGB-only ensemble rows). Cascade keeps its own architecture contract; governed comparison uses **ts_utc alignment**.
- **ML pipeline efficiency (operator 2026-05-31, binding)** — leaf ablation confirm → **stack refit backtest** (CLI `--survivor-stack-refit-backtest`; holdout refit full vs survivor — not mask on `models/active/`) → edge probe → validation run → scheduler train. **Compound-group survivors VOID** — re-ablate on atomic Schwab/manifest universe only. **ZERO-BIAS (2026-06-05, binding, cannot be violated):** data decides placement at **`(feature × model × horizon)`** cells only — see `AGENTS.md` §Ablation contract / ZERO-BIAS; agents build toward the target, not toward preserving biased artifacts. **Do not train** to discover wiring or drop quality. **seven stack models:** `xgb`, `lstm`, `transformer`, `meta`, `monte_carlo`, `regime`, `fusion` (canonical: `governed_stack_contract.FULL_STACK_MODEL_LAYERS`). Parallel train **writes** `parallel_cascade_bridge.npz`; cascade **must reuse** parallel XGB + bridge in the same `run_once`. Mechanical locks: `tools/check_ml_pipeline_efficiency.py` (gate order + CLI + ps1), `tools/check_ablation_pipeline_parity.py`, `check_full_stack_models_contract()`, `check_zero_bias_ablation_contract()`; pre-commit runs via `tests/test_ml_feature_schema_parity.py` + `tests/test_check_fix_everything_we_touch.py`.
- **Confluence-only** — `panel_auto` enrolled for logging/features, **excluded from ML training**.
- **Operator legibility** — WAIT/neutral horizon cards stay high-contrast vs page chrome (same labels; readable slate/blue neutral palette — not “broken UI”).

### Feature placement matrix — `(feature × model × horizon)` `[binding]`

**North star:** for **each of the seven stack models**, data decides **which atomic features fit that model at each horizon** (`1c` / `5c` / `15c` / `60c`). Nothing pre-routes placement — not manifest `members`, not hand-curated `FEATURES_5M` lists, not compound bundles.

| Axis | Binding values |
|------|----------------|
| **feature** | One atomic column per ablation unit — **all 280** ABLATE manifest rows on the grid (no builder pre-cull; `not_wired` / `no_model_interface` are per-cell skip reasons, not exclusions) |
| **model** | **All seven** stack layers — `xgb`, `lstm`, `transformer`, `meta`, `monte_carlo`, `regime`, `fusion` (`governed_stack_contract.FULL_STACK_MODEL_LAYERS`). **Not** xgb/lstm/transformer-only + four upper layers on a separate axis (`AGENTS.md` ZERO-BIAS). |
| **horizon** | `1c`, `5c`, `15c`, `60c` — all mandatory; partial-horizon runs rejected |

**Scoring:** one feature knocked out at a time; effect measured **through one unified seven-layer wire-row path** (`score_unified_ablation_fusion_from_wire_row` via `_production_fusion_prob_for_row` when `ED_ABLATION_SCORING_PASS=1`) so **every layer** consumes the same permuted DB row at every horizon. “That layer doesn’t consume raw features” is **not** a reason to drop it from the model axis — ablation decides.

**Authority output:** survivors resolve **per `(model, horizon)`** → `survivor_summary.by_model_horizon[model][horizon]`. That matrix is the **only** admissible training placement router.

**Target cell count:** 280 × **7 models** × **4 horizons** = **7,840** placement cells. Row pool = SPY + QQQ + IWM (pooled; not a grid axis). Mechanical lock: `check_ablation_seven_model_four_horizon_grid()` + `check_ablation_single_authority()` + `check_ablation_full_stack_non_negotiable()` on every pre-commit; runtime: `python tools/feature_curation_gate.py --ablation-audit`.

Schwab scanner/register work is **tracking only** — it does not replace wire fixes, UI honesty, or stack behavior.

### Stack honesty phased plan `[binding]` (2026-06-06 — Fusion-only horizon cards; code + locks, not memo-only)

Operator north star: **one door in** (wire row → seven-layer stack), **one door out** (fusion-only on horizon cards). Phases below are tracked here and in `OPEN_ITEMS.md`; each phase closes only with code + paired test + checker row in `AGENTS.md` §Mandatory enforcement registry.

| Phase | Status | Code targets | Mechanical lock |
|-------|--------|--------------|-----------------|
| **1 — Card honesty** | **LANDED** (working tree) | `prediction_engine.py::_overlay_multi_horizon_ml_on_product_triplets`, `bayesian_fusion.py` blend default | `check_fusion_only_card_contract()` |
| **1b — 5th ALL card** | **LANDED** (working tree) | `static/index.html` `#tf-signal-consolidated`, `deriveSourceForHorizon('consolidated')` | `test_issue18_ui_contract.py` + `check_fusion_only_card_contract()` |
| **2 — Four-stack promotion** | OPEN | `ml_scheduler.py`, `active_bundle_contract.py`, `models/active_{hz}/` per panel ticker | promotion + `verify_active_models.py` tests |
| **3 — Call → ALL only** | OPEN | `call_engine.py`, `multi_horizon_decision.py` | paired test in existing call contract file |
| **4 — Sequence-faithful ablation** | `[REAL-GATE: after-grid]` | `arch_competition/ablation_bundle_inference.py` | after current 1,120-cell grid completes |
| **5 — Schwab fix-as-we-touch** | **ONGOING** (cone-by-cone) | every file Read in producer/consumer cone per `CLAUDE.md` | `check_schwab_csv_first.py` on new market-fact sites; not repo-wide closure yet |
| **6 — Rules at turn-time** | **PARTIAL** | `tools/enforce_all_rules.py`, `.claude/settings.json` Stop hook | pre-commit mirrors ~⅓ deterministic rules; Claude Stop hook scans output; Cursor chat output has no mechanical gate |
| **7 — Pre-train observe (no retrain for cards)** | **LANDED** (working tree) | `ED_LIVE_ABLATION_EXPERIMENT=1` → `models/parallel/{ticker}/` + survivor serve masks; team gate blocks solo MC | `check_live_ablation_experiment_wiring()` + `check_unified_stack_team_contract()` |

**Pre-train card observe (operator binding):** set `ED_LIVE_ABLATION_EXPERIMENT=1` on the server process to score horizon + ALL cards from ablation survivor masks and candidate bundles under `models/parallel/` **before** scheduler promotion — not via retrain. Strict `models/active/` remains the post-train promotion path only.

**Verify after commit + server restart:** `python -m pytest tests/test_prediction_engine_chunk1_fail_closed.py tests/test_issue18_ui_contract.py tests/test_check_fix_everything_we_touch.py::test_fusion_only_card_contract -q` then `python tools/live_diag_compare.py SPY`.

**Governance consolidation** — **Phases 0–4 complete** @ `ed9f882`. **Concurrent:** Training PR5–PR7. **Schwab V4:** disposition/regen when it unblocks CI or closes a proven wire FIND — never scanner-only turns.

### Consolidation status (scope-explicit)

| Phase | Status |
|-------|--------|
| 0, 1a–1c | Complete |
| 2 | Complete @ `8e79ea2` |
| 3 decision | Complete @ `4018f41` |
| 3 execution | Complete @ `ed9f882` (3b–3f including 3e worktree prune) |
| 4 | Complete @ `6246920` |

## Concurrent epic (not blocking consolidation)

**Training pipeline automation PR5–PR7** — Phases 4–6 in [`docs/plans/TRAINING_PIPELINE_AUTOMATION_PLAN.md`](docs/plans/TRAINING_PIPELINE_AUTOMATION_PLAN.md). PR1–PR4.1 shipped and pushed.

## Deferred (operator-confirmed 2026-05-23)

- G-series Model Lifecycle
- V3 Infrastructure Governance INF-1–4
- Coverage Proof Phase 2
- Pilot v1.1

---

## Conflict resolutions

| Topic | Authority |
|-------|-----------|
| Promotion policy | `arch_competition.promotion_engine.PromotionPolicy` + `decide_promotion` + `promotion_execution.execute_promotion_if_eligible`; root `PROMOTION_POLICY.md` is **Historical** |
| Read-first source | `AGENTS.md` banned tools; `CLAUDE.md` Read-not-scan for Schwab |
| V4 register | **`governance/artifacts/schwab_v4_register_build_meta.json`** + generation recipe; full CSV generated locally/CI, gitignored |
| Host vs Git | [`docs/host/README.md`](docs/host/README.md) |
| Host auto-promote | **On by default** (`ED_SCHEDULER_AUTO_PROMOTE` defaults to enabled): successful train + governed eval → `models/active/` via `execute_promotion_if_eligible` (parallel on `keep_incumbent`, cascade when gates pass). Panic: `ED_DISABLE_AUTO_PROMOTE=1`. Host reload proof still tracked in OPEN_ITEMS `TRAINING-HOST-LIVE-RELOAD`. |
| OPEN_ITEMS archive path | `governance/archive/<quarter>/open_items_archive/` (first use creates quarter folder) |

---

## Known risks

- **CI:** `schwab-csv-first.yml` on every push/PR (CSV-first + committed meta/scoreboard pin; diff-emission on **pull_request** only). **`pytest.yml`** on every push/PR (`npm run test:all` — Playwright E2E + full pytest). **D17 closure** (`unreviewed_count == 0`) — local register @ tip passes (`replaced_count=34`, `bare_governed_exception_count=0`); commit meta/scoreboard + slice-builder line fixes before claiming CI green.
- **Memory portability:** `AGENTS.md` + repo `MEMORY.md` (Phase 1c) = portable; `[OPERATOR-ONLY]` prefs stay machine-local until archived.
- **Long branch:** prefer small consolidation commits; no force-push.
- **`config.py` credentials:** hardcoded Schwab API key/secret **removed** @ tip — `build_config` requires `SCHWAB_API_KEY` + `SCHWAB_APP_SECRET` env vars (fail-closed). **Operator action:** rotate keys in Schwab Dev Portal (prior values were in git history), set env before server start. Tests: `tests/test_governance_consolidation.py`.
- **`verify_active_models.py`:** exit 1 on many non-core tickers; SPY/QQQ/IWM compliant — expected, not broken stack.
- **Pre-commit (Phase 4):** `pre-commit install` + `pre-commit install --hook-type commit-msg` — runs governance slice + deferral guard + `check_no_grep_subprocess.py` on staged files. `pre-commit run --all-files` is the acceptance bar.

---

## UI card provenance spec (Claude design brief — Issue 18 card system)

**Keep existing card chrome:** `.tf-signal-card`, Horizon alignment (`dr-align-1m` … `dr-align-60m`), Decision Rail, `.tf-signal-card--trade-active` color semantics.

**Each horizon pill must show a source chip** (one of, from `mh_prob_source_by_horizon` already in API payload):

| Chip | Meaning | Operator text |
|------|---------|---------------|
| `EMPIRICAL` | Similar-setup histogram only | "N similar setups" |
| `ML FUSION` | Full stack fusion authoritative for that horizon | "Stack trained" |
| `BLEND` | **Opt-in only** — `ED_MH_EMPIRICAL_SUPPORT > 0` | "Stack + history" |
| `UNAVAILABLE` | Missing bundle or stack failed | "No ML — WAIT" |
| `DEGRADED` | Training audit NO-GO or incomplete 16-file bundle | "Data quality hold" |

**Call / forward direction (single authority line):** only when `canonical.provenance === 'bayesian_fusion'` — label **"Fusion authoritative"**. Otherwise show **"Not tradable — empirical context only"** (no LONG/SHORT styling on forward row).

**Layout (within one card, top → bottom):**
1. Horizon row — 4 pills, each: direction + confidence + **source chip** + sample count when empirical.
2. Fusion authoritative strip — dominant direction + agreement % (only when fusion available).
3. Empirical context line — tier label + N setups (always visible when N>0, muted when ML authoritative).
4. Degraded banner — red/slate bar when `stack_integrity_v1.degraded` or bundle incomplete.

**Do not** collapse the three pipelines into one number without a chip. **Do not** hide UNAVAILABLE/DEGRADED behind neutral gray that reads as "WAIT setup."

### UI design lock — operator verdict 2026-05-27 (binding, all agents)

The chip + unified `signal-rail-card` design is the **single source of truth**. The following surfaces were intentionally removed and **MUST NOT** be re-introduced:

| Removed surface | Reason |
|---|---|
| `dr-fusion-authority-strip` + `dr-empirical-context-line` inside the Decision Rail card (commit `c0770f6`) | Operator: "no co-existing your design rules" — parallel surface duplicated `signal-rail-card` |
| Decision Command verdict row (`dr-trade-pill` / `dr-bias-pill` / `dr-desk-confidence` / `dr-confidence-pill`) | Duplicated `signal-rail-card` (Entry armed + ↑ LONG + agreement + conviction) |
| Decision Command title strip ("DECISION COMMAND · Operator surface · bar horizons map…") | Redundant header chrome; chip ribbon stays |
| Dormant legacy `.tf-source` CSS rules (`--hidden` / `--empirical` / `--ml` / `--blend` / `--unavailable` / `--degraded`) | Pre-mockup; chip system uses `.tf-source-chip` |

**Mechanical enforcement:** `tests/test_issue18_ui_contract.py` — `test_no_decision_verdict_row_pills`, `test_no_cursor_parallel_fusion_strip`, `test_no_legacy_tf_source_classes`, `test_no_decision_command_title_strip`, `test_signal_rail_card_is_present_positive_lock`. Re-adding any removed surface fails the suite → blocks commit.

**Cursor + any other agent:** do not refactor the Decision Rail card chrome, do not re-mount the verdict pills, do not re-introduce parallel fusion-authority strips. If you genuinely need to change UI provenance behaviour, propose first; do not edit silently.

**Feature registry (operator):** `python tools/validate_feature_contracts.py` — categorized XGB/LSTM/fusion lists; LSTM registry now tags structure / micro / cross-asset / cf_* streams separately.

---

## Claude audit handoff — Cursor slice 2026-05-27 (CLOSED @ `cb40b80`)

**Status:** Claude reaudit **signed off** — `AUDIT-CURSOR-DATA-UI-SLICE-2026-05-27` closed @ `cb40b80` (doc pin `6335015`).  
**Branch:** `feature/institutional-key-levels`  
**Audit range:** `f078593` … `6222cc6` (initial); fixes `cb40b80` + `6335015`.

### FIND resolution (all closed — no new FINDs)

| FIND | Fix |
|------|-----|
| QQQ backfill math | `weighted_pushes_from_snapshot_row` uses full `QQQ_TOP`; `merged_snapshot_chg_map` + `confluence_quote_ticks` as-of `ts_utc` for WMT/GOOG; tests `test_qqq_weighted_push_full_top_matches_build_confluence`, `test_backfill_weighted_pushes_uses_quote_ticks` |
| IWM backfill math | `blend_iwm_weighted_push` (55/45) shared with `iwm_blended_participation_push`; backfill no longer sector-only; test `test_iwm_weighted_push_matches_blended_participation` |
| Doc / UI drift | Claude `signal-rail-card` UI + `test_issue18_ui_contract.py` (25/25); OPEN_ITEMS supersede Cursor UI closure @ `c0770f6` |

### Commits in scope (Read in order)

| SHA | Summary |
|-----|---------|
| `f078593` | panel_auto thin logging, confluence capture gate, audit/verify ML-only scope, `mh_prob_source_by_horizon`, horizon source chips, `pre_train_gate` in `ml_scheduler.run_once`, persistence map |
| `c0770f6` | Decision Rail fusion-authority strip + empirical context line |
| `1af892e` | Initial Claude audit handoff docs |
| *(tip)* | qqq_weighted_push historical backfill, quote-tick impute, audit bugfixes |

**Closure SHA:** `cb40b80` (fix) · tip `6335015` (OPEN_ITEMS pin)

### Files — Read end-to-end (producer/consumer cone)

`server.py`, `db.py`, `market_context.py`, `market_state.py`, `scheduler_user_tickers.py`, `audit_model_readiness.py`, `verify_active_models.py`, `ml_scheduler.py`, `feature_contracts.py`, `backfill_snapshot_derived.py`, `static/index.html`, `ACTIVE_PROGRAM.md`, `OPEN_ITEMS.md`, `governance/artifacts/persistence_consumer_map.json`, `tests/test_scheduler_user_tickers_return_type.py`, `tests/test_issue18_ui_contract.py`, `tests/test_feature_contract_validation.py`, `tests/test_training_canonical_input.py`.

### Verification commands (must pass at tip)

```text
python -m pytest tests/test_scheduler_user_tickers_return_type.py tests/test_issue18_ui_contract.py tests/test_feature_contract_validation.py tests/test_training_canonical_input.py -q
python audit_model_readiness.py
python verify_active_models.py
python tools/validate_feature_contracts.py
python db_health_audit.py
python backfill_snapshot_derived.py --skip-normalizer
```

### Operator DB results @ tip (local, not in git)

| Metric | Before slice | After backfill |
|--------|--------------|----------------|
| `qqq_weighted_push` NULL (RTH norm) | ~30.7% | **0.0%** (1/75,853) |
| `spy_weighted_push` NULL | ~0% | **0.0%** |
| `iv_rank` NULL | ~82% | **6.1%** |
| `confluence_quote_ticks` rows | 0 | fills on next live session |
| `audit_model_readiness` PRE-TRAIN GATE | broken / NO-GO | **GO** |
| `snapshots_1m_normalized` rows | 107,774 | 107,774 (rematerialized) |

### Closed OPEN_ITEMS @ closure

- `AUDIT-CURSOR-DATA-UI-SLICE-2026-05-27` @ `cb40b80`
- `UI-CARD-PROVENANCE-CHIPS` @ `cb40b80` (supersedes `c0770f6`)
- `QQQ-WEIGHTED-PUSH-HISTORICAL-NULLS` @ `cb40b80`
- `AUDIT-MODEL-READINESS-BUGFIX` @ `c32ae4b`

### Still open (post-audit — not blockers for slice sign-off)

| Item | Status |
|------|--------|
| `DATA-PIPELINE-INTEGRITY-CHAIN` | pre_train_gate wired; core trio artifact compliance + liquidity training host run not green |
| `SPY-60C-XGB-META-BUNDLE` | `[REAL-GATE: host-only]` — `xgb_SPY_60c.pkl` + `meta_SPY_60c.pkl` missing in `models/active/SPY/` (lstm/transformer present) |
| `verify_active_models.py` | Many non-core tickers NON-COMPLIANT (expected); SPY/QQQ/IWM core check required |
| `TRAINING-PIPELINE-NO-SILENT-DEATH` | preflight (1) satisfied by gate; ledger/resume not implemented |

### Claude audit checklist

1. **Confluence path:** `fetch_market_context` → `_ensure_mkt_ctx_confluence_complete` → quote-tick impute → `SnapshotRow.*_weighted_push` → normalizer.
2. **UI honesty:** horizon chips match `mh_prob_source_by_horizon`; fusion strip uses `isFusionAuthoritative(d)` only.
3. **panel_auto:** no full `_fetch_state` in logger; thin `confluence_quote_ticks` only.
4. **pre_train_gate:** `ml_scheduler.run_once` fail-closed exit 2; skip via `ED_ML_SCHEDULER_SKIP_PRE_TRAIN_GATE=1`.
5. **Backfill math:** `weighted_pushes_from_snapshot_row` + `blend_iwm_weighted_push` match live `qqq_confluence` / `iwm_blended_participation_push` (tests: full QQQ_TOP, IWM blend, quote-tick as-of).
6. **Training boundary:** `training_canonical_input` NaN→None for `absorption_score` (existing; re-verify).

### Excluded from repo

`.claude/settings.local.json`, `static/ui_card_provenance_mockup.html`.

---

## Tool-specific notes

### Cursor

- Always-on: `.cursor/rules/00-always.mdc` → read `ACTIVE_PROGRAM.md` → `AGENTS.md` → `CLAUDE.md` (Schwab work).
- Skills: task-scoped; do not override AGENTS.
- `move_agent_to_root`: operational only, not a substitute for reading AGENTS.

### Claude Code

- **AGENTS.md auto-load:** pending Phase 0 marker test post-1a; if marker absent at fresh session, merge AGENTS content into CLAUDE.md (record here).

---

## Stale backlog

(Unchecked OPEN_ITEMS rows > 30 days without owner — populated during quarterly review.)

---

## Schwab V4

**Active program:** Schwab Universal Coverage V4 (`governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md`).

**Walk order (binding on agents, 2026-05-24):** (1) full Read + fix wire FINDs in-cone + consolidate/delete dead files; (2) gatekeeper `--gatekeeper-crosscheck`; (3) paired tests; (4) disposition memo last (CI receipt, not the work). Local multi-GB generated register CSVs are gitignored — delete on sight; meta pin in `governance/artifacts/schwab_v4_register_build_meta.json` is the tracked source of truth.

**Money-path roster (AGENTS.md):** all 11 modules walked @ `9e88491`. All 16 V4 review memos pass gatekeeper CSV cross-check @ `fa4c6d7` (10 legacy memos retroactive appendix).

**D17 register scope (binding):** Closure = `unreviewed_count == 0` on the **scoped register** (gitignore + `SCAN_SCOPE_EXCLUDE_PREFIXES` in meta `scanner_flags`). Regen + slice merge pipeline: `stream_revert_v4_register_and_sync_perf.py --refresh-slice-baselines`, `--run-slice-builders`, `--merge-slices`. **Operator eyes** = trade-decision cone wire fixes; **slice merge** = honest REPLACED/GOV on matched sites (not classifier-tail NMD on product code).

**config.py credentials:** env-only `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET` required @ tip — hardcoded secrets removed; operator must rotate exposed keys in Schwab Dev Portal and set env before server start.

---

## Consolidation baseline (Phase 0 @ `dbb57c9`)

- Root `.py`: 132  
- Governance MD: 113 files / 16675 lines  
- Worktrees: ~2.3 GB  
- Artifacts: `governance/consolidation/phase0/`
