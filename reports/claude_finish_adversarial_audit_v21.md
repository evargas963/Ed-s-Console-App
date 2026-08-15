# BRUTAL ADVERSARIAL AUDIT v21 — 2026-07-28 ~19:35 CT

**HEAD:** `ba032b77` — `RC-123 CLOSED: the cross-tab ticker is back — one carrier, every path, proven journey.`  
**Scope:** Full audit process on Claude’s RC-123 finish claim + standing board  
**Method:** claim inventory → file:line guns → escape probes → suite → board  
**Verdict:** **PARTIAL ACCEPT** RC-123 (real carrier + ordering lock) · **REJECT** “every path / proven journey” as airtight · Decide / LP-01 / RC-6 still open

---

## Charter

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — adversarial verification |
| GAP | Claude RC-123 finish vs escapes + durable proof |
| SMALLEST_COMPLETE_CHANGE | This report |
| MINIMUM_SUFFICIENT_EVIDENCE | Source + pytest + missing-artifact check |
| DECISION_PATH_EFFECT | none |
| WHY_NOW | Operator: go through audit process |
| TASK_ADMISSION | audit only |

---

## What Claude shipped (`ba032b77`, 4 files, +71/−1)

| Path | Intent |
|---|---|
| `static/index.html` | Inline adopt; `fetchState` persist; cv2 `commitTicker` write; storage listener |
| `static/chart.html` | Adopt before load; write on `change`; storage listener |
| `tests/test_client_spot_single_faucet_v1.py` | Structural carrier + adoption-above-`fetchState` order |
| `governance/root_cause_log.md` | RC-123 CLOSED + v20 P0b receipt |

---

## Claim table

| Claim | Grade | Smoking gun |
|---|---|---|
| One carrier `ed_ticker` | **FIXED** | Both pages getItem/setItem; key shared |
| Console adopt before first poll | **FIXED** | Inline script at `ticker-input` markup `:3095-3101`; `getItem` index **before** `async function fetchState` |
| `fetchState` chokepoint persist | **FIXED** (legacy console) | `:9901-9909` reads `#ticker-input` |
| cv2 header commit writes carrier | **FIXED** | `commitTicker` `:13225` |
| Chart adopt + write | **FIXED** (narrow) | Adopt IIFE `:1212-1216`; write on **`change` only** `:1202-1208` |
| Parallel tabs live via `storage` | **FIXED** | Both pages listen (`index` `:13239`, `chart` `:1217`) — correct that same-tab doesn’t fire |
| “EVERY path” / all commit paths | **PARTIAL / ESCAPE** | Terrain/radar row click calls `setActiveTicker(r.ticker)` **without** `ed_ticker` write and **without** `fetchState` (`:12636-12639`). DOM updates (`:4337-4338`) but carrier stays stale → `/chart` can still wake on prior symbol |
| Playwright journey proof | **THEATER (artifact)** | RC-123 VERIFIED cites `node ticker_journey_probe.js` — **file not in repo** (rglob empty). 15/15 structural suite is real; journey is unreproducible from tree |
| Structural lock adequate | **PARTIAL** | `test_cross_page_ticker_carrier_is_wired` **passed**; asserts presence + order only — **no** storage-listener assert, **no** radar-path assert, **no** chart Enter/`input` coverage |
| v20 P0b receipted | **FIXED** | Ledger “Audit v20 processed…”; live `check_adversarial_audits_are_answered()` = `[]`; best=20 |
| Client suite 15/15 | **FIXED** | Same-turn `pytest tests/test_client_spot_single_faucet_v1.py` → **15 passed** |

---

## Escape detail (must fix before CLOSED is honest)

```12636:12639:static/index.html
  row.onclick = () => {
    if (typeof setActiveTicker === 'function') setActiveTicker(r.ticker);
    else window.activeTicker = r.ticker;
    edLoadTerrain();
  };
```

`setActiveTicker` mirrors DOM but does **not** own `ed_ticker`. Any commit that skips `fetchState` / `commitTicker` / chart `change` leaves the carrier behind.

**Chart:** write only on `change` — type + navigate without committing change can also miss (browser-dependent).

**Nav:** `href='/chart'` still carries no query param — OK **if** carrier is always written; the radar escape breaks that assumption.

---

## Standing board (unchanged by this commit)

| Item | Status |
|---|---|
| P0b C4/C1 | Prior ACCEPT @ `994c7348` (restart for screen) |
| Decide `!tradeable` LONG/SHORT | **OUTSTANDING** — `:5354/:5357` still dim-only |
| LP-01 | **NEXT** in `ACTIVE_PROGRAM.md` |
| RC-6 | **REOPENED** — supervised drop still owed |
| RC-58 / RC-107 | **OPEN** |
| Server | Stopped (Claude) — static fix needs reload when up |

---

## RC-123 honesty recommendation

| Status cell | Should be |
|---|---|
| CLOSED + “every path” | **PARTIAL** until radar/`setActiveTicker` writes carrier (or all non-fetchState commits are enumerated and locked) |
| Journey VERIFIED | Downgrade to probe-ran / or commit the probe script |

---

## Scorecard nudge

RC-123 is real UX glue (+operator trust). Overall stays ~**7/10** pending Decide + restart proof of P0b. Not a fitness leap.

---

## Operator fork (unchanged)

1. Claude: seal RC-123 escapes (carrier inside `setActiveTicker` **or** every click path) + commit journey probe / drop false VERIFIED  
2. Next burn: **Decide** (declared)  
3. Then **LP-01**; **RC-6 drop** on your word before Aug 9  

---

## Status line

`CLAIM: PARTIAL ACCEPT RC-123 @ba032b77 — carrier+order FIXED; radar setActiveTicker misses ed_ticker; journey probe absent from tree; 15/15 structural · DONE: v21 · NEXT: Decide | seal RC-123 · BLOCKER: none`
