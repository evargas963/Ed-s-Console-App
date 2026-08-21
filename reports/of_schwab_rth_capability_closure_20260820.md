# Definitive RTH Schwab Capability Closure (follow-up)

> **SUPERSEDED-BY (2026-08-20, RC-440):** the single canonical Schwab field dictionary + migration ledger is `reports/schwab_field_semantic_normalization_ledger_20260820.md`. Where any field semantic here differs, the ledger governs. This report is retained as capture evidence only; its field meanings are reconciled to the ledger (`NUM_*` = venue/quote-source count, NOT order/MM count; vendor semantics NOT_PROVEN).

**Host:** the primary Ed Console repo root, live token (`schwab_token.json`, refreshable, untouched).
**Session:** full RTH, US equities open. Main book/L1 capture `2026-08-20T13:49:27Z` (300 s); option capture `~13:54Z` (90 s).
**Symbols:** SPY, QQQ, IWM (equity L1/book); ATM SPY contract **`SPY   260820C00767000`** (strike 767, 0DTE, bid 1.55/ask 1.56, OI 2097, vol 28,408) for options.
**Streamer discipline:** console (sole streamer owner) stopped for the capture window, **restored after** (HTTP 200, `logger_running:true`, 44 tickers).

## Commands / exit codes / artifacts

| Step | Command | Exit | Artifact |
|---|---|---|---|
| Book/L1/TIMESALE (300s) | `python tools/probe_schwab_of_capability_rth.py --symbols SPY,QQQ,IWM --duration-sec 300 --with-levelone-options --max-frames-per-service 12` | 1 (cosmetic `→` stdout crash after write) | `reports/of_capability_probe/20260820T134927Z/` |
| Options contract (90s) | `python <scratchpad>/opt_stream_probe.py --option-symbol "SPY   260820C00767000" --duration-sec 90` | **0** | `reports/of_capability_probe/options_20260820T1354Z/` |

Probe tools reused from PR #168 (open). The probe's REST option-symbol resolver is drift-broken (`safe_get_chain(..., include_underlying_quote=…)` — arg not on `main`; returns httpx `Response`, not `.data`), so the option services were captured by a standalone scratchpad script subscribing the resolved contract directly. *Latent PR-tool bugs: (a) resolver signature drift; (b) non-ASCII stdout crash.*

## Raw live evidence (samples)

**LEVELONE_EQUITIES (QQQ, live):**
```
BID_PRICE=712.48 ASK_PRICE=712.51 LAST_PRICE=712.49
BID_SIZE=280 ASK_SIZE=400 LAST_SIZE=79
BID_ID=Q ASK_ID=P LAST_ID=D                 # single-char exchange IDs (Q=Nasdaq, P=Arca, D=FINRA ADF)
BID_MIC_ID=XNAS ASK_MIC_ID=ARCX LAST_MIC_ID=XADF   # ISO-10383 venue MICs
QUOTE_TIME_MILLIS=1787233769803 BID_TIME_MILLIS=1787233769803
ASK_TIME_MILLIS=1787233769794 TRADE_TIME_MILLIS=1787233769685
TOTAL_VOLUME=4639968   SEQUENCE=<absent at L1>
```
**NASDAQ_BOOK / NYSE_BOOK (live):** `content[]{key,BOOK_TIME,BIDS[],ASKS[]}`; level `{BID_PRICE,TOTAL_VOLUME,NUM_BIDS,BIDS[]}`; nested `{EXCHANGE,BID_VOLUME,SEQUENCE}`. Visible depth: **NYSE_BOOK ≤10 bid/9 ask; NASDAQ_BOOK ≤15/15**.
**OPTIONS_BOOK (SPY 767C, live):** `{key,BOOK_TIME,BIDS,ASKS}`, level `{BID_PRICE:1.28,TOTAL_VOLUME:1746,NUM_BIDS:12}`, nested `{EXCHANGE:'NYSE',BID_VOLUME:262,SEQUENCE:35693547}` — same aggregated venue-attributed shape as equities.

## Section verdicts (PASS / UNAVAILABLE / FAIL / NOT_PROVEN)

### 1. LEVEL 1 — all **PASS** (present live, raw above)
BID/ASK/LAST_PRICE · BID/ASK/LAST_SIZE · BID/ASK/LAST_ID (exchange single-char) · BID/ASK/LAST_MIC_ID (ISO MIC) · QUOTE_TIME_MILLIS · BID_TIME_MILLIS · ASK_TIME_MILLIS · TRADE_TIME_MILLIS · TOTAL_VOLUME — **PASS**. SEQUENCE — **not present at L1** (book-only field); definitively absent.

### 2. LEVEL 2 / BOOK — **PASS** (present); two semantics **NOT_PROVEN**
- Visible price levels, BID/ASK_PRICE, TOTAL_VOLUME, NUM_BIDS/NUM_ASKS, nested EXCHANGE, BID/ASK_VOLUME, SEQUENCE, BOOK_TIME — all **PASS** (live).
- **TOTAL_VOLUME == Σ nested side volumes:** **PASS** — 31,614/31,614 levels equal (0 exceptions) across 300 s RTH.
- **NUM_BIDS/NUM_ASKS meaning:** empirically **PASS** that `NUM_* == count of nested EXCHANGE rows at the level` (31,614/31,614). Vendor definition **NOT_PROVEN** — schwab-py's book enums are self-described as reverse-engineered; Schwab publishes no field definition. *Missing evidence:* Schwab's first-party field spec (login-gated developer.schwab.com). **Not obtainable by further probing** — a probe cannot yield a vendor definition. Do **not** label NUM_* "order count" or "market-maker count."
- **Nested EXCHANGE meaning:** the field carries a **mixed namespace** — 46 distinct RTH codes including true venues (NYSE, ARCX, MEMX, IEXG, MIAX, EDGX, BATY, PHLX…) **and** FINRA-registered market-participant MPIDs (`JPMS`=J.P. Morgan, `GSCO`=Goldman, `VIRT`=Virtu, `RBCD`=RBC, `IMCC`=IMC, plus `mlco`=Merrill pre-market). **PASS** that market-participant identifiers are present (proven by MPID-registry identity). Vendor's formal field definition **NOT_PROVEN** (schwab-py labels it "EXCHANGE" without authority; it is not cleanly exchanges nor cleanly MPIDs). Code `tssm`/`G` unresolved.
- **BOOK_TIME / SEQUENCE characterization:** BOOK_TIME = epoch-ms; **non-monotonic across the merged multi-symbol/multi-service stream** (expected from interleave). SEQUENCE = ascending integer counter (window 35,363,248→35,368,615; 44,708 values). **Per-symbol/per-book monotonicity, scope, and reset behavior: NOT_PROVEN** — the 300 s analysis pooled across symbols and saw no reset boundary. *Missing evidence:* per-symbol time-ordered SEQUENCE/BOOK_TIME isolation over a longer window incl. a session reset. **Obtainable by a further targeted Schwab probe** (per-symbol sequencing). **Therefore add/pull/replenishment/order-of-update analytics are NOT yet safe to build** — gated on that proof.

### 3. LEVEL 3 (market-by-order) — **UNAVAILABLE**
No Schwab streaming service is order-by-order. Full service list (schwab-py / Schwabdev / schwab-client-js, all agree): LEVELONE_EQUITIES, LEVELONE_OPTIONS, LEVELONE_FUTURES, LEVELONE_FUTURES_OPTIONS, LEVELONE_FOREX, NYSE_BOOK, NASDAQ_BOOK, OPTIONS_BOOK, CHART_EQUITY, CHART_FUTURES, SCREENER_EQUITY, SCREENER_OPTION, ACCT_ACTIVITY. None carries unique order IDs, add/cancel/modify events, execution-against-order, or queue position; the `*_BOOK` feeds are price-aggregated (proven by the nested-attribution shape). **UNAVAILABLE.**

### 4. LEVELONE_OPTIONS — **PASS**
Subscribed contract `SPY 260820C00767000`: response **code 0**, **91 frames**, **58 native fields** incl. BID/ASK/LAST + sizes, TOTAL_VOLUME, OPEN_INTEREST, VOLATILITY (IV), DELTA/GAMMA/THETA/VEGA/RHO, MARK, UNDERLYING_PRICE, QUOTE/TRADE_TIME_MILLIS, EXCHANGE_ID/EXCHANGE_NAME. Standard entitlement confirmed live.

### 5. OPTIONS_BOOK — **PASS**
Same contract: response **code 0**, **90 frames**, shape `{BIDS,ASKS,BOOK_TIME}` with the equity-book nesting (`BID_PRICE/TOTAL_VOLUME/NUM_BIDS` → `{EXCHANGE,BID_VOLUME,SEQUENCE}`). Depth is thin per single contract (≤2 levels observed) but the service is entitled and functional.

### 6. TIMESALE — **UNAVAILABLE**
`TIMESALE_EQUITY` SUBS returned **response code 11 "Service not available or temporary down" during active RTH** (0 frames) — same as pre-market and as the 2026-07-22 observation. The RTH re-probe **rules out "temporarily down / after-hours."** Corroboration: TIMESALE is a TD Ameritrade legacy service **not carried forward** by Schwab — absent from schwab-py, Schwabdev, and schwab-client-js service lists. Disposition **UNAVAILABLE** (service not offered). *Residual:* the verbatim code-11 row is in Schwab's login-gated Streamer Guide; classification rests on RTH-active refusal + wrapper absence, not a quoted spec line.

### 7. NATIVE AGGRESSOR SIDE — **UNAVAILABLE**
No aggressor / buyer-vs-seller / uptick-downtick / trade-condition field in any L1, book, chart, or REST surface (schwab-py full enum scan; 300 s payload key-scan found none). Even legacy TDA TIMESALE lacked it. **Ed Console signed-flow (cum_delta/tape) remains PROXY/INFERRED.**

### 8. NOII / AUCTION IMBALANCE — **UNAVAILABLE**
No imbalance/paired-shares/indicative/reference-price service in streaming (13-service list) or REST (Quotes, Chains, Expiration, PriceHistory, Movers, MarketHours, Instruments). 300 s payload key-scan: zero imbalance-like keys. Requires a direct exchange feed (Nasdaq NOII / NYSE Imbalances) — **not obtainable from Schwab.**

### 9. MPID / MMID — **present-but-unlabeled in book; no dedicated field**
Market-participant identifiers **are present** inside the book's nested `EXCHANGE` field: several observed values are FINRA-registered MPIDs (JPMS/GSCO/VIRT/RBCD/IMCC/mlco) — that these specific strings *are* MPIDs is **PROVEN** by the registry. But the field is a **mixed namespace** (venue MICs + participant MPIDs), and whether Schwab *intends* it as participant attribution is **SEMANTICS NOT_PROVEN** (schwab-py labels it `EXCHANGE`, reverse-engineered, no vendor doc). There is **no dedicated/labeled MPID field**, and **no participant ID at L1** (L1 `*_ID`/`*_MIC_ID` are venue/exchange only). Disposition: participant-ID **values present (PASS), field semantics NOT_PROVEN**; a clean dedicated MPID field is **UNAVAILABLE**. *(Reconciles the earlier pre-market matrix report, which saw only 32 mostly-venue codes and understated participant presence.)*

## 10. FINAL L1 / L2 / L3 VERDICT

| Feed | Available to us? | Exact Schwab capability | Granularity | Definitive evidence |
|---|---|---|---|---|
| **Level 1** (top-of-book quotes & trades) | **YES — PASS** | LEVELONE_EQUITIES + LEVELONE_OPTIONS | Top of book: best bid/ask/last, sizes, exchange IDs + ISO MICs, ms timestamps, greeks/IV/OI (options) | Raw frames above; 299 equity + 91 option frames, code 0 |
| **Level 2** (multi-price-level depth) | **YES — PASS** | NYSE_BOOK, NASDAQ_BOOK, OPTIONS_BOOK | Price-aggregated depth (NYSE ≤10, NASDAQ ≤15 levels) with per-participant/venue attribution (nested EXCHANGE + volume) | 300/299/90 frames; TOTAL_VOLUME=Σnested 31,614/31,614 |
| **Level 3** (market-by-order) | **NO — UNAVAILABLE** | none | no order IDs / add / cancel / modify / queue | 13-service enumeration + aggregated book shape |

## 11. NATIVE → DERIVED capability (no implementation)

**NATIVE (observed live):** L1 bid/ask/last prices, sizes, exchange IDs, MICs, four ms timestamps, TOTAL_VOLUME; L2 aggregated depth levels with per-level TOTAL_VOLUME + NUM_* + nested {EXCHANGE, side volume, SEQUENCE} + BOOK_TIME; option greeks/IV/OI/underlying.

**DERIVED — deterministic, safe now (from confirmed native):**
- Top-of-book imbalance (BID_SIZE vs ASK_SIZE)
- Top-3 / Top-5 depth imbalance (level TOTAL_VOLUME)
- Microprice / size-weighted mid (L1 price+size)
- Depth-pressure curve (per-level volumes)
- Book slope / depth decay
- Venue/source concentration & breadth (count + HHI of nested EXCHANGE rows) — describe as *quote-source/participant attribution*, not "order count"
- Size-per-source (nested BID_VOLUME/ASK_VOLUME per EXCHANGE)
- Quote aging (now − BID/ASK/QUOTE/TRADE_TIME_MILLIS)

**DERIVED — GATED, NOT_PROVEN (need SEQUENCE/BOOK_TIME per-symbol ordering proof first):**
- add / pull, replenishment, liquidity persistence, book migration, queue dynamics.

**PROXY / INFERRED (no native support):**
- Aggressor side / signed delta / cumulative delta / trade direction (tick-rule vs NBBO inference only).

## ONE FAUCET
Existing computation authority = `OrderFlowEngine._compute_book_imbalance` (level `TOTAL_VOLUME`). Every DERIVED item above is a **candidate new faucet — not implemented.**

## Restore
Console restarted post-capture: HTTP 200, `logger_running:true`, 44 tickers, streamer slot re-owned. No production logic modified; no unrelated services touched.
