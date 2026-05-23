> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/feature_contract_source_mapping.md`.

# MVP source → canonical mapping (`v1_1m_mvp`)

Exact field mapping used by `build_live_mvp_feature_row` and `build_db_mvp_feature_row`.
Coercion rules live in `features/mvp_source_coercion.py` (strict: missing ≠ invalid).

## Source-to-canonical table

| Canonical (MVP) | Live source (`l1_payload`) | DB source (`snapshot_row`) | Meaning |
|-----------------|----------------------------|------------------------------|---------|
| `price.spot` | `spot` | `spot` | Last / reference spot price for the bar. |
| `price.spread_pts` | `spread` | `spread` | Bid–ask width in **points** (same units as price). |
| `structure.zone` | `zone` (top-level structural) | `zone` | Structural zone token (locked vocabulary). |
| `structure.nearest_above_dist` | `nearest_above_dist` | `nearest_above_dist` | Signed distance to nearest meaningful level above. |
| `structure.nearest_below_dist` | `nearest_below_dist` | `nearest_below_dist` | Signed distance below (negative allowed per convention). |
| `structure.net_gamma` | `net_gamma` | `net_gamma` | Net gamma exposure snapshot. |
| `anchor.vwap_side` | `vwap_side` (flat; **not** `spot_anchors`) | `vwap_side` | Position of spot vs session VWAP (`above` / `below`). |
| `anchor.vwap_dist_pts` | `dist_to_vwap_pts` | `vwap_dist_pts` | Spot − VWAP in **points** (signed). |
| `liquidity.absorption_score` | `liquidity_summary['absorption_score']` | `absorption_score` | Absorption score from liquidity slice. |
| `liquidity.continuation_score` | `liquidity_summary['continuation_score']` | `continuation_score` | Continuation score from liquidity slice. |

### Live-only nesting

- If `liquidity_summary` is **absent** or **null**, nested liquidity keys are treated as **missing** (canonical `None` for both scores).
- If `liquidity_summary` is **present** and not `null`, it **must** be a `dict`; otherwise coercion raises `MvpFeatureSourceError`.

## Missing vs invalid (numeric)

| Situation | Result |
|-----------|--------|
| Source **key absent** | Canonical `None` (**missing**). |
| Source **key present**, value **null** | Canonical `None` (**missing**). |
| Source **key present**, value **non-null** but not a legal finite scalar numeric | `MvpFeatureSourceError` (**invalid**; never mapped to `None`). |

Strings are parsed with `float(...)`; `bool` is **not** numeric. Collections (`dict`, `list`, …) are invalid for numeric fields.

## Semantic parity audit

`features/semantic_parity.assert_live_db_canonicalization_equivalent` builds both canonical rows from controlled fixtures and asserts equality — same transformation rules for equivalent logical values across live and DB column names.
