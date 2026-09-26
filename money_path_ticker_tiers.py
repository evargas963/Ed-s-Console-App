"""
Money-path ticker tiers — base (SPY/QQQ/IWM) vs guest.

Base tickers are the minimum institutional money-path universe per operator binding
(2026-06-11 training anchors). Guest tickers may appear in UI but must not inherit
base trust without explicit observability promotion proof.

Policy artifact: reports/artifacts/base_ticker_money_path_contract.json
"""
from __future__ import annotations


from instrument_identity import ticker_storage_key
from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS


BASE_MONEY_PATH_TICKERS: tuple[str, ...] = TRAINING_ANCHOR_TICKERS






def base_money_path_tickers_upper() -> frozenset[str]:
    # RC-345/F25: canonical membership set (SPY/QQQ/IWM unchanged; index aliases collapse)
    return frozenset(ticker_storage_key(t) for t in BASE_MONEY_PATH_TICKERS)












# UNIVERSAL COLLECTION (operator requirement, restated 2026-08-25): `should_skip_background_
# full_snapshot` is DELETED, not neutered. It encoded the panel_auto confluence-only carve-out
# that left 17 enrolled tickers with ZERO snapshots over 5 measured trading days (RC-482). Once
# the operator ruled universal collection the standard, the predicate had no true branch and no
# caller; keeping an always-False shim would repeat RC-474 exactly — a producer removed at the
# call site while its dead body stays behind to be re-wired by someone who trusts the name.
# The surviving authority is the roster itself: every enrolled ticker enters the sweep.
