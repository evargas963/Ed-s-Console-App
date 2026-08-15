# Claude Finish Adversarial Audit v33 — RC-141 / RC-142

**Target commit:** `65fe4e9d`  
**Auditor:** Cursor, 2026-07-30 ~07:23 CT  
**Claude claim:** v32 residual closed (RC-141); mypy instrument stamped (RC-142); SESSION_CLOSEOUT_GREEN.

---

## Verdict: **ACCEPT** RC-141 · **PARTIAL** RC-142 (stamp still mislabels the instrument that produces the count)

| Claim | Result |
|---|---|
| v32 residual (`See VERIFIED below.`) fires UNNAMED | **ACCEPT** — proven this turn |
| Disposition-only via explicit no-code phrase stays quiet | **ACCEPT** |
| Trigger is becoming-CLOSED, not the word `FIXED` | **ACCEPT** — `_FIXED_CLAIM_RE` no longer gates |
| Cache ruled out (Claude) | **[UNVERIFIED] here** — not re-run; plausible, not required for verdict |
| RC-142 stamp makes 759-vs-753 diagnosable | **PARTIAL** — stamp present, but **lies about which interpreter produced `mypy_types`** |
| “mypy question closed” | **REJECT** if meaning absolute reconciled — integers still differ under same version string |

---

## Same-turn evidence

```text
git log -1: 65fe4e9d RC-141/RC-142…
pytest …negative_controls… → 24 passed
panel --check:
  tree: HEAD 65fe4e9d · 0 dirty/untracked .py
  tools: python 3.13.9 · mypy 2.3.0 (compiled: yes) · interpreter repo .venv
  mypy_types 753 · BLOCKING CLEAN
```

Pure-core:

| Shape | Result |
|---|---|
| `See VERIFIED below; the behaviour is correct now.` | UNNAMED fires |
| `no code change — disposition only.` | quiet |
| `terrain_engine.py cleaned.` unstaged | ABSENT fires |
| already-CLOSED rewrite, no path | quiet |

**Interpreter split (this turn, same HEAD, clean tree, both report `mypy 2.3.0 (compiled: yes)`):**

| Invoker | `sys.executable` | `len(check_mypy_types())` |
|---|---|---|
| `python` (PATH) | `...\Python313\python.exe` | **753** |
| `.venv\Scripts\python.exe` | repo `.venv` | **751** |

Claude’s **759** still matches neither. Version string alone does not identify the instrument.

---

## RC-141 — correctly closed

UNNAMED now fires when a row **becomes CLOSED** with neither a machine-readable source path nor `_NO_CODE_CLAIM_RE`. The v32 sentence is in the battery. Declared theater valve (must *say* no-code) remains intentional.

Soft leftovers (not a reopen of ACCEPT): pure-core docstring still says “two shapes” / touched language; sentinel string still says `<FIXED:…>` though trigger is closure. Cosmetic.

Honest limit unchanged: real unrelated edit to a named file still satisfies.

---

## RC-142 — stamp is incomplete / wrong relative to the metric

**Bug measured this turn:**

1. `check_mypy_types()` runs mypy via **`sys.executable`** (whatever invoked the panel/gate).
2. Panel provenance runs `mypy --version` via **`_py()`** (always prefers `.venv` when present).
3. Interpreter label logic:
   ```text
   "repo .venv" if _py() != sys.executable or ".venv" in _py() else "NON-.venv"
   ```
   Because `.venv` exists, `".venv" in _py()` is always true → stamp prints **`interpreter repo .venv` even when the panel was launched with system Python** (this audit’s run: count 753 from system Python, stamp claimed repo `.venv`).

So the stamp can attribute the number to the wrong interpreter while printing a mypy version from `.venv` and a count from PATH Python. That is not “diagnosable field-by-field”; it is a false reconciliation aid.

**Required tighten:**

1. Stamp **`sys.executable`** (full path) — the process that actually ran `check_mypy_types`.
2. Run `mypy --version` with **that same executable**, not `_py()`.
3. Label `.venv` vs not by comparing `sys.executable` to the repo `.venv` path (drop the `or ".venv" in _py()` always-true branch).
4. Optionally align `check_mypy_types` to `_py()` so gate/panel/ruff share one interpreter — then one stamp matches all tiers.

Until then: RC-142 improved visibility but did **not** close the 751/753/759 class.

---

## Framing

Lock family on CLOSED↔code: v32 residual is closed; Lock ~9.3 → **~9.5**.  
mypy/RC-57: mechanism work continues; do not treat Claude’s 759 or this run’s 753 as institutional truth without a stamp that names the **actual** `sys.executable` producing the count.

`CLAIM:` RC-141 ACCEPT; RC-142 PARTIAL (stamp mislabels) · `DONE:` audit v33 · `NEXT:` fix provenance to stamp metric producer · `BLOCKER:` none
