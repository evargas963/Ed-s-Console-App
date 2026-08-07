# Claude Finish Adversarial Audit v50 — RC-165 CLOSED stamp vs worktree/live (2026-07-31)

**Auditor:** Cursor (adversarial), 2026-07-31 ~12:14–12:20 CT  
**Target claims:** RC-165 CLOSED (terrain stale reason lying / delivered-cycle yardstick); recount 1166/38→1240/39→1359 via IESC; fix NOT LIVE (SHA `6c47b89b`, old 60s sentence); residual PARTIAL; combo forbidden; DB parked; Decide untouched; RC-163 trailing still OBSERVE.  
**Prior:** v49 residual PARTIAL; live SHA `6c47b89b`; accrual saw 1240/39.  
**Scope:** audit-only. **No commit. No console restart. No DB investigation** (operator).

**Admission preamble (AGENTS.md):** MISSION_CLASS=Collect (adversarial honesty audit) · GAP=same-turn verify RC-165 CLOSED reach vs worktree + live · SMALLEST_COMPLETE_CHANGE=`reports/claude_finish_adversarial_audit_v50.md` · MINIMUM_SUFFICIENT_EVIDENCE=`git diff server.py` + pytest 33 + `/api/build` + `/api/terrain?ticker=MSFT` · DECISION_PATH_EFFECT=none · WHY_NOW=Claude stamped RC-165 CLOSED while fix uncommitted/unrestarted · TASK_ADMISSION=audit only.

**drift-audit run:** phases 1–7 this turn. Findings below. Corrections: none applied (audit-only). Gate hardened: n (detector gap on non-hyphenated DOM ids noted).

---

## Verdict: RC-165 **PARTIAL** (CLOSED stamp **FAIL**) · residual **PARTIAL** · not live **CONFIRMED** · restart **not emergency**

| # | Claude claim | Auditor same-turn | Result |
|---|---|---|---|
| 1 | Recount 1166/38→1240/39→1359 = IESC joining ~12:38 ET | DB parked by operator; no COUNT this turn. Live `/api/terrain?ticker=IESC` returns a snapshot (spot 767.77) so IESC is on the terrain board — **not** proof of accrual join timing or the 1359 figure | **[UNVERIFIED]** recount causality; IESC-on-board only |
| 2 | RC-165 CLOSED: publish `_terrain_last_cycle_sec`; stale vs max(floor, 2×delivered); tests 33; relative ET fixtures | Worktree `server.py` + tests match the described fix; **33 passed** same-turn; fixtures use `datetime.now(ET).date()` (no hard-coded fixture day). **CLOSED stamp invalid** (see A) | Code/tests **PASS**; CLOSED **FAIL** |
| 3 | Fix NOT LIVE — process `6c47b89b`; MSFT still old "60s cadence" sentence | `/api/build` SHA `6c47b89bdcb4…`; MSFT reason still `…against a 60s cadence — the loop is inside its window but not producing` | **PASS** (Claude honest here) |
| 4 | Residual PARTIAL; combo forbidden; DB parked; nothing committed; Decide untouched | Working tree dirty on `server.py` / RC log / tests; HEAD still `6c47b89b`; admissions empty (covered by suite); no restart | **PASS** on meta |
| 5 | RC-163 trailing \| still OBSERVE | RC-163 **row** is CLOSED (lock). Residual evidence file still **STATUS: PARTIAL**. No "OBSERVE" token found in rc162 finish report this turn — claim is soft/ambiguous | **PARTIAL** / wording mush |

---

## A) RC-165 close-contract — CLOSED invalid for worktree-only

### Diff (PROVEN)

`git diff HEAD -- server.py`: **+28 / −3**. Three sites:

1. `terrain_staleness` — `stale_after = max(TERRAIN_STALE_AFTER_SEC, 2.0 * expected)` with `expected = max(TERRAIN_REFRESH_SEC, _terrain_last_cycle_sec|floor)`; reason string names **DELIVERED** cycle, retires "not producing" / "60s cadence".
2. Module global `_terrain_last_cycle_sec: float = 0.0`.
3. `_terrain_loop` — `globals()["_terrain_last_cycle_sec"] = float(elapsed)` after each cycle.

Substantive honesty fix (not a redesign disguised as hygiene): yardstick and sentence both move from sleep-floor fiction to delivered cycle. Floor retained so a fast loop cannot hide staleness. Pre-first-cycle falls back to nominal floor. That design is coherent.

### RC-165 row (quoted status + reach)

Status cell: **`CLOSED`**. Fix cell includes:

> FIXED: `server._terrain_last_cycle_sec` (new), `server._terrain_loop` (publishes it), `server.terrain_staleness` (threshold + reason). END-TO-END: `_terrain_loop` elapsed -> `_terrain_last_cycle_sec` -> `terrain_staleness` -> `/api/terrain` and `/api/terrain/strikes` levels_stale / levels_stale_reason -> `static/chart.html` `#gsrc` STALE/PAUSED/FAILING label.

**Close-contract gaps (AGENTS.md / RC-106):**

| Requirement | Present? | Evidence |
|---|---|---|
| `FIXED:` named victims | YES | server symbols enumerated |
| `END-TO-END:` | YES | producer→API→`#gsrc` |
| `VISIBLE_SURFACE:` for named DOM id | **NO** | `#gsrc` named; `VISIBLE_SURFACE:` absent (`HAS VISIBLE_SURFACE: False`) |
| Live operator victim repaired | **NO** | live still serves retired sentence (see C) |
| Committed / shipped | **NO** | uncommitted `M server.py` + RC log; process still prior SHA |

**Machine miss (not a clean bill):** `check_five_why_recursive_lock` returned **0** violations this turn because DOM-id regex is hyphen-requiring:

```text
#[a-z][a-z0-9]*(?:-[a-z0-9]+)+
```

So `#gsrc` (no hyphen) does not trigger the VISIBLE_SURFACE detector. Operator law still requires VISIBLE_SURFACE when a DOM id is named; the checker under-detects simple ids. Soft finding for lock hygiene — not Claude inventing a green gate, but CLOSED skating past detection.

**CLOSED while not live:** the named blast radius includes the live reason string the operator reads. That victim is **still broken on the running process**. A worktree + unit-test repair with an honest "await restart" note in chat does **not** license a CLOSED stamp. Correct status: **PARTIAL** until restart proves the new sentence and healthy ages clear STALE under the delivered yardstick.

Not redesign-as-honesty: the change is exactly the honesty defect (false "not producing"). Contaminant: stamping CLOSED before reach is live.

---

## B) Tests (PROVEN this turn)

```text
.venv\Scripts\python.exe -m pytest tests/test_chart_accrual_consumer_v1.py tests/test_scorecard_stale_fails_closed_v1.py -q
.................................                                        [100%]
33 passed, 1 warning in 10.56s
```

Hard-coded fixture dates: **none remaining.** `_ts_at` uses `datetime.now(ET).date()`. Remaining `2026-07-30` / `2026-07-31` strings are **comments / MEASURED narrative only**, not fixture pins.

Suite drives real `terrain_staleness` (156s delivered / 234s age → not stale; 400s → DELIVERED sentence; floor still binds; publish assert on `_terrain_loop` source). Not a substring-only green.

---

## C) Live probe — NOT LIVE (PROVEN)

| Probe | Result |
|---|---|
| `GET /api/build` `git_sha` / `startup_git_sha` | `6c47b89bdcb4daa75842a1edcc43205d454a3191` |
| `code_drift.repo_moved_past_process` | `false` (HEAD SHA matches process; dirty worktree not loaded) |
| `startup_git_dirty` | `true` (dirty at boot — still old code path) |
| MSFT `levels_stale` / `levels_age_sec` | `true` / **203.2** |
| MSFT `levels_stale_reason` | `levels are 203s old against a 60s cadence - the loop is inside its window but not producing` |
| SPY reason | same retired sentence (`226s` / `60s cadence`) |

Claude’s “await restart consent” is correct. **No emergency restart** from this audit: lying label is bad, but process is collecting; DB/contention parked; restart is operator consent, not auditor-forced.

Minor post-restart watch (not blocking this verdict): API still publishes `"stale_after_sec": TERRAIN_STALE_AFTER_SEC` (constant 180) while the real threshold is dynamic — residual honesty debt after live.

---

## D) IESC spot-check (cheap, no DB)

`GET /api/terrain?ticker=IESC`: snapshot present, spot **767.77**, age **2306.3s**, same **old** 60s-cadence stale sentence.

That shows IESC is enrolled / has been refreshed at least once this process life. It does **not** prove accrual `COUNT` jumped because IESC joined at ~12:38 ET, nor the **1359** figure. Those stay **[UNVERIFIED]** under the DB park.

---

## E) Lies / overclaims

1. **CLOSED without live reach** — primary lie-class. Chat correctly said not live; the RC stamp did not.
2. **Missing `VISIBLE_SURFACE:` for `#gsrc`** — close-contract breach; machine under-detects non-hyphenated ids.
3. Recount/IESC causality — not proven this turn; not labeled as lie because Claude’s number trail may be real and DB was correctly parked.
4. Not found: Decide influence, commit, combo ACCEPT, restart without consent.

---

## F) Residual status

- Chart/accrual residual evidence (`reports/claude_finish_rc162_chart_accrual_consumer.md`): still **STATUS: PARTIAL**.
- RC-165 honesty fix: **PARTIAL** (worktree+tests green; live red; CLOSED stamp reject).
- RC-163 **lock row** CLOSED; residual clock/paint criteria still open — do not confuse lock CLOSED with residual Done.
- Combo ACCEPT forbidden until live RC-165 proof + residual criteria; auditor agrees.

---

## G) STATUS line

`CLAIM:` RC-165 worktree fix + 33 tests real; CLOSED stamp invalid; live still `6c47b89b` + old 60s sentence · `DONE:` v50 audit artifact · `NEXT:` operator restart consent → re-probe MSFT/SPY reason for DELIVERED language; demote RC-165 to PARTIAL or add VISIBLE_SURFACE + live proof before re-CLOSE · `BLOCKER:` restart consent (not auditor-forced); DB parked

**Operator note:** restart needed for live honesty — **your call**. No emergency found.
