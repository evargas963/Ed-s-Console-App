"""
ml_scheduler / training bulk ticker load — Issue 22 single source of truth: EdDB.logging_universe.

Authoritative enrollment = rows in logging_universe (core + pinned + panel_auto + user_persisted).
There is no parallel ticker list from JSON or from DISTINCT(snapshot tables) for *who is enrolled*.

Historical companion file data/user_scheduler_tickers.json is migrated once into
logging_universe by EdDB.logging_universe_migrate_scheduler_companion_json.

Diagnostic / non-authoritative: ml_scheduler may log tickers that have labeled RTH rows in
snapshots_1m_normalized but are absent from logging_universe — that does not enroll them.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional
import logging

from instrument_identity import ticker_storage_key

log = logging.getLogger(__name__)

# Operator: bottom-panel / panel_auto symbols are confluence features only (SPY/QQQ/IWM context).
# They must log for cross-instrument features but are excluded from ML scheduler training.
CONFLUENCE_ONLY_UNIVERSE_CATEGORIES: frozenset[str] = frozenset({"panel_auto"})

# Operator binding (2026-06-11): ONLY these three index anchors receive ML train/promote/verify.
# All other enrolled symbols (core mega-caps, pinned, user_persisted, panel_auto) are guests:
# log + UI/cold-call inference from accumulated data — not scheduler training targets.
TRAINING_ANCHOR_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "IWM")

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def training_anchor_tickers_upper() -> frozenset[str]:
    # RC-345/F25: anchor membership set is canonical-keyed (SPY/QQQ/IWM unchanged; SPX↔$SPX collapse)
    return frozenset(ticker_storage_key(t) for t in TRAINING_ANCHOR_TICKERS)


def is_training_anchor_ticker(ticker: str) -> bool:
    return ticker_storage_key(ticker) in training_anchor_tickers_upper()  # RC-345/F25: canonical membership


def require_ml_training_ticker_allowed(ticker: str) -> str:
    """Fail-closed guard for explicit single-ticker train entry points."""
    t = ticker_storage_key(ticker)  # RC-345/F25: returned training identity is canonical
    if not t:
        raise ValueError("require_ml_training_ticker_allowed: empty ticker")
    if ml_scheduler_training_expansion_enabled():
        return t
    if t not in training_anchor_tickers_upper():
        raise ValueError(
            f"{t} is not a training anchor ({', '.join(TRAINING_ANCHOR_TICKERS)}). "
            "Guests are log/UI-only unless ED_ML_SCHEDULER_TRAINING_EXPAND=1."
        )
    return t


def ml_scheduler_training_expansion_enabled() -> bool:
    """Opt-in: train full enrolled roster minus panel_auto (legacy expansion path)."""
    return os.environ.get("ED_ML_SCHEDULER_TRAINING_EXPAND", "").strip().lower() in _TRUTHY


_ROOT = Path(__file__).resolve().parent
_PATH = _ROOT / "data" / "user_scheduler_tickers.json"
_ARCHIVE_PATH = _ROOT / "data" / "user_scheduler_tickers.json.migrated_issue22"


def load_user_scheduler_tickers() -> Optional[list[str]]:
    """Return authoritative enrolled tickers (same universe as background logger).

    Returns:
      ``list[str]`` (possibly empty) on success — the enrolled-ticker list.
      ``None`` on DB-bound load failure — distinct from "no tickers enrolled".

    STACK-VERIFY-CAND-LOAD-TICKERS-RETURN-TYPE closure: callers can now distinguish
    "DB unavailable" (None) from "DB OK but nobody enrolled" (empty list). Use
    ``load_user_scheduler_tickers_or_empty()`` for legacy callers that want the
    pre-fix list-or-empty semantic.
    """
    try:
        from db import get_db

        db = get_db()
        db.logging_universe_migrate_scheduler_companion_json(
            primary_path=_PATH,
            archive_path=_ARCHIVE_PATH,
        )
        return db.logging_universe_authoritative_tickers()
    except Exception as e:
        log.warning(
            "load_user_scheduler_tickers: DB-bound load failed; returning None "
            "(caller distinguishes DB-unavailable from empty enrollment): %s",
            e,
        )
        return None


def load_user_scheduler_tickers_or_empty() -> list[str]:
    """Legacy convenience: ``load_user_scheduler_tickers() or []``.

    Use when the caller treats DB-unavailable identically to no-enrollment and
    doesn't need the distinction. Prefer the typed version + explicit None handling
    in new code so DB failures are visible.
    """
    return load_user_scheduler_tickers() or []


def panel_auto_ticker_set(db_path: str) -> frozenset[str]:
    """Symbols enrolled as confluence-only (panel_auto) — quote context, not ML training."""
    try:
        from db import EdDB

        rows = EdDB(str(db_path)).logging_universe_list_rows()
    except Exception as e:
        log.warning("panel_auto_ticker_set: cannot read logging_universe (%s)", e)
        return frozenset()
    return frozenset(
        ticker_storage_key(str(row.get("ticker") or ""))  # RC-345/F25: canonical membership key
        for row in rows
        if str(row.get("category") or "") in CONFLUENCE_ONLY_UNIVERSE_CATEGORIES
    )


def filter_tickers_for_background_logging(tickers: list[str], db_path: str) -> list[str]:
    """Drop panel_auto from background full-chain snapshot rotation (thin quote path only).

    Base money-path anchors (SPY/QQQ/IWM) are never excluded — they require full capture parity.
    """
    skip = panel_auto_ticker_set(db_path) - training_anchor_tickers_upper()
    if not skip:
        return list(tickers)
    out = [t for t in tickers if ticker_storage_key(t) not in skip]  # RC-345/F25: canonical membership
    excluded = sorted(skip & {ticker_storage_key(t) for t in tickers})
    if excluded:
        log.info(
            "Background logging excludes %d confluence-only (panel_auto) from full snapshots: %s",
            len(excluded),
            excluded,
        )
    return out


def filter_tickers_for_ml_training(tickers: list[str], db_path: str) -> list[str]:
    """Drop confluence-only enrolled symbols (panel_auto) from ML training runs."""
    try:
        from db import EdDB

        rows = EdDB(str(db_path)).logging_universe_list_rows()
    except Exception as e:
        log.warning("filter_tickers_for_ml_training: cannot read logging_universe (%s)", e)
        return tickers
    skip = {
        ticker_storage_key(str(row.get("ticker") or ""))  # RC-345/F25: canonical membership key
        for row in rows
        if str(row.get("category") or "") in CONFLUENCE_ONLY_UNIVERSE_CATEGORIES
    }
    if not skip:
        return tickers
    enrolled = {ticker_storage_key(t) for t in tickers}
    excluded = sorted(skip & enrolled)
    if not excluded:
        return tickers
    out = [t for t in tickers if ticker_storage_key(t) not in skip]
    log.info(
        "ML training excludes %d confluence-only (panel_auto) tickers: %s",
        len(excluded),
        excluded,
    )
    return out


def resolve_ml_training_roster(enrolled: list[str], db_path: str) -> list[str]:
    """
    Authoritative ML training roster for scheduler, train_all, and verify_active_models.

    Default (expansion off): TRAINING_ANCHOR_TICKERS only (SPY, QQQ, IWM).
    Guests: panel_auto (confluence), pinned, user_persisted, and non-anchor core symbols
    remain enrolled for logging/UI but are excluded here.

    ED_ML_SCHEDULER_TRAINING_EXPAND=1 restores pre-anchor behavior (enrolled minus panel_auto).
    ED_ML_SCHEDULER_TICKERS further subsets the resolved pool (intersected with anchors when
    expansion is off — non-anchor explicit picks are dropped with a warning).
    """
    pool = filter_tickers_for_ml_training(list(enrolled), db_path)
    if not ml_scheduler_training_expansion_enabled():
        enrolled_upper = {ticker_storage_key(t) for t in enrolled}  # RC-345/F25: canonical membership
        pool = [ticker_storage_key(t) for t in TRAINING_ANCHOR_TICKERS if ticker_storage_key(t) in enrolled_upper]
        if len(pool) < len(TRAINING_ANCHOR_TICKERS):
            missing = [t for t in TRAINING_ANCHOR_TICKERS if t not in enrolled_upper]
            if missing:
                log.warning(
                    "Training anchor roster: missing enrolled anchors (will not train): %s",
                    missing,
                )
    explicit = (os.environ.get("ED_ML_SCHEDULER_TICKERS") or "").strip()
    if explicit:
        want = {ticker_storage_key(t) for t in explicit.split(",") if t.strip()}  # RC-345/F25: canonical membership
        if not ml_scheduler_training_expansion_enabled():
            dropped = sorted(want - training_anchor_tickers_upper())
            if dropped:
                log.warning(
                    "ED_ML_SCHEDULER_TICKERS ignored non-anchor symbols (expansion off): %s",
                    dropped,
                )
            want &= training_anchor_tickers_upper()
        before = len(pool)
        pool = [t for t in pool if ticker_storage_key(t) in want]  # RC-345/F25: canonical membership
        log.info(
            "ED_ML_SCHEDULER_TICKERS filter: %d of %d roster tickers selected",
            len(pool),
            before,
        )
    if not ml_scheduler_training_expansion_enabled() and pool:
        log.info(
            "ML training roster locked to anchors %s (%d tickers; guests excluded)",
            list(pool),
            len(pool),
        )
    return pool


def record_user_ticker(ticker: str) -> None:
    """
    Shim for code paths that register without server._register_tracked_ticker.
    Authoritative enrollment remains logging_universe (same upsert as UI/API).
    """
    from production_universe import is_valid_production_ticker, normalize_production_ticker

    s = normalize_production_ticker(ticker)
    if not s or not is_valid_production_ticker(s):
        return
    try:
        from db import get_db

        get_db().logging_universe_upsert_user_persisted(
            s, "scheduler_shim", time.time()
        )
    except Exception as e:
        log.debug("scheduler user tickers: %s", e, exc_info=True)
