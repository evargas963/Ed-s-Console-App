# Fallback register (operator rule 2026-09-23: NO FALLBACKS)

A value comes from its canonical Schwab field or its ONE canonical derived computation. When
that is missing, stale or invalid the value is ABSENT (shown absent / decision withheld with a
named reason). Substituting anything else — a default number or label, an older value, another
source, a guessed weight, `x or <default>`, re-weighting the legs that happen to exist — is a
violation, labelled or not.

Status: OPEN | FIXED `<sha>` | DORMANT (code path off today: fix before it is switched on).
Scope of this register: the 2026-09-24 re-audit (six read-only audits, every line of the named
files). The 2026-09-23 first-pass audit (653 sites, 16 P0 [UNVERIFIED]: audit report not committed) is tracked by its P0s below; its
P1/P2 rows are to be merged here as each file is repaired.

## First-pass P0s (2026-09-23)

| ID | What | Status |
|---|---|---|
| P0-01 | resolve_spot served REST / stale stream spot | FIXED 65ced8bd |
| P0-02 | replay stamped old rows "now" | FIXED 270a6213 |
| P0-03 | gamma heatmap last-valid refill shown as current | FIXED 253607bf |
| P0-04 | similar-setups tier labels (tier 5 "zone + VWAP") | FIXED 7d76e095 |
| P0-05 | confluence %-change imputed with no age limit | FIXED 7d76e095 |
| P0-06..09 | JS Number(null) -> "spot 0.00" on 4 screens | FIXED 96aa1bea |
| P0-10..11 | exposure page client-computed money | FIXED 7d76e095 |
| P0-12 | dex_magnitude always "negligible" | FIXED aa2b96cf |
| P0-13 | call_engine stop VIX/clock fallback | FIXED 53db9c34 |
| P0-14 | hand-typed event calendar | FIXED 1cb7dace |
| P0-15..16 | (first-pass ML/decision reports not recoverable; superseded by the re-audit below) | see below |

## Re-audit P0s — live paths (2026-09-24)

### The Call and its inputs (call_engine.py, signals.py, prediction_engine.py, lifecycle_rule_core.py)
| ID | file:line | Violation | Flows to | Status |
|---|---|---|---|---|
| C-01 | signals.py:146-197 | non-tradable canonical becomes a "flat / low / 1/3 each" forecast | persisted prediction_direction / pred_confidence every tick; readiness | FIXED 739fb9fc |
| C-02 | call_engine.py:564 | unknown event risk took the default threshold | stack threshold | FIXED 51a6def0 |
| C-03 | call_engine.py:178-181 | readiness uses "flat", 0.0 for a withheld forecast | The Call readiness | FIXED 739fb9fc |
| C-04 | call_engine.py:1874-1876, 1921-1923 | missing level distance -> "far" | readiness | FIXED 739fb9fc |
| C-05 | call_engine.py:1892-1901, 1939-1948 | readiness defaults 0 / "WAIT" / "dormant", except -> 0 | readiness | FIXED 739fb9fc |
| C-06 | call_engine.py:1916-1920 | put resistance falls back to support below | put readiness | FIXED 739fb9fc |
| C-07 | call_engine.py:1880, 1927 | readiness trend: rules.zone_label -> MVP zone | readiness | FIXED 739fb9fc |
| C-08 | call_engine.py:408-410 | unhandled WAIT reasons print "insufficient confirmation" (incl. no_measured_stop) | The Call headline | FIXED 2066e680 |
| C-09 | signals.py:330 | calibration timeframe `or "1m"` defeats the writer's refusal | calibration row (env-gated) | FIXED 2066e680 |
| F-09 | prediction_engine.py:436-446 | 15m/60m "structure approximation" text | readiness | FIXED a7b8aefc |
| F-10 | prediction_engine.py:420, 445-446 | missing charm -> "No clear trend — range" | readiness | FIXED a7b8aefc |
| S-14 | lifecycle_rule_core.py:203-208 | T1 = 2R fallback (also overrides the similar-setups avg5 when it is <= 1.5R) | The Call target | FIXED c36102ec |
| S-15 | lifecycle_rule_core.py:220-228 | T2 falls to avg60, then T1 + 1R | The Call target2 | FIXED c36102ec |
| S-16 | lifecycle_rule_core.py:237-240 | T2 <= T1 replaced by T1 + 1R | The Call target2 | FIXED c36102ec |

### Fusion / model labels persisted as data (bayesian_fusion.py, ml_predict.py, market_state.py)
| ID | file:line | Violation | Flows to | Status |
|---|---|---|---|---|
| F-01 | bayesian_fusion.py:789-796 | fuse returns available=True with 0 active sources | persisted fusion_* columns every tick | FIXED 693ffaa8 |
| F-02 | bayesian_fusion.py:182-189 | DEFAULT_PRIORS when regime missing | fusion_* | DORMANT since 693ffaa8 (runs only when a model contributes evidence; model stack off, #262). F-03 needs likelihoods estimated from labeled outcomes before re-enable |
| F-03 | bayesian_fusion.py:331-355 | "placeholder likelihoods" rules tables are the only evidence | fusion_* | DORMANT since 693ffaa8 (runs only when a model contributes evidence; model stack off, #262). F-03 needs likelihoods estimated from labeled outcomes before re-enable |
| F-04/05 | bayesian_fusion.py:333-336, 378, 508 | getattr(rules, "signal"/"conviction", default) | fusion_* | FIXED 693ffaa8 |
| F-06 | bayesian_fusion.py:620-621 | CALIBRATION_PENALTY placeholder | fusion_confidence | DORMANT since 693ffaa8 (runs only when a model contributes evidence; model stack off, #262). F-03 needs likelihoods estimated from labeled outcomes before re-enable |
| F-07/08 | bayesian_fusion.py:421, 427-429 | likelihood floor; "fallback to priors" | posteriors | DORMANT since 693ffaa8 (runs only when a model contributes evidence; model stack off, #262). F-03 needs likelihoods estimated from labeled outcomes before re-enable |
| L-01 | ml_predict.py:2853-2862 | model_version built from files on disk, not what ran | persisted pred_model_version | FIXED 425aa436 |
| F-11 | prediction_engine.py:923; server.py:8549 | `or "rules_v1"` | persisted pred_model_version | FIXED 425aa436 |
| S-01..03 | market_state.py:1707, 1719, 431, 446 | placeholder direction/confidence and fusion defaults persisted | snapshots | FIXED 739fb9fc |
| S-04 | market_state.py:359-422 | "low"/"rules_v1"/0.0 defaults persisted when signals fail | snapshots | FIXED 739fb9fc |
| L-02 | governed_stack_contract.py:229-254 | non-SPY/QQQ/IWM routed to an "SPY anchor" (+ The Call wait_reason) | The Call label | FIXED: guest-anchor route deleted; a ticker serves its own bundle or no model (branch fix/l02-no-guest-anchor) |

### Exposure math (math_exposure_core.py, math_levels.py)
| ID | file:line | Violation | Flows to | Status |
|---|---|---|---|---|
| M-01 | math_exposure_core.py:1037-1044 | net_delta: raw-unit switch on a gamma test; no valid delta -> 0.0 | The Call regime vote (0.0 votes LONG), zone, snapshots | FIXED b6c16570 |
| M-02 | math_exposure_core.py:1014-1022 | net GEX: raw fallback; no valid gamma -> 0.0 | kl_net_gex "$0", regime, snapshots | FIXED b6c16570 |
| M-03 | math_levels.py:139-145, 232 | inflection picks empty 0.0 buckets; all-strikes fallback | snapshots, SignalInput | FIXED b6c16570 |
| M-04 | math_levels.py:153-178 | pin_strength "Very Low" for absence | bias, zone | FIXED b6c16570 |
| M-05 | math_levels.py:190-224 | bias "Neutral"/"Chaos Zone" from absence | persisted zone, matching | FIXED b6c16570 |
| M-06 | math_levels.py:100-110, 497-506; server.py `_bucket_total_oi` | one-sided-OI strikes dropped from PCR / OI totals; DPI total OI counts a missing leg as 0 (bucket cannot yet tell "no contract listed" from "field missing" -- fix at the producer) | klPcr screen, Greeks vote | FIXED 65b45a7f |
| M-07 | math_levels.py:115-127 | oi_center skips one-sided strikes | snapshots | FIXED 65b45a7f |
| M-08 | math_levels.py:1439-1447 | max pain excludes one-sided strikes | Trade Desk screen | FIXED 65b45a7f |
| M-09 | math_levels.py:527-539 | ATM IV = one leg when the other is missing | IV direction, EM, IV rank | FIXED 65b45a7f |
| M-10 | math_levels.py:812-855 | gamma profile silently drops contracts; no counts | flip, regime | OPEN |
| M-11 | math_levels.py:1562-1575 | void zones drop the OI test with no OI | breakout score | FIXED 65b45a7f |
| S-05 | market_state.py:1319-1323 | iv_level: chain ATM IV stands in for straddle IV | vol regime -> The Call | FIXED 541ac2f9 |

### Terrain and market context (terrain_engine.py, terrain_read.py, market_context.py)
| ID | file:line | Violation | Flows to | Status |
|---|---|---|---|---|
| T-01 | terrain_engine.py:283-284 | per-strike GEX bar falls back to unsigned raw gamma | GEX-by-strike screen | FIXED 65b45a7f |
| T-02 | terrain_engine.py:259, 293 | missing strike volume shown as 0 | same panel | FIXED 65b45a7f |
| T-03 | terrain_engine.py:703-705 | key-level universe falls back to all strikes | walls, posture | FIXED 65b45a7f |
| T-04 | terrain_engine.py:723-743 | book OI: missing leg = 0; except -> silently skipped | pin gate, PIN SCORE | FIXED 65b45a7f |
| T-05 | terrain_engine.py:332 | wall range from raw gamma, still labelled "GEX mass" | chart | FIXED 65b45a7f |
| T-06 | terrain_engine.py:415-417 | implied move from one leg's IV | EM band, banked IV | FIXED 65b45a7f |
| T-07 | terrain_read.py:108-109 | regime from spot-vs-flip when gamma_at_spot == 0 | posture (edge case) | FIXED fa56b1dd |
| T-08 | market_context.py:753-755 | bond_signal guessed when VIX missing | snapshots | FIXED 3cc34f89 |
| T-09 | market_context.py:311-321 | %-change ladder: netPercentChange -> regular -> derived | confluence, snapshots | FIXED 3cc34f89 |
| T-10 | market_context.py:650-657 | resolve_chg_pct: REST when stream missing | fast-quote, context plane | FIXED 3cc34f89 |
| T-11 | market_context.py:288 | lastPrice -> extended.lastPrice | VIX, constituents | FIXED 3cc34f89 |
| T-12 | market_context.py:365, 412, 494 | weighted push rescaled when < half the weight reports | cf_weighted_push, snapshots | FIXED 3cc34f89 |
| T-13 | market_context.py:557-599 | IWM blend: one side alone stands in | snapshots | FIXED 3cc34f89 |
| T-14 | market_context.py:54-108 | hardcoded fund weights ("as of Feb 2026") | every weighted push | FIXED 3cc34f89 |
| T-15 | market_context.py:524-542 | backfill: tick %-change with no age limit | training rows (ops job) | FIXED 3cc34f89 |

### Other persisted scores (math_probabilities.py)
| ID | file:line | Violation | Flows to | Status |
|---|---|---|---|---|
| S-06 | math_probabilities.py:1422-1433 | flow imbalance falls back to call/put volume ratio | snapshots, SignalInput | FIXED b5c5aeff |
| S-07 | math_probabilities.py:1525-1550 | smart-money: missing legs = 0 | snapshots | FIXED b5c5aeff |
| S-08..10 | math_probabilities.py:658-668, 769-779, 830-840 | breakout / vol-expansion / sweep: missing component = 0 | snapshots | FIXED b6c16570 |
| S-11 | math_probabilities.py:545-557 | hedging flow re-weights present legs | snapshots | FIXED b6c16570 |
| S-12 | math_probabilities.py:1085-1123 | IWM confluence: missing legs neutral | snapshots | FIXED: compute_iwm_confluence and sector strength deleted with the retired roster (branch fix/retire-index-confluence-audited) |
| S-13 | math_probabilities.py:221-234 | option-expression score: missing inputs add 0 -> rec_strike | The Call contract | OPEN |

### Found while repairing (2026-09-24)
| ID | file:line | Violation | Flows to | Status |
|---|---|---|---|---|
| N-01 | calibration/edge_validation.py `_effective_directional_signal` | stored 1/3-each placeholder triplets won the p_up >= p_dn >= p_fl tie-break and were scored as LONG calls -- every edge study over rows logged while fusion was off counted them | calibration edge / discovery / engineering reports | FIXED 739fb9fc (reader requires tradable provenance; any edge report produced from those rows before this is invalid) |
| N-02 | prediction_engine.py `_empty_prediction` | no-database path seeds every horizon with a 1/3-each product triplet | PredictiveCard up/down/flat per horizon (no-DB only) | OPEN |
| N-03 | calibration/analyze_phase3.py `_confidence_bucket`; calibration/signal_engineering.py `final_signal or "wait"` | unknown confidence label bucketed as "low"; missing final signal counted as "wait" | offline calibration reports | OPEN |
| N-04 | db.py compute_accuracy | RTH scope read a NULL et_minute as :00; "statistical_v1" default version matched zero rows | accuracy surfaces | FIXED 425aa436 |
| N-05 | v2_decision/a2_lifecycle_sidecar.py | second stop/target producer: VIX/clock stop, VWAP-snapped targets, 2R/T1+1R fallbacks disagreeing with The Call | A2 lifecycle preview (advisory, training rows) | FIXED c36102ec (carries The Call's plan) |
| N-06 | call_engine.py `_vol_risk_mult`; lifecycle_rule_core.apply_risk_multiplier | vol-regime risk multiplier `or 1.0`; NaN multiplier -> 1.0 | The Call stop distance | OPEN |
| N-07 | terrain_engine.py compute_terrain | max pain computed over ALL expiries pooled (standard definition is per expiry) | Trade Desk max pain | FIXED 65b45a7f (front expiry, max_pain_dte) |
| N-08 | server.py /api/fast-quote REST writer; live_market_plane.record_quote; ingest LAST_PRICE carry | REST quotes written into the live plane (replacing stream rows), auth-failure stale carry-forward, REST row restamped as streamed | spot / header / tools | FIXED d944aabf |
| N-09 | server.py _fetch_state spread + volume | cached-spread label; 4-source volume chain into bar volume | snapshots, candles | FIXED d944aabf |
| N-10 | server.py _fetch_state | bid/ask/sizes/mark from a per-cycle REST quote while spot is streamed -- two sources and two instants in one persisted row | snapshots, The Call inputs | FIXED e7361e68 |
| N-11 | server.py _fetch_state expiry select | a requested past expiry is replaced by the default expiry ("using default") instead of refused | state payload | FIXED b5c5aeff |
| N-12 | app/options/order_flow/engine.py, state.py, history.py | order-flow fallbacks: REST quote/extended/regular/underlying + book-top stand-ins for L1 bid/ask/size/mark; rvol 4 current + 5 average sources incl. a candle-average baseline; institutional proxy averaging whichever of 4 legs existed; _weighted_mean_present weight renormalisation; options flow first-contract-only per strike, partial volume/delta sums, put_vol+1e-9; VOLUME for TOTAL_VOLUME; CHANGE_PERCENT (never sent) for change %; ts_recv "now" stamp; tape receipts on the console clock; raw-symbol key; invented 1s span | order-flow payload, snapshots | FIXED e7361e68 |
| N-13 | server.py _fetch_state | REST Cum Delta "tape" from one polled quote per cycle; candle volume from REST price history (nearest-in-time candle, ms-vs-s magnitude guess, $-stripped retry); plane_quote_authority "rest_*" labels and exception -> "rest_only" | snapshots, cum delta, diagnostics | FIXED e7361e68 |
| N-14 | live_market_plane vs app/options/order_flow/state | two stores hold the same streamed L1 fields (plane per-field state; order-flow `_top` with its own 25s field freshness) -- not a fallback, a duplicate store that can disagree | order-flow engine vs header | OPEN |

### v2 decision (advisory; persisted training rows only)
| ID | file:line | Violation | Status |
|---|---|---|---|
| V-01 | v2_decision/module_a_adapter.py:186-190 | direction `or prediction_dir or final_bias` | OPEN |
| V-02 | v2_decision/module_a_adapter.py:196, 81 | unknown -> "neutral" -> WAIT stored as a value | OPEN |

## Dormant (ML stack / Monte Carlo off) — fix before enabling
ml_predict feature imputation and nan_to_num (L-03..09), Monte Carlo sigma/drift/tail
fallbacks (F-12..20), mc_fusion_adjustment reverts (F-20), the 5c SPY-only isotonic map
(L-14), live-unreachable Call sizing/conviction defaults (C-10..19). Full rows: the
2026-09-24 audit reports.

## Counts
Re-audit live P0 open: 8 rows above marked OPEN (several rows group more than one site) -- `grep -c "| OPEN |$" governance/fallback_register.md`.
P1 (re-audit): ~70 more [UNVERIFIED]: audit reports not committed; to be merged as files are repaired.
