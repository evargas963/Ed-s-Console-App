"""Ticker-roster / logging-universe persistence, extracted from EdDB (RC-REHAB-1,
db.py decomposition, 2026-09-21).

Everything here answers ONE question: which tickers does the background logger/scheduler
enroll for, at what category (core / pinned / panel_auto / user_persisted), and how does
that roster evolve (eviction, one-time legacy-JSON migration, canonical-identity cleanup).
Also carries confluence_quote_ticks, the thin cross-instrument quote-tick store panel_auto
enrollment reads from -- a small, adjacent persistence concern, not its own cluster.

LoggingUniverseMixin is mixed into EdDB (db.py) rather than exported as free functions: every
method here already assumed `self._connect()`/`self.db_path` (EdDB's own connection
helper and schema-guard install) -- keeping that contract intact means call sites
(`db.logging_universe_sync_core(...)`, etc.) are unchanged by this move, which is what a
decomposition slice must prove: identical behavior, different file.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time as _wall_time
import logging
from pathlib import Path
from typing import Any, Optional

from instrument_identity import ticker_storage_key
from timeframe_config import CANONICAL_TIMEFRAME

log = logging.getLogger(__name__)


def _dedup_preserve(items: list[str]) -> list[str]:
    """Order-preserving unique — used when canonicalizing enrollment reads can collapse a legacy
    bare-root alias (``SPX``) and its canonical form (``$SPX``) onto one identity (RC-345/F25)."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


class LoggingUniverseMixin:
    """Mixed into EdDB. Assumes ``self._connect()`` and ``self.db_path`` from the host class."""

    def _ensure_logging_universe_table(self):
        """Issue 22 — durable background-logging enrollment (additive schema)."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logging_universe (
                    ticker                     TEXT PRIMARY KEY COLLATE NOCASE,
                    category                   TEXT NOT NULL,
                    enrollment_source          TEXT,
                    enrolled_ts_utc            REAL NOT NULL,
                    last_seen_ts_utc           REAL NOT NULL,
                    last_background_log_ts_utc REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logging_universe_cat "
                "ON logging_universe (category, enrolled_ts_utc)"
            )

    def _ensure_logging_universe_aux_tables(self):
        """Eviction audit + idempotent migration bookkeeping (Issue 22 hardening)."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logging_universe_eviction_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evicted_ticker TEXT NOT NULL,
                    evicted_ts_utc REAL NOT NULL,
                    reason TEXT NOT NULL,
                    cap_limit INTEGER,
                    incoming_ticker TEXT,
                    incoming_enrollment_source TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logging_universe_migration_log (
                    name TEXT PRIMARY KEY,
                    completed_ts_utc REAL NOT NULL,
                    source_sha256 TEXT,
                    detail_json TEXT
                )
                """
            )

    def _ensure_confluence_quote_table(self):
        """Thin quote ticks for panel_auto / cross-instrument symbols (not full snapshots)."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS confluence_quote_ticks (
                    ticker      TEXT NOT NULL,
                    ts_utc      REAL NOT NULL,
                    ts_et       TEXT NOT NULL,
                    last_price  REAL,
                    chg_pct     REAL,
                    PRIMARY KEY (ticker, ts_utc)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_confluence_quote_ticks_ticker_ts "
                "ON confluence_quote_ticks (ticker, ts_utc DESC)"
            )

    def upsert_confluence_quote_ticks(self, rows: list[dict[str, Any]]) -> int:
        """Insert thin quote rows (panel / constituent symbols). Returns rows written."""
        if not rows:
            return 0
        self._ensure_confluence_quote_table()

        def _do() -> int:
            n = 0
            with self._connect() as conn:
                for row in rows:
                    ticker = str(row.get("ticker") or "").upper().strip()
                    ts_utc = row.get("ts_utc")
                    ts_et = row.get("ts_et")
                    if not ticker or ts_utc is None or not ts_et:
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO confluence_quote_ticks
                            (ticker, ts_utc, ts_et, last_price, chg_pct)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            ticker,
                            float(ts_utc),
                            str(ts_et),
                            row.get("last_price"),
                            row.get("chg_pct"),
                        ),
                    )
                    n += 1
            return n

        return _do()

    def confluence_quote_tick_inventory(self) -> dict[str, int]:
        """Read-side inventory for panel_auto thin quotes (persistence consumer)."""
        self._ensure_confluence_quote_table()

        def _do() -> dict[str, int]:
            with self._connect() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM confluence_quote_ticks"
                ).fetchone()[0]
                tickers = conn.execute(
                    "SELECT COUNT(DISTINCT ticker) FROM confluence_quote_ticks"
                ).fetchone()[0]
            return {"total_rows": int(total), "distinct_tickers": int(tickers)}

        return _do()

    def fetch_latest_confluence_quote_chg(
        self, tickers: list[str]
    ) -> dict[str, Optional[float]]:
        """Latest ``chg_pct`` per symbol from ``confluence_quote_ticks`` (thin quote store)."""
        if not tickers:
            return {}
        self._ensure_confluence_quote_table()
        want = [str(t).upper().strip() for t in tickers if str(t).strip()]
        if not want:
            return {}
        out: dict[str, Optional[float]] = {t: None for t in want}

        def _do() -> dict[str, Optional[float]]:
            with self._connect() as conn:
                for sym in want:
                    row = conn.execute(
                        """
                        SELECT chg_pct FROM confluence_quote_ticks
                        WHERE ticker = ? COLLATE NOCASE
                        ORDER BY ts_utc DESC LIMIT 1
                        """,
                        (sym,),
                    ).fetchone()
                    if row is None or row[0] is None:
                        continue
                    try:
                        v = float(row[0])
                        if math.isfinite(v):
                            out[sym] = v
                    except (TypeError, ValueError):
                        pass
            return out

        return _do()

    def fetch_confluence_quote_chg_as_of(
        self,
        ts_utc: float,
        tickers: list[str],
    ) -> dict[str, Optional[float]]:
        """``chg_pct`` per symbol at or before ``ts_utc`` from ``confluence_quote_ticks``."""
        if not tickers:
            return {}
        self._ensure_confluence_quote_table()
        want = [str(t).upper().strip() for t in tickers if str(t).strip()]
        if not want:
            return {}
        out: dict[str, Optional[float]] = {t: None for t in want}

        def _do() -> dict[str, Optional[float]]:
            with self._connect() as conn:
                for sym in want:
                    row = conn.execute(
                        """
                        SELECT chg_pct FROM confluence_quote_ticks
                        WHERE ticker = ? COLLATE NOCASE
                          AND ts_utc <= ?
                          AND chg_pct IS NOT NULL
                        ORDER BY ts_utc DESC LIMIT 1
                        """,
                        (sym, float(ts_utc)),
                    ).fetchone()
                    if row is None or row[0] is None:
                        continue
                    try:
                        v = float(row[0])
                        if math.isfinite(v):
                            out[sym] = v
                    except (TypeError, ValueError):
                        pass
            return out

        return _do()

    def logging_universe_sync_panel_auto(self, panel_candidates: list[str], now_ts: float) -> dict[str, Any]:
        """
        Upsert ``panel_auto`` rows — cross-instrument panel symbols discovered from the
        market-context panel. The ``panel_auto`` CATEGORY records how a ticker was enrolled
        (auto, from the panel) — not how much data it gets: since 2026-08-25 (RC-482/RC-483,
        universal collection) panel_auto tickers take full option-chain snapshot rotation on
        the same terms as every other enrolled ticker (the roster loops in server.py include
        them). They also still feed the thin ``confluence_quote_ticks`` path via
        ``fetch_market_context``.

        Does not alter existing ``core`` / ``user_persisted`` / ``pinned`` rows. Drops ``panel_auto``
        rows no longer in the desired panel list (e.g. holdings table refresh).
        """
        from production_universe import filter_valid_tickers, is_valid_production_ticker, normalize_production_ticker

        want_list = [normalize_production_ticker(x) for x in filter_valid_tickers(panel_candidates)]
        want_list = [t for t in want_list if t and is_valid_production_ticker(t)]
        want = frozenset(want_list)

        def _do() -> dict[str, Any]:
            upserted = 0
            with self._connect() as conn:
                if not want:
                    conn.execute("DELETE FROM logging_universe WHERE category = 'panel_auto'")
                    return {"upserted": 0, "desired": 0, "symbols": []}

                qmarks = ",".join("?" * len(want))
                conn.execute(
                    f"""
                    DELETE FROM logging_universe
                    WHERE category = 'panel_auto'
                      AND UPPER(ticker) NOT IN ({qmarks})
                    """,
                    tuple(sorted(want)),
                )

                for sym in want_list:
                    row = conn.execute(
                        "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                        (sym,),
                    ).fetchone()
                    cat = str(row[0]) if row else None
                    if cat is None:
                        conn.execute(
                            """
                            INSERT INTO logging_universe
                                (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                            VALUES (?, 'panel_auto', 'market_context_panel_v1', ?, ?)
                            """,
                            (sym, now_ts, now_ts),
                        )
                        upserted += 1
                    elif cat == "panel_auto":
                        conn.execute(
                            """
                            UPDATE logging_universe SET
                                last_seen_ts_utc = ?,
                                enrollment_source = 'market_context_panel_v1'
                            WHERE ticker = ? COLLATE NOCASE AND category = 'panel_auto'
                            """,
                            (now_ts, sym),
                        )
                        upserted += 1
                    elif cat in ("core", "user_persisted", "pinned"):
                        continue

            return {"upserted": upserted, "desired": len(want), "symbols": want_list}

        return _do()

    def logging_universe_sync_core(self, core_tickers: list[str], now_ts: float) -> None:
        """Upsert core symbols — always category core (authoritative list from server)."""

        def _do() -> None:
            with self._connect() as conn:
                for raw in core_tickers:
                    t = ticker_storage_key(raw)  # RC-345/F25: canonical enrollment write identity
                    if not t:
                        continue
                    conn.execute(
                        """
                        INSERT INTO logging_universe
                            (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                        VALUES (?, 'core', 'core_bootstrap', ?, ?)
                        ON CONFLICT(ticker) DO UPDATE SET
                            category='core',
                            enrollment_source='core_bootstrap',
                            last_seen_ts_utc=excluded.last_seen_ts_utc
                        """,
                        (t, now_ts, now_ts),
                    )

        _do()

    def logging_universe_upsert_user_persisted(
        self, ticker: str, enrollment_source: str, now_ts: float
    ) -> None:
        """Enroll a non-core symbol for persistent background logging."""
        from production_universe import is_valid_production_ticker, normalize_production_ticker

        t = normalize_production_ticker(ticker)
        if not t:
            return
        if not is_valid_production_ticker(t):
            raise ValueError(
                f"logging_universe_upsert_user_persisted: refusing invalid ticker {ticker!r} "
                f"(normalized {t!r})"
            )

        def _do() -> None:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                    (t,),
                ).fetchone()
                if cur is None:
                    conn.execute(
                        """
                        INSERT INTO logging_universe
                            (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (t, "user_persisted", enrollment_source, now_ts, now_ts),
                    )
                elif cur[0] == "core":
                    conn.execute(
                        "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                        (now_ts, t),
                    )
                elif cur[0] == "pinned":
                    conn.execute(
                        "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                        (now_ts, t),
                    )
                else:
                    # Provenance is WRITE-ONCE (audit round 2, 2026-08-25): re-upserting an
                    # existing row used to overwrite enrollment_source, so a later touch —
                    # measured: a pytest healer stamped its own name onto the 13 newest user
                    # enrollments — destroyed the when/how of every real enrollment. Only
                    # last_seen moves on re-upsert; the original source stands.
                    conn.execute(
                        """
                        UPDATE logging_universe SET
                            last_seen_ts_utc = ?
                        WHERE ticker = ? COLLATE NOCASE AND category = 'user_persisted'
                        """,
                        (now_ts, t),
                    )

        _do()

    def logging_universe_upsert_pinned(
        self, ticker: str, enrollment_source: str, now_ts: float
    ) -> None:
        """Protect symbol from FIFO eviction (not a core ticker)."""
        from production_universe import is_valid_production_ticker, normalize_production_ticker

        t = normalize_production_ticker(ticker)
        if not t:
            return
        if not is_valid_production_ticker(t):
            raise ValueError(
                f"logging_universe_upsert_pinned: refusing invalid ticker {ticker!r} "
                f"(normalized {t!r})"
            )

        def _do() -> None:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                    (t,),
                ).fetchone()
                if cur is None:
                    conn.execute(
                        """
                        INSERT INTO logging_universe
                            (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                        VALUES (?, 'pinned', ?, ?, ?)
                        """,
                        (t, enrollment_source, now_ts, now_ts),
                    )
                elif cur[0] == "core":
                    conn.execute(
                        "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                        (now_ts, t),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE logging_universe SET
                            category = 'pinned',
                            enrollment_source = ?,
                            last_seen_ts_utc = ?
                        WHERE ticker = ? COLLATE NOCASE
                        """,
                        (enrollment_source, now_ts, t),
                    )

        _do()

    def logging_universe_unpin_to_user_persisted(self, ticker: str, now_ts: float) -> bool:
        """Downgrade pinned → user_persisted (evictable). Core unchanged."""
        t = ticker_storage_key(ticker)  # RC-345/F25: canonical identity — update hits the $-canonical row via any alias

        def _do() -> bool:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                    (t,),
                ).fetchone()
                if not cur or cur[0] != "pinned":
                    return False
                conn.execute(
                    """
                    UPDATE logging_universe SET
                        category = 'user_persisted',
                        enrollment_source = 'unpinned_from_pin',
                        last_seen_ts_utc = ?
                    WHERE ticker = ? COLLATE NOCASE
                    """,
                    (now_ts, t),
                )
                return True

        return _do()

    def logging_universe_remove_user_persisted(self, ticker: str) -> bool:
        t = ticker_storage_key(ticker)  # RC-345/F25: canonical identity — delete hits the $-canonical row via any alias

        def _do() -> bool:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    DELETE FROM logging_universe
                    WHERE ticker = ? COLLATE NOCASE AND category = 'user_persisted'
                    """,
                    (t,),
                )
                return cur.rowcount > 0

        return _do()

    def logging_universe_remove_non_core(self, ticker: str) -> bool:
        """Remove pinned or user_persisted row; never core."""
        t = ticker_storage_key(ticker)  # RC-345/F25: canonical identity — delete hits the $-canonical row via any alias

        def _do() -> bool:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    DELETE FROM logging_universe
                    WHERE ticker = ? COLLATE NOCASE AND category IN ('user_persisted', 'pinned')
                    """,
                    (t,),
                )
                return cur.rowcount > 0

        return _do()

    def logging_universe_prune_invalid_enrollments(self) -> list[str]:
        """
        Remove invalid user_persisted/pinned rows (migration fragments, corrupted keys).

        Core rows are never touched.
        """
        from production_universe import is_valid_production_ticker, normalize_production_ticker

        removed: list[str] = []

        def _do() -> None:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT ticker, category
                    FROM logging_universe
                    WHERE category IN ('user_persisted', 'pinned', 'panel_auto')
                    """
                ).fetchall()
                for r in rows:
                    raw = str(r[0] or "")
                    cat = str(r[1] or "")
                    t = normalize_production_ticker(raw)
                    if is_valid_production_ticker(t):
                        continue
                    cur = conn.execute(
                        "DELETE FROM logging_universe WHERE ticker = ? COLLATE NOCASE AND category = ?",
                        (raw, cat),
                    )
                    if cur.rowcount and int(cur.rowcount) > 0:
                        removed.append(raw)

        _do()
        return removed

    def logging_universe_record_eviction(
        self,
        *,
        evicted_ticker: str,
        evicted_ts_utc: float,
        reason: str,
        cap_limit: Optional[int] = None,
        incoming_ticker: Optional[str] = None,
        incoming_enrollment_source: Optional[str] = None,
    ) -> None:
        ev = ticker_storage_key(evicted_ticker)  # RC-345/F25: canonical eviction-audit identity
        inc = ticker_storage_key(incoming_ticker) if incoming_ticker else incoming_ticker

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO logging_universe_eviction_log
                        (evicted_ticker, evicted_ts_utc, reason, cap_limit,
                         incoming_ticker, incoming_enrollment_source)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        ev,
                        evicted_ts_utc,
                        reason,
                        cap_limit,
                        inc,
                        incoming_enrollment_source,
                    ),
                )

        _do()

    def logging_universe_recent_evictions(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM logging_universe_eviction_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def logging_universe_eviction_candidates_fifo(self) -> list[str]:
        """user_persisted only, oldest enrolled first — next eviction order."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker FROM logging_universe
                WHERE category = 'user_persisted'
                ORDER BY enrolled_ts_utc ASC, ticker COLLATE NOCASE
                """
            ).fetchall()
            return _dedup_preserve([ticker_storage_key(r[0]) for r in rows])  # RC-345/F25: canonical read identity

    def logging_universe_protected_tickers(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker FROM logging_universe
                WHERE category IN ('core', 'pinned', 'panel_auto')
                ORDER BY ticker COLLATE NOCASE
                """
            ).fetchall()
            return _dedup_preserve([ticker_storage_key(r[0]) for r in rows])  # RC-345/F25: canonical read identity

    def logging_universe_pinned_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM logging_universe WHERE category = 'pinned'"
            ).fetchone()
            # CAPS finding (2026-09-21, db.py decomposition audit): `or 0` here was dead --
            # COUNT(*) with no GROUP BY always returns exactly one row and never NULL, so the
            # fallback could never fire. Removed rather than allowlisted: the gate is right
            # that a silent-zero fallback on a value that CAN be absent is a real hazard
            # elsewhere; here the value provably cannot be absent, so the honest fix is to
            # stop writing code that looks like it might be.
            return int(row[0])

    def logging_universe_snapshot_ticker_orphans(self) -> list[str]:
        """Distinct snapshot tickers (canonical timeframe) with no logging_universe row.

        Non-empty indicates Issue-22 drift (e.g. raw SQL import) — normal server paths enroll
        before insert_snapshot via server._register_tracked_ticker. Used by /api/logger/status
        and tools/_ticker_coverage_audit_v1.py.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT s.ticker FROM snapshots s
                WHERE s.timeframe = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM logging_universe lu
                    WHERE lu.ticker = s.ticker COLLATE NOCASE
                  )
                ORDER BY s.ticker COLLATE NOCASE
                """,
                (CANONICAL_TIMEFRAME,),
            ).fetchall()
            return [str(r[0]) for r in rows]

    def logging_universe_authoritative_tickers(self) -> list[str]:
        """Sole enrollment authority (Issue 22): core + pinned + panel_auto + user_persisted.

        Background logger, ml_scheduler, and bulk train entry points use this same set.
        ``panel_auto`` is maintained by ``logging_universe_sync_panel_auto`` (market_context panel).
        Rows observed in snapshots are not authority — enroll via server/UI/API or sync_core.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker FROM logging_universe
                WHERE category IN ('core', 'pinned', 'panel_auto', 'user_persisted')
                ORDER BY CASE category
                    WHEN 'core' THEN 0
                    WHEN 'pinned' THEN 1
                    WHEN 'panel_auto' THEN 2
                    WHEN 'user_persisted' THEN 3
                    ELSE 4 END,
                    ticker COLLATE NOCASE
                """
            ).fetchall()
            return _dedup_preserve([ticker_storage_key(r[0]) for r in rows])  # RC-345/F25: canonical read identity (legacy bare rows resolve on-read)

    def logging_universe_scheduler_tickers(self) -> list[str]:
        """Alias for scheduler paths — identical to logging_universe_authoritative_tickers."""
        return self.logging_universe_authoritative_tickers()

    def logging_universe_migration_completed(self, name: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM logging_universe_migration_log WHERE name = ?",
                (name,),
            ).fetchone()
            return row is not None

    def logging_universe_migration_mark(
        self, name: str, ts: float, source_sha256: str, detail: dict
    ) -> None:
        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO logging_universe_migration_log
                        (name, completed_ts_utc, source_sha256, detail_json)
                    VALUES (?,?,?,?)
                    """,
                    (name, ts, source_sha256, json.dumps(detail)),
                )

        _do()

    def logging_universe_import_legacy_json_tickers(
        self,
        tickers: list[str],
        enrollment_source: str,
        now_ts: float,
        core_tickers: list[str],
    ) -> int:
        """Upsert deduped non-core symbols; returns rows touched. Caller runs inside transaction."""
        core_u = {(c or "").upper().strip() for c in core_tickers}
        tickers_copy = list(tickers)
        enr = enrollment_source
        nt = now_ts

        def _do() -> int:
            n = 0
            seen: set[str] = set()
            with self._connect() as conn:
                for raw in tickers_copy:
                    t = str(raw).upper().strip()
                    if not t or t.startswith("$") or t in core_u or t in seen:
                        continue
                    seen.add(t)
                    cur = conn.execute(
                        "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                        (t,),
                    ).fetchone()
                    if cur is None:
                        conn.execute(
                            """
                            INSERT INTO logging_universe
                              (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                            VALUES (?, 'user_persisted', ?, ?, ?)
                            """,
                            (t, enr, nt, nt),
                        )
                        n += 1
                    elif cur[0] == "user_persisted":
                        conn.execute(
                            """
                            UPDATE logging_universe SET
                              last_seen_ts_utc = ?,
                              enrollment_source = COALESCE(enrollment_source, ?)
                            WHERE ticker = ? COLLATE NOCASE
                            """,
                            (nt, enr, t),
                        )
                        n += 1
            return n

        return _do()

    def logging_universe_migrate_legacy_json_file(
        self,
        *,
        primary_path: Path,
        archive_path: Path,
        core_tickers: list[str],
    ) -> dict:
        """
        Idempotent one-time import of legacy [.logger_tickers.json] list into logging_universe.
        Uses a single transaction; archives primary only after successful commit.
        """
        mname = "legacy_logger_tickers_json_v1"
        if self.logging_universe_migration_completed(mname):
            return {"status": "already_completed", "migration": mname}
        src = primary_path if primary_path.is_file() else None
        archived_only = False
        if src is None and archive_path.is_file():
            src = archive_path
            archived_only = True
        if src is None:
            self.logging_universe_migration_mark(
                mname, _wall_time.time(), "", {"detail": "no_source_file"}
            )
            return {"status": "skipped_no_source", "migration": mname}
        raw_bytes = src.read_bytes()
        h = hashlib.sha256(raw_bytes).hexdigest()
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            return {"status": "error_json", "migration": mname, "error": str(e)}
        if not isinstance(payload, list):
            return {"status": "error_not_list", "migration": mname}
        tickers = [str(x) for x in payload]
        core_u = {(c or "").upper().strip() for c in core_tickers}
        expected = sorted(
            {
                str(t).upper().strip()
                for t in tickers
                if t
                and not str(t).startswith("$")
                and str(t).upper().strip() not in core_u
            }
        )
        now = _wall_time.time()

        def _body() -> dict:
            # Was a raw sqlite3.connect() (audit finding, RC-573): every other write path in
            # this class routes through self._connect(), which also installs the production
            # DROP/DETACH authorizer guard (db_safety.maybe_install_sql_guard_on_connection) --
            # this one-time migration silently had no structural-safety net. self._connect()
            # is a drop-in replacement (same row_factory + configure_sqlite_connection this
            # already did manually); BEGIN IMMEDIATE/commit/rollback/close stay explicit below,
            # unchanged from the manual-transaction control this method deliberately wants.
            conn = self._connect(timeout_sec=30.0)
            try:
                conn.execute("BEGIN IMMEDIATE")
                seen: set[str] = set()
                imported = 0
                for raw in tickers:
                    t = str(raw).upper().strip()
                    if not t or t.startswith("$") or t in core_u or t in seen:
                        continue
                    seen.add(t)
                    cur = conn.execute(
                        "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                        (t,),
                    ).fetchone()
                    if cur is None:
                        conn.execute(
                            """
                            INSERT INTO logging_universe
                              (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                            VALUES (?, 'user_persisted', ?, ?, ?)
                            """,
                            (t, "migrated_logger_tickers_json", now, now),
                        )
                        imported += 1
                    elif cur[0] == "user_persisted":
                        conn.execute(
                            """
                            UPDATE logging_universe SET last_seen_ts_utc = ?
                            WHERE ticker = ? COLLATE NOCASE AND category = 'user_persisted'
                            """,
                            (now, t),
                        )
                n_db = conn.execute(
                    """
                    SELECT COUNT(*) FROM logging_universe
                    WHERE category = 'user_persisted'
                      AND enrollment_source = 'migrated_logger_tickers_json'
                    """
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO logging_universe_migration_log
                        (name, completed_ts_utc, source_sha256, detail_json)
                    VALUES (?,?,?,?)
                    """,
                    (
                        mname,
                        now,
                        h,
                        json.dumps(
                            {
                                "source_path": str(src.resolve()),
                                "archived_only": archived_only,
                                "expected_non_core_symbols": expected,
                                "upsert_touched": imported,
                                "rows_migrated_enrollment": int(n_db),
                            }
                        ),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return {
                "status": "imported",
                "migration": mname,
                "sha256": h,
                "upsert_touched": imported,
                "archived_only": archived_only,
            }

        out = _body()
        if not archived_only and primary_path.is_file():
            try:
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(primary_path), str(archive_path))
            except OSError as e:
                log.warning("legacy logger json archive replace failed: %s", e)
        return out

    def logging_universe_migrate_scheduler_companion_json(
        self,
        *,
        primary_path: Path,
        archive_path: Path,
    ) -> dict:
        """One-time: data/user_scheduler_tickers.json → logging_universe (Issue 22 SSOT)."""
        mname = "scheduler_user_tickers_json_v1"
        if self.logging_universe_migration_completed(mname):
            return {"status": "already_completed", "migration": mname}
        src = primary_path if primary_path.is_file() else None
        archived_only = False
        if src is None and archive_path.is_file():
            src = archive_path
            archived_only = True
        if src is None:
            self.logging_universe_migration_mark(
                mname, _wall_time.time(), "", {"detail": "no_source_file"}
            )
            return {"status": "skipped_no_source", "migration": mname}
        raw = src.read_bytes()
        h = hashlib.sha256(raw).hexdigest()
        try:
            data = json.loads(raw.decode("utf-8"))
            raw_list = data.get("tickers") if isinstance(data, dict) else data
            if not isinstance(raw_list, list):
                raise ValueError("not_a_list")
        except Exception as e:
            return {"status": "error_json", "migration": mname, "error": str(e)}
        now = _wall_time.time()

        def _body() -> dict:
            # Was a raw sqlite3.connect() (audit finding, RC-573) -- see the identical fix's
            # comment in logging_universe_migrate_legacy_json_file just above.
            conn = self._connect(timeout_sec=30.0)
            try:
                conn.execute("BEGIN IMMEDIATE")
                n = 0
                seen: set[str] = set()
                for item in raw_list:
                    t = str(item).upper().strip()
                    if not t or t.startswith("$") or t in seen:
                        continue
                    seen.add(t)
                    cur = conn.execute(
                        "SELECT category FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                        (t,),
                    ).fetchone()
                    if cur is None:
                        conn.execute(
                            """
                            INSERT INTO logging_universe
                              (ticker, category, enrollment_source, enrolled_ts_utc, last_seen_ts_utc)
                            VALUES (?, 'user_persisted', ?, ?, ?)
                            """,
                            (t, "migrated_scheduler_user_tickers_json", now, now),
                        )
                        n += 1
                    elif cur[0] == "user_persisted":
                        conn.execute(
                            """
                            UPDATE logging_universe SET last_seen_ts_utc = ?
                            WHERE ticker = ? COLLATE NOCASE AND category = 'user_persisted'
                            """,
                            (now, t),
                        )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO logging_universe_migration_log
                        (name, completed_ts_utc, source_sha256, detail_json)
                    VALUES (?,?,?,?)
                    """,
                    (
                        mname,
                        now,
                        h,
                        json.dumps(
                            {
                                "source": str(src.resolve()),
                                "archived_only": archived_only,
                                "rows_touched": n,
                            }
                        ),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return {"status": "imported", "migration": mname, "rows_touched": n}

        out = _body()
        if not archived_only and primary_path.is_file():
            try:
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(primary_path), str(archive_path))
            except OSError as e:
                log.warning("scheduler json archive replace failed: %s", e)
        return out

    def logging_universe_touch_seen(self, ticker: str, now_ts: float) -> None:
        t = ticker_storage_key(ticker)  # RC-345/F25: canonical identity — touch hits the $-canonical row via any alias
        nt = now_ts

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE logging_universe SET last_seen_ts_utc = ? WHERE ticker = ? COLLATE NOCASE",
                    (nt, t),
                )

        _do()

    def logging_universe_touch_background_log(self, ticker: str, ts_utc: float) -> None:
        t = ticker_storage_key(ticker)  # RC-345/F25: canonical identity — touch hits the $-canonical row via any alias
        tu = ts_utc

        def _do() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE logging_universe SET last_background_log_ts_utc = ?
                    WHERE ticker = ? COLLATE NOCASE
                    """,
                    (tu, t),
                )

        _do()

    def logging_universe_user_persisted_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM logging_universe WHERE category = 'user_persisted'"
            ).fetchone()
            # See logging_universe_pinned_count's identical comment: COUNT(*) with no
            # GROUP BY is never NULL, so `or 0` was dead code, not a real absence guard.
            return int(row[0])

    def logging_universe_oldest_user_persisted_ticker(self) -> Optional[str]:
        """Must match eviction FIFO head — single deterministic eviction victim."""
        fifo = self.logging_universe_eviction_candidates_fifo()
        return fifo[0] if fifo else None

    def logging_universe_list_rows(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticker, category, enrollment_source,
                       enrolled_ts_utc, last_seen_ts_utc, last_background_log_ts_utc
                FROM logging_universe
                ORDER BY CASE category
                    WHEN 'core' THEN 0
                    WHEN 'pinned' THEN 1
                    WHEN 'panel_auto' THEN 2
                    WHEN 'user_persisted' THEN 3
                    ELSE 4 END,
                    ticker COLLATE NOCASE
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def logging_universe_list_rows_audit(self) -> list[dict]:
        """Rows + deterministic eviction_status + fifo position for user_persisted."""
        fifo = self.logging_universe_eviction_candidates_fifo()
        fifo_pos = {t: i + 1 for i, t in enumerate(fifo)}
        prot = set(self.logging_universe_protected_tickers())
        out: list[dict] = []
        for row in self.logging_universe_list_rows():
            d = dict(row)
            cat = d.get("category") or ""
            if cat in ("core", "pinned", "panel_auto"):
                d["eviction_status"] = "protected"
                d["eviction_fifo_position"] = None
            elif cat == "user_persisted":
                d["eviction_status"] = "eligible"
                d["eviction_fifo_position"] = fifo_pos.get(ticker_storage_key(d["ticker"]))  # RC-345/F25: canonical audit key
            else:
                d["eviction_status"] = "unknown"
                d["eviction_fifo_position"] = None
            d["is_protected"] = ticker_storage_key(d["ticker"]) in prot  # RC-345/F25: canonical audit key
            out.append(d)
        return out

    # Category protection priority — the SAME hierarchy the eviction/protection logic already uses.
    # Used as the deterministic collision-merge rule when a legacy alias row (e.g. "SPX") must fold
    # into its canonical form ("$SPX") that already exists.
    _LU_CATEGORY_PRIORITY = {"core": 0, "pinned": 1, "panel_auto": 2, "user_persisted": 3}

    def logging_universe_migrate_canonical_ticker_identity(
        self, *, dry_run: bool = True
    ) -> dict[str, Any]:
        """RC-345/F25 — bring persisted ``logging_universe`` rows onto the ONE canonical ticker
        identity (``ticker_storage_key``). Legacy bare-root index rows (e.g. ``SPX``) become
        ``$SPX``; a legacy row that collides with an existing canonical row is MERGED by a
        deterministic, evidence-based rule.

        Properties (institutional-grade):
          * deterministic + transactional (single transaction; ``dry_run`` rolls back)
          * idempotent (a re-run after a real run reports zero changes)
          * explicit before/after counts + per-ticker rewrite report
          * collision detection with a proven merge rule (never invents state)
          * fail-closed: an unresolvable collision aborts the whole transaction, mutating nothing

        Merge rule for ``legacy_alias -> canonical`` when BOTH exist (all deterministic):
          category         = stronger of the two (core > pinned > panel_auto > user_persisted)
          enrollment_source= the stronger-category row's source (ties: canonical row's)
          enrolled_ts_utc  = MIN (earliest original enrollment preserved)
          last_seen_ts_utc = MAX (most recent activity preserved)
          last_background_log_ts_utc = MAX (most recent activity preserved)
        No row field is silently discarded — the surviving row is the field-wise best of both.
        """
        self._ensure_logging_universe_table()
        self._ensure_logging_universe_aux_tables()

        def _do() -> dict[str, Any]:
            report: dict[str, Any] = {
                "dry_run": bool(dry_run),
                "rows_before": 0,
                "rows_after": 0,
                "renames": [],       # legacy -> canonical (no collision)
                "merges": [],        # legacy -> canonical (collision merged)
                "unchanged": 0,
                "aborted_collision": None,
            }
            with self._connect() as conn:
                conn.execute("BEGIN")
                try:
                    rows = conn.execute(
                        "SELECT ticker, category, enrollment_source, enrolled_ts_utc, "
                        "last_seen_ts_utc, last_background_log_ts_utc FROM logging_universe"
                    ).fetchall()
                    report["rows_before"] = len(rows)
                    by_ticker = {str(r[0]): dict(zip(
                        ("ticker", "category", "enrollment_source", "enrolled_ts_utc",
                         "last_seen_ts_utc", "last_background_log_ts_utc"), r)) for r in rows}

                    for stored, row in list(by_ticker.items()):
                        canon = ticker_storage_key(stored)
                        if canon == stored:
                            report["unchanged"] += 1
                            continue
                        # A COLLATE NOCASE PK already folds pure-case variants; the only rewrites
                        # are true alias changes (bare index root -> $-prefixed canonical).
                        if canon in by_ticker and canon != stored:
                            other = by_ticker[canon]
                            merged = self._lu_merge_rows(row, other)
                            if merged is None:
                                report["aborted_collision"] = {
                                    "legacy": stored, "canonical": canon,
                                    "reason": "no proven safe merge",
                                }
                                conn.execute("ROLLBACK")
                                return report
                            conn.execute(
                                "DELETE FROM logging_universe WHERE ticker = ? COLLATE NOCASE",
                                (stored,),
                            )
                            conn.execute(
                                """
                                UPDATE logging_universe SET
                                    category = ?, enrollment_source = ?, enrolled_ts_utc = ?,
                                    last_seen_ts_utc = ?, last_background_log_ts_utc = ?
                                WHERE ticker = ? COLLATE NOCASE
                                """,
                                (merged["category"], merged["enrollment_source"],
                                 merged["enrolled_ts_utc"], merged["last_seen_ts_utc"],
                                 merged["last_background_log_ts_utc"], canon),
                            )
                            by_ticker[canon] = {**merged, "ticker": canon}
                            del by_ticker[stored]
                            report["merges"].append({"legacy": stored, "canonical": canon,
                                                     "category": merged["category"]})
                        else:
                            conn.execute(
                                "UPDATE logging_universe SET ticker = ? WHERE ticker = ? COLLATE NOCASE",
                                (canon, stored),
                            )
                            by_ticker[canon] = {**row, "ticker": canon}
                            del by_ticker[stored]
                            report["renames"].append({"legacy": stored, "canonical": canon})

                    report["rows_after"] = conn.execute(
                        "SELECT COUNT(*) FROM logging_universe"
                    ).fetchone()[0]

                    if dry_run:
                        conn.execute("ROLLBACK")
                    else:
                        conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            return report

        return _do()

    def _lu_merge_rows(self, a: dict, b: dict) -> Optional[dict]:
        """Deterministic field-wise merge of a legacy-alias row and its canonical row.
        Returns None only if neither category is recognized (fail-closed)."""
        pa = self._LU_CATEGORY_PRIORITY.get(str(a.get("category")))
        pb = self._LU_CATEGORY_PRIORITY.get(str(b.get("category")))
        if pa is None or pb is None:
            return None
        strong = a if pa < pb else b  # lower priority number = stronger; ties -> b (canonical row)

        def _min(x, y):
            xs = [v for v in (x, y) if v is not None]
            return min(xs) if xs else None

        def _max(x, y):
            xs = [v for v in (x, y) if v is not None]
            return max(xs) if xs else None

        return {
            "category": strong["category"],
            "enrollment_source": strong.get("enrollment_source"),
            "enrolled_ts_utc": _min(a.get("enrolled_ts_utc"), b.get("enrolled_ts_utc")),
            "last_seen_ts_utc": _max(a.get("last_seen_ts_utc"), b.get("last_seen_ts_utc")),
            "last_background_log_ts_utc": _max(
                a.get("last_background_log_ts_utc"), b.get("last_background_log_ts_utc")),
        }
