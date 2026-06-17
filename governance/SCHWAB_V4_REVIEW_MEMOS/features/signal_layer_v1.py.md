> **Classification:** Policy Specification | **Scope:** Governance documentation `features/signal_layer_v1.py.md`.

# Review memo — features/signal_layer_v1.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Cursor (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**Evidence bar:** V4-A + AGENTS gatekeeper CSV cross-check @ `977e706`

**Class A:** Full Read (735 lines). No in-file Schwab JSON subscripts. Bar OHLCV keys are internal `price_bars_1m` row / aggregated bar dict namespace (LEAF chain: `polling_adapter.py.md` / backfill → `pricehistory.candles.*`). Paired tests: `tests/test_signal_layer_v1.py`, `tests/test_action12_13_signal_layer_v1_fail_closed.py`.

---

## Gatekeeper CSV cross-check

**Tool:** `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck features/signal_layer_v1.py`
**lexical_csv_collision_count:** 82

**Bulk classification:** All collisions are **HOMONYM** — standard OHLCV bar dict keys (`open`, `high`, `low`, `close`, `volume`, `_prev_close`) on `Mapping[str, Any]` bars loaded from SQLite `price_bars_1m` (`load_bars_before_decision`) or synthetic aggregation (`_aggregate_bars`). CSV would suggest `pricehistory.candles.*` / screener volume; this file never subscripts Schwab wire JSON. **Zero wire reads.**

---

## Disposition summary

| Section | Lines | Disposition |
|---------|-------|-------------|
| Bar load + compute | L238–610 | **NOT_MARKET_DATA** @ wire — DB bar rows + derived feature keys (`ps.*`, `vl.*`, `vol.*`, `cnd.*`, `mtf.*`, `part.*`) |
| Fusion helpers | L657–734 | **NOT_MARKET_DATA** — numeric layer → direction probs |

**code edit:** none.
