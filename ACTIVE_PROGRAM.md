> **Classification:** Active Rule Source | **Scope:** Current epic, conflicts, deferred work, known risks.

# ACTIVE_PROGRAM.md — what we are doing now

**Updated:** 2026-05-23 (tip `05cb883`)  
**Branch:** `feature/institutional-key-levels` — consolidation Phases 0–4 complete; pushing  
**Execution plan:** [`docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md`](docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md)

---

## Active program

**Governance consolidation** — **Phases 0–4 complete** @ `ed9f882` (3e: 9 worktrees pruned, ~2.43 GB freed). **Gate closed** (dual-agent re-audit 2026-05-24). **Next:** Schwab V4 walk primary thread. Training PR5–PR7 concurrent.

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
| Host auto-promote | **Off** until OPEN_ITEMS `TRAINING-HOST-PREFLIP-E2E` + `TRAINING-HOST-LIVE-RELOAD` close |
| OPEN_ITEMS archive path | `governance/archive/<quarter>/open_items_archive/` (first use creates quarter folder) |

---

## Known risks

- **CI:** `schwab-csv-first.yml` on every push/PR (CSV-first + committed meta/scoreboard pin; diff-emission on **pull_request** only). **`pytest.yml`** on every push/PR (`npm run test:all` — Playwright E2E + full pytest). **D17 closure** (`unreviewed_count == 0`) is `schwab-v4-closure.yml` (manual / main / register-path pushes) — expected fail until V4 walk completes.
- **Memory portability:** `AGENTS.md` + repo `MEMORY.md` (Phase 1c) = portable; `[OPERATOR-ONLY]` prefs stay machine-local until archived.
- **Long branch:** prefer small consolidation commits; no force-push.
- **`config.py` credentials (next highest-blast-radius slice):** hardcoded Schwab API key/secret in tracked file. **Slice shape when directed:** env-only loader with fail-closed on missing secrets + paired test + operator history-scrub/rotate plan — not a memo-only walk.
- **`verify_active_models.py`:** exit 1 on many non-core tickers; SPY/QQQ/IWM compliant — expected, not broken stack.
- **Pre-commit (Phase 4):** `pre-commit install` + `pre-commit install --hook-type commit-msg` — runs governance slice + deferral guard + `check_no_grep_subprocess.py` on staged files. `pre-commit run --all-files` is the acceptance bar.

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

**D17 register scope (do not conflate):** `unreviewed_count` ~4.1M is scanner row cardinality, not uniform-attention file count. **Operator-eyes bottleneck** = trade-decision producer/consumer cone (~30–80 files; money-path + server/populator/adapters — largely walked). **Mechanical long tail** = per-row classifier + per-row evidence per `scope_by_dataflow_relevance` (not line-by-line operator Read of every register row). V4 walk framing must keep these separate — "4.1M" is not "years of the same attention as money-path."

---

## Consolidation baseline (Phase 0 @ `dbb57c9`)

- Root `.py`: 132  
- Governance MD: 113 files / 16675 lines  
- Worktrees: ~2.3 GB  
- Artifacts: `governance/consolidation/phase0/`
