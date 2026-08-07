# Claude Finish Adversarial Audit v31 — RC-139 / v30 escape close

**Target commit:** `e0b961ca`  
**Auditor:** Cursor, 2026-07-29 ~21:52 CT  
**Claude claim:** v30 escape closed; positive invariant; 23 controls; live-fire A/B/C; mypy 759 reconciled; SESSION_CLOSEOUT_GREEN.

---

## Verdict: **ACCEPT** that v30’s escape is closed · **REJECT** “class airtight / Lock = 10” · wording escapes still sail through

| Claim | Result |
|---|---|
| v30 clean-tree ABSENT shape blocked | **ACCEPT** — proven this turn |
| Unrelated SHA cannot launder | **ACCEPT** — unit + Claude’s live-fire C shape covered in pure core |
| Already-closed text edit exempt | **ACCEPT** — tested |
| “No semantic escape remains” | **REJECT** — three wording/scope escapes measured below |
| mypy 759 is the panel truth | **PARTIAL** — this turn panel + gate both read **753**; 751/759/753 are run-variance (RC-57), not a session regression proof |

---

## Same-turn evidence

```text
git log -1: e0b961ca RC-139…
pytest tests/test_enforced_check_negative_controls_v1.py -q → 23 passed
code_health_panel.py --check → BLOCKING CLEAN; mypy_types 753; orphan 164; ruff_wide_net 12841; complexity 472
/api/health → ok, logger_tickers 40
```

Pure-core probes (`_closed_row_code_not_shipped`) this turn:

| Probe | Result | Meaning |
|---|---|---|
| Newly CLOSED, clean, unstaged, no SHA | `[(RC-999, [terrain_engine.py])]` | v30 escape **closed** |
| Cite SHA + `sha_touches=True` (any touch) | `[]` | quiet — **content-blind** |
| FIXED prose, no `.py/.html/.js` token | `[]` | quiet — **wording escape** |
| FIXED names only `.ts` / `.css` | `[]` | quiet — **extension scope** |
| Named file staged (even whitespace) | `[]` | quiet — **change theater** |

---

## What RC-139 actually locks (positively stated — good)

A row **becoming** CLOSED must, for every `.py/.html/.js` token found in the fix cell body:

1. have that path in this commit’s staged files, **or**
2. cite a SHA that `git show --name-only` lists as touching that path,

and must not leave that path dirty.

That kills: dirty uncommitted fix (RC-134) **and** clean tree with never-written/reverted fix (v30). Claude updated the old “clean ⇒ quiet” control instead of deleting it. That part is honest.

---

## Residuals that still get through mechanical locks (operator: do not let semantics win)

These are **not** deferred niceties. They are paths where wording or scope still outruns the invariant “CLOSED means the fix is present.”

### R1 — Omit machine-readable paths (wording)
`_FIXED_SOURCE_FILE_RE` only matches `\.(py|html|js)`.  
`FIXED: deleted the hvl twin in the terrain engine.` → **no fire**.  
A CLOSED row with no path tokens ships with zero code binding.

### R2 — Wrong extension / non-JS frontend
`FIXED: static/app.ts, styles.css` → **no fire**.  
If a close names only those, the lock never engages.

### R3 — Content-blind SHA / staged touch
Any commit that *touched* the path (whitespace, unrelated edit, pre-bug history) satisfies `sha_touches`.  
Staging a no-op change to the named file also satisfies.  
Touched ≠ contains the fix. This is weaker than the prose claim “backed by shipped code.”

### R4 — Stale check docstring (soft, governance drift)
`check_closed_rows_ship_their_code`’s public docstring still describes only the **dirty** rule. The ABSENT rule lives in the pure-core docstring. Next agent reading the registered check can re-implement the incomplete contract.

### R5 — mypy number theater (RC-57 class)
Same tree, same evening: Cursor panel read **751**, Claude claimed **759**, this audit reads **753**.  
Claude correctly showed session files contribute ~0 findings; incorrectly treated 759 as a stable “panel truth.” Do not close a metric-trust question by picking one run’s integer.

---

## Required tighten (hand back to implementer — not optional if Lock → 10)

1. **Path required on newly CLOSED rows that claim FIXED:** if status→CLOSED and the fix cell contains `FIXED:` (or equivalent), at least one `.py/.html/.js/.ts/.css` path token must appear — else fire (`NO_FIXED_PATH`).
2. **Widen extension set** to match the frontend continuum the mandate covers (at least `.ts`, `.css`; SQL if ledger closes name `.sql`).
3. **Keep content-blind SHA as known limit** *or* require SHA citation only when the named path is also present on `HEAD` *and* the row’s VERIFIED cell still carries a same-turn command — do not pretend touch==fix. If left as-is, ledger must say `OUT-OF-SCOPE: content proof` with a tracker, not “invariant closed.”
4. Refresh the registered check’s docstring to the positive invariant (DIRTY + ABSENT).
5. For mypy: stop asserting a single absolute; cite `panel --check` same-turn and treat ±N run noise as unresolved until a reproducibility note lands (or pin the panel’s invocation).

Fire+quiet controls required for R1/R2 before claiming class closed.

---

## Framing

Claude did the right thing on the **named** residual from v30 — same turn, positive invariant, battery updated, live-fire shapes A/B/C match the pure core. That is ACCEPT for “v30 escape closed.”

Claude did **not** earn “nothing semantic gets through.” Path-omission and extension gaps are exactly the class of wording escapes the operator forbade. Lock stays **~9.0**, not 10, until R1–R2 are locked (R3 declared honestly or tightened).

`CLAIM:` v30 escape ACCEPT; wording/scope escapes REJECT as closed · `DONE:` audit v31 · `NEXT:` R1–R2 lock (+ docstring) · `BLOCKER:` none
