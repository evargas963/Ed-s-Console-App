# ADVERSARIAL AUDIT v20 — P0b burn @ `994c7348` — 2026-07-28 ~19:20 CT

**HEAD:** `994c7348` — `RC-121/122 CLOSED: P0b burn — quote provenance travels, one wall book on screen.`  
**Operator pick:** P0b (C4 + C1)  
**Verdict:** **ACCEPT P0b burned** for both named guns · **PARTIAL** on “airtight forever” (placement still the fix for C1; restart required for screen) · Decide / LP-01 / RC-6 unchanged

---

## Charter

MISSION_CLASS: Find & Prove (verify burn) · GAP: Claude P0b claim vs code · EVIDENCE: file:line + 5/5 lock tests · DECISION_PATH: none · WHY_NOW: operator pasted finish · TASK_ADMISSION: audit

---

## Shipped (`994c7348`, 6 files, +121)

`server.py`, `live_market_plane.py`, `tests/test_spot_authority_v1.py`, `tests/test_levels_single_producer_v1.py`, RC log, error log (E-34).

---

## C4 / RC-121 — ACCEPT

| Check | Grade | Proof |
|---|---|---|
| Carry-forward records plane | **FIXED** | `_stale_fast_quote_carried_forward` calls `record_quote` `:3020` — covers all return sites including `:12189/:12203` |
| QSD in Tier C merge | **FIXED** | `live_market_plane.py:248` |
| QSD in L1 overlay | **FIXED** | `:290` |
| Tests | **FIXED** | `test_carried_forward…` + `test_plane_merges_carry_the_quote_provenance` **passed** this turn |

Note: `_fetch_state` still builds an analytics QSD at `:8511`; `merge_into_state` at `:9258` (end) overlays plane provenance after — order OK.

---

## C1 / RC-122 — ACCEPT (screen path)

| Check | Grade | Proof |
|---|---|---|
| Overlay function | **FIXED** | `_terrain_kl_overlay` `:10482-10507` — gamma family from terrain or blank + `kl_levels_source`; strengths `—` |
| Both kl producers call it after writes | **FIXED** | partial shell `:2684`; full `_fetch_state` `:8669` (comment documents prior silent overwrite) |
| Stale/absent → no narrow book | **FIXED** | tests blank keys; **3/3 passed** |
| Delta/OI/vanna stay analytics | **ACCEPT scope** | terrain doesn’t compute them — not dual gamma books |

Residual (honest): lock is **placement + unit tests on the helper**, not an AST “every kl_* write followed by overlay” gate. A future insert of kl writes after `:8669` could reopen the dual book — same class Claude already hit once.

---

## Same-turn tests

```
5 passed  (2× C4 + 3× C1 overlay)
```

---

## Board after P0b

| Item | Status |
|---|---|
| W3-C4 | **FIXED** (needs server restart for live screen) |
| W3-C1 gamma dual book | **FIXED** (restart) |
| Decide `!tradeable` pills | **OUTSTANDING** — next burn per sequencing |
| LP-01 | **NEXT** (Operator NOW after Decide if you keep that order) |
| RC-6 drop | still owed before Aug 9 |
| E-34 EM dual method | logged, not burned |

---

## Score nudge (seed)

Trust / Collect / Structure each **+~1** vs pre-P0b 6/10 overall → ~**7/10** once restart proves on screen. Decide still caps Decide-safety at 3 until that burn.

---

`CLAIM: ACCEPT P0b @994c7348 — C4+C1 FIXED + 5/5 locks; restart for screen; Decide next · DONE: v20 · NEXT: operator Decide | RC-6 drop · BLOCKER: none`
