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
























def filter_tickers_for_background_logging(tickers: list[str], db_path: str) -> list[str]:
    """UNIVERSAL COLLECTION (operator requirement, restated 2026-08-25): no ticker is
    dropped from background full-snapshot rotation — the panel_auto confluence-only
    carve-out this filter used to apply left 17 enrolled tickers with zero snapshots
    (RC-482). The function survives as the single roster authority for its callers and
    now passes the roster through unchanged; `db_path` is accepted and ignored."""
    del db_path
    return list(tickers)






