# Issue 19 — Canonical ontology specification and mismatch audit

**Mode:** architecture and validation only — **no core logic changes** in this pass.  
**Evidence:** SQLite `data/ed_console.db` (read-only queries), source files cited by path, reproducible script `tools/ontology_mismatch_evidence.py`.

**Methodology:** derive allowed values and producers from code; compare to **historical** distributions on disk; compare to **retrieval** SQL and anchor/query paths. Where proof is incomplete, marked **UNVERIFIED**.

---

## 1. Executive conclusion

| Finding | Type | Summary |
|---------|------|---------|
| **Dual taxonomies** | **Fact** | **Structural `zone`** (pin/expansion classification from gamma bias) and **`regime_primary`** (8-family environment from `regime_engine`) are **different namespaces**. They must not be treated as one ontology. |
| **Issue 19 structural retrieval** | **Fact** | Tiers 1–2 filter on **`zone`**, **`vwap_side`**, **distance buckets**, **`ticker`**, **`timeframe`**, plus **`outcome_1c IS NOT NULL`**. They do **not** filter on `regime_primary` / `session_bucket` / `vix_bucket`. |
| **`pin_neutral`** | **Fact (correcting prior shorthand)** | `pin_neutral` **is** stored historically (**797** rows). **None** have `outcome_1c` filled (**0** labeled). Issue 19 therefore has **no** eligible pool for anchors that query `zone = pin_neutral` — not because the string is missing from the table, but because **labeling never joined the ontology**. |
| **Index ticker `SPX` vs `$SPX`** | **Fact** | Snapshots store **`$SPX`** (7,888 rows; **718** labeled). `load_survivorship_anchors_v1` strips a leading `$`, producing anchor ticker **`SPX`**. SQL uses **exact** `ticker = ?` → **zero** rows for **`SPX`**. This is a **hard query/reality mismatch**, independent of zone. |
| **Shadow-only zone relaxation** | **Fact** | `similarity_feature_search._zone_predicate_for_overlay_lookup` expands `pin_neutral` to a **pin family** `IN (...)` for **overlay / diagnostics only**. **Production** `get_similar_setups` and `_fetch_issue19_tier1_candidate_rows` use **`zone = ?`** — **no** expansion. |
| **Option 2 direction** | **Inference (approved premise)** | Aligning **historical data** to the **canonical ontology** implies: (1) **first-class labeled participation** for every `zone` value that live `derive_zone` can emit and that you care to retrieve on; (2) **single canonical instrument identity** for tickers in storage vs query; (3) **re-materialization** of derived tables after raw fixes; (4) **validation gates** so drift cannot return silently. |

**Final lines (evidence-based):** see §15.

---

## 2. Scope and methodology

### 2.1 In scope

- Categorical dimensions that **materially** affect: snapshot persistence, Issue 19–style **structural** similarity, tier widening, shadow/calibration inputs, and coverage diagnostics.
- Live producers (`build_market_state`, `server` logging, `derive_zone`, `regime_engine`, bucketing helpers).
- Historical storage (`snapshots`, `snapshots_1m_normalized`).
- Retrieval: `EdDB.get_similar_setups`, `adaptive_similarity_engine._fetch_issue19_tier1_candidate_rows` (same tier-1 shape as Issue 19).

### 2.2 Out of scope

- Changing SQL, tiers, thresholds, or transport authority (explicit program constraint).
- Full implementation of migrations (design only here).

### 2.3 Evidence sources

| Source | Role |
|--------|------|
| `market_state.derive_zone` | Canonical **zone** definition and allowed inputs |
| `signal_types.SignalInput` | Declared **`zone`** semantics (comment contract) |
| `regime_engine.ALL_REGIMES` / `RegimePayload.primary` | **`regime_primary`** vocabulary |
| `math_volatility.session_bucket`, `vix_bucket` | **Session / VIX** bucket definitions |
| `db.market_session` | **`market_session`** values |
| `math_probabilities.dist_bucket` + `DIST_BUCKET_*` | **Distance bucket** semantics (magnitude via `abs`) |
| `canonical_distances` | **Option A** nearest above/below magnitudes |
| `db.py` `get_similar_setups` | **Retrieval** filters per tier |
| `similarity_feature_search` | **Shadow** overlay zone predicate (≠ production) |
| `adaptive_shadow_v2_calibration.load_survivorship_anchors_v1` | **Anchor/query** ticker normalization |
| `tools/ontology_mismatch_evidence.py` | **Historical** distinct values and label counts |

---

## 3. Canonical ontology specification

**Legend:**  
- **Exact** = equality filter in structural SQL.  
- **Bucketed** = reduced to interval/`dist_bucket` for SQL.  
- **Derived** = computed from other fields / time.  
- **First-class historical** = must be stored on `snapshots` (or accepted loss).  
- **Status:** CLEAR = code + storage unambiguous; AMBIGUOUS = multiple representations or undocumented branches; MISSING = ontology exists live but history cannot participate in retrieval.

| Dimension | Canonical meaning | Allowed values (from code) | Storage table.column | Live producer(s) | Historical producer | Retrieval consumer (structural) | Exact / bucketed / derived | First-class historical? | Documented? | Status |
|-----------|-------------------|----------------------------|----------------------|------------------|---------------------|-----------------------------------|-----------------------------|-------------------------|-------------|--------|
| **Instrument identity** | Tradable / index **symbol key** for partitioning history | **No single normalized form in DB** — observed `SPY`, `QQQ`, `IWM`, **`$SPX`**, equities, etc. | `snapshots.ticker` | Server request path (uppercasing); Schwab/index may use `$` prefix | Same at insert | **`ticker = ?` exact** (`get_similar_setups`) | Exact | **Yes** | Partially (`schwab_*` inventories show `$SPX`) | **AMBIGUOUS** — `$` prefix not unified with anchor loader |
| **Timeframe** | Horizon clock for outcomes and matching | `CANONICAL_TIMEFRAME` = **`1m`** (+ legacy rows may reference other values in old DBs) | `snapshots.timeframe` | `db.insert_snapshot` enforces `1m` | Legacy `5m` possible in old data; normalizer reads | **`timeframe = ?` exact** | Exact | **Yes** | `timeframe_config.py` | **CLEAR** for live; **AMBIGUOUS** for legacy mix |
| **Structural zone** | Gamma / bias / expansion **structure class** for matching | **`pin_bull`**, **`pin_bear`**, **`pin_neutral`**, **`pin_chaos`**, **`breakout`**, **`breakdown`** (plus **`unknown`** only if rules path errors — see `market_state`) | `snapshots.zone` | **`derive_zone(bias_signal, net_delta)`** in `build_market_state` | Copied into `SnapshotRow` at log | **`zone = ?` exact** tiers 1–4 | Exact | **Yes** | `derive_zone` docstring; `SignalInput` comment | **CLEAR** definition; **MISSING** labeled history for **`pin_neutral`** |
| **VWAP side** | Price vs session VWAP | **`above`**, **`below`**; **NULL** observed in history | `snapshots.vwap_side` | `build_market_state` / VWAP derivation | Same | **`vwap_side = ?` exact** | Exact | **Yes** | `SignalInput` | **AMBIGUOUS** — **68** labeled rows with **NULL** `vwap_side` (evidence script) |
| **Nearest above/below distance** | **Magnitude** to nearest structural above/below level | Non-negative **`REAL`** or **NULL** (Option A); bucket labels `0-1`, `1-2`, `2-5`, `5+` via `dist_bucket` | `snapshots.nearest_above_dist`, `nearest_below_dist` | **`canonical_nearest_distances`** | Same (+ backfill corrected sign) | **Null-aligned `BETWEEN`** per bucket (tiers 1–2); tier 2 drops below bucket | Bucketed (from magnitude) | **Yes** | `canonical_distances.py` | **CLEAR** post–Option A |
| **Session bucket (ET)** | Intraday **time-of-day** coarse bucket | **`open`**, **`morning`**, **`midday`**, **`afternoon`**, **`close`** (`math_volatility`) | `snapshots.session_bucket` | `server` uses `session_bucket(et_h, et_m)` | Logged on insert | **Not in Issue 19 tier 1–5 SQL** | Bucketed (derived from clock) | Stored, optional for structural | `math_volatility` | **CLEAR** |
| **Market session** | ETH/RTH classification | **`premarket`**, **`rth`**, **`afterhours`**, **`closed`** (`db.market_session`) | `snapshots.market_session` | `server` → `market_session(...)` | Logged | **Not in Issue 19 tier 1–5 SQL** | Exact (per ET rules) | Stored | `db.py` | **CLEAR** |
| **Regime primary** | **Environmental** regime (8 families) | `ALL_REGIMES`: **`pinning`**, **`acceleration`**, **`breakout`**, **`mean_reversion`**, **`vol_compression`**, **`vol_expansion`**, **`trend_continuation`**, **`reversal_prone`** | `snapshots.regime_primary` | `market_state` from `regime_engine` | Logged | **Tier 3 shadow soft** (`adaptive_similarity_engine`), **not** structural Issue 19 | Exact string family | Stored | `regime_engine.py` | **CLEAR** but **orthogonal** to **`zone`** |
| **Regime confidence** | Strength label for regime | **`high`**, **`medium`**, **`low`** | `snapshots.regime_confidence` | `regime_engine` | Logged | Shadow soft allowlist | Exact | Stored | `regime_engine` | **CLEAR** |
| **VIX bucket** | Implied vol **level** bucket | **`vix_low`**, **`vix_normal`**, **`vix_elevated`**, **`vix_high`** (`vix_bucket`) | `snapshots.vix_bucket` | From VIX level at log | Logged | **Not** Issue 19 structural; shadow | Bucketed | Stored | `math_volatility.vix_bucket` | **CLEAR** definition; **historical sample** may under-represent low/normal (see §6) |

**Critical non-identity:** **`zone = pin_bull`** is **not** the same proposition as **`regime_primary = pinning`**. Example: expansion structure can coincide with various regimes; pinning regime can occur outside narrow pin_* zone strings. **Conflating these is an ontology error.**

---

## 4. Producer / storage / consumer inventory

Abbreviated high-signal rows; **Role** is one of: LP (live producer), HP (historical producer = logged snapshot), ST (storage), C-19 (Issue 19 structural consumer), C-SH (shadow/adaptive consumer), C-RPT (reports/diagnostics).

| Dimension | File | Function / artifact | Role | Actual values / behavior | Evidence |
|-----------|------|---------------------|------|---------------------------|----------|
| zone | `market_state.py` | `derive_zone` | LP | Maps `bias_signal` + `net_delta` → `pin_*` / `breakout` / `breakdown`; default **`pin_neutral`** | Lines 44–72 |
| zone | `market_state.py` | `build_market_state` | LP | `ms.zone = derive_zone(ms.bias_signal, ms.net_delta)` | Line ~936 |
| zone | `server.py` | `SnapshotRow` build | HP | Persists `ms.zone` | `nearest_*` snapshot kwargs region |
| zone | `db.py` | `snapshots.zone` | ST | Mixed historical distribution | Evidence JSON §6 |
| zone | `db.py` | `get_similar_setups` tier 1–2 | C-19 | **`zone = ?`** exact | SQL block ~2545+ |
| zone | `adaptive_similarity_engine.py` | `_fetch_issue19_tier1_candidate_rows` | C-19 | Same as tier 1 | Lines 136–147 |
| zone | `similarity_feature_search.py` | `_zone_predicate_for_overlay_lookup` | C-SH | **`pin_neutral` → IN pin family** | Lines 424–439 |
| regime_primary | `regime_engine.py` | `compute_regime` / payload | LP | One of `ALL_REGIMES` | `ALL_REGIMES` list |
| regime_primary | `market_state.py` | fusion hook | LP | `ms.regime_primary` | ~1442 |
| regime_primary | `db.py` | `snapshots.regime_primary` | ST | 8 values in labeled data | Evidence JSON |
| regime_primary | `adaptive_similarity_engine.py` | Tier 3 soft scoring | C-SH | Weighted categorical match | `ADAPTIVE_SHADOW_V2_TIER3_COLUMNS` |
| session_bucket | `math_volatility.py` | `session_bucket` | LP | 5 ET buckets | Lines 96–104 |
| session_bucket | `server.py` | snapshot insert | HP | `session_bucket=_session_bucket` | ~2325 |
| session_bucket | `db.py` | column | ST | 5 values in labeled rows | Evidence JSON |
| vix_bucket | `math_volatility.py` | `vix_bucket` | LP | Up to 4 labels | Lines 107–116 |
| vix_bucket | `db.py` | column | ST | **Only** `vix_elevated`, `vix_high` in **labeled** sample | Evidence JSON (market VIX era / logging) |
| market_session | `db.py` | `market_session` | LP | 4 strings | Lines 2957–2966 |
| ticker | server + Schwab | symbol selection | LP | **`$SPX`** stored for index | Evidence JSON |
| ticker | `adaptive_shadow_v2_calibration.py` | `load_survivorship_anchors_v1` | C-RPT / query | Strips **`$`** → `SPX` | Lines 43–45, 53 |
| nearest_* | `canonical_distances.py` | `canonical_nearest_distances` | LP | Option A magnitudes | Module docstring |
| nearest_* | `prediction_engine.py` | `canonicalize_distance_read` before DB | C-19 | Aligns anchor with SQL | Lines ~470–480 |
| Snapshots normalized | `snapshot_normalizer.py` | `resample_to_1m` / materialize | ST | **Last row in minute bucket** carries zone/regime/etc. | Module header lines 24–27 |
| Outcome labels | `db.py` | `fill_outcomes` | HP | Sets `outcome_*` when bars exist | Docstring |
| ed_schema_flags | `db.py` / backfill module | flags | ST | e.g. distance Option A | Prior validation |

**Verdict summary:** **INCONSISTENT** where **query path** (`SPX`) ≠ **storage** (`$SPX`) and where **`pin_neutral`** exists in **ST** but **never** reaches **C-19** pools due to **NULL `outcome_1c`**. **CONSISTENT** for Option A distance magnitudes and for explicit separation of regime vs zone *definitions* — inconsistency is in **coverage and naming**, not in the definitions themselves.

---

## 5. Live vs historical vs query mismatch matrix

| Dimension | Live values | Historical values | Query / anchor values | Mismatch type | Severity | Evidence | Root cause hypothesis | Must fix before calibration? |
|-----------|-------------|-------------------|------------------------|---------------|----------|----------|----------------------|----------------------------|
| **zone = pin_neutral** | Emitted by `derive_zone` for balanced/neutral bias **and** as default for unrecognized bias | **797** rows with `zone=pin_neutral`; **0** with `outcome_1c` | Anchors query **`zone = pin_neutral`** + `outcome_1c NOT NULL` | **Labeled history missing** for stored zone | **Critical** | `ontology_mismatch_evidence.py` | Outcomes never backfilled / bars missing / rows stranded before label pipeline | **Yes** — cannot calibrate structural tier-1 on neutral pin until labeled |
| **ticker SPX** | **UNVERIFIED** whether live API presents `SPX` vs `$SPX` to logging | Stored as **`$SPX`** | Anchors loaded as **`SPX`** after `$` strip | **Identifier aliasing** | **Critical** | `count_labeled_SPX=0`, `count_labeled_$SPX=718` | Anchor loader normalizes away broker prefix that DB retains | **Yes** |
| **zone vs regime_primary** | Both emitted live; **different** meanings | Both stored | Issue 19 uses **zone**, shadow uses **regime** in Tier 3 | **Semantic conflation risk** (human/process) | **High** if conflated | Code refs §3 | Separate engines (`derive_zone` vs `regime_engine`) | **Yes** for **interpretation**; not a “bug” if kept separate |
| **vwap_side NULL** | **UNVERIFIED** if live can snapshot NULL | **68** labeled rows `vwap_side IS NULL` | Query uses **`vwap_side = ?`** exact | **NULL vs exact** | **Medium** | Evidence script | Missing VWAP at log time | **Maybe** — affects match rate for some rows |
| **vix_bucket low/normal** | Code can emit | **Not present** in labeled distinct set (only elevated/high) | Not in structural tiers | **Sample / era coverage** | **Low–Medium** for shadow | Evidence JSON | Historical VIX range always high band in sample | **Nice-to-have** for shadow diversity |
| **pin_neutral shadow expansion** | N/A | Family zones exist | Overlay expands **pin_neutral** | **Production vs shadow asymmetry** | **Medium** (audit confusion) | `similarity_feature_search.py` | By design — must be documented | **No** for Issue 19 truth; **Yes** for reporting clarity |

---

## 6. Deep audit — zone / pin taxonomy

### 6.1 Is `pin_neutral` a real live category?

**Yes (fact).** `derive_zone` maps `("balanced","neutral")` → **`pin_neutral`** and returns **`pin_neutral`** as the **default** when `bias_signal` matches none of the enumerated cases (`market_state.py` lines 65–72).

### 6.2 Is it query-only?

**No.** It is **stored** on `snapshots` (**797** rows).

### 6.3 Is it absent from storage?

**No** — **present but unlabeled.**

### 6.4 Mutual exclusivity

**Fact:** `derive_zone` returns exactly **one** string per call from the current `bias_signal` / `net_delta`; a row cannot be simultaneously `pin_bull` and `pin_neutral` **from this function**. **`pin_chaos`** is a distinct branch (`bias == "chaos zone"`).

### 6.5 Hierarchy vs conflicting ontologies

**Inference:** There is **no** explicit parent/child hierarchy in code (flat enum). **`is_pin_zone`** treats any `zone.startswith("pin")` as pin family (`math_levels.py`) — **family** is **derived**, not stored as a parent key.

### 6.6 Where assigned, stored, queried

| Stage | Mechanism |
|-------|-----------|
| Assigned | `derive_zone` ← `consensus_summary.bias_signal`, `net_delta` |
| Stored | `SnapshotRow.zone` → `snapshots.zone` |
| Queried (production) | **`zone = ?`** in `get_similar_setups` / tier-1 fetch |
| Queried (shadow overlay only) | **`pin_neutral` → IN (`pin_neutral`, `pin_bull`, `pin_bear`, `pin_chaos`)** |

**Blunt conclusion:** **Production Issue 19** **does not** treat `pin_neutral` as “any pin.” **Shadow overlay** does — if analysts compare overlay pools to production pools without noting this, they will talk past each other.

---

## 7. Deep audit — ticker ontology

### 7.1 Is SPX first-class historically?

**Yes for `$SPX`.** **718** labeled rows under ticker **`$SPX`**.

### 7.2 Is SPX intended in similarity retrieval?

**Inference:** Yes — the survivorship JSON lists **`$SPX`** anchors; the system clearly **intends** index cohorts.

### 7.3 Why do anchors show zero SPX matches?

**Fact:** `load_survivorship_anchors_v1` removes **`$`**, producing **`SPX`**. SQL equality fails against **`$SPX`**.

### 7.4 Live-first vs historical-first vs proxy

| Class | Example | Note |
|-------|---------|------|
| Equity | `AAPL`, `TSLA`, … | Uppercased; no `$` issue |
| Index (Schwab-style) | `$SPX` in DB | **Prefix retained** in storage |
| **UNVERIFIED** | What symbol the live widget passes into `insert_snapshot` for indices | Would require runtime trace or server log capture |

### 7.5 Hidden proxy logic?

**None found** in Issue 19 SQL for “SPX means SPY.” **Substitution** exists only for **IWM pin_bear → breakdown** in **overlay** zone predicate (`similarity_feature_search._OVERLAY_ZONE_SUBSTITUTION`), which is **explicit** and **narrow** — not global SPX proxying.

---

## 8. Deep audit — distance semantics (Option A)

**Fact:** `nearest_above_dist` / `nearest_below_dist` are **magnitudes** (or NULL); direction is **field name**, not sign (`canonical_distances.py`).  
**Fact:** `dist_bucket` applies **`abs(dist)`** before bucket selection (`math_probabilities.py`).  
**Conclusion:** **No remaining directional ambiguity** in **stored** magnitude contract **post backfill + live canonical producer**, aside from general data-quality NULLs.

---

## 9. Deep audit — tier filter semantics

| Tier | Structural dimensions (production) | Widening |
|------|--------------------------------------|----------|
| **1** | `zone`, `vwap_side`, **both** distance buckets | — |
| **2** | `zone`, `vwap_side`, **above** distance only | Below distance constraint dropped |
| **3** | `zone`, `vwap_side` | Distances dropped |
| **4** | `zone` only | `vwap_side` dropped |
| **5** | `ticker`, `timeframe` only | Broadest |

**Exact-match despite incomplete ontology:** **Yes — by construction.** Tier 1 is **exact** on `zone` and `vwap_side`. If history never contains **labeled** `(ticker, zone, vwap_side, bucket…)` tuples that anchors use, **tier 1 is mathematically empty** without any SQL bug.

**Compatible with historical dataset?** **Partially.** Dataset is **rich** for `pin_bull`, `breakdown`, etc.; **poor** for **`pin_neutral`** (no labels); **misaligned** for **`SPX`** vs **`$SPX`**.

---

## 10. Deep audit — materialized / normalized tables

**Fact:** `snapshots_1m_normalized` takes **last snapshot per minute bucket**; categorical fields copy from that row (`snapshot_normalizer.py` header).  
**Inference:** There is **no separate taxonomy mapping** in the normalizer — **drift** only if **raw** `snapshots` drift or if materialize runs on **stale** raw.  
**Rebuild implication:** After fixing **raw** ticker / labels, **re-run materialization** to propagate.

---

## 11. Required first-class historical entities

| Entity / category | Current status | Why required | Producer path needed | Storage path | Consumer impact | Priority |
|-------------------|----------------|--------------|----------------------|--------------|-----------------|----------|
| **Labeled `pin_neutral` rows** | 797 unlabeled | Anchors + live `derive_zone` default branch need empirical cohorts | Ensure `fill_outcomes` (or backfill) runs for those `snapshot_id`s; fix any upstream missing bars | `snapshots.outcome_*` | Issue 19 tier ≤2; calibration pools | **HARD BLOCKER** for neutral-pin structural calibration |
| **Canonical instrument key** | `$SPX` vs `SPX` split | Retrieval is **exact** on `ticker` | Single policy: **normalize at insert** OR **normalize at query** OR **alias table** | `snapshots.ticker` (+ optional `instrument_id`) | All SQL by ticker | **HARD BLOCKER** for index cohorts |
| **Optional: `vwap_side` completeness** | 68 NULL labeled | Exact tier match may skip real sessions | Improve VWAP fill / `derive_vwap_side` guards | `snapshots.vwap_side` | Tier 1–3 | **IMPORTANT** |
| **Shadow context diversity (vix low/normal)** | Rare in sample | Shadow Tier 3 calibration | More history or accept bias | `snapshots.vix_bucket` | Adaptive shadow | **OPTIONAL** short term |

---

## 12. Rebuild / migration design (architecture only)

### 12.1 Objectives

1. **`pin_neutral` rows participate** in `outcome_1c NOT NULL` population (or explicitly deprecate neutral-pin as a retrieval class — **product choice**; Option 2 as stated prefers **data aligned to ontology**, i.e. **label** them).
2. **Single canonical ticker** for index symbols across **insert**, **anchors**, and **SQL**.
3. **Refresh** `snapshots_1m_normalized` after raw repairs.

### 12.2 Tables affected

- **`snapshots`** — primary truth; **ticker normalization** migration + **outcome backfill** for `pin_neutral`.
- **`snapshots_1m_normalized`** — **re-materialize** from repaired raw (or incremental fix if policy allows).

### 12.3 Is raw history sufficient?

- **For outcomes:** **Yes**, *if* `price_bars_1m` has bars covering each snapshot timestamp + forward horizons (existing `fill_outcomes` contract). **UNVERIFIED** per-row without row-level audit.
- **For ticker:** **rename / map** only — no new market data.

### 12.4 New ingestion?

**Only if** bar history is missing for neutral-pin eras — then **cannot** label without external data; row-level audit required.

### 12.5 Backup / rollback

- File backup SQLite **before** ticker update or mass outcome update (same discipline as distance backfill).
- Transaction-wrapped migrations with **pre/post counts**.

### 12.6 Validation

- `tools/ontology_mismatch_evidence.py` — expect **`pin_neutral.labeled > 0`**; **`count_labeled_SPX` vs `$SPX`** resolved per policy.
- Tier-1 COUNT diagnostics per anchor (existing tools).
- **Mixed-era:** flag rows by **`ontology_schema_version`** or **`migrated_ts`** if partial application (avoid silent blend).

### 12.7 Guards

- **Startup / scheduled read-only audit:** fail if `zone=pin_neutral` & `outcome_1c IS NULL` fraction exceeds threshold **after** remediation window.
- **Ticker alias CI check:** anchors must reference stored form or join through alias table.

### 12.8 Tests (next phase)

- Contract tests: “anchor ticker == stored ticker OR alias.”
- “Every `derive_zone` output appears in labeled history” — **policy test**, not necessarily 100% if product excludes rare zones.

---

## 13. Risks of getting this wrong

- **False calibration:** tuning shadow weights on **empty or biased** structural pools → **overfitting to SPY breakout/breakdown** while believing coverage is “multi-index.”
- **Silent conflation:** training or narrative that treats **`regime_primary=pinning`** as **`zone=pin_*`** — **wrong science**.
- **Shadow vs production confusion:** comparing **`pin_neutral` expanded overlay** to **production tier 1** — **false conclusions**.
- **Ticker drift:** partial migration (some `SPX`, some `$SPX`) — **duplicated or orphaned** cohorts.

---

## 14. Exact next actions

1. **Decide canonical instrument string policy** (document in one place; migrate DB + anchors + any API normalization).
2. **Row-level audit:** all `pin_neutral` snapshots — **why** `outcome_1c` is NULL (missing bars vs not yet filled vs stale process).
3. **Run `fill_outcomes` / bar backfill** until **`pin_neutral` labeled > 0** or formally drop neutral-pin anchors.
4. **Re-materialize** normalized table.
5. **Re-run** structural coverage reports; only then **resume calibration**.

---

## 15. Required closing lines (evidence-based)

- **CANONICAL ONTOLOGY FULLY DEFINED:** **YES** for code-defined dimensions in §3; **AMBIGUOUS** for **instrument string normalization** until a **single** policy is adopted (currently **two** representations for index).

- **LIVE / HISTORICAL / QUERY ONTOLOGY ALIGNED:** **NO** — **`pin_neutral`** unlabeled pool; **`SPX` vs `$SPX`** query mismatch; **NULL `vwap_side`** in labeled rows.

- **HARD ONTOLOGY BLOCKERS:** (1) **Zero labeled `pin_neutral`** despite live + stored zone. (2) **Ticker normalization (`SPX` ≠ `$SPX`)** breaking index cohort retrieval. (3) **Process risk:** conflating **`zone`** with **`regime_primary`**.

- **FIRST-CLASS ENTITIES REQUIRED:** **Labeled historical `pin_neutral`** (or abandoned as a class); **canonical index ticker representation**; optional **`vwap_side` completeness**.

- **REBUILD REQUIRED:** **YES** — at minimum **data repair** (labels + ticker canon) and **normalized table refresh**; scope of **raw** rebuild depends on row-level missing-bar audit (**UNVERIFIED** without per-id trace).

- **SAFE TO PROCEED TO CALIBRATION:** **NO** — structural pools for declared anchors are **not** representative until the above blockers are cleared.

---

*Facts in §5–§7 rely on `tools/ontology_mismatch_evidence.py` output against `data/ed_console.db` at the time of authoring; re-run for your environment.*
