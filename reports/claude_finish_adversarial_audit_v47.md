# Claude Finish Adversarial Audit v47 — NEXT_RTH_PROOF live residual (2026-07-31)

**Auditor:** Cursor (adversarial), 2026-07-31 ~11:00–11:05 ET  
**Target claim:** Claude STATUS PARTIAL — boot PASS @ `6c47b89b`; NEXT_RTH accrual PARTIAL; Chart PASS (yellow OV + GEX; `#gsrc` live+bank); RC-159 “sentinels every 60s” VOID by claim-vs-measurement; combo forbidden; nothing committed; Decide untouched.  
**Evidence cited by Claude:** `reports/claude_finish_rc162_chart_accrual_consumer.md` (appended NEXT_RTH section). Alleged `next_rth_proof_20260731.py` — **absent**.  
**Prior:** v46 PARTIAL — Chart had zero bank reader (P0 CHART_CONSUMER); RC-162 later shipped reader @ `202237c7`.

**Admission preamble (AGENTS.md):** MISSION_CLASS=Collect (adversarial finish audit) · GAP=same-turn re-derive A/B/C vs Claude PARTIAL · SMALLEST_COMPLETE_CHANGE=audit report only · MINIMUM_SUFFICIENT_EVIDENCE=`/api/build` + exact-COUNT SQL + strikes API (sentinels + non-sentinel) + browser/DOM if reachable · DECISION_PATH_EFFECT=must prove Decide untouched · WHY_NOW=live Friday NEXT_RTH residual under operator Chart-intent · TASK_ADMISSION=audit only; no redesign; no commit; no Decide.

**drift-audit run:** phases 1–7 this turn.

- **Phase 1 intent:** Operator wants live accumulate **and** Chart render on enrolled surface for NEXT_RTH `2026-07-31` Friday — not banking alone, not sentinel-only framed as complete, not Monday language. Gate = residual close criteria, not Claude’s prose comfort.
- **Phase 2 mechanical:** re-ran `/api/build`, exact SQL `COUNT(*)`, full-ticker `today_source` probe, Chart `#gsrc`/bank code path Read; browser MCP unreachable (see §C). No AST arity change under audit (audit-only).
- **Phase 3 failure-class checklist:** see §5.
- **Phase 4 critic:** ledger still CLOSED with falsified cadence; stale “Monday” preamble in Claude evidence file; DOM paint not re-derivable this turn.
- **Phase 5–7:** verdict PARTIAL; corrections = none (audit-only); gate hardened n/a. Findings listed below.

---

## Verdict: **PARTIAL**

Claude’s overall **STATUS PARTIAL** label is the correct residual status. Same-turn re-derive confirms boot identity, universal early accrual, Chart API consumer with both `terrain_live_cache` and `accrual_bank:*`, and honest blockers (sentinel cadence + `max(et_minute)≥974` not yet available). It does **not** support ACCEPT.

| Claim | Claude | Auditor same-turn | Result |
|---|---|---|---|
| A) Boot `/api/build` == HEAD `6c47b89b` | PASS | HEAD + process `git_sha` both `6c47b89bdcb4…`; `code_drift.repo_moved_past_process=false`; pid 29920; `startup_git_dirty=true` | **ACCEPT** |
| B) Accrual NEXT_RTH `et_date='2026-07-31'` | PARTIAL (322 rows / 38 tk; min≤556; 35 non-sentinels premarket; gap FAIL; max≥974 N/A) | **607** rows / **38** tickers / **39** rows `et_minute≤556`; **35** non-sentinels in `[555,600)`; **0** tickers with `min>556`; global `max(et_minute)=660`; sentinel gaps **FAIL harder** | **ACCEPT as PARTIAL** (numbers advanced with clock; direction holds) |
| C) Chart yellow OV + GEX; `#gsrc` live+bank | PASS (DOM paint claimed) | API OV/GEX non-zero for SPY/QQQ/IWM + MSFT/NVDA/AMD; source hist **34** `terrain_live_cache` + **4** `accrual_bank:*`; `#gsrc` BANKED branch present in `static/chart.html`. **Browser/DOM pixel paint BLOCKED** this turn | **PARTIAL** (API consumer PASS; DOM paint unverified by auditor) |
| RC-159 “sentinels every 60s” VOID | voided in report prose | Live gaps falsify 60s; **CLOSED ledger fix cell still states 60s cadence** — not amended | **FINDING** (void without ledger correction) |
| Combo forbidden / nothing committed / Decide untouched | claimed | `admissions=[]`; only dirty path is the evidence `.md`; no `server.py`/`static`/`admissions` diff | **ACCEPT** |

**Why not ACCEPT:** residual close criteria require cadence contract honesty through EOD (`max≥974`) and a truthful ledger. Sentinel write gaps remain FAIL; 974 not chronologically available at ~11:00 ET; RC-159 CLOSED cell still lies.

**Why not FAIL:** Claude did not soft-close ACCEPT, did not claim combo, did not touch Decide, did not invent SPY-only completeness, and correctly kept STATUS PARTIAL. Accrual + Chart API consumer are live and measurable. A FAIL would erase correct PARTIAL discipline.

**P0 Claude lied about:** no fabricated A/B COUNT this turn. **Material honesty gap (treat as P0 governance):** declaring RC-159’s “sentinels every 60s” VOID in a report while leaving the **CLOSED** fix cell uncorrected — the ledger still advertises a cadence the live series falsifies.

---

## 1) A) Boot — PASS (PROVEN)

```text
git rev-parse HEAD
→ 6c47b89bdcb4daa75842a1edcc43205d454a3191

curl http://127.0.0.1:8000/api/build
→ git_sha = 6c47b89bdcb4daa75842a1edcc43205d454a3191
→ process_identity.startup_git_sha = same
→ code_drift.repo_moved_past_process = false
→ startup_git_dirty = true
→ process_id = 29920
```

HEAD message: `RC-164: remove orphan _chartCommitInflight that crashed Chart load().`  
RC-162 consumer is an ancestor (`202237c7`). Live process is on the claimed SHA.

---

## 2) B) Accrual NEXT_RTH — PARTIAL (PROVEN; counts re-derived)

**Calendar:** `is_trading_day_et(2026-07-31) = True`, weekday **Friday**. Now ET ~11:00 (`et_minute≈660`). Correct residual label is `NEXT_RTH_PROOF` + ISO date — not Monday.

Reproduce (read-only; exact `COUNT(*)`):

```bash
.venv/Scripts/python.exe scratchpad/_audit_v47_accrual.py
```

| Metric | Claude @ ~10:12 ET | Auditor @ ~11:00 ET |
|---|---:|---:|
| `COUNT(*)` rows | 322 | **607** |
| `COUNT(DISTINCT ticker)` | 38 | **38** |
| rows `et_minute≤556` | 39 | **39** |
| non-sentinel distinct in `[555,600)` | 35 | **35** |
| tickers with `min(et_minute)>556` | 0 (claimed) | **0** |
| global `max(et_minute)` | 609–610 sample | **660** |
| `max≥974` | not yet | **not yet** (need 16:14 ET) |

Sentinel sample (auditor):

| ticker | n | min | max | max(session_volume) |
|---|---:|---:|---:|---:|
| SPY | 36 | 556 | 658 | 4,907,785 |
| QQQ | 36 | 556 | 658 | 3,257,445 |
| IWM | 36 | 555 | 658 | 789,447 |
| MSFT | 14 | 555 | 655 | 380,085 |
| NVDA | 16 | 555 | 655 | 1,495,990 |

### Sentinel cadence — FAIL (worse than Claude’s snapshot)

Gaps from `ts_utc` ordered diffs (exact):

| ticker | n_rows | n_gaps | median gap (s) | max gap (s) | gaps >120s |
|---|---:|---:|---:|---:|---:|
| SPY | 36 | 35 | **132.4** | **472.5** | **20** |
| QQQ | 36 | 35 | **133.7** | **487.7** | **20** |
| IWM | 36 | 35 | **134.1** | **617.8** | **19** |

Claude @ 10:12 ET: SPY median ~105s, 7 gaps >120s, max ~298s. Directionally consistent; later window shows the FAIL deepening. Code still declares `ACCRUAL_MIN_INTERVAL_SENTINEL_SEC = 60.0` (`server.py`).

**RC-159 ledger:** CLOSED fix cell still states *“CADENCE, stated not implied: sentinels SPY/QQQ/IWM every 60s”*. Claude voided that in the evidence report (“Correction stated here rather than restated in the ledger”) — **that is not a ledger correction**. A CLOSED row with a falsified fix cell is a lying close.

---

## 3) C) Chart consumer + render — PARTIAL (API PASS; DOM BLOCKED)

### 3a) API OV + GEX (PROVEN)

Earlier same-turn probe (live cache warm):

| ticker | n | ov_n | OV | absGEX | today_source | age_s |
|---|---:|---:|---:|---:|---|---:|
| SPY | 201 | 158 | 4,907,785 | 2.32e10 | terrain_live_cache | 60.3 |
| QQQ | 210 | 155 | 3,257,445 | 8.09e9 | terrain_live_cache | 56.1 |
| IWM | 87 | 75 | 789,447 | 5.97e9 | terrain_live_cache | 47.4 |
| MSFT | 50 | 50 | 403,954 | 1.50e9 | terrain_live_cache | 27.4 |
| NVDA | 44 | 43 | 1,541,720 | 1.59e9 | terrain_live_cache | 36.3 |
| AMD | 40 | 40 | 150,270 | 3.24e8 | terrain_live_cache | 123.1 |

Full enrolled accrual-ticker source histogram (later same turn, `scratchpad/_audit_v47_sources.py`):

```text
SOURCE_HIST {'terrain_live_cache': 34, 'accrual_bank:0658et': 3, 'accrual_bank:0659et': 1}
BANKED: SPY, QQQ, IWM, MET  (OV/GEX non-zero on bank path)
```

Both faucets observed live in one window — RC-162 fallback is operative when live age exceeds `TERRAIN_STALE_AFTER_SEC` (180s). Sentinels hitting the bank path mid-session is consistent with the cadence FAIL (live snapshot going stale).

### 3b) `#gsrc` contract (code PROVEN; DOM BLOCKED)

`static/chart.html` binds `#gsrc` and, when `today_source` starts with `accrual_bank`, paints amber `BANKED — session accrual…`. Live-cache path prints `today: terrain_live_cache · <age>`.

**Browser/CDP:** MCP `browser_navigate` / tab create failed repeatedly (“No browser tab available” / viewId evaporated). No playwright/selenium in venv. **DOM yellow/blue/red pixel counts = BLOCKED** this auditor turn. Claude’s canvas numbers (`painted 28,536 px…`) are therefore **[UNVERIFIED]** by the auditor — not proven false.

Chart-intent residual is **not** “banking only”: API returns paintable `today.all` triples with positive OV and |GEX| for sentinels **and** non-sentinels. That closes the v46 P0 “zero production readers” for the live console. Pixel paint remains an auditor gap, not a proven Claude fabrication.

---

## 4) Process / scope checks

| Check | Result |
|---|---|
| Soft Done | **YES (soft)** — evidence file header: “consumer + render path is complete and proven” beside STATUS PARTIAL |
| Monday language | **YES** — same file still says “Monday live accrual proof” in preamble / “Not claimed”; new section correctly says Friday `2026-07-31`. Stale Monday prose violates RC-163 residual language |
| SPY-only as complete | **NO** — 38 tickers / 35 non-sentinels measured |
| banking ≠ render | **Addressed in code+API** (RC-162 reader live); DOM paint not auditor-reproven |
| Samples-as-counts | **NO material lie** — Claude used SQL COUNTs; gap medians marked with `~` |
| Void RC-159 w/o ledger fix | **YES FINDING** |
| Invented OUT-OF-SCOPE | **NO** |
| Scheduler redesign temptation | **Resisted** (attribution only; no redesign shipped) |
| Decide touch | **NO** — `admissions=[]`; no admissions diff |
| Combo before PASS | **Respected** |
| `next_rth_proof_20260731.py` | **Absent** — good (no script bloat) |
| Evidence file edit | **Useful** live numbers + reproduce SQL; **debt** = stale Monday preamble left in place |
| Commit | **None** for this residual (only uncommitted report edit) |

---

## 5) Drift-audit Phase 3 checklist (explicit)

- [x] **Presence vs capability** — bank reader present **and** serving (`accrual_bank:*` with OV/GEX > 0).
- [x] **Caller/consumer** — Chart still paints via `/api/terrain/strikes`; bank is second source with stale gate (not archive ghost).
- [x] **Fail-closed** — bank only when live absent/stale; `near`/`far` empty under bank (declared).
- [x] **Stale vs live** — Claude’s 322-row figure is a prior timestamp; auditor exact count is 607. Status PARTIAL still correct.
- [x] **Full-stack / ticker coverage** — not sentinel-only; 38 tickers banking; 35 non-sentinels in premarket window.
- [x] **Classification-by-complement** — non-sentinels via explicit `NOT IN ('SPY','QQQ','IWM')`, not “bad if not sentinel-tagged elsewhere”.
- [x] **Patch / gate-relax** — none observed this turn (no production cadence floor widened to pass).
- [x] **Side-channel** — n/a for this residual.
- [ ] **Browser paint path** — **BLOCKED** (tooling), so Chart PASS cannot be fully auditor-signed.

---

## 6) Residual close criteria (operator)

Live accumulate + render; fix only the failing link; no redesign.

| Criterion | Status |
|---|---|
| Boot on claimed SHA | PASS |
| Accrual from ≤556 across enrolled set | PASS (38/38 min≤556; 35 non-sentinels premarket) |
| Sentinel cadence ≤120s gaps / 60s floor | **FAIL** |
| Accrual through ≥974 | **NOT YET** (clock) |
| Chart API serves OV+GEX (live and/or bank) | PASS |
| Chart DOM yellow + blue/red paint | BLOCKED (auditor) / claimed by Claude |
| Ledger matches measurement (RC-159 cadence) | **FAIL** (uncorrected CLOSED cell) |
| Combo / Decide | clean |

→ Overall residual: **PARTIAL**. Next work is the failing cadence link (or honest PARTIAL reopen of RC-159) and EOD `max≥974` proof — not a Chart redesign, not Decide, not combo.

---

## 7) Cursor fix directive (if operator continues)

1. **Ledger:** reopen or amend RC-159 — either PARTIAL with measured cadence (~130s median sentinel gaps this session) or a real fix that restores ≤60s/≤120s without starving the universal board. Do not leave CLOSED + voided-in-report.
2. **Evidence hygiene:** strike “Monday live” from `reports/claude_finish_rc162_chart_accrual_consumer.md` preamble; keep `NEXT_RTH_PROOF 2026-07-31 Friday` only.
3. **Do not** ship a scheduler redesign in the same breath as ACCEPT; measure after any cadence change on the same day.
4. After 16:14 ET: exact `MAX(et_minute)≥974` per enrolled tickers that accrued.
5. Optional: one browser/CDP paint proof when MCP works — not a new gate script.

**Gate hardened:** n (audit-only; no new detector — rule 01 forbids bloat for this lock class).

---

## STATUS

`CLAIM:` residual remains PARTIAL — boot PASS; accrual universal early + cadence FAIL; Chart API consumer PASS (DOM paint BLOCKED); RC-159 CLOSED cadence cell uncorrected  
`DONE:` v47 adversarial audit report written  
`NEXT:` fix/honest-reopen RC-159 cadence + EOD `max≥974` proof (no combo)  
`BLOCKER:` browser MCP unavailable for pixel paint; wall-clock until 16:14 ET for 974

---

drift-audit run; findings: (1) RC-159 CLOSED cadence falsified and uncorrected, (2) Monday prose left in evidence file, (3) Chart DOM paint BLOCKED, (4) soft “complete and proven” beside PARTIAL; corrections: none (audit-only); gate hardened: n.
