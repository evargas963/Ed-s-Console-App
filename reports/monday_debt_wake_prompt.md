# Monday debt wake prompt — HISTORICAL (do not paste)

> **HISTORICAL RECORD (stamped 2026-08-25).** This was the 2026-08-03 one-shot wake prompt;
> its targets are dead and its cited authority (`reports/zero_debt_work_law_v1.md`) is itself
> historical. Under the 2026-08-24 operating model the operator directs each session in chat —
> no standing prompt file is a work order.

**When:** Mon 2026-08-03 at/after ~08:25 CT (RTH open 08:30 CT / 09:30 ET).  
**Authority:** `reports/zero_debt_work_law_v1.md` + `.cursor/rules/01-find-prove-no-soft-stop.mdc`.  
**Halt words only:** `STOP` / `PAUSE` / `HANG IT UP` / `DO NOT CONTINUE`.  
**Decide:** WAIT. Do not invent admissions. Prefer product proof over new gates.

---

OPERATOR GO — MONDAY LIVE DEBT FINISH (UNIVERSAL / enrolled universe; not SPY-only).

You are finishing the ONLY remaining RC product debt that was honestly clock-blocked over the weekend. Do not soft-stop. Do not open museum rows. Do not claim Done without same-turn evidence.

## Residue (must clear or re-park with new measurable clock)

| id | status | PASS criteria (measurable) | UNBLOCKED-BY command |
|---|---|---|---|
| **RC-166** | PARTIAL | Under RTH load: `GET /api/diagnostics/sqlite-contention` shows healthy recent window (no multi-minute lock waits / no DB_DEGRADED storm). Console must be the post-RC-166 worktree (`.venv` uvicorn). Keep **one** listener on `:8000` (parent/child pair OK; two LISTENs are not). | `curl -s http://127.0.0.1:8000/api/diagnostics/sqlite-contention` (or Invoke-WebRequest). Re-probe after ≥10–15 min RTH load. |
| **RC-180** | PARTIAL | Desk F-10 only: same contention re-probe as RC-166 during RTH. Desk F-01/04/05/07/08 already FIXED — do not re-litigate. Close RC-180 when RC-166 live proof PASSes. | Same diagnostics endpoint under RTH. |
| **RC-181** | OPEN | First `EdRthCompletenessCheck` fire after Mon RTH close must exit non-silently (0 complete / 1 holes / 2 measure-fail). Verify task Last Run / Last Result after **15:35 CT**. | `schtasks /Query /TN "EdRthCompletenessCheck" /FO LIST /V` after 15:35 CT; or `.venv\Scripts\python.exe -m tools.rth_completeness_check_v1 --db data/ed_console.db` (add `--backfill` only if holes). |

`NEXT_RTH_PROOF 2026-08-03` · `# next-rth-ok: 2026-08-03`.

## Required same-turn sequence

1. **Confirm console:** one uvicorn on `:8000` from this repo `.venv`. If stale/dual: stop extras, start:
   ```text
   .venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10
   ```
2. **RC-166 / RC-180:** after market open + load, capture sqlite-contention JSON; write evidence into RC fix cells; CLOSED only if live numbers prove the hold shortening works.
3. **Morning collector (FP-63 / GEX n):** after ~10:00 ET prove `option_chain_morning_full` rows for enrolled tickers (at least SPY/QQQ/IWM) on `et_date='2026-08-03'`. Write/update `reports/gex_r1_monday_collector_gate_result.json` if that gate is in scope.
4. **RC-181:** do not fake-close before 15:35 CT. After fire, record exit/Last Result; CLOSE only on non-silent success semantics.
5. **UNPROVEN register:** two rows were due **2026-08-02** (dealer-gamma range beyond RV; per-strike charm walls). On Mon they become overdue unless PROVEN / DISPROVED+track / honest re-date with measurement plan. Do **not** fake PROVEN. Either run the cheapest measure command from `reports/cursor_debt_deep_adversarial_audit_v1.md` §UNPROVEN or re-date with evidence why n is still illegal.
6. **Chart intent:** Collect/completeness Done language requires Chart consumer honesty (RC-163). Banking ≠ render Done.

## Forbidden soft-stops

- "Code is ready; live proof later" without updating UNBLOCKED-BY clock.
- Closing RC-166 from Sunday idle contention zeros.
- Claiming OPERABLE_SURFACE_CLEAN from sentinel-only samples.
- Mass-closing RC rows without FIXED reach.
- Ending the turn with prose while any of 166/180/181 remain without a new measured status.

## Status line when mid-work

`CLAIM:` … · `DONE:` … · `NEXT:` … · `BLOCKER:` or `none`

## Read first

- `AGENTS.md`
- `reports/zero_debt_work_law_v1.md`
- `reports/cursor_debt_deep_adversarial_audit_v1.md`
- `governance/root_cause_log.md` rows RC-166 / RC-180 / RC-181
- `reports/no_soft_stop_completion_playbook.md`

---

## MONDAY 08:30 CT — operator order of 2026-08-02 ("at 8:30 am ct on the dot all this gets fixed")

Alarm set: one-time scheduled task `monday-0830-single-faucet-levels-and-repairs` fires
2026-08-03T08:30:00-05:00 (Monday). Correction to earlier rows: Monday is 2026-08-03, not
08-04.

Sequence (details in the scheduled task prompt; ultimate law applies — named reference
before every change):
1. Confirm the co-tenant git freeze (RC-210 — two same-day wipes).
2. SINGLE-FAUCET LEVELS SERVICE — the operator's named priority. Why it's four producers
   today (the honest answer given 2026-08-02): each producer was born in a different
   mission era under ship-this-surface pressure — liquidity engine first, terrain walls
   later, per-strike payloads later, exposure flow/book/history this week — and no law
   forced a system-level design pass before adding another producer; the mockup law
   reviews UI, nothing reviews DATA architecture. Target: ONE /api/levels contract
   (id, price, family, evidence tier, provenance, per-level staleness clock), consumers
   migrated tab by tab, Gamma panel data untouched. Consider encoding the missing lock:
   a design-review gate for NEW producers/endpoints (mandate-to-mechanism).
3. RC-207 DB repair with the operator (disk ≥30GB → backup → rebuild
   snapshots_1m_normalized from source → integrity ok → deferred charm columns).
4. Live RTH cluster measurement (RC-204/RC-206 tail).
5. Wipe-recovery completion from earlier transcripts (charm plumbing, desk, time_et;
   ledger rows per scratchpad/_ledger_rows_backup_20260802.md).
6. Orphan-producer wiring (Split·DEX client on /api/exposure/book; GEX·vanna·charm triad
   on FORCES; register scratchpad/_orphan_producer_sweep.py as a standing check).
