# Fallback register

Operator rules 2, 3, 4 and 5 (AGENTS.md). One row per site found. Status: OPEN (found, not yet
checked against the code) | FIXED `<sha>` | NOT A VIOLATION (checked; reason).

Audit 2026-09-27: every line of the product code (33,581 lines: every `.py`, `.js` and `.html`
outside tests/, tools/, governance/, research/, scripts/, reports/, docs/ and static/vendor/), read
in full in six parts. Earlier registers (2026-09-23 first pass, 2026-09-24 re-audit) are closed:
their rows named code since deleted (a324e70d, 2f23ff9a) or were fixed (cd9e0cb9); git holds them.
Their L1 duplicate (N-14) is O-01 below.

Columns: file:line | rule | value | what the code does | who sees it.

## S — server.py

| ID | file:line | rule | value | what it does | seen by | status |
|---|---|---|---|---|---|---|
| S-01 | server.py:570 | 3 | ticker key | second normalizer after ticker_storage_key: `or (ticker or "").upper().strip()` | every route via resolve_spot | FIXED 7b64cae6 |
| S-02 | server.py:1073 | 2 | CHART_EQUITY bar_start_ms | read raw, not schwab_number | stored price_bars_1m | OPEN |
| S-03 | server.py:1209-1211 | 5 | logger roster | filter failure keeps the unfiltered roster | terrain board | OPEN |
| S-04 | server.py:1264, 4250, 4293, 4469, 4509, 4518, 5176 | 3 | ticker key | `.upper().strip()` instead of ticker_storage_key; "SPX" misses "$SPX" (SSE scope, watchlist, last_seen) | L1 SSE push, watchlist, order flow | FIXED 7b64cae6 (watchlist route: NOT A VIOLATION, price_row keys through ticker_storage_key) |
| S-05 | server.py:1634 | 3 | level_name | read-time relabel of the stored name | /api/desk/events | OPEN |
| S-06 | server.py:1890 | 5 | flip-drift ts | `computed_ts_utc or time.time()` | stored flip_drift_log | FIXED 317093a8 |
| S-07 | server.py:1942 | 3 | token age | hard-coded token path, not cfg.token_path | every terrain_staleness payload | FIXED 7b64cae6 |
| S-08 | server.py:1991-1997 | 5 | levels_stale | market closed + any snapshot of any age -> not stale | /api/terrain, surface, strikes | OPEN |
| S-09 | server.py:2016 | 5 | stale threshold | missing cycle time replaced by TERRAIN_REFRESH_SEC | levels_stale | OPEN |
| S-10 | server.py:2578 | 5 | stream_coverage live_pct | no relevant cells -> 0.0 | gamma-surface | OPEN |
| S-11 | server.py:2636-2659 | 3/5 | chain_basis, DTE clock, crosses | stored capture repriced with today's clock and relabelled; its past spot seeds level crosses | levels, heatmap, level_crosses | OPEN |
| S-12 | server.py:2666, 4980 | 2 | spot | truthiness treats 0 as missing | heatmap, /api/levels | FIXED 317093a8 at the heatmap; /api/levels divides by spot (a guard, not a substitute) |
| S-13 | server.py:2737 | 5 | option->ticker | first match wins | reprice routing | OPEN |
| S-14 | server.py:2824 | 5 | chain as-of | local time after the fetch | computed_ts_utc | OPEN |
| S-15 | server.py:2830-2831 | 2 | atr_daily/atr_15m | 0 read as missing | /api/terrain | FIXED 317093a8 |
| S-16 | server.py:2841 | 2 | iv_pct_atm | IV 0 rejected | stored iv_daily | FIXED 317093a8 (writer deleted: nothing reads iv_daily) |
| S-17 | server.py:2862-2867 vs 3651-3653 | 3 | day-over-day OI change | two producers (banked oi_daily; chain captures) | terrain delta_oi_walls vs /api/forces | OPEN |
| S-18 | server.py:2931 | 8 | status spot | SPY only | console log | OPEN |
| S-19 | server.py:2967-2968, 3019-3020 | 5 | board, viewed set | `except: tickers = []` / `_viewed_syms = []` hide failures | terrain loop | OPEN |
| S-20 | server.py:3208, 585 | 3 | spot_state | live_spot evaluated again after resolve_spot | /api/terrain, alerts | OPEN |
| S-21 | server.py:3225-3226 | 3/5 | net_gex_at_spot, gamma_at_spot | carried to a new spot by (S/S0)^2 outside compute_terrain | NET GEX chip, regime | OPEN |
| S-22 | server.py:3292-3293 | 3 | near/far split | route hard-codes `d <= 7`; terrain_engine has its own split | /api/terrain/strikes | OPEN |
| S-23 | server.py:3357-3359 | 5 | side sums | rows with missing strike/gamma/volume dropped uncounted | today_side_sums | OPEN |
| S-24 | server.py:3409, 3584, 5083 | 6 | chart bars, tape, liquidity bars | live screens read the DB | chart, tape, liquidity | OPEN (P2-3) |
| S-25 | server.py:3511/3515, 3530/3533 | 3 | spot | resolve_spot twice in one response | vanna/charm-by-strike | FIXED 7b64cae6 |
| S-26 | server.py:3911 | 5 | gamma_available | missing flag defaults to available | gamma-surface | FIXED 7b64cae6 |
| S-27 | server.py:3955-3979 | 3 | complete/coverage | labels a full chain "near-money, complete False" | heatmap coverage label | OPEN (fixed in #346, unmerged) |
| S-28 | server.py:4154, 4180, 4212 | 5 | desk window, cross direction/counts | window defaults to one day; missing direction reads "below"/down | /api/desk/events | FIXED 317093a8 |
| S-29 | server.py:4229-4233 | 3/6 | level crosses | raw DB read beside _merged_recent_crosses; missing direction -> down | /api/alerts | FIXED 317093a8 (DB read on the live path: S-24/P2-3) |
| S-30 | server.py:4318, 4356-4357 | 5 | flow, streaming_plane | exception -> None / {} with no reason | order flow, options microstructure | OPEN |
| S-31 | server.py:4345 | 5 | put_call | first-of | options microstructure | NOT A VIOLATION: one contract carries one CONTRACT_TYPE |
| S-32 | server.py:4582 | 5 | expiry | first expiry when none asked | /api/chain | NOT A VIOLATION: the served default view is the front expiry, named in the response |
| S-33 | server.py:4614, 4619 | 2 | strikePrice | read raw | /api/chain | FIXED 317093a8 |
| S-34 | server.py:4952-4957 | 5 | canonical levels stale | hard-coded `"stale": False` | /api/levels, alerts | FIXED 7b64cae6 |
| S-35 | server.py:4964-4965 | 3/5 | em_up/em_dn | live spot + chain-time move under the terrain's as-of | /api/levels | OPEN |
| S-36 | server.py:5040 | 5 | prev-day levels | first-of across keys | liquidity raw_levels_used | OPEN |
| S-37 | server.py:5111-5135 | 3/5 | zone anchor, tradeable_score | mid substituted; score with no spot; distance penalty computed in the route | liquidity zones | OPEN |
| S-38 | server.py:4633, 4650 | 5 | logger_running | never set True; /api/health always False | /api/health | FIXED 7b64cae6 |

## D — database and infrastructure

| ID | file:line | rule | value | what it does | seen by | status |
|---|---|---|---|---|---|---|
| D-01 | db.py:2703, 2714 | 2 | price_bars_1m OHLC | bare float(), no schwab_number (-999/NaN stored as a price) | charts, ATR, labels | FIXED 6a1672d9: the dict path is deleted; the one caller passes Candle bars whose OHLC server._write_streamed_bar read with schwab_number |
| D-02 | db.py:2708 | 5 | bar timestamp | first-of over 4 keys, default 0 | price_bars_1m | FIXED 6a1672d9: dict path deleted; ts is the Candle's bar start |
| D-03 | db.py:2711, 2719, 2724, 2752, 2758 | 5 | bars | dropped silently, uncounted | price_bars_1m | FIXED 6a1672d9: the parse drops went with the dict path; an off-grid bar is refused and counted (warning), a bar outside the collect window counted (debug) |
| D-04 | db.py:2721 | 5 | bar source | no source labelled authoritative | price_bars_1m.source | FIXED 6a1672d9: no caller-supplied source; the column default labels every row |
| D-05 | db.py:2732-2734 | 2 | bar time | unit guessed by magnitude; rounded to the minute grid | price_bars_1m | FIXED 6a1672d9: no unit guess, no snapping; an off-grid bar is refused and counted |
| D-06 | db.py:2654 | 3 | snapshots.timeframe | relabelled to 1m | (writer dead) | FIXED 6a1672d9: insert_snapshot deleted |
| D-07 | db.py:2319 | 3 | horizon slugs | hard-coded second copy | schema | FIXED 6a1672d9: the migration and its slug fallback deleted |
| D-08 | db.py:3462, 3540, 3588; movement_target_threshold.py:165-245; calibration/movement_target_thresholds_by_horizon_v1.json | 5/8 | outcome labels | placeholder point thresholds, same for every ticker; fallback chain JSON -> legacy blend -> 1e-9 | stored snapshot labels, rewritten on every bar write | FIXED 6a1672d9: the outcome pipeline, movement_target_threshold.py and both threshold JSON files deleted |
| D-09 | db.py:3625 | 5 | outcome_filled | first-of new vs stored | stored | FIXED 6a1672d9: the outcome pipeline deleted |
| D-10 | db.py:3689 | 3 | session label | second session classifier beside time_et.session_label | tools | OPEN |
| D-11 | db.py:3148 | 5/6 | prior-session OI | returned without its date; live path reads the DB | delta_oi_walls | OPEN |
| D-12 | db.py:3205-3207 | 5 | level crosses | invalid levels skipped uncounted | level_crosses | OPEN |
| D-13 | calibration/complete_chain_capture.py:242 | 2 | underlyingPrice | `== -999` only, not schwab_number; text aborts the round | stored captures | OPEN |
| D-14 | calibration/complete_chain_capture.py:95, 247, 252 | 5 | contracts, counts | non-dict and no-expiry contracts dropped uncounted; skipped writes counted as written | captures | OPEN |
| D-15 | calibration/complete_chain_capture.py:157 | 5 | nearest capture | 30 s memo serves a cached None after a newer capture | option root match | OPEN |
| D-16 | live_schwab_env.py:257, 355 | 3 | placeholder credentials, capability | second authority beside config | launcher | OPEN |
| D-18 | runtime_preflight.py:293 | 5 | requirements | missing requirements.txt reports OK | launcher | OPEN |

## M — math, levels and terrain

| ID | file:line | rule | value | what it does | seen by | status |
|---|---|---|---|---|---|---|
| M-01 | liquidity_value_engine.py:95, 109, 160, 192, 215, 221, 226 | 5/2 | bar timestamp | fallback and first-of key chains; units guessed by magnitude; `_ts or timestamp` | every bar-derived level | OPEN |
| M-02 | liquidity_value_engine.py:143-200; liquidity_models.py:63 | 5 | bars | dropped uncounted (no ts / OHLC / volume) | levels, POC/VAH/VAL | OPEN |
| M-03 | liquidity_value_engine.py:79 | 5 | tradeable_score | no spot -> a different formula | liquidity map | OPEN |
| M-04 | liquidity_value_engine.py:388 | 3 | RTH open | hard-coded 9:30 beside RTH_OPEN | ORB on /api/levels | OPEN |
| M-05 | liquidity_value_engine.py:426, 490 | 5 | VWAP | bars with no volume skipped uncounted | VWAP | OPEN |
| M-06 | liquidity_value_engine.py:439 | 5 | VWAP sigma | negative variance clamped to 0 | bands | NOT A VIOLATION: a variance is never negative; the clamp removes float rounding below 0 |
| M-07 | liquidity_value_engine.py:474, 1648, 1656 | 3 | VWAP bands | two computations; the series' last point overwritten by the other | /api/levels, chart | FIXED c86e95dd |
| M-08 | liquidity_value_engine.py:569, 575, 667-682, 764-809, 865-880, 961-983, 1185-1216 | 2/5 | level prices | truthiness treats 0 as missing | zones | OPEN |
| M-09 | liquidity_value_engine.py:984, 1050-1059 | 5 | value_state, vwap_relation, new_value_area | missing input -> "unchanged"/"at_value"; floor 0.01 | snapshot summary | OPEN |
| M-10 | liquidity_value_engine.py:757, 853, 952, 1174, 1341 | 3 | PDH..VWAP | checkpoint and replay builders recompute the Phase 2A families under the same ids | /api/liquidity-snapshot | OPEN |
| M-11 | liquidity_value_engine.py:1271, 1460, 1594, 1685 | 5/3 | cutoff label, session_scope, absent families | label says now for canonical values; relabel fallback; absence recorded only when all three missing | /api/levels | OPEN |
| M-12 | liquidity_value_engine.py:1222 | 2/5 | fused option levels | raw float, dropped silently | zones | OPEN |
| M-13 | math_exposure_core.py:30; math_levels.py:216 | 2 | IV, strike, multiplier | IV 0, strike 0, multiplier 0 rejected as bounds | exposures | OPEN (IV 0: see note) |
| M-14 | math_exposure_core.py:209, 218, 222-223, 252 | 5/3 | contracts | dropped uncounted; bad multiplier skipped before OI counted so the leg reads a known 0; diag counts them as "greeks missing" | OI, PCR, max pain | OPEN |
| M-15 | math_exposure_core.py:156-159, 239-249, 347-349 | 5 | sizes, dollars | accumulators start at 0.0; unreported reads 0 | per-strike | OPEN |
| M-16 | math_exposure_core.py:292, 324 | 3 | IV validity | inline re-implementation of schwab_iv_to_sigma | vanna | OPEN |
| M-17 | math_exposure_core.py:345, 687 | 5 | net vanna | $0 served when nothing priced a vanna | vanna_agg | FIXED 238ae6fb |
| M-18 | math_exposure_core.py:497, 500 | 2/5 | quoteTimeInLong, overlay baseline | raw float, 0 missing; fallback baseline | overlay | OPEN |
| M-19 | math_exposure_core.py:557, 573, 763, 921 | 5 | leg OI/volume, unwind, key delta strike | missing leg read as 0 | max pain, PCR, key delta | OPEN |
| M-20 | math_exposure_core.py:713 | 5/3 | DEX$ | reads 0.0-initialised fields, always "seen", $0 served; re-sums net_dex | dex_dollars | FIXED: the per-strike cell reads the delta flag (238ae6fb); the book total had no reader and is deleted |
| M-21 | math_exposure_core.py:795, 867 | 5 | 0DTE share, gamma strength | missing book -> 0%; single strike -> 100% | terrain | OPEN |
| M-22 | math_exposure_core.py:35 | 5 | book net GEX | partly valid strikes summed, invalid dropped silently | regime | OPEN |
| M-23 | math_exposure_core.py:969, 991 | 5 | gamma/delta walls | raw-gamma/raw-delta fallback when not dollarized | walls | FIXED 238ae6fb |
| M-24 | math_levels.py:150, 666 | 2 | spot | `not spot` | charm, flip | OPEN |
| M-25 | math_levels.py:297 | 5 | contract gamma | non-finite -> 0.0 uncounted | flip | OPEN |
| M-26 | math_levels.py:334 | 5 | flip | no spot -> first crossing | flip | OPEN |
| M-27 | math_levels.py:353-357, 609-634 | 3/5 | profile at a price | two interpolators, both carry the endpoint off the profile | GSF, flip diag | OPEN |
| M-28 | math_levels.py:429; terrain_engine.py:742 | 3 | gamma at spot | GSF uses the curve, regime uses Schwab's book; flip_diag's gamma_at_spot overwritten by the other producer under the same key | regime vs gsf_state | FIXED 12daaf9f for the flip_diag key; GSF (curve) vs regime (Schwab book) are two measures, open to label |
| M-29 | terrain_engine.py:365 | 5 | contract side | anything not PUT becomes call | chain ladder | OPEN |
| M-30 | terrain_engine.py:332 | 2 | strike volume | `if r[2]` | migration | OPEN |
| M-31 | terrain_engine.py:859 | 5 | computed_ts_utc | compute time labelled as fetch time | ages | OPEN |
| M-32 | terrain_engine.py:853, 858 | 3/5 | PCR by expiry | books sharing an expiry string overwrite | PCR | OPEN |
| M-33 | terrain_engine.py:818 | 3 | rr_25d scope | labelled front expiry; producer picks nearest 30 d | rr_25d | OPEN |
| M-34 | terrain_atr.py:52, 73 | 2/5/6 | ATR | raw DB OHLC; failure -> None with no reason; live radar reads the DB | radar | OPEN |
| M-35 | math_volatility.py:139 | 2/5 | candle OHLC | first-of keys, raw float | ATR | OPEN |
| M-36 | math_probabilities.py:53, 128, 137 | 5 | direction label, pin score | missing threshold -> "flat"; clamp; unverified divisor | outcome labels, pin gate | OPEN |
| M-37 | time_et.py:269 | 5 | time to expiry | 10-minute floor | every BS greek | OPEN |
| M-38 | time_et.py:151, 219, 255, 21 | 3 | session windows, close time | 240/1200 in two places; second close-time lookup; two names for 9:30 | session label, T | OPEN |

## O — streaming, order flow and Schwab client

| ID | file:line | rule | value | what it does | seen by | status |
|---|---|---|---|---|---|---|
| O-01 | app/options/order_flow/state.py:207; engine.py:47, 214-218, 629; streaming.py:308/310 | 3/5 | BID/ASK price and size | second L1 store (`_top`) with its own 25 s arrival-age freshness; no timestamp counts as fresh | microstructure, Trade Desk book | FIXED 7fab75b4 |
| O-02 | state.py:141-144, 181-182 | 3/7 | TOTAL_VOLUME | third and fourth stores (one never read) | none / overlay | FIXED 7fab75b4 for `_stream_volume` (deleted); equity volume in `_stream_greeks` left, read only for option contracts |
| O-03 | engine.py:274-312, 494-505; live_market_plane.py:123-133 | 3 | spread, spread_frac, mid | three spread producers, two mids; MARK never stored so spread_frac is always None | microstructure | OPEN |
| O-04 | engine.py:276, 351, 419-420, 615, 618 | 2 | MARK, book price, bid/ask, times | 0 rejected or read as missing | microstructure | OPEN |
| O-05 | engine.py:618 | 5 | quote_age_sec | computed from a quote that is not live | ages | OPEN |
| O-06 | engine.py:830-833 | 2/5 | institutional_flow_proxy | clamp with invented divisors | (always None) | OPEN |
| O-07 | state.py:28-38, 137-138 | 3/5 | session reset | own RTH test; clock failure -> "closed"; failure swallowed | tape/book reset | OPEN |
| O-08 | l1_trade_observation.py:143-147, 192-197 | 5 | tape pressure 30s/2m/5m | window anchored to the last print, not now; `now_ms = 0` substitute | Trade Desk flow card | FIXED 972beb7d |
| O-09 | live_market_plane.py:123-138 | 3/7 | spread, quote_mid, *_disp, generation | computed per row, no consumer | none | FIXED 972beb7d (quote_mid kept: the book's MARK); spot_disp formatted twice left |
| O-10 | live_market_plane.py:232; streaming.py:78-103, 181, 223, 905-916; stream_spine.py:274; capture.py:64 | 3 | feed liveness | four thresholds; heartbeat stored twice (5 s vs 3 s) | header vs diagnostics | FIXED 972beb7d for the option and equity quote health (feed_live_for); book age (OF_BOOK_STALE_SEC) and the daemon's own HealthRegistry left |
| O-11 | streaming.py:224-257, 907-916, 1006-1008 | 5 | streaming_healthy | healthy with no data for 8 s; synthetic stale_ms 0.0 | feed badges | FIXED 972beb7d |
| O-12 | streaming.py:952-968, 513-516 | 5 | producer contract, active contract | `symbols[0]` / `held[0]` when the asked contract is not held | subscription panel | NOT A VIOLATION: the field names the producer's held contract; the asked contract's state is subscription_state |
| O-13 | streaming.py:297-312, 361-364, 426-457, 504-507 | 5 | ingest, contract match, DB path | failures swallowed as False/None, uncounted | contract selection | OPEN |
| O-14 | live_price_rows.py:44-66 | 3/5 | forming 1m bar | built from L1 ticks while Schwab streams CHART_EQUITY; a same-price trade in a new minute never opens it | chart | OPEN |
| O-15 | live_price_rows.py:92 | 2 | trade_age_sec | negative age clamped to 0 | header | OPEN |
| O-16 | live_price_rows.py:121-123 | 5 | closed_last | carries time and label, not its source | header | OPEN |
| O-17 | history.py:356-366 | 3/5 | heatmap cell | venues overwrite each other; unobserved side reads 0 | order-flow heatmap | OPEN |
| O-18 | history.py:228-241, 159-162, 172-181, 47-73, 153-156 | 5/2/3 | axis, tape context, trade identity, hydrate | invented 0.01 width; context carried forward; second trade-dedup; raw fields; failures -> [] | heatmap, tape | OPEN |
| O-19 | app/api/routes/options_order_flow.py:26-30 | 5 | minutes | invalid -> 15.0 | (route dead) | FIXED 7fab75b4 (route deleted) |
| O-20 | app/options/contracts/default.py:57 | 5 | ATM spot | banked capture spot, no age check | contract selection | OPEN |
| O-21 | stream_spine.py:153-154 | 5 | ts_recv | build time substituted | every message | OPEN |
| O-22 | stream_spine.py:126; capture.py:101, 175 | 3 | symbol key | `.upper().strip()` beside ticker_storage_key | subscriptions | OPEN |
| O-23 | capture.py:157 | 2/3 | flat L1 columns | raw copy beside native_json | stream_quotes_raw | OPEN |
| O-24 | live_push.py:136-138 | 5 | bar1m replay | last bar re-delivered as new on reconnect | price_bars_1m writer | OPEN |
| O-25 | schwab_client.py:483-484, 561-564 | 5 | chain payload | failure -> {}; merged chain top-level fields first-of | chain consumers | OPEN |
| O-26 | schwab_field_dictionary_builder.py:34, 90-100 | 3/8 | ticker validity | heuristic + hard-coded ticker list used as production validity | production_universe | OPEN |

## P — page code (static/)

| ID | file:line | rule | value | what it does | seen by | status |
|---|---|---|---|---|---|---|
| P-01 | ed-core.js:386-409 | 4/5 | strike window | page index math; middle strike when spot_strike absent; hidden count computed | every windowed panel | OPEN |
| P-02 | ed-core.js:432-436, 822, 835, 887 | 4 | ages, push freshness | thresholds and unit conversion on the page | badges, header | OPEN |
| P-03 | ed-core.js:621, 878 | 5 | expiries, session | failure hidden, no reason | dropdown, header | OPEN |
| P-04 | ed-core.js:674, 678-679, 705, 817, 828-831 | 3/5 | header/watchlist | first-of fields; dead 'stale' branch; chg painted in closed state on the header only; any row marks the list healthy | header, watchlist | OPEN |
| P-05 | index.html:829-1062 (11 sites), 1083, 850, 886 | 5 | ticker label, AI expiry, notes | hard-coded "SPX"; never-updated text | panel headers | OPEN |
| P-06 | ed-gamma.js:54-63, 139-150, 474, 788-805, 836-843 | 4 | heat colour scale, flash, coverage %, counts | max/threshold/percent on the page | heatmap | OPEN |
| P-07 | ed-gamma.js:316-317 | 4/9 | as-of | browser local time, not CT | heatmap note | OPEN |
| P-08 | ed-gamma.js:355-370 | 4/5 | columns | page picks and sorts expiries; falls back to expired columns | heatmap | OPEN |
| P-09 | ed-gamma.js:478, 735, 561-576, 643-645, 730, 904 | 5 | liveness, reasons, defaults | absent -> live; first-of reasons ("undefined"); stale values drawn as normal; col-0 default; any error relabelled | heatmap | OPEN |
| P-10 | ed-gamma-panels.js:10-27; ed-gamma-chart.js:11-16; ed-tv-chart.js:31-38 | 3 | USD/volume formatting | three formatters with different precision | panels, chart | OPEN |
| P-11 | ed-gamma-panels.js:313-339, 623-635; ed-gamma-chart.js:563-615; ed-trade-desk.js:317-329; ed-order-flow.js:82-85; ed-order-flow-heatmap.js:137 | 4/5 | bar scales | max over served data, `|| 0`/`|| 1`, scale endpoints shown as numbers | GBS, vanna/charm, chart, migration, book, heatmap | OPEN |
| P-12 | ed-gamma-panels.js:372, 458-473, 696-700, 684 | 4/5 | Strike Detail, Structures | tolerance pick of contract and net; put substituted for call; UTC date | Strike Detail, Structures | OPEN |
| P-13 | ed-gamma-panels.js:70-71, 86, 197; ed-gamma-chart.js:19, 49-50, 208-227, 321, 361-436, 500-539, 659-664 | 3/4/5 | spot, badges, domain, readout, forming bar | page-formatted spot from a second source; min/max domain + synthetic ±2%; readout computed; forming bar merged on the page; stale drawing kept | chart, Key Levels | OPEN |
| P-14 | ed-tv-chart.js:238, 358-365, 435-481 | 4/5 | bar colour, levels shown, revisions, markers | arithmetic on bars; page filters levels; drops uncounted | Trade Desk chart | OPEN |
| P-15 | ed-trade-desk-map.js:25 | 3 | lookback words | second copy of DESK_LOOKBACK_SEC | Desk | OPEN |
| P-16 | ed-trade-desk-map.js:56, 64, 182, 236, 311-347, 369, 403-404, 427 | 4 | ages, date format, tail bars, VAH/VAL pick, colours, LEVELS age | page math and picks | Desk | OPEN |
| P-17 | ed-trade-desk-map.js:224, 351, 384, 385, 412, 415 | 5 | labels, not-priced, posture, flip relation, bars label, strikes | first-of; posture -> regime; any non-ABOVE -> "Below flip"; served 0 -> "—" | Desk | OPEN |
| P-18 | ed-trade-desk.js:114-117, 150, 309-336 | 4/5 | labels, distance, zone type, migration window/tags | first-of; negation; unknown type -> resistance; strike matching | Right Now | OPEN |
| P-19 | ed-stream.js:72-73, 328-330 | 3/5 | ACK verdict, book subscription | second ACK validator; marked warmed before ack, failure never shown | Flow, Book | OPEN |
| P-20 | ed-order-flow-heatmap.js:131-205 | 4/5/3 | grid, buckets, cell side, axis, readout | defaults (`|| 90`, `|| 0.01`); re-binning with last-wins; EVEN painted bid; date math | order-flow heatmap | OPEN |
| P-21 | ed-liquidity-map.js:27, 105-155 | 3/4/5 | zone type, PD/ON levels, range | unknown -> Resistance; levels from a second route; min/max range; invalid zones dropped uncounted | Liquidity Map | OPEN |
| P-22 | ed-gamma-flow.js:102, 172-175; options_subscription.js:121 | 3/5 | subscription badge, header contract | unknown -> PENDING; contract from shell state, not served | Options Flow | OPEN |
| P-23 | ed-gamma-chain.js:94 | 2 | chain cells | prints any number (server stripping of -999 to confirm) | Options Chain | OPEN |
| P-24 | ed-order-flow.js:86, 98-102 | 4/5 | wall marking, no-book reason | page matching; one reason for every cause | Book | OPEN |
| P-25 | ed-alerts.js:13, 20, 31 | 5 | alerts | HTTP failure shown as "no alerts"; strip hidden with no reason | alert strip | OPEN |

## X — code with no job (rule 7)

| ID | where | what | status |
|---|---|---|---|
| X-01 | static/governance.html, static/ops.html | whole pages; every route they call is gone (404) | FIXED bea2630b |
| X-02 | server.py:887-937, 734, 1131, 4016 | executors never used, `_main_event_loop`, `_l1_sse_last_drop_mono`, empty CORE_TICKERS, /api/spot (no page caller) | FIXED bea2630b, except CORE_TICKERS (goes with S-03) |
| X-03 | db.py:274, 282, 2601, 2866, 2981, 3073, 3285, 3399, 3638, 3689, 3718, 118-129, 1399-1426, 1439, 1488, 1848, 2521, 3106, 3115, 3267-3275 | snapshot writer and outcome pipeline with no writer, dead tables' code, iv_daily (no reader), unread rings and constants | FIXED 6a1672d9 (writer, pipeline, dead-table DDL, rings, constants, no-op at 3106); iv_daily kept: NOT A VIOLATION, it is session history for IV rank (RC-354), and the database is history (rule 6) |
| X-04 | execution_identity.py, decision_record.py, horizon_outcomes.py, ml_horizon.py, movement_target_threshold.py, api_pressure.py, schwab_field_dictionary_builder.py:117-395, config.py:92-96 | modules or parts with no product caller | FIXED 6a1672d9 for execution_identity.py, decision_record.py, horizon_outcomes.py, ml_horizon.py, movement_target_threshold.py; api_pressure.py kept, schwab_client imports it (its unread _events ring and its UI-banner log text stay OPEN); schwab_field_dictionary_builder.py:117-395 and config.py:92-96 OPEN (not checked in P2-5 part 1) |
| X-05 | app/options/order_flow/engine.py:680-835, 942-998; routes/options_order_flow.py; history.py:19; state.py `_stream_volume` | options-flow, rvol and institutional proxy paths that always return None; retired fields; dead route | FIXED 7fab75b4 for the history route and hydrate_option_content; the engine's always-None paths left |
| X-06 | live_market_plane.py:38-51, 150, 317-321 | SSE cursor and fast generation with no reader | FIXED 972beb7d |
| X-07 | liquidity_value_engine.py:750, 846, 945 (+ premarket via generate_*) | checkpoint snapshot builders; the page sends only snapshot=live | OPEN |
| X-08 | math_levels.py:234-240, 703; math_exposure_core.py:167, 895; liquidity_models.py:212; terrain_read.py:95, 106; micro_structure.py:52 | unused branches, parameters and fields | OPEN |
| X-09 | static/js: ed-stream.js status/acceptedForDesired/getDesiredAdditional/gate/setActiveTicker export; l1_sse_guards.js five test-only functions; options_subscription.js planeIsBoundToContract/subscriptionState/isCurrent/pendingContract; ed-core.js exports and `_wlLastGoodTs`; ed-gamma.js `_heatmapVisibleContracts`, exports; ed-tv-chart.js exports; fallback formatters and loader stubs; unused locals | test-only or never called | OPEN |
| X-10 | tools/rth_completeness_check_v1.py:104; tests/test_runtime_layout_v1.py:31-33; db_safety.py:1-19 | call or name things that do not exist | OPEN |

Note (M-13): IV 0 is rule 2 "a reported 0 is 0"; a contract with sigma 0 has no Black-Scholes
gamma (the price is intrinsic), so it cannot be priced: counted as `no_volatility`, never dropped
silently (cd9e0cb9). The strike and multiplier bounds are Schwab's own definitions (a strike and a
contract size are positive) and are to be confirmed per field against the Schwab field reference.
