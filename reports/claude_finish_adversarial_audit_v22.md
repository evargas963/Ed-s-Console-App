# ADVERSARIAL AUDIT v22 — v21 seal @ `c1330fb5` — 2026-07-28 ~21:45 CT

**HEAD:** `c1330fb5` — `v21 processed: carrier moved to its canonical owner; the proof joins the repo.`  
**Prior:** v21 PARTIAL @ `ba032b77` (radar escape + missing journey probe)  
**Verdict:** **ACCEPT** both v21 guns closed · **PARTIAL** on “sole carrier writer” doctrine (cv2 `commitTicker` still setItems) · board unchanged

---

## Three v21 findings — re-proof

| Finding | Grade | Evidence |
|---|---|---|
| Radar / non-fetchState escape | **FIXED** | `setActiveTicker` writes `ed_ticker` when `changed` (`static/index.html:4288`). Radar `:12636` calls it → carrier updates by construction |
| Journey probe THEATER | **FIXED** | `tools/ticker_journey_probe.js` tracked; same-turn run → `{"typedInto":"ticker-input","stored":"QQQ","chartTk":"QQQ","backTk":"QQQ"}` exit 0 |
| Structural lock (owner + no fetchState persist) | **FIXED** | Test asserts setItem inside `setActiveTicker`, absent from `fetchState`; **15/15** faucet suite; brace-aware extract confirms |

---

## Residuals (honest, non-blocking for ACCEPT)

| Item | Grade | Note |
|---|---|---|
| “Only setActiveTicker writes carrier” | **PARTIAL** | Console still has `commitTicker` setItem `:13224` (redundant with refresh→`setActiveTicker`). Chart page writer stays (separate document — required). |
| Test regex `.*?\n\}` | **OK here** | Match len = brace-aware len (2997); not truncated before setItem |
| v21 receipt / RC-118 | **FIXED** | Ledger cites audit v21; `check_adversarial_audits_are_answered()` = `[]` |

---

## Board

Decide → LP-01 → RC-6 drop (unchanged). Restart picks up static.

---

`CLAIM: ACCEPT v21 seal @c1330fb5 — escape+probe+lock FIXED; commitTicker still a spare setItem · DONE: v22 · NEXT: Decide · BLOCKER: none`
