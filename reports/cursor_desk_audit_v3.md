# Cursor adversarial audit v3 — Claude post-v2 opens

**Auditor:** Cursor · **this turn** (do not trust Claude)  
**Authority:** `reports/cursor_desk_audit_v2.md` residuals (stale ESTIMATED comment; DOM badge under replay)  
**HEAD:** `6213b1e5` (worktree, `/api/build` this turn)  
**Mode:** find / measure / report — **no fix, no push, no commit, Decide untouched**  
**Console:** real `python -m uvicorn server:app --host 127.0.0.1 --port 8000` started for API+CDP probes, then stopped (`CONSOLE_DOWN_OK`).

**Reproduce:**
```text
python -m pytest tests/test_desk_store_v1.py tests/test_v2_desk_confidence_adapter.py -q --tb=line
# with console + headless Chrome --remote-debugging-port=9222 on /desk:
# CDP Runtime.evaluate against #dos-out / #str-out (live scrub=0, then scrub=-14d)
python -c "import time_et,datetime; d=datetime.date(2026,8,1)
while not time_et.is_trading_day_et(d.isoformat()):
 d+=datetime.timedelta(days=1)
print(d.isoformat(), d.strftime('%A'))"
```

**STATUS: PASS on the two v2 opens (stale ESTIMATED comment FIXED; rendered-DOM badge/refusal CLOSED on real :8000). Broader Desk ledger still PARTIAL only for parked RC-166 NEXT_RTH_PROOF 2026-08-03 Monday and OPEN RC-168 — not for these two guns. Not FAIL.**

---

## Admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — adversarial verify of Claude post-v2 claims |
| GAP | v2 left two opens; Claude claims both closed |
| SMALLEST_COMPLETE_CHANGE | This report only |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn read + pytest + live API + CDP DOM |
| DECISION_PATH_EFFECT | none |
| WHY_NOW | Operator ordered adversarial verify only |
| TASK_ADMISSION | ADMITTED — audit-only |

---

## Claim 1 — stale ESTIMATED comment at `desk_store.py:84`

| Check | Result |
|---|---|
| Read `desk_store.py` lines 82–86 | Comment now says capacity is **UNPROVEN (RC-180 F-04)**; explains assumption earns neither DERIVED nor ESTIMATED |
| Payload path | `capacity_usd` tier still `"UNPROVEN"` (line ~914); no stale ESTIMATED assignment on capacity |

**Verdict open #1: PASS / FIXED.**

---

## Claim 2 — DOM badge / refusal under knowledge-time slider

### Suite (exact)

`python -m pytest tests/test_desk_store_v1.py tests/test_v2_desk_confidence_adapter.py -q --tb=line` → **47 passed**, 1 warning, 24.60s · **0 failed**. Collect-only same turn: **47 tests collected**.

### API (real :8000, SPY)

| Probe | Result |
|---|---|
| Live dossier | `capacity_usd` ≈ $1.89B; `tiers.capacity_usd` = **UNPROVEN**; dist/POP tiers **UNPROVEN** |
| Past `as_of` = now−14d dossier | `spread=null`, `capacity_usd=null`; `missing` carries **EVENT-TIME ONLY** on effective_spread and daily_sigma/capacity |
| Past structure | `distribution.available=false`, `knowledge_replay_safe=false`, reason starts with **EVENT-TIME ONLY:** |

### CDP rendered DOM (headless Chrome → `/desk`)

| Surface | Result |
|---|---|
| Live Dossier `#dos-out` | `has_UNPROVEN_badge=true`; capacity line `Capacity at 25 bp impact $1.89B UNPROVEN`; lock `no lookahead · live` |
| −14d Dossier `#dos-out` | scrub=`-1209600`; lock `no lookahead · replay`; `has_EVENT_TIME=true` (count=2); fields show `not available` + EVENT-TIME ONLY in notes |
| −14d Structures `#str-out` | `refusal_in_dom=true`; text includes **Refused under replay.** + **EVENT-TIME ONLY:** (first-class DOM, not canvas-only); `canvas_only_would_miss=false` |

**Verdict open #2: PASS / CLOSED** (rendered path proven, not label-only).

---

## Ledger honesty

| Row | Status claimed | This-turn honesty |
|---|---|---|
| RC-180 | **PARTIAL** | Correct. DOM + F-04 comment closes named under this audit; PARTIAL remains because F-10/RC-166 mid-RTH contention is still parked. |
| RC-166 | **PARTIAL** | Correct — not falsely CLOSED. `# next-rth-ok: 2026-08-03 Monday` — `is_trading_day_et` from 2026-08-01 → **2026-08-03 Monday**. |
| RC-168 | **OPEN** | Correct — no fix claimed; volume blowups untouched. |

---

## Verdicts on the two opens

| Open (from v2) | Claude claim | Cursor verdict |
|---|---|---|
| Stale ESTIMATED comment `desk_store.py:84` | FIXED | **PASS** |
| DOM badge under −14d slider + live UNPROVEN + str-out refusal | CLOSED | **PASS** |

`CLAIM: both v2 opens PASS — comment UNPROVEN at desk_store.py:84; CDP #dos-out live UNPROVEN + −14d EVENT-TIME ONLY; #str-out Refused under replay; pytest 47 passed; RC-180/166/168 ledger honest · DONE: reports/cursor_desk_audit_v3.md · NEXT: NEXT_RTH_PROOF 2026-08-03 Monday for RC-166/F-10 · BLOCKER: none for these two opens`
