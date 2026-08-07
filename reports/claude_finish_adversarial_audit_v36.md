# Claude Finish Adversarial Audit v36 — RC-147…150 ticker closeout

**Target commits:** `12b0efc5` · `ba5ec77b` · `ec3b266a`  
**Auditor:** Cursor, 2026-07-30 ~12:10 ET  
**Claude claim:** SESSION_CLOSEOUT_GREEN — board fresh or honestly failing; $SPX recovered; RTY/XXT quarantined with reason on pixels.

---

## Verdict: **ACCEPT** closeout (goal met) · **PARTIAL** on “process == HEAD” and `/api/terrain` parity

| Claim | Result |
|---|---|
| Commits exist | **ACCEPT** — three SHAs on branch |
| $SPX recovered | **ACCEPT** — age ~41s, `basis=dte<=120`, vol ~1.9M, `failing=false` |
| RTY/XXT hard quarantine + gate burn stopped | **ACCEPT** — producer `kind=hard`, avoided fetches climbing |
| Chart DOM shows HTTP 400 / QUARANTINED (RC-150) | **ACCEPT** — rendered text has QUARANTINED + HTTP 400; no “activates at next console start”; `strikes===null` but `strikesMeta` carries reason |
| TSL untouched zero-vol | **ACCEPT** |
| 22 tests | **ACCEPT** this turn |
| Running process == HEAD `ec3b266a` | **PARTIAL** — `/api/build` reports running `ba5ec77b`, `repo_moved_past_process: true`. Chart RC-150 still works because static is served from disk at HEAD. Python identity is one restart behind. |
| `levels_failing` on every surface | **PARTIAL** — present on `/api/terrain/strikes` for RTY/XXT; **absent** on `/api/terrain` not-ready path (`failing=None`, reason only inside `error:` string) |

---

## Same-turn evidence

```text
git log: ec3b266a, ba5ec77b, 12b0efc5
/api/build: running ba5ec77b… · checked_out ec3b266a… · drift true
producer: quarantined RTY/XXT hard; last_error HTTP 400; avoided RTY=17 XXT=9
$SPX: age≈41s basis=dte<=120 failing=false vol≈1.94M n=199
matrix: 40 tickers; STALE_NOT_FAILING=0
Chart RTY DOM: hasQuarantined=true hasHttp400=true hasActivates=false
  strikesIsNull=true · strikesMeta.reason starts QUARANTINED…HTTP 400
pytest test_scorecard_stale_fails_closed_v1.py → 22 passed
```

---

## What earned ACCEPT

The failure class from the brief is closed on the operator-visible Chart path and on the producer:

1. Visibility (RC-147) + quarantine that stops retries (RC-148) — live.
2. Ladder advances on 502 condition + learner won’t poison from narrowed rung (RC-149) — `$SPX` back with stamped degraded basis.
3. Reason reaches pixels (RC-150) — Claude correctly caught their own labeling theater via DOM; Cursor re-confirmed.

Honest leftovers Claude named (in-memory quarantine rediscovery, `$SPX` on `dte<=120`, analytics latency) are OUT-OF-SCOPE for this closeout — acceptable if tracked.

---

## Residuals (do not reopen ACCEPT of the goal)

1. **Restart once** so `/api/build` matches `ec3b266a` (identity hygiene; Chart already has RC-150 from disk).
2. **`/api/terrain` not-ready path** still omits `levels_failing` / `levels_quarantined` / structured reason (only `error: terrain_not_ready…`). Chart is fine; any consumer of `/api/terrain` alone can still under-label. Optional RC child.
3. **NEXT-DEPTH** Claude named: remember last-good basis / re-probe full once per ET day — still open for full `$SPX` book.

---

`CLAIM:` closeout ACCEPT; process-drift + terrain-parity PARTIAL · `DONE:` audit v36 · `NEXT:` optional restart to clear drift · `BLOCKER:` none
