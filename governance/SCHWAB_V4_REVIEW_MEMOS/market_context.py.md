> **Classification:** Policy Specification | **Scope:** Governance documentation `market_context.py.md`.

# Review memo — market_context.py (vol-index lane V1+V6)

**Status:** pending gatekeeper review
**Date:** 2026-06-29
**Reviewer:** Cursor (local diff) → Gatekeeper (verified) → Operator
**File language family:** python
**Lane:** `VOLATILITY_INDEX_CONFLUENCE_AND_CALL_PUT_SIGNAL_CORRECTNESS_AUDIT_V1` — LANE V1 + V6
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**Closest-shape precedent:** `market_data_adapter.py.md` — Schwab quote leaf reads via `_extract_quote` wire-first pattern.

**Class A scope (this slice):** fetch/identity/register evidence only. **No** trading behavior, SignalInput routing, ML features, UI/API emission, DB writes, vol-regime consumer, or call/put logic change.

---

## Schwab CSV-first declaration (CI / PR2 gate)

Schwab CSV authority checked: yes

CSV row(s): quotes.quote.lastPrice ($VXN via `_extract_quote`); quotes.quote.lastPrice ($RVX via `_extract_quote`)

Derived-field disposition: REPLACE_WITH_SCHWAB

All consumers checked: no — V1 lane fetch-only (`ctx.vxn` / `ctx.rvx` in-memory); SignalInput / `ms_dict` / DB / UI are V3/V5 lane scope

REGISTER_ROW: f71114faa5593111d243, c03a3d4963e22eded241

---

## Gatekeeper CSV cross-check

**Tool:** `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck market_context.py`
**lexical_csv_collision_count:** 73

---

## Vol-index lane V1+V6 — new wire sites

### S-VXN — `$VXN` native vol index fetch (QQQ confluence gauge)

- **lines:** L655–658 (`fetch_market_context`).
- **surface:** `_fetch("$VXN")` → `_extract_quote("$VXN", vxn_json)` → `ctx.vxn` when last present.
- **leaf path:** `quotes.$VXN.quote.lastPrice` (via `_extract_quote` wire-first: `quote.lastPrice` → `extended.lastPrice` → `regular.regularMarketLastPrice` → `quote.mark`).
- **proposed disposition:** **REPLACED** — Schwab quote leaf; no fallback source.
- **canonical_field:** CSV row 2275 (`quotes.quote.lastPrice`).
- **REGISTER_ROW:** `f71114faa5593111d243`
- **consumer boundary:** **none in V1** — `ctx.vxn` is in-memory on `MarketContext` only; not routed to `SignalInput`, `ms_dict`, DB, UI, ML, or vol-regime.
- **code edit:** additive fetch + `MarketContext.vxn` field.

### S-RVX — `$RVX` native vol index fetch (IWM confluence gauge)

- **lines:** L660–663 (`fetch_market_context`).
- **surface:** `_fetch("$RVX")` → `_extract_quote("$RVX", rvx_json)` → `ctx.rvx` when last present.
- **leaf path:** `quotes.$RVX.quote.lastPrice` (same `_extract_quote` chain as S-VXN).
- **proposed disposition:** **REPLACED** — Schwab quote leaf; no fallback source.
- **canonical_field:** CSV row 2275 (`quotes.quote.lastPrice`).
- **REGISTER_ROW:** `c03a3d4963e22eded241`
- **consumer boundary:** **none in V1** — same as S-VXN.
- **code edit:** additive fetch + `MarketContext.rvx` field.

### S-VIX-legacy — macro `$VIX` semantics frozen

- **lines:** L647–653 (unchanged semantics).
- **surface:** `ctx.vix` continues to source macro `$VIX` only; `vix_regime` / `vix_color` / `vix_implication` derived from macro VIX.
- **proposed disposition:** **REPLACED** (pre-existing) — no semantic change in V1 lane.
- **DUAL_GAUGE_HYBRID:** macro arm preserved; native arms (`ctx.vxn`, `ctx.rvx`) additive only.

### S-identity — broker index bare-root normalization

- **file:** `instrument_identity.py` — `BROKER_INDEX_BARE_ROOTS` adds `VXN`, `RVX`.
- **surface:** `ticker_storage_key("VXN")` → `"$VXN"`; same for RVX.
- **proposed disposition:** **NOT_MARKET_DATA** — identity normalization, not a wire read.

---

## Wire proof summary

| Symbol | Leaf | V1 consumer | Live wire proof |
|--------|------|-------------|-----------------|
| `$VIX` | `quotes.quote.lastPrice` | macro `ctx.vix` (legacy) | pre-existing production path |
| `$VXN` | `quotes.quote.lastPrice` | **none** (fetch-only) | pytest mock + operator host `safe_get_quote` pending |
| `$RVX` | `quotes.quote.lastPrice` | **none** (fetch-only) | pytest mock + operator host `safe_get_quote` pending |

**Fail-closed:** per-symbol `_fetch` try/except; missing `$VXN`/`$RVX` leaves `ctx.vxn`/`ctx.rvx` as `None`; `$VIX` failure does not block `$VXN`/`$RVX` and vice versa; `fetch_market_context` never raises.

---

## Explicit non-changes (V1 boundary)

- No `SignalInput` field additions or routing.
- No `market_state.py` / `server.py` / `volatility_regime.py` edits.
- No DB schema or snapshot writes.
- No UI/API (`ms_dict`) emission of `vxn`/`rvx`.
- No model feature / ablation / retrain.
- No register repin / build meta / scoreboard / merge-slices.

---

## Aggregate disposition

- **status:** pending gatekeeper
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/market_context.py.md
- **register slice:** `governance/register_slices/market_context_py_1_961.csv` (+2 REPLACED rows)
- **Class A determination:** code + paired tests + memo + register slice rows — consumer-forbidden files untouched
