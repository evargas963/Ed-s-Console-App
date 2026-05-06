# Repo Cleanup Queue

**Status:** Open cleanup queue  
**Created:** 2026-05-06  
**Policy reference:** `governance/ENGINEERING_GATEKEEPING_POLICY.md`

---

## Purpose

This queue tracks dead-code, stale-doc, temporary-artifact, and bloat candidates that should not be removed blindly during unrelated work. Entries here require disposition: remove, archive, retain with rationale, or defer with owner/trigger.

Queue entries should be added when cleanup is identified but not safely in scope for the current commit.

---

## Entry Schema

```text
file_path
why_flagged
date_flagged
recommended_resolution
status
notes
```

Valid statuses:

```text
open
needs_operator_disposition
resolved
retained_with_rationale
archived
```

---

## Open Items

| File path | Why flagged | Date flagged | Recommended resolution | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `governance/INSTITUTIONAL_STANDARD_WISHLIST.md` | V1 institutional standard wishlist appears superseded by later institutional standard governance. | 2026-05-06 | Move to `governance/archive/` if no live references or operator retention need exists. | open | Verify references before moving. |
| `governance/INSTITUTIONAL_STANDARD_V2.md` | Superseded by `governance/INSTITUTIONAL_STANDARD_V3.md` / V3.1-era governance. | 2026-05-06 | Move to `governance/archive/` if no live references or operator retention need exists. | open | Verify references before moving. |
| `governance/V3_CONFORMANCE_AUDIT_TEMPLATE.md` | Template appears redundant with completed `governance/V3_CONFORMANCE_AUDIT.md`. | 2026-05-06 | Move to `governance/archive/` or retain with explicit template reuse rationale. | open | Verify whether future audits still use the template. |
| Dirty working tree files | Current working tree contains many modified and untracked files outside the v2 calibration commits. | 2026-05-06 | Separate operator disposition pass: keep, commit by topic, archive, or discard only with explicit approval. | resolved | Disposition completed in approved topic commits; generated reports ignored, rejected placeholder/NULL-skip hunks reverted, and follow-up workstreams retained below. |
| `multi_horizon_ml_bundle.py:121-157` | Unavailable fusion path constructs neutral probability placeholders; downstream substitution into authoritative `pred_*` columns was rejected as V3 I-01 risk. | 2026-05-06 | Audit whether placeholders are non-authoritative metadata with hard consumer gating; otherwise redesign to preserve unavailable state explicitly. | open | Do not reintroduce placeholder-to-prediction substitution without governance review. |
| `db.py` snapshot outcome update invariant | `snapshots.snapshot_id` should be non-NULL for selected snapshot rows; a proposed skip was rejected as silent error suppression. | 2026-05-06 | If NULL `snapshot_id` is ever observed, root-cause the broken source/table assumption instead of skipping affected rows. | open | `snapshot_id` is `INTEGER PRIMARY KEY AUTOINCREMENT`; absence is an invariant violation. |
| `realized_contract_eval.py:146-188,846,961,990,1013` | `realized_contract_eval` still reads raw option-chain dict fields for replay serialization, selection, and entry/exit pricing instead of routing through `chains.contract_fields()` or an equivalent normalized accessor. | 2026-05-06 | Normalize replay contract access at the boundary before using these rows for durable A2 label training or replay/live parity gates. | resolved | Gap ID: `realized_contract_eval_raw_chain_reads_pending_normalization`; resolved by routing serialization and replay archive contract rows through `chains.contract_fields()` while leaving unverified Schwab fields unpromoted. |
| `lifecycle_rule_core_awaiting_consumers` | `lifecycle_rule_core.py` introduced as shared static rule core but no consumer imports it yet. | 2026-05-06 | Rewire `realized_contract_eval._simulate_exit` and in-scope `call_engine.py` geometry in separate commits, then close this transitional entry. | open | Two-truths state remains until Commit B and Commit C land; closes when no in-scope static geometry / firing logic remains duplicated outside `lifecycle_rule_core.py`. |

---

## Resolution Log

| Date | Entry | Resolution |
| --- | --- | --- |
| 2026-05-06 | Dirty working tree files | Resolved through operator-approved disposition: generated artifacts ignored, ad-hoc gap scripts superseded by `tools/inspect_price_bars_1m_rth_gaps.py`, rejected hunks reverted, and coherent topic commits pushed through `7d628c9`. |
| 2026-05-06 | `realized_contract_eval_raw_chain_reads_pending_normalization` | Resolved by replacing the hand-rolled replay serializer dict with `chains.contract_fields()` and normalizing archived entry/exit chain rows before selection or pricing; `underlyingSymbol`, contract-level `volume`, and `expiration` were not promoted because curated Schwab inventory did not confirm them as contract fields. |
