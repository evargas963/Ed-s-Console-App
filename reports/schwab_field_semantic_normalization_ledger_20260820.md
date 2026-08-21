# Schwab Field Semantic Normalization — Canonical Dictionary + Migration Ledger

**Date:** 2026-08-20. **Scope:** native Schwab L1 (LEVELONE_EQUITIES) + L2 (NASDAQ_BOOK / NYSE_BOOK / OPTIONS_BOOK) market-data fields.
**Evidence base:** schwab-py streaming enums (authoritative field numbers), RTH live payloads (`reports/of_capability_probe/20260820T134927Z/`, `options_20260820T1354Z/`), vendor-semantics research (schwab-py docs / FINRA MPID / ISO-10383), and a full repo consumer map.
**Vendor-doc note:** the *community decoders* (schwab-py, jeog, schwab-client-js) describe the BOOK streams as reverse-engineered and decline to transcribe the login-gated book section — but Schwab DOES document these fields in the first-party **Streamer Guide** (developer.schwab.com). The five materially-relevant book subfields are adjudicated **PROVEN** against that source in the M8 addendum (documented name + exact raw-position match). An earlier version of this ledger wrongly called them "undocumented"; that provenance error is corrected in M8/RC-443.

## Canonical field dictionary

| Native field | Service · field# | Vendor definition | RTH example | Units/clock | Class | Ed Console name / consumers | Verdict |
|---|---|---|---|---|---|---|---|
| BID_PRICE/ASK_PRICE/LAST_PRICE | L1 · 1/2/3 | best bid/ask/last | 712.48/712.51/712.49 | price | NATIVE | passed through; top-of-book + tape | **PASS** |
| BID_SIZE/ASK_SIZE/LAST_SIZE | L1 · 4/5/9 | sizes | 280/400/79 | shares | NATIVE | `_top`, tape prints | **PASS** |
| BID_ID/ASK_ID/LAST_ID | L1 · 7/6/16 | "Exchange ID" (single-char) | Q/P/D | code | NATIVE | **not consumed** (dropped at ingest; `NATIVE_AVAILABLE_BUT_NOT_RETAINED`) | **PASS** (received-but-discarded; no mislabel) |
| BID_MIC_ID/ASK_MIC_ID/LAST_MIC_ID | L1 · 40/39/41 | ISO-10383 MIC | XNAS/ARCX/XADF | code | NATIVE | **not consumed** (dropped; `NATIVE_AVAILABLE_BUT_NOT_RETAINED`) | **PASS** (discarded; no mislabel) |
| QUOTE_TIME_MILLIS | L1 · 34 | quote time | 1787233769803 | epoch ms | NATIVE | → `exchange_quote_ts` (÷1000, sec) in `live_market_plane.py`; `quote_time_ms` in capture | **PASS** (renamed from the legacy `fast_server_ts` to the truthful `exchange_quote_ts` this mission; value pinned to this exchange quote clock by the lock — M5/RC-440) |
| TRADE_TIME_MILLIS | L1 · 35 | last-trade time | 1787233769685 | epoch ms | NATIVE | tape dedup (`order_flow_live_state`), `time_millis` window (engine), `trade_time_ms` (capture); labeled QUOTE proxy | **PASS** (fallback now stamped `quote_source_detail["quote_ts"]=TRADE_TIME_MILLIS_proxy`, no silent conflation — M6/RC-440) |
| BID_TIME_MILLIS/ASK_TIME_MILLIS | L1 · 37/38 | bid/ask time | — | epoch ms | NATIVE | stored in `_top`; **never read** (`NATIVE_AVAILABLE_BUT_NOT_RETAINED`) | **PASS** (dead storage; latent, see M7) |
| TOTAL_VOLUME (book level) | Bid/AskFields · 1 | aggregated size at price level | 40/100 | shares | NATIVE | `_compute_book_imbalance` → `book_imbalance_1/3/5` (ONE FAUCET) | **PASS** |
| BOOK_TIME | BookFields · 1 | **Market Snapshot Time** (Schwab Streamer Guide; decoder key `BOOK_TIME`) | 1787233768352 | epoch ms | NATIVE | stored in snapshot; **never read** (`NATIVE_AVAILABLE_BUT_NOT_RETAINED`) | **PROVEN** vendor (Streamer Guide + exact position match — M8/RC-443); catalog `streaming_book` — M3/RC-439 |
| NUM_BIDS/NUM_ASKS | Bid/AskFields · 2 | **Market Maker Count** (Schwab Streamer Guide) | 12 | count | NATIVE | **not consumed** (mock only) | **PROVEN** vendor (position match; value == participant-row count; observed domain = market-maker MPIDs + exchange MICs — M8/RC-443); order-count mislabel still BLOCKED without cited evidence — M4/RC-440 |
| nested EXCHANGE | PerExchangeBid/Ask · 0 | **Market Maker ID** (Schwab Streamer Guide; decoder key `EXCHANGE` is a mislabel) | 'arcx'/'JPMS' | code | NATIVE | **not consumed** | **PROVEN** vendor (Streamer Guide + position match — M8/RC-443); observed domain = MPID namespace (43 codes: market-maker MPIDs AND exchange MICs) — value breadth does not refute the documented name |
| nested BID_VOLUME/ASK_VOLUME | PerExchangeBid/Ask · 1 | **Size** (Schwab Streamer Guide); Σ = level TOTAL_VOLUME | 262 | shares | NATIVE | **not consumed** (`NATIVE_AVAILABLE_BUT_NOT_RETAINED`) | **PROVEN** vendor (position match — M8/RC-443) |
| nested SEQUENCE | PerExchangeBid/Ask · 2 | **Quote Time** (Schwab Streamer Guide; decoder key `SEQUENCE` is a mislabel) | 35368606 (=09:49:28 ET) | ms since ET midnight | NATIVE | **not consumed** | **PROVEN** vendor (Streamer Guide + exact position match; independently confirmed on frames — 1,329/1,329 ∈ [0,86,400,000), freshest 25% within 77 ms of BOOK_TIME — M8/RC-443); catalog `streaming_book` — M3/RC-439 |

## Consumer inventory (proven)

- **Ingest:** `order_flow_streaming.py` `_book_handler` → `order_flow_live_state.push_book` (BIDS/ASKS/BOOK_TIME only); `push_level_one` (prices/sizes/`*_TIME_MILLIS`). L1 IDs/MIC_IDs never extracted.
- **Sole book consumer / ONE FAUCET:** `order_flow_engine._compute_book_imbalance` reads level `TOTAL_VOLUME` → `book_imbalance_1/3/5` → `market_state.book_imbalance_5` → `planes/context_light.py`. No duplicate book-imbalance authority exists.
- **Timestamp consumers:** `live_market_plane.py` (`exchange_quote_ts`), `server.py` aging (`quote_age_sec = now − exchange_quote_ts`), capture `stream_spine.py` (`quote_time_ms`/`trade_time_ms` SQLite columns).
- **Not persisted / not in UI:** `db.py`, `server.py` handlers, `static/index.html` contain **none** of NUM_*, nested EXCHANGE/SEQUENCE, BID/ASK_VOLUME, BOOK_TIME, or the L1 IDs. Only derived `book_imbalance_5` propagates.

## Migration ledger (PASS / FAIL / NOT_PROVEN)

| ID | Defect | Location | Severity | Disposition | Action |
|---|---|---|---|---|---|
| M1 | docstring names `BID_VOLUME/ASK_VOLUME` for a computation that reads level `TOTAL_VOLUME` | `order_flow_engine.py:554` | 🔴 code | **FIXED** (RC-437) | docstring corrected to level `TOTAL_VOLUME` (disclaims nested per-venue); behavior-neutral; owned tests **33 passed**; ONE FAUCET preserved |
| M2 | two reports contradict on nested EXCHANGE (venue-only vs MPIDs-proven) | `of_schwab_live_capability_matrix_20260820.md:48,59-60` vs `of_schwab_rth_capability_closure_20260820.md:62` | 🔴 doc | **FIXED** | both reports reconciled to: *values include registered MPIDs (JPMS/GSCO/VIRT) mixed with venue MICs — presence PROVEN, field's vendor-intended semantics NOT_PROVEN* |
| M3 | `BOOK_TIME` + top-level `SEQUENCE` filed as `streaming_quote` (both book-only; SEQUENCE proven absent at L1) | `schwab_field_dictionary_builder.py`, `schwab_field_dictionary.csv`, `schwab_ablation_field_registry.json` | ⚠️ catalog | **FIXED** (RC-439) | classifier `categorize()` given explicit `\.BOOK_TIME\b`/`\.SEQUENCE\b` → `streaming_book` rules before the `^streaming\.` catch-all; two generated rows corrected; registry regenerated. Cause fixed at the generator, not the row. |
| M4 | `NUM_BIDS/NUM_ASKS` could be read as order/market-maker count (vendor meaning NOT_PROVEN) | repo-wide + `schwab_ablation_field_registry.json` | ⚠️ catalog/semantic | **FIXED** (RC-440) | **mechanical**: enforced check `schwab_market_field_semantics` BLOCKS any code labeling NUM_* an order/MM count without authoritative evidence; generator emits `semantic_caveat` on NUM_* registry entries. |
| M5 | `fast_server_ts` named the exchange QUOTE/TRADE epoch as a "server" clock | `live_market_plane.record_from_level_one_equity`, `server._build_rest_fast_quote_payload`/`_tier_a_live_state_dict` + consumers | 🔴 derived | **FIXED (renamed + value-pinned)** (RC-440) | wire key RENAMED `fast_server_ts` → `exchange_quote_ts` end-to-end (producer, `server.py` REST/SSE, ~9 `static/index.html` consumers, `verification/ui_realtime_transport_audit.py`, tests); the old name is ELIMINATED — no two equivalent authoritative names. The truthful name is KEPT truthful by the enforced check, which BLOCKS assigning any wall clock (`time.time`/`datetime.now`/`monotonic`/`server_received_ts`) to `exchange_quote_ts`; `server_received_ts` remains the real wall clock. Producer documented inline. |
| M6 | QUOTE_TIME/TRADE_TIME conflation (trade time aged as quote time, no distinguishing field) | `live_market_plane.py`, `server._parse_quote_node_session_fields` | 🟡 derived | **FIXED** (RC-440) | producer records `quote_source_detail["quote_ts"]` = `QUOTE_TIME_MILLIS` \| `TRADE_TIME_MILLIS_proxy` \| `unavailable`, threaded into streaming + both REST producers — the TRADE fallback is a labeled proxy, never silent; locked by streaming + contract tests. |
| M7 | dead `BID_TIME_MILLIS/ASK_TIME_MILLIS` storage | `order_flow_live_state.py:148-149` | 🟢 latent | **PASS (no-op)** | classified `NATIVE_AVAILABLE_BUT_NOT_RETAINED` (see below); not a mislabel — left as latent (out of scope for this mission). |
| M8 | book field vendor semantics wrongly declared "undocumented" (provenance error) and documented names refuted from observed value domain | book service (NASDAQ_BOOK/NYSE_BOOK) fields; see addendum | ⚠️ semantic/doc | **RESOLVED — VENDOR-DOCUMENTED** (RC-443) | first-party Schwab Streamer Guide documents all five (Market Snapshot Time / Market Maker Count / Market Maker ID / Size / Quote Time); positions match the raw frames exactly and the distinctive Quote Time is independently confirmed on-frame; schwab-py decoder labels EXCHANGE and SEQUENCE recorded as wrong; observed value-domain breadth (MICs + MPIDs) does not refute the documented names; no field is consumed so no computation path changed |

## ONE FAUCET / duplicate-authority proof

`book_imbalance` has exactly one producer: `order_flow_engine._compute_book_imbalance` from level `TOTAL_VOLUME`. No nested-volume or NUM_*-based imbalance exists. The M1 docstring fix does not add or move any computation authority. No native field is consumed by two disagreeing paths.

## Acceptance table (per materially-relevant field)

Source service: **L1** = LEVELONE_EQUITIES; **BOOK** = NASDAQ_BOOK/NYSE_BOOK/OPTIONS_BOOK. Persistence: **SQLite** = capture columns in `stream_spine.py`; **plane** = in-memory `live_market_plane`/`order_flow_live_state` only (not the 34 GB Collect DB). Semantic authority = the single artifact that defines the meaning.

| Field | Svc·# | Raw name | Vendor meaning | Canonical Ed name | Units/clock | N/D/P | Ingestion | Persistence | Consumer(s) | Semantic authority | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| QUOTE_TIME_MILLIS | L1·34 | QUOTE_TIME_MILLIS | quote time | exchange quote timestamp (`exchange_quote_ts`) | epoch→sec, exchange | NATIVE | yes | plane; SQLite `quote_time_ms` | `server` aging, `static/index.html` quote-lane freshness | this ledger + `check_schwab_market_field_semantics` (M5) | **PASS** |
| TRADE_TIME_MILLIS | L1·35 | TRADE_TIME_MILLIS | last-trade time | trade timestamp / labeled quote proxy | epoch→sec, exchange | NATIVE | yes | plane; SQLite `trade_time_ms` | tape dedup; engine window; `quote_ts` proxy | this ledger + `quote_source_detail["quote_ts"]` (M6) | **PASS** |
| BID_TIME_MILLIS/ASK_TIME_MILLIS | L1·37/38 | *_TIME_MILLIS | bid/ask time | (unretained) | epoch ms | NATIVE | partial (stored, unread) | plane only | none | this ledger | **PASS** (NATIVE_AVAILABLE_BUT_NOT_RETAINED) |
| TOTAL_VOLUME (level) | BOOK·Bid/Ask·1 | TOTAL_VOLUME | aggregated size at level | book level volume | shares | NATIVE | yes | plane | `_compute_book_imbalance`→`book_imbalance_1/3/5` (ONE FAUCET) | `order_flow_engine` | **PASS** |
| BOOK_TIME | BOOK·Book·1 | Market Snapshot Time | book snapshot time (Streamer Guide) | book snapshot time | epoch ms | NATIVE | stored, unread | plane only | none | Schwab Streamer Guide (M8) | **PROVEN** vendor / NATIVE_AVAILABLE_BUT_NOT_RETAINED |
| NUM_BIDS/NUM_ASKS | BOOK·Bid/Ask·2 | Market Maker Count | market maker count (Streamer Guide) | participant-row count (observed domain: MMIDs + venue MICs) | count | NATIVE | no | none | none (mock only) | Schwab Streamer Guide (M8) + lock (M4) | **PROVEN** vendor / PASS guard |
| nested EXCHANGE | BOOK·PerExch·0 | Market Maker ID | market maker id (Streamer Guide; decoder key `EXCHANGE` is a mislabel) | MPID namespace — market makers AND venue MICs (M8) | code | NATIVE | no | none | none | Schwab Streamer Guide (M8) | **PROVEN** vendor / value breadth does not refute the documented name |
| nested BID_VOLUME/ASK_VOLUME | BOOK·PerExch·1 | Size | size (Streamer Guide); Σ = level TOTAL_VOLUME | per-participant displayed size | shares | NATIVE | no | none | none | Schwab Streamer Guide (M8) | **PROVEN** vendor / NATIVE_AVAILABLE_BUT_NOT_RETAINED |
| nested SEQUENCE | BOOK·PerExch·2 | Quote Time | quote time (Streamer Guide; decoder key `SEQUENCE` is a mislabel) | per-participant quote time (ms since ET midnight) | ms/ET-midnight | NATIVE | no | none | none | Schwab Streamer Guide (M8); catalog `streaming_book` | **PROVEN** vendor / independently confirmed on frames |
| BID_ID/ASK_ID/LAST_ID | L1·7/6/16 | *_ID | exchange id (1-char) | (unretained) | code | NATIVE | no (whitelist excl.) | none | none | this ledger | **PASS** (NATIVE_AVAILABLE_BUT_NOT_RETAINED) |
| BID_MIC_ID/ASK_MIC_ID/LAST_MIC_ID | L1·40/39/41 | *_MIC_ID | ISO-10383 MIC | (unretained) | code | NATIVE | no | none | none | this ledger | **PASS** (NATIVE_AVAILABLE_BUT_NOT_RETAINED) |
| — (derived) `exchange_quote_ts` | derived | exchange_quote_ts | — | exchange quote timestamp (renamed from legacy `fast_server_ts` this mission) | epoch sec, exchange | DERIVED (=QUOTE_TIME_MILLIS/sec) | — | plane; not a DB column | `server` aging, frontend | `check_schwab_market_field_semantics` pins value (M5) | **PASS** (truthfully named; value locked) |
| — (derived) `server_received_ts` | derived | server_received_ts | — | server ingest wall clock | epoch sec, server | DERIVED (`time.time()`) | — | plane | staleness cross-checks | producer | **PASS** (correctly named) |

## NATIVE_AVAILABLE_BUT_NOT_RETAINED (Schwab supplies, Ed Console discards)

Not defects — the current product contract does not require retention. Listed so the discard is explicit, not hidden. Reconsider on any future order-flow feature that needs them.

- L1: `BID_ID/ASK_ID/LAST_ID`, `BID_MIC_ID/ASK_MIC_ID/LAST_MIC_ID`, `BID_TIME_MILLIS/ASK_TIME_MILLIS`.
- BOOK: `BOOK_TIME`, top-level `SEQUENCE`, `NUM_BIDS/NUM_ASKS`, nested `EXCHANGE`, nested `BID_VOLUME/ASK_VOLUME`, nested `SEQUENCE`.

## Repo-wide semantic sweep — resolution

A whole-repo sweep (exchange/venue/participant/MPID/order-count/quote-source/sequence/quote-time/trade-time/server-time) found only these material items, all resolved or explicitly bounded:

- **`fast_server_ts` overclaimed "server"** → M5: RENAMED to `exchange_quote_ts` (old name eliminated) and its value mechanically pinned to the exchange quote clock by the lock.
- **`server_ts` morpheme named 4 clocks** (`fast_server_ts` exchange-quote; `server_received_ts` ingest-wall; `server_ts` envelope-wall; `_server_build_ts` build-wall) → the three genuine server clocks keep their names; the one misnomer `fast_server_ts` is now `exchange_quote_ts` (M5). Taxonomy recorded here as the single authority.
- **`quote_ts`/`quote_time` may carry a TRADE time** → M6: labeled proxy provenance, no silent conflation.
- **`quote_time_source` labels the ingestion lane, not the clock** → correct as-is (channel provenance); the *clock* provenance is the new `quote_source_detail["quote_ts"]` (M6). Two distinct axes, no longer conflated.
- **NUM_* vs order count** → M4 lock.
- **"exchange" spans 3 scopes** (instrument-listing venue / quote reporting market-center / per-order participant venue) → the consumed uses (`stream_spine` trade-print venue, Alpaca capture) are correctly named; the unconsumed L1 `EXCHANGE_ID/EXCHANGE_NAME` and BOOK nested `EXCHANGE` are NATIVE_AVAILABLE_BUT_NOT_RETAINED with raw names kept (no overclaim). No same-name/two-meaning collision reaches a consumer. `dealer` (options-hedging) and `seq_len` (ML window) are different domains, not microstructure collisions.

ONE FAUCET preserved: no fix added or moved a computation authority; `book_imbalance` still has exactly one producer from level `TOTAL_VOLUME`.

## Report reconciliation (single source of truth)

**This ledger is the ONE canonical Schwab field dictionary + migration ledger.** The prior capability reports are reconciled to it and carry a SUPERSEDED-BY header pointing here:
- `reports/of_schwab_live_capability_matrix_20260820.md`
- `reports/of_schwab_rth_capability_closure_20260820.md`

No contradictory field semantics remain across the three documents.

## M8 — Book-field vendor semantics: PROVEN against first-party Schwab documentation (2026-08-20 addendum, RC-443)

**Provenance-error correction.** An earlier pass of this addendum concluded the BOOK service was "undocumented at the vendor level" and, on that basis, kept all five NOT_PROVEN and marked the "Market Maker Count / Market Maker ID" candidates REFUTED. That was a **provenance error**: it rested on *reverse-engineered community decoders* (schwab-py, jeog/TDAmeritradeAPI, schwab-client-js) that decline to transcribe the login-gated developer-portal book section — absence of a label in a third-party decoder is not absence of vendor documentation. First-party Schwab documentation for these fields **does exist** and is authoritative.

**First-party source.** The Schwab Trader API **Streamer Guide** (developer.schwab.com; captured as saved portal HTML) documents the BOOK services (NYSE_BOOK / NASDAQ_BOOK / OPTIONS_BOOK) with named fields: book field 1 = **Market Snapshot Time**; price-level field 2 = **Market Maker Count**, field 3 = **Array of Market Makers**; nested field 0 = **Market Maker ID**, field 1 = **Size**, field 2 = **Quote Time**. Provenance is corroborated three ways: (a) the field **positions** are independently reproduced by three community decoders (schwab-py `BookFields/PerExchange*`, allensarkisyan `ORDER_BOOK_EXCHANGE_FIELDS`, schwab-client-js); (b) the positions match our raw RTH frames **exactly**; (c) the single distinctive, empirically-testable label — nested field 2 = **Quote Time** — is confirmed on our frames (ms-since-ET-midnight tracking BOOK_TIME within 77 ms) and *contradicts* every public decoder, which mislabels it "sequence." A table that names nested-2 correctly is sourced from real Schwab field names, not from the public decoders.

**Reasoning discipline (operator ruling).** The documented **vendor field name** is authoritative and is not refuted by a broader **observed value domain**. In Nasdaq TotalView the per-price-level participants are addressed by MPID, and exchange MICs (ARCX/NYSE/IEXG) are themselves market participants in that namespace; the presence of MICs alongside firm MPIDs (JPMS/GSCO/VIRT/MLCO) widens the observed domain but does **not** refute Schwab's documented "Market Maker ID"/"Market Maker Count" names.

**Adjudication** (`field | Schwab documented name | provenance | raw-position match | observed value domain | final status`):

| field | Schwab documented name | provenance | raw-position match | observed value domain | final status |
|---|---|---|---|---|---|
| `BOOK_TIME` (top · 1) | Market Snapshot Time | Streamer Guide (saved portal HTML); positions reproduced by 3 decoders | EXACT — top field 1 = epoch-ms (1787233769563) | book snapshot epoch-ms timestamp | **PROVEN** |
| `NUM_BIDS`/`NUM_ASKS` (level · 2) | Market Maker Count | Streamer Guide; positions reproduced by 3 decoders | EXACT — level field 2 = count, == len(array) (819/819; 31,614/31,614 census) | count of quoting participants (market-maker MPIDs + exchange MICs) | **PROVEN** |
| nested `EXCHANGE` (nested · 0) | Market Maker ID | Streamer Guide; positions reproduced by 3 decoders | EXACT — nested field 0 = participant code | MPID namespace: 43 codes = market-maker MPIDs AND exchange MICs | **PROVEN** (schwab-py decoder label "EXCHANGE" is wrong; vendor name is Market Maker ID) |
| nested `Size` (nested · 1) | Size | Streamer Guide; positions reproduced by 3 decoders | EXACT — nested field 1 = size (Σ = level TOTAL_VOLUME) | per-participant displayed size | **PROVEN** |
| nested `SEQUENCE` (nested · 2) | Quote Time | Streamer Guide + independently confirmed on our frames | EXACT — nested field 2 = ms-since-ET-midnight | per-participant quote time (1,329/1,329 ∈ [0,86,400,000); freshest 25% within 77 ms of BOOK_TIME) | **PROVEN** (schwab-py decoder label "SEQUENCE" is wrong; vendor name is Quote Time) |

**Reproduce** (read-only over the carried RTH capture — confirms the position identities the documentation names): `python -c "import json,glob,datetime as D; et=D.timezone(D.timedelta(hours=-4)); ems=lambda e:(lambda dt:(dt-dt.replace(hour=0,minute=0,second=0,microsecond=0)).total_seconds()*1000)(D.datetime.fromtimestamp(e/1000,et)); rows=[(c['1'],nx['2'],str(nx['0']).upper()) for fn in glob.glob('reports/of_capability_probe/*/frames/*BOOK_*_raw.json') for c in json.load(open(fn))['content'] if c.get('1') for lvl in c.get('2',[]) for nx in lvl.get('3',[])]; vals=[v for _,v,_ in rows]; off=sorted(abs(v-ems(b)) for b,v,_ in rows); print('n=%d in_range=%d/%d freshest25=%.0fms codes=%d'%(len(rows),sum(0<=v<86400000 for v in vals),len(vals),off[len(off)//4],len({c for _,_,c in rows})))"` → `n=1329 in_range=1329/1329 freshest25=77ms codes=43`. Quote-Time confirms nested-2; NUM_*==nested-row-count is 819/819 (and 31,614/31,614 in `capability_matrix.json`).

**Consumption check:** none of the five is consumed by any Ed Console computation (`NATIVE_AVAILABLE_BUT_NOT_RETAINED`), so promoting them to PROVEN changes **no computation path and creates no duplicate authority** — it corrects the canonical semantic record only. The M4 lock is unaffected in behavior: it still requires code that asserts a NUM_* meaning to cite authoritative vendor evidence — evidence that now exists (the Streamer Guide). Two decoder labels are recorded as wrong: schwab-py `EXCHANGE` (vendor: Market Maker ID) and schwab-py `SEQUENCE` (vendor: Quote Time); neither is consumed, so no rename is required.

## Verdict

The Schwab market-data field layer is **semantically clean**: every materially-relevant field has one canonical meaning, correctly named where consumed and explicitly classified `NATIVE_AVAILABLE_BUT_NOT_RETAINED` where discarded. M1–M6 are FIXED; M7 is a no-op latent; M8 is the book-field vendor-semantics reconciliation. Three semantics are **mechanically** enforced (`schwab_market_field_semantics`: NUM_* requires cited vendor evidence for a count claim, `exchange_quote_ts` not a wall clock; M6 proxy provenance in tests). The `fast_server_ts → exchange_quote_ts` wire rename is **COMPLETE** — renamed end-to-end (producer, `server.py` REST/SSE, ~9 `static/index.html` consumers, transport audit, tests) and the old name ELIMINATED; the truthful name is kept truthful by the value-pinning lock. **The five book fields are now PROVEN against first-party Schwab documentation (M8):** the Schwab Streamer Guide (developer.schwab.com; saved portal HTML) documents `BOOK_TIME`=Market Snapshot Time, level field 2=Market Maker Count, nested 0=Market Maker ID, nested 1=Size, nested 2=Quote Time; each matches our raw field positions exactly, and the distinctive Quote-Time label is independently confirmed on our frames. An earlier version of this ledger wrongly called the book service "undocumented" (a provenance error corrected in M8/RC-443); the documented vendor names stand — a broader observed value domain (MPIDs mixed with venue MICs) does not refute them. Nothing consumes these fields, so no computation path changed; schwab-py's decoder labels `EXCHANGE` (→ Market Maker ID) and `SEQUENCE` (→ Quote Time) are recorded as wrong.
