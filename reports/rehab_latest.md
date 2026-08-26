# Rehab latest — 2026-08-26T22:05:09.158152+00:00

**HEAD:** `4b36a5d8` · **Mode:** recommend only (no auto-edit); the operator triages findings in chat and assigns the session

Findings: **4**

| Sev | ID | Facet | Summary | Recommendation |
|-----|----|-------|---------|----------------|
| P0 | `rehab.product.faucets_disagree` | one_faucet | 5 field(s) disagree across endpoints right now: spot, spread_frac, lo, hi, contracts_used | Two screens can show contradictory numbers with nothing to detect it. One producer per field (RC-262). |
| P1 | `rehab.product.complexity` | codebase_quality | 528 function(s) above the CC>15 review threshold; worst is 622 | Median CC under 10, flag above 15 (codeant seven axes). The worst outliers carry the risk, not the median. |
| P1 | `rehab.product.coverage_unmeasured` | codebase_quality | no coverage artefact: test coverage is unmeasured | 544 test files prove tests EXIST, not that they cover anything. Target >=80% on core modules. |
| P1 | `rehab.code_health_blocking` | static_quality | code_health_panel --check non-zero (BLOCKING defects or unmeasurable) | Run /code-health quality circle; drive BLOCKING to 0. |

## Advisory debt (P1/RC-246 moved these off the blocking commit path)

**Total: 3477** · prior: 3364 · delta: ▲ +113

| Check | Count |
|---|---:|
| `ruff_quality` | 1429 |
| `mypy_types` | 861 |
| `function_complexity` | 545 |
| `function_length` | 441 |
| `orphan_dict_keys` | 152 |
| `file_length` | 49 |
| `debt_ratchet` | 0 |

### Top hotspots (file · rule · count)

| File | Check | Count |
|---|---|---:|
| `calibration/phase65_edge_isolation_v1.py` | mypy_types | 45 |
| `server.py` | ruff_quality | 38 |
| `db.py` | mypy_types | 22 |
| `features/signal_layer_v1.py` | mypy_types | 22 |
| `tests/test_a1_conformal_artifact_production.py` | ruff_quality | 22 |
| `call_engine.py` | ruff_quality | 20 |
| `arch_competition/stack_bundle_eval_v1.py` | function_complexity | 10 |
| `calibration/daily_scoreboard.py` | function_complexity | 10 |
| `arch_competition/stack_bundle_eval_v1.py` | function_length | 8 |
| `call_engine.py` | function_complexity | 5 |

## TQM queue — next ACT cycle (max 5)

Work ONLY these. Mass-rewriting the backlog is banned: every change needs a reproduce command and a test, and each item below carries the criteria that would KILL it as not-worth-doing.

**1. [P2] `mypy_types` → `calibration/phase65_edge_isolation_v1.py` (45 finding(s))**

- why now: 45 mypy_types finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: annotate the single function the error names; do not restructure call sites
- kill criteria: kill if the annotation forces a runtime change, or if the error is in a vendored/legacy tree scheduled for deletion

**2. [P2] `ruff_quality` → `server.py` (38 finding(s))**

- why now: 38 ruff_quality finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: ruff --fix on THIS FILE only, then run the file's own test module; commit the autofix alone
- kill criteria: kill if the file has no test module, or if --fix touches money-path semantics (greeks, levels, decisions) rather than style

**3. [P2] `mypy_types` → `db.py` (22 finding(s))**

- why now: 22 mypy_types finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: annotate the single function the error names; do not restructure call sites
- kill criteria: kill if the annotation forces a runtime change, or if the error is in a vendored/legacy tree scheduled for deletion

**4. [P2] `mypy_types` → `features/signal_layer_v1.py` (22 finding(s))**

- why now: 22 mypy_types finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: annotate the single function the error names; do not restructure call sites
- kill criteria: kill if the annotation forces a runtime change, or if the error is in a vendored/legacy tree scheduled for deletion

**5. [P2] `ruff_quality` → `tests/test_a1_conformal_artifact_production.py` (22 finding(s))**

- why now: 22 ruff_quality finding(s) concentrated in one file — a bounded change, not a sweep
- smallest safe change: ruff --fix on THIS FILE only, then run the file's own test module; commit the autofix alone
- kill criteria: kill if the file has no test module, or if --fix touches money-path semantics (greeks, levels, decisions) rather than style

Machine-readable queue: `reports/tqm_queue_latest.json` · tally: `reports/advisory_debt_latest.json`

RE-MEASURE after acting: re-run this scan and confirm the delta moved. A win claimed in chat is not a win.

## Operator next

1. The operator triages this table in chat (recommend-only scan; no standing roles).
2. The operator green-lights one slice and assigns the session.
3. The assigned agent executes; verification per AGENTS.md.

Queue log: `reports/rehab_queue.jsonl`
