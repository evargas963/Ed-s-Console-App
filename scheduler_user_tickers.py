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

import time
from pathlib import Path
from typing import Optional
import logging

log = logging.getLogger(__name__)


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
