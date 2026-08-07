# Repo attack plan + ratings v1 — 2026-07-28 ~11:55 CT

**HEAD:** `90048e5e` (+ dirty wall-range WIP)  
**Base canopy:** Wave-3 SYNTHESIZED (`reports/repo_wide_adversarial_audit_wave3.md`)  
**Merged:** [Bucket taxonomy](9ac24815-6fa2-4977-92ff-7ccc3d1fa545) · [Quality re-rate](78dd113c-2c41-4132-ac79-abefd7b63779) · [LP-01 gap](9a68b55e-6bbf-41b7-b1f2-3bee0d53f02f) · [P0 checklist](3657254e-0658-49d9-8e56-f4b6758a2a38) · [DB/capture/research](44a1cd95-e63d-4df0-9575-05301a80f30d)  
**Gap-pass HEAD note:** live tree was `5d5724a5` (descendant of plan cite `90048e5e`) when DB/capture ran.

---

## How to attack

**Do not run another blind full-repo audit.** Wave-3 is SYNTHESIZED 5/5. Next move = **bucket burn + re-audit that bucket**.

### The real fork (operator must pick)

| Goal | Burn first | Who said |
|---|---|---|
| Obey `ACTIVE_PROGRAM` Operator NOW | **LP01_LIQUIDITY** | [taxonomy](9ac24815-6fa2-4977-92ff-7ccc3d1fa545) rank 1; first fix = VP `[L,H]` |
| Trust the screen *today* (spot/walls/stale) | **UI_LYING_CLOCKS + MONEY_PATH** | Wave-3 P0; start at **W3-C8** memo ([P0 checklist](3657254e-0658-49d9-8e56-f4b6758a2a38)) |
| Stop TRADE-shaped paint under WAIT | **DECIDE_ADMISSION** | Wave-3 W3-C5/C9 |

**Program-legal default:** LP-01 (binding until you say otherwise).  
**Honesty default if the console is the complaint:** P0 clocks/money-path first — building LP-01 on a lying cockpit compounds distrust.

Reply `LP-01` or `P0_CLOCKS` (or `DECIDE`) to start the burn.

---

## Bucket taxonomy (merged)

| Rank | Bucket | Sev | Eff | Wave-3 home | First concrete fix |
|---|---|---|---|---|---|
| **1*** | **LP01_LIQUIDITY** | 4* | L | W3-C6 | VP volume across `[L,H]` in `liquidity_value_engine.py` |
| 2 | **MONEY_PATH** | 5 | L | W3-C1/C2/C8 | Tier C `_fetch_state` → `_memoized_quote_response` |
| 3 | **UI_CONSOLE_CHART** | 5 | M | W3-C3, W3-U3/U4 | One `cv2-hd-px` writer; kill `fnum((t\|\|{}).spot)` |
| 4 | **COLLECT_AUTH** | 5 | M | W3-C4 | `record_quote` on carry-forward + QSD in merge |
| 5 | **LEVELS_TERRAIN** | 4 | L | W3-C1, RC-113/115 | One wall/flip book + source label |
| 6 | **DECIDE_ADMISSION** | 5 | M | W3-C5/C9 | Blank pills / suppress `final_bias` under WAIT |
| 7 | **LOCKS_GOVERNANCE** | 3 | M | W3-C7 | Wire `verify_dead --check`; Cursor hooks |
| 8 | **FIND_PROVE_SCIENCE** | 3 | L | RC-58/107 | Thresholds → `session_safe`; RC-58 revalidate |
| 9 | **CAPTURE_STREAM** | 4 | M | W3-C2 stream leg | Single stream→plane handoff |
| 10 | **DB_STORAGE** | 3 | L | RC-6 via W3-C9 | Lock against silent ADD COLUMN re-ADD |
| 11 | **LANDFILL_BLOAT** | 2 | M | landfill slice | Ledger co-retire 13 section inventories |

\*Rank 1 is **program-binding**, not maximum severity. Severity-5 money/UI/Decide sit at ranks 2–4/6.

---

## Institutional fitness SCORECARD (merged re-rate)

Sources: wave3 + spot faucet + v9. Prior rough: locks~6, structure~4, trust~4, bloat~3, pretty~3, overall~4.

**Re-rate @ `891080b4` (2026-07-28 ~16:40 CT)** — after v10–v19 Claude-finish audits; ENFORCED **40**; RC n=**118** (CLOSED 110 · OPEN 2 · PARTIAL 4 · REOPENED 1 · REMEDIATED 1). RC-118 currently **red** on unanswered **v19** (expected until receipt). Same-turn: LP-01 **NEXT**; RC-6 residue **1380 / 240,250,082** B; C4/C1/Decide still live.

| # | Dimension | Score | Δ vs plan | Why now |
|---|---|---:|---|---|
| 1 | Lock / enforcement | **8** | ↑ | RC-118 receipt + suffix inbox; RC-119/120; law-guard blind-stage/heredoc; RC-6 fill exclude. Still: `verify_dead`∉CHECKS; Path.open/redirect escapes; guard battery not pytest; v19 unanswered |
| 2 | Structure / modularity | **5** | ↑ | **W3-C8 FIXED**; dual wall books + C2 overlay still (**W3-C1/C2**) |
| 3 | Trustworthiness (green≠true) | **4** | ↑ | Runtime clocks improved; QSD strip + dual books + Decide paint still lie-shaped |
| 4 | Job-without-bloat | **4** | → | Unchanged; audit-report sprawl local/untracked |
| 5 | Code beauty / clarity | **3** | → | Still multi-surface / dual books |
| 6 | Collect fidelity | **6** | ↑ | Memo class + RC-6 forward bleed stop; **W3-C4** carry/`record_quote` + QSD merge still OUTSTANDING |
| 7 | Find & Prove honesty | **3** | → | **LP-01 NEXT** untouched; RC-107/58 OPEN |
| 8 | Decide safety | **3** | → | Per-horizon LONG/SHORT under `!tradeable` (`:5345/:5348`) |
| 9 | Operator-visible UI honesty | **5** | ↑ | P0 clocks runtime FIXED; RC-117 PARTIAL (lock escapes); walls still dual-book |
| 10 | **OVERALL institutional fitness** | **6** | ↑ | Lock/collect/UI up; **NOT trade-ready**; program guns still the floor |

**+1 OVERALL levers (unchanged fork):** (1) **LP-01** · (2) **P0b** C4+C1 · (3) **DECIDE** sieve.

---

## Institutional fitness SCORECARD — re-rate @ `a6f203af` (2026-07-30 ~12:52 CT)

**Same-turn evidence:** `/api/build` sha=`a6f203af` drift=false; logger 40 tickers; `$SPX` age≈22s `chain_basis=dte<=120` failing=false; RTY/XXT hard-quarantined (`fetches_avoided` climbing); decision admissions registry still empty (WAIT by design); HEAD RC-147→151 + RC-6 CLOSED; audits v29–v36 ACCEPT on scoped claims. LP-01 still NEXT in `ACTIVE_PROGRAM.md` (operator-deferred).

| # | Dimension | Score | Δ vs `891080b4` | Why now |
|---|---|---:|---|---|
| 1 | Lock / enforcement | **9** | ↑+1 | CLOSED↔code (RC-137–141), citation allowlist (RC-136), mypy scope/instrument (RC-142–145), failure+quarantine class (RC-147–151) with fire/quiet + live wire. Residual: “right change” still audit-judged; some content-blind SHA theater declared |
| 2 | Structure / modularity | **7** | ↑+2 | Walls/pin single-authority path; terrain producer diagnostics; quarantine as shared memory across rotation+priority. `server.py` still a gravity well |
| 3 | Trustworthiness (green≠true) | **8** | ↑+4 | Stale-looking-healthy board killed: FAILING/PAUSED/STALE + quarantine reasons on strikes **and** terrain not-ready (RC-151) + Chart pixels (RC-150). Residual: analytics/state latency; `$SPX` full-basis still NEXT-DEPTH |
| 4 | Job-without-bloat | **3** | ↓ | Untracked adversarial-audit sprawl + daily report churn; not cleaned this arc |
| 5 | Code beauty / clarity | **3** | → | Unchanged shape debt (RC-19 FROZEN left alone on purpose) |
| 6 | Collect fidelity | **8.5** | ↑+2.5 | RC-6 blob drop CLOSED (zero-loss path, v29 ACCEPT); morning capture + operable-surface ops standing; geometry/learner no longer self-poisons width (RC-149) |
| 7 | Find & Prove honesty | **3** | → | Scoreboard still **0** existence PASS; LP-01 untouched (deferred); admissions empty — honest, not advanced |
| 8 | Decide safety | **10** | ↑+7 | Empty `decision_path_admissions.json` → WAIT; walls/pin fail-closed; no TRADE-shaped paint from unadmitted books (prior Decide arc). **Not** “edge proven” — abstention is the product |
| 9 | Operator-visible UI honesty | **8.5** | ↑+3.5 | Chart option volume live; FAILING·QUARANTINED on pixels; AMD/SPY candles healthy at desktop. Residual: narrow-window `#histwrap` collapse; RTY/XXT still enrolled (curation) |
| 10 | **OVERALL institutional fitness** | **8.5** | ↑+2.5 | Cockpit/collect/lock layer is institutional; science layer is not. **NOT trade-ready** (no ADMITTED edge). Layer closeout SESSION_CLOSEOUT_GREEN; system-to-10 is not |

**How to read OVERALL 8.5:** weighted toward Decide safety + Collect + Lock + UI honesty after the 2026-07-29/30 arcs. Find & Prove at 3 caps “trade readiness” regardless of cockpit polish.

**+1 OVERALL levers (next climb, operator pick):**
1. **LP-01** (program NEXT — deferred) → Collect/UI structure levels  
2. **`$SPX` full-basis** (RC-149 NEXT-DEPTH) → Trust + Collect  
3. **Evict or keep RTY/XXT** (curation) → board hygiene only  
4. **Narrow Chart layout** → UI only if you hit small windows  
5. **Find & Prove** new study / admission — only path to Decide≠WAIT with edge  

**Layer just closed (do not reopen without new evidence):** terrain producer honesty + quarantine + Chart reason pixels (RC-147–151); RC-6 storage; walls/pin Decide-safety arc.

---

## LP-01 gap grades ([LP-01 gap](9a68b55e-6bbf-41b7-b1f2-3bee0d53f02f))

| Sub-item | Grade | First evidence |
|---|---|---|
| VP volume across `[L,H]` (not typical-price dump) | **OUTSTANDING** | `liquidity_value_engine.py:463-475` |
| Overnight = prior **trading** close→open (Mon⊃Fri) | **OUTSTANDING** | `liquidity_value_engine.py:322-336` |
| PDH/PDL prior trading day | **FIXED** | `get_previous_day_levels` + Monday test |
| Demote sell_side/buy_side until proven | **PARTIAL** | Live demoted; checkpoints + UI badges still SMC |
| Surface POC/VAH/VAL/ORB/VWAP± on Chart/`#cv2` | **PARTIAL** | Chart: PDH/PDL/VWAP only; Liquidity Map under hidden `#main` |
| F&P touch→5/15/30m vs TOD base | **ABSENT** | No admission / study |
| `/api/liquidity-snapshot` | **FIXED** (backend) | Consumer invisible (`#main { display:none !important }`) |

**LP-01 repair order if chosen:** VP → overnight window → SMC demote → surface on Chart/`#cv2` → F&P last.

---

## P0 clocks checklist ([P0 checklist](3657254e-0658-49d9-8e56-f4b6758a2a38))

Dependency spine: **W3-C8 → W3-C4 → (U3∥U4)**; after C8 parallel **W3-C1 ∥ W3-C3 → W1-H2**.

| Wave | Items | Accept (one line) |
|---|---|---|
| **P0a** | W3-C8 → W3-C4 | One Schwab quote in TTL; plane carries QSD on auth fallback |
| **P0b** | W3-C1 ∥ W3-C3 → W1-H2 | One wall book painted; one `#cv2-hd-px` writer; gamma via `consoleSpot` |
| **P0c** | W3-U3 ∥ W3-U4 | No hardcoded `live ·` / wall-clock as-of; `#ct-conf` demotes with `#ct-trust` |

---

## DB / capture / research gaps ([DB/capture/research](44a1cd95-e63d-4df0-9575-05301a80f30d))

| Area | Worst proof | Grade |
|---|---|---|
| **DB RC-6** | `_migrate_schema` still ADD COLUMN blobs (`db.py:2727-2746`); live **1,097** non-null each on normalized; `option_chain_json` ΣLENGTH **187,193,762** B; RC-6 stamped CLOSED | **OUTSTANDING** |
| **Capture CR-*** | CR-CAP QUEUED (no refuse-to-mount); CR-01 incomplete; CR IN PROGRESS **2** / QUEUED **7**; `stream_capture.db` **1,242,238,976** B; quotes **13,636,327** | CR-CAP **OUTSTANDING**; CR-01/02 **PARTIAL** |
| **Research / FP** | RC-107 OPEN (`np.diff` fallback); RC-58 PARTIAL (loaders gated, revalidate unpaid); price_bars grandfather **38**; FP-63/64 QUEUED behind LP-01 | **OUTSTANDING** / **PARTIAL** |

Writer refuse of `ed_console.db` = **FIXED**. Underweight buckets stay behind operator fork (not auto-promoted over LP-01 / P0).

---

## Agents

| Role | Status |
|---|---|
| [Bucket taxonomy](9ac24815-6fa2-4977-92ff-7ccc3d1fa545) | **MERGED** |
| [Quality re-rate](78dd113c-2c41-4132-ac79-abefd7b63779) | **MERGED** |
| [LP-01 gap](9a68b55e-6bbf-41b7-b1f2-3bee0d53f02f) | **MERGED** |
| [P0 checklist](3657254e-0658-49d9-8e56-f4b6758a2a38) | **MERGED** |
| [DB/capture/research](44a1cd95-e63d-4df0-9575-05301a80f30d) | **MERGED** |

---

## Status line

`CLAIM: v24 ACCEPT residual seal @701dac31 — Lock3 reframed+flip+native FIXED; radar exception honest; Decide next · DONE: v24 · NEXT: Decide | RC-6 | migrate/shared · BLOCKER: none`
