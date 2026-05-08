# Schwab Remediation S009 Bid/Ask Spread Contract

**Status:** IMPLEMENTED  
**Slice:** S009 `ASK_MINUS_BID` x `bid_ask`  
**Authority:** `schwab_field_inventory/schwab_field_dictionary.csv`

## CSV-First Declaration

```text
Schwab CSV authority checked: yes
CSV row(s): quotes.quote.bidPrice; quotes.quote.askPrice; chains.callExpDateMap.*.bid; chains.callExpDateMap.*.ask; chains.putExpDateMap.*.bid; chains.putExpDateMap.*.ask
Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE
All consumers checked: yes
```

## Contract

Bid and ask are Schwab-native primitives. Spread is a derived value and must carry explicit unit discipline:

- `spread_pts`: point/dollar width, computed as `ask - bid`.
- `spread`: legacy live-plane field, fractional width `(ask - bid) / midpoint`, retained for adaptive materiality only.
- `price.spread_pts`: canonical MVP feature, must read point spread only.

If either bid or ask is missing, spread fields remain unavailable. No carry-forward or midpoint fabrication is allowed for tradeability decisions.

## Cross-context unit notes (D-S009-02)

The JSON key `spread` is **not** unit-universal:

- **Live plane / REST fast-quote row** (`live_market_plane`, `server._build_rest_fast_quote_payload`): `spread` is **fractional** width \((ask-bid)/midpoint\); `spread_pts` is **point** width.
- **DB snapshot column** `spread` and **option-expression** `oe.spread`: **point** width (same numeric convention as `spread_pts` on the wire).
- **A2 `ms_dict["spread"]`** in the evaluated path: **point** width, because `build_market_state` supplies OE spread, not the raw live-plane quote row.

S009 closure does not require renaming every legacy `spread` field; behavior is consistent when each producer’s contract is honored. **Future hygiene:** a follow-up pass could rename fractional usages to e.g. `spread_frac` everywhere so `spread` never ambiguously means two units — reducing the risk of new code mixing a REST-quote row into an `ms_dict` consumer that expects points.

## All-Consumers Disposition

| Consumer | Status | Evidence | Note |
|---|---|---|---|
| `features.live_feature_adapter.build_live_mvp_feature_row` | fixed-in-this-slice | `features/live_feature_adapter.py::build_live_mvp_feature_row` | Canonical `price.spread_pts` now reads live `spread_pts`, not fractional `spread`. |
| `features.db_feature_adapter.build_db_mvp_feature_row` | already-canonical | `features/db_feature_adapter.py::build_db_mvp_feature_row` | DB snapshot `spread` stores point width; no live fractional field is involved. |
| `live_market_plane.record_quote` | already-fixed | `live_market_plane.py::record_quote` | Emits `spread` fraction and `spread_pts` points separately; no missing bid/ask carry-forward. |
| `server._build_rest_fast_quote_payload` | already-fixed | `server.py::_build_rest_fast_quote_payload` | Emits separate `spread` fraction and `spread_pts` points from Schwab bid/ask. |
| `server._fetch_state` quote spread | already-fixed | `server.py::_fetch_state` | Persists `_quote_spread` as point width and source metadata; missing bid/ask remains unavailable or cached as not tradeable. |
| `server._live_state_tier_a` fallback quote row | already-fixed | `server.py::_live_state_tier_a` | Builds separate `spread` fraction and `spread_pts` points. |
| `math_probabilities.score_option_expression` | already-canonical | `math_probabilities.py::score_option_expression` | Option-expression spread is point width from chain bid/ask and liquidity gate is point-based. |
| `v2_decision.a2_option_expression._spread_from_bid_ask` | already-canonical | `v2_decision/a2_option_expression.py::_spread_from_bid_ask` | A2 spread is point width from selected chain-row bid/ask. |
| `market_state.recommend_option_expression` | already-canonical | `market_state.py::recommend_option_expression` | Uses OE point spread for display/gating. |
| `order_flow_engine` replenishment midpoint | not-applicable | `order_flow_engine.py` replenishment calculation | Queue replenishment analytic, not bid/ask spread width. |
| `call_engine.py` delta/spread wording | not-applicable | `call_engine.py` spread wording | Comment/text from divergence logic, not bid/ask spread construction. |

No `pending-follow-up` rows remain for S009.

## Verification

```text
python -m pytest tests/test_feature_contract_mvp.py tests/test_live_market_plane_streaming.py tests/test_server_quote_source_contract.py tests/test_v2_a2_option_expression.py
```

Expected: live canonical `price.spread_pts` uses `spread_pts`; live fractional `spread` remains separate and unavailable when bid/ask is missing.
