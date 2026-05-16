"""
Section 4 Schwab-leaf derivation audit inventory (KEY LEVELS re-walk).

Disposition: REPLACED | KEEP_DERIVED | PASS_THROUGH | NONE
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivationRecord:
    file: str
    line: str
    derivation: str
    schwab_leaf: str
    disposition: str
    justification: str


SECTION4_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
    DerivationRecord(
        "math_exposure_core.py",
        "29-38",
        "bucket_metric fail-closed reads",
        "chains.* (bucket keys)",
        "PASS_THROUGH",
        "No .get(key,0) silent default; returns None when absent.",
    ),
    DerivationRecord(
        "math_exposure_core.py",
        "105-232",
        "compute_exposures_by_strike GEX/DEX from chain greeks",
        "chains.*.delta,gamma,openInterest,multiplier,bidSize,askSize",
        "PASS_THROUGH",
        "Schwab chain leaves; skip -999/invalid greeks; dollarize when spot known.",
    ),
    DerivationRecord(
        "math_exposure_core.py",
        "370-451",
        "pick_gamma_pin/HVL/walls institutional metrics",
        "chains.*.gamma (via GEX$)",
        "KEEP_DERIVED",
        "Institutional aggregations; raw fallback only when dollar GEX unavailable.",
    ),
    DerivationRecord(
        "math_exposure.py",
        "—",
        "Order-flow verdict helpers + re-exports",
        "—",
        "NONE",
        "No Schwab field ingest; delegates to math_exposure_core.",
    ),
    DerivationRecord(
        "math_levels.py",
        "116-400",
        "build_summary_rows / walls / pins from exposures",
        "chains.* via exposures",
        "KEEP_DERIVED",
        "KEY LEVELS presentation; uses bucket_metric throughout.",
    ),
    DerivationRecord(
        "math_levels.py",
        "618-647",
        "parity residual _mid from mark only",
        "chains.*.mark",
        "PASS_THROUGH",
        "Mark-first mid for straddle parity; no bid+ask/2.",
    ),
    DerivationRecord(
        "math_levels.py",
        "859-872",
        "liquidity void _get_gex gamma sum",
        "chains.*.gamma",
        "REPLACED",
        "Sum call/put gamma only when present; no (c or 0)+(p or 0) synthesis.",
    ),
    DerivationRecord(
        "math_levels.py",
        "652-690",
        "compute_gamma_flip zero-crossing",
        "net_gamma / net_gex_1pct buckets",
        "KEEP_DERIVED",
        "Interpolation on exposure buckets; no Schwab leaf.",
    ),
    DerivationRecord(
        "math_volatility.py",
        "121-140",
        "expected move straddle from ATM marks",
        "chains.*.mark",
        "KEEP_DERIVED",
        "EM formula from Schwab option marks; not a single EM leaf.",
    ),
    DerivationRecord(
        "math_volatility.py",
        "288-320",
        "IV skew from chain volatility",
        "chains.*.volatility",
        "PASS_THROUGH",
        "Reads Schwab volatility leaf when present.",
    ),
    DerivationRecord(
        "math_volatility.py",
        "65-91",
        "charm_intraday_context banner",
        "derived charm_result dict",
        "KEEP_DERIVED",
        "Presentation of precomputed charm; contracts_used gate.",
    ),
    DerivationRecord(
        "math_probabilities.py",
        "176-264",
        "score_option_expression spread from bid/ask",
        "chains.*.bid,ask,mark,gamma,delta",
        "KEEP_DERIVED",
        "Spread pts from bid-ask; no mid synthesis for scoring.",
    ),
    DerivationRecord(
        "math_probabilities.py",
        "1370-1402",
        "strike_activity volume sum near ATM",
        "chains.*.totalVolume (bucket call/put_volume)",
        "REPLACED",
        "Sum volumes only when Schwab volume present per side.",
    ),
    DerivationRecord(
        "math_probabilities.py",
        "539-770",
        "gamma gradient / breakout / vol signal composites",
        "—",
        "KEEP_DERIVED",
        "Model composites from exposure inputs.",
    ),
    DerivationRecord(
        "levels.py",
        "—",
        "Display formatting for ExposureRow/WallsRow",
        "—",
        "NONE",
        "No derivations; formats precomputed KEY LEVELS rows.",
    ),
)
