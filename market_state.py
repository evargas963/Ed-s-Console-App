# market_state.py
"""
MarketState — single source of truth for the Ed Console UI.

Built once per refresh from raw inputs (quote, chain, greeks, signals).
Every card reads from this object. No card computes its own version of
any value. This eliminates discrepancies between cards.

Build order (dependencies flow downward):
  1. Raw inputs    — spot, bid, ask, contracts, walls, totals
  2. Regime        — zone, bias, pin_strength (net-GEX peak concentration, not terrain pin lead %), net_delta
  3. Bias gate     — bias_resolved (exact match only)
  4. OE strike     — rec_strike, rec_side
  5. Signals       — entry, stop, target, R/R (via signals engine)
  6. OE gate pills — liq_ok, ratio, vol_oi (from strike scoring)
  7. Entry zone    — entry_zone_lo/hi from signals entry ± 0.25
  8. Display       — colors, labels, formatted strings
"""
from __future__ import annotations


from math_probabilities import OE_SPREAD_TIGHT_MAX
from numeric_contract import float_finite_or_none







# is_pin_zone() lives in math_exposure.py — centralized










# ─────────────────────────────────────────────────────────────────────────────
# OE RECOMMENDATION — lives here so market_state has no circular imports
# Direction driven exclusively by The Call signal (long/short/wait)
# ─────────────────────────────────────────────────────────────────────────────
def _f_ms(v):
    """Safe float conversion (finite-only)."""
    return float_finite_or_none(v)




def _oe_chain_row_snapshot(ct: dict | None) -> dict | None:
    """Normalized Schwab option row fields preserved for audit/API/A2 proof."""
    if not ct:
        return None
    keys = (
        "symbol",
        "putCall",
        "strikePrice",
        "daysToExpiration",
        "expirationDate",
        "expirationType",
        "settlementType",
        "exerciseType",
        "lastTradingDay",
        "bid",
        "ask",
        "mark",
        "last",
        "openPrice",
        "highPrice",
        "lowPrice",
        "closePrice",
        # RC-388: vendor-computed per-contract breakeven (chains.*.breakEven,
        # first seen 2026-08-15). Preserved so A2 can serve the Schwab value
        # instead of its strike +/- mid approximation.
        "breakEven",
        "bidSize",
        "askSize",
        "bidAskSize",
        "lastSize",
        "totalVolume",
        "openInterest",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "volatility",
        "theoreticalVolatility",
        "theoreticalOptionValue",
        "quoteTimeInLong",
        "tradeTimeInLong",
        "multiplier",
        "extrinsicValue",
        "timeValue",
        "intrinsicValue",
        "inTheMoney",
        "nonStandard",
        "mini",
        "pennyPilot",
        "deliverableNote",
    )
    return {k: ct.get(k) for k in keys}


def _oe_first_contract_row(contracts: list, strike: float, side: str) -> dict | None:
    side_up = str(side).upper().strip()
    for ct in contracts:
        if (ct.get("putCall") or "").upper().strip() != side_up:
            continue
        sp = _f_ms(ct.get("strikePrice"))
        if sp is None or abs(float(sp) - float(strike)) >= 0.01:
            continue
        return ct
    return None


def _oe_composite_strike_row(
    *,
    contracts: list,
    spot: float,
    k: float,
    side: str,
    walls: list | None,
) -> tuple[float | None, list[str], dict]:
    """
    Single-strike OE audit row + composite score (same scoring as selection loop).
    Returns (score or None if unscorable, reasons, audit dict).
    """
    from math_exposure import score_option_expression

    row = _oe_first_contract_row(contracts, k, side)
    snap = _oe_chain_row_snapshot(row)
    oe = score_option_expression(contracts, spot, k, side, walls=walls)
    if oe is None:
        return None, [], {
            "strike": float(k),
            "side": side,
            "scored": False,
            "in_selection_pool": False,
            "chain_row": snap,
            "note": "score_option_expression returned None (missing strike/Greeks row?)",
        }

    score = float(oe.total_score_after_walls)
    reasons: list[str] = []

    if oe.liq_gate:
        reasons.append(f"Tight spread (${oe.spread:.2f} ≤ {OE_SPREAD_TIGHT_MAX})")
    elif oe.spread is not None:
        reasons.append(f"Wide spread (${oe.spread:.2f}) — partial liquidity score only")
    if oe.gamma_is_max:
        reasons.append("Max gamma strike")
    if (oe.wall_score_component or 0) > 0:
        reasons.append(
            f"Walls +{oe.wall_score_component:.3f} "
            f"(prox {oe.wall_proximity_component:.3f}, bias {oe.wall_bias_component:.3f})"
        )

    audit = {
        "strike": float(k),
        "side": side,
        "scored": True,
        "composite_score": round(score, 4),
        "total_score_before_walls": oe.total_score_before_walls,
        "total_score_after_walls": oe.total_score_after_walls,
        "wall_proximity_component": oe.wall_proximity_component,
        "wall_bias_component": oe.wall_bias_component,
        "wall_score_component": oe.wall_score_component,
        "wall_contribution_detail": oe.wall_contribution_detail,
        "reasons": reasons,
        "spread": oe.spread,
        "spread_source": oe.spread_source,
        "liq_gate_pass": oe.liq_gate,
        "spread_filter_pass": bool(oe.liq_gate),
        "delta_gamma_ratio": oe.delta_gamma_ratio,
        "vol_oi_ratio": oe.vol_oi_ratio,
        "volume": oe.volume,
        "open_interest": oe.open_interest,
        "gamma": oe.gamma,
        "delta": oe.delta,
        "chain_row": snap,
    }
    return score, reasons, audit


def recommend_option_expression(
    *,
    contracts: list,
    spot: float,
    call_signal: str | None,
    walls: list | None = None,
    selected_expiry: str | None = None,
) -> tuple[str, list[str], dict]:
    """
    Recommend CALL or PUT strike driven by The Call signal direction.
      long  → CALL (ATM or 1-strike ITM, best score via score_option_expression)
      short → PUT  (ATM or 1-strike ITM, best score)
      wait  → NO TRADE

    Third return value is an audit dict (chain rows, spread filter, why winner won).
    Uses score_option_expression() (math_probabilities via math_exposure) everywhere.
    """
    sig = (call_signal or "").strip().lower()
    base_proof: dict = {
        "code_path": "market_state.recommend_option_expression → math_probabilities.score_option_expression",
        "selected_expiry": selected_expiry,
        "spot": spot,
        "liquidity_spread_filter": {
            "max_spread_dollars": OE_SPREAD_TIGHT_MAX,
            "liq_gate": f"bid/ask spread ≤ {OE_SPREAD_TIGHT_MAX} → +5 liquidity points; else partial credit only",
        },
        "fallback_policy": (
            "NO TRADE if signal is wait, no contracts for side/expiry slice, or every candidate fails scoring. "
            "If quotes are missing so score_option_expression returns None for all strikes → NO TRADE. "
            "Otherwise highest composite score wins even when no strike passes liq_gate (wide spread)."
        ),
    }
    if sig == "long":
        side = "CALL"
    elif sig == "short":
        side = "PUT"
    else:
        return (
            "NO TRADE",
            ["No actionable signal — The Call says wait"],
            {**base_proof, "status": "no_trade", "reason": "call_signal_wait_or_unknown"},
        )

    side_contracts = [c for c in contracts if (c.get("putCall") or "").upper() == side]
    # single source: parse the strike once via the canonical finite reader (was parsed
    # twice — _f_ms for the filter, raw float() for the value — the raw path could admit
    # a value the filter would reject if the two ever diverged).
    strikes = sorted({sp for c in side_contracts
                      if (sp := _f_ms(c.get("strikePrice"))) is not None})
    if not strikes:
        return (
            "NO TRADE",
            [f"No {side} contracts in selected expiry"],
            {**base_proof, "status": "no_trade", "reason": "no_contracts_for_side", "side": side},
        )

    atm = min(strikes, key=lambda s: (abs(s - spot), s))
    if side == "CALL":
        itm_cands = [s for s in strikes if s <= spot]
        itm = max(itm_cands) if itm_cands else None
    else:
        itm_cands = [s for s in strikes if s >= spot]
        itm = min(itm_cands) if itm_cands else None

    candidates: list[float] = []
    for s in (atm, itm):
        if s is not None and s not in candidates:
            candidates.append(s)

    best_strike = None
    best_score = float("-inf")
    best_reasons: list[str] = []
    scored_rows: list[dict] = []
    pool_set = {float(x) for x in candidates}

    for k in candidates:
        score, reasons, audit = _oe_composite_strike_row(
            contracts=contracts, spot=spot, k=float(k), side=side, walls=walls
        )
        audit["in_selection_pool"] = float(k) in pool_set
        scored_rows.append(audit)
        if score is None:
            continue

        if score > best_score:
            best_score = score
            best_strike = k
            best_reasons = list(reasons)

    full_ranked: list[tuple[float, dict]] = []
    for k in strikes:
        sc, _reasons, audit = _oe_composite_strike_row(
            contracts=contracts, spot=spot, k=float(k), side=side, walls=walls
        )
        audit["in_selection_pool"] = float(k) in pool_set
        if sc is not None:
            full_ranked.append((sc, audit))
    full_ranked.sort(key=lambda x: x[0], reverse=True)
    ranked_top = [dict(r[1]) for r in full_ranked[:5]]

    proof_out = {
        **base_proof,
        "status": "no_trade" if best_strike is None else "ok",
        "call_signal": sig,
        "side": side,
        "candidates": {
            "atm": float(atm),
            "one_strike_itm": float(itm) if itm is not None else None,
            "evaluated_strikes": [float(x) for x in candidates],
        },
        "chain_rows_scored": scored_rows,
        "ranked_candidates_top5": ranked_top,
        "ranked_universe": "all strikes for side in selected expiry, sorted by composite_score",
    }

    if best_strike is None:
        return (
            "NO TRADE",
            ["Unable to score candidate strikes"],
            {**proof_out, "reason": "all_candidates_unscorable"},
        )

    txt = str(int(best_strike)) if float(best_strike).is_integer() else str(best_strike)
    if not best_reasons:
        best_reasons = ["ATM / ITM candidate with best composite liquidity+gamma score"]
    proof_out["winner"] = {
        "expression": f"{txt} {side}",
        "strike": float(best_strike),
        "side": side,
        "composite_score": round(best_score, 4),
        "win_reasons": best_reasons,
        "selection_rule": "max composite_score among ATM + one ITM candidate vs spot",
        "chain_row": _oe_chain_row_snapshot(_oe_first_contract_row(contracts, float(best_strike), side)),
    }
    any_liq = any(r.get("liq_gate_pass") for r in scored_rows if r.get("scored"))
    proof_out["liquidity_summary"] = {
        "any_candidate_passed_liq_gate": any_liq,
        "note": "Recommendation may still stand without liq_gate — see fallback_policy",
    }
    try:
        _bs = float(best_strike)
        _, _, _aud_w = _oe_composite_strike_row(
            contracts=contracts, spot=spot, k=_bs, side=side, walls=walls,
        )
        _, _, _aud_n = _oe_composite_strike_row(
            contracts=contracts, spot=spot, k=_bs, side=side, walls=None,
        )
        proof_out["wall_ablation_winner"] = {
            "with_walls_total_after": _aud_w.get("total_score_after_walls"),
            "without_walls_total_after": _aud_n.get("total_score_after_walls"),
            "wall_delta_on_winner": round(
                float(_aud_w.get("total_score_after_walls") or 0)
                - float(_aud_n.get("total_score_after_walls") or 0),
                4,
            ),
        }
    except Exception:
        proof_out["wall_ablation_winner"] = {"error": "ablation_compute_failed"}

    return (f"{txt} {side}", best_reasons, proof_out)














