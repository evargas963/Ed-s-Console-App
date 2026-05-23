> **Classification:** Active Rule Source | **Scope:** Current epic, conflicts, deferred work, known risks.

# ACTIVE_PROGRAM.md — what we are doing now

**Updated:** 2026-05-23 (tip `05cb883`)  
**Branch:** `feature/institutional-key-levels` — Phases 0–2 + 4 landed; Phase 3 execution gated  
**Execution plan:** [`docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md`](docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md)

---

## Active program

**Governance consolidation** — Phases **0–2** and **4** complete. Phase **3 execution partial:** **3b/3c/3d/3f** landed via `tools/execute_phase3_cleanup.py` (`phase3_execution_log.json`); **3e worktree prune** still open (~2.43 GB, 9 dirty Claude worktrees — operator manual step). **Next:** 3e prune or push current state; then Schwab V4 walk. Training PR5–PR7 concurrent.

### Consolidation status (scope-explicit)

| Phase | Status |
|-------|--------|
| 0, 1a–1c | Complete |
| 2 | Complete @ `8e79ea2` |
| 3 decision | Complete @ `4018f41` |
| 3 execution | **Partial** — 3b archive ✅, 3c no-delete decisions ✅, 3d import audit ✅, 3f LFS audit ✅; **3e worktree prune open** |
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
| Host auto-promote | **Off** until OPEN_ITEMS `TRAINING-HOST-PREFLIP-E2E` + `TRAINING-HOST-LIVE-RELOAD` close |
| OPEN_ITEMS archive path | `governance/archive/<quarter>/open_items_archive/` (first use creates quarter folder) |

---

## Known risks

- **CI:** `schwab-csv-first.yml` on every push/PR (CSV-first + committed meta/scoreboard pin; diff-emission on **pull_request** only). **D17 closure** (`unreviewed_count == 0`) is `schwab-v4-closure.yml` (manual / main / register-path pushes) — expected fail until V4 walk completes. Full pytest (~2620 tests) remains local gate.
- **Memory portability:** `AGENTS.md` + repo `MEMORY.md` (Phase 1c) = portable; `[OPERATOR-ONLY]` prefs stay machine-local until archived.
- **Long branch:** prefer small consolidation commits; no force-push.
- **`config.py` credentials:** hardcoded Schwab API key/secret in tracked file — queue credential-hygiene slice (env-only, rotate, history scrub if ever public).
- **`verify_active_models.py`:** exit 1 on many non-core tickers; SPY/QQQ/IWM compliant — expected, not broken stack.
- **Pre-commit (Phase 4):** optional local hook — `pre-commit install` runs governance slice + `check_no_grep_subprocess.py` on staged Python.

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

---

## Consolidation baseline (Phase 0 @ `dbb57c9`)

- Root `.py`: 132  
- Governance MD: 113 files / 16675 lines  
- Worktrees: ~2.3 GB  
- Artifacts: `governance/consolidation/phase0/`
