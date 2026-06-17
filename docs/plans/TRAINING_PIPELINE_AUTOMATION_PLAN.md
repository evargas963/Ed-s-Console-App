> **Classification:** Policy Specification | **Scope:** Execution plan; binding when ACTIVE_PROGRAM points here.

# Training Pipeline Automation Plan

**Goal:** End-to-end training that runs unattended, promotes winners to production automatically when governance gates pass, and fails loudly when anything is incomplete — for **SPY, QQQ, IWM** first, then the full enrolled universe.

**Audience:** Claude / Cursor implementation agent  
**Branch:** `feature/institutional-key-levels` (or dedicated `feature/training-pipeline-automation`)  
**Status:** **PR1–PR4.1 implemented locally** on `feature/institutional-key-levels` (tip `cd7d615`); PR5–PR7 not started. Not pushed to `origin` (133 commits ahead of `1c0ec96`).  
**Last updated:** 2026-05-21 (implementation status sync)

**Operator sign-off:** Plan sound. **PR4 merge gates satisfied in code** (P3-4b, P3-9, P3-10, preflip §3C hardened in PR4.1). **Do not enable `ED_SCHEDULER_AUTO_PROMOTE=1` on the host** until operator preflip e2e + `live_reload.succeeded: true` on the real console URL (git push ≠ host enable).

---

## 0. Code verification (plan claims)

| Plan claim | Verified (2026-05-21) |
|------------|-------------------------|
| Auto-promote off by default | `arch_competition/scheduler_auto_promote_policy.py` — `ED_SCHEDULER_AUTO_PROMOTE` unset/0 |
| `decide_promotion(..., auto_promote=True)` raises | `arch_competition/promotion_engine.py:106-107` (unchanged) |
| Single governed promotion writer | `arch_competition/promotion_execution.execute_promotion_if_eligible`; `_promote_candidate` **removed** from `ml_scheduler.py` |
| Phasing order | PR1–PR4.1 shipped: measure → fail-closed → layout → automate |
| `pre_train_gate` exists | `ops_runner.py:164` — scheduler wiring still a **PR5+** gap |
| `--all-horizons` shipped | commit `2924017` |
| Definition of done | Each PR row has tests; full suite **2619 passed** at `cd7d615` |

---

## 1. Current state (honest baseline)

| Area | Today | Problem | OPEN_ITEMS / G1 |
|------|--------|---------|-----------------|
| Train | `ml_scheduler.run_once` trains parallel + cascade per ticker/horizon | Works for core tickers | — |
| Evaluate | `arch_competition` writes manifest + promotion record | **G3-R3** lineage horizon mismatch can fail governed pass | `OPEN_ITEMS.md` G3 Reconciliation Queue |
| Promote | `scheduler_auto_promote_to_active_enabled()` always False | Active never updates without manual promote | G4-4 dormant scheduler copy |
| Horizons | `--all-horizons` loops 1c/5c/15c/60c | Promotion still manual per horizon | TRACK 4 (OPEN_ITEMS G4 queue) |
| Verify | `verify_active_models.py` | Use as post-run gate | G3-R1 vs `ml_predict` |
| Layout | Weights in `models/active/{T}/`, meta-only in `models/active_{hz}/{T}/` | Split-brain | G2 plan (paused) |
| Exit code | Scheduler exit 0 with incomplete artifacts | Operator thinks success | **G4-3** `ml_scheduler.py:1701-1707`, `2133-2135` |
| Features | e.g. `qqq_weighted_push` ~65% NULL | Degrades QQQ quality | operator data gate |
| Bypass | Movement-head tools write direct to `active/` | Governance desync | **G4-2** (five tool scripts) |
| Server sync | Request-path active mutation | Outside governance | **G4-1** `server.py:4426-4453` |

**Tracking ID note:** **G3-R1, G3-R2, G3-R3** are **not** plan-internal — they live in `OPEN_ITEMS.md` § G3 Reconciliation Queue (`~410-414`). **G4-1..G4-4** are in `OPEN_ITEMS.md` § G4 queue (`~388-392`). **STACK-WIRE-\*** is a separate stack-integrity workstream (Action 12.7+ closure); do not conflate with training automation except where verify/inference contracts overlap (G3-R1).

**Non-goal:** “100% perfect” ML accuracy. **Goal:** **reliable, automated, auditable** train → evaluate → promote → verify → live.

---

## 2. Target architecture (canopy)

```text
pre_train_gate (DB + readiness + feature NULL budgets)
        ↓
ml_scheduler --all-horizons [--auto-promote when enabled AND NOT panic-disabled]
        ↓
  per (ticker × horizon):
    normalized sync → fingerprint → train parallel/cascade OR hard-skip with reason
    governed eval (manifest + promotion decision)
    IF auto_promote AND gates pass AND NOT ED_DISABLE_AUTO_PROMOTE:
        rollback checkpoint → execute_promotion_if_eligible → active_{hz}/ (canonical layout)
        IF REQUIRE_VERIFY: sync verify (ticker, horizon) → on fail: rollback checkpoint, outcome=verify_failed
        → batch POST reload_models (P3-10) evict in-memory registry per (ticker, horizon)
    ELSE:
        hold production_write_held + reason in training_report.jsonl
        ↓
post_run_verify (verify_active_models + bundle completeness; per-ticker if already done inline)
        ↓
exit code ≠ 0 if ANY enrolled core ticker failed train/eval/promote/verify
        ↓
live: ml_predict strict active only → console stack
```

**Single promotion authority:** `execute_promotion_if_eligible()` in `manual_control.py` (shared by manual CLI and scheduler).

**Operator override:** Manual promote/rollback remains. Auto-promote is opt-in; panic-disable always wins.

---

## 3. Phased delivery

### Phase 0 — Preconditions (1–2 days, no behavior change)

**Objective:** Make measurement trustworthy before flipping automation.

| Task | Files | Acceptance |
|------|-------|------------|
| P0-0 | **Active-directory writer inventory** (grep + reconcile G1) | `governance/ACTIVE_DIRECTORY_WRITER_INVENTORY.md` (code-state audit, not a plan doc) | Every `models/active/` and `models/active_*/` writer listed with reachability; no “unknown” writers before Phase 3. **Pre-flip freeze:** document copy of `models/parallel/{T}/` + `models/cascade/{T}/` → `models/_preflip_{run_id}/{T}/` for harness replay (§3C). |
| P0-1 | Enrolled universe snapshot in run log | `ml_scheduler.py`, `training_report.jsonl` | Category counts (core/pinned/user/panel_auto) per run |
| P0-2 | Tests for `verify_active_models.py` | `tests/` | CI verify on SPY/QQQ/IWM fixtures |
| P0-3 | `training_pipeline_status.json` aggregate | new small module | Last run + per-ticker/horizon status |
| P0-4 | **G3-R3** lineage horizon fix | `arch_competition/lineage.py`, `eval_runner.py`, `ml_scheduler.py` | Governed pass succeeds 1c/5c/15c/60c on SPY dev run |
| P0-5 | **G3-R1** verify vs `ml_predict` completeness | `verify_active_models.py`, `ml_predict.py` | Single “complete bundle” contract |

**P0-0 inventory seed (from `governance/G1_DIAGNOSIS.md` Direct-Active Writer Inventory — re-grep before PR4):**

| # | Writer | File | Governance | Phase action |
|---|--------|------|------------|--------------|
| 1 | Manual promote | `arch_competition/manual_control.py` | YES | Becomes shared executor |
| 2 | Scheduler `_promote_candidate` | `ml_scheduler.py:1783-1804` | NO (dormant) | Delete or hard-disable in PR4 |
| 3 | Server request sync | `server.py:4426-4453` | NO | G4-1: env-gate audit or route through executor |
| 4 | `train_all_movement_heads_v1.py` | `tools/` | NO | G4-2: deprecate or candidate-only output |
| 5 | `train_missing_movement_heads_v1.py` | `tools/` | NO | G4-2 |
| 6 | `clone_sibling_dir_heads_v1.py` | `tools/` | NO | G4-2 |
| 7 | `patch_active_artifact_provenance.py` | root | NO | G4-2 / meta-only patch policy |

**Pre-Phase-1 grep audit (required):** `rg -n "models/active|active_\{|shutil\.copy.*active|_replace_active_dir"` across `*.py` and `tools/*.py`; diff against table above; file any new writers in P0-0 doc.

**Gate to Phase 1:** `verify_active_models.py` exit 0 for SPY, QQQ, IWM; governed manifest for each horizon on SPY after `--run-now --force-retrain --bypass-cache --horizon 1c`.

---

### Phase 1 — Fail-closed scheduler (2–4 days)

**Objective:** Never silently “succeed” with broken artifacts. Closes **G4-3**.

| Task | Behavior |
|------|----------|
| P1-1 | Per-ticker outcome enum: `trained`, `cache_skipped`, `train_failed`, `eval_failed`, `promote_skipped`, `promote_ok`, `verify_failed`, **`cache_skip_streak_exceeded`** |
| P1-2 | `run_once` summary; CLI exit **1** if any **core** ticker non-success for requested horizons |
| P1-3 | `--all-horizons` aggregates exit code |
| P1-4 | `training_report.jsonl`: `horizon`, `governed_failed_closed`, `artifact_complete`, `promotion_decision`, `blocked_promotion_flags`, `consecutive_cache_skips` |
| P1-5 | Reject partial 7-file bundles before eval |
| P1-6 | **Consecutive cache skip cap** (e.g. 3) → outcome `cache_skip_streak_exceeded` → core ticker fails run (closes risk-register item) |

**Tests:** `tests/test_scheduler_arch_competition_integration.py` — failure → exit 1.

---

### Phase 2 — Canonical active layout (2–3 days)

**Objective:** One directory per (ticker, horizon) for verify and inference.

| Task | Behavior |
|------|----------|
| P2-1 | Canonical root = `scheduler_active_root(hz)` only |
| P2-2 | Promotion writes full 7-file bundle to `models/active_{hz}/{T}/` (1c → `models/active/{T}/`) |
| P2-3 | `tools/consolidate_active_horizon_layout.py` on SPY/QQQ/IWM |
| P2-4 | `ml_predict._model_dir_for_ticker` — single root, no ambiguous tie-break |
| P2-5 | `OPEN_ITEMS.md` + runbook migration note |

**Acceptance:** No meta-only `active_5c/SPY` while weights only under `active/SPY`.

---

### Phase 3 — Automatic promotion (core deliverable, 4–6 days)

**Objective:** Governance-approved winners reach production without operator CLI.

#### 3A — Env flags (enable + panic + scope)

```text
ED_SCHEDULER_AUTO_PROMOTE=0|1              # enable path (default 0)
ED_DISABLE_AUTO_PROMOTE=1                  # PANIC: overrides enable; forces no-write always
ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY=1      # SPY, QQQ, IWM first
ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY=1 # verify after each promote
ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS=0|1  # default 0 at first host flip; see P3-11
ED_CONSOLE_RELOAD_URL=                           # default http://127.0.0.1:8000/api/internal/reload_models; "" disables
ED_CONSOLE_PORT=8000                             # used when URL not set explicitly
ED_CONSOLE_RELOAD_TOKEN=                         # optional; X-Reload-Token header
```

**Effective auto-promote:**

```python
def scheduler_auto_promote_to_active_enabled() -> bool:
    if os.environ.get("ED_DISABLE_AUTO_PROMOTE", "").strip() in ("1", "true", "yes"):
        return False
    return os.environ.get("ED_SCHEDULER_AUTO_PROMOTE", "").strip() in ("1", "true", "yes")
```

Panic-disable must be tested: `ED_SCHEDULER_AUTO_PROMOTE=1` + `ED_DISABLE_AUTO_PROMOTE=1` → **no** active writes.

| Task | Detail |
|------|--------|
| P3-1 | Implement env-based `scheduler_auto_promote_to_active_enabled()` (default False in CI) |
| **P3-1b** | **Refactor `assert_active_mutation_only_via_manual_control`** (`manual_control.py:554-559`) | Today: raises `ManualGovernanceError` whenever auto-promote flag is True — breaks `tests/test_manual_governance.py::test_assert_active_mutation_guard` and blocks any future runtime use. **Replace with:** `assert_active_writes_use_governed_executor(caller)` — allow writes only when routed through `execute_promotion_if_eligible` (manual operator_id **or** scheduler audit record). Ship **in same PR as P3-1**. |
| P3-2 | Split promotion **decision** vs **execution** — `decide_promotion` stays decision-only; remove `auto_promote=True` raise or restrict to decision record only |
| P3-3 | `execute_promotion_if_eligible()` in `manual_control.py` (manual + scheduler) |
| P3-4 | After `decide_promotion`, if eligible + auto enabled + not panic-disabled → execute + audit |
| **P3-4b** | If `ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY=1` (default when auto-promote on): after `execute_promotion_if_eligible` returns success, run **`verify_active_models` synchronously for the just-promoted (ticker, horizon) tuple only** (not full-universe scan). Record `post_promote_verify_passed` in `training_report.jsonl`. |
| P3-5 | Rollback checkpoint before every auto-promote (checkpoint id stored for P3-9) |
| P3-6 | `promotion_record.auto_promote_executed=true`, `training_report.promoted=true` |
| P3-7 | If auto off or panic on: `production_write_held=true` (current behavior) |
| P3-8 | Remove/disable `_promote_candidate` shutil path (`ml_scheduler.py:1783-1804`) — **G4-4** closure; add static grep guard test so it cannot silently return |
| **P3-9** | **Verify-fail → rollback:** if P3-4b verify fails (or inline verify after promote when REQUIRE_VERIFY set): call `manual_rollback_to_checkpoint_explicit` using the P3-5 checkpoint; set outcome **`promote_ok` → `verify_failed`**; log `verify_failed_rolled_back=true`; **core ticker contributes exit 1** via Phase 1 enum. Active dir must match pre-promote state after rollback — never leave a verify-non-compliant bundle in production. |
| **P3-10** | **Live-server model reload after promote** — see **§3E** (required before nightly host enable). Summary: batch reload via `ED_CONSOLE_RELOAD_URL`; visible outcomes in `training_report.jsonl`; reload failure does **not** roll back promote. |
| **P3-11** | **First-week core freshness strictness:** `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS=0|1` (default **0** at first host flip). When **0**: core `promote_skipped` with `would_promote=true` is logged + counted in status JSON but **does not** contribute to exit 1 — avoids failure spam from legitimate cache hits / eval gate rejects during baseline week. When **1** (steady state, flip after baseline): core `promote_skipped` on a day with `would_promote=true` → exit 1 per Appendix D. |

#### 3E — Live reload after promote (P3-10 detail)

Nightly setup is **two processes**: `ml_scheduler.py --wait` and `server.py` side-by-side. Disk promote alone does not refresh in-memory registries (`ml_predict.py` ~194–199: `_xgb_registry`, `_lstm_registry`, `_trans_registry` load once per `(ticker, hz)`).

**Env (explicit URL — no silent localhost assumption):**

```text
ED_CONSOLE_RELOAD_URL     # default: http://127.0.0.1:${ED_CONSOLE_PORT:-8000}/api/internal/reload_models
                            # empty "" → disable reload call (scheduler-only / training-rig deployments)
ED_CONSOLE_PORT             # optional; default 8000 (matches server.py uvicorn docstring)
ED_CONSOLE_RELOAD_TOKEN     # optional shared secret; if set, scheduler sends X-Reload-Token header
```

Resolve `ED_CONSOLE_RELOAD_URL` at scheduler startup; log effective URL (redact token). When empty, emit `live_reload.called=false` — never assume localhost succeeded.

**Endpoint contract** (`POST`, JSON body — batch shape from day one):

```json
{
  "reloads": [
    { "ticker": "SPY", "horizon": "1c" },
    { "ticker": "SPY", "horizon": "5c" }
  ]
}
```

Response:

```json
{
  "schema_version": "reload_models_v1",
  "results": [
    { "ticker": "SPY", "horizon": "1c", "succeeded": true },
    { "ticker": "SPY", "horizon": "5c", "succeeded": false, "error": "registry_evict_failed" }
  ],
  "partial_failure": true
}
```

Server: `invalidate_model_registry(ticker, hz)` per tuple; return per-tuple success (handles locked files / partial horizon mix — worse than uniformly stale).

**Three wiring rules:**

1. **Failure is visible, not silent.** Each promote logs `live_reload` into `training_report.jsonl`:

```json
"live_reload": {
  "called": true,
  "url": "http://127.0.0.1:8000/api/internal/reload_models",
  "results": [
    { "ticker": "SPY", "horizon": "1c", "succeeded": true, "http_status": 200 },
    { "ticker": "SPY", "horizon": "5c", "succeeded": false, "http_status": 503, "error": "connection refused" }
  ],
  "live_reload_partial_failure": true
}
```

Or when disabled: `{ "called": false, "reason": "ED_CONSOLE_RELOAD_URL=<empty>" }`. Operator greps `succeeded: false` or `live_reload_partial_failure` to detect stale predictions.

2. **Reload failure does NOT block promote.** Promote + verify already committed on disk; rolling back because reload failed leaves disk new + memory old with no signal. Keep `promote_ok`; emit warning; operator restarts server or re-invokes reload manually.

3. **Endpoint not Internet-reachable.** Minimum: reject non-loopback clients (`request.client.host not in 127.0.0.1/::1` → 403). Stronger (reverse-proxy setups): require `X-Reload-Token` matching `ED_CONSOLE_RELOAD_TOKEN` on both scheduler and server.

**When to call:** After each successful auto-promote + P3-4b verify for that tuple; batch accumulated reloads at end of ticker loop or end of `--all-horizons` leg — either is fine if every promoted tuple appears in `results` and is logged.

**Host-enable check:** With console running on actual port, scheduler promote → grep `live_reload` shows `succeeded: true` for promoted tuples. Connection refused with non-empty URL = **block host enable** until URL/port/process fixed.

#### 3B — Promotion gates (must all pass for auto)

Reuse `PromotionPolicy` + `validate_for_promotion` + manifest lineage:

- Complete 7-file bundle
- `training_timeframe == "1m"`, correct `target_column`
- **`rows_used >= 500`** (same as PromotionPolicy — integration tests must use ≥500 labeled rows, not “minimal” fixtures that skip the gate)
- Eval accuracy / balanced accuracy thresholds
- Beat incumbent OR `--force-retrain` with broken active contract
- No `blocked_promotion_flags`
- Lineage `ml_horizon_slug` matches run horizon (**G3-R3**)
- **Feature NULL budget (operator decision):** default critical-feature NULL cap **30%** for `qqq_weighted_push` etc. — **explicit operator pick**; document waiver path in runbook if waived

#### 3C — Pre-flip validation harness (required before host enable)

**Do not set `ED_SCHEDULER_AUTO_PROMOTE=1` on the automation host until this passes once.**

**Default mode: frozen candidate dirs** (validates the *promotion path*, not re-training). Re-training between capture and replay invalidates the diff (new timestamps, candidate contents, possibly different winner) — use only as an **advanced** end-to-end smoke, not for the gate.

**Freeze mechanism (P0-0 / harness):** After a train+eval pass with auto-promote off, copy candidate trees to a stable snapshot:

```text
models/_preflip_{run_id}/{T}/parallel/   ← copy from models/parallel/{T}/ (or horizon-specific candidate root)
models/_preflip_{run_id}/{T}/cascade/
```

Both capture and replay runs point at the frozen tree via `--preflip-candidate-root models/_preflip_{run_id}` (CLI flag to add in PR4). Governed eval + promotion decision re-run against frozen inputs; training step skipped on replay.

**Source-tree freeze invariant (process):** Between `--freeze-and-capture` and `--verify`, **do not** invoke `ml_scheduler.run_once`, `train_all.py`, or any training entry point against the live `models/parallel/` or `models/cascade/` trees. Harness replay reads only from `models/_preflip_{run_id}/`, but a stray train overwriting live candidates makes manual debugging and checksum reconciliation misleading — diff failures would appear for the wrong reason.

**Pre-flip JSON schema** (`models/arch_competition/_preflip_decisions_{run_id}.json`):

```json
{
  "schema_version": "preflip_decisions_v1",
  "run_id": "...",
  "captured_at_utc": "...",
  "candidate_root": "models/_preflip_{run_id}",
  "decisions": [
    {
      "ticker": "SPY",
      "horizon": "1c",
      "would_promote": true,
      "winner_architecture": "parallel",
      "manifest_path": "...",
      "blocked_promotion_flags": [],
      "candidate_checksums": { "parallel": "sha256:...", "cascade": "sha256:..." },
      "expected_active_files": ["xgb_SPY_1c.pkl", "..."]
    }
  ]
}
```

Validator rejects unknown `schema_version` so re-runs months later still validate.

**Steps:**

1. **Capture (promote held):** Train+eval once with auto-promote off → freeze candidates → record decisions JSON + checksums.
2. **Replay (promote executed):** Same frozen root, `ED_SCHEDULER_AUTO_PROMOTE=1`, skip retrain → execute promotes only.
3. **Diff:** Active tree after replay must match capture decisions exactly (files, arch, horizon roots).
4. **Artifact:** `tools/validate_autopromote_preflip.py` — `--capture-only`, `--verify --run-id <id>`; exit 0 only on match.

**Advanced mode (optional):** full `--force-retrain --bypass-cache` on both legs — useful as a smoke test, **not** the PR4 merge gate.

**Phase 3 acceptance (operator + harness, default frozen mode):**

```powershell
# Step 1 — train+eval, freeze, capture decisions (auto-promote off)
python ml_scheduler.py --run-now --force-retrain --bypass-cache --all-horizons
python tools/validate_autopromote_preflip.py --freeze-and-capture --run-id <id>

# Step 2 — replay promotion only (after PR4 merged)
$env:ED_SCHEDULER_AUTO_PROMOTE = "1"
$env:ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY = "1"
python ml_scheduler.py --run-now --preflip-candidate-root models/_preflip_<id> --all-horizons

python tools/validate_autopromote_preflip.py --verify --run-id <id>
python verify_active_models.py
```

Emergency stop: `$env:ED_DISABLE_AUTO_PROMOTE = "1"` (no restart required if scheduler reads env each run).

#### 3D — Tests

- `tests/test_arch_competition_auto_promote.py`
- `tests/test_auto_promote_rollback.py`
- `tests/test_post_promote_verify_and_rollback.py` — P3-4b + P3-9: verify fail → checkpoint restored, outcome `verify_failed`, exit 1 for core
- `tests/test_model_registry_reload_after_promote.py` — P3-10: batch reload → per-tuple registry evict; partial failure logged
- `tests/test_console_reload_url_env.py` — empty URL → `called: false`; wrong port → `succeeded: false` visible in report shape
- `tests/test_strict_core_freshness_env.py` — P3-11: strict off → promote_skipped no exit 1; strict on → exit 1
- `tests/test_panic_disable_auto_promote.py` — enable + panic → no write
- `tests/test_no_promote_candidate_in_scheduler.py` — static grep: `"_promote_candidate"` absent from `ml_scheduler.py` source (P3-8 regression guard)
- Update `test_assert_active_mutation_guard` → `test_governed_executor_required_for_active_writes`
- CI default: auto-promote off; optional nightly job with env on + preflip fixture

---

### Phase 4 — Data quality & pre-train integration (3–5 days)

| Task | Detail |
|------|--------|
| P4-1 | Wire `pre_train_gate` into scheduler start (`--skip-pre-train-gate` for dev) |
| P4-2 | Per-ticker readiness slice in scheduler log |
| P4-3 | Feature NULL backfill (`qqq_weighted_push`, `iv_rank`) |
| P4-4 | Auto-promote block on NULL budget breach (threshold = operator-confirmed, default 30%) |
| P4-5 | `outcome_15c` / `outcome_60c` label density check before train |

Universe: batch `ED_ML_SCHEDULER_TICKERS`; auto-promote pinned + user_persisted before panel_auto.

**Scope rollout (Phase 4 extends env):** Phase 3 uses binary `ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY=1`. Phase 4 adds **`ED_SCHEDULER_AUTO_PROMOTE_CATEGORIES=core,pinned,user_persisted`** (comma-separated enrollment categories) so core → core+pinned expansion does not require a code change.

**CRWD / partial bundles:** If CRWD remains partial after dedicated `--force-retrain`, auto-promote must **hold CRWD** (`promote_skipped`, reason `partial_bundle`) **without failing the whole nightly run** — same pattern for any non-core ticker with incomplete artifacts. Core tickers (SPY/QQQ/IWM) still fail-closed per P1-2.

---

### Phase 5 — Observability & ops (2–3 days)

| Task | Detail |
|------|--------|
| P5-1 | `/ops` panel: last run, promote status, manifest links |
| P5-2 | `GET /api/training/status` |
| P5-3 | Digest on auto-promote / fail-closed (optional webhook) |
| P5-4 | UI training freshness chip |
| P5-5 | Nightly Task Scheduler recipe in `TRAINING_AND_MAINTENANCE.md` |

---

### Phase 6 — Hardening & governance closure (3–5 days)

| OPEN_ITEMS ID | Action | Plan phase |
|---------------|--------|------------|
| G3-R1 | Single completeness contract | P0-5, P2 |
| G3-R2 | Remove or wire `promotion_decision` in manifests | P6 |
| G3-R3 | Lineage fix | P0-4 |
| G4-1 | Server active sync audit/quarantine | P6 |
| G4-2 | Movement-head tools → candidate-only or executor | P6 + P0-0 |
| G4-3 | Fail-closed exit | P1 |
| G4-4 | Dormant `_promote_candidate` removed | P3-8 |
| TRACK 4 | Four horizons = four scheduler runs + auto-promote each; full retrain epic separate | doc only |

**Integration test (golden path):**

- Fixture DB with **≥500** labeled RTH rows for SPY (exercises real PromotionPolicy gates)
- Scheduler slice + auto-promote on (test env only)
- `verify_active_models` compliant
- `@pytest.mark.integration` — optional nightly CI

---

## 4. Recommended operator runbook (after Phase 3 + pre-flip)

### Daily / nightly (automatic)

```powershell
$env:ED_SCHEDULER_AUTO_PROMOTE = "1"
$env:ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY = "1"
$env:ED_CONSOLE_RELOAD_URL = "http://127.0.0.1:8000/api/internal/reload_models"  # match actual console port
# ED_DISABLE_AUTO_PROMOTE unset
python ml_scheduler.py --wait --all-horizons
# After run: rg "live_reload_partial_failure|succeeded.: false" models/training_report.jsonl
```

### Emergency — stop all auto writes immediately

```powershell
$env:ED_DISABLE_AUTO_PROMOTE = "1"
```

### Manual train day

```powershell
$env:ED_SCHEDULER_AUTO_PROMOTE = "1"
$env:ED_ML_SCHEDULER_TICKERS = "SPY,QQQ,IWM"
python ml_scheduler.py --run-now --force-retrain --bypass-cache --all-horizons
python verify_active_models.py
```

### Rollback

`manual_rollback_to_checkpoint_explicit` — checkpoint under `models/arch_competition/{hz}/{T}/rollback_checkpoints/`.

---

## 5. Risk register

| Risk | Mitigation |
|------|------------|
| Bad model auto-promoted | PromotionPolicy + P3-4b require verify + **P3-9 verify-fail rollback** + pre-flip harness |
| Verify-non-compliant active left in prod | **P3-9** automatic rollback to pre-promote checkpoint |
| Promote wrong horizon | G3-R3 lineage lock |
| panel_auto sparse promote | `AUTO_PROMOTE_CORE_ONLY` |
| OOM mid-train | Per-ticker try/except; fail ticker not whole run |
| Cache skip hides stale train | P1-6 consecutive skip cap; `--bypass-cache` on force-retrain |
| Partial writer unification | **P0-0 inventory + PR4 gate** |
| Test CI breaks | Auto-promote default off; dedicated job |
| Stale predictions after disk promote | **P3-10** + `ED_CONSOLE_RELOAD_URL`; grep `live_reload` / `live_reload_partial_failure` |
| False-positive nightly exit 1 during baseline week | **P3-11** `STRICT_CORE_FRESHNESS=0` until operator flips to 1 |
| Cannot stop auto-promote quickly | **`ED_DISABLE_AUTO_PROMOTE=1`** panic override |

---

## 6. Definition of done (program complete)

**PR1–PR4.1 slice (push-ready on branch):**

- [x] P0-0 writer inventory complete (post-PR4 refresh in `governance/ACTIVE_DIRECTORY_WRITER_INVENTORY.md`)
- [x] SPY, QQQ, IWM compliant in `verify_active_models.py` (full universe scan may exit 1 on non-core tickers)
- [ ] Pre-flip validation harness passed once on automation host (operator e2e — not git-gated)
- [ ] No manual promote for routine nightly until host enables `ED_SCHEDULER_AUTO_PROMOTE=1`
- [x] Scheduler exit 1 on any core ticker failure (**G4-3** closed, PR2)
- [ ] Governed manifests for four horizons per core ticker after success (runtime / training cadence)
- [x] Canonical active layout — no split-brain (PR3)
- [ ] `qqq_weighted_push` NULL &lt; operator threshold OR documented waiver
- [x] Docs: `TRAINING_AND_MAINTENANCE.md`, plan §7.0, OPEN_ITEMS push-review rows
- [x] P3-4b post-promote verify + P3-9 verify-fail rollback tested (PR4.1)
- [x] P3-10 model registry reload after promote (code + tests)
- [ ] P3-11 strict core freshness flipped to 1 after baseline week (host steady-state; default off in code)
- [x] Pytest green + auto-promote + panic-disable + `_promote_candidate` grep guard tests (**2619** at tip)
- [ ] Pinned universe batch (optional Phase 4b — PR5+)

---

## 7. Implementation order (PR sequence)

1. **PR1:** Phase 0 (P0-0 inventory doc, G3-R3, G3-R1, status JSON)  
2. **PR2:** Phase 1 (exit codes, outcome enum, P1-6 cache skip cap) — **G4-3**  
3. **PR3:** Phase 2 (layout + consolidate SPY/QQQ/IWM)  
4. **PR4 pre-check (operator, not a PR):** Run pre-flip harness **capture-only** on current manual path OR post-PR4 dry run  
5. **PR4:** Phase 3 (auto-promote + **P3-1b** + **P3-4b** + **P3-9** + **P3-10** + **P3-11** + panic env + P3-8 remove `_promote_candidate` + preflip frozen mode + schema v1 JSON)  
6. **PR4 post-check:** Pre-flip harness **verify** step; enable nightly with `ED_SCHEDULER_AUTO_PROMOTE=1`, `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS=0`; after baseline week flip strict to 1  
7. **PR5:** Phase 4  
8. **PR6:** Phase 5  
9. **PR7:** Phase 6  

### 7.0 Implementation status (local branch)

| PR | Commit (code) | Phase | Status |
|----|---------------|-------|--------|
| PR1 | `5886ca0` | 0 — inventory, lineage, bundle contract, status JSON | Done |
| PR2 | `4375c58` | 1 — G4-3 fail-closed, outcome enum, cache skip cap | Done |
| PR3 | `2d8208e` | 2 — canonical active layout | Done |
| PR4 | `51e27ce` | 3 — auto-promote, governed executor, reload, preflip tool | Done |
| PR4.1 | `8feab6b` | 3 follow-up — preflip §3C verify, rollback/guard tests | Done |
| PR5–PR7 | — | Phases 4–6 | Not started |

OPEN_ITEMS push-review rows: signed off 2026-05-21 (2619 pytest at tip). Phase 3a.1 done: `scheduler_log_loss_winner` in `report`, `promotion_decision_record`, and eval dashboard metrics (not ambiguous `"winner"`).

### Merge gates (non-negotiable)

- **Do not merge PR4 until PR1–PR3 pass** — auto-promote on broken eval/layout is worse than manual.
- **Do not merge PR4 until P0-0 active-directory writer inventory is complete** (grep reconciled with G1 list).
- **Do not merge PR4 until P3-4b (REQUIRE_VERIFY wired) and P3-9 (verify-fail rollback) are implemented** — correctness/safety, not optional.
- **Do not merge PR4 until P3-10 (live model registry reload) is implemented** — stale in-memory predictors otherwise.
- **Do not enable `ED_SCHEDULER_AUTO_PROMOTE=1` on the host until:** pre-flip harness passes **and** P3-10 deployed **and** host-enable reload check succeeds (`live_reload.succeeded: true` for a test promote, or documented manual reload + grep clean).
- **Host enable defaults:** `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS=0` for first 1–2 weeks; flip to `1` for steady-state freshness enforcement.

---

## 8. Key files (leaf index)

| Concern | Path |
|---------|------|
| Scheduler | `ml_scheduler.py` |
| Auto-promote flag | `arch_competition/scheduler_integration.py:95-97` |
| Promotion decision | `arch_competition/promotion_engine.py:106-107` |
| Promotion execution | `arch_competition/manual_control.py` |
| **Guard (P3-1b)** | `arch_competition/manual_control.py:554-559` |
| Dormant writer | `ml_scheduler.py:1783-1804` |
| Writer inventory (deliverable) | `governance/ACTIVE_DIRECTORY_WRITER_INVENTORY.md` |
| Writer inventory source | `governance/G1_DIAGNOSIS.md` § Direct-Active Writer Inventory |
| Pre-flip harness | `tools/validate_autopromote_preflip.py`, `models/arch_competition/_preflip_decisions_{run_id}.json` |
| OPEN_ITEMS | `OPEN_ITEMS.md` G3 Reconciliation Queue, G4 queue |
| Inference / reload | `ml_predict.py` (~194–199 registries), `server.py` `POST /api/internal/reload_models`, `ml_scheduler.py` reload client |
| Verify | `verify_active_models.py` |
| Pre-train | `ops_runner.py` (`pre_train_gate`) |

---

## 9. Questions for operator (before Phase 3 merge)

1. Nightly: permanent `ED_SCHEDULER_AUTO_PROMOTE=1` on automation host after pre-flip?  
2. Scope: core only vs all pinned (15) + CRWD?  
3. panel_auto: train yes, auto-promote no?  
4. Promotion thresholds: unchanged vs tightened for auto?  
5. **`qqq_weighted_push` NULL cap:** confirm **30%** or other?  
6. Failure notify: log only vs webhook?  
7. **Baseline week end date** for flipping `STRICT_CORE_FRESHNESS` to 1?

---

## Appendix A — Claude handoff (paste this with the plan)

**Task:** Implement PR1–PR7 in `docs/plans/TRAINING_PIPELINE_AUTOMATION_PLAN.md` on branch `feature/institutional-key-levels` (or `feature/training-pipeline-automation`). Read the plan end-to-end first; then read the files in Appendix B before editing.

**Constraints:**
- Do **not** merge PR4 until PR1–PR3 pass, P0-0 inventory is complete, P3-4b + P3-9 + **P3-10** are implemented.
- Do **not** enable auto-promote on host until pre-flip passes and P3-10 reload check succeeds against **actual** `ED_CONSOLE_RELOAD_URL` (not assumed localhost).
- First host enable: `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS=0` (P3-11); flip to `1` after baseline week.
- Auto-promote env defaults **off**; CI must stay green without env flags.
- Single active writer: `execute_promotion_if_eligible()` in `manual_control.py` — delete scheduler `_promote_candidate`.
- Preserve manual `manual_promote_to_active_explicit` / rollback CLI; refactor internals, don’t remove operator path.

**Start PR1 with:** P0-0 grep audit → `governance/ACTIVE_DIRECTORY_WRITER_INVENTORY.md`, then G3-R3 lineage fix, then G3-R1 bundle contract alignment.

**Verify each PR:** `pytest` on touched tests + acceptance criteria in the phase table.

---

## Appendix B — Runtime integration map (where to wire)

### B.1 Per-ticker loop in `ml_scheduler.run_once` (~1271+)

Current order for each `(ticker, hz_sched)`:

| Step | Location | Today | Change |
|------|----------|-------|--------|
| Train parallel/cascade | ~1500–1670 | Writes `models/parallel/{T}/`, `models/cascade/{T}/` | No change |
| Governed eval | `1687–1695` `run_governed_architecture_competition_pass` | Manifest + promotion record under `models/arch_competition/{hz}/{T}/` | Fix G3-R3 inputs |
| Fail-open on eval error | `1723–1729` | Sets `governed_slice.failed_closed=True`, **continues** | Phase 1: core ticker → `eval_failed`, exit 1 |
| Legacy promote block | `1898–1947` | Calls `_promote_candidate` if `_scheduler_auto_promote_to_active()` | **Remove.** Replace with call to `execute_promotion_if_eligible` when env on, using `_gov["promotion_record"]` + manifest winner |
| Report write | ~1950+ | `training_report.jsonl` line | Add outcome enum fields (P1-4) |

### B.2 Refactor target: `manual_promote_to_active_explicit` (~226+)

Extract from existing manual path (do not rewrite from scratch):

1. Load manifest + promotion record from `models/arch_competition/{hz}/{T}/`
2. Validate lineage + paths (`_validate_manifest_paths_match_canonical`)
3. `_snapshot_active_to_checkpoint` → checkpoint id
4. `_copy_candidate_to_active` from winner dir (`parallel/{T}` or `cascade/{T}`)
5. Update `arch_state.json` for horizon
6. Audit record

**New:** `execute_promotion_if_eligible(model_dir, ticker, hz, *, operator_id=None, scheduler_run_id=None, promotion_record, manifest)` — same steps 3–6; manual path passes `operator_id` + intent; scheduler passes `scheduler_run_id` + audit metadata.

### B.3 Post-promote verify + rollback (P3-4b, P3-9)

After step 4 succeeds:

```text
if REQUIRE_VERIFY:
    result = verify_single_bundle(ticker, hz)   # new helper or verify_active_models slice
    if not result.compliant:
        manual_rollback_to_checkpoint_explicit(..., checkpoint_id from step 3)
        outcome = verify_failed
        log verify_failed_rolled_back=true
```

Add `verify_single_bundle()` to `verify_active_models.py` (reuse `check_artifact_compliance` logic for one hz).

### B.4 `--all-horizons` entry (~2289+)

Already loops `PRIMARY_DECISION_HORIZONS` and calls `run_once` per hz. Phase 1 must OR exit codes across horizons.

### B.5 `--preflip-candidate-root` (PR4)

When set: skip train steps; point `parallel_out` / `cascade_out` at frozen tree; still run governed eval + promote path.

### B.6 Post-promote live reload (P3-10 / §3E)

After `promote_ok` + P3-4b verify, accumulate `(ticker, horizon)` tuples and POST batch reload:

```text
POST ${ED_CONSOLE_RELOAD_URL}
Content-Type: application/json
X-Reload-Token: ${ED_CONSOLE_RELOAD_TOKEN}   # if set

{"reloads": [{"ticker": "SPY", "horizon": "1c"}, {"ticker": "SPY", "horizon": "5c"}]}
→ ml_predict.invalidate_model_registry(ticker, hz) per result
→ training_report.jsonl live_reload block (per §3E)
```

Reload failure: **warn only** — promote stays committed. Implement in PR4 — **host-enable gate**.

---

## Appendix C — Artifact & directory contract

### C.1 Directory layout

```text
models/
  parallel/{TICKER}/          # candidate parallel bundle (7 files per horizon trained)
  cascade/{TICKER}/           # candidate cascade bundle
  active/{TICKER}/            # production 1c (canonical)
  active_5c/{TICKER}/         # production 5c
  active_15c/{TICKER}/
  active_60c/{TICKER}/
  arch_competition/{hz}/{T}/  # evaluation_manifest.json, promotion_record.json, rollback_checkpoints/
  _preflip_{run_id}/{T}/      # frozen candidates for harness
  training_report.jsonl
  arch_state.json             # per-horizon slices (see existing governed layout)
```

Candidate dirs are **per ticker**, not per horizon subfolder — horizon is encoded in filenames (`xgb_SPY_5c.pkl`).

### C.2 Seven-file bundle (per ticker × horizon)

For horizon slug `{hz}` (e.g. `1c`, `5c`):

| # | Model | Meta |
|---|-------|------|
| 1 | `xgb_{T}_{hz}.pkl` | `xgb_{T}_{hz}_meta.json` |
| 2 | `lstm_{T}_{hz}.pt` | `lstm_{T}_{hz}_meta.json` |
| 3 | `transformer_{T}_{hz}.pt` | `transformer_{T}_{hz}_meta.json` |

Source: `verify_active_models.py:110–114`. Promotion must copy **all six files** (3 pairs) atomically via `_replace_active_dir_from_source`.

### C.3 Two promotion decision systems (do not conflate)

| System | Used for | Thresholds |
|--------|----------|--------------|
| **Scheduler legacy** | `_promote_candidate` + `validate_for_promotion` | `PROMOTION_POLICY.md`: acc ≥0.34, bal ≥0.33, rows ≥500, beat incumbent |
| **Arch competition (authoritative for auto)** | `decide_promotion(manifest)` | `PromotionPolicy` in `promotion_engine.py`: log_loss delta, Brier, ECE, regime gates |

**PR4 rule:** Auto-promote follows **`decide_promotion` winner + `would_promote_challenger`**, not scheduler log-loss tie-break at `ml_scheduler.py:1872–1896`. Scheduler tie-break becomes diagnostic-only in report; production copy uses manifest `recommended_architecture` (or equivalent field — read `promotion_record` schema before implementing).

---

## Appendix D — Outcome enum & exit-code rules

### D.1 Per (ticker, horizon) terminal outcomes

| Outcome | Meaning | Core ticker effect |
|---------|---------|-------------------|
| `trained` | Train + eval OK; promote held (auto off) or not eligible | Success if no promote required |
| `promote_ok` | Auto or manual promote + verify passed | Success |
| `promote_skipped` | Eligible but held (auto off, partial bundle, scope filter, panic) | Success for **non-core**; core fails if promote was required for nightly freshness policy* |
| `cache_skipped` | Training cache hit, no retrain | Success if streak ≤ cap |
| `cache_skip_streak_exceeded` | Too many consecutive skips | **Fail** (core) |
| `train_failed` | Exception in train path | **Fail** (core) |
| `eval_failed` | Governed pass failed / `failed_closed` | **Fail** (core) |
| `verify_failed` | Post-promote verify failed (rolled back) | **Fail** (core) |

\* **Core freshness (P3-11):** When `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS=1`, core `promote_skipped` with `would_promote=true` → exit 1. When **0** (default at first host flip): same skips are logged and surfaced in status JSON but **do not** fail the nightly run — use during baseline week to avoid masking real regressions with legitimate gate/cache skips. Flip to **1** after baseline.

### D.2 `--all-horizons` aggregation

Exit **1** if any core ticker has any horizon outcome ∉ `{trained, promote_ok, cache_skipped}` when that horizon was requested — **except** core `promote_skipped` with `would_promote=true` when `STRICT_CORE_FRESHNESS=0`.

Non-core (CRWD, panel_auto): partial bundle → `promote_skipped` only; **does not** fail nightly (§Phase 4).

---

## Appendix E — G3-R3 fix direction (P0-4)

**Symptom:** `EvaluationLineageError: manifest horizon '1c' != expected '5c'` when running `--horizon 5c`.

**Root cause hypothesis (verify in code):** `scheduler_run_manifest.json` under `models/parallel/{T}/` and `models/cascade/{T}/` retains `ml_horizon_suffix: "1c"` from a prior 1c train while a 5c governed pass passes `expected_ml_horizon_suffix="5c"` into `validate_parallel_cascade_manifest_lineage` (`lineage.py:95–102`).

**Fix direction (pick minimal correct one after trace):**
1. Ensure each `--horizon {hz}` train writes manifests with matching `ml_horizon_suffix={hz}` before governed eval; OR
2. Scope candidate dirs per horizon (e.g. `parallel_{hz}/{T}/`) if manifests cannot be shared; OR
3. Re-run manifest stamp at governed-pass boundary from `hz_sched` run context.

**Acceptance:** `run_governed_architecture_competition_pass` succeeds for SPY on all four horizons in one `--all-horizons` run; `models/arch_competition/{hz}/SPY/` directories exist with manifests.

---

## Appendix F — Environment & CLI reference

### F.1 Environment variables

| Variable | Default | Phase | Effect |
|----------|---------|-------|--------|
| `ED_SCHEDULER_AUTO_PROMOTE` | off | 3 | Enable auto promote path |
| `ED_DISABLE_AUTO_PROMOTE` | off | 3 | **Panic:** force no active writes (wins over enable) |
| `ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY` | off | 3 | Only SPY, QQQ, IWM (+ `CORE_TICKERS`) |
| `ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY` | on when auto on | 3 | P3-4b inline verify |
| `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS` | **0** at host flip | 3 | P3-11: 0 = core promote_skipped no exit 1; 1 = steady-state freshness |
| `ED_SCHEDULER_AUTO_PROMOTE_CATEGORIES` | — | 4 | e.g. `core,pinned,user_persisted` |
| `ED_ML_SCHEDULER_TICKERS` | enrolled | existing | Limit train universe |
| `ED_CONSOLE_RELOAD_URL` | `http://127.0.0.1:8000/api/internal/reload_models` | 3 | P3-10 reload endpoint; `""` disables |
| `ED_CONSOLE_PORT` | `8000` | 3 | Used when `ED_CONSOLE_RELOAD_URL` unset |
| `ED_CONSOLE_RELOAD_TOKEN` | unset | 3 | Optional shared secret for reload POST |
| `ED_XGB_STRICT_ACTIVE_ONLY` | on | existing | Live inference fail-closed without active bundle |

### F.2 New CLI flags (by PR)

| Flag | PR | Effect |
|------|-----|--------|
| `--skip-pre-train-gate` | 4 | Bypass `ops_runner.pre_train_gate` at scheduler start |
| `--preflip-candidate-root PATH` | 4 | Skip train; use frozen candidates |

Existing: `--run-now`, `--wait`, `--force-retrain`, `--bypass-cache`, `--all-horizons`, `--horizon {1c,5c,15c,60c}`.

---

## Appendix G — Tests inventory

| Test file | PR | Purpose |
|-----------|-----|---------|
| `tests/test_scheduler_arch_competition_integration.py` | 1–4 | Governed pass, exit codes, no active write when off |
| `tests/test_manual_governance.py` | 3 | Manual promote/rollback; **update** guard test (P3-1b) |
| `tests/test_arch_competition_eval_promotion.py` | existing | PromotionPolicy thresholds — do not loosen |
| `tests/test_arch_competition_auto_promote.py` | 4 | New |
| `tests/test_auto_promote_rollback.py` | 4 | New |
| `tests/test_post_promote_verify_and_rollback.py` | 4 | P3-4b + P3-9 |
| `tests/test_panic_disable_auto_promote.py` | 4 | New |
| `tests/test_no_promote_candidate_in_scheduler.py` | 4 | Static grep guard |

Integration golden path (P6): ≥500 row SPY fixture, `@pytest.mark.integration`.

---

## Appendix H — Explicit non-goals & do-nots

- Do **not** auto-promote via `_promote_candidate` / `validate_for_promotion` alone — use governed `decide_promotion` + shared executor.
- Do **not** enable auto-promote in CI default job.
- Do **not** merge PR4 without pre-flip frozen-candidate harness passing on host.
- Do **not** leave verify-non-compliant files in active after failed P3-4b (must rollback).
- Do **not** leave reload failures invisible — every promote must emit a `live_reload` block (§3E).
- Do **not** roll back promote because reload failed (disk commit stands; fix reload or restart server).
- Do **not** fail entire nightly for CRWD/panel_auto partial bundles (hold only).
- Do **not** conflate STACK-WIRE work with this epic unless touching G3-R1 inference contract.
- G2 (cascade alignment rewrite) remains **paused** — this plan works within existing parallel/cascade architecture.

---

## Appendix I — Related docs (read before PR4)

| Doc | Why |
|-----|-----|
| `PROMOTION_POLICY.md` | Legacy scheduler promotion thresholds |
| `TRAINING_AND_MAINTENANCE.md` | Operator cadence; update in P5 |
| `governance/G1_DIAGNOSIS.md` | Writer inventory source |
| `OPEN_ITEMS.md` | G3-R1..R3, G4-1..4, TRACK 4 |
| `ops_runner.py` | `pre_train_gate` sequence for P4-1 |

---

*Share with Claude: `docs/plans/TRAINING_PIPELINE_AUTOMATION_PLAN.md` + Appendix A handoff block*
