# Issue 19 — `pin_neutral` reachability at canonical 1m (deterministic audit)

**Date:** 2026-04-03  
**Scope:** Prove where `pin_neutral` is produced, whether it is **logically reachable**, whether **historical `1m` data** contains it, and whether **labeling** is faithful. **Market open/closed is irrelevant** — this uses **code + SQLite** only.

---

## 1. `PIN_NEUTRAL` logic spec

| Field | Detail |
|--------|--------|
| **File** | `market_state.py` |
| **Function** | `derive_zone(bias_signal, net_delta)` |
| **Inputs** | `bias_signal: str \| None`, `net_delta: float \| None` |
| **Conditions → `pin_neutral`** | After lowercasing/stripping `bias_signal`: **`"balanced"`** or **`"neutral"`** → **`pin_neutral`**. Any value **not** matched by bull/bear/chaos/expansion branches falls through to **`return "pin_neutral"`** (default / catch-all). |
| **Dependencies** | **`bias_signal`** ultimately comes from **`math_levels._bias_from_net(net_gamma, net_delta, pin_strength)`** (consensus row). **`pin_strength`** depends on gamma structure across strikes (**not** on OHLC). **`net_delta`** also used when `bias_signal == "expansion"` → `breakout` / `breakdown` (not `pin_neutral`). |
| **Where persisted** | `server.py`: `cur_zone = derive_zone(bias_sig, nd_raw)` with `bias_sig` / `nd_raw` from **`consensus_summary`**; later `build_market_state` sets **`ms.zone = derive_zone(ms.bias_signal, ms.net_delta)`**; snapshot uses **`zone=ms.zone`**. |

**Source excerpts**

```44:72:market_state.py
def derive_zone(bias_signal: str | None, net_delta: float | None) -> str:
    ...
    b = (bias_signal or "").strip().lower()
    if b in ("bull", "tilt bull"):
        return "pin_bull"
    if b in ("bear", "tilt bear"):
        return "pin_bear"
    if b in ("balanced", "neutral"):
        return "pin_neutral"
    if b == "chaos zone":
        return "pin_chaos"
    if b == "expansion":
        nd = net_delta or 0.0
        return "breakout" if nd >= 0 else "breakdown"
    return "pin_neutral"  # safe default
```

```161:177:math_levels.py
def _bias_from_net(net_gamma: float | None, net_delta: float | None, pin_strength: str) -> str:
    if net_gamma is None or net_delta is None:
        return "Neutral"
    if pin_strength in ("High", "Med"):
        if net_delta > 0 and net_gamma > 0:
            return "Bull"
        if net_delta < 0 and net_gamma > 0:
            return "Bear"
        if net_gamma < 0:
            return "Expansion"
    if pin_strength == "Very Low":
        return "Chaos Zone"
    if net_delta > 0:
        return "Tilt Bull"
    if net_delta < 0:
        return "Tilt Bear"
    return "Balanced"
```

**Important:** **`price_bars_1m` is not an input** to `derive_zone` or `_bias_from_net`. **1m bars** only drive **`zone_since_bars_1m`** counters (`server.py`), not the **zone string**.

---

## 2. Reachability (mathematical / logical)

**REACHABLE: YES**

**Proof sketch**

1. **`_bias_from_net` → `"Neutral"`** when `net_gamma is None` or `net_delta is None` → `derive_zone` → **`pin_neutral`** (via `"neutral"` branch).  
2. **`_bias_from_net` → `"Balanced"`** when: not in High/Med expansion branches, **not** Very Low (chaos), **`net_delta` is neither `> 0` nor `< 0`** — i.e. **`net_delta == 0.0`** (exact) with **`pin_strength == "Low"`** (or the High/Med case with **`net_gamma > 0`** and **`net_delta == 0`** where none of the earlier High/Med branches fire). → **`derive_zone`** → **`pin_neutral`**.  
3. **`derive_zone` default** (`return "pin_neutral"`) makes **any unrecognized `bias_signal`** map to **`pin_neutral`** (should be rare in production if bias is always from `_bias_from_net`).

**Mutual exclusivity**

- For a **fixed** `(bias_signal, net_delta)` pair, **`derive_zone`** returns **one** zone.  
- **`_bias_from_net`** returns **one** bias per `(net_gamma, net_delta, pin_strength)`. **Same** `(net_gamma, net_delta)` can yield **different** biases if **`pin_strength`** differs — **`pin_strength` is not stored on `snapshots`**, so **you cannot re-derive `zone` from DB greeks alone** without replaying the full exposure map.

**Not impossible**

- There is **no** contradiction that makes **`pin_neutral`** logically impossible under the current code.

**Why it can be *rare***

- **`Neutral`** from missing greeks is **unlikely** when consensus is built successfully (both aggregates usually present).  
- **`Balanced`** requires **`net_delta` exactly zero** (after aggregation) for the **Low** pin path — **uncommon** for real float aggregates.  
- Most nonzero deltas → **Tilt Bull / Tilt Bear** → **`pin_bull` / `pin_bear`**, not **`pin_neutral`**.

---

## 3. Historical scan (DB + limits of “simulate from 1m bars”)

### 3.1 Cannot evaluate “expected `pin_neutral` per `price_bars_1m` row”

**By construction, zone is not a function of OHLC or `price_bars_1m`.**  
Simulating **`pin_neutral` “for each 1m bar”** would require **replaying option exposure** at each timestamp (chain, strikes, aggregation). That is **not** available from **`price_bars_1m` alone**.

**Expected count from bars alone:** **undefined / N/A**.

### 3.2 Actual counts (measured)

**Command:** `python tools/pin_neutral_reachability_audit_v1.py --db data/ed_console.db --json-out data/pin_neutral_reachability_audit_v1.json`

**Results on this workspace’s `data/ed_console.db` (see JSON for `generated_ts_utc`):**

| Metric | Value |
|--------|------:|
| **`snapshots` `timeframe='1m'` total** | **39 589** |
| **`zone='pin_neutral'` AND `timeframe='1m'`** | **0** |
| **`zone='pin_neutral'` AND `timeframe='5m'`** | **797** |
| **`1m` zone histogram (top)** | `breakdown` 18 293; `pin_bull` 16 187; `pin_bear` 3 442; `breakout` 1 406; `pin_chaos` 261 — **no `pin_neutral` bucket** |

**Gap analysis**

- **Not** “labeling failed to write `pin_neutral` while bars implied it” — **bars imply nothing** about zone.  
- **Observed gap:** under **live consensus + floats** during the **`1m` snapshot era**, **`bias_signal`** apparently **never** landed in a combination that **`derive_zone`** maps to **`pin_neutral`**, **or** only the legacy **`5m`** ingest window recorded that cohort. Empirically: **`pin_neutral` exists historically on `5m`, not on `1m`** for this file.

---

## 4. Labeling path trace

| Step | Behavior |
|------|----------|
| **Compute** | `ms.zone = derive_zone(ms.bias_signal, ms.net_delta)` in `build_market_state` (`market_state.py`). |
| **Persist** | `server.py` → `SnapshotRow(..., zone=ms.zone, ...)` → `insert_snapshot`. |
| **Overwrite?** | **No** separate zone rewrite on insert path reviewed; **`zone`** is **`ms.zone`**. |

**LABELING FAILURE STAGE:** **N/A** — there is **no** second-stage “pin_neutral label” decoupled from **`derive_zone`**. If **`pin_neutral`** is absent in **`1m` rows**, the explanation is **upstream** (bias/consensus distribution + timeframe era), **not** a broken writer.

---

## 5. Root cause (required taxonomy)

**Primary: D — `pin_neutral` is valid and reachable but extremely rare under `_bias_from_net` + real aggregates; historical `pin_neutral` cohort on this DB is on legacy `5m`, not canonical `1m`.**

**Secondary nuance (not a separate “broken pipeline”):** **`derive_zone`’s final `return "pin_neutral"`** means **unknown biases** would also **collapse** to **`pin_neutral`** — that is **not** the driver of the measured histogram (other zones dominate).

**Not A:** Logic does **not** make **`pin_neutral`** impossible.  
**Not B:** **No** evidence of a **separate** labeling bug; **`zone`** follows **`derive_zone`**.  
**Not C:** **No** evidence **`pin_neutral`** is **replaced after** `ms.zone` in the traced insert path.

---

## 6. Recommended actions

1. **Treat “simulate from `price_bars_1m` only” as out of scope** for zone — add **`bias_signal` (and optionally `pin_strength`) to `SnapshotRow`** if you need **replayable** zone audits from SQLite alone.  
2. **Product decision:** If **`pin_neutral`** should be **more common**, adjust **`_bias_from_net`** (e.g. map **small \|net_delta\|** to **`Balanced`** instead of requiring **exact zero**) — **this changes trading semantics**; must be **explicit**.  
3. **Operational:** Continue **canonical `1m`** logging; **`pin_neutral`** will appear when consensus produces **`Neutral` / `Balanced`** (or unknown bias hits default). Re-run **`tools/pin_neutral_reachability_audit_v1.py`** periodically.

---

## 7. Artifacts

| Artifact | Purpose |
|----------|---------|
| `tools/pin_neutral_reachability_audit_v1.py` | Reproducible DB + `derive_zone` samples |
| `data/pin_neutral_reachability_audit_v1.json` | Latest measured counts |

---

## 8. Final output (exact lines)

- **`pin_neutral` REACHABLE AT 1M:** **YES** (logic allows it; **not** OHLC-derived)  
- **`pin_neutral` GENERATED IN HISTORICAL 1M DATA:** **NO** (on measured `data/ed_console.db`: **0** rows)  
- **LABELING PIPELINE CORRECT:** **YES** (zone = `derive_zone(bias_signal, net_delta)` → snapshot)  
- **ROOT CAUSE IDENTIFIED:** **YES** ( **D** + **`5m` vs `1m` era** )  
- **EXACT NEXT FIX DEFINED:** **YES** (§6: **optional schema for bias/pin_strength**; **optional `_bias_from_net` threshold change** — product-owned)
