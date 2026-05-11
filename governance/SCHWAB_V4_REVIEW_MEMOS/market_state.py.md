# Review memo — market_state.py

**Status:** pending gatekeeper re-review (Evidence bar tightening)  
**Date:** 2026-05-10  
**Reviewer:** Cursor (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)  
**File language family:** python  
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**V4-B code (2026-05-10):** `_oe_chain_row_snapshot` **keys tuple** no longer includes non-CSV aliases **`expiration`** or **`volume`** — only **`expirationDate`** and **`totalVolume`** (see `A2_MARKET_STATE_PROOF_ROW_COMPLETENESS_CONTRACT.md`).

---

## Enumeration completeness

Sites **S1–S6** cover **every** `ct.get("…")` on **Schwab contract dicts** and the **full** `_oe_chain_row_snapshot` projection list.  
**S7+** cover **non-wire** / derived **`MarketState`** / **`SignalInput`** population.  

**Review complete** — no additional Schwab JSON subscripts in this file outside **S1–S6**.

---

## Market-data sites identified

### S1 — `_oe_chain_row_snapshot` projection (`ct` dict)

- **lines:** 501–549  
- **surface:** `return {k: ct.get(k) for k in keys}`; **`keys`** (exact order in source):  
  `symbol`, `putCall`, `strikePrice`, `daysToExpiration`, `expirationDate`, `expirationType`, `settlementType`, `exerciseType`, `lastTradingDay`, `bid`, `ask`, `mark`, `last`, `openPrice`, `highPrice`, `lowPrice`, `closePrice`, `bidSize`, `askSize`, `bidAskSize`, `lastSize`, `totalVolume`, `openInterest`, `delta`, `gamma`, `theta`, `vega`, `rho`, `volatility`, `theoreticalVolatility`, `theoreticalOptionValue`, `quoteTimeInLong`, `tradeTimeInLong`, `multiplier`, `extrinsicValue`, `timeValue`, `intrinsicValue`, `inTheMoney`, `nonStandard`, `mini`, `pennyPilot`, `deliverableNote`.  
- **proposed disposition:** **REPLACED** — each key **`k`** has a matching `chains.callExpDateMap.*.<k>` row in `schwab_field_inventory/schwab_field_dictionary.csv` (**verified:** no `expiration` / `volume` keys remain in tuple).  
- **provenance trace:** `ct` from **`chains.contract_fields`** ← **`iter_contracts(c_json)`** ← **`safe_get_chain`**.  
- **code edit:** **landed** — removed **`expiration`**, **`volume`**.

### S2 — `_oe_first_contract_row` filters

- **lines:** 555–562  
- **surface:** `ct.get("putCall")`, `ct.get("strikePrice")`.  
- **proposed disposition:** **REPLACED** — `chains.callExpDateMap.*.putCall`, `.strikePrice`.  
- **provenance trace:** **S1**.  
- **code edit:** none.

### S3 — Composite / selection helpers using `ct.get`

- **lines:** 678–680, 801–803, 832–835, 839  
- **surface:** `c.get("putCall")`, `c.get("strikePrice")`, `ct.get("strikePrice")`, `ct.get("daysToExpiration")`.  
- **proposed disposition:** **REPLACED** — same canonical rows as **S2** + `chains.callExpDateMap.*.daysToExpiration`.  
- **provenance trace:** `contracts` list elements are **`contract_fields`** outputs (**S1**).  
- **code edit:** none.

### S4 — Bid/ask on **contract** row (`ct.get("bid")`, `ct.get("ask")`)

- **lines:** 812–813  
- **surface:** `float(ct.get("bid"))`, `float(ct.get("ask"))`  
- **proposed disposition:** **REPLACED** — `chains.callExpDateMap.*.bid`, `.ask`.  
- **provenance trace:** `ct` from **Schwab chain** contract dicts via **`contract_fields`**.  
- **code edit:** none.

### S5 — `_schwab_days_to_expiration_for_contract`

- **lines:** 819–842  
- **surface (per line):**  
  - **L830:** `ct.get("putCall", "")`  
  - **L833:** `ct.get("strikePrice")`  
  - **L837:** `ct.get("daysToExpiration")`  
- **proposed disposition:** **REPLACED** — `chains.callExpDateMap.*.putCall`, `.strikePrice`, `.daysToExpiration`.  
- **provenance trace:** `contracts` arguments are **`contract_fields`** dicts from Schwab chain (**`server._fetch_state`** pipeline).  
- **code edit:** none.

### S6 — Linked artifact — contract-dict `.get` closure

- **record:** Enumerated every line in `market_state.py` matching `(ct|c).get(` via Python `re` scan; output committed as **`governance/artifacts/schwab_v4_market_state_contract_dict_get_20260510.txt`** (12 lines, including **L549** projection comprehension and **L555–557, 676, 678, 799–801, 810–811, 830, 833, 837**). Sites **S1–S5** subsume these occurrences for **Schwab wire** disposition.

### S7 — `MarketState` / `SignalInput` attribute writes (`ms.spot`, `ms.net_delta`, `vwap`, walls, etc.)

- **lines:** (throughout `build_market_state`) e.g. 985–1210 region  
- **surface:** `ms.net_delta = …`, `ms.vwap_side = …`, `getattr(consensus_summary, "net_gamma", None)`, etc.  
- **proposed disposition:** **NOT_MARKET_DATA** at **Schwab JSON key** layer — **Python dataclass / summary object** fields; values are **derived** from upstream Schwab-backed computations.  
- **provenance trace:** Upstream **`server._fetch_state`** + **`compute_exposures_by_strike`** + quote parse — **this** file **does not** re-subscript `q_json` for those assignments.  
- **code edit:** none.

### S8 — `derive_zone`, `nd_color`, formatting helpers

- **lines:** 44–100, etc.  
- **proposed disposition:** **NOT_MARKET_DATA** — pure functions on **numeric / enum** inputs.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)  
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/market_state.py.md  
