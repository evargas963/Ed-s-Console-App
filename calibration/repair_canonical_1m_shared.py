"""Shared helpers for canonical 1m repair tools (carry basis + synthetic source tags)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from horizon_outcomes import (
    SYNTHETIC_ANCHOR_COVERAGE_PAD_V1,
    SYNTHETIC_EDGE_CARRY_V1,
    SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
)
from app.domain.time_et import is_collect_window_bar_end_ts_utc  # RC-183 collect-window law

GAP_FILL_CANONICAL_1M_GRID_V1 = "gap_fill_canonical_1m_grid_v1"

REPAIR_SYNTHETIC_1M_SOURCES: frozenset[str] = frozenset(
    {
        GAP_FILL_CANONICAL_1M_GRID_V1,
        SYNTHETIC_EDGE_CARRY_V1,
        SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
        SYNTHETIC_ANCHOR_COVERAGE_PAD_V1,
    }
)


def carry_basis_source_sql(*, column: str = "source") -> tuple[str, tuple[str, ...]]:
    """SQL fragment + bind values: exclude known synthetic repair sources from carry basis."""
    placeholders = ",".join("?" * len(REPAIR_SYNTHETIC_1M_SOURCES))
    clause = f"({column} IS NULL OR {column} NOT IN ({placeholders}))"
    return clause, tuple(REPAIR_SYNTHETIC_1M_SOURCES)


CANONICAL_1M_BAR_SECONDS = 60.0


def apply_repair_1m_bar_batch_writes(
    db_path: Path,
    batch: dict[str, list[dict[str, Any]]],
    *,
    tz: float,
    default_source: str,
) -> tuple[int, int]:
    """Single-transaction bar upserts + governed outcome refresh for mutated starts."""
    from db import _refresh_governed_outcomes_after_bar_mutation, configure_sqlite_connection
    from app.domain.instrument_identity import ticker_storage_key

    conn = sqlite3.connect(str(db_path), timeout=120.0)
    configure_sqlite_connection(conn)
    # Row factory required: _refresh_governed_outcomes_after_bar_mutation indexes
    # snapshot/bar rows by column name (r["ts_utc"], r["bar_start_ts_utc"]).
    conn.row_factory = sqlite3.Row
    changed_by_ticker: dict[str, set[float]] = {}
    n_written = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for tkr, bars in batch.items():
            t_key = ticker_storage_key(tkr)
            if not t_key or not bars:
                continue
            rows: list[tuple[Any, ...]] = []
            for b in bars:
                g = float(b["ts"])
                # RC-183: this writer FABRICATES flat o=h=l=c volume-0 bars — the exact shape
                # the RTH census counted as fake-filled minutes. It must never fabricate one
                # outside the collect window the seam enforces.
                if not is_collect_window_bar_end_ts_utc(g + CANONICAL_1M_BAR_SECONDS):
                    continue
                c = float(b["close"])
                rows.append(
                    (
                        t_key,
                        g,
                        g + CANONICAL_1M_BAR_SECONDS,
                        c,
                        c,
                        c,
                        c,
                        0.0,
                        str(b.get("source") or default_source),
                    )
                )
                changed_by_ticker.setdefault(t_key, set()).add(g)
            if not rows:
                continue
            conn.executemany(
                """
                INSERT INTO price_bars_1m -- collect-window-ok: rows gated via is_collect_window_bar_end_ts_utc above (RC-183)
                  (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, bar_start_ts_utc) DO UPDATE SET
                  bar_end_ts_utc = excluded.bar_end_ts_utc,
                  open = excluded.open,
                  high = excluded.high,
                  low = excluded.low,
                  close = excluded.close,
                  volume = excluded.volume,
                  source = excluded.source
                """,
                rows,
            )
            n_written += len(rows)
        for t_key, starts in changed_by_ticker.items():
            _refresh_governed_outcomes_after_bar_mutation(
                conn,
                tkr=t_key,
                changed_bar_starts=starts,
                tz=tz,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return n_written, len(changed_by_ticker)
