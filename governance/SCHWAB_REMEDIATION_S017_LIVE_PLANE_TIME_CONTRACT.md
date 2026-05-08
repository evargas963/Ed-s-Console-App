# Schwab Remediation S017 Live Plane Time Contract

**Status:** IMPLEMENTED_IN_WORKING_TREE  
**Slice:** S017 `TIME_NOW_FALLBACK` aggregate  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): streaming.content.*.QUOTE_TIME_MILLIS; streaming.content.*.TRADE_TIME_MILLIS; quotes.quote.quoteTime; quotes.quote.tradeTime
Derived-field disposition: REPLACE_MARKET_DATA_TIME_WITH_SCHWAB_AND_SPLIT_INGESTION_CLOCK
All consumers checked: yes
```

## Contract

Live quote data time must come from Schwab quote/trade time when Schwab provides it. Server wall-clock time may be recorded only as ingestion/provenance time and must be labeled as such.

The live plane must not label `time.time()` as the fast quote timestamp for Schwab streaming Level One updates. New Schwab timestamps with unchanged price/bid/ask must still update the plane so downstream freshness calculations can see the new market-data time.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `live_market_plane.record_from_level_one_equity` | fixed-in-this-slice | `live_market_plane.py::record_from_level_one_equity` | `fast_server_ts` now uses `QUOTE_TIME_MILLIS`/`TRADE_TIME_MILLIS` when present; server clock is `server_received_ts`. |
| `live_market_plane.merge_into_state` | covered-by-contract | `live_market_plane.py::merge_into_state` | Propagates `_live_plane_fast_ts` from the plane row, now Schwab data time for streaming rows. |
| `live_market_plane.apply_l1_live_quote_overlay` | covered-by-contract | `live_market_plane.py::apply_l1_live_quote_overlay` | Propagates `_live_plane_fast_ts` from the plane row, now Schwab data time for streaming rows. |
| `live_market_plane.take_fresh_sse_quote_payload` | covered-by-contract | `live_market_plane.py::take_fresh_sse_quote_payload` | Emits the stored row; duplicate suppression now permits new Schwab timestamps even if prices are unchanged. |

No `pending-follow-up` rows remain for this live-plane S017 sub-slice.

## Verification

```text
python -m pytest tests/test_live_market_plane_streaming.py tests/test_fast_lane_contract.py
```

Expected: Schwab quote timestamp drives `fast_server_ts`, server ingestion time remains separately labeled, and unchanged prices with new Schwab time are not suppressed as duplicates.
