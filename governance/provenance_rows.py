"""The provenance rows: one module, one row type, no bookkeeping rows.

GENERATED 2026-09-07 from the four mega inventories by the mega REPAIR (scratchpad/mega_build.py):
every row whose disposition carries provenance (SCHWAB_LEAF, REPLACED, DERIVED, ALLOWLISTED)
was copied verbatim; the 1,421 NONE rows (every-function bookkeeping) were dropped because a
row that says nothing about lineage proves nothing about lineage. Rows are keyed
(file, derivation) and resolved by governance/provenance_inventory.py. Edit by hand.
"""
from __future__ import annotations

from governance.provenance_inventory import Row

ROWS: tuple[Row, ...] = (
    Row(
        file='server.py', derivation='get_alerts', disposition='DERIVED',
        producer_refs=('server.py:_terrain_refresh_one', 'server.py:resolve_spot'),
        justification='Proximity alerts: spot (resolve_spot) against the published gamma walls, and the level crosses the levels producer records.',
    ),
    Row(
        file='server.py', derivation='get_session', disposition='ALLOWLISTED',
        allowlist_id='mega1_session_calendar',
        justification='The market session label from the ET clock and the trading calendar (time_et.session_label); no market field.',
    ),
    Row(
        file='live_market_plane.py',
        derivation='get_quote',
        disposition='DERIVED',
        producer_refs=('app/options/order_flow/streaming.py:_ingest_pushed',),
        justification='Delegates to Schwab transport producers for get_quote.',
    ),
    Row(
        file='live_market_plane.py',
        derivation='record_from_level_one_equity',
        disposition='DERIVED',
        producer_refs=('app/options/order_flow/streaming.py:_ingest_pushed',),
        justification='Delegates to Schwab transport producers for record_from_level_one_equity.',
    ),
    Row(
        file='math_exposure_core.py',
        derivation='_pick_strike_max_metric',
        disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Max-metric strike picker.',
    ),
    Row(
        file='math_exposure_core.py',
        derivation='bucket_metric',
        disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Fail-closed; no .get(k,0).',
    ),
    Row(
        file='math_exposure_core.py',
        derivation='compute_exposures_by_strike',
        disposition='DERIVED',
        producer_refs=('server.py:flatten_chain_contracts',),
        justification='Core Schwab chain aggregation; skip -999 greeks.',
    ),
    Row(
        file='math_levels.py',
        derivation='_norm_pdf',
        disposition='DERIVED',
        producer_refs=('math_levels.py:bs_vanna',),
        justification='Standard normal PDF; pure math constant, no market field.',
    ),
    Row(
        file='math_levels.py',
        derivation='compute_gamma_flip_v2',
        disposition='DERIVED',
        producer_refs=('server.py:flatten_chain_contracts',),
        justification='Gamma flip plus chain-span confidence flag; narrow chains are never served as trustworthy.',
    ),
    Row(
        file='math_levels.py',
        derivation='compute_gamma_profile',
        disposition='DERIVED',
        producer_refs=('server.py:flatten_chain_contracts',),
        justification='Dealer gamma recomputed at each hypothetical spot (+call/-put); canonical profile.',
    ),
    Row(
        file='math_probabilities.py',
        derivation='compute_pin_score',
        disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Pin score from GEX.',
    ),
    Row(
        file='math_volatility.py',
        derivation='compute_atr._get',
        disposition='DERIVED',
        producer_refs=('server.py:_read_bars_1m',),
        justification='Nested candle field reader inside compute_atr.',
    ),
    Row(
        file='server.py',
        derivation='get_bars1m',
        disposition='DERIVED',
        producer_refs=('server.py:_read_bars_1m',),
        justification='Serves canonical 1m OHLCV bars from the cached bars store; no direct chain leaf.',
    ),
    Row(
        file='terrain_engine.py',
        derivation='compute_terrain',
        disposition='DERIVED',
        producer_refs=('server.py:flatten_chain_contracts',),
        justification='Assembles the terrain payload (regime, walls, pin, HVL, max pain, charm walls) from one chain; no model stack.',
    ),
    Row(
        file='calibration/schema.py', derivation='_migrate_calibration_decision_log_columns', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='DDL migration: takes a sqlite3.Connection, ADD COLUMN on calibration_decision_log for any missing nullable columns under the current schema. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/schema.py', derivation='_migrate_calibration_pending_index', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='DDL migration: takes a sqlite3.Connection, CREATE INDEX IF NOT EXISTS on the pending rows index. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='calibration/schema.py', derivation='_migrate_calibration_unique_ticker_decision_ts', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='DDL migration: takes a sqlite3.Connection, alters calibration_decision_log to add the (ticker, decision_ts_utc) unique constraint. Persistence-only; no Schwab wire derivation.',
    ),
    Row(
        file='live_market_plane.py', derivation='reset_sse_push_cursor', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (reset_sse_push_cursor).',
    ),
    Row(
        file='market_context.py', derivation='market_context_panel_symbols_excluding_core', disposition='SCHWAB_LEAF',
        schwab_leaf='quotes.quote.lastPrice',
        justification='Schwab API or wire JSON ingest path.',
    ),
    Row(
        file='math_exposure_core.py', derivation='_strike_bucket', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.openInterest',
        justification='Strike dict lookup.',
    ),
    Row(
        file='math_exposure_core.py', derivation='bucket_metric_abs', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='Abs of bucket_metric.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_delta_oi_walls', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification="RC-359: diffs today's {strike: (call_oi, put_oi)} map — taken from the terrain snapshot's oi_by_strike, i.e. the same exposures book — against the prior session banked by server.py, then picks the largest call build, largest put build and deepest combined unwind. It reads no vendor leaf; the OI values reach it already parsed. Fail-closed: None when no prior session is banked, so the diff is withheld rather than invented.",
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_net_dex_dollars', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification="RC-361: sums call_dex_dollars MINUS put_dex_dollars over the same exposures book, giving the dealer's net delta notional (put deltas already arrive negative, so subtracting the put leg lands on the dealer's side). Consumes only fields the book produced; fail-closed to None on an empty/degenerate book rather than a fabricated $0.",
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_net_vanna', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike', 'terrain_engine.py:compute_terrain'),
        justification='RC-362: sums call_vanna MINUS put_vanna over the ONE exposures book compute_exposures_by_strike already built (per-strike vanna is the vega/(S*IV) proxy accumulated with OI and multiplier at parse time), divides by 100 for per-vol-point and multiplies by spot for dollars. Reads no vendor field itself; the dealer sign model is inherited from the book, not re-encoded. Fail-closed: None on an empty/valueless book or missing spot, never a fabricated zero.',
    ),
    Row(
        file='math_exposure_core.py', derivation='compute_zero_dte_gamma_share', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='RC-357: share of sum(|net_gex_1pct|) contributed by the same-day-expiry book over the full book, where BOTH books come from compute_exposures_by_strike (the 0DTE one is the same call with use_only_dte_max=0) — same parser, same sign model, no second math path. A strike with no valid gamma (unpriced, or excluded for an invalid contract and listed in the diagnostics) is left out of both the 0DTE and the full sum, never counted as zero.',
    ),
    Row(
        file='math_exposure_core.py', derivation='exposures_have_dollar_gex', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='Detects dollarized GEX availability.',
    ),
    Row(
        file='math_exposure_core.py', derivation='greek_reported', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification="Schwab's per-contract Greek is used exactly as sent unless Schwab marks it as having no value (-999 on the Greek or on the contract's volatility).",
    ),
    Row(
        file='math_exposure_core.py', derivation='key_level_strikes_with_gamma', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.gamma',
        justification='Strikes with usable gamma.',
    ),
    Row(
        file='math_exposure_core.py', derivation='key_level_strikes_with_oi', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.openInterest',
        justification='Strikes with OI leaf.',
    ),
    Row(
        file='math_exposure_core.py', derivation='net_gex_dollars_at_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='Net GEX$ at strike.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_delta_wall_strikes', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:exposures_have_dollar_gex', 'math_exposure_core.py:_pick_strike_max_metric', 'math_exposure_core.py:bucket_metric_abs'),
        justification='Call/put delta walls.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_gamma_wall_strikes', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:exposures_have_dollar_gex', 'math_exposure_core.py:_pick_strike_max_metric', 'math_exposure_core.py:bucket_metric_abs'),
        justification='Call/put gamma walls.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_key_delta_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric_abs',),
        justification='Selects the strike with the largest total delta notional (|call DEX$|+|put DEX$|) from derived exposures; no raw leaf read.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_key_delta_strike._total_dex', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric_abs',),
        justification='Nested: sums |call DEX$|+|put DEX$| per strike bucket for the key-delta selection.',
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_net_gex_peak_strike', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification="RC-124/RC-417: the strike with the largest |net GEX$| per 1% (calls MINUS puts) — a real measure of where the signed book concentrates, formerly displayed under the name 'gamma pin'. ExposureRow.net_gex_peak is this strike; the canonical pin is pick_pin_and_strength. institutional=True returns None rather than falling back to raw gamma.",
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_pin_and_strength', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification="RC-124/RC-315: the strike with maximum TOTAL gamma (|call GEX$| + |put GEX$|) — a GROSS GAMMA CONCENTRATION, i.e. where the most dealer re-hedging activity sits — plus strength_pct, the leader's margin over the runner-up on the same metric. It is a pin CANDIDATE and NOT a demonstrated magnet: magnitude sets the SIZE of the hedging flow while the SIGN of the dealer position sets whether that flow stabilises or repels, and this metric discards the sign, so two strikes with equal absolute gamma can behave oppositely. The sign is also not observable — public open interest does not say who owns the contracts, so dealer direction is modelled (https://spotgamma.com/what-is-gex-gamma-exposure/). Expiration-date clustering turns on NET positioning, not gross: Ni, Pearson and Poteshman, Journal of Financial Economics, doi:10.1016/j.jfineco.2004.08.005. An earlier version of this row asserted that magnitude pins regardless of sign; that was refuted (RC-315) and must not return. Fail-closed: no dollarized GEX gives (None, None), never a raw-gamma fallback.",
    ),
    Row(
        file='math_exposure_core.py', derivation='pick_volatility_point_strikes', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric',),
        justification='(HVP, LVP): strikes holding the most-negative / most-positive net GEX$ from derived exposures.',
    ),
    Row(
        file='math_exposure_core.py', derivation='schwab_iv_to_sigma', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.volatility',
        justification='Single conversion of Schwab IV (reported in percent) to decimal sigma; guards a vendor units change.',
    ),
    Row(
        file='math_exposure_core.py', derivation='total_gamma_raw_at_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric_abs',),
        justification='Raw gamma magnitude fallback.',
    ),
    Row(
        file='math_exposure_core.py', derivation='total_gex_dollars_at_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:bucket_metric_abs',),
        justification='Sum |call|+|put| GEX$.',
    ),
    Row(
        file='math_levels.py', derivation='_contract_inputs', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.volatility',
        justification='Reads strike/IV/OI/DTE/putCall leaves from the Schwab contract; normalizes IV-in-percent.',
    ),
    Row(
        file='math_levels.py', derivation='_interp_profile_at', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_profile',),
        justification='Linear interpolation of net GEX$ at an arbitrary price on the ascending profile compute_gamma_profile materialised; clamps to the endpoints outside the profile span. Operates purely on that derived profile — no vendor field is read here.',
    ),
    Row(
        file='math_levels.py', derivation='bs_charm', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_charm_by_strike',),
        justification='Black-Scholes charm dDelta/dt per share; verified against a finite-difference derivative of BS delta.',
    ),
    Row(
        file='math_levels.py', derivation='bs_vanna', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Black-Scholes vanna dDelta/dSigma per share, closed form -e^(-qT) phi(d1) d2 / sigma — identical for calls and puts, sign driven entirely by -d2 so it flips through SPOT and never through the call/put boundary. Independently verified 2026-08-02 against a central finite difference of BS delta over 27 (K,T,sigma) points to max |err| 9.1e-9, and against both the vega and gamma identities; the gamma identity is a standing cross-check in tests/test_charm_sign_finite_difference.py. Units are delta-change per 1.00 of IV.',
    ),
    Row(
        file='math_levels.py', derivation='compute_charm_by_strike', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification='Per-strike dealer charm exposure in delta-shares/day, +call/-put convention.',
    ),
    Row(
        file='math_levels.py', derivation='compute_gamma_support_levels', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_profile', 'math_levels.py:_interp_profile_at'),
        justification='RC-354: the Gamma Support Floor (highest s < spot with N(s) <= phi*N(spot)) and Gamma Resistance Ceiling (lowest s > spot with the same condition) on the SAME materialised net-GEX profile the flip and regime read (RC-345 one-profile rule), located by walking outward from spot and linearly interpolating the crossing. Fail-closed: N(spot) <= eps returns state=BELOW_SUPPORT with both levels None, an unusable profile returns state=UNAVAILABLE — never a fabricated price.',
    ),
    Row(
        file='math_levels.py', derivation='compute_max_pain', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Max pain from OI; no Schwab max-pain leaf.',
    ),
    Row(
        file='math_levels.py', derivation='compute_max_pain._pain_at', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_max_pain',),
        justification='Nested pain calc at settlement inside compute_max_pain.',
    ),
    Row(
        file='math_levels.py', derivation='gamma_at_price', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_flip_v2',),
        justification='Net dealer gamma interpolated at a price; the SIGN of this value defines the regime, independent of whether a flip exists.',
    ),
    Row(
        file='math_levels.py', derivation='gamma_flip_from_profile', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_gamma_flip_v2',),
        justification='Interpolated zero-crossing of the gamma profile.',
    ),
    Row(
        file='math_levels.py', derivation='pick_charm_wall_strikes', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification='Strikes of maximum call-side and put-side charm exposure.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_25d_risk_reversal', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.volatility',
        justification='RC-358: IV(25-delta call) minus IV(25-delta put) on the front expiry, in vol points. Unlike the other RC-35x metrics this one reads the vendor contract dicts directly — putCall, daysToExpiration, delta and the `volatility` leaf, which Schwab reports in PERCENT and which stays in vol points here. Front expiry is the smallest usable dte >= 0; each wing must sit within RR25_DELTA_TOL of its +/-0.25 target and the -999 missing-greek sentinel is rejected, so a missing or off-target wing withholds the whole reading rather than producing a fabricated skew.',
    ),
    Row(
        file='math_volatility.py', derivation='compute_atr', disposition='DERIVED',
        producer_refs=('math_volatility.py:compute_atr._get',),
        justification='ATR from Schwab candles; skip incomplete bars.',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='OrderFlowEngine._empty_result', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (OrderFlowEngine._empty_result).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='OrderFlowEngine.compute', disposition='DERIVED',
        producer_refs=('app/options/order_flow/state.py:get_content_for_symbol',),
        justification='Public OF engine entry; composes sub-metrics.',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_book_concentration', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_concentration).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_book_imbalance_from_totals', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_imbalance_from_totals).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_book_pressure_curve', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_pressure_curve).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_book_side_depth_total', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_side_depth_total).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_book_slope', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_slope).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_book_wall_candidates', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_book_wall_candidates).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_compute_cum_delta_proxy', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_cum_delta_proxy).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_compute_cum_delta_slope', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_cum_delta_slope).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_compute_institutional_flow_proxy', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_institutional_flow_proxy).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_compute_options_flow', disposition='DERIVED',
        producer_refs=('app/options/order_flow/engine.py:_iter_option_exp_levels', 'app/options/order_flow/engine.py:_option_contract_volume'),
        justification='Options flow from chain/stream maps.',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_compute_rvol', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_rvol).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_compute_spread', disposition='DERIVED',
        producer_refs=('app/options/order_flow/engine.py:_resolve_quote_mark',),
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_spread).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_compute_tape_pressure', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_tape_pressure).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_compute_top_book_pressure', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_compute_top_book_pressure).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_extract_canonical_book', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_extract_canonical_book).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_iter_asks_levels', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_asks_levels).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_iter_bids_levels', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_bids_levels).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_iter_content', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_content).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_iter_option_exp_levels', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_iter_option_exp_levels).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_latest_book_snapshot', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_latest_book_snapshot).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_latest_content_field', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='PR214 Gap 1: the ONE freshness-aware per-field resolver over Schwab LEVELONE_OPTIONS/EQUITIES partial/delta content items (_latest_content_field).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_microprice', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_microprice).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_microstructure_structural', disposition='DERIVED',
        producer_refs=('app/options/order_flow/engine.py:_book_side_depth_total', 'app/options/order_flow/engine.py:_microprice', 'app/options/order_flow/engine.py:_book_wall_candidates'),
        justification='Structural book microstructure: depth totals, imbalance, microprice, slope, concentration and wall candidates from one canonical book snapshot.',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_nonnegative_float', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_nonnegative_float).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_option_contract_volume', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_option_contract_volume).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_resolve_bid_ask_prices', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_resolve_bid_ask_prices).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_resolve_quote_mark', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_resolve_quote_mark).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_safe_float', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_safe_float).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_safe_int', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_safe_int).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='_sorted_valid_levels', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_sorted_valid_levels).',
    ),
    Row(
        file='app/options/order_flow/engine.py', derivation='compute_book_microstructure', disposition='DERIVED',
        producer_refs=('app/options/order_flow/engine.py:_extract_canonical_book', 'app/options/order_flow/engine.py:_microstructure_structural'),
        justification='Canonical book microstructure producer: extracts the book once, carries structural state per book identity, stamps ages; the API route serializes it.',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='OrderFlowState._get_book', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_book).',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='OrderFlowState._get_tape', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_get_tape).',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='clear_all_live_state', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Clears tape/book/top/prev-print identity on disconnect/reconnect so prior-session restatements cannot bind the new session.',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='clear_symbol', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (clear_symbol).',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='forget_unsubscribed_symbols', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Clears live state for symbols leaving the active LEVELONE subscription set.',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='get_content_for_symbol', disposition='DERIVED',
        producer_refs=('app/options/order_flow/state.py:push_level_one', 'app/options/order_flow/state.py:push_book'),
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_content_for_symbol).',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='is_rth_open', disposition='ALLOWLISTED',
        allowlist_id='mega1_session_calendar',
        justification='No Schwab market-field derivation in function body.',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='push_book', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (push_book).',
    ),
    Row(
        file='app/options/order_flow/state.py', derivation='push_level_one', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (push_level_one).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='_feed_loop', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Live-push client (2026-09-23): consumes the capture daemon\'s local WebSocket push of Schwab stream messages; opens zero Schwab connections and reads no database (_feed_loop).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='_ingest_pushed', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification="Applies one daemon-pushed Schwab LEVELONE_EQUITIES / book / LEVELONE_OPTIONS message to order_flow_live_state and live_market_plane with the message's own ts_recv -- the same plane-ingest calls the retired DB replay made (_ingest_pushed).",
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='_log_stream', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_log_stream).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='_option_streaming_healthy', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='FRESHNESS/HEALTH 2026-08-30: same feed-connection health gate as _streaming_healthy, mirrored for the independent option-contract slot (_option_streaming_healthy).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='_read_daemon_upstream_health', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification="Per-service Schwab health from the capture daemon's own status (its HealthRegistry), pushed on the console socket every second (_read_daemon_upstream_health).",
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='_read_producer_option_contracts', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification="What Schwab holds per option service, from the capture daemon's pushed status -- distinct from the console's DESIRED contract (_read_producer_option_contracts).",
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='_streaming_healthy', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (_streaming_healthy).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='get_option_contract_book_microstructure', disposition='DERIVED',
        producer_refs=('app/options/order_flow/engine.py:compute_book_microstructure',),
        justification="Order-flow semantic product for one option contract's live book — delegates to the SAME producer the equity route reads, never a second book-imbalance computation (get_option_contract_book_microstructure).",
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='get_option_contract_streaming_diagnostics', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification='FRESHNESS/HEALTH 2026-08-30: same diagnostics shape as get_streaming_diagnostics, mirrored for the independent option-contract slot (get_option_contract_streaming_diagnostics).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='get_plane_authority_for_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_plane_authority_for_ticker).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='get_streaming_diagnostics', disposition='ALLOWLISTED',
        allowlist_id='mega1_diagnostic_log',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (get_streaming_diagnostics).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='set_active_option_contract', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Requests LEVELONE_OPTIONS/OPTIONS_BOOK for one option contract via the daemon signal file (set_active_option_contract).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='set_streaming_active_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (set_streaming_active_ticker).',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='start_order_flow_stream', disposition='DERIVED',
        producer_refs=('app/options/order_flow/state.py:get_content_for_symbol',),
        justification='Delegates to Schwab transport producers for start_order_flow_stream.',
    ),
    Row(
        file='app/options/order_flow/streaming.py', derivation='stop_order_flow_stream', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Schwab LEVEL_ONE/stream book fields ingested via streaming adapter (stop_order_flow_stream).',
    ),
    Row(
        file='schwab_client.py', derivation='build_client_from_token', disposition='ALLOWLISTED',
        allowlist_id='mega1_schwab_py_client',
        justification='Constructs schwab-py client from token file.',
    ),
    Row(
        file='schwab_client.py', derivation='safe_get_chain', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.openInterest',
        justification='Schwab option chain wrapper.',
    ),
    Row(
        file='server.py', derivation='_accrue_chain_observation', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Banks one wide-chain per-strike observation into option_chain_accrual and never raises into the producer; the per-strike values are already derived upstream.',
    ),
    Row(
        file='server.py', derivation='_app_lifespan', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_app_lifespan).',
    ),
    Row(
        file='server.py', derivation='_build_raw_levels_used', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_build_raw_levels_used).',
    ),
    Row(
        file='server.py', derivation='_canonical_price_level_bars', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Phase 2A: the ONE bar input for the canonical snapshot -- price_bars_1m (written only from streamed CHART_EQUITY bars) plus the forming minute; a thin prior session is stamped degraded, never filled; no direct Schwab read.',
    ),
    Row(
        file='server.py', derivation='_charm_book_scope', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.expirationDate',
        justification="RC-288: counts the DISTINCT expirations in the contracts actually summed and reports single_expiry_banked:<date>, full_chain_banked, or unknown. It replaced a hardcoded literal that matched the client's own fallback, so the label could never disagree with itself. An empty or unreadable chain yields unknown, never a confident book for a chain nobody looked at.",
    ),
    Row(
        file='server.py', derivation='_option_expiries', disposition='SCHWAB_LEAF',
        schwab_leaf='expirationchain.expirationList.expirationDate',
        justification='Schwab expiration chain expirationList[].expirationDate, read as dates verbatim.',
    ),
    Row(
        file='server.py', derivation='_gated_safe_get_chain', disposition='DERIVED',
        producer_refs=('schwab_client.py:safe_get_chain',),
        justification='Schwab get_chain wrapper serialized behind the chain-fetch gate; call shape unchanged, fail-open on gate timeout.',
    ),
    Row(
        file='server.py', derivation='_get_fast_quote_executor', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_get_fast_quote_executor).',
    ),
    Row(
        file='server.py', derivation='_hydrate_logger_tickers_from_db', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_hydrate_logger_tickers_from_db).',
    ),
    Row(
        file='server.py', derivation='_is_loggable_session', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_is_loggable_session).',
    ),
    Row(
        file='server.py', derivation='_liquidity_live_1m_overlay_bars', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_liquidity_live_1m_overlay_bars).',
    ),
    Row(
        file='server.py', derivation='_liquidity_zone_tradeable_fields', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_liquidity_zone_tradeable_fields).',
    ),
    Row(
        file='server.py', derivation='_log_schwab_startup_diagnostics', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_log_schwab_startup_diagnostics).',
    ),
    Row(
        file='server.py', derivation='_market_context_panel_auto_candidates', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_market_context_panel_auto_candidates).',
    ),
    Row(
        file='server.py', derivation='_reprice_cached_terrain', disposition='DERIVED',
        producer_refs=('server.py:resolve_spot',),
        justification='Re-evaluates cached gamma profile at the fresh authoritative spot (RC-28); both inputs from traced producers.',
    ),
    Row(
        file='server.py', derivation='_sync_market_context_panel_into_logging_universe', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (_sync_market_context_panel_into_logging_universe).',
    ),
    Row(
        file='server.py', derivation='_terrain_refresh_one', disposition='DERIVED',
        producer_refs=('server.py:flatten_chain_contracts',),
        justification='Fetches one chain and computes terrain into the cache; no model stack, never raises.',
    ),
    Row(
        file='server.py', derivation='api_order_flow_microstructure', disposition='DERIVED',
        producer_refs=('live_market_plane.py:get_quote',),
        justification='Read-only ORDER_FLOW_MARKET_MICROSTRUCTURE_V1 endpoint serializing the canonical book microstructure computed by order_flow_engine.compute_book_microstructure; stamps the exchange quote clock from the live plane get_quote and never recomputes.',
    ),
    Row(
        file='server.py', derivation='api_order_flow_options_microstructure', disposition='ALLOWLISTED',
        allowlist_id='mega1_live_plane_state',
        justification="Same ORDER_FLOW_MARKET_MICROSTRUCTURE_V1 shape as api_order_flow_microstructure, for one option contract's live book. This row serializes over in-memory live-plane state; the actual computation it delegates to (order_flow_streaming.get_option_contract_book_microstructure -> order_flow_engine.compute_book_microstructure, never a second book-imbalance computation) lives in mega2-owned files and is registered + chain-closed there, not re-derived here.",
    ),
    Row(
        file='server.py', derivation='canonical_price_level_snapshot', disposition='DERIVED',
        producer_refs=('server.py:_canonical_price_level_bars',),
        justification='Phase 2A single-materialization entry point; delegates to liquidity_value_engine.materialize_price_level_snapshot (outside MEGA1 scope), computes no market field itself.',
    ),
    Row(
        # api_watchlist_quotes (/api/watchlist-quotes): every watchlist row from the ONE
        # streamed source (live_price_rows.price_row over the live_market_plane row); the REST
        # batch quote read and its parser are gone -- no vendor call on this route.
        file='server.py', derivation='api_watchlist_quotes', disposition='DERIVED',
        producer_refs=('live_market_plane.py:get_quote',),
        justification='Streamed LEVELONE_EQUITIES LAST_PRICE + REGULAR_MARKET_CHANGE_PERCENT per symbol while fresh (live_price_rows.price_row); a symbol with no fresh LAST_PRICE is absent, never filled from REST.',
    ),
    Row(
        file='server.py', derivation='_atr_pair', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='The (daily, 15-minute) ATR from persisted price_bars_1m via terrain_atr.compute_atr_pair, recomputed at most every ATR_TTL_SEC; too few bars reads None, never a vendor stand-in.',
    ),
    Row(
        file='server.py', derivation='_read_bars_1m', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='The newest N price_bars_1m rows for one ticker (written only from streamed CHART_EQUITY bars); every bar reader (_bars_1m/_bars_5m/_session_bars) goes through it.',
    ),
    Row(
        file='server.py', derivation='flatten_chain_contracts', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.callExpDateMap.*.strikePrice',
        justification='Flattens the Schwab chain response into a contract list; single source shared by _fetch_state and the terrain loop.',
    ),
    Row(
        file='server.py', derivation='get_analytics_light_stream', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_analytics_light_stream).',
    ),
    Row(
        file='server.py', derivation='get_chain', disposition='DERIVED',
        producer_refs=('server.py:_gated_safe_get_chain',),
        justification='OPTIONS_ORDER_FLOW_V1 contract-selection surface: serves the live strike_range=ALL Schwab chain for exactly the requested expiry (flatten_chain_contracts verbatim, streamed-field overlay newer than the fetch), or status unavailable with the named reason -- never a stored or captured substitute (fallback register R-01).',
    ),
    Row(
        file='server.py', derivation='get_client', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_client).',
    ),
    Row(
        file='server.py', derivation='get_desk_brief', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='The newest research brief held at `as_of`, with each block aged against that instant rather than against now.',
    ),
    Row(
        file='server.py', derivation='get_desk_dossier', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification="One name's measured structure as it stood at `as_of`, from the desk fact store.",
    ),
    Row(
        file='server.py', derivation='get_desk_radar', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Candidate structure as it stood at `as_of`, read from the desk fact store; the as-of bound is what keeps a replay honest.',
    ),
    Row(
        file='server.py', derivation='get_desk_structure', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Deterministic payoff plus the PHYSICAL terminal distribution for one candidate, as of the requested instant.',
    ),
    Row(
        file='server.py', derivation='get_options_gamma_surface', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-UI-1: strike x expiry GEX$ surface (Options/Gamma heatmap). PREFERRED source is the LIVE terrain cache (current terrain-refresh contracts + live spot, bounded near-money window) — an in-memory read, no SQLite. This SQLite read is the FALLBACK ONLY: the banked morning wide reference (option_chain_morning_full), stale, not intraday, not proven complete. Both paths partition by native expirationDate and route each expiry slice through the shared compute_exposures_by_strike faucet; the endpoint owns no gamma/GEX math and is a projection of the one exposure producer.',
    ),
    Row(
        file='server.py', derivation='get_exposure_flow', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-208: serves banked option_chain_accrual frames for the latest banked session; reads rows this repo already persisted rather than re-deriving them.',
    ),
    Row(
        file='server.py', derivation='get_forces', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='RC-192/RC-199: per-side OI delta from the two newest banked trading-day chains, plus DEX and dealer-signed CHARM summed on the NEWER capture alone. Serves charm_book_scope and charm_error beside the numbers so a surface can state which book was summed and whether the charm failed (RC-288/RC-304).',
    ),
    Row(
        file='server.py', derivation='get_levels', disposition='DERIVED',
        producer_refs=('server.py:resolve_spot', 'server.py:_liquidity_live_1m_overlay_bars'),
        justification='The single levels contract, schema v1: id, price, family, evidence_tier, provenance and staleness for every served level. Assembles already-derived level producers; the gamma family is explicitly excluded from the Tier-B slice and served by /api/terrain until that migration completes, and the payload says so rather than omitting it silently.',
    ),
    Row(
        file='server.py', derivation='get_liquidity_snapshot', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_liquidity_snapshot).',
    ),
    Row(
        file='server.py', derivation='get_spot', disposition='DERIVED',
        producer_refs=('server.py:resolve_spot',),
        justification='Featherweight live spot via the single spot authority resolve_spot (RC-14); no direct leaf here.',
    ),
    Row(
        file='server.py', derivation='get_terrain', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (get_terrain); delegates all level math to terrain_engine.compute_terrain.',
    ),
    Row(
        file='server.py', derivation='get_terrain_strikes', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.strikePrice',
        justification='Per-strike GEX$ endpoint: reads strikePrice/daysToExpiration/totalVolume from the chain.',
    ),
    Row(
        file='server.py', derivation='get_terrain_strikes._per_strike', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.daysToExpiration',
        justification='Nested: builds one per-strike row from the chain leaves; near/far split now via the canonical terrain_engine._dte_of (Cursor-audit F8, replacing the removed nested _dte).',
    ),
    Row(
        file='server.py', derivation='project_gamma_surface', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='RC-UI-1 strike x expiry GEX surface (/api/options/gamma-surface payload owner): PURE projection - partitions the wide chain by native expirationDate through the existing selected-expiry slicer and runs the ONE exposure faucet per slice; every cell is that faucet net_gex_1pct, no exposure math of its own (tests/test_gamma_surface_projection_v1.py invariant I).',
    ),
    Row(
        file='server.py', derivation='get_vanna_by_strike', disposition='DERIVED',
        producer_refs=('math_exposure_core.py:compute_exposures_by_strike',),
        justification='Operator field-inventory audit (2026-09-13): /api/options/vanna-by-strike payload owner. Aggregates the live wide chain (every expiry) through the SAME canonical faucet the Gamma/DEX heatmaps already use and reads its own call_vanna/put_vanna accumulators (RC-211s exact BS-vanna faucet) straight off the per-strike bucket - net_vanna = call_vanna - put_vanna, the identical +call/-put dealer convention net_gex_1pct/net_charm_daily already use. No exposure math of its own (tests/test_vanna_charm_by_strike_v1.py).',
    ),
    Row(
        file='server.py', derivation='get_charm_by_strike', disposition='DERIVED',
        producer_refs=('math_levels.py:compute_charm_by_strike',),
        justification='Operator field-inventory audit (2026-09-13): /api/options/charm-by-strike payload owner. Row-shapes the live wide chain through math_levels.compute_charm_by_strike, the SAME faucet /api/forces charm_below/charm_above already sum, for a per-strike bar chart. No charm math of its own (tests/test_vanna_charm_by_strike_v1.py).',
    ),
    Row(
        file='server.py', derivation='get_options_tape', disposition='DERIVED',
        producer_refs=('app/options/order_flow/history.py:tape_rows_for_symbol',),
        justification='Operator field-inventory audit (2026-09-13): /api/options/tape payload owner (the Options Flow tape). Resolves which contract(s) are currently desired for the ticker (the same identity _desired_stream_greeks_for_ticker already uses) and merges tape_rows_for_symbols own de-duplicated native trade-print rows newest-first. No trade/quote parsing of its own, and no aggressor-side (buy/sell) classification is ever produced anywhere on this path (tests/test_options_flow_tape_v1.py).',
    ),
    Row(
        file='app/options/order_flow/history.py', derivation='tape_rows_for_symbol', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Operator field-inventory audit (2026-09-13): reads the persisted native LEVELONE_OPTIONS stream rows (stream_options_quotes_raw.native_json) directly for one contract symbol, oldest to newest. A tick counts as a trade print only when it carries its OWN LAST_PRICE and TRADE_TIME_MILLIS together (a partial tick can bump LAST_SIZE alone with no fresh price, and must not mint a null-priced trade row); de-dupes on (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE); static contract context (STRIKE_TYPE/CONTRACT_TYPE/EXPIRATION_*/MULTIPLIER/UNDERLYING) is carried forward from whichever prior tick last reported it, since the vendor does not repeat it on every partial update. classification is a mechanical BID_PRICE/ASK_PRICE comparison against that same ticks own quote, never an aggressor-side (buy/sell) inference (tests/test_options_flow_tape_v1.py).',
    ),
    Row(
        file='server.py', derivation='get_order_flow_book_heatmap', disposition='DERIVED',
        producer_refs=('app/options/order_flow/history.py:book_heatmap_for_ticker',),
        justification='Operator field-inventory audit (2026-09-13, "we do not have an order flow heatmap"): /api/order-flow/book-heatmap payload owner. Pure serializer over book_heatmap_for_ticker with a clamped minutes window [5,240]; no binning/aggregation of its own.',
    ),
    Row(
        file='app/options/order_flow/history.py', derivation='book_heatmap_for_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega2_schwab_stream_l1',
        justification='Operator field-inventory audit (2026-09-13): reads the persisted native NASDAQ_BOOK/NYSE_BOOK stream rows (stream_book_raw.native_json) directly for one underlying ticker, bins them into a time x price grid (cell = summed native BID_PRICE/ASK_PRICE TOTAL_VOLUME) — the historical, time-dimensioned counterpart to the live single-snapshot ladder api_order_flow_microstructure already serves from the SAME table. The window always ends at the latest row actually captured for this ticker, never wall-clock now, so a real prior session still renders honestly outside RTH. Fails closed (available:false + a plain reason) at every stage; never interpolates a cell between captured ticks.',
    ),
    Row(
        file='server.py', derivation='get_terrain_strikes._side_sums', disposition='ALLOWLISTED',
        allowlist_id='mega1_internal_helper',
        justification="Nested: sums the already-computed per-strike GEX$ and volume per side of the payload's OWN spot. One aggregator, one spot basis — the in-browser re-sum was killed because a client loop could straddle a different spot and broke silently on payload changes.",
    ),
    Row(
        file='server.py', derivation='post_streaming_active_option_contract', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Subscribes LEVELONE_OPTIONS+OPTIONS_BOOK to one option contract via the daemon signal file — mirrors post_streaming_active_ticker for the separate option-contract slot (post_streaming_active_option_contract).',
    ),
    Row(
        file='server.py', derivation='post_streaming_active_ticker', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Reads persisted snapshot SQLite rows, not Schwab wire JSON (post_streaming_active_ticker).',
    ),
    Row(
        file='server.py', derivation='resolve_spot', disposition='DERIVED',
        producer_refs=('live_market_plane.py:get_quote',),
        justification='THE single spot authority (RC-14): the streamed LEVELONE_EQUITIES LAST_PRICE while fresh (live_price_rows.live_spot over live_market_plane.get_quote), else unavailable; no REST quote, chain, or snapshot leg.',
    ),
    Row(
        file='server.py', derivation='schwab_capability_state', disposition='DERIVED',
        producer_refs=('schwab_client.py:build_client_from_token',),
        justification='RC-514: capability verdict for /api/health, taken from the canonical client and the same _client cache get_client() uses.',
    ),
    Row(
        file='snapshot_access.py', derivation='require_snapshot_timeframe', disposition='ALLOWLISTED',
        allowlist_id='mega1_sqlite_internal',
        justification='Enforces explicit timeframe on snapshot SQL reads.',
    ),
    Row(
        file='terrain_engine.py', derivation='_dte_of', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.daysToExpiration',
        justification="Reads the contract's own daysToExpiration and returns None when it cannot be read; RC-290 removed the 999.0 sentinel that was putting unknown-maturity contracts into the FAR scope and rendering them there.",
    ),
    Row(
        file='terrain_engine.py', derivation='_per_strike_rows', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.totalVolume',
        justification="Builds the [[strike, net_gex_1pct$, session_volume], ...] triples the per-strike panel renders; volume is summed from the chain's own totalVolume through float_nonnegative_or_none, strikes through float_finite_or_none, so a NaN can never become a key or a bar.",
    ),
    Row(
        file='terrain_engine.py', derivation='per_strike_view', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification='Builds the {all, near, far} per-strike rows the ALL / <=7DTE / MONTHLY+ chips switch between from the chain exposure_books (one pricing pass); the maturity split comes from _dte_of and a contract that cannot answer it lands in NEITHER side (RC-290).',
    ),
    Row(
        file='terrain_engine.py', derivation='compute_implied_one_day_move', disposition='SCHWAB_LEAF',
        schwab_leaf='chains.*.volatility',
        justification='RC-113 institutional sigma band EM_1d = S x sigma_ATM x sqrt(1/252); selects the ATM contract by putCall and strikePrice and takes its volatility leaf directly.',
    ),
    Row(
        file='terrain_engine.py', derivation='compute_wall_value_area', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain',),
        justification="RC-115 Market-Profile value area over SIDE gamma mass — the wall's earned range. Consumes exposures already derived upstream; reads no vendor leaf itself.",
    ),
    Row(
        file='terrain_engine.py', derivation='qualify_pin_candidate', disposition='DERIVED',
        producer_refs=('terrain_engine.py:compute_terrain', 'math_probabilities.py:compute_pin_score'),
        justification='RC-292 operator disposition: pin_candidate is the absolute-gamma strike published as a candidate pin ONLY after regime (net long gamma at spot), proximity (<=0.5% of spot, study_pin_residence_v1 cut), DTE (front expiry <=1 day, same study), liquidity (committed pin-score thresholds above negligible) and completeness (RC-413 magnitude bundle present) qualification; every gate fail-closed, absence ships with its blocker names.',
    ),
    Row(
        file='terrain_engine.py', derivation='wall_geometry_state', disposition='DERIVED',
        producer_refs=('server.py:get_terrain', 'terrain_engine.py:compute_terrain'),
        justification='RC-130: answers whether a wall is in the configuration its support/resistance label claims (contains / breached / unknown) from spot and the wall strike; the UI renders NO behavioural claim without a positive state.',
    ),
)
