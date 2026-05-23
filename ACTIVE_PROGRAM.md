# ACTIVE_PROGRAM.md — what we are doing now

**Updated:** 2026-05-23 (Phase 1a)  
**Branch:** `feature/institutional-key-levels` @ consolidation Phase 1a  
**Execution plan:** [`docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md`](docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md)

---

## Active program

**Governance consolidation & repo cleanup** — Phases 0–4 per execution plan. Phase 0 complete @ `f12bf75`. Phase 1a in progress / landing.

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

- **CI:** `.github/workflows/schwab-csv-first.yml` only; full pytest (~2620 tests) is local gate until pytest-to-CI OPEN_ITEMS row lands.
- **Memory portability:** `AGENTS.md` + repo `MEMORY.md` (Phase 1c) = portable; `[OPERATOR-ONLY]` prefs stay machine-local until archived.
- **Long branch:** prefer small consolidation commits; no force-push.
- **`config.py` credentials:** hardcoded Schwab API key/secret in tracked file — queue credential-hygiene slice (env-only, rotate, history scrub if ever public).
- **`verify_active_models.py`:** exit 1 on many non-core tickers; SPY/QQQ/IWM compliant — expected, not broken stack.
- **Consolidation limit:** reduces forgetfulness drift, not silent rule violation after Read.

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
