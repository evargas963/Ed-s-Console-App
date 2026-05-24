> **Classification:** Policy Specification | **Scope:** Governance documentation `signals.py.md`.

> **FROZEN_SNAPSHOT (2026-05-10):** This V4 review memo audited `signals.py` against the call graph that flowed through `chains.py::parse_quote_payload` and related helpers. **`chains.py` and those helpers were subsequently removed in the Schwab-direct redesign**; quote / chain reads are now inline. Provenance-trace mentions of `parse_quote_payload` should be read as "formerly `chains.py::parse_quote_payload` — removed in Schwab-direct redesign". Dispositions and Schwab `canonical_field` citations remain accurate.

# Review memo — signals.py

**Status:** FROZEN_SNAPSHOT (2026-05-10) — pre-Schwab-direct-redesign V4 review; helper symbols cited below were subsequently removed.  
**Date:** 2026-05-10  
**Reviewer:** Cursor (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)  
**File language family:** python  
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

---

---

## Gatekeeper CSV cross-check (retroactive @ 977e706, 2026-05-24)

**Tool:** \python tools/check_schwab_csv_first.py --gatekeeper-crosscheck signals.py\n**lexical_csv_collision_count:** 10

Retroactive full-CSV AST cross-check. Prior memo dispositions unchanged; homonym collisions classified in original site sections. Zero new wire FIND from cross-check.

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** for:

| Channel | Method |
|--------|--------|
| String-literal dict access | All `.get("...")` with string keys |
| Bracket dict access | `_mc_ctx["spot"]` |
| Attribute access on market-bearing objects | `inp.iv_level`, `inp.em_upper`, `inp.em_lower`; `getattr(inp, "ticker", ...)` (identity only) |
| Method calls passing market objects | `monte_carlo.simulate(...)`, `compute_rules(inp, ...)`, etc. — **no** Schwab wire tokens **inside** this file at call boundary |

**Review complete:** Every site **in this file** falls under **S1–S12** below; no other Schwab `example_raw_field` tokens or chain JSON subscripts occur in `signals.py`.

---

## Market-data sites identified

### S1 — `inp.iv_level` (attribute access)

- **lines:** 448–450  
- **surface:** `iv = inp.iv_level` (scaled if > 5.0)  
- **proposed disposition:** **NOT_MARKET_DATA** at **Schwab JSON literal** layer — `SignalInput` field (**`signal_types.SignalInput.iv_level`**) populated upstream in **`market_state.build_market_state`** from exposure / chain **`volatility`** pipeline (Schwab-sourced **values**, not `q_json["…"]` reads **here**).  
- **provenance trace (clause 4 — generic `inp`):** `server._fetch_state` → `compute_exposures_by_strike` / totals → `build_market_state(...)` constructs **`SignalInput`** — **`volatility`** numeric enters **`inp.iv_level`** off Schwab chain **ATM `volatility`** path (see `market_state.py` memo). **This file** only consumes the dataclass field.  
- **canonical_field:** Chain **`volatility`** maps to `chains.callExpDateMap.*.volatility` / related rows — **binding occurs upstream**, not at this attribute read.  
- **code edit:** none.

### S2 — `inp.em_upper`, `inp.em_lower` (log + MC input lineage)

- **lines:** 477–478, 487–488  
- **surface:** `inp.em_upper`, `inp.em_lower`; `em_upper=_mc_ctx.get("em_upper")`  
- **proposed disposition:** **NOT_MARKET_DATA** at wire literal layer — **SignalInput** EM bounds from **`market_state`** / server expected-move calculation (Schwab marks + spot).  
- **provenance trace:** Same as **S1**: **`SignalInput`** built in **`build_market_state`** from server-computed EM structures.  
- **code edit:** none.

### S3 — `_mc_ctx["spot"]` and `_mc_ctx.get("spot")` (MC dict)

- **lines:** 479, 482  
- **surface:** `_mc_ctx.get("spot")` (log), `spot=_mc_ctx["spot"]` (`monte_carlo.simulate`) — **dict keys are the literals `"spot"`**, not Schwab CSV leaves.  
- **proposed disposition:** **NOT_MARKET_DATA** at **Schwab wire-token** layer (same rule as **S1** / **S2** / **S4**).  
- **provenance trace (for audit only):** `_mc_ctx` from **`resolve_monte_carlo_stack_inputs`**; numeric spot is validated against MVP **`price.spot`** and **`SignalInput.spot`** per `features/monte_carlo_stack_input.py` **L44–71**. Upstream Schwab quote lineage: **`parse_quote_payload`** → **`quotes.quote.lastPrice` / `mark`**.  
- **canonical_field:** **N/A at this surface** — **REPLACED** is **not** asserted on internal projection keys **`"spot"`** / **`"price.spot"`**.  
- **code edit:** none.

### S4 — `_mc_ctx.get("call_gamma_wall")`, `put_gamma_wall`, `realized_vol`, `atr`, `garch_sigma_bars`

- **lines:** 485–486, 491–492, 497  
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab **JSON key** layer — values copied from **`SignalInput`** fields inside **`resolve_monte_carlo_stack_inputs`** (`getattr(inp, "call_gamma_wall", None)`, etc. per `monte_carlo_stack_input.py` **L72–78**).  
- **provenance trace:** `SignalInput` fields set in **`market_state.build_market_state`** from exposures / walls / vol metrics (Schwab chain-derived **numbers**, not wire dict access in **this** file).  
- **code edit:** none.

### S5 — `mc_spot_ctx.get("spot")` (`_spot_for_mc_fusion_adjustment`)

- **lines:** 262–265  
- **provenance trace:** When `mc_spot_ctx` is provided, it matches **`resolve_monte_carlo_stack_inputs`** output shape.  
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — same reasoning as **S3** (`"spot"` key).  
- **code edit:** none.

### S6 — `feats.get("price.spot")` (MVP feature subscript)

- **lines:** 268–272  
- **surface:** `feats.get("price.spot")` — **literal key `price.spot`** is **not** a `canonical_field` row in the Schwab CSV.  
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — internal MVP namespace; upstream values trace to **`SignalInput.spot`** / quote parse per `build_inference_snapshot_v1_from_signal_input` (**provenance for audit**, not **REPLACED** at this accessor).  
- **code edit:** none.

### S7 — `inference_snapshot_v1.get("features")`, `.get("as_of_ts")`

- **lines:** 268, 544, 553, 887, 896  
- **proposed disposition:** **NOT_MARKET_DATA** — wrapper keys for the MVP snapshot object, not Schwab REST field names.

### S8 — Multi-horizon / fusion / ML bundle `.get`

- **lines:** 198–204, 373–388, 1155, 1158  
- **keys:** `primary_horizon`, `trade_mode`, `xgb`, `lstm`, `transformer`, `direction`, `source`, etc.  
- **proposed disposition:** **NOT_MARKET_DATA** — stack / governance / debug keys.

### S9 — `os.environ.get(...)` (pred override gate)

- **lines:** 131  
- **proposed disposition:** **NOT_MARKET_DATA**

### S10 — `getattr(inp, "ticker"|"timeframe", ...)` and similar

- **lines:** 234, 311, 541, 596, 868, 880, etc.  
- **proposed disposition:** **NOT_MARKET_DATA** — identity / config fields.

### S11 — `getattr(fusion, ...)`, `getattr(regime, ...)`, `getattr(pred, ...)`, `getattr(call, ...)`

- **throughout** stack instrumentation  
- **proposed disposition:** **NOT_MARKET_DATA** — Python object fields on **non-Schwab** types.

### S12 — `canonical_forecast_from_fusion` / fusion probabilities

- **lines:** 79–110  
- **proposed disposition:** **NOT_MARKET_DATA** — model posterior card, not Schwab wire.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)  
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/signals.py.md  
