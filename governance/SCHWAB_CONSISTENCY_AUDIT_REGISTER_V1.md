# Schwab Consistency Audit Register V1

**Status:** Draft closure register - not yet all-inclusive PASS  
**Date:** 2026-05-07  
**Scope:** Repo-wide Schwab field, symbol, persistence, consumer, and governance consistency audit baseline  
**Mode:** Read-only findings; no runtime fixes authorized by this document

This register makes the Schwab-consistency findings durable. It exists because A2 and adjacent runtime paths must not govern around internal data-flow loss when Schwab-native fields are available upstream.

This document is not yet a final all-inclusive PASS artifact. It is the governing baseline for repo-wide closure work. A finding is not considered closed until its owning track has explicit file inventory, tests or measurement evidence, and a disposition recorded here.

---

## Audit Standard

Canonical priority for Schwab-provided primitive market data:

```text
schwab_native_normalized > schwab_native_raw_fallback > governed_derived_fallback > unavailable_gate
```

Derived analytics remain allowed when Schwab does not provide the output directly, for example dealer exposure, gamma walls, breakeven math, model features, replay PnL policy, VWAP side, and liquidity scores. Those are not substitutes for Schwab-native primitive observations.

Source priority enforcement is governed by `ENGINEERING_GATEKEEPING_POLICY.md` §Schwab Same-or-Better Rule.

---

## Closure Status

| Track | Coverage status | Closure requirement |
|---|---|---|
| Schwab fetch paths | Partial inventory complete | Every quote, option-chain, price-history, streaming, and probe path must use an explicit broker-symbol policy. |
| Normalization boundary | Partial inventory complete | `chains.py`, quote parsing, bar parsing, and stream normalization must preserve Schwab-native primitives or mark them unavailable. |
| Option proof handoff | Blocking defect identified | `market_state` proof rows must preserve A2-required Schwab fields end-to-end. |
| Runtime consumers | Partial inventory complete | A2, market state, order flow, volatility, exposure, liquidity, and API/UI consumers must document native-vs-derived behavior. |
| Persistence/archive | Partial inventory complete | `snapshots.option_chain_json`, replay context, bars, calibration logs, and backfills must have source/shape guarantees. |
| DB authority and backups | Known incomplete | All write-capable scripts must use canonical DB authority and one backup/manifest convention or document an explicit exception. |
| Symbol identity | Known incomplete | `$SPX`, `$VIX`, `$NDX`, storage keys, fetch symbols, migrations, reporting, and backfills must be aligned. |
| Source labeling | Known incomplete | Critical trader-facing and decision-facing fields must carry source/provenance outside v2 leaves where needed. |
| Governance contracts | Partial inventory complete | Binding contracts must match empirical behavior and must not authorize workarounds for internal data loss. |
| Tests and measurement | Incomplete | Each track needs regression tests, live/archive measurement, or static enforcement before PASS. |

This table is intentionally strict. Anything marked partial or incomplete remains open repo-wide work.

---

## Required File-Family Inventory For PASS

Before this register can be upgraded from draft to closure PASS, these file families must be explicitly reviewed and either assigned a finding or marked no-issue with evidence:

| Family | Required coverage |
|---|---|
| Schwab clients/probes | `schwab_client.py`, `schwab_full_field_inventory.py`, `schwab_full_accessible_field_inventory.py`, `tools/schwab_minute_history_probe_v1.py`, auth/reauth tooling. |
| Runtime fetch and state | `server.py`, `market_context.py`, `live_market_plane.py`, `polling_adapter.py`, `market_data_adapter.py`. |
| Option chain normalization and replay | `chains.py`, `market_state.py`, `realized_contract_eval.py`, `v2_decision/a2_option_expression.py`, `v2_decision/a2_replay_labels.py`. |
| Option math and derived analytics | `math_exposure_core.py`, `math_exposure.py`, `math_probabilities.py`, `math_volatility.py`, `order_flow_engine.py`, `order_flow_live_state.py`, `order_flow_streaming.py`. |
| Persistence and DB authority | `db.py`, `db_authority.py`, `db_safety.py`, `snapshot_normalizer.py`, migration and repair scripts under `tools/`, calibration repair/backfill modules. |
| Historical ingestion/backfill | `bar_rehydration_issue19_v1.py`, `tools/historical_backfill_enrolled_1m_v1.py`, `tools/ingest_1m_to_staging.py`, Issue 19 repair/validation tools. |
| Calibration and training | `calibration/*.py`, `ml_train.py`, `train_all.py`, `lstm_data.py`, `ml_data_common.py`, feature adapters and training canonical input modules. |
| API/UI consumers | `static/index.html`, Tier C payload builders, UI contract tests, dashboard/ops surfaces. |
| Symbol identity and universe | `instrument_identity.py`, `production_universe.py`, scheduler/logging-universe enrollment, ticker readiness tools, `$` index tests. |
| Governance and docs | `governance/*.md`, `docs/SCHWAB_FIELD_REFERENCE.md`, `docs/FIELD_SOURCE_AUDIT.md`, `docs/SCHWAB_FIELD_NORMALIZATION_AUDIT.md`, DB authority docs. |
| Tests | Schwab normalization, A2 option expression, market-state proof, live plane, DB safety, migration, UI payload, and replay-label tests. |

---

## Closure Evidence Required Per Finding

Every finding promoted to a fix slice must include:

1. The exact producer path and consumer path.
2. The Schwab-native field or symbol involved.
3. Whether Schwab provides the primitive directly.
4. The current internal transformation or fallback.
5. The intended source priority after fix.
6. Tests proving the priority or fail-closed behavior.
7. Live/archive measurement when the issue involves feed availability.
8. Governance citation or explicit statement that no governance change is needed.

---

## Executive Findings

| ID | Finding | Severity | Blocking Track | Disposition |
|---|---|---:|---|---|
| SC-001 | `market_state` truncates selected option proof rows before A2 consumes them. | High | A2 Slice 2+ | Must fix before further A2 slice work. |
| SC-002 | Historical archive theta null/missing rate was caused by internal normalization/archive omission, not current Schwab API absence. | High | A2 theta governance | Do not authorize Black-Scholes as structural primary path. |
| SC-003 | Current live Schwab option-chain samples return theta/rho/quote timestamps for SPY and QQQ, and current `chains.contract_fields()` preserves them. | High | A2 proof-row fix | Use as post-fix expected behavior. |
| SC-004 | Index symbol handling is inconsistent for NDX and selected `$`-prefixed migration/reporting paths. | High | Infra data integrity | Separate symbol-policy fix track. |
| SC-005 | DB authority remains globally incomplete for auxiliary scripts and backup conventions. | Medium/High | Infra data integrity | Separate DB-authority closure track. |
| SC-006 | Source labeling remains uneven outside v2 leaf structures. | Medium | Infra provenance | Separate source-labeling audit/fix track. |
| SC-007 | Fallback-heavy quote/spread/spot/expiry paths can carry stale or semantically degraded values without enough field-level provenance. | High | Runtime data quality | Separate runtime provenance/gating track. |
| SC-008 | Mark-vs-mid and **`volatility`** fallback/recompute policy are under-specified in binding governance. | Medium/High | Governance | Contract/operator decision follow-up. |

---

## SC-001 - Market-State Proof Row Truncation

| Field | Value |
|---|---|
| Location | `market_state.py::_oe_chain_row_snapshot()` |
| Prior behavior (pre-2026-05-10 fix) | Emitted a narrow subset and non-canonical aliases; current `_oe_chain_row_snapshot()` emits **canonical leaves only** (no `expiration` / `volume` aliases) and an expanded A2-aligned key set per `A2_MARKET_STATE_PROOF_ROW_COMPLETENESS_CONTRACT.md`. |
| Missing Schwab-native fields needed by A2 | `theta`, `rho`, `vega`, `volatility`, `theoreticalVolatility`, `theoreticalOptionValue`, `quoteTimeInLong`, `tradeTimeInLong`, `mark`, `last`, `bidSize`, `askSize`, `bidAskSize`, `lastSize`, option OHLC, and contract metadata. |
| Impact | A2 can fall into Black-Scholes theta, `theta_unavailable`, missing quote timestamp, or weaker source labels even when normalized Schwab fields existed upstream. |
| Classification | Internal field elision / accidental contract mismatch. |
| Required next artifact | `A2_MARKET_STATE_PROOF_ROW_COMPLETENESS_CONTRACT.md`. |

This is the first blocking fix. It must be handled before more A2 0DTE slice work because A2 consumes the selected proof row.

---

## SC-002 - Historical Theta Missingness Was Internal

Archive evidence from `data/ed_console.db` on 2026-05-07:

| Population | Value |
|---|---:|
| SPY/QQQ archived contracts inspected | 989,120 |
| Contracts with `theta` key missing | 966,080 |
| Contracts with `theta` present-null | 0 |
| Contracts with numeric `theta` | 23,040 |
| Contracts with `raw.theta` value | 0 |

Recent archive split:

| Date | Result |
|---|---|
| 2026-05-06 to 2026-05-07 | Numeric `theta`, `rho`, and quote/trade timestamps are present in archived rows. |
| Prior historical rows | `theta` key is mostly missing entirely, not present-null. |

Interpretation:

```text
This is not evidence that Schwab omits 0DTE theta structurally.
It is evidence that earlier internal normalization/archive paths omitted the field.
```

Governance consequence:

```text
Do not bind an operator decision that treats Black-Scholes theta as the permanent primary path.
After the proof-row fix lands, re-measure live/post-fix archives before deciding whether BS remains as a residual governed fallback or is removed.
```

---

## SC-003 - Live Schwab Chain Evidence

Fresh live Schwab option-chain sample on 2026-05-07:

| Ticker | Raw contracts | Raw theta values | Raw rho values | Raw quote timestamps | Normalized theta values |
|---|---:|---:|---:|---:|---:|
| SPY | 1,440 | 1,440 | 1,440 | 1,440 | 1,440 |
| QQQ | 1,400 | 1,400 | 1,400 | 1,400 | 1,400 |

Current normalizer:

| Location | Status |
|---|---|
| `chains.contract_fields()` | Preserves `theta`, `rho`, `quoteTimeInLong`, `tradeTimeInLong`, implied-vol fields (**`volatility`**, `theoreticalVolatility`, …), prices, sizes, and metadata when present. |
| `realized_contract_eval.serialize_option_chain_for_eval()` | Uses `contract_fields()` and strips only `raw`, preserving normalized Schwab fields. |

---

## SC-004 - Index Symbol Canonicalization

| Location | Finding | Severity | Follow-up |
|---|---|---:|---|
| `instrument_identity.py` | `SPX` and `VIX` map to `$SPX`/`$VIX`; NDX parity is missing. | High | Decide and enforce NDX canonical storage/fetch policy. |
| `db.py` logging-universe migration/import paths | Some `$`-prefixed tickers are filtered out. | High | Make migration/import paths canonical-key aware. |
| `server.py` price-history fallback | One path retries `ticker[1:]` for `$` tickers; other fetch paths do not share a central policy. | Medium | Centralize broker fetch symbol translation. |
| Backfill/rehydration tools | Some fetch using DB ticker directly. | Medium | Add shared DB-key to Schwab-symbol translation and telemetry. |
| `realized_contract_eval.py` | Replay coverage reporting skips `$` tickers. | Low/Medium | Include canonical index symbols or explicitly justify exclusion. |

---

## SC-005 - DB Authority And Backup Consistency

| Location | Finding | Severity | Follow-up |
|---|---|---:|---|
| `docs/db_authority_enforcement_final.md` | Global DB authority status is already documented as FAIL for strict closure. | High | Continue DB authority closure track. |
| Auxiliary scripts | Many scripts still open `data/ed_console.db` literally or bypass `DB_PATH`/guards. | Medium/High | Migrate high-risk write/read paths first. |
| Backup APIs | Split conventions exist, including `data/backups/...` and `backups/db/...`. | Medium | Standardize on one backup API and manifest format. |
| Schema repair tooling | Strong O-38 explicit-DDL policy exists, but drift detection/post-migration audit remains open. | Medium | Add recurring schema-drift check contract. |

---

## SC-006 - Source Labeling Outside V2 Leaves

| Surface | Current State | Risk | Follow-up |
|---|---|---:|---|
| `v2_decision` leaves | Strong source indicator structure exists. | Low/Medium | Expand market-data leaves to distinguish Schwab-native vs approximation consistently. |
| `chains.py` normalization | Preserves fields but has no per-field source-classification tags. | Medium | Add source-classification digest or tags. |
| `server.py` API payloads | Some source/update tags exist, not field-level. | Medium | Add field-level provenance for critical primitives. |
| ML/training features | Envelope-level provenance exists; missingness may become numeric defaults. | Medium | Persist source/missingness masks with artifacts. |
| Calibration logs | Snapshot-level provenance exists; primitive-field lineage is limited. | Medium | Add compact field-source digest for key primitives. |
| UI | v2 source suffixes exist; non-v2 display values can show placeholders without durable cause. | Low/Medium | Add missing/stale/policy reason chips where trader-facing. |

This track does not block the proof-row fix, but it is part of the same institutional standard.

---

## SC-007 - Runtime Fallback Hotspots

| Location | Fallback | Severity | Follow-up |
|---|---|---:|---|
| `live_market_plane.py` | `spot` falls through `LAST_PRICE -> MARK -> prior spot -> bid/ask midpoint`; bid/ask may carry forward. | High | Add freshness TTL and per-field provenance. |
| `server.py` | Spread may fall back to cached prior spread. | High | Bound cache age and gate spread-dependent decisions if stale-derived. |
| `server.py` | Expiry filtering can fall back to unfiltered contracts if selected-expiry filter is empty. | High | Fail closed instead of using unfiltered contracts. |
| `math_probabilities.py` | Flow imbalance can compare book-derived and volume-derived paths as if equivalent. | High | Persist fallback source and prevent equivalence assumptions. |
| `market_context.py` | Index change percent can be direct or derived. | Medium | Emit field-level provenance for direct vs derived changes. |
| `snapshot_normalizer.py` | Recomputes 1m OHLCV from snapshot buckets and spot fallback. | Medium | Tag rows as normalized-from-snapshots vs exchange bars. |

---

## SC-008 - Governance Gaps

| Gap | Current State | Required Governance |
|---|---|---|
| Black-Scholes theta | Contract permits fallback, but live evidence says Schwab theta is currently available and historical missingness was internal. | Revisit only after proof-row fix and post-fix measurement. |
| Raw-theta bridge | Code/test behavior exists but prose is incomplete. | Contract source order if still needed: normalized theta > raw theta > governed fallback > WAIT. |
| **`volatility`** fallback/recompute | A2 contract says use `volatility` when present, but synthetic **`volatility`** fallback is not explicitly forbidden/authorized. | Add explicit A2 **`volatility`** source policy. |
| Mark vs midpoint | Audit guidance exists; binding precedence is incomplete. | Add per-field price precedence matrix. |
| Policy object status | O-20/O-21 are bound, but some status labels can lag as pending. | Require source/status transition once operator decision exists. |

---

## Open Repo-Wide Inventory Backlog

These are not yet closed by this register. They must be expanded into findings, exceptions, or no-issue evidence before the repo-wide effort can be called complete.

| Backlog ID | Area | Current concern | Required next step |
|---|---|---|---|
| SBI-001 | All Schwab fetch wrappers and direct calls | Some direct `client.get_*` calls bypass central policy. | Inventory every direct Schwab call and require wrapper or documented exception. |
| SBI-002 | Streaming vs REST field parity | Streaming fields (`LAST_PRICE`, `MARK`, `BID_PRICE`, `ASK_PRICE`, `TOTAL_VOLUME`) and REST quote fields may not have identical provenance. | Add stream/REST field equivalence matrix and fallback policy. |
| SBI-003 | Option-chain query parameters | Field availability could vary by endpoint/query params. | Record current chain request shape and required fields; test SPY/QQQ 0DTE sample. |
| SBI-004 | `market_state` proof row | Blocking truncation already identified. | Implement contract in `A2_MARKET_STATE_PROOF_ROW_COMPLETENESS_CONTRACT.md`. |
| SBI-005 | A2 leaf source labels | Some Schwab-native fields are still labeled as `v1_approximation`. | After proof-row fix, relabel only fields proven Schwab-native through the handoff. |
| SBI-006 | Black-Scholes theta | Fallback exists, but current evidence suggests it should not be primary. | Re-measure after proof-row fix; then decide remove/quarantine/narrow-govern. |
| SBI-007 | **`volatility`** source policy | Synthetic **`volatility`** fallback is not clearly forbidden or authorized for A2. | Add binding **`volatility`** source policy. |
| SBI-008 | Mark vs mid | `mark`, `mid`, spread, breakeven, and broker mark semantics are not globally bound. | Add price-field precedence matrix. |
| SBI-009 | Spot/bid/ask carry-forward | Live plane may carry stale values forward. | Add TTL/provenance and gate stale-derived decision inputs. |
| SBI-010 | Expiry filter fallback | `server.py` can use unfiltered contracts when selected-expiry filter is empty. | Fail closed and test selected-expiry contract isolation. |
| SBI-011 | Flow and order-book fallbacks | Book-derived and volume-derived values can flow as comparable metrics. | Add source tiering and downstream gating. |
| SBI-012 | Index symbol policy | NDX parity and `$` migration/reporting behavior are incomplete. | Create symbol policy slice covering storage/fetch/reporting/backfill. |
| SBI-013 | DB authority | Auxiliary scripts and tools still have literal DB paths or inconsistent guards. | Continue DB authority closure with write-capable scripts first. |
| SBI-014 | Backup convention | Multiple backup paths and manifest formats exist. | Standardize backup API/path/manifest or document exceptions. |
| SBI-015 | Calibration primitive provenance | Calibration rows lack compact Schwab primitive source digests. | Design minimal source digest for critical fields. |
| SBI-016 | Training missingness/source masks | Model feature defaults can hide feed-quality changes. | Persist missingness/source masks in training artifacts. |
| SBI-017 | UI missing-state clarity | Some placeholders hide missing vs stale vs policy-gated states. | Add reason chips for critical trader-facing fields. |
| SBI-018 | Docs drift | Schwab reference docs can lag normalization implementation. | Add doc/implementation parity test or release checklist. |
| SBI-019 | Historical archives | Old `option_chain_json` rows lack fields now preserved. | Decide no-backfill vs annotated historical limitation; do not silently mix with post-fix rows. |
| SBI-020 | Tests from production path | Some tests use rich synthetic rows and miss production proof truncation. | Add integration tests through actual producer-to-consumer paths. |

---

## Explicit Non-Closure Statement

This register is currently a control document, not proof of completion.

```text
repo_wide_schwab_consistency_status = OPEN
blocking_fix = market_state proof-row field preservation
next_required_artifact = implementation slice with tests
```

No future A2 0DTE slice should claim Schwab-field consistency until the relevant entries above are closed or explicitly deferred with operator approval.

---

## Blocking Sequence

1. Approve this register as the current open closure baseline.
2. Approve the market-state proof-row completeness contract.
3. Implement the proof-row fix in a bounded slice.
4. Add tests proving Schwab theta and quote timestamps survive from normalized selected contract to A2 input.
5. Re-measure post-fix archive/live theta availability.
6. Decide whether Black-Scholes remains as a narrow governed residual fallback or is removed from the A2 path.
7. Resume A2 Slice 2 correction and later slice work only after the upstream proof-row fix path is accepted.

