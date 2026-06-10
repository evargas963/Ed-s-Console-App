> **Classification:** Active Rule Source | **Scope:** Always-on agent behavior rules (Cursor + Claude Code).

# AGENTS.md — always-on agent rules (EdWebConsole)

**Status:** Phase 1a consolidation + 2026-05-24 rule promotion (closure / no-deferral / no-new-files).  
**Sources:** `docs/governance/AGENT_SELF_GOVERNANCE.md`, `CLAUDE.md` (Schwab law only). Archived memory under `governance/archive/` is **historical only** — if it disagrees with this file, **AGENTS.md wins**.

Process mechanics (alternation, 7-artifact sign-off, slice tags) remain in [`docs/governance/AGENT_SELF_GOVERNANCE.md`](docs/governance/AGENT_SELF_GOVERNANCE.md).

Schwab market-field methodology remains in [`CLAUDE.md`](CLAUDE.md).

Current program: [`ACTIVE_PROGRAM.md`](ACTIVE_PROGRAM.md).

---

## World-class / institutional code gate `[PROMOTED]` (2026-05-27 — operator binding, top rule)

**Before writing or landing code:** research when uncertain (Read end-to-end, trace producer→consumer, check enrollment and data contracts). Then ask:

1. Would an **MIT professor** accept this in a production trading-systems course (correctness, proofs, tests, no hand-waving)?
2. Would the **world's greatest coder** ship this without apology (clarity, uniformity, no silent shortcuts)?

If either answer is **no**, **stop** — fix the design or implementation before coding. This is a homegrown app; when done it must **rival any institutional platform**. **Substandard is not acceptable** — not in architecture, not in partial stacks, not in "we'll fix it later."

### Always-on institutional binding `[PROMOTED]` (2026-05-27 — no operator activation phrase)

**This section is always in force.** The operator does **not** need to type `INSTITUTIONAL STRICT`, restate the MIT bar, or re-prompt lane ownership each turn. If ACTIVE_PROGRAM + this file are in scope, compliance is mandatory.

| Before any edit | Requirement |
|-----------------|-------------|
| Read order | `ACTIVE_PROGRAM.md` (lane + epic owner) → this §World-class gate → cone files **end-to-end** ([§Banned tools](#banned-tools-promoted-memory-feedback_no_grep_toolmd-2026-05-22) — no grep/scan) |
| Intent | **Design brief ≠ build.** Text in ACTIVE_PROGRAM marked design brief / Claude design / operator design is **not** authorization to implement in Cursor unless the same section or the operator message explicitly says **Cursor UI authorized** or **`CURSOR-UI-AUTHORIZED`**. |
| UI lane | **No edits** to `static/index.html`, `templates/**`, or UI closure rows unless UI lane is explicitly authorized as above. Default: UI design = Claude (or named owner), Cursor = data/audit/scheduler/money-path unless ACTIVE_PROGRAM assigns otherwise. |
| Before landing code | State MIT professor + world's greatest coder yes/no in the **same turn** as the edit (not deferred). If **no** → do not land. |
| Closure | No `[x]` OPEN_ITEMS without commit SHA + test cite. No audit-row self-close by the implementer. |
| Conflict | Operator message vs ACTIVE_PROGRAM lane vs this gate → **stop**, name the conflict, do not implement around it. |
| Completion | [§Completion in touched cone](#world-class--institutional-code-gate-promoted-2026-05-27--operator-binding-top-rule) — known FINDs in the Read cone must close in-turn or get `[REAL-GATE: …]` in OPEN_ITEMS. |

**Anti-pattern (rejection-grade):** Treating a spec-shaped paragraph (chips, layout, field names) as a build ticket without checking **who owns implementation** in ACTIVE_PROGRAM.

| Must hold | Failure mode |
|-----------|----------------|
| Operator intent wired in code, not comments only | "Policy by design" that contradicts stated product rules |
| **Design brief ≠ Cursor build** (always-on binding above) | Cursor implements UI/card chrome while ACTIVE_PROGRAM assigns design to Claude |
| Train-success-live for ML scheduler targets | Train completes but `models/active/` empty without explicit operator opt-out |
| **Full parallel stack uniformity** | XGB-only rows, 0.333 meta filler, or parallel eval degrade while cascade skips — partial stack without explicit governed exception |
| Governed eval compares architectures on **aligned row sets** only | Raw row-count mismatch failures |
| Confluence-only symbols excluded from training | `panel_auto` tickers trained like tradeables |
| Live UI shows honest state | Gray cards mistaken for broken pipeline when policy is WAIT |
| **Operator-surface legibility** | WAIT/neutral cards indistinguishable from page chrome; operator cannot read horizon + confidence at a glance |
| **Live accuracy** | `/api/state` `mhap_rows` diverges from `tools/live_diag_compare.py` for same ticker without documented reason |
| **Completion in touched cone** | Turn ends with known FINDs in files/cone Read this session still open (no `[REAL-GATE: …]` row) |
| **ZERO-BIAS ablation** (data decides placement; no pre-decision anywhere) | `members` routing, bundled groups, curated LSTM channel lists, XGB-only discovery, fabricated neutrals, partial grids (feature×horizon-only or base-3-only), or describing survivors as "per model" without horizon |

**Completion discipline (binds every turn):** [§Meet-or-Exceed Closure Cycle](#meet-or-exceed-closure-cycle) is the **universal** completion standard for the **full repo** — every turn, every deliverable, every sign-off. It subsumes [§Fix everything we touch](#fix-everything-we-touch) + [§Closure definition + no-deferral](#closure-definition--no-deferral). Open a file or cone → fix every FIND there before sign-off. ML/UI/money-path change → spot-check live (`tools/live_diag_compare.py <TICKER>`) when `mhap_rows` or cards are in scope. UI-only legibility change → paired assertion in `tests/test_issue18_ui_contract.py` (no new test file).

**Governed exception (only):** `5c` runtime may use documented `xgb_plus_transformer` stack per `ACTIVE_PROGRAM.md` — not a license for other horizons or eval paths.

**Mechanical enforcement (binding — no prose-only rules):** pre-commit → `check_fix_everything_we_touch.py` runs every repo-wide static lock in `_REPO_WIDE_STATIC_CHECK_FUNCS` plus staged locks. Before sign-off: `python tools/enforce_all_rules.py --enforce-all` (exit 0). Coverage of all 27 AGENTS `[PROMOTED]` sections: `check_promoted_agents_rules_mechanically_locked()`.

**Mandatory enforcement registry (2026-05-27 — operator binding):** Every row in the world-class gate table MUST have a mechanical lock before the rule is considered promoted. Prose-only rules are **incomplete** until the checker lands in the **same commit** as the rule text.

| Gate row | Mechanical lock | Paired test |
|----------|-----------------|-------------|
| Full parallel stack / no 0.333 filler | `tests/test_ml_predict_fail_closed.py` | same |
| Governed eval row alignment | `tests/test_arch_competition_eval_runner.py` | same |
| Live UI honest state + legibility | `tests/test_issue18_ui_contract.py` | same |
| Cards lit + no false STALE pill (live UI lane coherence) | `tools/check_fix_everything_we_touch.py` → `check_institutional_contract()` | `tests/test_check_fix_everything_we_touch.py` |
| `/api/state` ticker query (`ticker=` + `symbol=` alias) | `check_institutional_contract()` + `tests/test_batch2_analytics_bg_fail_counter.py` | same |
| Analytics `stale` ≠ SSE-connected alone | `check_institutional_contract()` + `test_analytics_stale_not_sse_connected_only` | `tests/test_batch2_analytics_bg_fail_counter.py` |
| Rule drift / excuse phrases | `check_fix_everything_we_touch.py` (pre-commit) | `tests/test_check_fix_everything_we_touch.py` |
| Deferral language | `tools/check_no_deferral_language.py` | `tests/test_check_no_deferral_language.py` |
| Live diag evidence before pipeline claims | Operator: `python tools/live_diag_compare.py <TICKER>`; agents must paste output or JSON keys when claiming pipeline state | — |
| Closure (code+test+OPEN_ITEMS) | `tests/test_governance_consolidation.py` | same |
| **Meet-or-Exceed sign-off** (VERDICT MET/EXCEEDED only) | `check_meet_or_exceed_signoff()` in `check_fix_everything_we_touch.py` | `tests/test_check_fix_everything_we_touch.py` |
| **Runtime tip = disk tip** | `GET /api/build` `git_sha` vs `git rev-parse HEAD` | `tests/test_batch2_analytics_bg_fail_counter.py` |
| **Encoder width/schema changes** | `tools/check_encoder_cone_tests.py` → `check_encoder_cone_tests()` (pre-commit when cone paths staged) | `tests/test_check_fix_everything_we_touch.py` |
| **Universal simplicity + institutional pride** (full repo; simple when simple wins) | `check_universal_code_quality_contract()` + `audit_staged_python_simplicity()` + `python tools/enforce_all_rules.py --code-quality` | `tests/test_check_fix_everything_we_touch.py::test_universal_code_quality_contract` |
| **O-56 ablation survivor mask** (per-model×horizon; shared-snapshot mask fail-closed + confirm-verified, no fabricated default) | `arch_competition/stack_bundle_eval_v1.py::resolve_ablation_drop_group_ids` (fail-closed to full feature set) + `confirmed_drop_group_ids_by_model_horizon` / `globally_safe_drop_group_ids` (intersection) | `tests/test_ml_feature_schema_parity.py::test_ablation_survivor_training_mask_defaults`, `::test_globally_safe_drop_is_confirm_verified_intersection`, `::test_primary_pass_recommendation_alone_is_not_a_verified_drop` |
| **Schwab-catalog ablation universe** (≥2× ML cone; no stack-only pre-pick) | `check_ablation_schwab_universe_contract()` in `check_fix_everything_we_touch.py` | `tests/test_ml_feature_schema_parity.py::test_schwab_ablation_universe_contract` |
| **Full stack — all seven models named** (no partial stack lists) | `check_full_stack_models_contract()` in `check_fix_everything_we_touch.py` | `tests/test_ml_feature_schema_parity.py::test_full_stack_models_contract` |
| **ZERO-BIAS — data-driven placement** (repo-wide; survivor output is the only router) | `check_zero_bias_ablation_contract()` + `check_ablation_agnostic_ingest_contract()` + `check_ablation_seven_model_four_horizon_grid()` + `check_ablation_full_stack_non_negotiable()` + `check_graphrag_fidelity_ablation_contract()` in `check_fix_everything_we_touch.py` + `python tools/feature_curation_gate.py --ablation-audit` | `tests/test_check_fix_everything_we_touch.py::test_zero_bias_ablation_contract`, `::test_ablation_agnostic_ingest_contract`, `::test_ablation_grid_requires_all_seven_models_and_four_horizons`, `::test_ablation_full_stack_non_negotiable_contract`, `::test_graphrag_fidelity_ablation_contract` |
| **Objective → Code → Audit closure** (mandatory turn protocol; **full repo**; situational runtime where cone fits) | `run_repo_wide_static_audit()` + `run_objective_code_audit()` + `run_situational_runtime_audits()` + `check_objective_code_audit_signoff()` + `python tools/enforce_all_rules.py --objective-audit` | `tests/test_check_fix_everything_we_touch.py::test_objective_code_audit_contract`, `::test_objective_code_audit_universal_scope`, `::test_objective_code_audit_situational_runtime_dispatch` |
| **Fusion-only horizon cards** (zero default blend; withhold product triplets when fusion missing; 5th ALL consolidated card) | `check_fusion_only_card_contract()` in `check_fix_everything_we_touch.py` | `tests/test_check_fix_everything_we_touch.py::test_fusion_only_card_contract`, `tests/test_prediction_engine_chunk1_fail_closed.py::test_overlay_withholds_product_triplets_when_fusion_missing`, `tests/test_issue18_ui_contract.py` (consolidated + no-implicit-blend) |
| **Schwab fix-as-we-touch** (every Read in producer/consumer cone → leaf disposition or O-NN) | `tools/check_schwab_csv_first.py` (pre-commit + CI diff-emission on new market-fact sites) + `CLAUDE.md` line-by-line method | `tests/test_check_schwab_csv_first.py` — **honest limit:** repo-wide leaf walk is cone-by-cone work, not one regex gate |
| **Mandatory registry completeness** (no prose-only promoted rules) | `check_mandatory_enforcement_registry()` + `check_promoted_agents_rules_mechanically_locked()` + `python tools/enforce_all_rules.py --enforce-all` | `tests/test_check_fix_everything_we_touch.py::test_mandatory_enforcement_registry_passes_on_current_repo`, `::test_promoted_agents_rules_mechanically_locked` |
| **Unified stack canonical vocabulary** (seven-layer team; legacy names alias-only) | `check_unified_stack_canonical_vocabulary()` + `check_unified_stack_team_contract()` | `tests/test_check_fix_everything_we_touch.py::test_unified_stack_canonical_vocabulary_checker`, `::test_unified_stack_team_contract_checker` |
| **All external rule tools wired** | `check_external_rule_tools_wired()` | `tests/test_check_fix_everything_we_touch.py::test_external_rule_tools_wired` |

**Pre-commit:** `check_institutional_contract()` runs on **every** commit (via `check_fix_everything_we_touch.py`), not only when UI files are staged. A promotion without a registry row + checker is rejection-grade.

### Rule enforcement — agent binding (2026-06-06 — operator)

| Agent | What is mechanically enforced | Honest limit |
|-------|------------------------------|--------------|
| **Either agent at commit** | pre-commit → `check_fix_everything_we_touch.py` (static locks, banned phrases in staged source + commit msg) | Only runs when committing |
| **Either agent before sign-off** | `python tools/enforce_all_rules.py --enforce-static` + `--code-quality` | Does not scan chat output |
| **Claude Code at turn-end** | `.claude/settings.json` Stop hook → `enforce_all_rules.py --stop-hook` (output phrases + session-touched files) | Claude harness only |
| **Cursor during chat** | `.cursor/rules/00-always.mdc` → read AGENTS; no output hook exists | **Cannot** mechanically block Cursor chat violations today |

Prose-only rules without a registry row + `check_*` lock are **incomplete promotions** — rejection-grade per the table above.

---

## Universal code quality — simplicity and institutional pride `[PROMOTED]` (2026-06-06 — operator binding; full repo)

**Scope — universal:** Every file, every subsystem, every language — ML, UI, money-path, Schwab, governance, tooling, tests. Not ablation-only. This section **extends** [§World-class / institutional code gate](#world-class--institutional-code-gate-promoted-2026-05-27--operator-binding-top-rule); it does not replace it.

**Operator binding:** Code must be **as simple as the problem allows** and **as sophisticated as the problem requires** — never the reverse. **Simple when simple beats complication.** Overcomplication when a direct path exists is rejection-grade. Sloppy or ugly code when a clean path exists is rejection-grade. You should feel **pride** presenting the work: an MIT professor reviewing it for a production trading-systems course would call it **high quality** — correct, readable, tested, no hand-waving, no accidental complexity.

| Principle | Requirement | Rejection-grade |
|-----------|-------------|-----------------|
| **Simple beats complicated** | Prefer the smallest correct design; one clear path; delete duplicate/dead branches | Parallel flag paths, cell gating, wrapper layers for one caller, “framework” for a single use |
| **Sophisticated when warranted** | Hard domains get rigorous structure — contracts, tests, named boundaries | Hand-waving, silent defaults, magic numbers without contract |
| **Pretty / readable** | Uniform naming, obvious file ownership, functions that read top-to-bottom | Spaghetti, mixed concerns, 200-line nested blocks, copy-paste divergent twins |
| **Institutional pride** | Would you sign your name on this diff? | “Good enough”, “works for now”, shame-apology comments |

**Before landing code:** ask (same turn, not deferred):

1. Is this the **simplest design that is still correct**?
2. Is every non-trivial piece **sophisticated enough** (contracts, tests, fail-closed)?
3. Would an **MIT professor** deem this **high quality** without asterisks?

If any answer is **no** → redesign or simplify before commit.

**Agent/operator audit (every turn that lands code — exit 0 required):**
```bash
python tools/enforce_all_rules.py --code-quality
```
Pre-commit runs static locks on every commit; `--code-quality` is the explicit full-repo audit before sign-off.

**Mechanical lock:** `check_universal_code_quality_contract()` + `audit_staged_python_simplicity()` in `check_fix_everything_we_touch.py` — **every pre-commit** on staged production Python. Paired: `tests/test_check_fix_everything_we_touch.py::test_universal_code_quality_contract`.

**Honest limit (binding disclosure):** The mechanical lock is a **smell-detector**, not a simplicity guarantee. It **hard-fails** duplicate `def` names in staged production Python (copy-paste twins). It **warns only** (does not block commit) on functions longer than 150 lines — including pre-existing orchestrators like `tools/feature_curation_gate.py`; touching those files will surface warnings, not force artificial splits. **Architectural** over-complication (parallel scoring paths, stale-bundle machinery, one-caller wrappers) requires end-to-end Read + judgment + the MIT bar — not regex. Pre-commit cannot replace that; neither can splitting a legitimate 165-line report builder to satisfy a line threshold.

---

## Ablation universe — Schwab-catalog first `[PROMOTED]` (2026-06-04 — operator binding)

**Agents MUST NOT pre-pick ablation winners** by restricting the candidate set to what the current ML stack already consumes. That is rejection-grade scope-narrowing.

| Requirement | Violation |
|-------------|-----------|
| **Categorize all Schwab dictionary rows** (2393) in `governance/artifacts/schwab_ablation_field_registry.json` before ablation manifest work | Manifest built only from `engineer_features` / registered cone |
| **Ablation pool ≥ 2× registered ML cone** (`MIN_ABLATION_EXPANSION_FACTOR`) including Schwab `ML_*` tiers + snapshot expansion | Compound split / "123 atomic groups" from stack-only cone |
| **Ablation decides DROP/KEEP** — workbook `horizon_disposition` is informational only | Pre-culling groups before permutation pass |
| **`not_wired` Schwab candidates stay in manifest** for **materialization + discovery ablation** — never wire to production until additive | Silently excluding unexplored Schwab leaves; **production wiring before ablation proof** |

**Canonical builders:** `tools/build_feature_assignment_matrix_v2.py::build_schwab_ablation_field_registry`, `::resolve_expanded_schwab_ablation_universe`, `::write_feature_ablation_manifest`.

**Mechanical lock:** `check_ablation_schwab_universe_contract()` — paired `tests/test_ml_feature_schema_parity.py::test_schwab_ablation_universe_contract`.

---

## Full stack — all seven models `[PROMOTED]` (2026-06-04 — operator binding)

**Every agent turn that names the ML stack MUST list all seven models** — partial lists are rejection-grade (omitting Regime or Meta is the recurring failure mode).

| # | Slug | Role |
|---|------|------|
| 1 | `xgb` | Tabular XGBoost |
| 2 | `lstm` | LSTM sequence model |
| 3 | `transformer` | Transformer sequence model |
| 4 | `meta` | Meta-learner on base triplets |
| 5 | `monte_carlo` | Monte Carlo fusion adjustment |
| 6 | `regime` | Volatility + market regime + rules context |
| 7 | `fusion` | Bayesian fusion posterior |

**Canonical source:** `governed_stack_contract.FULL_STACK_MODEL_LAYERS` — import this tuple; do not maintain divergent local lists.

**Ablation / stack eval:** the **placement grid** is **`feature × model × horizon`** where **model** is all seven layers and **horizon** is all four (`1c`, `5c`, `15c`, `60c`). Partial grids (feature×horizon-only, xgb/lstm/transformer-only, omitting meta/monte_carlo/regime/fusion) are **rejection-grade**. All seven appear in manifest `full_stack_layers`.

**No production wiring until additive:** Schwab leaves win discovery ablation (materialized on labeled rows) before any live cone wiring.

**Mechanical lock:** `check_full_stack_models_contract()` in `check_fix_everything_we_touch.py` — paired `tests/test_ml_feature_schema_parity.py::test_full_stack_models_contract`.

---

## Fusion-only horizon cards `[PROMOTED]` (2026-06-06 — operator binding)

**One door out:** horizon product triplets on cards come from **per-horizon stack fusion only**. Empirical histograms stay on the signal rail for context — they do **not** fill product triplets unless the operator explicitly opts in.

| Requirement | Violation |
|-------------|-----------|
| Default `ED_MH_EMPIRICAL_SUPPORT=0.0` — no silent 85/15 blend | Default 0.15 or empirical fallback when fusion missing |
| Default `ED_SIGNAL_LAYER_FUSION_BLEND=0.0` in `bayesian_fusion.py` | Default 0.38 signal-layer blend on cards |
| Fusion missing → withhold `(None,None,None)` + `fusion_unavailable` | Copy empirical into product triplets |
| UI chip: `ML FUSION` when fusion authoritative; **never** implicit `BLEND` because empirical exists | `if (hzFusionOk && empPresent) return 'BLEND'` |
| Fifth **ALL** card (`tf-signal-consolidated`) reads four fusion outputs + alignment | Collapsing four horizons into one number without a chip |

**Mechanical lock:** `check_fusion_only_card_contract()` — pre-commit + `run_repo_wide_static_audit()`. Paired: `tests/test_check_fix_everything_we_touch.py::test_fusion_only_card_contract`, `tests/test_prediction_engine_chunk1_fail_closed.py`, `tests/test_issue18_ui_contract.py`.

---

## Ablation grid — all seven models × all four horizons `[PROMOTED]` (2026-06-05 — operator escalation; non-negotiable)

**Operator binding:** ablation MUST score **every atomic feature** at **every stack model** at **every governed horizon**. There is no admissible partial grid.

| Grid axis | Required values | Partial grid = rejection-grade |
|-----------|-----------------|--------------------------------|
| **model** | All 7 — `governed_stack_contract.FULL_STACK_MODEL_LAYERS` | "3 base models", "upper stack separate", omitting meta/monte_carlo/regime/fusion |
| **horizon** | All 4 — `1c`, `5c`, `15c`, `60c` | Single-horizon runs, "primary horizon only" |
| **feature** | Full captured-cone atomic universe | Pre-cull, manifest `members` routing, compound bundles |

**Cell count:** Catalog grid = `280 groups × 7 × 4 = 7,840` accounting slots. **Runnable scored grid** = `wire_scoring_groups × 7 × 4` from `ablation_cell_accounting.runnable_target` (typically ~1,092–1,288 — not 2,632 or code-registry 94). Each runnable cell pools **SPY, QQQ, IWM**.

**Readiness requires the FULL cube — all 7 models × all 4 horizons × all 3 pool tickers (SPY, QQQ, IWM).** Preflight `ready` is **only** `ready_for_unbiased_ablation` — DB-wire agnostic ingest (`audit_ablation_ingest_purity`), row fidelity, zero score-path derailers (`audit_ablation_score_path_bias`), seven-layer probe under `ED_ABLATION_SCORING_PASS`, and `placement_validity.ok`. **`ready_for_production_path_ablation`** is the explicit alternate when score-path bias is accepted (production fusion re-engineering). XGB-loadable-alone is NOT ready; cell gating / skipped horizons / skipped models is NOT ready; DB-has-data alone is NOT ready; preflight green under ablation env while LSTM/TR knockouts are no-ops is NOT ready; **`ready_for_whole_stack` alone is NOT unbiased green**.

**Agent/operator audit (every ablation turn — exit 0 required before claiming complete):**
```bash
python tools/feature_curation_gate.py --ablation-audit
python tools/enforce_all_rules.py --objective-audit
```
Static locks run on every pre-commit; runtime preflight runs when `data/ed_console.db` exists.

**Banned agent vocabulary:** "feature×horizon only", "Stage 3 without model axis", "base models only for placement", "meta/MC/regime/fusion don't consume features so skip them", "ready" while any pool ticker or horizon is blocked, describing `--ablation` as complete without all **runnable** cells scored (denominator from `ablation_cell_accounting.runnable_target`, not catalog slots).

**Mechanical lock:** `check_ablation_seven_model_four_horizon_grid()` + `check_ablation_full_stack_non_negotiable()` + `check_graphrag_fidelity_ablation_contract()` + `check_ablation_agnostic_ingest_contract()` in `check_fix_everything_we_touch.py` — **every pre-commit**. Runtime: `run_ablation_integrity_audit()` via `--ablation-audit` or `python tools/enforce_all_rules.py --ablation-bias`. Preflight requires `audit_ablation_ingest_purity()` + `audit_ablation_row_fidelity()` + `audit_ablation_score_path_bias()`. Paired: `tests/test_check_fix_everything_we_touch.py::test_ablation_grid_requires_all_seven_models_and_four_horizons`, `::test_ablation_full_stack_non_negotiable_contract`, `::test_graphrag_fidelity_ablation_contract`, `::test_ablation_agnostic_ingest_contract`.

**Scored run scope (2026-06-07):** Manifest retains full Schwab catalog (280 groups). Stage 3 scores **DB wire atoms only** (`ablation_scoring_groups` ∩ `ablation_db_wire_ablatable_columns`). **Runnable denominator** = wire features with knockout column on identity-enriched rows × 7 models × 4 horizons (typically **~39–46 × 28 = 1,092–1,288** on SPY/QQQ/IWM — not catalog-inflated 2,632 or code-registry 94). XGB-engineered-only manifest atoms (`time_cos`, `dgex_positive`, `cf_*`, …) without a DB column are **honestly not runnable** until persisted to `snapshots_1m_normalized` or reclassified. Catalog-only `not_wired` Schwab slots are **not** walked during `--ablation`.

---

## GraphRAG fidelity-first — ablation and experimentation `[PROMOTED]` (2026-06-07 — operator binding)

**Problem:** Grep/scan/isolated Read misses producer→consumer bias (registry pre-placement, confluence on enrich path, fallback knockouts, noop cells scored as ok, preflight green while score path re-engineers). That is rejection-grade experimentation malpractice. Prior agents certified MET/institutional while omitting these layers — **green = unbiased only when every row below is bias-free or explicitly gated**.

**Binding method (mandatory before ablation code changes, preflight, or restart claims):**

1. **GraphRAG cone trace** — canopy → trunk → branch → leaf for every hop (table below). No stopping at registry, manifest stamp, or `ms_dict`.
2. **DB identity row surface** — `_enrich_rows_for_whole_stack_ablation` = shallow copy of DB snapshot dict only. **Banned on ingest:** `attach_confluence_feature_columns`, `ml_train` engineer, `engineer_single_snapshot`, registry fallbacks.
3. **Wire-only scoring universe** — `ablation_scoring_groups(manifest, db_path)` = manifest `in_cone` ∩ `ablation_db_wire_ablatable_columns`. One DB column = one ablatable atom.
4. **Fidelity-first knockouts** — unified `_whole_stack_knockout_columns` per feature across all seven layers; `model_family` tags attribution only.
5. **Preflight hard gate** — `ready` = `ready_for_unbiased_ablation` only (`audit_ablation_ingest_purity` + `audit_ablation_row_fidelity` + `audit_ablation_score_path_bias.ok` + placement). Use `ready_for_production_path_ablation` when accepting documented score-path bias.
6. **No narrow isolation** — ablation FINDs require Read end-to-end of the full inventory cone in the same turn.

### Ablation producer→consumer inventory (canopy → trunk → branch → leaf)

| # | Canopy | Trunk | Branch (file:fn) | Leaf | Bias? |
|---|--------|-------|------------------|------|-------|
| 1 | `--ablation` cell spec | `group_id`, `model_family`, `horizon_slug` | `feature_curation_gate.py:ablation_whole_stack_feature_cell_specs` | manifest `feature_ablation_manifest_leaf.json` | **no** at score — wire filter + `ablation_scoring_groups(db_path=)` is authority |
| 2 | Scoring universe filter | `ablation_scoring_groups` list | `feature_curation_gate.py:ablation_scoring_groups` → `ablation_db_wire_ablatable_columns` | `snapshots_1m_normalized` PRAGMA columns | **no** when wire filter live |
| 3 | DB row load | row dict keys | `stack_bundle_eval_v1.py:_load_chronological_rth_rows` | `db.py` / `snapshots_1m_normalized` SELECT | **no** |
| 4 | Row enrich (ingest) | enriched row dict keys | `feature_curation_gate.py:_enrich_rows_for_whole_stack_ablation` | same DB keys (+ `__ablation_ticker`) | **no** (identity); **was yes** with `ml_data_common.attach_confluence_feature_columns` |
| 5 | Knockout column resolve | `group_columns` | `feature_curation_gate.py:_whole_stack_knockout_columns` → `_ablation_atomic_knockout_column_candidates` | DB wire column name | **no** |
| 6 | Permute / null column | permuted row dict | `stack_bundle_eval_v1.py:apply_ablation_knockout_columns` | knocked-out DB wire value | **no** at knockout |
| 7–10 | All seven layers (XGB→Fusion) | fusion triplet + `stack_layers_scored` | `_production_fusion_prob_for_row` → `ablation_bundle_inference.score_unified_ablation_fusion_from_wire_row` (one permuted DB row; `wire_row_surface_bars` for LSTM/TR seq_len only) | same knocked-out DB wire dict for every layer | **no** — single contiguous path; no `production_fusion_payload_for_stack` fork, no DB history window, no fusion overlay |
| 11 | Cell score | `log_loss_delta` | `feature_curation_gate.py:score_whole_stack_feature_cell` | multiclass log loss vs baseline cache | **mixed** — honest if ingest+score bias disclosed |
| 12 | Survivor routing | `survivor_summary.by_model_horizon` | `feature_curation_gate.py:build_ablation_survivor_summary` → O-56 mask | scored cells only | **no** if cells honest |
| 13 | Manifest build | `groups[]` | `build_feature_assignment_matrix_v2.py:write_feature_ablation_manifest` → `_registered_ml_columns` | `ml_train` + `lstm_data` registries | **yes** for `in_cone` stamp — mitigated by wire filter at score |
| 14 | Preflight `ready` | JSON `ready` bool | `feature_curation_gate.py:run_ablation_preflight` | `ingest_purity` ∧ `score_path_bias` ∧ probe | **no** when fail-closed |
| 15 | Offline scoring env | `ED_ABLATION_SCORING_PASS=1` | `stack_bundle_eval_v1.py` → `score_unified_ablation_fusion_from_wire_row` | offline v2/v3 bundle encode on wire row surface | **no** at score path — live `ml_predict` predict forks removed |

**Mechanical lock:** `check_graphrag_fidelity_ablation_contract()` + `check_ablation_agnostic_ingest_contract()` — markers in this section + banned symbols in `tools/feature_curation_gate.py`. Paired: `tests/test_check_fix_everything_we_touch.py::test_graphrag_fidelity_ablation_contract`, `::test_ablation_agnostic_ingest_contract`.

---

## Encoder cone — mandatory pytest cone `[PROMOTED]` (2026-05-27 — closes afac60b stale-test class)

**Problem:** Hand-picked pytest slices (e.g. two `test_lstm_*` files) miss stale width/index/schema-guard tests in `test_transformer_sequence_input.py`, `test_ml_feature_provenance.py`, etc. Production can be correct while the suite is red.

**Rule:** Any change to sequence encoders, LSTM/Transformer predict/train paths, or `feature_contracts` LSTM/Transformer registries MUST pass the **encoder cone** before sign-off or commit — not a self-selected subset.

| Trigger (staged) | Action |
|------------------|--------|
| `lstm_data.py`, `lstm_model.py`, `features/lstm_sequence_input.py`, `ml_predict.py`, `transformer_train.py`, `feature_contracts.py` | Pre-commit runs cone pytest |
| Any `tests/` file matching `ENCODER_CONE_TEST_GLOBS` in `tools/check_encoder_cone_tests.py` | Same |

**Cone list (authoritative globs — extend checker + this section together):** `test_lstm*.py`, `test_transformer*.py`, `test_ml_feature*.py`, `test_ml_predict*.py`, `test_feature_contract*.py`, `test_fusion_model_input*.py`, `test_db_feature_adapter_layer5*.py`, `test_training_canonical_input.py`, `test_model_contract_enforcement.py`, `test_multi_horizon_ml_bundle*.py`.

**Agent chat / commit claims:** Do not report "N passed" or "green" on encoder work unless the command included the cone (cite `encoder-cone` or list cone test paths). Commit messages claiming pass/green without that cite are blocked when encoder paths are staged.

**Manual run:** `python tools/check_encoder_cone_tests.py` (runs pytest on the cone; exit 0 = green).

**When `LSTM_ENCODER_SCHEMA_VERSION` or `encoded_width_*` changes:** Read every file under the cone globs end-to-end for `FEATURES_5M` length/indexing and v1-shaped fake checkpoints; fix in the same commit.

---

## Meet-or-Exceed Closure Cycle `[PROMOTED]` (2026-05-27 — operator binding; universal; no partial sign-off)

<a id="meet-or-exceed-closure-cycle"></a>

**Scope — universal, not gated:** This is **the** completion standard for **all work in this repository** — repo root through every directory, extension, and program (Schwab V4, ML, UI, money-path, governance, tooling, tests, static, docs). It applies to **every agent turn** and **every deliverable** (code change, review, disposition, sign-off, chat report). It is **not** scoped to an epic, PR, subsystem, "slice", or feature area. There is no separate "operator coherence standard" vs "ML standard" vs "Schwab standard" for completion — one cycle, one verdict vocabulary, full repo.

**Problem this solves:** Agents habitually report "mostly", "partial", "B+", or "meets with gaps" and stop. That is **rejection-grade** — the standard is binary: **MET** or **EXCEEDED**. Anything else means **keep working** (return to IMPLEMENT).

### The cycle (mandatory — every turn, until MET or EXCEEDED)

```
IMPLEMENT → VERIFY → SCORE → (if any applicable row not MET/EXCEEDED) → IMPLEMENT → …
```

| Step | Action | Stop condition |
|------|--------|----------------|
| **1. IMPLEMENT** | Code + paired tests in existing owners ([§No new files](#no-new-files)); Schwab work also per [CLAUDE.md](CLAUDE.md) canopy→leaf | — |
| **2. VERIFY** | Run paired tests + `python tools/check_fix_everything_we_touch.py`; live diag when pipeline/UI/API claims are in scope; re-Read at tip before sign-off | All green |
| **3. SCORE** | Score **every applicable row** — world-class gate table, mandatory registry, [§Closure definition](#closure-definition--no-deferral) when closing FINDs, Schwab register/perf-proof when in Schwab scope | Each row **MET** or **EXCEEDED** only |
| **4. LOOP** | Any row scored PARTIAL / NO / mostly / letter-grade → return to step 1 for that row | None remain |
| **5. SIGN-OFF** | Emit the sign-off block below in chat and/or commit body | `VERDICT: MET` or `VERDICT: EXCEEDED` only |

**Banned sign-off vocabulary (rejection-grade everywhere — chat, commits, OPEN_ITEMS):** "mostly", "partial(ly) meets", "meets with gaps", "B+", "B−", "A−", "not yet", "does not exceed", "honest limit" **as the completion verdict**, "good enough", "substandard but", "for the most part", "standard met for this slice/area/section only".

**Required sign-off block** (when claiming **any** work is complete — turn report, commit, PR body):

```
VERDICT: MET | EXCEEDED
SCOPE: full repo | <named paths touched this turn — not a scope-narrowing excuse>
CYCLE_ITERATIONS: <n>
GATE_TABLE:
  <gate_row>: MET | EXCEEDED — <evidence cite: tests/… or file:line or live_diag one-liner>
```

If you cannot fill every **applicable** `GATE_TABLE` line with MET or EXCEEDED and a cite, **the work is not done** — continue the cycle. Omitting rows because they are "outside this slice" is scope-narrowing and rejection-grade.

**EXCEEDED** means: behavioral proof beyond presence markers (TestClient, Playwright driving exported helpers, negative fixture, live_diag pasted, full-file Read with file:line disposition) — not prose.

**Program closure (Schwab D17):** Register walk to `unreviewed_count == 0` is the same universal standard applied file-by-file across the full tree — not a different bar.

### Mechanical enforcement (every commit)

| Lock | What it blocks |
|------|----------------|
| `check_meet_or_exceed_signoff()` in `tools/check_fix_everything_we_touch.py` | Commit messages with `VERDICT:` not equal to MET/EXCEEDED; banned partial-completion verdict phrases |
| `check_meet_or_exceed_cycle_documentation()` | `AGENTS.md` missing this section or universal-scope binding |
| Registry rows | Each gate → checker + test (see table above) |

Paired: `tests/test_check_fix_everything_we_touch.py`, `tests/test_governance_consolidation.py`.

**Runtime vs disk:** After pull/commit, restart server; confirm `GET /api/build` `git_sha` matches `git rev-parse HEAD` before live pipeline claims.

---

## Objective → Code → Audit closure `[PROMOTED]` (2026-05-31 — operator binding; mandatory every turn; no activation phrase)

<a id="objective-code-audit-closure"></a>

**Scope — universal, full repo, not gated:** This protocol binds **every agent turn** and **every deliverable** across the entire repository — ML, UI, money-path, Schwab/market-field, governance, tooling, tests, static, docs. Same reach as [§Meet-or-Exceed Closure Cycle](#meet-or-exceed-closure-cycle). There is no separate "ablation-only" or "ML-only" completion loop.

**Operator binding — non-negotiable agent role:** Every turn that implements, fixes, audits, or signs off work follows this loop until the audit is **clean**. There is no shortcut, no weaker bar, no "runs but invalid" escape hatch.

```
OBJECTIVE → CODE → AUDIT → (defects?) RECODE → REAUDIT → … → AUDIT: CLEAN → SUMMARIZE
```

| Step | Agent duty | Stop condition |
|------|------------|----------------|
| **1. OBJECTIVE** | **State the operator objective first** in chat — one sentence naming what success looks like for *this* turn (not a generic process description) | Operator can confirm you are on the right track |
| **2. CODE** | Implement the fix / feature in existing owners ([§No new files](#no-new-files)); MIT bar + simplicity per [§Universal code quality](#universal-code-quality--simplicity-and-institutional-pride-promoted-2026-06-06--operator-binding-full-repo) | Code lands |
| **3. AUDIT** | Run `python tools/enforce_all_rules.py --objective-audit` — **repo-wide static locks always**; **situational runtime probes only where the touched cone / subsystem fits** (see table below) | `AUDIT: CLEAN` |
| **4. LOOP** | Any audit defect → **recode in the same turn** → **reaudit**; repeat until clean | Zero open defects in audit output |
| **5. SUMMARIZE** | Report findings with evidence cites only after step 4 passes | Operator sees objective + what changed + audit proof |

**Situational runtime audits (apply where the situation fits — not every turn runs every probe):**

| Situation / cone touched | Runtime audit | When it runs |
|--------------------------|---------------|--------------|
| **Any implementation turn** | Repo-wide static locks (`run_repo_wide_static_audit`) | **Always** — every `--objective-audit` |
| **Ablation / placement / ML stack bundles / `feature_curation_gate`** | `audit_ablation_placement_validity` | Staged paths hit ablation cone **or** operator runs `--objective-audit --full-runtime` **or** manual audit with ablation manifest present |
| **Ablation scored pass / survivor claims** | `run_ablation_integrity_audit` + `--ablation-bias` | Claiming ablation ready or running `--ablation` |
| **UI / pipeline / card claims** | `python tools/live_diag_compare.py <TICKER>` | `mhap_rows` or live cards in scope |
| **Encoder / LSTM / Transformer paths staged** | `python tools/check_encoder_cone_tests.py` | Pre-commit when cone paths staged |
| **Schwab market-field disposition** | Canopy→leaf trace + register row | Schwab-scope work per [CLAUDE.md](CLAUDE.md) |

**Banned agent behavior (rejection-grade):**
- Signing off, claiming "ready", "complete", `VERDICT: MET`, or running scored ablation **before** `AUDIT: CLEAN`
- Scoping the **protocol** or **static locks** to a subsystem ("ablation-only audit", "this slice only")
- Conflating grid cardinality / preflight under ablation env / "runs 2632 cells" with **valid** `(feature × model × horizon)` placement through the real seven-layer path
- Skipping step 1 (objective) or step 3 (audit) because tests passed or static locks green
- Leaving known audit defects for a "follow-up" without `[REAL-GATE: …]` in `OPEN_ITEMS`

**Required chat sign-off block** (when claiming work complete — turn report, commit, PR body):

```
OBJECTIVE: <one sentence — operator intent this turn>
AUDIT: CLEAN — python tools/enforce_all_rules.py --objective-audit (exit 0)
VERDICT: MET | EXCEEDED
SCOPE: <paths touched — full repo static; situational runtime named if run>
CYCLE_ITERATIONS: <n>
GATE_TABLE:
  <gate_row>: MET | EXCEEDED — <evidence cite>
```

**Agent/operator audit (every implementation turn — exit 0 required before sign-off):**
```bash
python tools/enforce_all_rules.py --objective-audit
# Ablation / placement claims also require:
python tools/enforce_all_rules.py --ablation-bias
# Force every situational runtime probe (operator / pre-ablation gate):
python tools/enforce_all_rules.py --objective-audit --full-runtime
```

**Mechanical lock:** `run_repo_wide_static_audit()` + `run_objective_code_audit()` + `run_situational_runtime_audits()` + `check_objective_code_audit_signoff()` in `check_fix_everything_we_touch.py` — pre-commit static wiring on **every** commit; `--objective-audit` orchestrates repo-wide static + situational runtime. Paired: `tests/test_check_fix_everything_we_touch.py::test_objective_code_audit_contract`, `::test_objective_code_audit_universal_scope`, `::test_objective_code_audit_situational_runtime_dispatch`.

**Relationship to [§Meet-or-Exceed Closure Cycle](#meet-or-exceed-closure-cycle):** Meet-or-Exceed is the **verdict vocabulary**; Objective→Code→Audit is the **mandatory turn workflow** that must complete before any `VERDICT:` is admissible — **full repo**, one cycle.

---

## Rule compliance — zero drift `[PROMOTED]` (2026-05-27 — operator binding; sits with world-class gate)

**Rules in this file are law, not suggestions.** Cursor and Claude Code must follow them on every turn. **Rule drift is rejection-grade** — the same severity as a money-path bug. Prose without a matching `tools/check_*.py` lock is an incomplete promotion; extend the checker in the **same commit** as the new rule ([§Self-governance quality loop](#self-governance-quality-loop)).

| Violation (non-exhaustive) | What happens |
|----------------------------|--------------|
| Patch in one file while a known FIND in the same cone stays open | Incomplete work — land fix + test + closure artifacts same commit |
| "By design" / "out of scope" / "not in the ticket" / "patch only" to excuse incomplete or asymmetric behavior | Banned — use code change or `[REAL-GATE: …]` in `OPEN_ITEMS` |
| Governance-only turn when operator assigned code work | Rejected — [§Code-first](#code-first--no-governance-only-turn-promoted--2026-05-25--operator-escalation) |
| Claiming complete / verified without evidence cite | Rejected — [§Do not lie to the operator](#do-not-lie-to-the-operator-promoted-2026-05-24--binding-hard-rule-no-exceptions) |
| Different agent re-introduces a miss the other agent already caught | **PROC-MISSED-FIX** row + checker extension same commit — no repeat |

**Neither agent may end a turn with:** known FINDs in files Read this session still open; closure checklist incomplete; or chat/commit text that uses banned excuse phrases ([§Banned phrases](#banned-phrases-promoted) + **Excuse / partial-completion** list).

**Mechanical enforcement (pre-commit + CI):** `tools/check_fix_everything_we_touch.py` — commit messages and staged source/docs scanned for banned phrases (`governance/forbidden_phrases.py`) and excuse patterns; investigation-only / unverified-claim guards unchanged. Paired: `tests/test_check_fix_everything_we_touch.py`, `tests/test_forbidden_phrases.py`, `tests/test_governance_consolidation.py`.

**Operator escalation:** If an agent violates this section twice on the same FIND family, the fix is **checker + test**, not another paragraph of rules.

---

## Do not lie to the operator `[PROMOTED]` (2026-05-24 — binding, hard rule, no exceptions)

**Never present unverified claims as verified. Never soften known bad news into reassurance. Never frame a clean-looking artifact (memo, green checker, handoff, status note) as proof that the underlying work was done.**

| Banned behavior | What it actually is |
|-----------------|----------------------|
| "Verified" / "confirmed" without evidence cite | Asserting certainty without doing the verification |
| "This will prevent X" about a tool/lock | Selling a partial guard as a full guarantee |
| "All sites NOT_MARKET_DATA" without full CSV cross-check | Hand-picked spot-check framed as audit |
| Omitting a known limit when describing a fix | Lie by selective framing |
| "Standing by" / clean handoff while a known FIND is unfixed | Performing readiness; the work is incomplete |
| Restating operator's view back as if independently arrived at | Agreement theater |
| "Section present" / "heading at L<n>" without reading the body | Treating structure as content — the `§File delete gatekeeper` slip (title said gatekeeper, body said catch-net; heading existed, body contradicted intent) |
| "Per [subagent / Cursor / peer] summary" without source-Read | Echoing upstream as fact — the zero-refs slip (accepted "zero references outside itself" without enumerating; 10 referrers existed) |
| "Looks clean" / "appears orphaned" / "should be safe" as verdict | Inference framed as verification; verdicts require enumerated tables or recomputed values, not impressions |
| Tool exit 0 cited as proof of correctness | Tool ran; doesn't prove the right thing was checked. Cite both the tool AND the intent it verified |
| Count match (rows / files / tests pass) cited as content match | Cardinality alignment ≠ semantic alignment; 174459 rows can sum correctly while individual dispositions are wrong |
| "Same gap applies" / "parallel pattern" / "extends to" without same-turn verification | Scope-extension lie — the bid/ask parallel slip (2026-05-25: claimed server.py L2328-2333 had "same vocab+AST gap" as the verified L2334-2341 set, then admitted "haven't done it this turn"). An unverified parallel observation is just an unverified claim wearing a humility costume. |
| "Haven't verified" / "haven't checked" / "separate verification" / "out of scope of this turn" as live caveats in the body of a response | The admission is the violation. If the claim couldn't be verified in-turn, the claim shouldn't be in the response — verify or omit. Caveats narrate the gap; they don't close it. |

**When uncertain, say uncertain.** When a tool or rule has a known limit, name the limit in the same sentence that describes the tool. When operator catches a slip, correct in the same turn, not the next.

**Verdict discipline (universal):** Before any verdict word — `verified`, `confirmed`, `correct`, `matches`, `ready`, `complete`, `safe` — the response must carry either (a) an enumerated table with file:line / SHA / tool-exit-code citations, (b) a recomputed value with the recompute command shown, or (c) explicit attribution to the upstream source the claim came from (and naming that source as unverified-by-me if so). Heading existence, tool exit 0, count match, and summary receipt are necessary inputs to a verdict, never the verdict itself.

**Verify-in-turn-or-omit (universal):** Every factual claim, parallel observation, scope-extension note, "while we're here" remark, and "same pattern applies" comment carries the same evidence bar as the primary finding. If the claim can be verified in-turn (Read, count, recompute) → do it before posting. If it can't → omit. "Haven't verified" / "haven't checked" / "separate verification needed" / "out of scope of this turn" caveats are themselves the violation — they narrate the gap instead of closing it, and they put the burden of catch on the operator. Future-tense verification ("would need to check") = current-turn omission obligation.

**Honest limit of mechanical enforcement:** Pre-commit / commit-msg checkers can catch surface patterns (e.g., "verified" without evidence cite, "guarantees" without a cited mechanism). They **cannot** catch omission, framing, soft-selling, or false reassurance on natural language. The primary enforcement is **operator-as-catch-net + agent discipline**. The rule binds regardless of how partial mechanical coverage is. Adding a regex check does not discharge the obligation.

### No assumptions — verify, never assume `[PROMOTED]` (2026-06-06 — operator binding; HARD-ENFORCED at turn-end)

Asserting an assumption is the same violation as asserting an unverified claim — it is stating something is so without doing the work to know. **Every claim is either verified in-turn (Read / command output / cited `file:line` / recomputed value) or omitted. There is no assumed middle, and no hedged substitute for verification.**

Unlike the rest of §Do not lie (operator-catch-net), this one is **mechanically blocked**, in two layers, by `tools/enforce_all_rules.py --stop-hook` (no `[REAL-GATE]` escape — both are in the no-escape set):

- **The word.** Fails the turn on `assum(e|ing|ption…)`, `presum(e|ably…)`, `(i'd|my|i'm) guess` in asserted prose.
- **The action behind the word** (the real target — you can assume in *any* words). Fails the turn on any **verdict** — `verified` / `confirmed` / `passes` / `passed` / `ready to run` / `all green` / `no issues` / `is clean` / `is done` / `is fixed` / `checks out` / `holds up` — asserted with **NO shown command or Read output anywhere in the response**. A claim without its evidence *in the same turn* is the assume-action regardless of wording; the only way to make a verdict is to **show the verification** (a fenced block of the command + its output) or **omit the claim**.

The rule itself may be discussed only inside code fences, `` `inline code` ``, or `>`-quoted lines (the scanner strips those before matching). **Honest limit (stated, not hidden):** this forces the *structure* "claim ⇒ shown evidence"; it cannot read whether I actually verified vs. pasted a plausible block. The true enforcement of the action stays what's worked all along — **external gates that fail on the concrete artifact, and the operator** — never my prose.

**Lock:** `_BANNED_OUTPUT` `no-assume-verify` entries in `tools/enforce_all_rules.py` + paired test `tests/test_check_fix_everything_we_touch.py::test_stop_hook_blocks_assumption_vocabulary`.

**Partial mechanical enforcement:** `tools/check_fix_everything_we_touch.py` — commit-msg patterns for `verified` / `confirmed` / `guarantee(s)` / `all clear` without an evidence cite on the same line (`tests/…`, `@` SHA, or `:line`). Paired test: `tests/test_check_fix_everything_we_touch.py`.

This rule sits above §Fix everything we touch because lying makes every other rule unreliable: a fix claimed but not made, a test claimed but not added, a deletion claimed but not executed — all of those are application failures of this one rule.

---

## Fix everything we touch `[PROMOTED]` (2026-05-24 — top rule)

**Every Read is a write obligation.** Open a file, cone, or walk for audit, review, investigation, or disposition → **fix every FIND there before sign-off or commit**. Same turn. Same commit bundle (code + test + governance touch per [§Closure definition + no-deferral](#closure-definition--no-deferral)).

| In scope | Out of scope (only with evidence) |
|----------|-----------------------------------|
| Wrong leaf, non-canonical key, silent default, stale comment, adjacent defect in producer-consumer cone | Site already canonical with file:line proof |
| Memo says `code edit` / audit catch with remediation | `NOT_MARKET_DATA` @ wire layer with upstream trace |
| Test gap for behavior you changed | `[REAL-GATE: …]` in `OPEN_ITEMS` only |

**Banned modes:** read-only investigation, memo-only when a fix is known, reporting FINDs without landing fix+test, "pending gatekeeper" as fix parking.

**Mechanical enforcement:** `tools/check_fix_everything_we_touch.py` (pre-commit + `tests/test_check_fix_everything_we_touch.py`).

---

## Code-first / no governance-only turn `[PROMOTED]` (2026-05-25 — operator escalation)

**Every turn must land application code + paired tests** unless the operator explicitly assigns a governance-only lane (e.g. `go SCHWAB FULL REPO — governance PR only`, register regen in operator PowerShell lane with no agent code scope).

| Required in the turn | Banned as the sole deliverable |
|----------------------|--------------------------------|
| Producer / consumer / money-path fix (`server.py`, `signals.py`, `call_engine.py`, `market_state.py`, `static/index.html`, fusion stack, order flow, etc.) | Register regen, scanner cardinality tuning, CI workflow pin, meta/scoreboard repin, OPEN_ITEMS or ACTIVE_PROGRAM text-only |
| Paired test in an **existing** test file for the behavior changed | Scanner-only `pattern_kind`, memo-only disposition, inventory/report without wire or UI fix |

**Schwab scanner / register work** is admissible only **paired** with a code fix in the **same commit** or the immediately adjacent commit in the **same session** (same FIND family — producer or consumer cone). A scanner gap on code that already reads the correct Schwab leaf is **bookkeeping**, not a product bug; it must not block or replace app-quality fixes.

**Program anchor:** [`ACTIVE_PROGRAM.md`](ACTIVE_PROGRAM.md) §Active program (code-first posture).

**Partial mechanical enforcement:** `tests/test_governance_consolidation.py::test_agents_code_first_no_governance_only_section` — AGENTS body must carry this section.

---

## Action-not-documentation `[PROMOTED]` (2026-05-25 — operator escalation)

**No documentation without code-fix scope.** Every plan, phase, memo, audit, OPEN_ITEMS row, or process artifact must carry CODE-FIX scope — paired commit SHA, paired test ID, OR named code target (`file:line`) for the next action. Artifacts exist to drive code change; they are not the deliverable, the code they cite is. Pure description without action is the violation.

| Required content (per artifact section) | Banned as sole content |
|-----------------------------------------|------------------------|
| Per FIND / issue: paired-fix SHA, paired test, OR `[REAL-GATE: <tag>]` per [§Closure definition + no-deferral](#closure-definition--no-deferral) | Audits / memos / phase docs that list FINDs without per-FIND remediation cite |
| Per phase in a phase plan: code commit SHA when closed; named `file:line` code target when open | Phase plans with goal/scope but zero code-target lines |
| OPEN_ITEMS new rows: `**Fix direction:**` AND named target file:line | Rows that describe risk without naming the consumer-side or producer-side code that needs editing |
| Memos: code-fix scope same commit ([§Fix everything we touch](#fix-everything-we-touch)) | Doc-only memo handoffs — re-affirmed |

**This rule is the artifact-content corollary of §Code-first.** §Code-first bans governance-only turns at the commit level. This rule bans governance-only *content* inside artifacts: a phase doc that lists six phases without code-fix scope per phase, an audit that flags ten FINDs without per-FIND remediation cite, a memo that documents state without naming the code change — all violations even if shipped alongside other code.

**Operator intent (2026-05-25):** "ALL PLANS, ALL PHASES, MEMOS, AUDITS, ETC. MUST CONTAIN ACTION TO FIX ISSUES. THEY CAN NEVER BE JUST DOCUMENTATION. WE MUST PRODUCE CODE THAT CONTINUES TO MOVE THE APP FORWARD."

**Honest limit:** Rule files (`AGENTS.md`, `CLAUDE.md`, `MEMORY.md`), sign-off pins (`governance/artifacts/*.json`), and operator-assigned governance-only lanes are not in scope. The §Code-first existing carve-outs apply identically here.

**Mechanical enforcement (partial):** `tools/check_fix_everything_we_touch.py` — staged commits where only governance artifacts (`governance/audits/**`, `governance/SCHWAB_V4_REVIEW_MEMOS/**`, `governance/PHASE_PLAN_*.md`) change and those artifacts contain action language (`FIND-`, `fix direction`, `Risk:`, `Remaining:`, `Open:`, `TODO`) WITHOUT paired code change (`.py` / `.html` / `.js` / `.css`) fail at pre-commit. Paired test: `tests/test_check_fix_everything_we_touch.py`.

---

## Storage-needs-consumer `[PROMOTED]` (2026-05-25 — operator escalation)

**No writer without a consumer.** Every new persistence path (new DB table + writer, new file writer, new emit-to-API path) must land in the same commit with BOTH:

1. **At least one production caller** that invokes the writer from a live code path (not just tests, not just a helper definition).
2. **At least one consumer** — reader API used somewhere visible, scheduled-audit script that reads the rows, operator-visible surface (UI element, log summary, alert), or pytest assertion that exercises consumed-row content.

**Why this rule exists (empirical 2026-05-25/26):** the production DB had 4 tables (`level_crosses`, `confluence_log`, `model_accuracy`, `session_log`) plus `news_events` with full schemas and writer methods but ZERO production callers (one had a guarded call site with no downstream reader). They were scaffolded — closure-rule artifacts (code + tests) could have been ticked — but never wired to a live path. Result: real engineering time spent on storage that delivered zero operator value. The `calibration_decision_log` env-gate gap also went 24 days undetected because no consumer surfaced the rate — Pass 3 added `/api/ops/calibration_rowcount` + Calibration health card on `static/ops.html` (rate-vs-expected-WARN). Pass 4 wired `level_crosses`; Pass 5a/5b wired `model_accuracy`; Passes 6 / 7 / 8 dropped `session_log` / `confluence_log` / `news_events` (no defensible consumer). One remaining dormant writer (`logging_universe_import_legacy_json_tickers`) is a legacy importer — REAL-GATE-tracked.

| Required in the same commit as a new writer | Banned as the sole deliverable |
|---------------------------------------------|--------------------------------|
| Live producer call from `server.py` / `market_state` / `signals` / scheduler / equivalent | New `INSERT INTO` helper with only test callers |
| Consumer: reader function used by UI/API/log/alert, OR scheduled audit script, OR test that asserts on row content meaningful to operator | Writer-only ship; "consumer in next slice" |
| Throttle / debounce / state-management design for tick-rate writers | Per-tick INSERT without rate limit |

**This is the artifact-content corollary of §Action-not-documentation extended to PERSISTENCE.** A new writer that nobody calls is doc-only code: it documents intent (a table can exist) without producing operator value (no rows, no reads, no surface).

**Operator intent (2026-05-25):** "WE BETTER NOT HAVE GOVERNANCE, OR RULES, ETC WITH NO PATH TO CODE CHANGES UPDATE… WHATEVER NEEDS TO BE DONE PERIOD."

**Honest limit:** Refactors that move an existing writer (no new persistence path), schema-only migrations preparing for a future slice tagged `[REAL-GATE: <tag>]`, and writer additions inside an already-consumed table family (where the consumer already exists upstream) are not in scope. The rule narrows to NEW persistence paths.

**Mechanical enforcement:** `tools/check_fix_everything_we_touch.py` — staged `db.py` (or other persistence-layer module) adding new `INSERT INTO <table>` statements without a paired non-`db.py` non-`tests/` `.py` file in the same commit fails at pre-commit. Paired test: `tests/test_check_fix_everything_we_touch.py`.

**Source-of-truth artifact:** `governance/artifacts/persistence_consumer_map.json`, generated by `tools/audit_persistence_consumers.py` (AST-walks `db.py` + `calibration/writer.py`; one row per writer with `tables_written`, `production_callers`, `read_consumers`, `status`). The map is the authoritative ledger of which writers have callers and which tables have readers. Any commit that edits `db.py`, `calibration/writer.py`, or the audit tool itself must re-stage the map in the same commit; pre-commit blocks via `check_persistence_map_fresh`. Paired test: `tests/test_audit_persistence_consumers.py`.

**Honest limit on the mechanical lock:** the pre-commit gate is `caller + (reader symbol OR tracked REAL-GATE row)`, not full semantic consumer proof. A logger that writes a row and an endpoint that returns the row both satisfy the lock; whether the row is *meaningfully consumed by an operator-visible decision* is product judgment that the lock cannot enforce.

---

## Self-governance quality loop `[PROMOTED]` (2026-05-24)

When operator or peer catches a **missed fix** (FIND surfaced, fix not landed same turn/commit):

1. **Land the fix** immediately — code + test + governance touch.
2. **Record** `PROC-MISSED-FIX-<topic>` row in `OPEN_ITEMS.md` (file:line, what was skipped, who caught it).
3. **Promote prevention** in the **same commit bundle**:
   - Rule gap → amend this file (`AGENTS.md`), OR
   - Repeatable failure mode → extend `tools/check_*.py` + paired pytest so CI/pre-commit blocks the exact miss.
4. **Close** the row `[x] @ <SHA>` only after the checker lock lands.

**Gatekeeper CSV cross-check (V4 memos):** Before sign-off on any new/updated `governance/SCHWAB_V4_REVIEW_MEMOS/*.py.md`, Cursor (and Claude on verify) must run `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck <target.py>` — full AST string/`.get()` token pass against the **entire** `schwab_field_dictionary.csv`, not a hand-picked bid/ask list. Record results in memo section `## Gatekeeper CSV cross-check` with `**lexical_csv_collision_count:** N` and per-collision disposition (homonym vs wire read). Pre-commit enforces via `check_fix_everything_we_touch` + `check_schwab_csv_first.check_v4_memo_gatekeeper_csv`.

**Incident template (OPEN_ITEMS):** `- [ ] PROC-MISSED-FIX-<topic> — <file:line> <what>; caught <how>; prevention: <checker or AGENTS §>`.

Neither agent waits for permission to run this loop when a miss is recognized.

---

## File delete gatekeeper `[PROMOTED]` (2026-05-25)

<a id="file-delete-gatekeeper"></a>

**The agent is gatekeeper and own catch-net** — block bad deletes before they reach the operator; do not rely on the operator to catch a missed enumeration. Enumeration first, verdict second.

Before any delete, archive verdict, or **"safe to delete"** / **"zero references"** claim:

1. **Glob** the basename across the repo (paths only).
2. **Read** every hit — full file when small; at minimum the registry/allowlist block that names the path.
3. **Publish an in-chat referrer table:** `path | role | classification` where classification is `runtime import/exec`, `tooling allowlist/registry`, or `historical dead pointer`.
4. **Verdict only after the table is complete** — per-item enumeration before any positive batch delete claim.
5. **Delete = multi-file cone closure** in one commit: removed file + every tooling allowlist/registry that names it. Historical audit JSON and archived memory are exempt (dead pointers only).

**Banned without referrer table:** "zero references outside itself", "orphan/self-referential only", "safe single-slice delete", "safe-delete count: N" (N > 0).

**Subagent/explore summaries are leads, not verdicts** — re-Read or independently enumerate before sign-off.

---

## Banned tools `[PROMOTED]` (memory `feedback_no_grep_tool.md`, 2026-05-22)

**Absolute ban — no exceptions.** Do not use pattern-matching search that returns matched **lines** instead of full file content:

- `Grep` / ripgrep tool, `grep`, `rg`, `egrep`, `fgrep`, `ripgrep`
- Shell pipes: `cat foo | grep bar`, `awk '/pattern/'`, `sed -n '/pattern/p'`, `find ... | grep ...`

**Allowed:** `Read` end-to-end (use `offset`+`limit` for large files); `Glob` / `find -name` for **paths only**.

**Self-check before Bash:** does the command return matched lines inside files? If yes, use Read instead.

### Audit method — AST scan MANDATORY (2026-06-05 — operator binding)

**Every code audit MUST include an AST scan — regex/grep-style scanning and eyeballing are NOT sufficient and are rejection-grade as the *sole* method for an audit.** Regex misses multi-line constructs and two-step bindings (`r = fn(); a, b, c = r`); reading misses call sites you didn't open. For any signature/arity/return change, run `python tools/enforce_all_rules.py --ast-callsites <FUNC>` to enumerate every call site with its exact binding (tuple-unpack arity / single-name / arg-use) before signing off. For other structural invariants, write the equivalent `ast`-based check. An audit verdict ("clean", "no callers break", "MET") asserted without an AST scan of the touched surface is **not** a valid audit. Lazy = regex-only; rigorous = AST-exhaustive. Mechanical helper: `enforce_all_rules.py::_ast_callsites`.

**Drift-audit protocol MANDATORY before ANY sign-off (2026-06-05 — operator binding).** Before claiming any audit / stage-acceptance / "MET / clean / verified / 100%" — especially when auditing Cursor's work — run the **`drift-audit`** skill (`.claude/skills/drift-audit/SKILL.md`): intent & drift check vs the written plan → mandatory AST scan + run gates/tests yourself → the known failure-class checklist (arity, **presence-vs-capability**, silent-swallow, caller-compat, fail-closed, test-actually-exercises, stale-vs-live, **gate-weaker-than-principle**) → completeness critic ("what class did I not check? is the gate smaller than the goal?") → verdict with cited evidence → self-correct loop (Cursor directive + new self-rule + **mechanize the check**). A sign-off without the protocol is rejection-grade. New failure classes get appended to the protocol so it compounds.

---

## No permission asks `[PROMOTED]` (memory `feedback_no_permission_asks.md`, 2026-05-22)

Operator has standing full repo access. Do not ask for read-only research.

**Banned output patterns:** "Want me to…?", "Should I…?", "Your call.", "Say the word…", "If you want, I can…", end-of-turn next-step menus, "Standing by for direction."

**Deliver a decision and act** on named follow-ons in the same turn when possible. Reserve confirmation for high-blast-radius writes not pre-authorized.

**No announce-and-stop (2026-06-05, binding):** naming a next action you can do NOW ("next I'll build X", "let me wire Y next") and then ending the turn is a banned punt — do it in the SAME turn. Only stop after naming a next step when it is genuinely operator-owned (>10min host run in their PowerShell), Cursor-owned (push/PR), or blocked by a real `[REAL-GATE]`, and say so explicitly rather than as a self-promise. Mechanically locked: `tools/enforce_all_rules.py` `_BANNED_CLOSERS` (Stop hook blocks self-promise closers).

**Push / PR creation:** Cursor lane unless operator explicitly assigns to Claude.

---

## Active agent posture + mutual gatekeeping `[PROMOTED]` (2026-05-24)

<a id="active-agent-posture"></a>

**Neither Cursor nor Claude is a passive relay.** Both have standing authority to keep the repo correct, efficient, and clean — not only when asked.

### Active duties (both agents)

| Duty | Requirement |
|------|-------------|
| **Surface FINDs** | Any defect, drift, or adjacent issue discovered during a Read → name it immediately (file:line). Do not wait for operator to ask. |
| **Fix in cone** | When the fix is known and scope is the same file/producer-consumer cone → land **code + test + governance touch** same commit per [§Closure definition + no-deferral](#closure-definition--no-deferral). |
| **Reject bad handoffs** | Operator or peer handoff that would commit audit debt (memo-only when memo marks `code edit`, REPLACED-via-removal, or open FIND) → **refuse and correct in-turn**, then report what was wrong. |
| **Independent verification** | Re-Read at tip before sign-off or commit; never trust the other agent's summary alone. `[PROMOTED]` AGENT_SELF_GOVERNANCE #22 |
| **Retract** | If re-verification surfaces gaps after accept → retract sign-off and fix. `[PROMOTED]` #23 |

### Mutual gatekeeping (peer roles)

| Direction | Gatekeeper duty |
|-----------|-----------------|
| **Claude → Cursor** | Claude verifies dispositions, O-XX narratives, register/perf-proof bundles, and Schwab evidence bar before merge/sign-off. |
| **Cursor → Claude** | Cursor re-Reads Claude handoffs and diffs at tip; blocks relay-only commits that skip required fixes, tests, or sibling-pattern conformance. **Runs full CSV gatekeeper cross-check** (`check_schwab_csv_first --gatekeeper-crosscheck`) before V4 memo sign-off — never a hand-picked field list. |
| **Either → Operator** | Either agent may escalate a **process violation** (memo-first drift, deferred FIND, handoff/convention mismatch) with file citations — not permission-seeking. |

### Two-way audit — MANDATORY before any stage / gate / MET claim (2026-06-05 — operator binding)

Neither agent signs off from the other's summary. Each deliverable gets **two independent passes** — implementer audit (the coding agent re-Reads the touched cone at tip and runs the **full acceptance command, not a sub-function**) and verifier audit (the other agent / operator **re-runs the same command independently** and challenges gate-conflation, scope-narrowing, and "green sub-function = green gate"). The **mechanical gate's exit code is the arbiter.**

**Required evidence block — both agents, identical shape; the verifier RECOMPUTES, never echoes:**
```
AUDIT: <Cursor|Claude>
SLICE: <name>
ACCEPTANCE GATE: <full command> → exit <code>     ← BINDING
AXIS placement: <fn> → PASS|FAIL + cite
AXIS coverage:  <fn> → PASS|FAIL + cite
TESTS: <command> → <N passed, N skipped>           (re-run, not quoted)
FINDS: <none | table file:line>
VERDICT: MET|NOT MET|EXCEEDED   ← only if gate exit 0 AND all axes PASS
```
**Hard rules (rejection-grade):** a sub-function PASS is **never** the gate PASS — cite the command that failed, not a parent name; **placement MET ≠ stage MET while the coverage axis is RED**; the verifier rejects any sign-off whose evidence is missing, echoed, or uses a sub-function as the gate; either side **retracts a prior MET** if re-audit fails. No MET until **both** audits agree **and** the acceptance gate is exit 0. (Verifier-side discipline = the `drift-audit` skill.)

**Gatekeeper pending ≠ fix parking.** Memo status `pending gatekeeper` applies to **disposition sign-off**, not to deferring a **known, in-scope code fix** surfaced in the same Read. The only admissible split is [REAL-GATE](#closure-definition--no-deferral) with tag in `OPEN_ITEMS`.

### V4 walk / review-memo rule

When a review memo (e.g. `governance/SCHWAB_V4_REVIEW_MEMOS/*.md`) records:

- `code edit: proposed` / **REPLACED via removal** / **REPLACED** with a named code change, or  
- an **audit catch** with recommended remediation in the **same file**,

then the **same commit** that adds or updates the memo must include that code change + paired test (unless a REAL-GATE tag applies). **Memo-only commits that document fixable code debt are rejection-grade.**

Schwab register-row / perf-proof / O-XX authorization slices still follow `governance/CURSOR_V4_AGENT_BRIEF.md` — but that brief is subordinate to this section for fix-as-we-find conflicts.

### Handoff rejection checklist (executing agent)

**Operator relay handoffs** (paste from Claude or operator) are **instructions, not immunity**. Before `git commit` on a relayed handoff, confirm:

1. No open `code edit` / REPLACED-removal in the memo without matching diff in the commit.
2. Closure artifacts present when the slice closes an OPEN_ITEMS row or FIND.
3. Sibling-pattern conformance for convention-driven directories.
4. Pre-commit / targeted pytest run when Python changed.
5. **Gatekeeper CSV cross-check** on staged V4 memos: `## Gatekeeper CSV cross-check` section + `lexical_csv_collision_count` matches `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck <target.py>`.

If any check fails → fix first, then commit once.

---

## Banned phrases `[PROMOTED]`

Rejection-grade in commit messages, code comments, tests, chat, and OPEN_ITEMS row text (unless the row carries `[REAL-GATE: …]`):

**Scope-narrowing (full repo):**
- "scope of current section" / "for this section only"
- "scanner capability" / "the scanner doesn't walk that"
- "in scope of the file I'm editing" / "collateral only" / "not in the ticket" / "out of scope of this PR"
- "ms_dict is the source" / "the API provides it" (without leaf trace)
- "based on the files I've reviewed" / "Mega N is done" / "the section is closed"
- "fail-closed in [specific place]" as substitute for canopy→leaf trace
- "closure per D17" while `partial_scan` is true or PR 2 gate not live
- Any phrase whose effect narrows scope to less than the full repo

**Deferral / parking (see [§Closure definition + no-deferral](#closure-definition--no-deferral) for REAL-GATE exceptions only):**
- "deferred" / "deferring" used to schedule work to a later commit (unquoted scheduling sense)
- "TBD:" / "still pending" / "currently pending" (scheduling sense)
- "follow-up commit" / "follow-up slice" / "next slice will" / "next commit will"
- "Phase N paired-fix pending" / "implementation pending" / "consumer pending" / "behavioral spec pending"
- "will land later" / "can land later" / "Playwright deferred until CI"
- "broader sweep deferred" / "deferred FINDs" (use **disclosed FINDs** + REAL-GATE tag or close in-turn)
- End-of-turn menus: "Want me to…?", "Should I…?", "Your call.", "Say the word…", "go X if you want"

**Excuse / partial-completion (operator 2026-05-27 — zero drift):**
- "by design" / "works as designed" / "works as intended" / "policy by design"
- "patch only" / "minimal patch" / "small patch" (as a completion excuse — not describing a diff shape in governance meta)
- "mostly complete" / "substantially complete" / "good enough for now"
- "not in scope" / "out of scope" (without `[REAL-GATE: …]` row)
- "intentional asymmetry" (without governed O-NN / operator narrative)
- "rules are guidance" / "operator will catch" / "acceptable drift"
- "partial fix" / "partial enforcement" (as reason to stop — extend the checker instead)

Schwab-only phrases remain in `CLAUDE.md` FORBIDDEN PHRASES.

---

## Banned patterns `[CONSOLIDATED]`

- **Auto-promote without governed executor:** never write `models/active*` except via `arch_competition.promotion_execution.execute_promotion_if_eligible` (or documented manual CLI wrapping it). `[PROMOTED]` training pipeline PR4.
- **End-of-turn menus:** see No permission asks. `[PROMOTED]`
- **New files of any kind:** see [§No new files when an existing one will do](#no-new-files). Applies to md / test / script / memory / governance doc.
- **Passive relay:** executing operator/peer handoffs without AGENTS compliance check; committing memos that document in-file code fixes without landing the fix. See [§Active agent posture + mutual gatekeeping](#active-agent-posture). `[PROMOTED]` 2026-05-24

---

## Closure definition + no-deferral `[PROMOTED]` (2026-05-24 binding — operator escalation)

**Closure of any slice means ALL of the following land in the same commit:**

1. **Code** — the fix itself.
2. **Tests** — paired test(s) that lock the behavior, in an existing test file when one owns the topic (extend, don't create — see [§No new files when an existing one will do](#no-new-files)).
3. **Mega inventory** — when the refactor adds/renames/deletes a registered Python function/class: `governance/megaN_traceable_inventory.py` row + `tests/test_megaN_traceable_audit.py` row-count update in the same commit.
4. **Map row** — when the slice touches a registered surface: `governance/STACK_WIRING_INTEGRITY_MAP.md` row updated to "producer + consumer landed" (not "inventory only", not "pending").
5. **OPEN_ITEMS** — `[x] @ <SHA>` for every row the slice closes, with test cite in the row text when applicable.

**ML scheduler train-success-live (operator 2026-05-27):** For tickers that complete train + governed eval without `failed_closed`, closure requires `models/active/{TICKER}/` refreshed in the **same scheduler run** via `execute_promotion_if_eligible` (default ON). Outcome `promote_ok` or `trained` without `promoted: true` in the training report is **not closed** for that ticker. Panic-only opt-out: `ED_DISABLE_AUTO_PROMOTE=1` or `ED_SCHEDULER_AUTO_PROMOTE=0`.

If any of the 5 cannot land same-commit, the slice is **not closed**. There is no "phase 2 paired-fix pending", "behavioral spec deferred until CI", "broader sweep deferred behind a brief", or "follow-up commit lands the e2e" variant. Those are the violation.

**REAL-GATE taxonomy** — the ONLY acceptable deferrals. Each must be tagged `[REAL-GATE: <reason>]` in the OPEN_ITEMS row:

| Tag | Meaning |
|-----|---------|
| `telemetry` | Needs production observation before the fix can be designed (e.g., uniform-triplet tiebreak prevalence). |
| `training-skew` | Changing breaks trained model inputs without retrain. |
| `unwalked-file` | The consumer/caller hasn't been Read yet AND won't be in this commit's scope. |
| `accepted-as-designed` | Documented contract; the disclosure IS the right behavior. |
| `host-only` | E2E / preflip / migration requires operator host time. Applies ONLY to execution, NOT to writing the spec / harness. |

Any deferral without one of these tags is rejection-grade.

**Mechanical enforcement:** `tools/check_no_deferral_language.py` (pre-commit + pytest via `tests/test_check_no_deferral_language.py`). The phrase list is normative in the tool's `DEFERRAL_PATTERNS` — don't duplicate it here. Allowlisted surfaces (legitimate future-work tracking, NOT deferral): `OPEN_ITEMS.md`, `ACTIVE_PROGRAM.md`, `MEMORY.md`, `governance/**`, `tests/**`, the tool itself, and the `[REAL-GATE: <tag>]` line shape.

---

## No carried residuals — done means zero residuals `[PROMOTED]` (2026-05-31 — operator binding; sharpens §Closure + §Meet-or-Exceed)

<a id="no-carried-residuals"></a>

**Scope — universal (full repo, every subsystem and extension).** This binds the *entire* codebase — ML, UI, money-path, Schwab/market-field, governance, tooling, tests, static, docs — not only the ML pipeline that surfaced it. Same reach as [§Meet-or-Exceed Closure Cycle](#meet-or-exceed-closure-cycle): one standard, full repo, no per-area carve-out.

**A disclosed residual is NOT a closed residual.** When work on a subsystem is called complete, "complete" means **zero open residuals in that subsystem** — not "complete with a tracked residual," not "complete (NOT closed)," not "complete with a known limitation." Calling something done while a fixable defect in the same cone is knowingly carried forward is **rejection-grade**, and the honest answer to the operator's *"is this clean / fixed?"* is **NO** while any such residual exists — no asterisk, no soft-sell ([§Do not lie to the operator](#do-not-lie-to-the-operator-promoted-2026-05-24--binding-hard-rule-no-exceptions)).

**The only two admissible end-states for any FIND in the touched cone:**
1. **Closed** — fix + paired test landed in the same work ([§Closure definition](#closure-definition--no-deferral)), OR
2. **`[REAL-GATE: <tag>]`** — explicitly tagged in `OPEN_ITEMS` with one taxonomy tag (real future work that *cannot* land now). It is tracked work, not "done."

There is no third state. "Disclosed residual / tracked residual / bounded-design residual / known limitation / NOT closed by this commit" used to ship something **as complete without** a `[REAL-GATE: <tag>]` is the violation — **in any file, any subsystem.** The B-series leakage + fusion residuals (shipped as "complete (NOT closed)") are the *originating* incident (ML); the rule applies repo-wide.

**Operator intent (2026-05-31):** "when we fix … the answer to whether something is clean should always be an honest yes without omitting anything … everything needs to be fixed and we fix along the way."

**Mechanical lock (landed with this rule):** `tools/check_no_deferral_language.py` flags commit messages / staged non-allowlisted source using a residual-completion-qualifier — `tracked` / `disclosed` / `bounded-design residual`, or `residual … NOT closed` — without an adjacent `[REAL-GATE: <tag>]`. Bare `residual` (ML "residual connection/block/error") is intentionally NOT caught. Allowlisted surfaces (legitimate future-work tracking): `OPEN_ITEMS.md` / `ACTIVE_PROGRAM.md` / `MEMORY.md` / `AGENTS.md` / `CLAUDE.md` / `governance/**` / `tests/**`. Paired test: `tests/test_check_no_deferral_language.py`. **Honest limit:** surface-pattern catch only — omission / soft-framing of a residual in prose is operator-catch-net + agent discipline ([§Do not lie to the operator](#do-not-lie-to-the-operator-promoted-2026-05-24--binding-hard-rule-no-exceptions)).

---

<a id="ablation-contract-o56"></a>

## Ablation contract — feature→model→horizon `[PROMOTED]` (2026-06-03 — operator binding, O-56)

**Unit of decision:** the cell is **`(feature × model × horizon)`** — each atomic feature evaluated in **each of the seven stack models** at **each of the four horizons**, to find where that feature fits. A feature may survive for `xgb`-`1c` and die for `xgb`-`60c`, survive for `lstm`-`1c` and die for `meta`-`1c` — that is the data talking, per cell. Survivors resolve **per (model, horizon)** — `survivor_summary.by_model_horizon[model][horizon]`. All seven models (`xgb`, `lstm`, `transformer`, `meta`, `monte_carlo`, `regime`, `fusion`) are **grid axes — none omitted.**

**Agent lens (binding — 2026-06-05 escalation):** build toward the **zero-bias target**, not toward preserving what any file currently does. "The manifest says grouped" / "FEATURES_5M is hand-curated today" is **not** authorization to keep bias. If code or artifacts pre-decide placement, they are **FINDs to remove**, not the spec.

The feature ablation is **per-feature × per-model × per-horizon** — every atomic feature evaluated in **all seven stack models** at **all four horizons** (compound / bundled groups are **VOID**). Binding (register **O-56**):

- Grid is **`feature × model × horizon`** (one atomic feature per unit). **Model** = all seven stack layers (`xgb`, `lstm`, `transformer`, `meta`, `monte_carlo`, `regime`, `fusion`); **horizon** = all four (`1c`, `5c`, `15c`, `60c`). **Tickers are pooled** (SPY+QQQ+IWM) — **not** a grid axis. For each cell the feature is permuted/knocked out and its effect at that `(model, horizon)` is recorded (`log_loss_delta` + derived layer audit). Expected size: **94 captured features × 7 models × 4 horizons = 2,632 cells.**
- Survivors resolve **per (model, horizon)** only — which features survive for each model at each horizon. **No** single global survivor list across models or horizons; **no** per-ticker list (pooled). There is **no fabricated default drop set** (`DEFAULT_ABLATION_DROP_GROUP_IDS` removed 2026-06-03). The **only** admissible placement router is the per-`(model, horizon)` survivor matrix applied at each model's feature assembly.
- **TRAINING CONSUMES THE SURVIVORS — full-feature training is NOT a valid retrain target.** When a complete ablation matrix exists, full-feature training is **never** an acceptable default, fallback, or *offered option*. If survivors cannot be applied → **fail loud and stop — do not train.**
- Legacy holdout MCC for xgb/lstm/transformer only (`--ablation-include-o56`) and stack-authority mode-lifts are **diagnostic partial axes** — they may **never** replace or collapse the full **`feature × 7 models × 4 horizons`** placement grid.
- **Consumption check — `cf_*` knockout must actually perturb the model:** the 6 `cf_*` confluence features (`lstm_data.CONFLUENCE_FEATURES`) are NOT snapshot columns; for the lstm cells they must be knocked out by **zeroing the X_conf channel** (`zero_ablated_lstm_conf_channels` / `_zero_conf_channels`), not by permuting a non-existent snapshot column. A `cf_*` cell whose knockout leaves X_conf unchanged is a **no-op → fail** (never mistake "not perturbed" for "doesn't matter").
- **Mechanical lock:** `check_ablation_seven_model_four_horizon_grid()` (rejects partial grids — base-3-only, missing models or horizons) + `tests/test_check_fix_everything_we_touch.py::test_ablation_grid_requires_all_seven_models_and_four_horizons` + `check_full_stack_ablation_coverage()` + `check_ablated_training_only()` + `check_zero_bias_ablation_contract()`. Binds Cursor **and** Claude.

### ZERO-BIAS — data-driven, no pre-decision anywhere `[PROMOTED]` (2026-06-05 — operator binding, ALL-CAPS escalation; cannot be violated)

**This is a data-driven app. PERIOD.** Nothing in any file, code, JSON, spreadsheet, or artifact may pre-decide what features matter, where they go, or how they group. **Only** the ablation survivor output — per **`(model × horizon)`** cell — decides placement. Repo-wide bias sweep: same standard as [§Meet-or-Exceed Closure Cycle](#meet-or-exceed-closure-cycle) — **anywhere in the repo**, not just the manifest.

**Banned agent vocabulary (rejection-grade in chat, commits, plans):** describing ablation or survivors as **"per model"** without naming horizons; framing work as **"preserve current behavior"** / **"match the file"** when the file embeds bias; treating any pre-routing as **"by design"** without a governed O-NN.

Every item below is **BIAS** — rejection-grade wherever it appears:

| Bias source | Target disposition |
|-------------|-------------------|
| **`members` as assignment** | **Gone.** Every feature available to every model × horizon. `members` may encode ingest-capability only — **never routing** (empty lists for "wrong" models forbidden). |
| **Bundled / grouped features** | **Gone.** Ablation unit = **one atomic feature** (one Schwab leaf / one column). Compound survivors VOID. |
| **Confluence / composite pre-blends** (`cf_*`, `*_score`, alignment composites) | Not pre-dropped **or** pre-kept — in the ablation universe; data decides. |
| **Curated sequence channels** (`FEATURES_5M` / `FEATURES_1M` hand-lists) | Expand so sequence models can ingest the full universe — not a curated subset. |
| **Candidate-discovery pinned to XGB** | **Gone.** Discovery candidates available to **all** base models. |
| **Fabricated / neutral defaults** (0.5, 0.33, 0.333, "neutral", "flat") | Honest nulls + consumption checks — never fills that prejudice a read. |
| **Hardcoded thresholds/weights that prejudge** (e.g. imbalance 0.65/0.35 cutoffs, MC fusion weight pinned to 0, fixed fusion weights) | Data-driven or operator-surfaced — never silently baked. |
| **Stale persisted snapshots** that freeze old assignments | Derive the feature universe **live each run** — do not trust drifted pre-built assignments. |
| **Pre-set horizon dispositions** | Every feature **`TEST`** at every horizon until ablation evidence drops it. |
| **Excluding any of the 7 stack layers from per-feature evaluation** (treating `meta` / `monte_carlo` / `regime` / `fusion` as "no feature-members" or a "separate axis"; or describing the stack as "3 feature-models + 4 others") | **Gone — this is itself a pre-decision.** Every feature's effect is measured through the **FULL seven-layer stack** (the whole-stack fusion path → final fused prediction) at every horizon. Whether a feature matters to a layer is for **ablation to decide, not the agent.** "That layer doesn't consume raw features" is a bias, not a reason to skip it. |

**Acceptance test (every change, every agent turn):** every **`(feature × FULL 7-layer stack × horizon)`** effect is measured **through the final fused prediction** (per-feature whole-stack fusion — `_full_fusion_prob_for_row`), for **all** of `(xgb, lstm, transformer, meta, monte_carlo, regime, fusion)` at **all** of `(1c, 5c, 15c, 60c)`; the survivor output is the **ONLY** place placement is ever decided; no line anywhere pre-judges what ablation may find. Per-base-model MCC permute and mode-lift scoring are **partial axes — neither closes the gate.** Mechanical arbiter: `python tools/enforce_all_rules.py --ablation-bias` (placement **and** full-stack-coverage axes; exit 0 only when both pass). If anything pre-excludes a layer → **bias → remove in the same cone**.

**Mechanical lock:** `check_zero_bias_ablation_contract()` in `check_fix_everything_we_touch.py` (manifest + live-cone bias detector: per-model routing in `members`, multi-member bundles, grouped `primary_pass`, non-`TEST` horizon dispositions, live inputs absent from universe) + `python tools/enforce_all_rules.py --ablation-bias`. Paired: `tests/test_check_fix_everything_we_touch.py::test_zero_bias_ablation_contract`. **Until the atomic manifest rebuild lands, this check is EXPECTED to fail** — that failure is the gate the rebuild must satisfy; agents still must not add new bias while rebuilding.

---

<a id="no-new-files"></a>

## No new files when an existing one will do `[PROMOTED]` (2026-05-24)

Before creating any new file — md / test / script / memory / governance doc — find the existing file that owns the topic and extend it.

| New thing | Existing owner (default — extend, don't create) |
|-----------|--------------------------------------------------|
| Rule about how to do a fix | This file (AGENTS.md). NOT a new `feedback_*.md` memory. |
| Lock test for a new invariant adjacent to an existing rule's enforcement | The existing paired test (e.g., `tests/test_check_no_deferral_language.py` owns "deferral rule enforcement" including ledger-state locks, not just regex behavior). |
| Decision rationale | Commit message body. NOT a `*_PROPOSAL.md` / `*_PLAN.md`. |
| Architecture amendment | Existing `governance/PHASE_PLAN_*.md` or `INSTITUTIONAL_STANDARD_V3.md` §20. |
| Enforcement script for a new rule | Single `tools/check_*.py`. Don't split. |
| Mega inventory bump | Same commit as the refactor (no separate "mega-sync" commit or file). |

Counter-cases (legitimately new files): genuinely new topic with no owner; new feature's paired test (one feature = one test file is a real convention); fundamentally different tool. If unsure, default to extend.

---

## Posture rules `[CONSOLIDATED]`

- **Fix-as-we-find:** adjacent FINDs in cone → same commit; see [§Closure definition + no-deferral](#closure-definition--no-deferral). The 5-artifact closure list is the authoritative form of "fix-as-we-go". **Memo-only when code edit is known = violation** — see [§Active agent posture + mutual gatekeeping](#active-agent-posture).
- **Scope-explicit completion:** state what was and was NOT verified (by name). `[PROMOTED]` AGENT_SELF_GOVERNANCE #7
- **Full-Read verification:** re-Read at tip; never sign off from another agent's summary alone. `[PROMOTED]` #22
- **Per-item enumeration before positive batch verdict:** enumerate each item before "all pass" / "complete". `[NEW]` Round 3
- **Commit to specifics:** implementing commit is the deliverable, not a proposal doc. `[PROMOTED]` memory `feedback_commit_to_specifics.md`
- **Cleanup-as-we-go:** every turn — dead code touched, stale comments, duplicate rules surfaced. `[NEW]` Phase 4
- **Unprompted surfacing:** if governance MD count grows >10 since last pass or a rule duplicates across ≥3 surfaces, tell operator. `[NEW]` Phase 4
- **Sibling-pattern conformance:** before drafting a per-file artifact in any convention-driven directory (e.g., `governance/SCHWAB_V4_REVIEW_MEMOS/`), Read every existing sibling end-to-end first and cite the closest-shape precedent in the new artifact's header. Catches disposition / schema drift from convention. `[NEW]` 2026-05-24

---

## Money-path module roster `[PROMOTED]` (AGENT_SELF_GOVERNANCE #25)

Every listed file must exist; changes require regression awareness:

- `signals.py`
- `call_engine.py`
- `prediction_engine.py`
- `realized_contract_eval.py`
- `bayesian_fusion.py`
- `mc_fusion_adjustment.py`
- `market_state.py`
- `live_decision_bundle.py`
- `features/signal_layer_v1.py`
- `features/inference_snapshot.py`
- `features/fusion_policy_contract.py`

Authority modules (reference): `time_et.py`, `numeric_contract.py`, `fusion_contract.py`, `replay_hold_bars.py`, `position_sizing_policy.py`.

---

## OPEN_ITEMS rules-of-use `[CONSOLIDATED]`

- Add rows for FINDs before next slice; close only with **commit SHA** in row text.
- `[x]` without SHA is **invalid at any age** — reopen or fix row.
- Checked `[x]` + SHA + age **> 90 days** → archive (path: `governance/archive/<quarter>/open_items_archive/` — named in ACTIVE_PROGRAM when first used).
- Unchecked row age **> 30 days** without owner → escalate to ACTIVE_PROGRAM §Stale Backlog.
- Report session-relevant open count + full unchecked count when working OPEN_ITEMS. `[PROMOTED]` #15

---

## Background / cloud agents `[NEW]`

Same AGENTS.md + ACTIVE_PROGRAM apply; no reduced governance on async runs.

---

## Audit excludes `[NEW]`

Do not count toward repo hygiene sweeps: `**/.claude/worktrees/**`, `governance/archive/**`, `models/active*/**`.

---

## Cursor user rules disposition `[CONSOLIDATED]` (Phase 1a)

| User rule topic | Disposition |
|-----------------|-------------|
| Git commit only when requested | `[PROMOTED]` → AGENTS (operator write authority) |
| PR workflow via `gh` | `[OPERATOR-ONLY]` — Cursor PR lane |
| Follow instructions completely | `[CONSOLIDATED]` → this file |
| Real environment / run commands | `[PROMOTED]` → posture |
| Code principles (minimal scope, conventions) | `[PROMOTED]` → posture |
| Communication / citations | `[PROMOTED]` → posture |

Superseded by `.cursor/rules/00-always.mdc` for always-on read order and conflict resolution.
