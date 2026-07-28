# BRUTAL ADVERSARIAL AUDIT v4 — Claude "finished" (2026-07-27 ~20:59 CT)

**Commit under review:** `9d67ff27`  
**Verdict (scoped):** **ACCEPT lock-set / scorecard / phantom closure — with named leftovers.**  
**Verdict (repo-wide / "everything done"):** **REJECT.**

---

## What "finished" can honestly mean

| Scope | Status |
|---|---|
| Tracked lock-failure set (35 RCs) | **ALL_FIXED** — monitor `closed=35/35` |
| Scorecard producer (RC-70/97) + ET age (RC-98) | **FIXED(verified)** this turn |
| Phantom RC citations (RC-96/99) | **FIXED(verified)** — `rc_citations_resolve` 0 |
| RC-12 span adequacy | **FIXED(verified)** — SPY span math ~±6.09%; row cites 0/11 under ±5% |
| RC-43 status/text | **FIXED(verified)** — CLOSED reconciled |
| Entire repo pristine / all OPEN debt | **NOT DONE** |

Claude's own commit honestly says: **"The coach is NOT fixed"** (thin `call_n=1`, `put_n=2`). That honesty is correct — do not let a finish claim overwrite it.

---

## Verified this turn (same-turn evidence)

- Scorecard API: `stale=false`, `age_trading_days=0`, `generated_utc=2026-07-28T01:29:56+00:00`
- Evening UTC age: `scorecard_trading_day_age('…T01:19:43+00:00')` → **0**
- Task `\EdTerrainScorecard` → bat; Last Result historically **0**
- Checks: `rc_citations_resolve` 0, `scheduled_producers_are_not_inert` 0, `agents_laws_name_their_enforcer` 0, `root_cause_log` 0
- Tests: `test_scorecard_stale_fails_closed_v1` + negative-controls → **16 passed**
- `required_strike_count(738.65,1.0)` → need 90 → span **6.09%**

---

## Still OPEN — finish is incomplete if claimed globally

| RC | Status | Reality |
|---|---|---|
| **RC-31** | OPEN | Fix cell: **NOT FIXED** — overnight bleed into TCN/HAR/Kalman |
| **RC-58** | OPEN | Fix cell: **PARTIALLY FIXED** — remaining study contamination set |
| **RC-100** | OPEN | Dead-code Wave-A orphans from Cursor audit — fix cell stub `tools/` only |

Also: **RC-55 REMEDIATED** with fix text starting **REFUTED** — ledger weirdness, not a clean CLOSED.

---

## Residual risk Claude named (do not forget)

1. **Coach sample thin** — producer live ≠ useful hold-rates (`call_n=1`, `put_n=2`).
2. **RC-12 NEXT-DEPTH** — unseeded tickers still fall back to fixed **40** for one cycle.
3. **Staged/uncommitted leftovers** — `AGENTS.md` + scorecard report artifacts still dirty vs HEAD in working tree; commit landed core code, not a fully clean tree.
4. **Wave-1 pristine backlog untouched** — dual spot clocks, dual wall books, Cursor-unbound hooks, hidden UI painters (`reports/repo_wide_adversarial_audit_wave1.json`). Saying "finished" does **not** clear that program.

---

## Paste to Claude / operator one-liner

```
SCOPED ACCEPT: lock-set 35/35 + scorecard producer + phantom RC lock + RC-12 spans
are FIXED(verified) on commit 9d67ff27. Honest limit stands: coach numbers are thin.

GLOBAL REJECT if you meant "all done": RC-31 NOT FIXED, RC-58 PARTIAL, RC-100 OPEN
(orphan delete wave), and Wave-1 money-path/UI dual-faucet backlog is untouched.
```
