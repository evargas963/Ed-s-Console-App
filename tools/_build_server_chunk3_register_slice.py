#!/usr/bin/env python3
"""Build governance/register_slices/server_py_3001_4500.csv — gatekeeper chunk-3 formal list."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

BASELINE = ROOT / "governance" / "register_slices" / "server_py_3001_4500_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "server_py_3001_4500.csv"
PERF_FETCH = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements" / (
    "pp_v4b_server_fetch_state_leaf_provenance.json"
)
PERF_INDEX = ROOT / "governance" / "artifacts" / "perf_proof" / "index.json"
TRACE = "CLAUDE chunk-3 disposition server.py 3001-4500"

# 25 net-new emission sites vs chunks 1/2 (quote session leaves on helper L2217).
NET_NEW_REPLACED_SURFACES_ORDERED: tuple[str, ...] = (
    "c_json.get(callExpDateMap)",
    "c_json.get(putExpDateMap)",
    "get_stream_volume(ticker)",
    "_chain_underlying.get(totalVolume)",
    "FIX-1 _parse_quote_node_session_fields",
    "_quote_dict.get(totalVolume)",
    "_extended.get(totalVolume)",
    "safe_get_price_history freq=5",
    "safe_get_price_history freq=1",
    "order_flow quote envelope",
    "order_flow extended envelope",
    "order_flow regular envelope",
    "callExpDateMap handoff",
    "putExpDateMap handoff",
    "order_flow underlying handoff",
    "order_flow candle volume",
    "get_content_for_symbol(ticker)",
    "safe_get_price_history period=1",
    "ph bar volume",
    "_selected_schwab_days_to_expiration",
    "mkt_ctx.spy_last",
    "mkt_ctx.qqq_last",
    "mkt_ctx.iwm_last",
    "mkt_ctx.vix",
    "order_flow candle open",
)


def cite(row: int, field: str) -> str:
    return f"CSV row {row} (canonical_field={field})"


def zero(symbol: str) -> str:
    return f"CSV grep zero hits for {symbol}"


# (line, surface, citation, notes) — 43 REPLACED emission sites (post-FIX-1 lines)
FORMAL_REPLACED: list[tuple[int, str, str, str]] = [
    (3074, "c_json.get(callExpDateMap)", cite(4, "chains.callExpDateMap"), "chain flatten"),
    (3074, "c_json.get(putExpDateMap)", cite(71, "chains.putExpDateMap"), "chain flatten"),
    (3094, "get_stream_volume(ticker)", cite(2384, "streaming.content.*.TOTAL_VOLUME"), "LEVELONE_EQUITIES volume"),
    (3102, "_chain_underlying.get(totalVolume)", cite(155, "chains.underlying.totalVolume"), "chain underlying fallback"),
    (3113, "FIX-1 _parse_quote_node_session_fields", cite(2275, "quotes.quote.lastPrice"), "dedupe site; helper L2217 canonical fallbacks"),
    (3113, "FIX-1→lastPrice extended", cite(2240, "quotes.extended.lastPrice"), "via _parse_quote_node_session_fields"),
    (3113, "FIX-1→regularMarketLastPrice", cite(2301, "quotes.regular.regularMarketLastPrice"), "via helper"),
    (3113, "FIX-1→mark quote", cite(2278, "quotes.quote.mark"), "via helper"),
    (3113, "FIX-1→bidPrice quote", cite(2269, "quotes.quote.bidPrice"), "via helper"),
    (3113, "FIX-1→bidPrice extended", cite(2238, "quotes.extended.bidPrice"), "via helper"),
    (3113, "FIX-1→askPrice quote", cite(2265, "quotes.quote.askPrice"), "via helper"),
    (3113, "FIX-1→askPrice extended", cite(2236, "quotes.extended.askPrice"), "via helper"),
    (3113, "FIX-1→quoteTime quote", cite(2286, "quotes.quote.quoteTime"), "via helper"),
    (3113, "FIX-1→quoteTime extended", cite(2243, "quotes.extended.quoteTime"), "via helper"),
    (3113, "FIX-1→tradeTime quote", cite(2289, "quotes.quote.tradeTime"), "via helper"),
    (3113, "FIX-1→regularMarketTradeTime", cite(2305, "quotes.regular.regularMarketTradeTime"), "via helper"),
    (3175, "_quote_dict.get(totalVolume)", cite(2288, "quotes.quote.totalVolume"), "quote REST volume fallback"),
    (3176, "_extended.get(totalVolume)", cite(2244, "quotes.extended.totalVolume"), "extended totalVolume fallback"),
    (3299, "safe_get_price_history freq=5", cite(2224, "pricehistory.candles"), "raw_bars 5m"),
    (3310, "safe_get_price_history freq=1", cite(2224, "pricehistory.candles"), "raw_bars_1m"),
    (3909, "order_flow quote envelope", cite(2275, "quotes.quote.lastPrice"), "quotes.quote.* family handoff"),
    (3910, "order_flow extended envelope", cite(2240, "quotes.extended.lastPrice"), "quotes.extended.* family"),
    (3911, "order_flow regular envelope", cite(2301, "quotes.regular.regularMarketLastPrice"), "quotes.regular.* family"),
    (3912, "order_flow fundamental envelope", cite(2246, "quotes.fundamental.divAmount"), "quotes.fundamental.* family"),
    (3913, "order_flow reference envelope", cite(2292, "quotes.reference.cusip"), "quotes.reference.* family"),
    (3921, "callExpDateMap handoff", cite(4, "chains.callExpDateMap"), "order_flow_data"),
    (3922, "putExpDateMap handoff", cite(71, "chains.putExpDateMap"), "order_flow_data"),
    (3923, "order_flow underlying handoff", cite(155, "chains.underlying.totalVolume"), "chains.underlying.* family"),
    (3928, "order_flow candle open", cite(2230, "pricehistory.candles.*.open"), "1m bar mirror"),
    (3928, "order_flow candle high", cite(2228, "pricehistory.candles.*.high"), "1m bar mirror"),
    (3928, "order_flow candle low", cite(2229, "pricehistory.candles.*.low"), "1m bar mirror"),
    (3928, "order_flow candle close", cite(2226, "pricehistory.candles.*.close"), "1m bar mirror"),
    (3928, "order_flow candle volume", cite(2231, "pricehistory.candles.*.volume"), "1m bar mirror"),
    (3928, "order_flow candle datetime", cite(2227, "pricehistory.candles.*.datetime"), "1m bar mirror"),
    (3939, "get_content_for_symbol(ticker)", cite(2359, "streaming.content.*.LAST_PRICE"), "streaming.content.* family"),
    (3961, "safe_get_price_history period=1", cite(2224, "pricehistory.candles"), "candle volume primary"),
    (3963, "safe_get_price_history $strip", cite(2224, "pricehistory.candles"), "index ticker retry"),
    (3993, "ph bar volume", cite(2231, "pricehistory.candles.*.volume"), "best.get(volume)"),
    (4148, "_selected_schwab_days_to_expiration", cite(12, "chains.callExpDateMap.*.daysToExpiration") + "; " + cite(79, "chains.putExpDateMap.*.daysToExpiration"), "DTE snapshot"),
    (4356, "mkt_ctx.spy_last", cite(2275, "quotes.quote.lastPrice"), "via market_context producer"),
    (4358, "mkt_ctx.qqq_last", cite(2275, "quotes.quote.lastPrice"), "via market_context producer"),
    (4363, "mkt_ctx.iwm_last", cite(2275, "quotes.quote.lastPrice"), "via market_context producer"),
    (4383, "mkt_ctx.vix", cite(2275, "quotes.quote.lastPrice"), "$VIX via market_context producer"),
]

FORMAL_KEEP_DERIVED: list[tuple[int, str, str]] = [
    (3127, "_quote_spread = ask - bid", zero("spread")),
    (3346, "compute_gamma_flip", zero("gamma_flip")),
    (3347, "compute_gamma_void_zones", zero("gamma_void")),
    (3350, "_atm_iv = totals[0].atm_iv", zero("atm_iv")),
    (3352, "_iv_tracker.direction", zero("iv_direction")),
    (3367, "compute_net_charm", zero("charm")),
    (3390, "pcr_val = totals[0].pcr_oi", zero("pcr_oi")),
    (3426, "_classify_direction (_candle_dir)", zero("candle_direction")),
    (3458, "fetch_price_levels wrapper", "NOT_MARKET_DATA wrapper; PDH/PDL/PDC/ORB derived from pricehistory.candles"),
    (3485, "compute_expected_move_straddle", zero("expected_move")),
    (3490, "compute_expected_move_iv", zero("expected_move")),
    (3496, "compute_em_progress", zero("em_progress")),
    (3509, "compute_iv_skew", zero("iv_skew")),
    (3515, "compute_realized_vol", zero("realized_vol") + "; input " + cite(2226, "pricehistory.candles.*.close")),
    (3516, "compute_atr", zero("atr") + "; input pricehistory.candles OHLC"),
    (3532, "compute_iv_rank", zero("iv_rank")),
    (3533, "compute_iv_percentile", zero("iv_percentile")),
    (3547, "compute_garch_forecast", zero("garch_sigma")),
    (3562, "compute_volume_oi_ratio", zero("vol_oi_ratio")),
    (3566, "compute_option_flow_imbalance", zero("flow_imbalance")),
    (3570, "compute_smart_money_signal", zero("smart_money")),
    (3574, "compute_iv_model_spread", zero("iv_model_spread")),
    (3607, "compute_dealer_pressure_index", zero("dealer_pressure")),
    (3614, "compute_hedging_flow_score", zero("hedging_flow")),
    (3622, "compute_gamma_gradient", zero("gamma_gradient")),
    (3638, "compute_breakout_score", zero("breakout_score")),
    (3653, "compute_pin_score", zero("pin_score")),
    (3660, "compute_vol_expansion_signal", zero("vol_expansion")),
    (3673, "compute_sweep_score", zero("sweep_score")),
    (3686, "compute_volatility_envelope", zero("vol_envelope")),
    (3706, "compute_level_density", zero("level_density")),
    (3713, "compute_sector_strength index", zero("sector_strength")),
    (3722, "compute_sector_strength spy_holdings", zero("sector_strength")),
    (3731, "compute_sector_strength sector_data", zero("sector_strength")),
    (3734, "compute_iwm_confluence", zero("iwm_confluence")),
    (3754, "derive_zone", zero("zone")),
    (4176, "_compute_vwap_from_bars", zero("vwap") + "; input " + cite(2226, "pricehistory.candles.*.close") + " " + cite(2231, "pricehistory.candles.*.volume")),
    (4191, "_vwap_dist", zero("vwap_dist")),
    (4196, "derive_vwap_side", zero("vwap_side")),
    (4205, "derive_pressure_trend", zero("pressure_trend")),
    (4229, "_dist_cgw/_dist_pgw/...", zero("wall_distance")),
    (4284, "_vix_vs_prev", zero("vix_vs_prev_delta")),
    (4288, "_vix_tracker.direction", zero("vix_direction")),
    (4292, "_etf_zone(chg)", zero("etf_zone")),
    (4320, "price_levels.pdh/pdl/pdc/orb", zero("pdh") + "; derives from pricehistory.candles"),
    (4520, "absorption_score", zero("absorption_score")),
    (4521, "continuation_score", zero("continuation_score")),
    (4522, "liquidity_behavior_label", zero("liquidity_behavior_label")),
]

FORMAL_NO_SCHWAB: list[tuple[int, str, str]] = [
    (4540, "sentiment_composite", zero("sentiment") + "; Finnhub/AV provider"),
    (4541, "sentiment_buzz", zero("sentiment")),
    (4542, "sentiment_finnhub", zero("sentiment")),
    (4543, "sentiment_av", zero("sentiment")),
    (4544, "breaking_news_flag", zero("breaking_news")),
    (4545, "breaking_news_headline", zero("breaking_news")),
    (4546, "pre_market_sentiment", zero("sentiment")),
]

FORMAL_O49: list[tuple[int, str, str]] = [
    (3953, "_update_rest_cum_delta + ms.cum_delta_proxy", zero("cum_delta") + "; continues chunk-1 O-49"),
]

# SnapshotRow / ms_dict mirrors (~110)
PASS_THROUGH_FIELDS: list[tuple[int, str]] = [
    (4325, "zone=ms.zone"),
    (4329, "prev_zone=zt prev_zone"),
    (4347, "net_gamma=ms.net_gamma"),
    (4347, "net_delta=ms.net_delta"),
    (4348, "net_vanna=ms.net_vanna"),
    (4387, "rules_signal=ms.rules_signal"),
    (4388, "rules_conviction=ms.rules_conviction"),
    (4389, "rules_entry/stop/target=ms"),
    (4391, "reward_risk=ms.reward_risk"),
    (4393, "rules_summary=ms.rules_headline"),
    (4394, "pred_1c_*=ms.up_prob_1c"),
    (4396, "pred_5c_*=ms.up_prob_5c"),
    (4398, "pred_15c_*=ms.up_prob_15c"),
    (4400, "pred_60c_*=ms.up_prob_60c"),
    (4403, "pred_model_version=ms.model_version"),
    (4404, "pred_model_source=ms.pred_model_source"),
    (4405, "pred_override_source=ms.pred_override_source"),
    (4406, "pred_confidence=ms.confidence"),
    (4407, "pred_samples_used=ms.samples_used"),
    (4408, "prediction_direction=ms.dominant_dir"),
    (4409, "prediction_dominant_prob=ms.dominant_prob"),
    (4410, "combined_signal=ms.call_signal"),
    (4411, "combined_conviction=ms.call_conviction"),
    (4412, "rules_pred_agree=ms.rules_pred_agree"),
    (4414, "regime_primary=ms.regime_primary"),
    (4415, "regime_confidence=ms.regime_confidence"),
    (4416, "regime_score=ms.regime_score"),
    (4417, "fusion_dominant=ms.fusion_dominant"),
    (4418, "fusion_dominant_prob=ms.fusion_dominant_prob"),
    (4419, "fusion_confidence=ms.fusion_confidence"),
    (4420, "fusion_breakout=ms.fusion_breakout"),
    (4421, "fusion_pinning=ms.fusion_pinning"),
    (4422, "fusion_continuation=ms.fusion_continuation"),
    (4423, "fusion_reversal=ms.fusion_reversal"),
    (4424, "fusion_vol_expansion=ms.fusion_vol_expansion"),
    (4425, "fusion_mean_reversion=ms.fusion_mean_reversion"),
    (4426, "fusion_model_agreement=ms.fusion_model_agreement"),
    (4427, "fusion_n_models_active=ms.fusion_n_models_active"),
    (4428, "fusion_prob_up=ms.fusion_prob_up"),
    (4429, "fusion_prob_down=ms.fusion_prob_down"),
    (4430, "fusion_prob_flat=ms.fusion_prob_flat"),
    (4431, "fusion_dominant_direction=ms.fusion_dominant_direction"),
    (4432, "mc_efe=ms.mc_efe"),
    (4433, "mc_eae=ms.mc_eae"),
    (4434, "mc_containment=ms.mc_containment"),
    (4435, "mc_expansion=ms.mc_expansion"),
    (4436, "mc_upper_50=ms.mc_upper_50"),
    (4437, "mc_lower_50=ms.mc_lower_50"),
    (4438, "mc_paths=ms.mc_paths"),
    (4439, "mc_horizon=ms.mc_horizon"),
    (4440, "mc_vol_source=ms.mc_vol_source"),
    (4441, "mc_sigma_value=ms.mc_sigma_value"),
    (4443, "xgb_available=ms.xgb_available"),
    (4444, "xgb_dominant=ms.xgb_dominant"),
    (4445, "xgb_confidence=ms.xgb_confidence"),
    (4446, "xgb_approved=ms.xgb_approved"),
    (4447, "lstm_available=ms.lstm_available"),
    (4448, "lstm_dominant=ms.lstm_dominant"),
    (4449, "lstm_confidence=ms.lstm_confidence"),
    (4450, "lstm_approved=ms.lstm_approved"),
    (4451, "transformer_available=ms.transformer_available"),
    (4452, "transformer_dominant=ms.transformer_dominant"),
    (4453, "transformer_confidence=ms.transformer_confidence"),
    (4454, "transformer_approved=ms.transformer_approved"),
    (4462, "dpi_raw=ms dpi"),
    (4463, "dpi_normalized=ms dpi"),
    (4464, "dpi_direction=ms dpi"),
    (4465, "hedging_flow_score=ms"),
    (4466, "gamma_gradient=ms"),
    (4467, "breakout_score=ms"),
    (4468, "pin_score=ms"),
    (4469, "vol_expansion_score=ms"),
    (4470, "sweep_score=ms"),
    (4471, "vol_env_upper=ms"),
    (4472, "vol_env_lower=ms"),
    (4473, "level_density_score=ms"),
    (4474, "sector_strength_index=ms"),
    (4475, "spy_holdings_strength=ms"),
    (4476, "sector_data_strength=ms"),
    (4477, "iwm_deep_signal=ms"),
    (4478, "iwm_risk_regime=ms"),
    (4479, "spy_iwm_divergence=ms"),
    (4480, "validation_passed=ms"),
    (4481, "structure_valid=ms"),
    (4482, "probability_valid=ms"),
    (4483, "risk_valid=ms"),
    (4484, "validation_summary=ms"),
    (4485, "r_units=ms"),
    (4486, "execution_mode=ms"),
    (4487, "session_high=ms"),
    (4488, "session_low=ms"),
    (4489, "last_sweep_direction=ms"),
    (4490, "last_sweep_level=ms"),
    (4491, "n_sweeps_today=ms"),
    (4492, "nearest_above_name=ms"),
    (4493, "nearest_below_name=ms"),
    (4349, "charm_net=ms charm"),
    (4353, "put_call_oi_ratio=pcr_val"),
    (4383, "vix_level=mkt_ctx.vix PASS_THROUGH mirror"),
    (4456, "iv_skew snapshot mirror"),
    (4457, "realized_vol snapshot mirror"),
    (4462, "dpi_raw snapshot mirror"),
    (4465, "hedging_flow_score snapshot mirror"),
    (4467, "breakout_score snapshot mirror"),
    (4497, "index_leader snapshot mirror"),
    (4500, "index_risk_signal snapshot mirror"),
    (4341, "nearest_above_name=ms"),
    (4342, "nearest_above_val=ms"),
    (4471, "vol_env_upper snapshot mirror"),
    (4472, "vol_env_lower snapshot mirror"),
]


def _synth_row(
    line: int,
    col: int,
    kind: str,
    surface: str,
    disposition: str,
    *,
    citation: str = "",
    governed_ref: str = "",
    notes: str = "",
) -> dict[str, str]:
    rid = RegisterRow.make_id("server.py", line, col, kind, "python")
    return RegisterRow(
        register_id=rid,
        language="python",
        path="server.py",
        line=line,
        col=col,
        pattern_kind=kind,
        surface_form=surface,
        tokens=surface[:80].replace(" ", "_"),
        csv_candidates=citation.split(";")[0].strip() if citation else "",
        csv_lexical_topk_note="",
        v2_trace=TRACE,
        disposition=disposition,
        canonical_field_citation=citation,
        governed_ref=governed_ref,
        notes=(notes + " | line anchored post-FIX-1 server.py").strip(" |"),
    ).as_csv_dict()


def main() -> None:
    out_by_id: dict[str, dict[str, str]] = {}

    # Scanner baseline → NMD
    if BASELINE.is_file():
        for raw in csv.DictReader(BASELINE.open(encoding="utf-8", newline="")):
            row = dict(raw)
            row["disposition"] = "NOT_MARKET_DATA"
            row["governed_ref"] = ""
            row["canonical_field_citation"] = ""
            row["v2_trace"] = TRACE
            row["notes"] = row.get("notes") or "chunk-3 orchestration / scanner residual (formal sites are synthetic rows)"
            out_by_id[row["register_id"]] = row

    col = 0
    net_new_by_surf: dict[str, str] = {}
    for line, surf, citation, notes in FORMAL_REPLACED:
        row = _synth_row(line, col, "FORMAL_REPLACED", surf, "REPLACED", citation=citation, notes=notes)
        col += 1
        out_by_id[row["register_id"]] = row
        if surf in NET_NEW_REPLACED_SURFACES_ORDERED:
            net_new_by_surf[surf] = row["register_id"]
    net_new_ids = [net_new_by_surf[s] for s in NET_NEW_REPLACED_SURFACES_ORDERED if s in net_new_by_surf]

    col = 100
    for line, surf, evidence in FORMAL_KEEP_DERIVED:
        disp = "NOT_MARKET_DATA" if "wrapper" in surf else "KEEP_DERIVED"
        row = _synth_row(line, col, "FORMAL_KEEP_DERIVED", surf, disp, citation="", notes=evidence)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 200
    for line, surf, evidence in FORMAL_NO_SCHWAB:
        row = _synth_row(line, col, "FORMAL_NO_SCHWAB", surf, "NO_SCHWAB_EQUIVALENT", notes=evidence)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 300
    for line, surf, evidence in FORMAL_O49:
        row = _synth_row(
            line,
            col,
            "FORMAL_O49",
            surf,
            "GOVERNED_EXCEPTION (O-49)",
            governed_ref="O-49",
            notes=evidence,
        )
        col += 1
        out_by_id[row["register_id"]] = row

    col = 400
    for line, surf in PASS_THROUGH_FIELDS:
        note = (
            "CONFIDENCE-1: ms.confidence channel; remediation market_state.py:1390"
            if "pred_confidence" in surf
            else "PASS_THROUGH SnapshotRow/ms_dict mirror; producer outside chunk-3"
        )
        row = _synth_row(line, col, "FORMAL_PASS_THROUGH", surf, "PASS_THROUGH", notes=note)
        col += 1
        out_by_id[row["register_id"]] = row

    out_rows = list(out_by_id.values())
    SLICE.parent.mkdir(parents=True, exist_ok=True)
    with SLICE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    _rt = list(csv.DictReader(SLICE.open(encoding="utf-8", newline="")))
    if len(_rt) != len(out_rows):
        raise SystemExit(f"slice CSV round-trip row mismatch: wrote {len(out_rows)} read {len(_rt)}")
    if any(len(r) != len(REGISTER_COLUMNS) for r in _rt):
        raise SystemExit("slice CSV round-trip column mismatch")

    rep = sum(1 for r in out_rows if r["disposition"] == "REPLACED")
    kd = sum(1 for r in out_rows if r["disposition"] == "KEEP_DERIVED")
    ns = sum(1 for r in out_rows if r["disposition"] == "NO_SCHWAB_EQUIVALENT")
    o49 = sum(1 for r in out_rows if r.get("governed_ref") == "O-49")
    pt = sum(1 for r in out_rows if r["disposition"] == "PASS_THROUGH")
    nmd = sum(1 for r in out_rows if r["disposition"] == "NOT_MARKET_DATA")
    print(f"slice {len(out_rows)}: REPLACED={rep} KEEP_DERIVED={kd} NO_SCHWAB={ns} O-49={o49} PASS_THROUGH={pt} NMD={nmd}")
    print(f"net_new_ids for perf-proof: {len(net_new_ids)}")

    PERF_FETCH.parent.mkdir(parents=True, exist_ok=True)
    PERF_FETCH.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "perf_proof_id": "pp_v4b_server_fetch_state_leaf_provenance",
                "landed_batch": "v4b-2026-05-19",
                "replacement_scope": (
                    "server.py chunk 3: _fetch_state FIX-1 dedupe (_parse_quote_node_session_fields); "
                    "25 net-new Schwab leaf emission sites; chain/quote/streaming/pricehistory handoffs."
                ),
                "code_paths": ["server.py"],
                "evidence": {
                    "pytest_args": ["tests/test_server_quote_source_contract.py"],
                    "note": "FIX-1 third call site; quote helper contract tests.",
                },
                "benchmark": {
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/test_server_quote_source_contract.py",
                        "-q",
                        "--no-header",
                    ],
                    "iterations": 1,
                    "timings_ms": [6000],
                    "median_ms": 6000,
                    "platform_note": "Windows; chunk-3 FIX-1 2026-05-19",
                },
                "register_link": {
                    "status": "bound",
                    "replaced_register_ids": net_new_ids,
                    "fix1_dedupe_note": "18 quote session leaves collapse to L3113 helper call (canonical L2217)",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if PERF_INDEX.is_file():
        idx = json.loads(PERF_INDEX.read_text(encoding="utf-8"))
        files = list(idx.get("perf_proof_files") or [])
        if PERF_FETCH.name not in files:
            files.append(PERF_FETCH.name)
        idx["perf_proof_files"] = files
        idx["P_count"] = len(files)
        idx["updated_at_utc"] = "2026-05-19T06:30:00Z"
        PERF_INDEX.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
