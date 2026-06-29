> **Classification:** Policy Specification | **Scope:** Governance documentation `features/inference_snapshot.py.md`.

# Review memo — features/inference_snapshot.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24 (Lane A lineage memo update 2026-06-29 @ `c919639`)
**Reviewer:** Cursor (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**Evidence bar:** V4-A + AGENTS gatekeeper CSV cross-check @ `977e706`

**Class A:** Full Read + cone Read of `features/live_feature_adapter.py`, `features/db_feature_adapter.py`. InferenceSnapshotV1 envelope builder; MVP features via adapters. Lane A adds operator-visible `field_lineage` metadata only (no wire reads, no value mutation).

---

## CSV-First Declaration (Lane A — operator field lineage labeling)

```text
Schwab CSV authority checked: yes
CSV row(s): quotes.*.lastPrice; quotes.*.mark; quotes.*.bidPrice; quotes.*.askPrice
Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE
All consumers checked: yes — server.py::_fetch_state + Tier-C JSON paths attach additive field_lineage only; no value mutation
```

Lane A classifies existing Tier-C payload keys (`spot`, `bid`, `ask`, `call_state`, `mhap_rows`, fusion triplets, `wait_reason`, `expected_move`, `analytics_stale`) using `quote_source_detail` and upstream producer labels. No new Schwab wire reads; no numeric or decision-path changes.

---

## Gatekeeper CSV cross-check

**Tool:** `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck features/inference_snapshot.py`
**lexical_csv_collision_count:** 10

| Token / site | CSV homonym example | Lane A disposition |
|--------------|---------------------|-------------------|
| `lastPrice`, `mark`, `bidPrice`, `askPrice` (L283–286) | `_SCHWAB_QUOTE_LEAF_BY_DETAIL` dict keys | **HOMONYM** — maps existing `quote_source_detail` strings to leaf citations; no wire subscript |
| `bid`, `ask` (L369–373) | dict.get / field labels on Tier-C md | **HOMONYM** — classifies existing md values via `_quote_field_lineage`; no new emission |

**No new wire reads.** Lane A reads existing md keys only. LEAF citations for live quote values remain in producer memos (`server.py.md`, `market_state.py.md`).

---

## Disposition summary

| Section | Disposition |
|---------|-------------|
| `build_inference_snapshot_v1*` / `_assert_inference_snapshot_v1` | **NOT_MARKET_DATA** @ wire — canonical contract envelope + validation |
| `_lineage_entry`, `attach_operator_field_lineage` | **NOT_MARKET_DATA** @ wire — metadata envelope / in-place attach |
| `_quote_field_lineage`, `build_operator_field_lineage` | **KEEP_DERIVED_WITH_PROVENANCE** — classifies existing trunk values; no mutation |
| Cone: `live_feature_adapter`, `db_feature_adapter` | **NOT_MARKET_DATA** @ wire — strict coercion from trunk keys |
| `market_state.py::attach_operator_visible_field_lineage` | **NOT_MARKET_DATA** @ wire — thin delegate to `attach_operator_field_lineage` |

**code edit:** Lane A landed @ `c919639` (metadata only). This memo update is governance/inventory closure only.
