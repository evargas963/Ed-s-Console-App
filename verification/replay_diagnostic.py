"""
Phase 5 — replay over stored snapshots (honest as-of via as_of_ts_utc).

Uses multi_horizon_decision.build_multi_horizon_bundle with a predictive stub built
only from empirical triplets (None when withheld), matching live missingness semantics.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from features.fusion_model_input import FusionModelInputError, similar_setup_filters_from_db_snapshot_row
from multi_horizon_decision import (
    WAIT_REASON_INSUFFICIENT_VALID_HORIZONS,
    WAIT_REASON_POOLED_FLAT,
    build_multi_horizon_bundle,
)
from prediction_engine import _literal_empirical_horizon, _tri_probs

from timeframe_config import CANONICAL_TIMEFRAME
from verification.similar_set_trace import PRODUCT_EMPIRICAL, full_similar_and_empirical_trace
from verification.threshold_stress import threshold_stress_on_similar


def _pred_from_similar(similar: list) -> Any:
    """Build SimpleNamespace like PredictiveCard fields for product horizons."""
    lit = {hz: _literal_empirical_horizon(similar, col, br) for hz, col, br in PRODUCT_EMPIRICAL}
    u1, d1, f1 = _tri_probs(lit["1c"][0])
    u5, d5, f5 = _tri_probs(lit["5c"][0])
    u15, d15, f15 = _tri_probs(lit["15c"][0])
    u60, d60, f60 = _tri_probs(lit["60c"][0])
    return SimpleNamespace(
        up_prob_1c=u1,
        down_prob_1c=d1,
        flat_prob_1c=f1,
        up_prob_5c=u5,
        down_prob_5c=d5,
        flat_prob_5c=f5,
        up_prob_15c=u15,
        down_prob_15c=d15,
        flat_prob_15c=f15,
        up_prob_60c=u60,
        down_prob_60c=d60,
        flat_prob_60c=f60,
        avg_3c_pts=0.8,
        avg_5c_pts=1.0,
        avg_15c_pts=2.0,
        avg_60c_pts=4.0,
    )


def _default_inp(row: dict) -> Any:
    zl = row.get("nearest_below_val") or row.get("nearest_below")
    zh = row.get("nearest_above_val") or row.get("nearest_above")
    return SimpleNamespace(
        spot=row.get("spot"),
        mins_to_close=float(row.get("mins_to_close", 180) or 180),
        nearest_below_val=float(zl) if zl is not None else 441.3,
        nearest_above_val=float(zh) if zh is not None else 441.8,
    )


def _default_canonical():
    return SimpleNamespace(
        direction="up",
        probability_up=0.55,
        probability_down=0.25,
        probability_flat=0.20,
        confidence="medium",
        provenance="replay_diag_stub",
    )


def _default_call():
    return SimpleNamespace(
        signal="long",
        entry=441.5,
        stop=440.9,
        target=442.8,
        target2=444.0,
        call_state="WATCH",
    )


def replay_summary(
    db,
    *,
    tickers: tuple[str, ...] = ("SPY", "QQQ"),
    timeframe: str = CANONICAL_TIMEFRAME,
    limit_bars: int = 200,
    stride: int = 1,
    as_of_honest: bool = True,
) -> dict[str, Any]:
    """
    Walk recent snapshots per ticker; for each bar run similar+empirical trace and MH bundle.

    as_of_honest: pass ts_utc to get_similar_setups (strictly prior rows only).
    """
    out: dict[str, Any] = {"tickers": {}, "meta": {"limit_bars": limit_bars, "stride": stride, "as_of_honest": as_of_honest}}

    for tkr in tickers:
        tkr = tkr.upper().strip()
        rows = db.get_recent_snapshots(tkr, timeframe, n=limit_bars * stride + 50, filled_only=False)
        rows = list(reversed(rows))[-limit_bars * stride :]
        sampled = rows[::stride]
        if not sampled:
            out["tickers"][tkr] = {
                "error": "no snapshots for ticker/timeframe",
                "counts": {},
                "percent": {},
            }
            continue
        stats = {
            "n_slices": 0,
            "withheld_1c": 0,
            "withheld_5c": 0,
            "withheld_15c": 0,
            "withheld_60c": 0,
            "wait_no_confluence": 0,
            "final_wait": 0,
            "similar_sizes": [],
            "similarity_filter_skipped_invalid_mvp": 0,
        }
        slices: list[dict[str, Any]] = []

        for row in sampled:
            ts = row.get("ts_utc")
            try:
                _f = similar_setup_filters_from_db_snapshot_row(row)
            except FusionModelInputError:
                stats["similarity_filter_skipped_invalid_mvp"] += 1
                continue
            zone = _f["zone"]
            vwap_side = _f["vwap_side"]
            nad, nbd = _f["nearest_above_dist"], _f["nearest_below_dist"]
            as_of = float(ts) if as_of_honest and ts is not None else None

            trace = full_similar_and_empirical_trace(
                db,
                ticker=tkr,
                timeframe=timeframe,
                zone=zone,
                vwap_side=vwap_side,
                nearest_above_dist=nad,
                nearest_below_dist=nbd,
                as_of_ts_utc=as_of,
                include_similar=True,
            )
            similar = trace.get("similar") or []
            similar_sz = trace["narrowing"]["G_final_similar_list_size"]
            stats["similar_sizes"].append(similar_sz)
            eh = trace["empirical_horizons"]
            for k, st_key in (
                ("1c", "withheld_1c"),
                ("5c", "withheld_5c"),
                ("15c", "withheld_15c"),
                ("60c", "withheld_60c"),
            ):
                if eh.get(k, {}).get("status") == "WITHHELD":
                    stats[st_key] += 1

            pred = _pred_from_similar(similar)
            mh = build_multi_horizon_bundle(
                _default_inp(row),
                pred,
                _default_canonical(),
                _default_call(),
            )
            fd = mh.final_decision
            if str(fd.final_bias) == "WAIT" or not fd.final_tradeable:
                stats["final_wait"] += 1
            # Pooled-consensus WAIT classes (2026-06-11): insufficient evidence,
            # flat-dominant pool, or pooled evidence below the entry gate.
            _wr = str(fd.wait_reason or "")
            if _wr in (
                WAIT_REASON_INSUFFICIENT_VALID_HORIZONS,
                WAIT_REASON_POOLED_FLAT,
            ) or _wr.startswith("pooled stack evidence below entry gate"):
                stats["wait_no_confluence"] += 1

            stats["n_slices"] += 1
            if len(slices) < 5:
                slices.append(
                    {
                        "ts_utc": ts,
                        "similar_size": similar_sz,
                        "empirical": {k: eh[k]["status"] for k in eh},
                        "primary": fd.primary_horizon,
                        "final_bias": fd.final_bias,
                        "wait_reason": fd.wait_reason,
                    }
                )

        try:
            _last_f = similar_setup_filters_from_db_snapshot_row(sampled[-1]) if sampled else None
        except FusionModelInputError:
            _last_f = None
        if _last_f is not None:
            _lnad, _lnbd = _last_f["nearest_above_dist"], _last_f["nearest_below_dist"]
        else:
            _lnad = _lnbd = None
        n = max(1, stats["n_slices"])
        out["tickers"][tkr] = {
            "counts": stats,
            "percent": {
                "withheld_1c": round(100.0 * stats["withheld_1c"] / n, 2),
                "withheld_5c": round(100.0 * stats["withheld_5c"] / n, 2),
                "withheld_15c": round(100.0 * stats["withheld_15c"] / n, 2),
                "withheld_60c": round(100.0 * stats["withheld_60c"] / n, 2),
                "final_wait": round(100.0 * stats["final_wait"] / n, 2),
                "wait_no_confluence": round(
                    100.0 * stats["wait_no_confluence"] / n, 2
                ),
            },
            "sample_slices": slices,
            "avg_similar_size": round(sum(stats["similar_sizes"]) / n, 2) if stats["similar_sizes"] else 0,
            "threshold_stress_last_slice": (
                threshold_stress_on_similar(
                    (
                        full_similar_and_empirical_trace(
                            db,
                            ticker=tkr,
                            timeframe=timeframe,
                            zone=_last_f["zone"],
                            vwap_side=_last_f["vwap_side"],
                            nearest_above_dist=_lnad,
                            nearest_below_dist=_lnbd,
                            as_of_ts_utc=float(sampled[-1]["ts_utc"])
                            if as_of_honest
                            else None,
                            include_similar=True,
                        ).get("similar")
                        or []
                    )
                )
                if sampled and _last_f is not None
                else {}
            ),
        }

    return out
