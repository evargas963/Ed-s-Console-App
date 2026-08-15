# RC-162 — Chart consumer for the accrual bank (P0 CHART_CONSUMER)

**STATUS: PARTIAL** — the consumer + render path is complete and proven; the Monday live
accrual proof remains an honest residual carried from RC-159.

Slice: Collect + Chart visible surface. No Decide. `decision_path_admissions` admissions `[]`.

---

## The gap, proven before the change

| claim | command | result |
|---|---|---|
| Chart has no bank reader | count of `option_chain_accrual` in `static/chart.html` | **0** |
| Chart paints via the strikes API | count of `/api/terrain/strikes` in `static/chart.html` | **3** |
| bank has no production reader | scan of tracked non-test `.py` for `option_chain_accrual` | **1 file** — `calibration/option_chain_morning_full.py`, its own writer |
| bank not yet materialised | `sqlite_master` lookup on `data/ed_console.db` | table **absent** (console has not run this code) |

Banking is not rendering. With a cold, thin or stale live cache the Chart painted an empty
panel while the session's own gamma and volume sat in the database.

## Root cause

`/api/terrain/strikes` sourced `today` **only** from the in-memory live snapshot
(`terrain_cache_get(tk)['_per_strike']`). Whenever that snapshot was absent — cold start, the
first minutes of the mandated window, a ticker whose refresh is failing — `today` was empty and
the Chart had nothing to draw. The durable bank built for exactly this data had no reader,
because the slice that created it was scoped as Collect and stopped at persistence.

**"Banked" was treated as equivalent to "delivered."** A write with no reader is a cost with no
product — the same failure as RC-156's *produced is not surfaced*, one layer further back.

## What shipped

- `latest_accrual_rows(db_path, ticker, et_date)` — the bank's first reader, returning the newest
  banked observation as the same `[strike, net_gex_1pct$, session_volume]` triples the Chart
  already paints, so the fallback cannot change what the numbers mean.
- Wired into `server.get_terrain_strikes` as a **declared** second source, bounded three ways so
  it cannot repeat RC-68 (a 09:47 archive served at 11:31 under a live label):
  1. serves only when the live snapshot is **absent or older than `TERRAIN_STALE_AFTER_SEC`**
  2. serves only rows banked **today**, and only when **newer** than live
  3. stamps `today_source = accrual_bank:<HHMM>et` and its own age
- `near`/`far` stay **empty** under the fallback: the bank holds the `all` scope only, and
  inventing a DTE split it never measured would be a fabricated level.
- The prior-day `morning_full` archive is untouched and still serves **only** the ghost.

**VISIBLE_SURFACE:** `#gsrc` on `/chart` prints
`BANKED — session accrual, <N> min old (accrual_bank:HHMMet); live chain not current`
in amber, with a tooltip stating the ALL-scope limitation.

## Evidence, same turn

End-to-end through the **real** handler with a seeded temp DB and a forced-cold live cache
(`scratchpad/rc162_e2e_probe.py`) — a sentinel **and** a non-sentinel, per RC-160:

```
SPY   [SENTINEL]     today_source='accrual_bank:0600et'  rows=2
                     yellow OV total=2,300   |GEX| total=6,500,000  near=0 far=0  prior_source=None
MSFT  [NON-SENTINEL] today_source='accrual_bank:0600et'  rows=2
                     yellow OV total=570     |GEX| total=2,100,000  near=0 far=0  prior_source=None
```

In both cases the **later** of two banked observations was served (yellow 2,300, not the earlier
100) — which is what accumulation means.

```bash
.venv/Scripts/python.exe -m pytest tests/test_chart_accrual_consumer_v1.py tests/test_chain_accrual_and_storm1_v1.py tests/test_liquidity_engine.py -q
```
→ **79 passed.** The 8 new tests drive the real reader and the real endpoint source: newest row
wins for both ticker classes, row shape is the Chart's paint contract, the reader fails closed on
missing file / empty DB / unknown ticker / different `et_date`, the live-vs-bank rule is
exercised against the real `TERRAIN_STALE_AFTER_SEC` (a fresh live cache is never overridden),
the endpoint keeps `morning_full` out of `today`, the Chart labels banked rows BANKED, the
existing paint fields are unchanged, and admissions are `[]`.

Gates: `five_why_recursive_lock` 0 · `root_cause_log` RC-162 0 · `rc_log_rows_keep_schema` 0 ·
`universal_ticker_scope` 0 · `single_faucet_provenance` 0 · `no_terminal_null` 0.

## Not claimed

- **Monday live accrual proof** — market closed, console down, table not yet created. The
  RC-159 criteria are unchanged and are **not** claimed here: SPY/QQQ/IWM must show
  `min(et_minute) <= 556`, `max(et_minute) >= 974`, no sentinel gap above 120s.
- No live-console render proof: the console was **down** at 23:44 ET, so the paint was proven
  through the endpoint payload and the DOM label contract, not a running browser.
- `near`/`far` are empty under the bank fallback by design; changing that needs the writer to
  persist DTE scopes.
- Scheduler rotation (RC-161) untouched; no storm1 production wire; no Decide.
