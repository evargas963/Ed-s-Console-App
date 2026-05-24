> **Classification:** Policy Specification | **Scope:** Governance documentation `live_market_plane.py.md`.

# Review memo — live_market_plane.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**Closest-shape precedent** (per `AGENTS.md` Posture rules — sibling-pattern conformance, 2026-05-24): `polling_adapter.py.md` — producer-side file, mixed-disposition shape (some sites NOT_MARKET_DATA at Schwab wire-token layer, one site REPLACED for explicit Schwab JSON subscripts, downstream overlay/projection sites NOT_MARKET_DATA per `signals.py.md` S3 rule). Streaming-key handling pattern matches `server.py.md` S11 (`top.get("LAST_PRICE")` / `item.get("LAST_PRICE")` → canonical `streaming.content.*.LAST_PRICE`).

**Audit catch flagged (S2a):** Two non-canonical fallback keys on L97–98 — `or _positive_float(item.get("BID"))` and `or _positive_float(item.get("ASK"))`. Bare `"BID"` / `"ASK"` are **not** rows in `schwab_field_inventory/schwab_field_dictionary.csv` (only `streaming.content.*.BID_PRICE` L2338 and `streaming.content.*.ASK_PRICE` L2323 / L2318 are catalogued). **Closed:** fallbacks removed in fix-as-we-find slice with paired test (see S2a below).

---

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** for:

| Channel | Method |
|---------|--------|
| String-literal dict access | `item.get("LAST_PRICE")` (L95), `item.get("MARK")` (L96), `item.get("BID_PRICE")` (L97, L108), `item.get("BID")` (L97), `item.get("ASK_PRICE")` (L98, L109), `item.get("ASK")` (L98), `item.get("QUOTE_TIME_MILLIS")` (L115), `item.get("TRADE_TIME_MILLIS")` (L116) |
| Bracket dict access on Schwab payloads | None (all access via `.get(...)`) |
| Attribute access on market-bearing objects | None (only on Python primitives and module dicts `_by_ticker` / `_fast_lane_gen_by_ticker` / `_last_sse_pushed_gen`) |
| Method calls passing Schwab market objects | None — `notify_quote_updated(t)` (L190, L206) passes only the ticker symbol, no payload |
| Internal projection-key reads (NOT Schwab wire) | `q.get("spot")`, `q.get("bid")`, `q.get("ask")`, `q.get("spot_disp")`, `q.get("bid_disp")`, `q.get("ask_disp")`, `q.get("quote_mid")`, `q.get("mid_source")`, `q.get("spread")`, `q.get("spread_pts")`, `q.get("spread_source")`, `q.get("spread_pts_source")`, `q.get("quote_ingestion")`, `q.get("fast_server_ts")`, `q.get("fast_generation_id")` (S5 / S6 / S7 overlay loops) — these are internal plane projection keys, NOT Schwab wire tokens |

**Review complete:** Every site **in this file** falls under **S1–S8** below; no other Schwab `example_raw_field` tokens or chain JSON subscripts occur in `live_market_plane.py`.

---

## Market-data sites identified

### S1 — Module helpers + state

- **lines:** L22–82 — module imports (L22–25); `log` (L27); thread locks `_lock`, `_gen_lock` (L31, L37); module dicts `_by_ticker`, `_last_sse_pushed_gen`, `_fast_lane_gen_by_ticker` (L33, L35, L38); `next_fast_generation` (L41–47); `_safe_float` (L50–59); `_plane_tuple_sig` (L62–67); `_positive_float` (L70–74); `_epoch_seconds_from_millis` (L77–81).
- **surface:** Python primitives, threading locks, type coercion. No Schwab JSON keys read.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — utility scaffolding for the plane; no tokens match any row in `schwab_field_inventory/schwab_field_dictionary.csv`.
- **code edit:** none.

### S2 — `record_from_level_one_equity` (Schwab streaming LEVEL_ONE_EQUITY ingest)

- **lines:** L84–193. Canonical key reads L95–98, L115–116. Cache compare L100–126. Diagnostic source labels L107–109. Spread/mid derivation L128–141. Output dict assembly L143–184. Plane write + notify L185–192.
- **surface — canonical Schwab streaming reads:**
  - **L95:** `last = _positive_float(item.get("LAST_PRICE"))` → `streaming.content.*.LAST_PRICE` (dict L2359).
  - **L96:** `mark = _positive_float(item.get("MARK"))` → `streaming.content.*.MARK` (dict L2364).
  - **L97 primary:** `_positive_float(item.get("BID_PRICE"))` → `streaming.content.*.BID_PRICE` (dict L2338).
  - **L98 primary:** `_positive_float(item.get("ASK_PRICE"))` → `streaming.content.*.ASK_PRICE` (dict L2323).
  - **L108:** `bid_source = "BID_PRICE" if _positive_float(item.get("BID_PRICE")) is not None else ("BID" if bid is not None else None)` — diagnostic label string, same primary read as L97.
  - **L109:** mirror of L108 for `ask_source`.
  - **L115:** `_epoch_seconds_from_millis(item.get("QUOTE_TIME_MILLIS"))` → `streaming.content.*.QUOTE_TIME_MILLIS` (dict L2374).
  - **L116:** `_epoch_seconds_from_millis(item.get("TRADE_TIME_MILLIS"))` → `streaming.content.*.TRADE_TIME_MILLIS` (dict L2385).
- **proposed disposition (canonical reads):** **REPLACED** — six Schwab streaming leaves, all catalogued, all consumed via `.get(...)` without fabricated defaults; fail-closed when `spot_f is None or spot_f <= 0` (L111–112).
- **canonical_field citations:**
  - `streaming.content.*.LAST_PRICE`
  - `streaming.content.*.MARK`
  - `streaming.content.*.BID_PRICE`
  - `streaming.content.*.ASK_PRICE`
  - `streaming.content.*.QUOTE_TIME_MILLIS`
  - `streaming.content.*.TRADE_TIME_MILLIS`
- **provenance trace (clause 4):** Streaming hot path — `planes/order_flow_live_state` (or equivalent streaming-plane consumer) listens for Schwab WebSocket `LEVEL_ONE_EQUITY` content rows and dispatches each row's `item` dict here. The Schwab streaming response shape is documented at `streaming.content.*` family (dict L2308–2394). The `item` argument matches the per-row content dict shape (key = `1` per the dict example).
- **derived outputs (L128–141, L143–184) — diagnostic / projection:**
  - `spread_frac = (af - bf) / quote_mid` (L139) — derivation from canonical `BID_PRICE` / `ASK_PRICE` / `MARK`. Tagged via `spread_source` ("derived_bid_ask_fraction_schwab_mark_denom" L161) per the operator's spread-provenance convention — disclosed derivation, not a substitution.
  - `quote_mid = mark_f` (L135) — direct use of Schwab `MARK`, tagged `mid_source = "schwab_streaming_mark"` (L136).
  - Output dict keys `spot` / `bid` / `ask` / `spot_disp` / `bid_disp` / `ask_disp` / `quote_mid` / `mid_source` / `spread` / `spread_pts` / `spread_source` / `spread_pts_source` / `fast_generation_id` / `fast_server_ts` / `quote_time_source` / `server_received_ts` / `quote_ingestion` / `quote_source_detail` (L144–184) — **internal plane projection keys**, not Schwab wire tokens (same rule as `signals.py.md` S3 / `server.py.md` S23 / S24 / S25).
- **code edit:** none for the canonical reads.

### S2a — Non-canonical `BID` / `ASK` fallback reads (audit catch)

- **lines:** L97 `or _positive_float(item.get("BID"))`; L98 `or _positive_float(item.get("ASK"))`. Diagnostic label echoes at L108–109.
- **surface:** `item.get("BID")` and `item.get("ASK")` — bare keys, not the canonical `BID_PRICE` / `ASK_PRICE`.
- **CSV check:** Searching `schwab_field_inventory/schwab_field_dictionary.csv` for `streaming.content.*.BID` (bare): no row exists. Only `streaming.content.*.BID_PRICE` (L2338), `streaming.content.*.BID_ID` (L2336), `streaming.content.*.BID_MIC_ID` (L2337), `streaming.content.*.BID_SIZE` (L2339), `streaming.content.*.BID_TIME_MILLIS` (L2340), `streaming.content.*.BIDS` (L2326) are catalogued. Same for `ASK` (only `ASK_PRICE`, `ASK_ID`, `ASK_MIC_ID`, `ASK_SIZE`, `ASK_TIME_MILLIS`, `ASKS` exist).
- **proposed disposition:** **REPLACED** — non-canonical fallbacks removed @ fix-as-we-find slice (paired test `test_record_from_level_one_ignores_non_canonical_bid_ask_keys` in `tests/test_live_market_plane_streaming.py`).
- **code edit:** landed — `live_market_plane.py` reads `BID_PRICE` / `ASK_PRICE` only; bare `BID` / `ASK` ignored.

### S3 — `record_quote` (REST fast-quote fallback writer)

- **lines:** L196–208.
- **surface:** `t = (ticker or "").upper().strip()` (L198); `_by_ticker[t] = dict(payload)` (L202); `notify_quote_updated(t)` (L206). The `payload` argument is opaque to this function — no Schwab JSON keys subscripted here; the parsing happened upstream in the REST fast-quote callsite (`_fetch_fast_quote_payload` per module docstring L4–6) which is dispositioned in **`server.py.md`** (the file owning `_fetch_fast_quote_payload`).
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — plane-write delegation; no in-file Schwab key reads.
- **code edit:** none.

### S4 — `get_quote` (plane row accessor)

- **lines:** L211–216.
- **surface:** `dict(row) if row else None` — defensive copy of the internal `_by_ticker` row.
- **proposed disposition:** **NOT_MARKET_DATA** — pure read of internal plane state.
- **code edit:** none.

### S5 — `merge_into_state` (Tier C overlay onto `ms_dict`)

- **lines:** L219–254. Overlay loop L230–246. Auxiliary fields L247–254.
- **surface:** Iterates internal plane projection keys (`"spot"`, `"bid"`, `"ask"`, `"spot_disp"`, `"bid_disp"`, `"ask_disp"`, `"quote_mid"`, `"mid_source"`, `"spread"`, `"spread_pts"`, `"spread_source"`, `"spread_pts_source"`, `"quote_ingestion"`) and writes them into `ms_dict[k]`. Writes auxiliary keys `_live_plane_fast_ts`, `fast_server_ts`, `fast_generation_id`, `_quote_authority`. These keys are **internal plane projection names** — NOT Schwab wire tokens.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — same rule as `signals.py.md` S3 (REPLACED not asserted on internal projection keys like `"spot"`).
- **provenance trace (for audit only):** Underlying values in `q["spot"]` etc. originate from S2 (`record_from_level_one_equity`) where they were set from canonical Schwab streaming leaves. **This** function only reads projection keys.
- **code edit:** none.

### S6 — `apply_l1_live_quote_overlay` (L1 cache overlay)

- **lines:** L257–292. Same shape as S5.
- **surface:** Same internal projection-key set as S5; writes onto `l1_payload[k]` plus `_live_plane_fast_ts`, `_quote_authority`, `l1_live_overlay_applied`.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — same rule as S5.
- **code edit:** none.

### S7 — `take_fresh_sse_quote_payload` (SSE coalescing)

- **lines:** L295–315.
- **surface:** Reads internal `_by_ticker[t]` row, compares `row.get("fast_generation_id")` (internal projection key) against `_last_sse_pushed_gen[t]`; returns a copy with `_plane_layer` and `_update_source` tags.
- **proposed disposition:** **NOT_MARKET_DATA** — internal coalescing state machinery; no Schwab keys.
- **code edit:** none.

### S8 — `reset_sse_push_cursor` (SSE cursor reset)

- **lines:** L318–322.
- **surface:** `_last_sse_pushed_gen.pop(t, None)` — internal cursor reset.
- **proposed disposition:** **NOT_MARKET_DATA** — pure internal state mutation.
- **code edit:** none.

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

Bulk **NOT_MARKET_DATA** at Schwab `example_raw_field` token layer: module imports + logger setup (L22–27); thread locks and module dicts (L31–38); helper functions `next_fast_generation` (L41–47), `_safe_float` (L50–59), `_plane_tuple_sig` (L62–67), `_positive_float` (L70–74), `_epoch_seconds_from_millis` (L77–81); the entire output-dict assembly inside `record_from_level_one_equity` (L143–184) for internal plane projection keys (`spot` / `bid` / `ask` / `spot_disp` / `bid_disp` / `ask_disp` / `quote_mid` / `mid_source` / `spread` / `spread_pts` / `spread_source` / `spread_pts_source` / `fast_generation_id` / `fast_server_ts` / `quote_time_source` / `server_received_ts` / `quote_ingestion` / `quote_source_detail`); REST plane-write delegation (`record_quote` S3); plane accessor (`get_quote` S4); Tier C overlay loops (`merge_into_state` S5, `apply_l1_live_quote_overlay` S6); SSE coalescing state (`take_fresh_sse_quote_payload` S7, `reset_sse_push_cursor` S8); `planes.l1_events.notify_quote_updated(t)` invocations (L188–192, L204–208) — ticker-only payload, no Schwab keys.

The **REPLACED** dispositions in this file are concentrated in S2 (`record_from_level_one_equity`) — six canonical Schwab streaming-leaf reads (`LAST_PRICE`, `MARK`, `BID_PRICE`, `ASK_PRICE`, `QUOTE_TIME_MILLIS`, `TRADE_TIME_MILLIS`). S2a flags the only audit catch (non-canonical `BID` / `ASK` fallback) with a proposed REPLACED-via-removal remediation.

This file's contribution to V4 closure is **completing the streaming-plane producer leg** of the CANOPY→TRUNK→BRANCH→LEAF chain: Schwab `LEVEL_ONE_EQUITY` content rows enter at `record_from_level_one_equity`, are canonicalized into internal plane projection keys, and overlay onto Tier B/C analytical payloads via `merge_into_state` / `apply_l1_live_quote_overlay`. Together with `schwab_client.py.md` (REST producer-leaf adapter) and `polling_adapter.py.md` (REST candle-array producer), the three memos close the producer-side of the Schwab market-data ingest.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/live_market_plane.py.md
- **S2a closed @ `e147097`** (2026-05-24): non-canonical `BID` / `ASK` fallbacks removed; paired test `test_record_from_level_one_ignores_non_canonical_bid_ask_keys` in `tests/test_live_market_plane_streaming.py` locks the behavior.
