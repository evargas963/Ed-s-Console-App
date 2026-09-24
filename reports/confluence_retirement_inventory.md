# Index confluence retirement inventory

Catalog of every consumer of `market_context`'s SPY/QQQ/IWM constituent-weight
confluence outputs (weighted pushes, IWM holdings/sectors blend, `bond_signal`,
and the T-08..T-15 fallbacks that feed them). Classification is from a same-session
grep of the tree; it is a consumer map, not a runtime measurement.

Disposition after this change:

- Live screens that still name these fields keep the surface and show unavailable
  (`—` / withheld with reason `index_confluence_retired`).
- Persisted DB columns are **not dropped**. Writers stop; new rows leave them NULL.
- ML feature contracts are **not changed**. Named features become
  `dormant: absent until retrained`.
- Dead / test-only producers of the retired math are deleted or rewritten to pin
  absence.

## Live screens

| Consumer | File | Fields | Class | After retirement |
|---|---|---|---|---|
| `/api/state` confluence stamp | `server.py` (`ms_dict.update(stamp_confluence_display_fields(...))`) | `cf_weighted_push`, `cf_label`, `cf_color`, `cf_dot_*`, `qqq_cf_*`, `iwm_cf_*`, `iwm_holdings_cf_*`, `iwm_participation_push` | live screen (API) | Same keys, always withheld (`—` / None + `cf_unavailable_reason`) |
| `/api/state` index / constituent payload | `server.py` (`ms_dict["spy_chg_pct"]` … `ms_dict["iwm_sectors"]`) | `spy_/qqq_/iwm_` last and chg, `constituents`, `qqq_constituents`, `iwm_holdings_constituents`, `iwm_sectors` | live screen (API) | Empty lists / None (no built-in roster) |
| `/api/state` bond | `server.py` (`ms_dict["bond_signal"]`) | `bond_signal` | live screen (API) | None (TNX yield still fetched; signal not guessed) |
| Console JS / HTML | `static/js/*.js`, `static/*.html` | no `cf_weighted_push` / `bond_signal` / constituent-dot consumer (F39 note) | live screen (none) | No screen deleted. Liquidity-map `confluence_score` is a different semantic (zone overlap), not this subsystem. |

## Persisted DB columns (schema kept; writers stop)

| Consumer | File | Columns | Class | After retirement |
|---|---|---|---|---|
| Snapshot persist | `server.py` (snapshot kwargs) | `spy_weighted_push`, `qqq_weighted_push`, `iwm_weighted_push` | persisted DB column | Stop writing; stay NULL |
| Snapshot persist | `server.py` | `spy_chg_pct`, `qqq_chg_pct`, `iwm_chg_pct`, `spy_spot`, `qqq_spot`, `iwm_spot`, `spy_zone`, `qqq_zone`, `iwm_zone`, `qqq_vs_spy`, `iwm_vs_spy` | persisted DB column | Stop writing; stay NULL |
| Snapshot persist | `server.py` | `nvda_chg_pct`, `aapl_chg_pct`, `msft_chg_pct`, `amzn_chg_pct`, `googl_chg_pct`, `goog_chg_pct`, `avgo_chg_pct`, `meta_chg_pct`, `tsla_chg_pct` | persisted DB column | Stop writing; stay NULL |
| Snapshot persist | `server.py` | `kre_chg_pct`, `xbi_chg_pct`, `psci_chg_pct`, `xrt_chg_pct` | persisted DB column | Stop writing; stay NULL |
| Snapshot persist | `server.py` | `bond_signal` | persisted DB column | Stop writing; stay NULL. `tnx_yield` / `tnx_chg` still written when the TNX quote exists. |
| Snapshot persist | `server.py` | `iwm_risk_regime`, `iwm_risk_score`, `spy_iwm_divergence`, `spy_iwm_fragile`, `iwm_early_warning`, `rotation_signal`, `index_*`, `spy_holdings_*`, `sector_*` (when fed only by the retired roster) | persisted DB column | Inputs absent → `compute_iwm_confluence` / `compute_sector_strength` return unavailable / empty; columns stay NULL |
| Snapshot dataclass / schema | `db.py` | same column names on `SnapshotRow` and `CREATE TABLE` | persisted DB column | Schema unchanged. No drop. No migration. |
| Thin tick store | `db.py` `confluence_quote_ticks` | ticker/last/chg rows for the retired roster | persisted DB column | Stop inserting constituent/index-roster rows. Table kept. VIX (and TNX when quoted) may still land here. |
| Ops backfill (T-15) | `backfill_snapshot_derived.py` `backfill_weighted_pushes` | fills NULL `*_weighted_push` from constituent chg with no age limit | persisted DB column | Stops filling. Does not rewrite historical values. |

## ML features (contracts unchanged)

Listed features remain in `feature_contracts.py`, `lstm_data.py`, `ml_train.py`,
and `arch_competition/*`. The model stack is off. New snapshots leave them NULL.

| Feature | Listed in | Class |
|---|---|---|
| `spy_weighted_push` | `feature_contracts.py`, `lstm_data.py`, `ml_train.py`, `arch_competition/encoder_lineage_v2.py`, `governed_stack_contract.py` fusion overlay, `audit_model_readiness.py` | dormant: absent until retrained |
| `qqq_weighted_push` | same | dormant: absent until retrained |
| `iwm_weighted_push` | same | dormant: absent until retrained |
| `spy_chg_pct` | `feature_contracts.py`, `lstm_data.py`, `ml_train.py`, fusion overlay | dormant: absent until retrained |
| `qqq_chg_pct` | same | dormant: absent until retrained |
| `iwm_chg_pct` | same | dormant: absent until retrained |
| `nvda_chg_pct`, `aapl_chg_pct`, `msft_chg_pct`, `amzn_chg_pct`, `googl_chg_pct`, `avgo_chg_pct`, `meta_chg_pct`, `tsla_chg_pct` | `ml_train.py`, `lstm_data.py` / feature contracts (mega-cap chg set) | dormant: absent until retrained |
| `kre_chg_pct`, `xbi_chg_pct`, `psci_chg_pct`, `xrt_chg_pct` | `ml_train.py`, feature contracts | dormant: absent until retrained |
| `bond_signal` | `similarity_feature_search.py` (categorical search list) | dormant: absent until retrained |
| `qqq_vs_spy`, `spy_iwm_divergence`, `iwm_risk_signal` | training / fusion overlay lists | dormant: absent until retrained |

`SignalInput` fields (`signal_types.py`) and `prediction_engine.py` payload keys
keep the same names; they receive None. That is not a contract change.

Guest-anchor routing in `governed_stack_contract.py` stops importing
`IWM_TOP_HOLDINGS` (the retired roster). Feature contracts are not edited.

## Call / snapshot plumbing that only *reads* the retired outputs

| Consumer | File | Class | After retirement |
|---|---|---|---|
| SignalInput stamp | `market_state.py` | live/persist path | Reads None; no second producer |
| IWM blend call | `market_state.py` `iwm_blended_participation_push` | live/persist path | Function remains as a None stub so the import does not invent a value |
| Sector / index strength | `server.py` + `math_probabilities.compute_sector_strength` | persist path | Empty input maps |
| IWM deep confluence | `math_probabilities.compute_iwm_confluence` | persist path | Already returns unavailable when spy/qqq/iwm chg are all None |
| Forced refresh / impute | `server.py` `_ensure_mkt_ctx_confluence_complete` | writer | Becomes a no-op (must not refresh-to-fill) |
| Panel-auto enrollment | `market_context_panel_symbols_excluding_core` → `server.py` logging universe | collection roster | Shrinks to `$VIX` only. `$TNX` stays unenrolled (no options chain). |
| Scheduler comments | `scheduler_user_tickers.py` | dead copy | No roster table to enroll |

## Fallbacks retired (T-08..T-15)

| ID | Producer | Class |
|---|---|---|
| T-08 | `bond_signal` guessed when VIX missing | deleted (signal never set) |
| T-09 | `extract_pct_change` ladder `netPercentChange` → regular → derived | deleted; only `quotes.quote.netPercentChange` |
| T-10 | `resolve_chg_pct` REST when stream missing | deleted; stream or None |
| T-11 | `_last_traded_price` `lastPrice` → `extended.lastPrice` | deleted; only `quotes.quote.lastPrice` (VIX included) |
| T-12 | weighted push rescaled when < half the weight reports | deleted with the push math |
| T-13 | IWM blend: one side stands in | deleted |
| T-14 | hardcoded `SPY_TOP` / `QQQ_TOP` / `IWM_TOP_HOLDINGS` / `IWM_SECTORS` | deleted |
| T-15 | `backfill_weighted_pushes` %-change with no age limit | fill path stopped |

VIX remains: fetched and used for the vol regime. Its last price is
`quotes.quote.lastPrice` only.

## Dead / test-only (rewritten to pin absence)

| Consumer | File | Class |
|---|---|---|
| Producer lock | `tests/test_f39_confluence_missingness.py` | dead (pins retired producers) |
| Weighted-push parity + backfill | `tests/test_scheduler_user_tickers_and_confluence_misc.py` | dead |
| Panel-auto NVDA/WMT from tables | `tests/test_issue22_logging_universe.py` | dead (roster gone) |
| REST/extended fallbacks | `tests/test_watchlist_chg_pct_universality_v1.py`, `tests/test_market_context_spot_semantics_v1.py` | rewritten: absent, not substituted |
| Historical UI transport dumps | `reports/ui_transport/*.json` | historical artifact (not a live producer) |

## Out of scope (same English word, different semantic)

| Name | Why it is not this subsystem |
|---|---|
| `lstm_data.compute_confluence_features` / `ml_data_common.confluence_features_for_bar` | Clock-window ML features, not fund-weight pushes |
| Liquidity-map `confluence_score` | Zone-overlap count from `/api/liquidity-snapshot` |
| Dropped `confluence_log` table | Already removed; tests in `test_confluence_log_drop.py` |
