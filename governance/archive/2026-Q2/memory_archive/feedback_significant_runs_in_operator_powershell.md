> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: Significant runs happen in operator's PowerShell
description: Neither Claude nor Cursor executes pytest, migration tools, schedulers, model training, DB writes, or other significant runs. Operator runs them in PowerShell and shares output for verification.
type: feedback
originSessionId: b724fbb2-9fd1-49e3-a3a2-f6ee89a57d27
---
ANY significant run — pytest suites, migration tools (even against temp DBs), schedulers, model training, live DB writes, anything that produces meaningful side effects or non-trivial execution time — happens in the operator's PowerShell, not inside a Claude or Cursor session.

**Why:** Operator has a dedicated PowerShell environment for running tests/migrations/etc. and wants to keep agent sessions focused on code + verification + research. Agent-side execution risks: stale environment, partial output truncation, hidden side effects, no operator visibility into runtime.

**How to apply:**
- Cursor writes code + tests + tools. Cursor does NOT run pytest, migration scripts, or any tool against a real or temp DB.
- Claude does Read-based verification (file content citation). Claude does NOT run pytest or tools either.
- Inspection commands (`git log`, `git diff`, `git ls-remote`, `git status`, `git show`, `Read` tool) are fine — they're read-only.
- When test results are needed, operator runs in PowerShell and pastes/shares the output; Claude verifies the output against the test code.
- D-style migration scope examples: D1 commits the tool + test file. Operator runs `pytest` in PowerShell. Operator runs `--apply` against real DB. Claude verifies via Read + audit JSON inspection.

When in doubt: do not execute. Ask or defer to operator's PowerShell.
