> **Classification:** Policy Specification | **Scope:** Governance policy/contract `SCHWAB_REMEDIATION_S017_REST_QUOTE_TIME_CONTRACT.md`.

# Schwab Remediation S017 REST Quote Time Contract

**Status:** IMPLEMENTED  
**Slice:** S017 `TIME_NOW_FALLBACK` aggregate  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): quotes.quote.quoteTime; quotes.quote.tradeTime; pricehistory.candles.*.datetime
Derived-field disposition: REPLACE_MARKET_DATA_TIME_WITH_SCHWAB_AND_SPLIT_INGESTION_CLOCK
All consumers checked: yes
```

## Contract

REST quote market-data time must come from Schwab `quoteTime` or `tradeTime`. Server wall-clock time may be retained only as separately labeled ingestion/build provenance.

REST quote rows must not expose wall-clock `time.time()` as `fast_server_ts`. Candle accumulator ticks derived from REST quotes must only use Schwab quote/trade time. If Schwab quote/trade time is missing, the quote may still serve price fields, but no synthetic candle tick timestamp is fabricated.

## All-Consumers Disposition

`fast_server_ts` is market-data time only (Schwab `quoteTime` / `tradeTime` precedence per `server._build_rest_fast_quote_payload`). Every production site that reads or writes the key is listed below (line refs are stable anchors for review).

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| Inline equity-quote reads in `server.py` (formerly `chains.QuoteBlock` — removed in the Schwab-direct redesign) | fixed-in-this-slice | inline at each consumer | Schwab REST `quoteTime` / `quoteTimeInLong` and `tradeTime` / `tradeTimeInLong` are preserved by reading the Schwab leaves directly per the Precedence Principle. |
| Inline equity-quote reads in `server.py` (formerly `chains.parse_quote_payload` — removed in the Schwab-direct redesign) | fixed-in-this-slice | inline at each consumer | Schwab quote/trade time leaves are read inline; no helper-side normalization is needed because consumers operate on the raw Schwab leaf. |
| `server._build_rest_fast_quote_payload` | fixed-in-this-slice | `server.py:732-770` | `fast_server_ts = parsed.quote_time or parsed.trade_time`; `server_received_ts` is wall receipt (logged as `server_received_ts=`). |
| `server._tier_a_live_state_dict` REST bootstrap row | fixed-in-this-slice | `server.py:2736-2770` | Tier A `quote_ingestion: rest_tier_a` row uses Schwab times for `fast_server_ts` (not `time.time()`); `server_received_ts` is ingestion clock. |
| `server._tier_a_live_state_dict` response passthrough | fixed-in-this-slice | `server.py:2799-2821` | Echoes `quote_time_source`, `server_received_ts`, `fast_server_ts`, `_live_plane_fast_ts` from the quote row; `_pipeline_ms` from `t0_mono` only. |
| `server._fetch_state` candle accumulator path | fixed-in-this-slice | `server.py:3052-3068` | `_tick_ts = parsed.quote_time or parsed.trade_time`; ticks skipped when `_tick_ts is None`. |
| `server._fetch_state` pipeline latency vs quote wall | fixed-in-this-slice | `server.py:4861-4866` | `_pipeline_ms` / `_chain_ms` / `_quote_ms` / `_compute_ms` from `time.monotonic()` deltas; `_server_build_ts` is separate ingestion wall clock (`time.time()`), not Schwab quote time. |
| `server._fetch_state` **`volatility`**-history lookup | fixed-in-this-slice | `server.py::_fetch_state` | Time-bounded lookup only runs when Schwab quote/trade time is present. |
| `live_market_plane.record_from_level_one_equity` | fixed-in-this-slice | `live_market_plane.py:115-145` | Streaming: Schwab millis → `fast_server_ts`; see S017 Live Plane contract. |
| `live_market_plane.merge_into_state` | fixed-in-this-slice | `live_market_plane.py:208-210` | Copies plane `fast_server_ts` into `_live_plane_fast_ts` only when present. |
| `live_market_plane.apply_l1_live_quote_overlay` | fixed-in-this-slice | `live_market_plane.py:231-233` | Same overlay rule as `merge_into_state`. |
| `static/index.html` fast-lane render | canonical | `static/index.html:5195-5290`, `8845` | UI reads `fast_server_ts` for staleness display; does not manufacture timestamps. |

No `pending-follow-up` rows remain for this REST quote time sub-slice.

## Verification

```text
python -m pytest tests/test_server_quote_source_contract.py tests/test_fast_lane_contract.py tests/test_live_market_plane_streaming.py
```

Expected: REST fast quote `fast_server_ts` is Schwab quote time, server receipt time is separately labeled, and quote source details remain Schwab-field explicit.
