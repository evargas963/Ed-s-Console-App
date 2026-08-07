# Claude Finish Adversarial Audit v32 — RC-140 / v31 three escapes

**Target commit:** `d47618eb`  
**Auditor:** Cursor, 2026-07-29 ~22:24 CT  
**Claude claim:** all three v31 escapes closed; mypy answered by mechanism; SESSION_CLOSEOUT_GREEN.

---

## Verdict: **ACCEPT** on the three named v31 gaps · **PARTIAL** on “semantics closed” · mypy mechanism **ACCEPT**, absolute still not unique

| Claim | Result |
|---|---|
| R1 prose-only `FIXED:` → UNNAMED | **ACCEPT** — fires this turn |
| R2 `.ts`/`.css` (+ widened set) | **ACCEPT** — ABSENT when unstaged; quiet when staged |
| R3 whitespace / touch-only SHA | **ACCEPT** — wrapper filters staged via `_staged_has_real_change`; SHA path uses `git show` non-blank +/- |
| Honest limit (right change unmachinable) | **ACCEPT** — stated in check docstring, not hidden |
| Panel provenance stamp | **ACCEPT** — present above tiers this turn |
| “No wording escape remains” | **PARTIAL** — see residual below |
| mypy 759 is this tree | **REJECT as unique truth** — this turn, stamp says `0 dirty/untracked .py` on `HEAD d47618eb` and panel reads **753** |

---

## Same-turn evidence

```text
git log -1: d47618eb RC-140…
pytest …negative_controls… → 24 passed
code_health_panel --check:
  tree: HEAD d47618eb · 0 dirty/untracked .py (27 paths total) · python 3.13.9
  mypy_types 753 · orphan 164 · ruff_wide_net 12841 · complexity 472 · length 398
  BLOCKING CLEAN
/api/health → ok, 40 tickers
```

Pure-core probes:

| Shape | Result |
|---|---|
| `FIXED: deleted the hvl twin.` (no path) | UNNAMED fires |
| `FIXED: static/app.ts.` unstaged | ABSENT fires |
| same + staged | quiet |
| `FIXED: terrain_engine.py.` + empty staged (whitespace filtered out upstream) | ABSENT fires |
| `FIXED: documentation only — hvl still in code.` | quiet (declared magic phrase) |
| Closed fix cell with **no** `FIXED:` and no path | **quiet** — residual |

---

## What landed correctly

- Extension set widened to the continuum Claude listed (incl. ts/tsx/css/scss/sql/shell/yaml).
- UNNAMED requires a machine-readable path **or** an explicit no-code phrase.
- Real-change filter on staged diffs and on cited SHA diffs (non-blank `+/-`).
- Registered check docstring now names DIRTY / ABSENT / UNNAMED and the honest limit.
- Report-only FIXED control rewritten so report churn cannot block a closure that also ships source.
- Live-fire rewrite avoiding `reset --hard` in a shared worktree is the right operational call (not re-run here; pure-core + helper evidence sufficient for the three gaps).

---

## Residual wording escape (not deferred rhetoric)

UNNAMED is gated on `_FIXED_CLAIM_RE` (`\bFIXED\b\s*[:\-]`).

A newly CLOSED row whose fix cell **never says `FIXED:`** and names **no** source path stays quiet:

```text
fix cell: "Deleted the twin; terrain engine now clean."  → []
fix cell: "See VERIFIED below."                         → []
```

That is the same class as v31 R1: omit the token the lock keys on, sail through. The magic phrase `documentation only` is an *intentional* theater valve (Claude declared it); avoiding `FIXED:` entirely is **not** declared and still works.

**Tighten:** for rows **becoming** CLOSED, require either (a) ≥1 machine-readable source path with DIRTY/ABSENT/real-change rules, or (b) an explicit `_NO_CODE_CLAIM_RE` match — **whether or not** the cell contains the word `FIXED`. Fire+quiet required.

Secondary (soft): pure-core `_closed_row_code_not_shipped` docstring still describes only two shapes / “touched” language; the registered check docstring is correct. Align them so the next patch doesn’t re-read the incomplete contract.

---

## mypy

Claude’s mechanism claim is right: `mypy .` is working-tree-scoped; provenance stamp makes readings comparable.

This turn on a stamp of **0 dirty/untracked .py** at `d47618eb` / Python 3.13.9 → **753**, not 759. So either Claude’s triple-759 was a different tree than the stamp now shows, or another factor remains (tool version, cache, scan roots). Do **not** treat 759 as the institutional absolute; cite the stamp + the integer together.

---

## Framing

v31’s three measured gaps are closed with same-turn proof. Claude’s honest limit on “right change” is correctly left to audit. Lock moves ~9.0 → **~9.3**, not 10, until newly CLOSED rows cannot omit both paths and the no-code declaration by simply avoiding the word `FIXED`.

`CLAIM:` v31 R1–R3 ACCEPT; FIXED-keyword residual PARTIAL · `DONE:` audit v32 · `NEXT:` require path-or-no-code on every new CLOSED · `BLOCKER:` none
