# Live Schwab Native Capability Inventory — reconciled matrix (host run)

> **SUPERSEDED-BY (2026-08-20, RC-440):** the single canonical Schwab field dictionary + migration ledger is `reports/schwab_field_semantic_normalization_ledger_20260820.md`. Where any field semantic here differs, the ledger governs. This report is retained as capture evidence only; its field meanings are reconciled to the ledger (nested `EXCHANGE` = MICs + registered MPIDs, presence PROVEN / vendor semantics NOT_PROVEN; `NUM_*` = venue/quote-source count, NOT order/MM count).

**Run host:** operator console root (the primary Ed Console repo root; same auth path as Ed Console)
**Auth:** `schwab_token.json` at console root — EXISTS, "structure OK; refreshable" (token untouched; no reauth/recreate)
**Local session:** ~08:0x CT / ~09:0x ET = **US pre-market** (not full RTH — see caveats)
**Branch:** `main` @ `eed07d45`. Probe tools materialized read-only from open PR #168 (`cursor/of-schwab-capability-probe-5a23`); not merged to main.

## Commands executed (exact) + exit codes + artifacts

| Step | Command | Exit | Streamer stopped? | Key artifact(s) |
|---|---|---|---|---|
| Auth prove | `python -c "...inspect_token_file..."` | 0 | no | (stdout: token path, EXISTS=True) |
| A · REST | `python tools/sync_schwab_field_dictionary.py --poll` | **0** | no (REST-only) | `governance/artifacts/schwab_field_sync_state.json`; `schwab_field_inventory/schwab_field_dictionary.csv` |
| B · REST+stream | `python schwab_full_field_inventory.py` | **0** | yes | `schwab_field_inventory/schwab_all_fields_master.txt`; `schwab_field_inventory/schwab_field_inventory_summary.csv` |
| C · OF probe | `python tools/probe_schwab_of_capability_rth.py --symbols SPY,QQQ,IWM --duration-sec 90 --with-levelone-options` | **1 (cosmetic)** | yes | `reports/of_capability_probe/20260820T130550Z/{capability_matrix.json, probe_manifest.json, analysis/*, frames/*}` |

**Step C exit-1 is non-fatal:** capture + analysis completed; `UnicodeEncodeError` on the final `print("→")` line only (Windows cp1252). All artifacts written (`capability_matrix.json` 5853 B, 430 decoded book content-items). *Latent tool bug to fix later: ASCII-only stdout.*

**Streamer discipline:** console (uvicorn `server:app`, PID 12312, sole `order_flow_streaming` owner) force-stopped before B/C; port 8000 freed; **restored after** (new PID 2524, `logger_running:true`, 44 tickers, HTTP 200). No `run_stream_capture` process was running (stale `data/stream_capture.lock` left untouched). No unrelated services touched.

## Five-source reconciliation

1. **Static schwab-py schema** (`schwab_field_inventory/schwab_native_schema_inventory_v1.json`, `schwab_all_fields_master.txt`): book leaves + LEVELONE enums documented.
2. **Aug-15 live** (`schwab_field_sync_state.json` baseline): synced `2026-08-15T22:38:06Z`; endpoints quotes 75 / chains 140 / pricehistory 10 / market_hours 12 / instruments 63 / movers 1; 2412 dict rows.
3. **New REST** (today `2026-08-20T13:02:19Z`): all 6 endpoints observed; **0 new fields**; more instances only (market_hours 43, movers 11, quotes 76). **REST universe unchanged since Aug-15.**
4. **New streaming** (probe `20260820T130550Z`): NYSE_BOOK 91 frames, NASDAQ_BOOK 90, LEVELONE_EQUITIES 90; 430 decoded book content-items; 8488 nested-exchange rows.
5. **Console use paths** (code): `order_flow_engine._compute_book_imbalance` reads **level `TOTAL_VOLUME` only**; `NUM_*`, nested `EXCHANGE`, `SEQUENCE`, nested `BID_VOLUME/ASK_VOLUME` received but **not consumed**.

## Live book shape — PROVEN (NASDAQ_BOOK / NYSE_BOOK, decoded)

```
content[] : { key, BOOK_TIME, BIDS[], ASKS[] }
  BIDS[i]  : { BID_PRICE, TOTAL_VOLUME, NUM_BIDS, BIDS[] }      # aggregated price level
    BIDS[i][j] : { EXCHANGE, BID_VOLUME, SEQUENCE }             # per-venue breakdown
  ASKS[i]  : { ASK_PRICE, TOTAL_VOLUME, NUM_ASKS, ASKS[] } / { EXCHANGE, ASK_VOLUME, SEQUENCE }
```
Measured equalities (n=3756 levels): `NUM_* == count(nested EXCHANGE entries)` (3756/3756); `level TOTAL_VOLUME == Σ nested *_VOLUME` (3756/3756). 32 distinct `EXCHANGE` codes live (nsdq, arcx, edgx, baty, bosx, edga, cinn, tssm, mlco, …).

## Capability matrix

| Concept | Classification | Live evidence / note |
|---|---|---|
| NYSE_BOOK | **NATIVE OBSERVED LIVE · NATIVE USED** | 91 frames; console subscribes → book imbalance |
| NASDAQ_BOOK | **NATIVE OBSERVED LIVE · NATIVE USED** | 90 frames; shape proven (QQQ) |
| LEVELONE_EQUITIES (top of book) | **NATIVE OBSERVED LIVE · NATIVE USED** | 90 frames; bid/ask/sizes/last consumed |
| `TOTAL_VOLUME` at book price levels | **NATIVE OBSERVED LIVE · NATIVE USED · DERIVED TODAY** | authority: `OrderFlowEngine` book imbalance; == Σ nested volumes |
| `NUM_BIDS` / `NUM_ASKS` | **NATIVE OBSERVED LIVE · NATIVE UNUSED/DISCARDED · SEMANTICS NOT_PROVEN** | == count of nested EXCHANGE entries. **Venue/quote-source count — NOT order count, NOT MM count** |
| Nested `EXCHANGE` | **NATIVE OBSERVED LIVE · NATIVE UNUSED/DISCARDED · SEMANTICS NOT_PROVEN** | pre-market: 32 codes. **Superseded by RTH (2026-08-20):** 46 codes MIXING venue MICs (arcx, edgx) with registered MPIDs (JPMS, GSCO, VIRT) — participant IDs ARE present; field's vendor-intended meaning NOT_PROVEN |
| Nested `BID_VOLUME` / `ASK_VOLUME` | **NATIVE OBSERVED LIVE · NATIVE UNUSED/DISCARDED** | per-venue size (e.g. arcx=40); Σ == level TOTAL_VOLUME |
| `BOOK_TIME` | **NATIVE OBSERVED LIVE · SEMANTICS NOT_PROVEN** | 430 frames; non-monotonic across merged stream; per-symbol lag uncharacterized |
| `SEQUENCE` | **NATIVE OBSERVED LIVE · NATIVE UNUSED/DISCARDED · SEMANTICS NOT_PROVEN** | 8488 values; update-order usefulness NOT proven |
| L1 exchange IDs (`*_ID`, `*_MIC_ID`) | **NATIVE DOCUMENTED** | documented as Exchange ID; MIC distinct; live field-presence not separately asserted |
| Quote/trade/bid/ask timestamps | **NATIVE DOCUMENTED**; `BID/ASK_TIME_MILLIS` **NATIVE USED** | clock-skew vs BOOK_TIME NOT_PROVEN |
| OPTIONS_BOOK | **NATIVE DOCUMENTED BUT NOT OBSERVED** | SUBS accepted, **0 frames** in pre-market; console does not subscribe |
| LEVELONE_OPTIONS | **NATIVE DOCUMENTED BUT NOT OBSERVED** | subs failed "no option symbol from chain"; console uses REST chains |
| TIMESALE (TIMESALE_EQUITY) | **UNAVAILABLE (observed refused today)** | response code 11 "Service not available or temporary down"; matches 2026-07-22 |
| Native aggressor side | **UNAVAILABLE → repo reads are PROXY/INFERRED** | no enum field; none in payloads; cum_delta/tape = tick-rule proxy |
| NOII / auction imbalance | **UNAVAILABLE** | no matching keys in enums or captured payloads (key-name scan) |
| MPID / MMID | **no dedicated field; participant codes present in book (RTH)** | no labeled MPID field and none at L1; but nested EXCHANGE values INCLUDE registered MPIDs (JPMS/GSCO/VIRT, RTH) mixed with venue MICs — presence proven, field semantics NOT_PROVEN |
| True Level 2 (full MM montage) | **SEMANTICS NOT_PROVEN** | schema = aggregated price levels + nested per-EXCHANGE sizes (venue-aggregated, not MM-by-MM) |
| True Level 3 (order add/cancel/modify) | **UNAVAILABLE** | no order-id stream service in schwab-py |

## Native fields Ed Console RECEIVES but DISCARDS (free signal)

`NUM_BIDS`/`NUM_ASKS` · nested `EXCHANGE` · nested `BID_VOLUME`/`ASK_VOLUME` · `SEQUENCE` · `BOOK_TIME` (only freshness, not depth). All arrive in every NYSE_BOOK/NASDAQ_BOOK frame the console already subscribes to.

## Highest-value DERIVABLE institutional metrics (candidate — NOT implemented; new faucets)

Deterministic from confirmed native inputs; each is a NEW producer, distinct from the existing `OrderFlowEngine` book-imbalance authority (ONE FAUCET preserved):

1. **Venue-level book imbalance** — per-`EXCHANGE` `BID_VOLUME`/`ASK_VOLUME` skew (which venues lean bid vs ask).
2. **Venue breadth / concentration** — from `NUM_*` (count of quoting venues) + venue HHI. *Label venue-count, not order-count.*
3. **Size-per-venue** — `TOTAL_VOLUME / NUM_*` (avg size per quoting venue at a level).
4. **Microprice / size-weighted mid** — from L1 price+size.
5. **Depth-resolved imbalance curve (L1/L3/L5)** — full curve from level volumes.
6. **Book slope / depth decay** — volume falloff away from touch.
7. **Queue/refresh dynamics** — `SEQUENCE` + `BOOK_TIME` deltas (pull/refill/iceberg) — **gated on SEMANTICS NOT_PROVEN**; needs RTH characterization first.

## Unresolved / owed at full RTH (re-probe)

- **OPTIONS_BOOK** frames (SUBS ok, 0 frames pre-market) — confirm live shape in RTH.
- **LEVELONE_OPTIONS** — re-probe with an explicit near-ATM option symbol (chain-symbol resolution failed).
- **TIMESALE_EQUITY code 11** — RTH re-probe to separate "temporary down" from unentitled.
- **BOOK_TIME** monotonicity/lag and **SEQUENCE** update-order semantics — characterize per-symbol at RTH.
- **NUM_* / nested EXCHANGE semantics** — remain NOT_PROVEN pending Schwab documentation; do not label as order/participant identity.
- Fix probe tool's non-ASCII stdout crash (cosmetic, exit-1).
