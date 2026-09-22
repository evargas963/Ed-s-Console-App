"""Snapshot writes + horizon-outcome labeling + similarity search, extracted from EdDB
(RC-REHAB-1, db.py decomposition, 2026-09-21, slice 3).

The money-path data layer: every write that feeds ML training/prediction (insert_snapshot,
upsert_1m_bars, fill_outcomes and its bulk/backfill variants) and every read the prediction
engine uses (get_similar_setups' progressive-relaxation search, get_recent_snapshots,
get_avg_move, count_snapshots).

SnapshotOutcomesMixin is mixed into EdDB (db.py), exactly like slices 1-2's mixins: every
method here already assumed self._connect()/self._tier1_snapshot_write() from the host class.

MONKEYPATCH SAFETY (read before editing): _apply_bar_based_outcome_updates,
_refresh_governed_outcomes_after_bar_mutation, _fill_outcomes_latency_log,
FILL_OUTCOMES_LIVE_BATCH_LIMIT, LIVE_BARS_REUPSERT_OVERLAP_SEC, similarity_labeled_counts,
similarity_tier_stop_viable, and similarity_empirically_viable all stay defined in db.py
itself (not moved) and are referenced here ONLY via ``db.<name>`` module-attribute access
(a lazy ``import db`` inside each method that needs one), never a bound ``from db import
X`` name. tests/test_db_perf_rc166_v1.py monkeypatches db_mod._refresh_governed_outcomes_
after_bar_mutation directly on the module object to prove a real concurrency contract (the
tier-1 write lock is released before the governed-outcome refresh runs); tests/test_horizon_
bar_outcomes.py does the same to FILL_OUTCOMES_LIVE_BATCH_LIMIT. A bound import here would
silently defeat both monkeypatches -- verified empirically, not assumed, before this file
was written (see the RC-REHAB-1 slice-3 commit message for the reproduction).
"""
from __future__ import annotations

import logging
import threading
import time as _wall_time
from dataclasses import asdict
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    # Type-hint only -- a plain top-level `from db import SnapshotRow` would be a real
    # circular import (db.py imports THIS module before its own SnapshotRow class is
    # defined further down); TYPE_CHECKING guards this out at runtime entirely.
    from db import SnapshotRow

from instrument_identity import ticker_storage_key
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME
from snapshot_access import require_snapshot_timeframe
from horizon_outcomes import (
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    OUTCOME_BAR_SPECS,
    OUTCOME_MOVEMENT_V1_SPECS,
    AUTHORITATIVE_1M_SOURCE,
)
from time_et import is_collect_window_bar_end_ts_utc
from math_exposure import (
    dist_bucket as _dist_bucket,
    bucket_lo as _bucket_lo,
    bucket_hi as _bucket_hi,
    MIN_SAMPLES_STATISTICAL,
)
from similarity_audit import (
    SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS,
    SIMILARITY_TIER_STOP_OUTCOME_COLUMNS,
    query_context_for_similarity,
    structured_constraints_for_tier,
    relaxed_constraints_vs_previous_tier,
    withheld_horizons_report,
    tier_stop_weak_horizons,
    weakest_tracked_horizons,
    widening_summary_from_tiers,
)

log = logging.getLogger(__name__)


class SnapshotOutcomesMixin:
    """Mixed into EdDB. Assumes self._connect()/self._tier1_snapshot_write() from the host
    class, and db.<name> module-attribute access for the monkeypatch-sensitive helpers named
    in this module's own docstring above."""

    def insert_snapshot(self, snap: SnapshotRow) -> int:
        """Insert a snapshot row. Returns the new snapshot_id.

        RULE: All live snapshot inserts MUST use timeframe=CANONICAL_TIMEFRAME (1m).
        Non-canonical timeframe is overridden and logged. This prevents legacy 5m
        writes from any code path.
        """
        d = asdict(snap)
        d.pop("snapshot_id", None)  # let DB assign

        # execution_identity_v1 fail-closed coherence: a MODEL_DERIVED row must
        # carry its identity pair; a NOT_APPLICABLE (quote-only) row must not.
        # When identity fields arrive without a class, the row IS model-derived.
        # (Trigger-level linkage against the identity table + ledger enforces
        # registration and same-identity-per-decision below the Python layer.)
        # Schwab CSV authority checked: yes
        # CSV row(s): NO_SCHWAB_EQUIVALENT — execution-identity provenance
        #   linkage only; no market field read, derived, or emitted here.
        # Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE (n/a — no
        #   derivation in this block).
        # All consumers checked: yes — identity columns are additive; every
        #   existing snapshot reader ignores unknown columns by name.
        # SCHWAB_CSV_CHECKED
        _xid_class = d.get("execution_identity_class")
        _xid = d.get("execution_identity_sha256")
        _did = d.get("decision_id")
        if _xid_class or _xid or _did:
            from execution_identity import require_identity_for_model_derived_write

            d["execution_identity_class"] = require_identity_for_model_derived_write(
                is_model_derived=(_xid_class != "NOT_APPLICABLE"),
                decision_id=_did,
                execution_identity_sha256=_xid,
                surface="snapshots",
            )

        # Enforce canonical 1m — fail loudly if caller passed wrong timeframe
        # CAPS finding (2026-09-22, db.py decomposition audit): the `.get(..., "")` defaults
        # below were dead -- SnapshotRow.ticker/timeframe are REQUIRED dataclass fields (no
        # default), so asdict(snap) always includes both keys. Direct indexing instead of a
        # fallback that can never fire.
        incoming_tf = d["timeframe"]
        if incoming_tf != CANONICAL_TIMEFRAME:
            log.warning(
                "insert_snapshot: timeframe=%r != canonical %r — OVERRIDING to 1m (caller bug or stale process)",
                incoming_tf,
                CANONICAL_TIMEFRAME,
            )
            d["timeframe"] = CANONICAL_TIMEFRAME

        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        sql = f"INSERT INTO snapshots ({cols}) VALUES ({placeholders})"
        vals = list(d.values())
        tkr_w = str(d["ticker"] or "")

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(sql, vals)
                return int(cur.lastrowid)

        return self._tier1_snapshot_write("insert_snapshot", tkr_w or None, _do)

    def upsert_1m_bars(
        self,
        ticker: str,
        bars: list,
        *,
        refresh_governed_outcomes: bool = True,
    ) -> int:
        """
        Authoritative canonical 1m series for horizon labels (Schwab price history + server accumulator).
        Completed bars only; bar_start_ts_utc matches Candle.ts (epoch seconds, bar open).

        Ticker key uses ticker_storage_key (Issue 19): e.g. SPX -> $SPX for parity with snapshots
        and pin_neutral / fill_outcomes joins; $SPX unchanged.

        By default, after each successful upsert, governed BAR_ANCHOR_V1 snapshot outcomes that
        depend on any mutated bar_start are recomputed in the same connection so stored labels
        cannot drift. Historical bulk backfills may pass ``refresh_governed_outcomes=False`` and
        run ``refresh_all_governed_bar_anchor_outcomes_v1`` once after the batch.

        Returns count of rows written (after timestamp/OHLC validation), 0 if none.
        """
        import db  # module-attribute access only -- see this file's own docstring

        tkr = ticker_storage_key(ticker)
        if not tkr or not bars:
            return 0
        rows = []
        def _volume_or_none(raw):
            if raw is None:
                return None
            try:
                v = float(raw)
            except (TypeError, ValueError):
                return None
            return v if v >= 0 else None

        for b in bars:
            src = AUTHORITATIVE_1M_SOURCE
            if hasattr(b, "ts"):
                ts = float(b.ts)
                o, h, lo, c = float(b.open), float(b.high), float(b.low), float(b.close)
                vol = _volume_or_none(getattr(b, "volume", None))
            elif isinstance(b, dict):
                # Multi-format external input (callers pass differently-shaped bar dicts); the
                # final `0` fallback is a deliberate poison sentinel, not a fabricated
                # timestamp -- bar_start <= 0 is rejected a few lines below ("Reject poison
                # timestamps"), so a bar missing every known key is dropped, never silently
                # written under a fake time.
                raw_ts = b.get("datetime", b.get("ts", b.get("timestamp", b.get("_ts", 0))))  # caps-ok: poison sentinel, rejected downstream by bar_start<=0 check
                try:
                    ts = float(raw_ts)
                except (TypeError, ValueError):
                    continue
                try:
                    o = float(b["open"])
                    h = float(b["high"])
                    lo = float(b["low"])
                    c = float(b["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                vol = _volume_or_none(b.get("volume"))
                if b.get("source"):
                    src = str(b["source"])
            else:
                continue
            # Unit normalization for BOTH input shapes (Candle objects and dicts): Schwab wire
            # times are epoch ms; the canonical bar grid is epoch seconds. 2026-06-09 regression:
            # Candle.ts arrived in ms via the object path (which previously skipped this), writing
            # ms-grid rows that the outcome filler could never match.
            # Canonical 60s UTC grid: snap bar open to whole-minute epoch seconds (Schwab / adapters
            # may emit sub-second noise). Large drift (>30s from nearest minute) is rejected.
            raw_ts = float(ts)
            if raw_ts > 1e10:
                raw_ts = raw_ts / 1000.0
            grid_ts = round(raw_ts / 60.0) * 60.0
            if abs(raw_ts - grid_ts) > 30.0:
                log.warning(
                    "upsert_1m_bars: skipping bar far from canonical minute grid ts=%.4f (nearest=%.1f) ticker=%s",
                    raw_ts,
                    grid_ts,
                    tkr,
                )
                continue
            if abs(raw_ts - grid_ts) > 0.25:
                log.info(
                    "upsert_1m_bars: snapped bar ts %.6f -> %.1f ticker=%s",
                    raw_ts,
                    grid_ts,
                    tkr,
                )
            bar_start = grid_ts
            # Reject poison timestamps (0/negative breaks anchor SQL and MIN(); Schwab ms→s is always >> 0).
            if bar_start <= 0:
                continue
            bar_end = bar_start + 60.0
            # RC-183 collect-window law (operator, non-negotiable): price_bars_1m persists ET
            # bar-END minutes (555, min(975, cash_close+15)] on trading days only. This is the
            # ONE write seam for the table; every producer inherits the gate here.
            if not is_collect_window_bar_end_ts_utc(bar_end):
                continue
            rows.append((tkr, bar_start, bar_end, o, h, lo, c, vol, src))
        if not rows:
            return 0
        rows_tuple = list(rows)

        def _do() -> int:
            with self._connect() as conn:
                write_rows = rows_tuple
                if refresh_governed_outcomes:
                    # LIVE-path incremental write (2026-07-03 console usability): the in-memory
                    # accumulator re-seeds days of Schwab pricehistory, and rewriting the whole
                    # list every cycle held the tier-1 write lock for seconds (17.8s first-cycle
                    # exec observed live; ~0.6s every cycle after) and recomputed governed
                    # outcomes for EVERY bar. A bar is written only when it is MISSING from the
                    # DB, its values CHANGED (mutation → governed-outcome refresh contract), or
                    # it sits in the recent overlap window (in-progress bar). Identical
                    # re-upserts of persisted history are no-ops. One narrow index-range read
                    # replaces thousands of redundant writes. Bulk backfills pass
                    # refresh_governed_outcomes=False and keep the unconditional full write.
                    lo = min(float(t[1]) for t in rows_tuple)
                    hi = max(float(t[1]) for t in rows_tuple)
                    existing: dict[float, tuple] = {
                        float(er[0]): (
                            float(er[1]), float(er[2]), float(er[3]), float(er[4]),
                            None if er[5] is None else float(er[5]),
                        )
                        for er in conn.execute(
                            "SELECT bar_start_ts_utc, open, high, low, close, volume "
                            "FROM price_bars_1m WHERE ticker = ? "
                            "AND bar_start_ts_utc BETWEEN ? AND ?",
                            (tkr, lo, hi),
                        ).fetchall()
                    }
                    r = conn.execute(
                        "SELECT MAX(bar_start_ts_utc) FROM price_bars_1m WHERE ticker = ?",
                        (tkr,),
                    ).fetchone()
                    # CAPS finding (2026-09-22): a bare MAX(...) with no GROUP BY always
                    # returns exactly one row (r is never None); r[0] itself CAN be NULL
                    # (MAX of zero matching rows) -- that half of the check is real.
                    db_max = float(r[0]) if r[0] is not None else None  # caps-ok: r[0] is a real MAX() NULL, r itself is never None from a bare aggregate fetchone()
                    if db_max is not None:
                        cutoff = db_max - db.LIVE_BARS_REUPSERT_OVERLAP_SEC

                        def _needs_write(t: tuple) -> bool:
                            bs = float(t[1])
                            if bs >= cutoff:
                                return True
                            prev = existing.get(bs)
                            if prev is None:
                                return True  # mid-history hole — repair it
                            # (open, high, low, close, volume) — REAL round-trips exactly.
                            return prev != (t[3], t[4], t[5], t[6], t[7])

                        write_rows = [t for t in rows_tuple if _needs_write(t)]
                if not write_rows:
                    return 0
                conn.executemany(
                    """
                    INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc,
                        open, high, low, close, volume, source)
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
                    write_rows,
                )
                n_written = len(write_rows)
                if refresh_governed_outcomes and write_rows:
                    # RC-166/RC-243: the refresh is DEFERRED to after the tier-1 lock is
                    # released — see the post-unlock block below. Only the bar starts travel
                    # out of the critical section.
                    _pending_refresh["starts"] = {float(r[1]) for r in write_rows}
                return n_written

        # RC-166 (root reached 2026-08-04, RC-243): the governed-outcome recompute used to run
        # INSIDE _do(), i.e. while _TIER1_SNAPSHOT_WRITE_LOCK was held, so every bar upsert held
        # the one global write lock for the whole recompute. On a 27 GB file that is precisely
        # the 38–180 s holds measured on the live console, and it is why adding bar workers made
        # the console slower rather than faster: they queue behind one another's refreshes.
        # tests/test_db_perf_rc166_v1.py has asserted this contract ("outcome refresh must not
        # hold the tier-1 lock") since 2026-07-31 and had been RED — the fix was specified and
        # never landed. Bars commit under the lock; labels are recomputed after release on a
        # separate connection, so a concurrent writer can proceed between the two.
        _pending_refresh: dict[str, set[float]] = {}

        def _post_unlock_refresh() -> None:
            """post-unlock governed outcome refresh — runs with tier-1 RELEASED."""
            starts = _pending_refresh.get("starts")
            if not starts:
                return
            with self._connect() as refresh_conn:
                db._refresh_governed_outcomes_after_bar_mutation(
                    refresh_conn,
                    tkr=tkr,
                    changed_bar_starts=starts,
                    tz=float(_wall_time.time()),
                )

        n_written_total = self._tier1_snapshot_write("upsert_1m_bars", tkr, _do)
        _post_unlock_refresh()
        return n_written_total

    def fill_outcomes(self, ticker: str, timeframe: str, ts_utc_now: float) -> None:
        """
        Universal bar-based horizon outcomes (Issue 3 forward + Issue 4 anchor).

        For each snapshot at time T (ts_utc):
          anchor_close = close of the last price_bars_1m row with bar_end_ts_utc <= T
          forward_close = close of the bar with bar_start_ts_utc = floor((T+N*60)/60)*60
          outcome_Nc = classify_direction_pts(forward_close - anchor_close,
                                              threshold_move_pts_for_slug(slug, anchor_close, atr))
          (per-horizon ATR-scaled threshold — same scale as the v2 move gate, so
           outcome_Nc is balanced on each horizon's own volatility, not a fixed 0.05% cut)

        Poll-window fills are not used. Rows must have horizon_outcome_schema_version = BAR_ANCHOR_V1.

        outcome_filled is set only when every column in OUTCOME_BAR_SPECS is non-null (backfill-queue
        completion). ML training eligibility is per-horizon (label IS NOT NULL); do not use outcome_filled there.
        """
        import db  # module-attribute access only -- see this file's own docstring

        if timeframe != CANONICAL_TIMEFRAME:
            return

        tkr = ticker_storage_key(ticker)
        if not tkr:
            return

        tz = float(ts_utc_now)
        min_snap_ts = tz - 14 * 86400.0
        # Prefetch forward bars through the longest OUTCOME_BAR_SPECS horizon (+ padding).
        _max_fwd_min = max(s[2] for s in OUTCOME_BAR_SPECS)
        _bar_start_upper = tz + float(_max_fwd_min) * 60.0 + 120.0
        tf = timeframe

        def _do() -> None:
            with self._connect() as conn:
                close_by_start: dict[float, float] = {}
                for r in conn.execute(
                    """
                    SELECT bar_start_ts_utc, close FROM price_bars_1m
                    WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
                    """,
                    (tkr, min_snap_ts - 5000.0, _bar_start_upper),
                ).fetchall():
                    close_by_start[float(r["bar_start_ts_utc"])] = float(r["close"])

                bar_end_rows = conn.execute(
                    """
                    SELECT bar_end_ts_utc, close FROM price_bars_1m
                    WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
                    ORDER BY bar_end_ts_utc ASC
                    """,
                    (tkr, min_snap_ts - 5000.0, tz),
                ).fetchall()
                bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
                bar_end_closes = [float(r["close"]) for r in bar_end_rows]

                # Prefetch outcome/valid_dir cols so _apply skips N+1 per-horizon SELECTs.
                _odir_cols = ", ".join(s[0] for s in OUTCOME_BAR_SPECS)
                _vd_cols = ", ".join(s[2] for s in OUTCOME_MOVEMENT_V1_SPECS)
                unfilled = conn.execute(
                    f"""
                    SELECT snapshot_id, ts_utc, atr, {_odir_cols}, {_vd_cols}
                    FROM snapshots
                    WHERE ticker = ? AND timeframe = ?
                      AND outcome_filled = 0
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                      AND ts_utc < ? AND ts_utc > ?
                    ORDER BY ts_utc DESC
                    LIMIT ?
                    """,
                    (
                        tkr,
                        tf,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        tz,
                        min_snap_ts,
                        int(db.FILL_OUTCOMES_LIVE_BATCH_LIMIT),
                    ),
                ).fetchall()

                db._apply_bar_based_outcome_updates(
                    conn,
                    tz=tz,
                    unfilled_rows=unfilled,
                    bar_ends=bar_ends,
                    bar_end_closes=bar_end_closes,
                    close_by_start=close_by_start,
                )

        _t0 = _wall_time.perf_counter()
        _do()
        _exec_ms = (_wall_time.perf_counter() - _t0) * 1000.0
        _th = threading.current_thread().name
        _db_s = str(self.db_path)
        # Honest SLA: 5s+/10s+ remain WARNING (quiet-window FAIL). Perf fix is the
        # live batch + N+1 cut above — do not demote severity to greenwash 23s runs.
        _level, _tier = db._fill_outcomes_latency_log(_exec_ms)
        if _level is logging.WARNING:
            log.warning(
                "sqlite_bg_write_slow op=fill_outcomes tier=%s ticker=%s exec_ms=%.1f "
                "thread=%s db_path=%s",
                _tier,
                tkr,
                _exec_ms,
                _th,
                _db_s,
            )
        elif _level is logging.INFO:
            log.info(
                "sqlite_bg_write op=fill_outcomes ticker=%s exec_ms=%.1f thread=%s db_path=%s",
                tkr,
                _exec_ms,
                _th,
                _db_s,
            )

    def refresh_all_governed_bar_anchor_outcomes_v1(self) -> dict:
        """
        Recompute all BAR_ANCHOR_V1 / 1m snapshot horizon outcomes from current price_bars_1m.

        Use after bulk bar repairs or before governed-dataset certification when labels must
        match authoritative closes. Live upsert_1m_bars already refreshes affected snapshots.
        """
        import db  # module-attribute access only -- see this file's own docstring

        tz = float(_wall_time.time())
        _max_fwd_min = max(s[2] for s in OUTCOME_BAR_SPECS)
        _bar_start_upper = tz + float(_max_fwd_min) * 60.0 + 120.0
        audit: dict = {
            "schema": "refresh_all_governed_bar_anchor_outcomes_v1",
            "ts_eval_utc": tz,
            "updates_executed": 0,
            "tickers": [],
        }
        total_updates = 0
        with self._connect() as conn:
            tickers = [
                r[0]
                for r in conn.execute(
                    """
                    SELECT DISTINCT ticker FROM snapshots
                    WHERE timeframe = ?
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                    """,
                    (
                        CANONICAL_TIMEFRAME,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                    ),
                )
            ]
            for tkr in tickers:
                rows = conn.execute(
                    """
                    SELECT snapshot_id, ts_utc, atr FROM snapshots
                    WHERE ticker = ? AND timeframe = ?
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                      AND ts_utc < ?
                    """,
                    (
                        tkr,
                        CANONICAL_TIMEFRAME,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        tz,
                    ),
                ).fetchall()
                if not rows:
                    continue
                min_snap_ts = min(float(r["ts_utc"]) for r in rows)
                bar_low = min_snap_ts - 5000.0
                close_by_start: dict[float, float] = {}
                for r in conn.execute(
                    """
                    SELECT bar_start_ts_utc, close FROM price_bars_1m
                    WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
                    """,
                    (tkr, bar_low, _bar_start_upper),
                ).fetchall():
                    close_by_start[float(r["bar_start_ts_utc"])] = float(r["close"])
                bar_end_rows = conn.execute(
                    """
                    SELECT bar_end_ts_utc, close FROM price_bars_1m
                    WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
                    ORDER BY bar_end_ts_utc ASC
                    """,
                    (tkr, bar_low, tz),
                ).fetchall()
                bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
                bar_end_closes = [float(r["close"]) for r in bar_end_rows]
                n = db._apply_bar_based_outcome_updates(
                    conn,
                    tz=tz,
                    unfilled_rows=rows,
                    bar_ends=bar_ends,
                    bar_end_closes=bar_end_closes,
                    close_by_start=close_by_start,
                    force_refresh=True,
                )
                total_updates += n
                audit["tickers"].append({"ticker": tkr, "updates": n, "snapshots": len(rows)})
        audit["updates_executed"] = total_updates
        return audit

    def refresh_governed_outcomes_for_mutated_bar_starts(
        self,
        ticker: str,
        bar_start_ts_utc: set[float] | list[float],
        *,
        ts_eval_utc: float | None = None,
    ) -> int:
        """
        Recompute BAR_ANCHOR_V1 snapshot rows affected by 1m bars at the given starts.

        Call after any price_bars_1m write that does not go through upsert_1m_bars (e.g. repair SQL).
        """
        import db  # module-attribute access only -- see this file's own docstring

        tz = float(ts_eval_utc if ts_eval_utc is not None else _wall_time.time())
        tkr = ticker_storage_key(ticker)
        if not tkr:
            return 0
        changed = {float(x) for x in bar_start_ts_utc}
        if not changed:
            return 0
        with self._connect() as conn:
            n = db._refresh_governed_outcomes_after_bar_mutation(
                conn, tkr=tkr, changed_bar_starts=changed, tz=tz
            )
            conn.commit()
            return n

    def fill_outcomes_pin_neutral_backfill_v1(
        self,
        *,
        dry_run: bool = False,
    ) -> dict:
        """
        Repair outcomes for historical pin_neutral rows left unfilled because live
        fill_outcomes only considers snapshots in a rolling 14-day window.

        Same bar-anchor contract as fill_outcomes. Evaluation time is wall-clock now
        so forward horizons are complete when 1m bar history exists.

        Scope: zone='pin_neutral', outcome_filled=0, BAR_ANCHOR_V1, **canonical timeframe (1m) only**.
        Legacy ``timeframe='5m'`` rows are **excluded** (counted in ``legacy_timeframe_rows_excluded``)
        so repair does not extend labels into non-canonical snapshot metadata used by Issue 19.
        Labeling still uses ``price_bars_1m`` (same bar grid as ``fill_outcomes``).
        """
        import db  # module-attribute access only -- see this file's own docstring

        tz = float(_wall_time.time())
        _max_fwd_min = max(s[2] for s in OUTCOME_BAR_SPECS)
        bar_pad = float(_max_fwd_min) * 60.0 + 120.0
        audit: dict = {
            "schema": "pin_neutral_outcome_repair_v1",
            "dry_run": dry_run,
            "ts_eval_utc": tz,
            "timeframes_in_scope": [CANONICAL_TIMEFRAME],
            "legacy_timeframe_rows_excluded": 0,
            "updates_executed": 0,
            "tickers_touched": [],
            "snapshots_scanned": 0,
        }

        def _do() -> None:
            with self._connect() as conn:
                leg = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM snapshots
                    WHERE zone = 'pin_neutral'
                      AND outcome_filled = 0
                      AND timeframe = ?
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                    """,
                    (
                        DERIVED_TIMEFRAME,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                    ),
                ).fetchone()
                # CAPS finding (2026-09-22): COUNT(*) with no GROUP BY always returns exactly
                # one row -- `if leg else 0` was dead, same class as RC-573's fix.
                audit["legacy_timeframe_rows_excluded"] = int(leg["n"])
                if audit["legacy_timeframe_rows_excluded"]:
                    log.info(
                        "fill_outcomes_pin_neutral_backfill_v1: excluding %s legacy %s pin_neutral rows "
                        "(canonical repair is 1m-only)",
                        audit["legacy_timeframe_rows_excluded"],
                        DERIVED_TIMEFRAME,
                    )
                rows = conn.execute(
                    """
                    SELECT ticker, snapshot_id, ts_utc, atr
                    FROM snapshots
                    WHERE zone = 'pin_neutral'
                      AND outcome_filled = 0
                      AND timeframe = ?
                      AND COALESCE(horizon_outcome_schema_version, ?) = ?
                    ORDER BY ticker, ts_utc
                    """,
                    (
                        CANONICAL_TIMEFRAME,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                        HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                    ),
                ).fetchall()
                audit["snapshots_scanned"] = len(rows)
                by_ticker: dict[str, list] = {}
                for r in rows:
                    tkr_row = r["ticker"]
                    by_ticker.setdefault(tkr_row, []).append(r)

                total_updates = 0
                tickers_touched: list[str] = []
                for tkr_raw, trows in sorted(by_ticker.items()):
                    t_key = ticker_storage_key(tkr_raw)
                    min_ts = min(float(x["ts_utc"]) for x in trows)
                    bar_low = min_ts - 120.0 * 86400.0
                    bar_high = tz + bar_pad

                    close_by_start: dict[float, float] = {}
                    for r in conn.execute(
                        """
                        SELECT bar_start_ts_utc, close FROM price_bars_1m
                        WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
                        """,
                        (t_key, bar_low, bar_high),
                    ).fetchall():
                        close_by_start[float(r["bar_start_ts_utc"])] = float(r["close"])

                    bar_end_rows = conn.execute(
                        """
                        SELECT bar_end_ts_utc, close FROM price_bars_1m
                        WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
                        ORDER BY bar_end_ts_utc ASC
                        """,
                        (t_key, bar_low, tz),
                    ).fetchall()
                    bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
                    bar_end_closes = [float(r["close"]) for r in bar_end_rows]

                    if dry_run:
                        tickers_touched.append(t_key)
                        continue
                    n = db._apply_bar_based_outcome_updates(
                        conn,
                        tz=tz,
                        unfilled_rows=trows,
                        bar_ends=bar_ends,
                        bar_end_closes=bar_end_closes,
                        close_by_start=close_by_start,
                    )
                    total_updates += n
                    if n:
                        tickers_touched.append(t_key)

                audit["updates_executed"] = total_updates
                audit["tickers_touched"] = sorted(set(tickers_touched))

        _do()
        return audit

    def get_recent_snapshots(
        self,
        ticker: str,
        timeframe: str,
        n: int = 5000,
        filled_only: bool = False,
        *,
        as_of_ts_utc: Optional[float] = None,
    ) -> list:
        """Return the N most recent snapshots for a ticker/timeframe (DESC by ts_utc).

        as_of_ts_utc: when set (replay / causal inference), only rows with ts_utc < as_of_ts_utc
        are eligible — same strict ordering contract as get_similar_setups. Default None preserves
        legacy unbounded history reads (training/offline tools must pass explicitly when simulating
        a decision at time T).
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.get_recent_snapshots")
        ticker = ticker_storage_key(ticker)
        filled_clause = "AND outcome_filled = 1" if filled_only else ""  # caps-ok: filled_only is a real required bool parameter, not a possibly-absent value
        asof_clause = " AND ts_utc < ? " if as_of_ts_utc is not None else ""
        params: tuple = (ticker, timeframe)
        if as_of_ts_utc is not None:
            params = params + (float(as_of_ts_utc),)
        params = params + (n,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM snapshots
                WHERE ticker = ? AND timeframe = ?
                {filled_clause}
                {asof_clause}
                ORDER BY ts_utc DESC
                LIMIT ?
            """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_iv_levels(
        self,
        ticker: str,
        timeframe: str,
        n: int = 5000,
        *,
        as_of_ts_utc: Optional[float] = None,
    ) -> list:
        """iv_level column of the N most recent snapshots (DESC by ts_utc).

        Narrow projection twin of get_recent_snapshots for the live IV rank /
        percentile path (burndown 2026-07-05): the hot loop pulled 5,000
        FULL-WIDTH rows (200+ columns including the option_chain_json /
        replay_context_json blobs) per tick per ticker and read exactly one
        float from each — py-spy attributed 1,258 of 3,062 samples to that
        read. Same row window, ordering, and as-of visibility as
        get_recent_snapshots(filled_only=False); only the projection narrows,
        so consumer-visible iv_level values are identical.
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.get_recent_iv_levels")
        ticker = ticker_storage_key(ticker)
        asof_clause = " AND ts_utc < ? " if as_of_ts_utc is not None else ""
        params: tuple = (ticker, timeframe)
        if as_of_ts_utc is not None:
            params = params + (float(as_of_ts_utc),)
        params = params + (n,)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT iv_level FROM snapshots
                WHERE ticker = ? AND timeframe = ?
                {asof_clause}
                ORDER BY ts_utc DESC
                LIMIT ?
            """,
                params,
            ).fetchall()
        return [r["iv_level"] for r in rows]

    def get_similar_setups(self, ticker: str, timeframe: str,
                            zone: Optional[str], vwap_side: Optional[str],
                            nearest_above_dist: Optional[float],
                            nearest_below_dist: Optional[float],
                            n_similar: int = 500,
                            *,
                            return_trace: bool = False,
                            as_of_ts_utc: Optional[float] = None,
                            exclude_heavy_json_columns: bool = False) -> list | tuple[list, dict]:
        """
        Find historical snapshots similar to current setup.
        Uses PROGRESSIVE RELAXATION — tries tight match first, then
        loosens criteria until empirical viability is met (Issue 19), or tier 5 is reached.

        Tiers (Issue 19 — stop at the **narrowest** tier where **SIMILARITY_TIER_STOP_OUTCOME_COLUMNS**
        (1c / 5c / 15c) each have >= MIN_SAMPLES_STATISTICAL labeled rows — aligned with
        multi_horizon_decision primary candidates except sparse 60c; same bar as
        prediction_engine._literal_empirical_horizon for those columns):
          1. zone + vwap_side + both distance buckets  (tightest)
          2. zone + vwap_side + above distance bucket only
          3. zone + vwap_side  (drop all distance criteria)
          4. zone only  (drop vwap_side)
          5. all filled snapshots for this ticker  (broadest; always returned if reached)

        SQL still requires outcome_1c IS NOT NULL for pool membership; tier-stop viability uses
        SIMILARITY_TIER_STOP_OUTCOME_COLUMNS. Auxiliary horizons (3c/8c/13c/60c) may still be
        withheld per _literal_empirical_horizon without broadening the match tier.

        Returns: list of snapshot dicts, plus a 'match_tier' key on each
        indicating which tier matched (1=tightest, 5=broadest).

        If return_trace is True, returns (rows, trace_dict) for verification only;
        default False preserves the original single-list return type.

        as_of_ts_utc: when set (e.g. replay), only rows with ts_utc < as_of_ts_utc are
        considered. Default None is identical to historical behavior (all history visible).
        Production callers do not pass this.

        exclude_heavy_json_columns (burndown 2026-07-05): opt-in projection that
        drops option_chain_json / replay_context_json from the SELECT. The live
        similarity consumers (fusion overlay, prediction core, enrichment,
        similarity_labeled_counts) read only outcome_*, outcome_*_pts, ts_utc,
        and match_tier — enumerated end-to-end before this landed — while the
        two blobs dominate row width. Default False is byte-identical for every
        other caller (audit / replay / verification tools keep full rows).
        """
        import db  # module-attribute access only -- see this file's own docstring

        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.get_similar_setups")
        ticker = ticker_storage_key(ticker)
        # Issue 19 / production similarity: canonical 1m snapshot rows only — no 5m legacy pool mixing.
        if timeframe != CANONICAL_TIMEFRAME:
            log.warning(
                "get_similar_setups: timeframe=%r is not canonical %r — Issue 19 similarity is "
                "1m-only; returning empty similar set (legacy timeframes excluded by policy).",
                timeframe,
                CANONICAL_TIMEFRAME,
            )
            if return_trace:
                return [], {
                    "trace_schema": "similarity_trace_issue21_v1",
                    "rejected": True,
                    "reject_reason": "non_canonical_timeframe_for_issue19",
                    "requested_timeframe": timeframe,
                    "canonical_timeframe": CANONICAL_TIMEFRAME,
                    "ticker": ticker,
                    "zone": zone,
                    "vwap_side": vwap_side,
                    "final_similar_count": 0,
                    "tiers": [],
                }
            return []

        above_bucket = _dist_bucket(nearest_above_dist)
        below_bucket = _dist_bucket(nearest_below_dist)
        _asof_sql = "" if as_of_ts_utc is None else " AND ts_utc < ? "

        _query_ctx: Optional[dict] = None
        trace: Optional[dict] = None
        if return_trace:
            _query_ctx = query_context_for_similarity(
                ticker=ticker,
                timeframe=timeframe,
                zone=zone,
                vwap_side=vwap_side,
                nearest_above_dist=nearest_above_dist,
                nearest_below_dist=nearest_below_dist,
                n_similar=n_similar,
                as_of_ts_utc=as_of_ts_utc,
            )
            trace = {
                "trace_schema": "similarity_trace_issue21_v1",
                "ticker": ticker,
                "timeframe": timeframe,
                "zone": zone,
                "vwap_side": vwap_side,
                "nearest_above_dist": nearest_above_dist,
                "nearest_below_dist": nearest_below_dist,
                "query_context": _query_ctx,
                "MIN_SAMPLES_STATISTICAL": MIN_SAMPLES_STATISTICAL,
                "empirical_outcome_columns": list(SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS),
                "tier_stop_outcome_columns": list(SIMILARITY_TIER_STOP_OUTCOME_COLUMNS),
                "LIMIT": n_similar,
                "as_of_ts_utc": as_of_ts_utc,
                "note": (
                    "Session/regime are NOT SQL filters here; narrowing is tier 1–5 only. "
                    "All tiers require outcome_1c IS NOT NULL for SQL pool membership. "
                    "Tiers 1–4 stop when SIMILARITY_TIER_STOP_OUTCOME_COLUMNS (1c/5c/15c) "
                    f"each have ≥{MIN_SAMPLES_STATISTICAL} labeled rows."
                ),
                "tiers": [],
            }

        def _finish(rows_raw, tier_num: int, *, stop_reason: str):
            out = [dict(r) for r in rows_raw]
            if return_trace and trace is not None:
                trace["chosen_tier"] = tier_num
                trace["final_similar_count"] = len(out)
                trace["final_labeled_counts"] = db.similarity_labeled_counts(out)
                fc = trace["final_labeled_counts"]
                ftsv = db.similarity_tier_stop_viable(fc)
                fatv = db.similarity_empirically_viable(fc)
                trace["final_empirically_viable"] = ftsv
                trace["final_all_tracked_viable"] = fatv
                trace["final_selected_tier"] = tier_num
                trace["final_selected_row_count"] = len(out)
                trace["final_selected_labeled_counts"] = dict(fc)
                trace["final_tier_stop_viable"] = ftsv
                trace["stop_reason"] = stop_reason
                trace["withheld_horizons"] = withheld_horizons_report(fc)
                trace["tier_stop_weak_horizons"] = tier_stop_weak_horizons(fc)
                trace["weakest_tracked_horizons"] = weakest_tracked_horizons(fc)
                # CAPS finding (2026-09-22): trace's own literal construction above always
                # includes "tiers": [] whenever trace is not None -- `.get(..., [])` was dead.
                trace["widening_analysis"] = widening_summary_from_tiers(
                    trace["tiers"], tier_num
                )
                return out, trace
            return out

        def _append_tier(
            tier_num: int,
            nrows: int,
            selected: bool,
            *,
            counts: Optional[dict[str, int]] = None,
            stop_reason: Optional[str] = None,
        ):
            if trace is not None and _query_ctx is not None:
                c = dict(counts or {})
                # CAPS finding (2026-09-22): both functions already guard `if not
                # labeled_by_col: return False` internally -- the `if c else False` wrapper
                # was fully redundant, never changed the result.
                tsv = db.similarity_tier_stop_viable(c)
                atv = db.similarity_empirically_viable(c)
                entry: dict = {
                    "tier": tier_num,
                    "constraint_definition": structured_constraints_for_tier(tier_num, _query_ctx),
                    "relaxed_vs_previous_tier": relaxed_constraints_vs_previous_tier(tier_num),
                    "row_count_after_query_limit": nrows,
                    "selected": selected,
                    "labeled_counts": c,
                    "tier_stop_viable": tsv,
                    "empirically_viable": tsv,
                    "all_tracked_viable": atv,
                }
                if stop_reason:
                    entry["stop_reason"] = stop_reason
                trace["tiers"].append(entry)

        def _maybe_return_tier(rows_raw, tier_num: int):
            """Return this tier if it satisfies full empirical viability; else record trace and continue."""
            out_dicts = [dict(r) for r in rows_raw]
            counts = db.similarity_labeled_counts(out_dicts)
            viable = db.similarity_tier_stop_viable(counts)
            _append_tier(tier_num, len(rows_raw), viable, counts=counts)
            if viable:
                log.debug(
                    "get_similar_setups %s/%s zone=%s vwap_side=%s: tier %s ACCEPT "
                    "(n=%s labeled_counts=%s min=%s)",
                    ticker,
                    timeframe,
                    zone,
                    vwap_side,
                    tier_num,
                    len(out_dicts),
                    counts,
                    MIN_SAMPLES_STATISTICAL,
                )
                return _finish(rows_raw, tier_num, stop_reason="tier_stop_satisfied")
            log.debug(
                "get_similar_setups %s/%s: tier %s not empirically viable (n=%s counts=%s need %s each) — widening",
                ticker,
                timeframe,
                tier_num,
                len(out_dicts),
                counts,
                MIN_SAMPLES_STATISTICAL,
            )
            return None

        # When canonical zone/vwap are withheld, do not SQL-match fabricated sentinels.
        if zone is None:
            _start_tier = 5
        elif vwap_side is None:
            _start_tier = 4
        else:
            _start_tier = 1

        with self._connect() as conn:
            _sel = "*"
            if exclude_heavy_json_columns:
                _all_cols = [
                    r["name"] for r in conn.execute("PRAGMA table_info(snapshots)")
                ]
                _sel = ", ".join(
                    c for c in _all_cols
                    if c not in ("option_chain_json", "replay_context_json")
                )

            if _start_tier <= 1:
                # ── Tier 1: zone + vwap_side + both distance buckets ──────────
                _p1 = (
                    ticker, timeframe, zone, vwap_side,
                    nearest_above_dist,
                    _bucket_lo(above_bucket), _bucket_hi(above_bucket),
                    nearest_below_dist,
                    _bucket_lo(below_bucket), _bucket_hi(below_bucket),
                )
                if as_of_ts_utc is not None:
                    _p1 = _p1 + (as_of_ts_utc, n_similar)
                else:
                    _p1 = _p1 + (n_similar,)
                rows = conn.execute(f"""
                    SELECT {_sel}, 1 as match_tier FROM snapshots
                    WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?
                      AND outcome_1c IS NOT NULL
                      AND (
                        (nearest_above_dist IS NULL AND ? IS NULL)
                        OR (nearest_above_dist BETWEEN ? AND ?)
                      )
                      AND (
                        (nearest_below_dist IS NULL AND ? IS NULL)
                        OR (nearest_below_dist BETWEEN ? AND ?)
                      )
                    """ + _asof_sql + """
                    ORDER BY ts_utc DESC LIMIT ?
                """, _p1).fetchall()

                done = _maybe_return_tier(rows, 1)
                if done is not None:
                    return done

                # ── Tier 2: zone + vwap_side + above distance only ────────────
                _p2 = (
                    ticker, timeframe, zone, vwap_side,
                    nearest_above_dist,
                    _bucket_lo(above_bucket), _bucket_hi(above_bucket),
                )
                if as_of_ts_utc is not None:
                    _p2 = _p2 + (as_of_ts_utc, n_similar)
                else:
                    _p2 = _p2 + (n_similar,)
                rows = conn.execute(f"""
                    SELECT {_sel}, 2 as match_tier FROM snapshots
                    WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?
                      AND outcome_1c IS NOT NULL
                      AND (
                        (nearest_above_dist IS NULL AND ? IS NULL)
                        OR (nearest_above_dist BETWEEN ? AND ?)
                      )
                    """ + _asof_sql + """
                    ORDER BY ts_utc DESC LIMIT ?
                """, _p2).fetchall()

                done = _maybe_return_tier(rows, 2)
                if done is not None:
                    return done

                # ── Tier 3: zone + vwap_side only ─────────────────────────────
                _p3 = (ticker, timeframe, zone, vwap_side)
                if as_of_ts_utc is not None:
                    _p3 = _p3 + (as_of_ts_utc, n_similar)
                else:
                    _p3 = _p3 + (n_similar,)
                rows = conn.execute(f"""
                    SELECT {_sel}, 3 as match_tier FROM snapshots
                    WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?
                      AND outcome_1c IS NOT NULL
                    """ + _asof_sql + """
                    ORDER BY ts_utc DESC LIMIT ?
                """, _p3).fetchall()

                done = _maybe_return_tier(rows, 3)
                if done is not None:
                    return done

            if _start_tier <= 4:
                # ── Tier 4: zone only ─────────────────────────────────────────
                _p4 = (ticker, timeframe, zone)
                if as_of_ts_utc is not None:
                    _p4 = _p4 + (as_of_ts_utc, n_similar)
                else:
                    _p4 = _p4 + (n_similar,)
                rows = conn.execute(f"""
                    SELECT {_sel}, 4 as match_tier FROM snapshots
                    WHERE ticker = ? AND timeframe = ? AND zone = ?
                      AND outcome_1c IS NOT NULL
                    """ + _asof_sql + """
                    ORDER BY ts_utc DESC LIMIT ?
                """, _p4).fetchall()

                done = _maybe_return_tier(rows, 4)
                if done is not None:
                    return done

            # ── Tier 5: all filled snapshots for this ticker ──────────────
            _p5 = (ticker, timeframe)
            if as_of_ts_utc is not None:
                _p5 = _p5 + (as_of_ts_utc, n_similar)
            else:
                _p5 = _p5 + (n_similar,)
            rows = conn.execute(f"""
                SELECT {_sel}, 5 as match_tier FROM snapshots
                WHERE ticker = ? AND timeframe = ?
                  AND outcome_1c IS NOT NULL
                """ + _asof_sql + """
                ORDER BY ts_utc DESC LIMIT ?
            """, _p5).fetchall()

            out5 = [dict(r) for r in rows]
            c5 = db.similarity_labeled_counts(out5)
            v5 = db.similarity_tier_stop_viable(c5)
            _append_tier(
                5,
                len(rows),
                True,
                counts=c5,
                stop_reason="max_tier_broadest_pool",
            )
            if trace is not None:
                trace["tier5_empirically_viable"] = v5
                trace["tier5_all_tracked_viable"] = db.similarity_empirically_viable(c5)
                if not v5:
                    trace["tier5_note"] = (
                        "Tier-stop columns (1c/5c/15c) may still be sparse; "
                        "or auxiliary horizons may be withheld per horizon where "
                        f"labeled count < {MIN_SAMPLES_STATISTICAL}."
                    )
            return _finish(rows, 5, stop_reason="max_tier_broadest_pool_forced")

    def snapshot_exists_in_minute(self, ticker: str, timeframe: str, minute_bucket: int) -> bool:
        """True when a snapshot row already exists for (ticker, timeframe) in the
        given UTC minute bucket (int(ts_utc // 60)).

        Repo-wide audit 2026-07-05: durable half of the 1-insert/ticker/minute
        throttle (server._snapshot_row_insert_allowed). The in-process bucket
        cannot survive restarts and raced concurrent callers — 4,783 duplicate
        (ticker, minute) groups accumulated on disk. Uses idx_snap_ticker_tf_ts
        (~0.06ms measured). Ticker is matched EXACTLY as insert_snapshot writes
        it (no storage-key normalization) so probe and write key identically.
        """
        lo = float(minute_bucket) * 60.0
        with self._connect() as conn:
            r = conn.execute(
                "SELECT 1 FROM snapshots WHERE ticker = ? AND timeframe = ?"
                " AND ts_utc >= ? AND ts_utc < ? LIMIT 1",
                (ticker, timeframe, lo, lo + 60.0),
            ).fetchone()
        return r is not None

    def count_snapshots(self, ticker: str, timeframe: str) -> dict:
        """Return snapshot counts for UI display.

        'filled' = has at least outcome_1c populated (usable for prediction).
        outcome_filled=1 means every column in OUTCOME_BAR_SPECS is populated
        (db backfill “complete” for that row). ML training uses per-horizon
        IS NOT NULL, not outcome_filled (Issue 14).
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.count_snapshots")
        ticker = ticker_storage_key(ticker)
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=?",
                (ticker, timeframe)
            ).fetchone()[0]
            filled = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=? AND outcome_1c IS NOT NULL",
                (ticker, timeframe)
            ).fetchone()[0]
        return {"total": total, "filled": filled, "pending": total - filled}

    def get_avg_move(self, ticker: str, timeframe: str,
                      zone: str, vwap_side: str,
                      nearest_above_dist: Optional[float],
                      nearest_below_dist: Optional[float],
                      *,
                      as_of_ts_utc: Optional[float] = None) -> dict:
        """
        Return avg and median point move for similar setups.
        Used by 'What the Data Says' to show WHERE price typically goes,
        not just direction probability.

        as_of_ts_utc: when set, only rows with ts_utc < as_of_ts_utc (same contract as get_similar_setups).

        Non-canonical timeframes return empty stats (same policy as get_similar_setups / Issue 19).

        Returns:
          avg_1c_pts   : average move over next 1 candle (signed, +up/-down)
          avg_5c_pts   : average move over next 5 candles (product 5m clock)
          median_1c_pts: median move
          median_5c_pts: median over 5c window
          n            : sample count used
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.get_avg_move")
        if timeframe != CANONICAL_TIMEFRAME:
            log.warning(
                "get_avg_move: timeframe=%r is not canonical %r — returning empty stats (Issue 19).",
                timeframe,
                CANONICAL_TIMEFRAME,
            )
            return {
                "avg_1c_pts": None,
                "avg_5c_pts": None,
                "median_1c_pts": None,
                "median_5c_pts": None,
                "n": 0,
                "reject_reason": "non_canonical_timeframe",
            }
        ticker = ticker_storage_key(ticker)
        above_bucket = _dist_bucket(nearest_above_dist)
        below_bucket = _dist_bucket(nearest_below_dist)
        _asof_sql = "" if as_of_ts_utc is None else " AND ts_utc < ? "

        with self._connect() as conn:
            _params = (
                ticker, timeframe, zone, vwap_side,
                nearest_above_dist,
                _bucket_lo(above_bucket), _bucket_hi(above_bucket),
                nearest_below_dist,
                _bucket_lo(below_bucket), _bucket_hi(below_bucket),
            )
            if as_of_ts_utc is not None:
                _params = _params + (as_of_ts_utc,)
            rows = conn.execute(f"""
                SELECT outcome_1c_pts, outcome_5c_pts
                FROM snapshots
                WHERE ticker = ?
                  AND timeframe = ?
                  AND zone = ?
                  AND vwap_side = ?
                  AND outcome_1c_pts IS NOT NULL
                  AND (
                    (nearest_above_dist IS NULL AND ? IS NULL)
                    OR (nearest_above_dist BETWEEN ? AND ?)
                  )
                  AND (
                    (nearest_below_dist IS NULL AND ? IS NULL)
                    OR (nearest_below_dist BETWEEN ? AND ?)
                  )
                  {_asof_sql}
                ORDER BY ts_utc DESC
                LIMIT 500
            """, _params).fetchall()

        if not rows:
            return {"avg_1c_pts": None, "avg_5c_pts": None,
                    "median_1c_pts": None, "median_5c_pts": None, "n": 0}

        pts1 = [r["outcome_1c_pts"] for r in rows if r["outcome_1c_pts"] is not None]
        pts5 = [r["outcome_5c_pts"] for r in rows if r["outcome_5c_pts"] is not None]

        def _avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else None

        def _median(lst):
            if not lst: return None
            s = sorted(lst)
            n = len(s)
            return round(s[n // 2] if n % 2 else (s[n//2 - 1] + s[n//2]) / 2, 2)

        return {
            "avg_1c_pts":    _avg(pts1),
            "avg_5c_pts":    _avg(pts5),
            "median_1c_pts": _median(pts1),
            "median_5c_pts": _median(pts5),
            "n":             len(pts1),
        }
