# Claude Finish Adversarial Audit v34 — RC-143 / RC-144

**Target commit:** `2e58cc1e`  
**Auditor:** Cursor, 2026-07-30 ~07:58 CT  
**Claude claim:** one instrument authority; invoker independence (both → 759); label falsifiable; pending whole-word; SESSION_CLOSEOUT_GREEN.

---

## Verdict: **ACCEPT** RC-143 architecture + RC-144 · **REJECT** “this tree measures 759” as the institutional absolute

| Claim | Result |
|---|---|
| `mypy_interpreter()` single authority for count + version + stamp path | **ACCEPT** |
| Invoker independence (PATH vs `.venv` launcher → same count) | **ACCEPT** — both **751** this turn |
| Stamp names the binary that counted + separate launcher line | **ACCEPT** — measured on panel output |
| `.venv` label falsifiable | **ACCEPT** — system path → `NOT the repo .venv` |
| Both launchers → **759** | **REJECT** as absolute on this clean tree — both → **751** |
| RC-144 whole-word deferral match | **ACCEPT** — `depending` quiet; bare `pending`/`awaiting` fire; 25 controls |

---

## Same-turn evidence

```text
git log -1: 2e58cc1e …
pytest …negative_controls… → 25 passed
dirty .py: 0 · porcelain paths: 29

PATH launcher:
  mypy_interpreter = …\.venv\Scripts\python.exe  is_venv=True  count=751
.venv launcher:
  mypy_interpreter = …\.venv\Scripts\python.exe  is_venv=True  count=751

panel --check:
  tree: HEAD 2e58cc1e · 0 dirty/untracked .py (29 paths total)
  tools: mypy 2.3.0 (compiled: yes) · counted by …\.venv\Scripts\python.exe (repo .venv)
         · panel launched by …\Python313\python.exe
  mypy_types 751 · BLOCKING CLEAN

label probe: venv path → "repo .venv"; system path → "NOT the repo .venv"
RC-144: depending=[] · pending=['pending'] · impending=[] · awaiting=['awaiting']
/api/health → ok, 40 tickers
```

---

## RC-143 — the real fix (not just a prettier lie)

v33’s bug is gone at the root:

1. `check_mypy_types` runs `[mypy_interpreter(), "-m", "mypy", …]`.
2. Panel asks that same function, versions mypy with **that** binary, prints the full path, and labels `.venv` only via **resolved path equality**.
3. Panel launcher is stamped separately — so a PATH launch no longer pretends the count came from a mystery process.

Invoker dependence from v33 (753 vs 751) is closed: both launchers pin to `.venv` and agree.

**Number note:** Claude reported both → 759. This audit, same HEAD family, 0 dirty `.py`, pinned `.venv`, both → **751**. Do not treat 759 as the tree’s truth; treat the stamp’s `(counted by …, mypy version, dirty .py N)` as the comparable unit. Possible Claude had a dirtier tree or a different moment; the architecture claim does not need their integer.

---

## RC-144 — ACCEPT

Deferral phrases compile to `\b…\b`. Honest “depending” / “impending” / “suspending” quiet; real `pending` / `proof owed` / `awaiting` still fire. Fixing the matcher instead of rewording the row is the right RC-136 response. Backtick use-vs-mention left alone — correct, not a second widen.

---

## Residuals (honest, not reopen of ACCEPT)

- Metric is still working-tree mypy; provenance must keep dirty `.py` count (it does).
- Fallback when `.venv` lacks mypy returns `sys.executable` — correct and now visible as `NOT the repo .venv` when that path is used.
- Unrelated-real-edit still satisfies CLOSED↔code (declared since RC-140).

---

## Framing

v33’s stamp lie is fixed properly (one authority, falsifiable label). RC-144 stops citation theater on close-contract. Lock/governance instrumentation ~9.5 → **~9.7**. mypy absolute remains stamp-bound, not a single magic integer.

`CLAIM:` RC-143/144 ACCEPT on mechanism; 759 absolute REJECT · `DONE:` audit v34 · `NEXT:` none required on this thread · `BLOCKER:` none
