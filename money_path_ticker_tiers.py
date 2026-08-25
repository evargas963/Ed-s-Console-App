"""
Money-path ticker tiers — base (SPY/QQQ/IWM) vs guest.

Base tickers are the minimum institutional money-path universe per operator binding
(2026-06-11 training anchors). Guest tickers may appear in UI but must not inherit
base trust without explicit observability promotion proof.

Policy artifact: governance/artifacts/base_ticker_money_path_contract.json
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS

_REPO_ROOT = Path(__file__).resolve().parent
_CONTRACT_PATH = _REPO_ROOT / "governance" / "artifacts" / "base_ticker_money_path_contract.json"

BASE_MONEY_PATH_TICKERS: tuple[str, ...] = TRAINING_ANCHOR_TICKERS

# RTH full-pipeline capture cadence for base tickers (independent of UI-active symbol).
DEFAULT_BASE_CAPTURE_INTERVAL_SEC = 60.0

TRUST_GUEST_UNPROVEN = "guest_unproven"
TRUST_PROMOTED_GUEST = "promoted_guest"
TRUST_BASE = "base_money_path"


@lru_cache(maxsize=1)
def load_base_ticker_contract() -> dict[str, Any]:
    if not _CONTRACT_PATH.is_file():
        raise FileNotFoundError(f"missing base ticker contract: {_CONTRACT_PATH}")
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def base_money_path_tickers_upper() -> frozenset[str]:
    # RC-345/F25: canonical membership set (SPY/QQQ/IWM unchanged; index aliases collapse)
    return frozenset(ticker_storage_key(t) for t in BASE_MONEY_PATH_TICKERS)


def is_base_money_path_ticker(ticker: str) -> bool:
    return ticker_storage_key(ticker) in base_money_path_tickers_upper()  # RC-345/F25: canonical membership


def is_guest_ticker(ticker: str) -> bool:
    return not is_base_money_path_ticker(ticker)


def ticker_trust_class(ticker: str, *, promoted: bool = False) -> str:
    if is_base_money_path_ticker(ticker):
        return TRUST_BASE
    if promoted:
        return TRUST_PROMOTED_GUEST
    return TRUST_GUEST_UNPROVEN


def observability_thresholds() -> dict[str, Any]:
    return dict(load_base_ticker_contract()["rth_observability_thresholds"])


def base_money_path_capture_interval_sec() -> float:
    """Seconds between dedicated base-ticker capture cycles (~1 RTH snapshot/min per symbol)."""
    raw = os.environ.get("ED_BASE_MONEY_PATH_CAPTURE_INTERVAL_SEC", "").strip()  # caps-ok: operator config read; empty sentinel falls through to the declared default below, not market data
    if raw:
        try:
            v = float(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return DEFAULT_BASE_CAPTURE_INTERVAL_SEC


# UNIVERSAL COLLECTION (operator requirement, restated 2026-08-25): `should_skip_background_
# full_snapshot` is DELETED, not neutered. It encoded the panel_auto confluence-only carve-out
# that left 17 enrolled tickers with ZERO snapshots over 5 measured trading days (RC-482). Once
# the operator ruled universal collection the standard, the predicate had no true branch and no
# caller; keeping an always-False shim would repeat RC-474 exactly — a producer removed at the
# call site while its dead body stays behind to be re-wired by someone who trusts the name.
# The surviving authority is the roster itself: every enrolled ticker enters the sweep.
