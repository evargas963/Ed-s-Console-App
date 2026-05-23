> **Classification:** Policy Specification | **Scope:** Governance documentation `REPO_CLEANUP_QUEUE.md`.

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
| `realized_contract_eval.py:146-188,846,961,990,1013` | `realized_contract_eval` historically read raw option-chain dict fields for replay serialization, selection, and entry/exit pricing instead of routing through a normalized accessor. | 2026-05-06 | Normalize replay contract access at the boundary before using these rows for durable A2 label training or replay/live parity gates. | resolved | Gap ID: `realized_contract_eval_raw_chain_reads_pending_normalization`; first resolved by routing serialization and replay archive contract rows through the then-current `chains.py::contract_fields()` helper, then re-resolved durably by the Schwab-direct redesign — `chains.py` was removed and replay/serialization now reads `chain_row` fields inline using Schwab `canonical_field` names per the Precedence Principle in `governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md`. |
| `lifecycle_rule_core_awaiting_consumers` | `lifecycle_rule_core.py` introduced as shared static rule core but no consumer imports it yet. | 2026-05-06 | Rewire `realized_contract_eval._simulate_exit` and in-scope `call_engine.py` geometry in separate commits, then close this transitional entry. | resolved | Resolved by `abb5587` wiring replay exit firing and Commit C wiring `call_engine.py` threshold geometry to `lifecycle_rule_core.py`; verified no in-scope production geometry remains duplicated in `_stop_distance` / `_compute_levels` for VIX >20/>30 thresholds, time decay, risk multiplier clamp, or structural snap math. |
| `v2_decision/a2_option_expression.py:383,512` | `a2_option_expression.py:383` reads `_first_number(ms_dict.get("mins_to_close"), ms_dict.get("minutes_to_close"))` and `a2_option_expression.py:512` reads `_num(ms_dict.get("mins_to_close"))`. Neither `mins_to_close` nor `minutes_to_close` is a `MarketState` dataclass field; only function parameters of `build_market_state` (`market_state.py:847-849`). Since `_ms_to_dict` only serializes dataclass fields, both reads silently return None in production. Downstream consumer behavior on the always-None result is unverified; this may be latent bug or dead-code defensive. | 2026-05-06 | Verify what `_first_number(None, None)` and `_num(None)` produce, and whether downstream code exercises any path that depends on a non-None value. If unused, remove the reads or mark as explicit TODO. If used, fix propagation by either adding `mins_to_close` to the `MarketState` dataclass (so `_ms_to_dict` auto-propagates it) OR computing inline at the call sites from existing clock sources (e.g., `decision_time_ms` + `RTH_CLOSE_MINS`). | resolved | Gap ID: `a2_option_expression_mins_to_close_unpropagated_input_pending`. Found during A2 EOD force-exit contract Map-1 pre-check (`20a1c14`). Flagged separately per operator directive (not bundled with the EOD contract or its future code commit). Resolved by this fix commit — investigation confirmed both call sites are real production reads (L383 drives `late_day_gamma.status` / soft gates; L512 unlocks Black-Scholes theta fallback). Fix: new `_mins_to_close(ms_dict)` helper reuses `derive_et_clock_from_decision_time_ms` from `a2_eod_force_exit`; honors explicit value, otherwise derives from `decision_time_ms`. 5 new tests include 2 `decision_time_ms`-only paths. Existing fixtures stay green. |

---

## Resolution Log

| Date | Entry | Resolution |
| --- | --- | --- |
| 2026-05-06 | Dirty working tree files | Resolved through operator-approved disposition: generated artifacts ignored, ad-hoc gap scripts superseded by `tools/inspect_price_bars_1m_rth_gaps.py`, rejected hunks reverted, and coherent topic commits pushed through `7d628c9`. |
| 2026-05-06 | `realized_contract_eval_raw_chain_reads_pending_normalization` | First resolved by replacing the hand-rolled replay serializer dict with the then-current `chains.py::contract_fields()` helper and normalizing archived entry/exit chain rows before selection or pricing; `underlyingSymbol`, contract-level `volume`, and `expiration` were not promoted because curated Schwab inventory did not confirm them as contract fields. Subsequently superseded by the Schwab-direct redesign (`chains.py` removed); replay serialization now reads `chain_row` fields inline using Schwab `canonical_field` names per the Precedence Principle. |
| 2026-05-06 | `lifecycle_rule_core_awaiting_consumers` | Resolved by wiring both planned consumers: `realized_contract_eval._simulate_exit` in `abb5587` and `call_engine.py` threshold geometry in Commit C. Duplication check confirmed the in-scope VIX, time decay, risk multiplier, and structural snap production logic in `_stop_distance` / `_compute_levels` now routes through `lifecycle_rule_core.py`; separate VIX sizing logic remains out of scope. |
