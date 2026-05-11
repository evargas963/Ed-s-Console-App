# Review memo — server.py

**Status:** pending gatekeeper re-review (Evidence bar tightening)  
**Date:** 2026-05-10  
**Reviewer:** Cursor (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)  
**File language family:** python  
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**V4-B code landed (2026-05-10):** Non-canonical chain/quote fallbacks removed in repository: `market_state._oe_chain_row_snapshot` drops **`expiration`** and **`volume`** keys; `server._expiries_from_contracts`, `_selected_schwab_days_to_expiration`, and `_fetch_state` contract filter use **`expirationDate` only**; quote-volume coalesce **drops** `_quote_node["underlying"]["totalVolume"]** (dead arm). **`A2_MARKET_STATE_PROOF_ROW_COMPLETENESS_CONTRACT.md`** + **`tests/test_a2_market_state_proof_row_completeness.py`** updated to match.

---

## Enumeration scope (completeness claim)

Sites **S1–S27** below are the **complete** set of **market-data surfaces in this file** that either:

1. Read **Schwab JSON string keys** present in `schwab_field_inventory/schwab_field_dictionary.csv` (`quotes.*`, `chains.*`, `pricehistory.*`, `streaming.*`), or  
2. Read **streaming** tape/top-of-book dict keys **`LAST_PRICE`**, or  
3. **Pass** Schwab **`q_json` / `c_json`** subtrees into downstream engines where this file is the **last** inline accessor, or  
4. Use **generic** `quote` / `dict` accessors that require a **provenance trace** to the Schwab REST payload (Evidence bar clause **4**).

**Appendix A** lists **NOT_MARKET_DATA** (at the **Schwab wire-token** layer) clusters for remaining control-plane / cache / app dict access **in this file** that do **not** introduce additional Schwab `example_raw_field` string tokens.

**Review complete — no additional Schwab wire-token sites** in `server.py` beyond **S1–S27** and **Appendix A** under the scope above.

---

## Market-data sites identified

### S1 — REST fast quote: `parsed` lineage (`last` / `mark` / `bid` / `ask` / times)

- **lines:** 722–731, 749  
- **surface:** `parsed.last`, `parsed.mark`, `parsed.bid`, `parsed.ask`, `parsed.quote_time`, `parsed.trade_time`; branch labels `"lastPrice"`, `"mark"`.  
- **proposed disposition:** **REPLACED**  
- **provenance trace (clause 4):**  
  `get_client()` → `_safe_get_quote_with_retry(client, tkr)` → **`schwab_client.safe_get_quote`** returns HTTP response → `q_resp.json()` → **`q_json`** Schwab **GET /marketdata/v1/quotes** shaped payload → `parse_quote_payload(tkr, q_json, session_label)` in **`chains.py`** reads `node["quote"]["lastPrice"]`, `bidPrice`, `askPrice`, `mark`, `quoteTime`, `tradeTime` (see `chains.py` memo) → **`QuoteBlock`** fields `last`, `bid`, `ask`, `mark`, `quote_time`, `trade_time`.  
- **canonical_field (specific rows, CSV):**  
  - `quotes.quote.lastPrice`  
  - `quotes.quote.bidPrice` / `quotes.quote.askPrice` (bid/ask family)  
  - `quotes.quote.mark`  
  - Time fields: `quotes.quote.quoteTime`, `quotes.quote.tradeTime` (same CSV; `example_raw_field` uses `SPY.quote.*` pattern).  
- **code edit:** none — names already align with Schwab JSON via `parse_quote_payload`.

### S2 — Tier A live REST bootstrap: same `parse_quote_payload` lineage

- **lines:** 2754–2760  
- **surface:** `q_resp.json()` → `pq = parse_quote_payload(...)` → `pq.last` / `pq.mark` / `pq.bid` / `pq.ask`; labels `"lastPrice"`, `"mark"`.  
- **proposed disposition:** **REPLACED**  
- **provenance trace:** Same as **S1**; `q_json` from `_safe_get_quote_with_retry` Schwab REST.  
- **canonical_field:** Same set as **S1**.  
- **code edit:** none.

### S3 — `_fetch_state` core quote parse + spot/bid/ask

- **lines:** 2957–2967, 3084 (`_tick_ts`)  
- **surface:** `parsed.last`, `parsed.mark`, `parsed.bid`, `parsed.ask`, `parsed.quote_time`, `parsed.trade_time`.  
- **proposed disposition:** **REPLACED**  
- **provenance trace:** `q_resp = _safe_get_quote_with_retry(client, ticker)` → `q_json = q_resp.json()` → `parse_quote_payload(ticker, q_json, session_label)` → `QuoteBlock`.  
- **canonical_field:** **S1** set.  
- **code edit:** none.

### S4 — API response `quote_source_detail` string labels (diagnostic, not generic accessors)

- **lines:** 786–789, 2780–2784, 3071–3075, 4384–4387  
- **surface:** Python string literals `"lastPrice"`, `"mark"`, `"bidPrice"`, `"askPrice"` inside `quote_source_detail` / error payloads.  
- **proposed disposition:** **NOT_MARKET_DATA** (Schwab **wire read**) — these lines **do not** subscript Schwab JSON; they record **which** Schwab field names were used upstream. Semantic reason: **telemetry / UI diagnostic strings**, not live `q_json[...]` access.  
- **evidence:** Context inspection at each line block — values are assigned into **outgoing** `dict`s, not read from `q_json`.

### S5 — REST cum-delta: generic `quote` dict (**clause 4** trace required)

- **lines:** 2162–2165, 3682–3686 (caller)  
- **surface:** `quote.get("lastPrice")`, `quote.get("lastSize")`, `quote.get("bidPrice")`, `quote.get("askPrice")`.  
- **proposed disposition:** **REPLACED**  
- **provenance trace:** `_update_rest_cum_delta(ticker, _quote_for_cum, now_et)` where `_quote_for_cum = dict(_order_flow_data["extended"]) merged with `dict(_order_flow_data["quote"])` (**L3684–3685**). `_order_flow_data` built **L3638–3656** from `_q_node = q_json.get(ticker.upper()) or q_json.get(ticker) or q_json` with `_q_node.get("quote")`, `.get("extended")` — and `q_json` is the **same** Schwab REST quote payload as **S3** (`_fetch_state` **L2957–2960**). Therefore `quote` **is** a slice of **Schwab REST equity quote JSON** (extended+quote arms), not an arbitrary internal dataclass.  
- **canonical_field:**  
  - `quotes.quote.lastPrice`  
  - `quotes.quote.lastSize`  
  - `quotes.quote.bidPrice`  
  - `quotes.quote.askPrice`  
  (Extended session uses the same key names under `quotes.extended.*` in CSV; access here is merged `quote`+`extended` dicts.)  
- **code edit:** none.

### S6 — Chain underlying volume (`totalVolume`) + `regularMarketVolume`

- **lines:** 2949–2954  
- **surface:** `_chain_underlying = c_json.get("underlying")` → `.get("totalVolume")`, `.get("regularMarketVolume")`.  
- **provenance trace:** `c_resp = safe_get_chain(client, ticker, ...)` (**L2928–2934**) → `c_json = c_resp.json()` Schwab **options chain** JSON.  
- **proposed disposition:**  
  - **`totalVolume`:** **REPLACED** — `chains.underlying.totalVolume`.  
  - **`regularMarketVolume`:** **NO_SCHWAB_EQUIVALENT** — token grep on `schwab_field_inventory/schwab_field_dictionary.csv` → **0** rows for substring `regularMarketVolume`.  
- **Four-channel exhaustion (`regularMarketVolume`):**  
  1. **Token:** no CSV hit (above).  
  2. **Category:** inspected `volume` / `order_flow_proxy` rows under `quotes.*` and `chains.underlying.totalVolume`.  
  3. **likely_use:** `order_flow_proxy` (volume).  
  4. **Embedding top-K:** `sentence-transformers` **`all-MiniLM-L6-v2`** over all **`canonical_field`** strings; query `regularMarketVolume`; **K=12** results in **`governance/artifacts/schwab_v4_embedding_topk_volume_surfaces_20260510.json`** (top-1 `quotes.regular.regularMarketPercentChange`, score **0.540343** — **not** an equivalent field identity). Reproduce:  
     `python -m tools.schwab_canonical_field_embedding_topk --queries regularMarketVolume quotes.regular.totalVolume quotes.reference.totalVolume -k 12 --out governance/artifacts/schwab_v4_embedding_topk_volume_surfaces_20260510.json`  
- **code edit:** none for `regularMarketVolume` read — disposition stays **NO_SCHWAB_EQUIVALENT** until dictionary row exists or replacement strategy is coded.

### S7 — Quote-node volume fallbacks (`totalVolume` / `regularMarketVolume`)

- **lines:** 2984–3006 *(post-change: `_underlying_node` arm **removed** — no `quote` payload `underlying.totalVolume` coalesce)*  
- **surface:** `_quote_dict.get("totalVolume")`, `.get("regularMarketVolume")`, `_regular.get("totalVolume")`, `.get("regularMarketVolume")`, `_extended.get("totalVolume")`, `_reference.get("totalVolume")`.  
- **provenance trace:** `_quote_node` from **`q_json`** (same REST payload as **S3**).  
- **proposed disposition:**  
  - **`_quote_dict.get("totalVolume")`:** **REPLACED** — `quotes.quote.totalVolume`.  
  - **`_extended.get("totalVolume")`:** **REPLACED** — `quotes.extended.totalVolume`.  
  - **`_quote_dict.get("regularMarketVolume")`, `_regular.get("regularMarketVolume")`:** **NO_SCHWAB_EQUIVALENT** — channel record tied to **S6** artifact query `regularMarketVolume`.  
  - **`_regular.get("totalVolume")`, `_reference.get("totalVolume")`:** **NO_SCHWAB_EQUIVALENT** — no CSV rows `quotes.regular.totalVolume` / `quotes.reference.totalVolume`. Embedding queries `quotes.regular.totalVolume` and `quotes.reference.totalVolume` in the **same JSON artifact**; **no** returned top-K row equals those hypothetical paths (closest: `quotes.extended.totalVolume` / `quotes.quote.totalVolume` — **different** canonical identities).  
- **code edit:** **landed** — removed erroneous cross-payload `underlying.totalVolume` read from equity **quote** JSON.

### S8 — Price-history candle seeds (`candles` list dicts)

- **lines:** 3092–3101  
- **surface:** `resp_*.json().get("candles", [])` then dict keys consumed in **`chains`-compatible** candle shape via `seed()`; `seed` uses `b["open"]`, `b["high"]`, `b["low"]`, `b["close"]`, `b["volume"]`, `b.get("datetime", ...)` (**L1117–1124** in this file for `CandleAggregator.seed`).  
- **provenance trace:** `safe_get_price_history(client, ticker, ...)` → Schwab **pricehistory** JSON.  
- **proposed disposition:** **REPLACED**  
- **canonical_field:** `pricehistory.candles.*.open`, `.high`, `.low`, `.close`, `.volume`, `.datetime` (CSV rows ~2224–2231).  
- **code edit:** none.

### S9 — Price-history volume for `_c_vol` selection

- **lines:** 3694–3714  
- **surface:** `ph_candles = resp_ph.json().get("candles", [])`, `best.get("volume")`, `ph_candles[-1].get("volume")`, `b.get("datetime", 0)`.  
- **provenance trace:** `safe_get_price_history` Schwab REST → `candles` array.  
- **proposed disposition:** **REPLACED** — `pricehistory.candles.*.volume`, `.datetime`.  
- **code edit:** none.

### S10 — Order-flow payload: quote / extended / regular / reference / fundamental + chain maps

- **lines:** 3640–3656  
- **surface:** `_q_node.get("quote"|"extended"|"regular"|"fundamental"|"reference")`; `c_json.get("callExpDateMap"|"putExpDateMap"|"underlying")`.  
- **provenance trace:** `_q_node` from **`q_json`** (**S3**); `c_json` from **`safe_get_chain`** (**S6**).  
- **proposed disposition:** **REPLACED** — subtree keys are Schwab API arms / chain maps (`chains.callExpDateMap`, `chains.putExpDateMap`, `chains.underlying` in CSV).  
- **code edit:** none — pass-through to `OrderFlowEngine` / accumulators.

### S11 — Streaming spot `LAST_PRICE` (**generic** content dict — clause 4)

- **lines:** 914–934  
- **surface:** `top.get("LAST_PRICE")`, `item.get("LAST_PRICE")`, `float(top["LAST_PRICE"])`, `float(item["LAST_PRICE"])`.  
- **provenance trace:** `get_content_for_symbol(symbol)` / `get_top_of_book(symbol)` from **`order_flow_live_state`** → streaming plane filled from **Schwab streaming** Level I content; dictionary rows `streaming.content.*.LAST_PRICE` (`example_raw_field` `content.1.LAST_PRICE`).  
- **proposed disposition:** **REPLACED**  
- **canonical_field:** `streaming.content.*.LAST_PRICE`  
- **code edit:** none.

### S12 — `_selected_schwab_days_to_expiration` + `_expiries_from_contracts` contract scans

- **lines:** 2025–2031 (`_expiries_from_contracts` exp scan), 2048–2073 (`_selected_schwab_days_to_expiration`)  
- **surface:** `ct.get("expirationDate")`, `ct.get("putCall")`, `ct.get("strikePrice")`, `ct.get("daysToExpiration")` — **`expiration` alias fallback removed** (canonical leaf only).  
- **provenance trace:** `contracts` are **`contract_fields`** outputs from **`iter_contracts(c_json)`**; `c_json` from **`safe_get_chain`** (Schwab chain).  
- **proposed disposition:** **REPLACED**  
- **canonical_field:** `chains.callExpDateMap.*.expirationDate`, `.putCall`, `.strikePrice`, `.daysToExpiration`  
- **code edit:** **landed** — stripped `or ct.get("expiration")`.

### S13 — Exposure pipeline contract selection (expiration filter)

- **lines:** 3051–3052 (`filtered = [ct for ct in contracts if …]`)  
- **surface:** `(ct.get("expirationDate") or "")[:10] == selected_exp` — **`expiration` alias removed**.  
- **proposed disposition:** **REPLACED**  
- **canonical_field:** `chains.callExpDateMap.*.expirationDate`  
- **code edit:** **landed**.

### S14 — ATM straddle marks from contracts

- **lines:** 3256–3271  
- **surface:** `ct.get("strikePrice")`, `ct.get("putCall")`, `_atm_calls[0].get("mark")`, `_atm_puts[0].get("mark")`.  
- **provenance trace:** `contracts_use` from Schwab chain (**S6**) via `contract_fields`.  
- **proposed disposition:** **REPLACED**  
- **canonical_field:** `chains.callExpDateMap.*.strikePrice`, `.putCall`, `.mark`  
- **code edit:** none.

### S15 — Missing spot error copy (prose reference to Schwab fields)

- **lines:** 3064, 4385 (labels)  
- **surface:** string content `"lastPrice"`, `"mark"` in error/detail payloads.  
- **proposed disposition:** **NOT_MARKET_DATA** (wire read) — diagnostic text only (same rationale as **S4**).

### S16 — `fetch_price_levels(..., quote_raw=q_json)` (Schwab quote payload boundary)

- **lines:** 3229, 6367–6369  
- **surface:** passes **`q_json`** into **`fetch_price_levels`**.  
- **provenance trace:** `q_json` from Schwab REST quote fetch in `_fetch_state` / `/api/price-levels` handler.  
- **proposed disposition:** **NOT_MARKET_DATA** **in this file** for subscript tokens — **delegation**; Schwab wire parsing occurs under **`market_context` / `math_levels` / price-level engine** (separate file memo). This site records **payload handoff**.  
- **evidence:** No additional field **literals** at callsite beyond parameter binding.

### S17 — `underlyingPrice` (debug charm endpoint)

- **lines:** 6755–6761  
- **surface:** `chain_json.get("underlyingPrice")`  
- **provenance trace:** `chain_json = c_resp.json()` from `safe_get_chain`.  
- **proposed disposition:** **REPLACED**  
- **canonical_field:** `chains.underlyingPrice`  
- **code edit:** none.

### S18 — Debug charm contract gamma / OI probes

- **lines:** 6745–6748  
- **surface:** `ct.get("expirationDate")`, `ct.get("daysToExpiration")`, `ct.get("gamma")`, `ct.get("openInterest")`  
- **proposed disposition:** **REPLACED**  
- **canonical_field:** `chains.callExpDateMap.*.gamma`, `.openInterest`, `.expirationDate`, `.daysToExpiration`  
- **code edit:** none.

### S19 — `first_raw.keys()` (inspection only)

- **lines:** 6741–6742  
- **proposed disposition:** **NOT_MARKET_DATA** — introspection of raw Schwab dict keys for debug output; no disposition claim on unseen keys.

### S20 — `_compute_vwap_from_bars` attribute access

- **lines:** 2191–2196  
- **surface:** `getattr(b, 'volume'|'high'|'low'|'close')` on **bar objects**  
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab **literal** layer — **normalized bar objects** / OHLCV model, not raw `q_json` keys in this stanza. Upstream seed data for these bars is loaded via **S8** / **S9** Schwab **pricehistory** when that path runs; **this** function only reads **bar object** attributes.

### S21 — `CandleAggregator.tick` / internal `cur["v"]`

- **lines:** 1088–1102  
- **proposed disposition:** **NOT_MARKET_DATA** — internal accumulator dict keys `v`, `o`, `h`, `l`, `c`.

### S22 — `_stream_spot_and_of_regime` regime via `OrderFlowEngine.compute`

- **lines:** 936–939  
- **surface:** `of_result.get("order_flow_regime")`  
- **proposed disposition:** **NOT_MARKET_DATA** — engine output key, not Schwab wire.

### S23 — L1 overlay `vq.get("spot")` / `row.get("spot")` (live plane)

- **lines:** 2525–2535, 2753, 2802  
- **proposed disposition:** **NOT_MARKET_DATA** — keys are **application plane** field names (`spot`, `spread`), not Schwab `lastPrice` / `bidPrice` strings.

### S24 — `_tier_a_live_state_dict` reads `row.get("bid")`, `row.get("ask")` (**L2815–2816**)

- **proposed disposition:** **NOT_MARKET_DATA** — `row` is **live plane** dict using short keys `bid`/`ask` for **floats** already extracted from Schwab upstream; no `bidPrice`/`askPrice` literals at this read site.

### S25 — `ms_dict` / analytics lightweight mirror (`spy_last`, etc.)

- **lines:** 2876–2889  
- **proposed disposition:** **NOT_MARKET_DATA** — snapshot/UI mirror keys; not Schwab wire tokens.

### S26 — `raw_levels` / playbook display tags

- **lines:** 6375–6408  
- **proposed disposition:** **NOT_MARKET_DATA** — internal tag map for UI (`PDH`, `VWAP`, …), not Schwab JSON.

### S27 — Playbook session bars (`fetch_bars_via_schwab_for_session`)

- **lines:** 6701–6703  
- **proposed disposition:** **NOT_MARKET_DATA** for **inline wire tokens** — Schwab bar JSON parsed inside **`polling_adapter.fetch_bars_via_schwab_for_session`** (memo that file separately).

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

Bulk **NOT_MARKET_DATA** at Schwab **example_raw_field** token layer: L1/SSE diagnostics, logging universe sync, DB snapshot **metadata**, prediction override API, `/api/health`, accuracy cache, `ms_dict` model-availability flags, stack runtime attachments, **internal** candle accumulator keys, **order_flow_regime** output, **live plane** short keys (`spot`, `bid`, `ask` without `*Price` suffix), UI throttle payloads, and **delegated** price-level / playbook bar fetch **without** inline Schwab key literals at the callsite (**S16**, **S27**).

---

## Aggregate disposition for inventory

- **status:** pending (memo resubmitted; inventory row **not** `reviewed` until gatekeeper acceptance)  
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/server.py.md  
