"""Universal trade-impacting validation gate (I-28 market integrity + I-29 route supremacy).

Every production decision emission must pass through this module before
decision_id assignment or production_decision_records persistence.

The gate computes FACTS (route class, market-data sanity, staleness, quarantine, whether
production emission is permitted) and blocks emission / persistence / actionability on them.
It does not compute or rewrite the trading verdict: The Call (call_engine.compute_call) is the
one computation authority for call_signal / call_conviction, and it consumes these facts as an
input (RC-534) — see validate_trade_impacting_gate at server._fetch_state before build_market_state.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

from numeric_contract import float_finite_or_none
from instrument_identity import ticker_storage_key

#: Wrong-but-finite price quarantine, the SAME rule for every ticker (universality, operator
#: 2026-09-23): the price must lie within [0.5x, 2x] of the ticker's own prior close (Schwab
#: LEVELONE_EQUITIES CLOSE_PRICE). It used to be a fixed 50-2000 band for SPY/QQQ/IWM and an
#: effectively open 1-100000 band for everyone else. A move past 2x or below 0.5x in one
#: session is outside any exchange's single-session price behaviour and reads as a bad print.
PRICE_SANITY_BAND_VS_PRIOR_CLOSE: tuple[float, float] = (0.5, 2.0)

SYNTHETIC_NON_PRODUCTION_ROUTES: frozenset[str] = frozenset(
    {
        "server._fetch_state.no_valid_expiry",
        "server._fetch_state.expiry_slice_empty",
    }
)

CLASSIFIED_NON_PRODUCTION_ROUTES: frozenset[str] = frozenset(
    {
        "server.api.debug_prediction",
        "cli.verify_model_outputs",
        "cli.verify_mc_directional",
        "calibration.stack",
        "governance.ops.promote",
        "ml_scheduler.promotion",
    }
)

NON_PRODUCTION_ROUTE_PREFIXES: tuple[str, ...] = (
    "test.",
    "audit.",
    "debug.",
    "replay.",
    "synthetic.",
)



@dataclass
class TradeImpactingGateResult:
    ok: bool
    quarantined: bool
    production_emission_allowed: bool
    reasons: list[str] = field(default_factory=list)
    route_class: str = "production"

    def market_data_quarantine(self) -> dict[str, Any]:
        return {
            "active": self.quarantined,
            "reasons": list(self.reasons),
            "route_class": self.route_class,
        }


def classify_route(route: str) -> str:
    r = str(route or "").strip()
    if r in SYNTHETIC_NON_PRODUCTION_ROUTES:
        return "synthetic_non_production"
    if r in CLASSIFIED_NON_PRODUCTION_ROUTES:
        return "classified_non_production"
    if any(r.startswith(p) for p in NON_PRODUCTION_ROUTE_PREFIXES):
        return "test_non_production"
    return "production"




def assess_spot_price(ticker: str, spot: Any, prior_close: Any = None) -> tuple[bool, list[str]]:
    """Return (acceptable, reasons). Rejects missing, non-finite, non-positive, outside
    PRICE_SANITY_BAND_VS_PRIOR_CLOSE of the ticker's own prior close -- and, when that prior
    close is unknown, rejects too: a price that cannot be checked is not a verified price
    (operator rule 2026-09-23: no fallbacks)."""
    t = ticker_storage_key(ticker) or "UNKNOWN"  # RC-345/F25: canonical gate identity
    if spot is None:
        return False, ["missing_price"]
    f = float_finite_or_none(spot)
    if f is None:
        if isinstance(spot, float) and math.isnan(spot):
            return False, ["nan_price"]
        return False, ["non_finite_price"]
    if f <= 0:
        return False, ["non_positive_price"]
    ref = float_finite_or_none(prior_close)
    if ref is None or ref <= 0:
        return False, [f"no_prior_close_reference:{t}"]
    lo = ref * PRICE_SANITY_BAND_VS_PRIOR_CLOSE[0]
    hi = ref * PRICE_SANITY_BAND_VS_PRIOR_CLOSE[1]
    if f < lo or f > hi:
        return False, [f"price_out_of_sanity_range:{f} not in [{lo:.4f}, {hi:.4f}] "
                       f"(0.5x-2x prior close {ref}) for {t}"]
    return True, []


def _spread_stale(ms_dict: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if ms_dict.get("analytics_stale") is True:
        reasons.append("analytics_stale")
    spread_age = ms_dict.get("spread_age_ms")
    if spread_age is not None:
        try:
            age_ms = float(spread_age)
            max_age = float(os.environ.get("ED_GATE_MAX_SPREAD_AGE_MS", "300000"))  # caps-ok: declared operational default (300s staleness ceiling), operator-tunable config not market data
            if age_ms > max_age:
                reasons.append(f"spread_age_ms_exceeded:{age_ms}")
        except (TypeError, ValueError):
            reasons.append("invalid_spread_age_ms")
    return bool(reasons), reasons


def validate_trade_impacting_gate(
    ms_dict: dict[str, Any],
    *,
    route: str,
) -> TradeImpactingGateResult:
    """Validate ms_dict for trade-impacting emission. Does not mutate."""
    reasons: list[str] = []
    route_class = classify_route(route)
    ticker = ticker_storage_key(ms_dict.get("ticker"))  # RC-345/F25: canonical gate identity
    if not ticker:
        reasons.append("missing_ticker")

    spot_ok, spot_reasons = assess_spot_price(ticker, ms_dict.get("spot"), ms_dict.get("prior_close"))
    if not spot_ok:
        reasons.extend(spot_reasons)

    stale, stale_reasons = _spread_stale(ms_dict)
    if stale:
        reasons.extend(stale_reasons)

    if route_class == "synthetic_non_production":
        reasons.append("synthetic_route_no_full_pipeline")
    elif route_class == "classified_non_production":
        reasons.append("classified_non_production_no_production_emission")

    val_summary = ms_dict.get("validation_summary")
    if route_class == "production" and not val_summary and ms_dict.get("call_signal") in ("long", "short"):
        reasons.append("missing_validation_summary_for_directional_signal")

    if ms_dict.get("state_error") and route_class == "production":
        reasons.append(f"state_error:{ms_dict.get('state_error')}")

    non_route_reasons = [
        r
        for r in reasons
        if r
        not in (
            "synthetic_route_no_full_pipeline",
            "classified_non_production_no_production_emission",
        )
    ]
    quarantined = bool(non_route_reasons) or route_class in (
        "synthetic_non_production",
        "classified_non_production",
    )
    production_allowed = route_class == "production" and not non_route_reasons
    return TradeImpactingGateResult(
        ok=not quarantined,
        quarantined=quarantined,
        production_emission_allowed=production_allowed,
        reasons=reasons,
        route_class=route_class,
    )


def apply_trade_impacting_gate(
    ms_dict: dict[str, Any],
    *,
    route: str,
) -> TradeImpactingGateResult:
    """Apply gate — stamps the route, its class and the market_data_quarantine FACT on ms_dict.

    RC-534: this function used to rewrite the verdict (call_signal → wait, call_conviction → low,
    nested call.signal, trade_valid, a fabricated validation_summary) when quarantined or on a
    non-production route — a second writer of The Call after its owner had produced it, while
    every coupled field (call_option_right, is_no_trade, rec_strike, headline, plan) stayed
    derived from the pre-veto verdict. The owner now consumes the same facts BEFORE it decides
    (server._fetch_state validates them and hands them to compute_call through SignalInput) and
    vetoes itself. Here the gate keeps only its distinct responsibilities: the quarantine fact
    for consumers, and — through stamp_decision_bundle / persist_stamped_decision / the operator
    mirror — blocking decision_id, persistence and actionability. It rewrites no verdict field.
    """
    result = validate_trade_impacting_gate(ms_dict, route=route)
    ms_dict["trade_impacting_route"] = route
    ms_dict["trade_impacting_route_class"] = result.route_class
    ms_dict["market_data_quarantine"] = result.market_data_quarantine()
    return result




def production_emission_allowed(ms_dict: dict[str, Any], *, route: str) -> bool:
    result = validate_trade_impacting_gate(ms_dict, route=route)
    return result.production_emission_allowed
