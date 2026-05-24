> **Classification:** Policy Specification | **Scope:** Governance documentation `realized_contract_eval.py.md`.

# Review memo — realized_contract_eval.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**Closest-shape precedent** (per `AGENTS.md` Posture rules — sibling-pattern conformance, 2026-05-24): `market_state.py.md` S1 (`_oe_chain_row_snapshot` projection — same chain-row attribute family with `expirationDate` / `strikePrice` / `putCall` / `symbol` / `bid` / `ask` / `multiplier` canonical reads). Mixed-disposition shape similar to `polling_adapter.py.md` (some NOT_MARKET_DATA at Schwab wire-token layer, multiple REPLACED for direct chain JSON subscripts).

**Active-posture Class A check** (per `AGENTS.md` §Active agent posture + §Fix everything we touch, 2026-05-24): no Schwab-replaceable derivation outside the documented GOVERNED_EXCEPTION O-54 (`multiplier` legacy 100 fallback for pre-emission archived captures); no non-canonical fallback (no `bidSize`-class REST-vs-streaming mismatch); no actionable FIND. All missing-leaf paths fail-closed via explicit `skip()` semantics. **Memo-only commit admissible.**

---

---

## Gatekeeper CSV cross-check (retroactive @ 977e706, 2026-05-24)

**Tool:** \python tools/check_schwab_csv_first.py --gatekeeper-crosscheck realized_contract_eval.py\n**lexical_csv_collision_count:** 23

Retroactive full-CSV AST cross-check. Prior memo dispositions unchanged; homonym collisions classified in original site sections. Zero new wire FIND from cross-check.

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** for:

| Channel | Method |
|---------|--------|
| String-literal dict access on Schwab chain payloads | `ct.get("expirationDate")` (L151); `ct["multiplier"]` (L248, L250); `ct.get("symbol")` (L300, L955); `ct.get("putCall")` (L303); `ct.get("strikePrice")` (L305); `en.get("ask")` (L407); `ex.get("bid")` (L408); `entry_ct.get("ask")` (L902); `exit_ct.get("bid")` (L965); `entry_ct.get("symbol")` (L955); `exit_row["option_chain_json"]` (L938) — SNAPSHOTS column, not chain payload. |
| String-literal dict access on DB snapshot rows | `row.get("snapshot_id"\|"ts_utc"\|"ts_et"\|"expiry"\|"spot"\|"combined_signal"\|"option_chain_json"\|"rules_stop"\|"rules_target"\|"rules_entry"\|"replay_context_json")` — SNAPSHOTS table columns, not Schwab JSON. |
| Attribute access on market-bearing objects | `outcome.*` on `lifecycle_rule_core.fire_exit` result; `WallsRow` / `TotalsRow` dataclass fields. None on Schwab payload objects. |
| Method calls passing Schwab market objects | `recommend_option_expression(contracts=chain, …)` (L877) hands archived chain list back to `market_state.recommend_option_expression`; selection logic owned by `market_state.py` (per its memo). |
| Internal projection-key reads (NOT Schwab wire) | `replay_obj.get("walls"\|"option_chain_selection_proof")`; `proof.get("winner")`; `win.get("expression")`; `path_r.get("skip_reason"\|"exit_reason"\|"exit_row"\|"hold_bars"\|"path_model_used"\|"same_bar_stop_target_conflict"\|"same_bar_resolution_rule")`; trade-log dict assembly. None match any row in `schwab_field_inventory/schwab_field_dictionary.csv`. |
| Schwab field dictionary citations consumed | `chains.callExpDateMap.*.{expirationDate,strikePrice,putCall,symbol,bid,ask,multiplier}` and `chains.putExpDateMap.*.{...}` — dict L4–62 (calls) and L71–129 (puts). |

**Review complete:** Every site **in this file** falls under **S1–S10** below; no streaming `content.*` keys, no `quotes.*` subscripts, and no chain JSON keys beyond the seven canonical leaves enumerated above.

---

## Market-data sites identified

### S1 — Module imports + constants + STACK-WIRE-6b tunables

- **lines:** L1–77 — imports (L16–36); `log` (L38); STACK-WIRE-6b constants L40–53 (`DEFAULT_CONTRACTS`, `LEGACY_CHAIN_MULTIPLIER_DEFAULT = 100` per O-54, strike-match tolerances, ring-buffer max records); pricing rule strings L56–64 (`PRICING_ENTRY_RULE`, `PRICING_EXIT_RULE`, `EXIT_RULE_DOC`); skip-rate gates L66–68; file paths L70–77.
- **surface:** Python primitives + path constants. No Schwab JSON keys.
- **proposed disposition:** **NOT_MARKET_DATA** — module scaffolding; `LEGACY_CHAIN_MULTIPLIER_DEFAULT` is the documented O-54 legacy fallback constant (governance pointer at L46, full narrative in `governance/OPERATOR_DECISION_REGISTER.md`).
- **code edit:** none.

### S2 — `TRADE_LOG_FIELDS` + `_COARSE_BUCKETS` + path helpers

- **lines:** L79–139 — `TRADE_LOG_FIELDS` (29 internal CSV column names L79–109); `_COARSE_BUCKETS` skip-reason taxonomy L111–119; `trade_log_path_for_architecture` / `trade_log_path` / `aggregate_path` L122–139.
- **surface:** Internal CSV column names (`architecture_type`, `ticker`, `signal_time`, `entry_time`, `exit_time`, `right`, `strike`, `expiry`, `contract_symbol`, `entry_price`, `exit_price`, etc.) — **NOT** Schwab JSON keys. These are the eval pipeline's own output schema.
- **proposed disposition:** **NOT_MARKET_DATA** — internal projection-key set (same rule as `signals.py.md` S3).
- **code edit:** none.

### S3 — `serialize_option_chain_for_eval`

- **lines:** L142–159.
- **surface (Schwab chain read):** **L151:** `raw_exp = ct.get("expirationDate")` → `chains.callExpDateMap.*.expirationDate` / `chains.putExpDateMap.*.expirationDate` (dict L18 / L85).
- **proposed disposition:** **REPLACED** — canonical leaf; used to filter archived contract rows to the selected expiry on snapshot logging.
- **canonical_field:** `chains.callExpDateMap.*.expirationDate` + `chains.putExpDateMap.*.expirationDate`.
- **provenance trace (clause 4):** Called from `server.py` snapshot-persistence path with `contracts` = full Schwab chain (per `server.py.md` S12 / S13 expiration-filter pattern, same canonical field).
- **code edit:** none.

### S4 — `build_replay_context_payload`

- **lines:** L162–225.
- **surface:** Iterates `walls` / `totals` lists, converts `WallsRow` / `TotalsRow` dataclasses to dicts via `asdict`, or passes through dict items unchanged. No Schwab JSON keys subscripted — all reads are Python dataclass attributes via `asdict(w)`.
- **proposed disposition:** **NOT_MARKET_DATA** — payload assembly for replay context JSON (operator-side governance metadata: regime label, vol regime, max hold bars, vwap side, replay policies).
- **code edit:** none.

### S5 — `_f` + `_contract_multiplier` (FIND-WIRE6-3 / O-54)

- **lines:** L228–257. `_f` L228–229 (float coerce). `_contract_multiplier` L232–257.
- **surface (Schwab chain read):**
  - **L248–249:** `if "multiplier" not in ct or ct["multiplier"] is None: return LEGACY_CHAIN_MULTIPLIER_DEFAULT` — **GOVERNED_EXCEPTION O-54** branch (legacy absence; operator-documented per `governance/OPERATOR_DECISION_REGISTER.md`).
  - **L250:** `raw = ct["multiplier"]` → `chains.callExpDateMap.*.multiplier` / `chains.putExpDateMap.*.multiplier` (dict L35 / L102).
  - **L252–256:** invalid (non-numeric / zero / negative) → `return None` — fail-closed on data corruption.
- **proposed disposition:**
  - **L250 (canonical leaf read):** **REPLACED** — `chains.callExpDateMap.*.multiplier` + `chains.putExpDateMap.*.multiplier`.
  - **L248–249 (legacy absence fallback):** **GOVERNED_EXCEPTION (O-54)** — narrative in `governance/OPERATOR_DECISION_REGISTER.md`; **Permanent or interim:** interim — sunset when legacy snapshots backfilled or aged out (per docstring L43–44 and inline comment L46).
  - **L252–256 (corrupt-data fail-closed):** **NOT_MARKET_DATA** at disposition layer — defensive type guard.
- **canonical_field:** `chains.callExpDateMap.*.multiplier` + `chains.putExpDateMap.*.multiplier`.
- **provenance trace (clause 4):** Caller is `_contract_pnl_at_horizon` (L411) and main eval loop (L906). The `ct` argument is a single contract dict from the archived `option_chain_json` — itself sourced via `safe_get_chain` per `schwab_client.py.md` S4 → `c_json.get("callExpDateMap"|"putExpDateMap")` per `server.py.md` S10 → contract dicts per `market_state.py.md` S1 projection.
- **observation:** The four-channel exhaustion required for `NO_SCHWAB_EQUIVALENT` (V4-A clause 3) does **not** apply here — the field DOES have a Schwab leaf; the GOVERNED_EXCEPTION is for the legacy-absence path only. Three-element narrative (Why / Constraint / Permanent-or-interim) already present in `governance/OPERATOR_DECISION_REGISTER.md` per the L46 pointer.
- **code edit:** none.

### S6 — `_walls_from_replay` + `_forward_path_rows` + `_find_contract_row`

- **lines:** L260–308.
- **surface:**
  - `_walls_from_replay` (L260–272): iterates `obj.get("walls")` (internal replay key); instantiates `WallsRow(**item)` from dict items — no Schwab JSON keys here (replay payload is operator-side).
  - `_forward_path_rows` (L275–293): SQL `SELECT snapshot_id, ts_utc, ts_et, candle_open, candle_high, candle_low, candle_close, spot, option_chain_json FROM {table} WHERE ticker = ? AND timeframe = ? AND ts_utc > ? ORDER BY ts_utc ASC LIMIT ?` — DB column reads, no Schwab JSON. The `{table}` interpolation is the `SNAPSHOT_TABLE_1M` constant from `timeframe_config`, bounded value not user input.
  - `_find_contract_row` (L296–308): **L300:** `str(ct.get("symbol") or "")` → `chains.callExpDateMap.*.symbol` / `chains.putExpDateMap.*.symbol` (dict L54 / L121). **L303:** `str(ct.get("putCall") or "")` → `chains.callExpDateMap.*.putCall` / `chains.putExpDateMap.*.putCall` (dict L49 / L116). **L305:** `_f(ct.get("strikePrice"))` → `chains.callExpDateMap.*.strikePrice` / `chains.putExpDateMap.*.strikePrice` (dict L53 / L120).
- **proposed disposition:**
  - `_walls_from_replay` + `_forward_path_rows`: **NOT_MARKET_DATA** — internal replay payload + DB reads.
  - `_find_contract_row` (L296–308): **REPLACED** — three canonical chain leaves (`symbol` / `putCall` / `strikePrice`); strike match within `STRIKE_MATCH_TOL_PENNY = 0.011` for sub-penny float drift (FIND-WIRE6-4 — documented tolerance, not a substitution).
- **canonical_field:** `chains.callExpDateMap.*.{symbol,putCall,strikePrice}` + `chains.putExpDateMap.*.{symbol,putCall,strikePrice}`.
- **provenance trace (clause 4):** Caller is `_contract_pnl_at_horizon` (L401, L402) and main eval loop (L898, L956). The `chain` argument is the deserialized archived `option_chain_json` (Schwab chain row list).
- **code edit:** none.

### S7 — `_parse_expression` + `_expressions_match_live` + `_simulate_exit`

- **lines:** L311–390.
- **surface:** `_parse_expression` splits a string like `"595.0 C"` into `(strike_float, side)` — internal expression format from `market_state.recommend_option_expression`. `_expressions_match_live` compares replay-computed vs live-snapshot expressions via `proof.get("winner")` → `win.get("expression")` (internal proof keys). `_simulate_exit` wraps `lifecycle_rule_core.fire_exit` and reads `outcome.exit_bar_index` / `outcome.same_bar_conflict` / `outcome.exit_reason` / `outcome.skip_reason` (Python dataclass attributes); composes `path_model_used` label.
- **proposed disposition:** **NOT_MARKET_DATA** — internal expression parsing + replay-vs-live consistency check + exit simulation orchestration. No Schwab JSON keys.
- **code edit:** none.

### S8 — `_contract_pnl_at_horizon` + `_chain_selection_quality_row`

- **lines:** L393–532.
- **surface (Schwab chain read):**
  - **L407:** `_f(en.get("ask"))` → `chains.callExpDateMap.*.ask` / `chains.putExpDateMap.*.ask` (dict L6 / L73).
  - **L408:** `_f(ex.get("bid"))` → `chains.callExpDateMap.*.bid` / `chains.putExpDateMap.*.bid` (dict L8 / L75).
  - **L411:** `_contract_multiplier(en)` — delegates to S5.
- **rest of S8 surface:** Top-5 alt-strike PnL scaffolding (L417–532) — iterates `ranked_top5` proof rows reading internal keys (`composite_score`, `strike`); calls `_contract_pnl_at_horizon` for non-selected strikes; assembles quality audit row with `selected_was_best_among_scored_alternatives` / `selected_pnl_rank_among_known` / `pnl_gap_vs_best` etc. (internal projection keys).
- **proposed disposition:**
  - **L407, L408 (canonical leaf reads):** **REPLACED** — `chains.*.ask` + `chains.*.bid`. Fail-closed when `a is None or a <= 0 or b is None` (L409–410); returns `None` PnL — caller treats as skip.
  - **L411 multiplier:** delegates to S5 disposition.
  - **Quality scaffolding (L417–532):** **NOT_MARKET_DATA** — internal alt-strike PnL audit using already-REPLACED chain reads recursively.
- **canonical_field:** `chains.callExpDateMap.*.{ask,bid}` + `chains.putExpDateMap.*.{ask,bid}`.
- **provenance trace (clause 4):** Caller is `_chain_selection_quality_row` (L448) and main eval loop (uses entry_ct.ask + exit_ct.bid directly at L902 / L965 — same canonical leaves).
- **code edit:** none.

### S9 — Coverage stats + audit/debug file I/O + parallel/cascade trade-log compare

- **lines:** L535–746 — `compute_replay_coverage_stats` + `save_replay_coverage_report` (L535–597); `_append_chain_quality_audit` + `_coarse_skip` + `_append_trade_csv` + `_update_chain_debug_file` (L600–689); `compare_parallel_cascade_trade_logs` (L692–746).
- **surface:** DB I/O (replayable-rows coverage SQL, parameterized; no Schwab JSON in SQL), JSON file I/O for audit/debug ring buffers (`CHAIN_QUALITY_AUDIT_MAX_RECORDS = 5000`, `CHAIN_DEBUG_MAX_RECORDS = 200`), CSV reads of trade logs for parallel/cascade overlap metrics. No Schwab JSON key subscripts.
- **proposed disposition:** **NOT_MARKET_DATA** — DB + file I/O + internal trade-log overlap analytics. The "skipped_flag" / "signal_time" / "pnl_dollars" / "strike" / "right" / "expiry" / "contract_symbol" keys (L701, L703, L716–719, L726) are internal CSV column names (S2).
- **code edit:** none.

### S10 — `evaluate_realized_contract_trades_for_rows` (main eval loop) + `save_eval_aggregate_merge`

- **lines:** L749–1190.
- **surface (Schwab chain reads inside the main loop, L779–1031):**
  - **L902:** `entry_ask = _f(entry_ct.get("ask"))` → `chains.*.ask` (same as S8).
  - **L906:** `multiplier = _contract_multiplier(entry_ct)` — delegates to S5.
  - **L955:** `sym = entry_ct.get("symbol")` → `chains.*.symbol` (same as S6).
  - **L965:** `exit_bid = _f(exit_ct.get("bid"))` → `chains.*.bid` (same as S8).
  - **L898 / L956:** `_find_contract_row(...)` — delegates to S6.
- **surface (REPLAY orchestration, no Schwab JSON):** DB row reads (`snap_id`, `ts_utc`, `ts_et`, `expiry`, `spot`, `call_sig`, `chain_raw`, `r_stop`, `r_tgt`, `r_entry`, `replay_raw`); JSON deserialization of `replay_context_json` and `option_chain_json` from snapshot columns; calls `recommend_option_expression(contracts=chain, …)` (delegates Schwab chain selection to `market_state.py`); `_simulate_exit(...)` (delegates exit simulation to `lifecycle_rule_core`); PnL math `(exit_bid - entry_ask) * multiplier * DEFAULT_CONTRACTS`; trade-log dict assembly with internal CSV column keys; per-ticker aggregate compute (win rate / median / expectancy / skip-rate gates / chain-selection quality summary). `save_eval_aggregate_merge` (L1141–1190) merges per-ticker eval into `models/realized_contract_eval_aggregate.json` with per-architecture skip-rate aggregation.
- **proposed disposition:**
  - **Inline chain reads (L902 / L955 / L965):** **REPLACED** — delegates to S6 / S8 canonical leaves; all fail-closed via `skip()` semantics.
  - **L906 multiplier:** delegates to S5 (REPLACED + O-54 fallback narrative).
  - **REPLAY orchestration:** **NOT_MARKET_DATA** — DB + replay-payload + delegation + PnL math + CSV/JSON assembly.
- **observation:** Every Schwab chain leaf read in the main loop has explicit `skip()` semantics for missing/invalid data:
  - `if entry_ask is None or entry_ask <= 0: skip("missing_entry_ask")` (L903–905)
  - `if multiplier is None: skip("missing_multiplier")` (L907–909)
  - `if exit_bid is None or exit_bid <= 0: skip("missing_exit_bid")` (L966–968)
  - `if not entry_ct: skip("entry_contract_not_in_chain")` (L899–901)
  - `if not exit_ct: skip("exit_contract_not_found")` (L962–964)
  - Fail-closed throughout; no fabricated PnL when leaves are missing.
- **code edit:** none.

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

Bulk **NOT_MARKET_DATA** at Schwab `example_raw_field` token layer:

- **Module scaffolding (S1, S2):** Imports, sizing/tolerance constants, ring-buffer maxima, file path constants, internal CSV column schema (`TRADE_LOG_FIELDS`), coarse skip-reason taxonomy (`_COARSE_BUCKETS`).
- **Internal replay payload (S4, S6 partial, S7, S10 partial):** `WallsRow` / `TotalsRow` dataclass conversion via `asdict`; replay context JSON keys (`walls`, `totals`, `option_chain_selection_proof`, `replay_max_hold_bars*`, `vwap` / `vwap_side`, `regime_*`, `vol_regime`, `call_trade_type`, etc.); proof object internal keys (`winner`, `expression`, `ranked_candidates_top5`, `wall_ablation_winner`).
- **DB I/O + file I/O (S6 partial, S9, S10 orchestration):** SNAPSHOTS table column reads, parameterized SQL (`SNAPSHOT_TABLE_1M` interpolation is a constant from `timeframe_config`, not user input), JSON deserialization of archived `option_chain_json` / `replay_context_json` columns, CSV writes to `trade_log_*.csv`, JSON file writes to `chain_selection_quality_audit.json` / `option_chain_selection_debug.json` / `replay_coverage_report.json` / `realized_contract_eval_aggregate.json`.
- **Expression parsing + replay-vs-live consistency (S7):** `_parse_expression` string split on internal `"595.0 C"` format from `market_state.recommend_option_expression`; `_expressions_match_live` strike comparison within `STRIKE_MATCH_TOL_NICKEL = 0.02`.
- **PnL math + skip-rate gates + quality scaffolding (S8 partial, S10 partial):** `(exit_bid - entry_ask) * multiplier * DEFAULT_CONTRACTS`; per-ticker aggregate (win rate, median, expectancy); skip-rate warning/fail flags (`SKIP_RATE_WARNING_THRESHOLD = 0.35`, `SKIP_RATE_FAIL_THRESHOLD = 0.55`); chain-selection quality summary (`selected_was_best_rate`, `selected_was_top2_rate`, `average_pnl_gap_vs_best`, `average_score_gap_vs_best`).

**REPLACED dispositions** concentrate in S3 (`expirationDate`), S5 (`multiplier` + O-54 legacy fallback), S6 (`symbol` / `putCall` / `strikePrice` via `_find_contract_row`), S8 (`ask` / `bid` via `_contract_pnl_at_horizon`), and S10 (same chain reads inline in the main loop). Seven canonical chain leaves total: `expirationDate`, `strikePrice`, `putCall`, `symbol`, `bid`, `ask`, `multiplier` — all in Schwab dictionary under `chains.callExpDateMap.*` (L4–62) and `chains.putExpDateMap.*` (L71–129).

**GOVERNED_EXCEPTION** count: 1 (O-54 `multiplier` legacy fallback) — narrative already in `governance/OPERATOR_DECISION_REGISTER.md`; three-element shape (Why / Constraint / Permanent-or-interim) present per the L43–44 docstring + L46 inline pointer.

This file's contribution to V4 closure is **establishing the REPLAY-mode chain consumer** as Schwab-wire-clean: every chain JSON subscript uses a canonical CamelCase Schwab REST key with explicit skip-on-missing semantics; the one operator-cited exception (O-54 multiplier legacy absence) is the documented governed path for pre-emission archived captures. No `bidSize`-class cross-shape leak (file works with REST chain payload only — no streaming `content.*` mixing).

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/realized_contract_eval.py.md
- **Class A determination:** memo-only commit admissible — every chain leaf read is REPLACED (canonical) or GOVERNED_EXCEPTION (O-54 already operator-signed); no actionable code edit, no new non-canonical fallback, no in-file FIND requiring a same-commit fix. Bundling not required.
