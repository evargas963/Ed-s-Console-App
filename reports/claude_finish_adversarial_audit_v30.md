# Claude Finish Adversarial Audit v30 — Lock hardening walk-away

**Target commits:** `1a384d0b` (RC-134) · `26dabafd` (RC-136/137) · `abb31193` (RC-138) · `1a04140f` (v29 receipt)  
**Auditor:** Cursor, 2026-07-29 ~21:25 CT  
**Claude claim:** items 1–4 DONE; SESSION_CLOSEOUT_GREEN; BLOCKER none.

---

## Verdict: **ACCEPT** goal items · **PARTIAL** on “Lock = airtight / class fully closed”

| Item | Result |
|---|---|
| (1) RC-134 on committed tree | **ACCEPT** — HEAD `to_dict` has no `hvl`; live wire no `hvl` key; source tree clean of RC-134 files |
| (2) RC-136 curl/urllib allowlist | **ACCEPT** — `_RC_CITATION_RE` includes `curl `, `urllib`, localhost probes; 22 battery passed this turn |
| (3) RC-137 CLOSED-ships-code | **ACCEPT** for the **observed** defect (CLOSED + dirty FIXED files) · **PARTIAL** as a full class lock (see escape) |
| (4) code-health | **ACCEPT** — `--check` OK, BLOCKING clean this turn |
| FROZEN attribution cleanup (RC-138) | **ACCEPT** as honest hygiene; not a Lock-10 claim |
| “Lock/enforcement is done / 10” | **REJECT** if implied — residual escape below |

---

## Same-turn evidence

```text
git log: abb31193, 26dabafd, 1a384d0b present
git status: no dirty .py source (reports churn only)
TerrainSnapshot.to_dict / unavailable path: 'hvl' not in dict; no attr
pytest test_enforced_check_negative_controls_v1.py → 22 passed
code_health_panel.py --check → [OK] No BLOCKING defects
/api/terrain?ticker=SPY → 'hvl' not in payload
```

---

## Residual escape (RC-137) — does not reopen ACCEPT of the observed fix

`check_closed_rows_ship_their_code` blocks when named FIXED sources are **dirty**.

It does **not** require that named FIXED sources appear in the **same commit’s tree diff**.

Escape (worktree clean, HEAD still broken):
1. Write CLOSED row naming `foo.py`
2. Leave `foo.py` unmodified (or revert it to HEAD)
3. Commit only the ledger → files are not dirty → check stays quiet → ledger claims CLOSED while HEAD still has the defect

That is a different shape than RC-134 (which was CLOSED + dirty uncommitted fix). Claude’s lock correctly kills the shape that bit the operator; it does not yet kill “CLOSED with zero code change.”

**Tighten later (optional):** for CLOSED rows staged in the commit, every named `.py/.html/.js` FIXED path must appear in `git diff --cached --name-only` (or be proven already present on HEAD via a content assertion). Fire+quiet required.

---

## Framing
Walk-away goal met. Git matches console on RC-134. Citation theater reduced. The dirty-file CLOSED lie is locked. Lock dimension moves ~8.5 → **~9.0**, not 10, until the clean-worktree CLOSED escape is closed.

`CLAIM:` items 1–4 ACCEPT; RC-137 class PARTIAL · `DONE:` audit v30 · `NEXT:` optional RC-137 tighten, or resume score climb · `BLOCKER:` none
