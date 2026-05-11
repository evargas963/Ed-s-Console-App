# Review memo — chains.py

**Status:** pending gatekeeper re-review (Evidence bar tightening)  
**Date:** 2026-05-10  
**Reviewer:** Cursor (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)  
**File language family:** python  
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

---

## Enumeration completeness

**S1** covers **all** `q.get("…")` accesses in `parse_quote_payload`.  
**S2** covers **all** `ct.get("…")` keys returned from `contract_fields` (one row per key, same disposition family).  
**S3** covers `iter_contracts` map keys.  

**Review complete — no further Schwab wire-token sites** in `chains.py`.

---

## Market-data sites identified

### S1 — `parse_quote_payload` (`quote_json` → `QuoteBlock`)

- **lines:** 28–44  
- **surface:** `node = quote_json.get(ticker.upper()) or quote_json.get(ticker) or {}`; `q = node.get("quote", {}) or {}`; `q.get("lastPrice"|"bidPrice"|"askPrice"|"mark"|"quoteTime"|"tradeTime")`.  
- **proposed disposition:** **REPLACED**  
- **provenance trace (clause 4 — generic `quote_json`):** Callers **`server.py`** pass **`q_resp.json()`** from **`schwab_client.safe_get_quote`** (Schwab **GET /marketdata/v1/quotes** family). Therefore `quote_json` **is** the Schwab multi-symbol quote JSON at the API boundary.  
- **canonical_field (each key):**  
  - `quotes.quote.lastPrice`  
  - `quotes.quote.bidPrice`  
  - `quotes.quote.askPrice`  
  - `quotes.quote.mark`  
  - `quotes.quote.quoteTime`  
  - `quotes.quote.tradeTime`  
- **code edit:** none.

### S2 — `contract_fields` normalized option dict (every `ct.get` key)

- **lines:** 65–112  
- **surface:** all keys in the returned dict (each `ct.get("<field>")` on raw **Schwab chain** contract object `ct`).  
- **provenance trace:** `ct` yielded by `iter_contracts(chain_json)` where `chain_json` is **`safe_get_chain(...).json()`** in **`server.py`** — Schwab **options chain** payload.  
- **proposed disposition:** **REPLACED** for every field below — each has a matching `chains.callExpDateMap.*.<field>` or symmetric `putExpDateMap` row in `schwab_field_inventory/schwab_field_dictionary.csv` (same leaf name).  

| Key returned | canonical_field row (representative) |
|--------------|----------------------------------------|
| `putCall` | `chains.callExpDateMap.*.putCall` |
| `strikePrice` | `chains.callExpDateMap.*.strikePrice` |
| `openInterest` | `chains.callExpDateMap.*.openInterest` |
| `delta` | `chains.callExpDateMap.*.delta` |
| `gamma` | `chains.callExpDateMap.*.gamma` |
| `theta` | `chains.callExpDateMap.*.theta` |
| `vega` | `chains.callExpDateMap.*.vega` |
| `rho` | `chains.callExpDateMap.*.rho` |
| `theoreticalVolatility` | `chains.callExpDateMap.*.theoreticalVolatility` |
| `theoreticalOptionValue` | `chains.callExpDateMap.*.theoreticalOptionValue` |
| `volatility` | `chains.callExpDateMap.*.volatility` |
| `daysToExpiration` | `chains.callExpDateMap.*.daysToExpiration` |
| `expirationDate` | `chains.callExpDateMap.*.expirationDate` |
| `expirationType` | `chains.callExpDateMap.*.expirationType` |
| `settlementType` | `chains.callExpDateMap.*.settlementType` |
| `exerciseType` | `chains.callExpDateMap.*.exerciseType` |
| `lastTradingDay` | `chains.callExpDateMap.*.lastTradingDay` |
| `multiplier` | `chains.callExpDateMap.*.multiplier` |
| `mark` | `chains.callExpDateMap.*.mark` |
| `bid` | `chains.callExpDateMap.*.bid` |
| `ask` | `chains.callExpDateMap.*.ask` |
| `last` | `chains.callExpDateMap.*.last` |
| `openPrice` | `chains.callExpDateMap.*.openPrice` |
| `highPrice` | `chains.callExpDateMap.*.highPrice` |
| `lowPrice` | `chains.callExpDateMap.*.lowPrice` |
| `closePrice` | `chains.callExpDateMap.*.closePrice` |
| `totalVolume` | `chains.callExpDateMap.*.totalVolume` |
| `bidSize` | `chains.callExpDateMap.*.bidSize` |
| `askSize` | `chains.callExpDateMap.*.askSize` |
| `bidAskSize` | `chains.callExpDateMap.*.bidAskSize` |
| `lastSize` | `chains.callExpDateMap.*.lastSize` |
| `quoteTimeInLong` | `chains.callExpDateMap.*.quoteTimeInLong` |
| `tradeTimeInLong` | `chains.callExpDateMap.*.tradeTimeInLong` |
| `extrinsicValue` | `chains.callExpDateMap.*.extrinsicValue` |
| `timeValue` | `chains.callExpDateMap.*.timeValue` |
| `intrinsicValue` | `chains.callExpDateMap.*.intrinsicValue` |
| `inTheMoney` | `chains.callExpDateMap.*.inTheMoney` |
| `nonStandard` | `chains.callExpDateMap.*.nonStandard` |
| `mini` | `chains.callExpDateMap.*.mini` |
| `pennyPilot` | `chains.callExpDateMap.*.pennyPilot` |
| `deliverableNote` | `chains.callExpDateMap.*.deliverableNote` |
| `symbol` | `chains.callExpDateMap.*.symbol` |

- **code edit:** none.

### S3 — `iter_contracts` walk of `callExpDateMap` / `putExpDateMap`

- **lines:** 47–63  
- **surface:** `chain_json.get(side_key)` for `side_key in ("callExpDateMap", "putExpDateMap")`.  
- **proposed disposition:** **REPLACED**  
- **canonical_field:** `chains.callExpDateMap`, `chains.putExpDateMap` (and `chains.callExpDateMap.*` pattern rows).  
- **provenance trace:** `chain_json` is Schwab **options chain** JSON (**S2**).  
- **code edit:** none.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)  
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/chains.py.md  
