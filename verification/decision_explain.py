"""Phase 4 — structured explainability from a /api/state MarketState dict."""
from __future__ import annotations

from typing import Any

from verification.horizon_health import horizon_health_from_state_horizon_bars


def explain_reason_ladder(ms_dict: dict) -> list[str]:
    """Human-orderable chain: empirical withhold → primary → WAIT."""
    ladder: list[str] = []
    hpb = ms_dict.get("horizon_prob_bars") or {}
    if isinstance(hpb, dict):
        for k in ("1m", "5m", "15m", "60m"):
            row = hpb.get(k)
            if isinstance(row, dict):
                u, d, f = row.get("up"), row.get("down"), row.get("flat")
                lc, mn = row.get("labeled_count"), row.get("min_samples_required")
                src = row.get("source") or ""
                if u is None and lc is not None and mn is not None:
                    ladder.append(
                        f"horizon {k}: triplet withheld — labeled_count={lc} min_required={mn} ({src})"
                    )
    mh = ms_dict.get("primary_horizon")
    if mh:
        ladder.append(f"selected primary_horizon (display)={mh!r}")
    fin = str(ms_dict.get("final_bias") or "")
    ft = ms_dict.get("final_tradeable")
    wr = ms_dict.get("wait_reason") or ""
    if fin == "WAIT" or not ft:
        ladder.append(f"final bias WAIT (final_tradeable={ft!r}) wait_reason={wr!r}")
    if not ladder:
        ladder.append("no explicit withhold reasons parsed (payload may be complete)")
    return ladder


def explain_market_state_dict(ms_dict: dict) -> dict[str, Any]:
    if not isinstance(ms_dict, dict):
        return {"error": "expected dict"}

    pred_health = horizon_health_from_state_horizon_bars(ms_dict)

    mh_block = {
        "primary_horizon": ms_dict.get("primary_horizon"),
        "trade_mode": ms_dict.get("trade_mode"),
        "alignment_state": ms_dict.get("alignment_state_display") or ms_dict.get("alignment_state"),
        "contradiction_state": ms_dict.get("contradiction_state"),
        "final_bias": ms_dict.get("final_bias"),
        "final_tradeable": ms_dict.get("final_tradeable"),
        "wait_reason": ms_dict.get("wait_reason"),
        "entry_state": ms_dict.get("entry_state"),
        "mhap_rows": ms_dict.get("mhap_rows"),
    }

    stack = {
        "xgb_available": ms_dict.get("xgb_available"),
        "lstm_available": ms_dict.get("lstm_available"),
        "transformer_available": ms_dict.get("transformer_available"),
        "fusion_available": ms_dict.get("fusion_available"),
        "canonical_provenance": ms_dict.get("canonical_provenance"),
    }

    predictive = {
        "samples_used": ms_dict.get("samples_used"),
        "match_tier": ms_dict.get("match_tier"),
        "horizon_prob_bars_summary": pred_health,
        "forward_provenance": ms_dict.get("forward_provenance"),
    }

    withheld = [
        hz
        for hz, h in (pred_health.get("horizons") or {}).items()
        if isinstance(h, dict) and h.get("status") == "WITHHELD"
    ]

    return {
        "model_stack_health": stack,
        "predictive_card_health": {
            **predictive,
            "withheld_horizons": withheld,
        },
        "multi_horizon_decision_health": mh_block,
        "reason_ladder": explain_reason_ladder(ms_dict),
    }
