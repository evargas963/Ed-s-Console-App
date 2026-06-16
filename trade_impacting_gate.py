"""Universal trade-impacting validation gate (I-28 market integrity + I-29 route supremacy).

Every production decision emission must pass through this module before
decision_id assignment or production_decision_records persistence.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from numeric_contract import float_finite_or_none

# Conservative index ETF bounds — wrong-but-finite prices outside these quarantine.
_PRICE_SANITY_BOUNDS: dict[str, tuple[float, float]] = {
    "SPY": (50.0, 2000.0),
    "QQQ": (50.0, 2000.0),
    "IWM": (50.0, 2000.0),
}
_DEFAULT_BOUNDS: tuple[float, float] = (1.0, 100_000.0)

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

# Phase 3C — canonical route inventory evidence (artifact builder + adversarial tests).
ROUTE_INVENTORY_EVIDENCE: dict[str, dict[str, object]] = {
    "R-005": {
        "enforcement_state": "blocked",
        "source_file": "server.py",
        "source_function": "_fetch_state (no_valid_expiry branch)",
        "trade_impacting": True,
        "runtime_gate": "trade_impacting_gate.apply_trade_impacting_gate",
        "evidence_tests": [
            "tests/adversarial/test_route_universality.py::test_synthetic_no_valid_expiry_route_blocked_from_decision_id",
            "tests/adversarial/test_route_universality.py::test_synthetic_route_does_not_persist_production_record",
        ],
    },
    "R-004": {
        "enforcement_state": "proven_gated",
        "source_file": "server.py",
        "source_function": "_fetch_state (normal path) → _finalize_production_decision",
        "trade_impacting": True,
        "runtime_gate": "trade_impacting_gate.apply_trade_impacting_gate via _finalize_production_decision",
        "evidence_tests": [
            "tests/adversarial/test_r004_live_path_gate.py",
            "tests/runtime_proof/test_live_path_decision_reconstruction.py",
        ],
    },
    "R-010": {
        "enforcement_state": "proven_gated",
        "source_file": "server.py",
        "source_function": "_tier_c_analytics_json_response",
        "trade_impacting": True,
        "runtime_gate": "trade_impacting_gate.revalidate_cached_decision",
        "evidence_tests": [
            "tests/adversarial/test_stale_cache_revalidation.py::test_stale_cache_revalidation_quarantines_bad_spot",
            "tests/adversarial/test_stale_cache_revalidation.py::test_fresh_valid_cache_passes_gate",
        ],
    },
    "R-011": {
        "enforcement_state": "classified_non_production",
        "source_file": "server.py",
        "source_function": "debug_prediction",
        "trade_impacting": False,
        "runtime_gate": "ED_ALLOW_DEBUG_ENDPOINTS + classified_non_production route",
        "evidence_tests": [
            "tests/adversarial/test_remaining_route_inventory.py::test_r011_debug_endpoint_blocked_without_flag",
            "tests/adversarial/test_remaining_route_inventory.py::test_r011_debug_fetch_state_no_production_decision_id",
        ],
    },
    "R-017": {
        "enforcement_state": "proven_gated",
        "source_file": "signals.py",
        "source_function": "_compute_signals_impl (pred_override)",
        "trade_impacting": True,
        "runtime_gate": "override_registry.append_override_record",
        "evidence_tests": ["tests/adversarial/test_override_registry.py"],
    },
    "R-031": {
        "enforcement_state": "classified_non_production",
        "source_file": "verify_model_outputs.py",
        "source_function": "main → _fetch_state(update_source=verify_model_outputs_cli)",
        "trade_impacting": False,
        "route_class": "diagnostic_only",
        "runtime_gate": "resolve_fetch_state_decision_route → cli.verify_model_outputs",
        "evidence_tests": [
            "tests/adversarial/test_r031_cli_classification.py",
        ],
    },
    "R-027": {
        "enforcement_state": "classified_non_production",
        "source_file": "governance/manual_control.py",
        "source_function": "ops promote / jobs",
        "trade_impacting": False,
        "runtime_gate": "non-production classification — not live HTTP decision emission",
        "evidence_tests": [
            "tests/adversarial/test_remaining_route_inventory.py::test_r027_classified_non_production",
        ],
    },
    "R-033": {
        "enforcement_state": "classified_non_production",
        "source_file": "calibration/",
        "source_function": "compute_signals direct (offline)",
        "trade_impacting": False,
        "runtime_gate": "non-production classification — calibration trust boundary",
        "evidence_tests": [
            "tests/adversarial/test_remaining_route_inventory.py::test_r033_classified_non_production",
        ],
    },
    "R-034": {
        "enforcement_state": "classified_non_production",
        "source_file": "ml_scheduler.py",
        "source_function": "execute_promotion_if_eligible",
        "trade_impacting": False,
        "runtime_gate": "governed executor when used; manual copy documented bypass",
        "evidence_tests": [
            "tests/adversarial/test_remaining_route_inventory.py::test_r034_classified_non_production",
        ],
    },
}


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


def resolve_fetch_state_decision_route(update_source: str | None) -> str:
    """Map _fetch_state caller to production decision route (R-011/R-031 use classified routes)."""
    src = str(update_source or "").strip()
    if src == "debug_endpoint":
        return "server.api.debug_prediction"
    if src in ("verify_model_outputs_cli", "verify_model_outputs"):
        return "cli.verify_model_outputs"
    if src in ("verify_mc_directional_cli", "verify_mc_directional"):
        return "cli.verify_mc_directional"
    return "server._fetch_state"


def _price_bounds(ticker: str) -> tuple[float, float]:
    t = str(ticker or "").upper().strip()
    return _PRICE_SANITY_BOUNDS.get(t, _DEFAULT_BOUNDS)


def assess_spot_price(ticker: str, spot: Any) -> tuple[bool, list[str]]:
    """Return (acceptable, reasons). Rejects missing, non-finite, non-positive, out-of-range."""
    reasons: list[str] = []
    t = str(ticker or "").upper().strip() or "UNKNOWN"
    if spot is None:
        return False, ["missing_price"]
    f = float_finite_or_none(spot)
    if f is None:
        if isinstance(spot, float) and math.isnan(spot):
            return False, ["nan_price"]
        return False, ["non_finite_price"]
    if f <= 0:
        return False, ["non_positive_price"]
    lo, hi = _price_bounds(t)
    if f < lo or f > hi:
        return False, [f"price_out_of_sanity_range:{f} not in [{lo}, {hi}] for {t}"]
    return True, []


def _spread_stale(ms_dict: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if ms_dict.get("analytics_stale") is True:
        reasons.append("analytics_stale")
    spread_age = ms_dict.get("spread_age_ms")
    if spread_age is not None:
        try:
            age_ms = float(spread_age)
            max_age = float(os.environ.get("ED_GATE_MAX_SPREAD_AGE_MS", "300000"))
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
    ticker = str(ms_dict.get("ticker") or "").upper().strip()
    if not ticker:
        reasons.append("missing_ticker")

    spot_ok, spot_reasons = assess_spot_price(ticker, ms_dict.get("spot"))
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
    """Apply gate — mutates ms_dict with quarantine + non-tradeable fields when blocked."""
    result = validate_trade_impacting_gate(ms_dict, route=route)
    ms_dict["trade_impacting_route"] = route
    ms_dict["trade_impacting_route_class"] = result.route_class
    ms_dict["market_data_quarantine"] = result.market_data_quarantine()

    if result.quarantined or result.route_class != "production":
        ms_dict["trade_valid"] = False
        if ms_dict.get("call_signal") in ("long", "short"):
            ms_dict["call_signal"] = "wait"
            ms_dict["call_conviction"] = "low"
        call = ms_dict.get("call")
        if isinstance(call, dict):
            call = dict(call)
            call["trade_valid"] = False
            if call.get("signal") in ("long", "short"):
                call["signal"] = "wait"
            ms_dict["call"] = call
        if not ms_dict.get("validation_summary"):
            ms_dict["validation_summary"] = "GATED — " + "; ".join(result.reasons[:3])
    return result


def revalidate_cached_decision(
    md: dict[str, Any],
    *,
    route: str,
    stale: bool,
) -> dict[str, Any]:
    """R-010 — re-run gate before serving stale Tier C cache."""
    out = dict(md)
    if stale:
        out["analytics_stale"] = True
    result = apply_trade_impacting_gate(out, route=route or "server._tier_c_cache_serve")
    out["tier_c_cache_revalidated"] = True
    out["tier_c_cache_gate_ok"] = result.production_emission_allowed
    return out


def production_emission_allowed(ms_dict: dict[str, Any], *, route: str) -> bool:
    result = validate_trade_impacting_gate(ms_dict, route=route)
    return result.production_emission_allowed
