# Claude Finish Adversarial Audit v35 — RC-145 scope-to-commit

**Target commit:** `29a9d920`  
**Auditor:** Cursor, 2026-07-30 ~08:20 CT  
**Claude claim:** mypy debt scoped to `git ls-files`; 759→757; machine-local population removed; residual 8 unexplained; SESSION_CLOSEOUT_GREEN.

---

## Verdict: **ACCEPT** RC-145 (scope is part of the measurement) · **PARTIAL** on “readings at one commit are now comparable” — tracked-population gap remains

| Claim | Result |
|---|---|
| Findings outside `git ls-files "*.py"` dropped | **ACCEPT** — this turn: raw 751 → kept **749**, dropped exactly `timing_probe.py` / `timing_probe2.py` |
| Fail-closed when git cannot answer | **ACCEPT** — `tracked is not None` guard present; battery asserts it |
| Panel stamps scope + off-commit disk count | **ACCEPT** (see panel line) |
| Scratch probes removed from debt | **ACCEPT** — same two filenames Claude named |
| This removes machine-local population from the *reported* count | **ACCEPT** |
| Integers now reconcile across agents at one HEAD | **REJECT / residual** — Claude **757** vs this audit **749** after identical filter (Δ=8 on **tracked** paths) |
| Claude’s honesty that 751 is not retroactively explained | **ACCEPT** — still true; gap moved from 759–751 to 757–749 |

---

## Same-turn evidence

```text
git log -1: 29a9d920 RC-145…
pytest …negative_controls… → 26 passed

raw mypy errors:     751
after RC-145 filter: 749
dropped paths:       timing_probe.py, timing_probe2.py  (n=2)
off_commit findings in metric: 0
tracked .py (ls-files): 1134
mypy_interpreter: repo .venv

panel --check:
  tree: HEAD 29a9d920 · 0 dirty/untracked .py · 501 .py on disk outside the commit
  tools: mypy 2.3.0 · counted by …\.venv\… (repo .venv)
  scope: git-tracked .py only (RC-145)
  mypy_types 749 · BLOCKING CLEAN · health ok / 40 tickers
```

Interpretation aligned with Claude’s story on this machine: the only untracked contributors were the two timing probes (−2). Nested worktree files contributed **0** finding lines here (Claude’s disk had a larger untracked population; that is exactly the machine-local class RC-145 targets).

---

## What RC-145 gets right

Root diagnosis is correct: `mypy .` walks the disk; `git status` (even `-uall`) cannot see gitignored probes or registered nested worktrees; stamping a clean tree while counting foreign `.py` is RC-57 class fraud-by-omission.

Fix shape is correct for **attribution**: drop finding lines whose path ∉ tracked set; keep raw output if git fails (must not shrink toward clean).

Panel now states `scope: git-tracked .py only` and an off-commit disk count — operators can see population pressure even when status is clean.

---

## Residuals (do not reopen ACCEPT of the filter)

### R1 — Tracked-population Δ=8 still live
After the same filter, Claude reports **757**, this tree **749**. Both drops were −2 scratch probes. The remaining gap is inside the commit’s file set (or in analysis effects — R2), not in untracked finding attribution. Claude correctly refused to claim reconciliation.

### R2 — Analysis scope ≠ finding scope
`mypy .` still **analyzes** untracked trees; RC-145 only **filters reported paths**. Untracked modules can still change errors attributed to tracked files (import resolution, plugin side effects, duplicate module names). Stronger close: pass an explicit file list from `git ls-files` (or exclude `.claude/worktrees` / ignorefile in the mypy invocation) so the analysis population is the commit.

### R3 — Control softness
Fail-closed is asserted via `inspect.getsource` string presence, not a behavioral monkeypatch of `_tracked_py_files → None`. Adequate as a tripwire; not a fire drill.

---

## Framing

You were right to reject the integer; Claude found a worse defect than a stamp field and fixed the right layer (scope). That is ACCEPT. Comparability is improved but **not** achieved until the tracked Δ=8 is explained or analysis is pinned to `ls-files` as well.

`CLAIM:` RC-145 ACCEPT; cross-agent integer PARTIAL · `DONE:` audit v35 · `NEXT:` pin mypy analysis set to tracked files (optional) / chase Δ=8 · `BLOCKER:` none
