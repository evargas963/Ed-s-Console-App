> **Classification:** Policy Specification | **Scope:** Governance documentation `live_decision_bundle.py.md`.

# Review memo — live_decision_bundle.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Cursor (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)** + `AGENTS.md` §V4 walk / review-memo rule (gatekeeper CSV-first cross-check, 2026-05-24 @ `977e706`)

**Closest-shape precedent:** `signals.py.md` (orchestration over upstream-populated structures — no in-file Schwab wire); `mc_fusion_adjustment.py.md` @ `706f8eb` (gatekeeper section shape).

**Active-posture Class A check:** Full end-to-end Read (457 lines). No Schwab-replaceable derivation, no non-canonical fallback, no in-file wire FIND. No code edit required this slice — paired tests already lock fail-closed tick triggers (`tests/test_live_decision_bundle_tick_triggers.py`, 6 cases).

---

## Gatekeeper CSV cross-check (mandatory per AGENTS §V4 walk rule, 977e706)

**Tool:** `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck live_decision_bundle.py`
**CSV lookup tokens loaded:** 394 (from `schwab_field_inventory/schwab_field_dictionary.csv`)
**lexical_csv_collision_count:** 0

**Zero wire reads.** No Schwab JSON subscripts (`q_json`, `c_json`, `pricehistory`, streaming `content.*`) anywhere in file. All market-bearing values arrive via `ms_dict` trunk keys populated upstream (`market_state.py`, `server.py` — LEAF citations belong to those producer memos) or as caller-supplied `stream_spot` / `stream_of_regime` floats.

---

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** (457 lines) for string-literal dict access, bracket access, attribute access on market objects, and method calls passing Schwab payloads.

**Review complete:** Every site falls under **S1–S6** below.

---

## Market-data sites identified

### S1 — Module scaffolding + tick-refresh constants

- **lines:** L21–48.
- **surface:** Imports, logger, lock, `_next_generation_id`, env-overridable tick-refresh thresholds (`TICK_REFRESH_SPOT_PCT_DEFAULT`, `TICK_REFRESH_SPOT_ABS_DEFAULT`).
- **proposed disposition:** **NOT_MARKET_DATA** — module scaffolding / policy constants.
- **code edit:** none.

### S2 — `stamp_decision_bundle`

- **lines:** L54–85.
- **surface:** Mutates `ms_dict` with `decision_generation_id`, `decision_timestamp_utc`, `decision_tick_kind`, `decision_generation_skipped`. Fail-closed when `signals_engine_failed`.
- **proposed disposition:** **NOT_MARKET_DATA** — bundle coherence metadata stamp; no Schwab wire.
- **code edit:** none.

### S3 — `_key_levels_from_ms_dict`

- **lines:** L100–146.
- **surface:** Reads `kl_call_gamma_wall`, `kl_put_gamma_wall`, `kl_hvl`, `kl_max_pain`, `kl_gamma_inflection`, `kl_call_delta_wall`, `kl_put_delta_wall`, `kl_delta_inflection`, `kl_call_oi_wall`, `kl_put_oi_wall`, `vwap` from `ms_dict`. Values are upstream-derived structure levels (canopy keys; LEAF chain in `market_state.py.md` / `server.py.md`).
- **proposed disposition:** **NOT_MARKET_DATA at wire-token layer** — consumes populated trunk; does not read Schwab JSON.
- **code edit:** none.

### S4 — `recompute_nearest_struct_at_spot`

- **lines:** L152–198.
- **surface:** Nearest above/below wall selection at alternate `spot_f` using S3 level list; `canonical_nearest_distances` for distance buckets.
- **proposed disposition:** **NOT_MARKET_DATA** — pure geometry on cached structure levels + spot float.
- **code edit:** none.

### S5 — Session bucket helpers

- **lines:** L204–238 (`_session_bucket_et`, `_session_bucket_from_utc_ts`, `_live_session_label`).
- **surface:** ET session bucket via `math_volatility.session_bucket`; live session label via `market_context._derive_session()` (time/regime classification — not Schwab wire in this file).
- **proposed disposition:** **NOT_MARKET_DATA** — clock/session classification glue.
- **code edit:** none.

### S6 — `tick_triggers_coherent_refresh`

- **lines:** L244–456.
- **surface:** Read-only coherence checks comparing `stream_spot` / `stream_of_regime` against cached `ms_dict` fields (`spot`, `zone`, `bias_signal`, `net_delta`, `session_label`, `decision_timestamp_utc`, `vwap`, `vwap_side`, nearest wall names/distances, `order_flow_regime`). Triggers full `_fetch_state` refresh when drift detected. Every check fail-closed toward refresh on exception (paired tests lock this — SWEEP-EP-4).
- **proposed disposition:** **NOT_MARKET_DATA at wire-token layer** — bundle coherence policy; inputs are trunk-populated ms_dict + stream floats from plane/order-flow paths.
- **code edit:** none.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/live_decision_bundle.py.md
- **Class A determination:** audit complete, zero CSV collisions, zero wire reads, no code FIND. Paired tests pre-exist; no in-cone hardening required.
