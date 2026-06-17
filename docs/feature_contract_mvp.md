> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/feature_contract_mvp.md`.

# MVP canonical feature contract (`v1_1m_mvp`) — strict boundary

## Canonical timeframe

- **`CANONICAL_FEATURE_TIMEFRAME = "1m"`** — single modeling clock for this contract.
- Higher timeframes are **not** part of MVP; derive later from 1m or separate views.

## Missing vs invalid (source → canonical)

At adapters (`live_feature_adapter`, `db_feature_adapter`), coercion is **strict** (`mvp_source_coercion`):

| | Definition |
|---|------------|
| **Missing** | Source key is absent **or** the value is JSON/SQL null → canonical **`None`**. |
| **Invalid** | Source key is present with a non-null value that cannot be coerced to a legal canonical value → **`MvpFeatureSourceError`** (never laundered into **`None`**). |

Unparseable numerics (`"abc"`, `"not_a_number"`), wrong types (`bool`, `dict`, `list` for numeric fields), non-finite floats, empty categorical strings, and vocabulary violations are **invalid**.

Per-field text: `get_mvp_field_semantics(name)` in `features/canonical_contract.py` (`missing` / `invalid` / `valid`).

Full source column mapping: [feature_contract_source_mapping.md](./feature_contract_source_mapping.md).

## Strict validation (`validate_feature_contract_row`)

Enforced in `features/canonical_contract.py` on the **canonical row** after adapters:

| Rule | Behavior |
|------|----------|
| Key set | **Exactly** the 10 MVP keys; **no** `extra` keys; **no** missing keys |
| Key order | **Must** match `get_mvp_feature_names()` order (drift protection) |
| `None` | **Allowed** for any field (optional / missing-at-tick) |
| Numeric types | `int` or `float` only when non-`None`; **`bool` rejected** |
| Numeric finiteness | **Finite** only — `NaN` and `±inf` **rejected** |
| String types | `str` only when non-`None`; **empty string rejected** (use `None`) |
| Categoricals | **Lowercase canonical tokens** only (no leading/trailing whitespace); must match locked vocabularies below |
| `price.spot` | If non-`None`: **must be > 0** |
| `price.spread_pts` | If non-`None`: **must be ≥ 0** |
| Signed distances | `structure.nearest_above_dist`, `structure.nearest_below_dist`, `anchor.vwap_dist_pts`, `structure.net_gamma`, liquidity scores: **any finite sign** unless noted |

## Locked categorical vocabularies

Normalized in adapters via **strip + lowercase + vocabulary check** (invalid → raise):

### `structure.zone`

Must be one of:

`pin_bull`, `pin_bear`, `pin_neutral`, `pin_chaos`, `breakout`, `breakdown`

(Aligned with `lstm_data.ZONE_MAP` / structural zones.)

### `anchor.vwap_side`

Must be one of:

`above`, `below`

## MVP feature field rules (reference)

| Canonical name | Python type(s) when non-`None` | `None` allowed | Empty `str` | Non-finite | Other domain |
|----------------|----------------------------------|----------------|-------------|------------|--------------|
| `price.spot` | `int` / `float` | yes | N/A | rejected | must be **> 0** |
| `price.spread_pts` | `int` / `float` | yes | N/A | rejected | must be **≥ 0** |
| `structure.zone` | `str` | yes | forbidden | N/A | must be in **ALLOWED_ZONE_VALUES** |
| `structure.nearest_above_dist` | `int` / `float` | yes | N/A | rejected | signed OK |
| `structure.nearest_below_dist` | `int` / `float` | yes | N/A | rejected | signed OK (negative allowed) |
| `structure.net_gamma` | `int` / `float` | yes | N/A | rejected | signed OK |
| `anchor.vwap_side` | `str` | yes | forbidden | N/A | must be in **ALLOWED_VWAP_SIDE_VALUES** |
| `anchor.vwap_dist_pts` | `int` / `float` | yes | N/A | rejected | signed OK |
| `liquidity.absorption_score` | `int` / `float` | yes | N/A | rejected | signed OK |
| `liquidity.continuation_score` | `int` / `float` | yes | N/A | rejected | signed OK |

## Adapters

- **Live:** `features/live_feature_adapter.build_live_mvp_feature_row` — `mvp_source_coercion.read_optional_*` + `read_liquidity_summary_subdict`.
- **DB:** `features/db_feature_adapter.build_db_mvp_feature_row` — same helpers keyed by DB column names.

## Semantic parity (audit)

- **Helper:** `features/semantic_parity.assert_live_db_canonicalization_equivalent` — asserts identical canonical rows for equivalent live vs DB fixtures.

## Inference snapshot (`InferenceSnapshotV1`)

`features/inference_snapshot.build_inference_snapshot_v1`:

- **Mandatory:** `snapshot_type`, `feature_contract_version`, `canonical_timeframe` (fixed `"1m"`), `source` (`live_l1_tier_b`).
- **Fails hard** if live coercion raises or MVP feature row fails validation.
- **`feature_quality`:** `present_count` + `missing_count` === 10; `len(missing_fields)` === `missing_count`.

## Excluded from MVP

- `order_flow.*`, readiness, live freshness diagnostics, `l1_generation`, instrumentation — unchanged.

## Live-only vs canonical modeling

- **Canonical modeling features:** the 10 MVP fields above when they pass validation.
- **Live-only execution/context** (not in MVP row): SSE generation, staleness, overlay metadata — **not** in this contract.
