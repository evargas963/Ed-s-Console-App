# Order-Flow Schwab capability inventory (preserved)

**Status:** DISCOVERY / AUDIT — no UI, no new analytics  
**RC:** RC-438  
**Spec companions:** `tools/probe_schwab_of_capability_rth.py`, `tools/of_schwab_capability_lib.py`,  
`reports/of_capability_probe/*/capability_matrix.json`

## Corrections (operator 2026-08-20)

1. Nested book `EXCHANGE` depth is **`exchange_code_raw` only**. Do **not** call it
   per-participant / MPID / market-maker until identity semantics are **PASS**-proven.
2. **Documented / repo-visible** capability ≠ **live entitlement / proof**. Live cells stay
   `NOT_PROVEN` until an RTH probe records evidence (or `UNAVAILABLE` on a refused service).

## Status vocabulary (OF-tab design)

| Status | Meaning |
|---|---|
| `PASS` | Live RTH evidence captured for entitlement; semantic ruling recorded where required |
| `NOT_PROVEN` | Documented and/or partially observed; live proof or semantics incomplete |
| `UNAVAILABLE` | Not offered / refused / absent on probed surfaces |
| `DOCUMENTED` | Present in schwab-py enums or `schwab_field_inventory/*` only |

## Documented / repo-visible surface (not live proof)

### Streamer (schwab-py 1.5.1)

| Service | Documented | Console subscribes today |
|---|---|---|
| `LEVELONE_EQUITIES` | Yes (fields 0–51) | Yes (active UI ticker) |
| `LEVELONE_OPTIONS` | Yes | No (REST chain instead) |
| `NYSE_BOOK` / `NASDAQ_BOOK` | Yes (“level two”) | Yes (same ticker) |
| `OPTIONS_BOOK` | Yes (same book schema) | **No** |
| `CHART_EQUITY` | Yes | Capture daemon only |
| `TIMESALE_*` | **Not wrapped** in schwab-py | No; prior probe code **11** (2026-07-22) — live still `NOT_PROVEN` until re-probe |

### Book schema (documented)

| Level | Field | Documented meaning |
|---|---|---|
| Top | `SYMBOL`, `BOOK_TIME`, `BIDS`, `ASKS` | Envelope |
| Price | `BID_PRICE` / `ASK_PRICE` | Price |
| Price | `TOTAL_VOLUME` | Aggregate size at price (vendor name) |
| Price | `NUM_BIDS` / `NUM_ASKS` | Count field — **semantics NOT_PROVEN** (not order-count / MM-count) |
| Nested | `EXCHANGE` | `exchange_code_raw` — **identity NOT_PROVEN** |
| Nested | `BID_VOLUME` / `ASK_VOLUME` | Size on that exchange code |
| Nested | `SEQUENCE` | Per-row sequence — update-order use NOT_PROVEN |

### L1 equity OF-relevant (documented)

Bid/ask/last + sizes; `QUOTE_TIME_MILLIS` / bid/ask/trade times; `ASK/BID/LAST_ID` =
**Exchange ID** (not MMID); `ASK/BID/LAST_MIC_ID` = **MIC**; session `TOTAL_VOLUME`.

### Explicit gaps (documented absence)

| Concept | Documented status |
|---|---|
| MPID / Market Maker ID | UNAVAILABLE in enums |
| Market Maker Count | UNAVAILABLE as a named field |
| Native aggressor / condition codes | UNAVAILABLE |
| NOII / auction imbalance | UNAVAILABLE in enums |
| Level-3 order stream | UNAVAILABLE |

## Current console use (gap)

| Concept | Live path today | Persisted | UI |
|---|---|---|---|
| L1 TOB | Stream + REST | Partial snapshots / plane | Header |
| Book `TOTAL_VOLUME` imbalance | Memory OF engine | No raw books | Compact bias only |
| `NUM_*`, nested `EXCHANGE`/`*_VOLUME`, `SEQUENCE` | Received then **discarded** | No | No |
| Hidden OF metrics | Computed | API Tier C may carry | Mostly hidden |
| Schwab timesales | None | Alpaca→`stream_capture.db` only | Alert tape ≠ prints |

**ONE FAUCET:** cum-delta has stream proxy vs REST Lee-Ready fallback; `flow_imbalance` (options) ≠ `book_imbalance_*` (book).

## RTH probe (smallest)

```text
# Stop console streamer / run_stream_capture first (single-streamer-owner).
python tools/probe_schwab_of_capability_rth.py --symbols SPY,QQQ,IWM --duration-sec 90 --with-levelone-options
```

Writes `reports/of_capability_probe/<stamp>/`:

- `frames/*_raw.json` — numeric-key Schwab data frames (pre relabel)
- `frames/*_decoded.json` — schwab-py named relabel (still pre Ed Console OF normalize)
- `analysis/*.json` — NUM_*, EXCHANGE samples, BOOK_TIME/SEQUENCE, TIMESALE, absence scan
- `capability_matrix.json` — design matrix with PASS / NOT_PROVEN / UNAVAILABLE

Offline / no token: writes a template matrix with `live_probe_ran=false` and exit 2.

## Final matrix location

After RTH: use the latest `reports/of_capability_probe/*/capability_matrix.json` as the
OF-tab design authority. Until then every live cell remains **NOT_PROVEN**.
