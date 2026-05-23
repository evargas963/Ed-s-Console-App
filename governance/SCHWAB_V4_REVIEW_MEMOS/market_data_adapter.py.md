> **Classification:** Policy Specification | **Scope:** Governance documentation `market_data_adapter.py.md`.

# Review memo — market_data_adapter.py

**Status:** pending gatekeeper re-review  
**Date:** 2026-05-10  
**Reviewer:** Cursor (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)  
**File language family:** python  
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

---

## Enumeration completeness

**S1** — `schwab_candles_to_bars` (Schwab pricehistory candle dict keys).  
**S2** — `normalize_bar` / `normalize_bars` (multi-provider, generic `raw`).

**Review complete** for this file under those two sites.

---

## Market-data sites identified

### S1 — `schwab_candles_to_bars`

- **lines:** 118–147  
- **surface:** For each candle dict `c`: `c.get("datetime")`, `c["open"]`, `c["high"]`, `c["low"]`, `c["close"]`, `c.get("volume")`.  
- **proposed disposition:** **REPLACED**  
- **provenance trace:** Callers pass **`safe_get_price_history` → `.json()["candles"]`** Schwab **pricehistory** array elements.  
- **canonical_field:** `pricehistory.candles.*.datetime`, `.open`, `.high`, `.low`, `.close`, `.volume`  
- **code edit:** none.

### S2 — `normalize_bar` / `normalize_bars`

- **lines:** 43–100 (`normalize_bar`), 103–110 (`normalize_bars`)  
- **surface:** `raw.get("open"|"high"|"low"|"close"|"volume"|"vol"|"timestamp"|"datetime"|"t"|"time")`, `getattr(raw, …)`, aliases `o`/`h`/`l`/`c`.  
- **proposed disposition:** **UNREVIEWED**  
- **evidence:** Docstring names **Schwab, Polygon, Alpaca, generic**. Evidence bar clause **4** requires a **payload-bound** trace per call site; this function has **no** single Schwab API boundary. Closure requires **typed per-provider entrypoints** or operator **`GOVERNED_EXCEPTION (O-NN)`** for the shared adapter — **not** a qualified NOT_MARKET_DATA variant.  
- **code edit:** deferred — add provider-specific wrappers or register **O-NN** before closure.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)  
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/market_data_adapter.py.md  
