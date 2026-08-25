---
description: Run the Code Health Panel (BLOCKING / TRACKED / FROZEN) and drive the quality circle
allowed-tools: Bash(*), Read, Edit, Glob
---

# Code Health Panel + Quality Circle

Run the standing static-quality scoreboard, then work the quality circle on whatever it finds:
**identify → fix → audit → fix → audit**, until BLOCKING is clean.

## Step 1 — Identify

Run the panel using the mandated interpreter (`.venv`, per `check_venv_parity`):

```bash
.venv/Scripts/python.exe tools/code_health_panel.py
```

Read the three tiers exactly as they are defined — this triage is the whole point:

- **BLOCKING** — the project's OWN ruff correctness rules (F-rules: unused variables,
  redefinitions, undefined names, duplicate dict keys). These are **defects**. Target **0**.
- **TRACKED** — `mypy_types`, `orphan_dict_keys`. Real debt, driven down incrementally.
  A **rise is a regression** and must be explained.
- **FROZEN** — the gate's wider ruff net, `function_complexity`, `function_length`,
  `file_length`. Watched for **runaway growth only**. **Never drive these to zero** — RC-19
  recorded that chasing a file-length ceiling forced five circular imports to save seven lines.

## Step 2 — Fix (BLOCKING first, safely)

Never mass-apply `--unsafe-fixes`. Use the transformation that provably preserves behaviour:

| Case | Safe transformation |
|---|---|
| Unused local, RHS is a **pure expression** | delete the line |
| Unused local, RHS is a **function call** | keep the call, drop the binding (`x = f()` → `f()`) |
| **Tuple unpack** where only one target is unused | rename that target to `_name` — never delete the line |
| Anything ambiguous or on the money path | rename to `_name`; do **not** delete |

**Hard-won lesson (RC-64):** deleting `orb_h, orb_l = ...` because `orb_h` was unused also killed
`orb_l`, which WAS used — in money-path `liquidity_value_engine.py`. Ruff's own "unsafe fix" does
the same thing silently. Renaming is always safe; deleting is not.

After every batch, `ast.parse` each file **before** writing it.

## Step 3 — Audit (mandatory, not optional)

```bash
.venv/Scripts/python.exe -m ruff check . --select F --statistics
.venv/Scripts/python.exe -m compileall -q . -x "\.venv|\.git|node_modules|__pycache__|\.mypy_cache"
```

Then confirm the app and money path still import:

```bash
.venv/Scripts/python.exe -c "import os; os.environ['PYTEST_CURRENT_TEST']='boot'; import server, call_engine, rules_engine, bayesian_fusion, liquidity_value_engine; print('money path imports OK')"
```

If a fix introduced an `F821 undefined-name`, restore the file's HEAD content rather than patching
blind — a cosmetic warning is never worth a money-path regression. Recovery must be guard-legal:
read the content with `git show HEAD:<file>` (read-only) and write it back with the Write tool.
The destructive-git verb class (`reset` / `restore` / `checkout --` / shell redirects into `.py`)
is blocked by LOCK-2 and must not be attempted.

## Step 4 — Loop

Re-run Step 1. If BLOCKING is not 0, repeat 2–3. When BLOCKING is clean:

```bash
.venv/Scripts/python.exe tools/code_health_panel.py --check
```

`--check` exits non-zero on any BLOCKING defect **and** on an unmeasurable count — a metric that
cannot be measured is never reported as a pass (RC-57: the gate once reported ~1,900 findings as
zero because ruff was missing from the mandated interpreter).

## Step 5 — Report

State the before → after per tier, name what was fixed vs deliberately left, and run the affected
tests. Do not claim green without pasting the command output from this same run.
