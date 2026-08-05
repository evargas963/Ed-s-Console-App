# Rehab latest — 2026-08-05T03:35:17.946770+00:00

**HEAD:** `8da220ad` · **PM:** Cursor · **Mode:** recommend only (no auto-edit)

Findings: **2**

| Sev | ID | Facet | Summary | Recommendation |
|-----|----|-------|---------|----------------|
| P0 | `rehab.index_wt_drift` | worktree_integrity | 1 enforcement path(s) index≠WT | Reconcile WT from index (or re-stage intentional WT) before any green claim or commit. |
| P2 | `rehab.dirty_tree_sprawl` | worktree_hygiene | Dirty tree sprawl: 357 porcelain lines | PM: sequence landings; avoid multi-mission dirt; path-limited commits only. |

## Advisory debt (P1/RC-246 moved these off the blocking commit path)

**Total: 3360** · prior: 3360 · delta: = 0

| Check | Count |
|---|---:|
| `ruff_quality` | 1262 |
| `mypy_types` | 796 |
| `function_complexity` | 592 |
| `function_length` | 474 |
| `orphan_dict_keys` | 188 |
| `file_length` | 47 |
| `debt_ratchet` | 1 |

### Top hotspots (file · rule · count)

| File | Check | Count |
|---|---|---:|
| `calibration/phase65_edge_isolation_v1.py` | mypy_types | 45 |
| `db.py` | mypy_types | 22 |
| `features/signal_layer_v1.py` | mypy_types | 22 |
| `arch_competition/stack_bundle_eval_v1.py` | ruff_quality | 11 |
| `arch_competition/stack_bundle_eval_v1.py` | function_complexity | 10 |
| `calibration/daily_scoreboard.py` | function_complexity | 10 |
| `bayesian_fusion.py` | ruff_quality | 10 |
| `calibration/phase65_edge_isolation_v1.py` | ruff_quality | 10 |
| `arch_competition/stack_bundle_eval_v1.py` | function_length | 8 |
| `news_sentiment.py` | orphan_dict_keys | 8 |

## TQM queue — next ACT cycle (max 5)

Work ONLY these. Mass-rewriting the backlog is banned: every change needs a reproduce command and a test, and each item below carries the criteria that would KILL it as not-worth-doing.

**1. [P1] `debt_ratchet` → `governance/advisory_debt_baseline.json` (1 finding(s))**

- why now: 1 debt_ratchet finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: read the ratchet delta and revert whichever change raised it, or record why the rise is correct
- kill criteria: kill if the rise is a deliberate, reviewed addition already justified in an RC row

**2. [P2] `mypy_types` → `calibration/phase65_edge_isolation_v1.py` (45 finding(s))**

- why now: 45 mypy_types finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: annotate the single function the error names; do not restructure call sites
- kill criteria: kill if the annotation forces a runtime change, or if the error is in a vendored/legacy tree scheduled for deletion

**3. [P2] `mypy_types` → `db.py` (22 finding(s))**

- why now: 22 mypy_types finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: annotate the single function the error names; do not restructure call sites
- kill criteria: kill if the annotation forces a runtime change, or if the error is in a vendored/legacy tree scheduled for deletion

**4. [P2] `mypy_types` → `features/signal_layer_v1.py` (22 finding(s))**

- why now: 22 mypy_types finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: annotate the single function the error names; do not restructure call sites
- kill criteria: kill if the annotation forces a runtime change, or if the error is in a vendored/legacy tree scheduled for deletion

**5. [P2] `ruff_quality` → `arch_competition/stack_bundle_eval_v1.py` (11 finding(s))**

- why now: 11 ruff_quality finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: ruff --fix on THIS FILE only, then run the file's own test module; commit the autofix alone
- kill criteria: kill if the file has no test module, or if --fix touches money-path semantics (greeks, levels, decisions) rather than style

Machine-readable queue: `reports/tqm_queue_latest.json` · tally: `reports/advisory_debt_latest.json`

RE-MEASURE after acting: re-run this scan and confirm the delta moved. A win claimed in chat is not a win.

## Operator next

1. PM (Cursor) triages this table.
2. Operator green-lights one mission.
3. Sole writer executes; Cursor audits.

Queue log: `reports/rehab_queue.jsonl`
