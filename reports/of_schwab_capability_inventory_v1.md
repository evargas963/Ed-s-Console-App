# Order-Flow Schwab capability inventory (preserved + definition-refreshed)

**Status:** DISCOVERY / AUDIT — no UI, no new analytics  
**RC:** RC-438  
**Definition refresh:** `tools/refresh_schwab_native_field_inventory.py` against **schwab-py 1.5.1**  
**Observed dictionary last live sync:** 2026-08-15 (`governance/artifacts/schwab_field_sync_state.json`) — this cloud run: **`CLOUD_SECRET_UNAVAILABLE`** (no `schwab_token.json` / `.env` in agent workspace; **not** `TOKEN_FAILURE`). Host runbook: `reports/of_schwab_live_inventory_host_runbook_v1.md`.

## Corrections (operator)

1. Nested book `EXCHANGE` → `exchange_code_raw` only (never “per-participant” until proven).
2. **Documented / repo-visible ≠ live entitlement.**  
3. **Do not mark a documented native field `NOT_PROVEN` merely because RTH has not run.**  
   Use `DOCUMENTED_NATIVE` / `AVAILABLE_IN_SCHWAB_PY` for definition presence; reserve **RTH** for semantics, entitlement, and population questions static inventory cannot answer.

## Canonical inventory mechanisms

| Mechanism | Role |
|---|---|
| `python schwab_full_field_inventory.py` | Live REST+stream observation |
| `python schwab_field_dictionary_builder.py` | Snapshot rebuild from master (prefer sync) |
| `python tools/sync_schwab_field_dictionary.py --poll` | Live **union-merge** into dictionary (RC-380) |
| `python tools/refresh_schwab_native_field_inventory.py` | Always-on **schwab-py definition** inventory + diff + matrix v2 |

## Freshness result (this refresh)

| Surface | Verdict |
|---|---|
| Streamer field numbers / nested book schema (schwab-py) | **FRESH** — written to `schwab_field_inventory/schwab_native_schema_inventory_v1.json` |
| Observed REST leaf dictionary | **Pending live sync** on operator host (`--poll`) |
| Book nested vs prior observed paths | **Unchanged** — `TOTAL_VOLUME`, `NUM_BIDS`/`NUM_ASKS`, `EXCHANGE`, `*_VOLUME`, `SEQUENCE`, `BOOK_TIME` still match |
| Field-number changes vs prior enum snapshot | **None detected** (no prior enum snapshot committed; numbers recorded now for future diffs) |
| Services documented but outside May-2026 streaming capture | `NYSE_BOOK`, `OPTIONS_BOOK`, `LEVELONE_OPTIONS`, futures/forex L1, screeners, `CHART_FUTURES` |
| TIMESALE wrapper in schwab-py | **Absent** |
| `MARKET_MAKER` | **FOREX L1 only** (`LevelOneForexFields#26`) — not equity book |

Machine-readable refresh report: `reports/of_schwab_native_inventory_refresh_v1.json`  
Universe map: `reports/of_schwab_capability_universe_map_v1.json`  
Capability matrix v2: `reports/of_capability_matrix_template_v1.json`

## RTH reserved for (static inventory cannot close)

- `NUM_BIDS` / `NUM_ASKS` **semantics**
- Nested `EXCHANGE` **identity** semantics
- `OPTIONS_BOOK` entitlement / population
- `SEQUENCE` runtime behavior
- `TIMESALE` availability
- Security-type / entitlement-dependent population

Probe: `tools/probe_schwab_of_capability_rth.py` (PR #168) — keep; run on host after definition refresh.

## Universe map (summary)

See `reports/of_schwab_capability_universe_map_v1.json`:

- **NATIVE_USED** — L1 TOB/times/volume; book aggregate `TOTAL_VOLUME`; REST quote/chain/bars  
- **NATIVE_UNUSED** — `NUM_*`, nested `EXCHANGE`/`*_VOLUME`/`SEQUENCE`, MIC/exchange IDs, OPTIONS_BOOK, LEVELONE_OPTIONS stream, many L1 fundamentals  
- **DERIVED_TODAY** — imbalances, tape proxies, options flow, VWAP/terrain  
- **DERIVABLE** — depth history, venue-share **if** EXCHANGE proven, breadth **if** NUM_* proven, quote aging, options depth if entitled  
- **PROXY_INFERRED** — aggressor/uptick/Lee-Ready; Alpaca IEX prints  
- **UNAVAILABLE** — Schwab timesales wrapper; native aggressor/NOII/MPID/L3  

## Operator next (host)

**Auth:** same as working console — `<console_root>/schwab_token.json` (or `SCHWAB_TOKEN_PATH`) + `.env` `SCHWAB_API_KEY`/`SCHWAB_APP_SECRET`. Do not copy/recreate token unless host auth itself fails.

**`sync --poll` is REST-only** — pair with streaming inventory/probe for Level One + BOOK.

**Stop console `order_flow_streaming` (and any `run_stream_capture`) before streaming steps** — single-streamer-owner.

```text
# From console root (where schwab_token.json already works):

# 1) REST live dictionary sync (REST-ONLY; streamer may stay up)
python tools/sync_schwab_field_dictionary.py --poll

# 2) REST + brief LEVEL_ONE / NASDAQ_BOOK / CHART sample (STOP console streamer first)
python schwab_full_field_inventory.py

# 3) OF streaming probe — NYSE+NASDAQ books (+ OPTIONS_BOOK/TIMESALE/L1 options) (STOP streamer; prefer RTH)
python tools/probe_schwab_of_capability_rth.py --symbols SPY,QQQ,IWM --duration-sec 90 --with-levelone-options
```

Full command + blocker evidence: `reports/of_schwab_live_inventory_host_runbook_v1.md`.  
Do **not** substitute `refresh_schwab_native_field_inventory.py` for the live authenticated reading.
